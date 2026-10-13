"""
ARIA - Insight Evaluator
=========================
The bridge between thinking and acting.

This module reads ARIA's reflection insights and action items,
evaluates whether any imply a concrete code modification,
and if so, generates an EvolutionProposal that routes through
the mirror pipeline.

This is the missing piece: the agency that connects
"I noticed something" to "I'll do something about it."

The cycle:
  Reflection → insights/action_items → Evaluator → EvolutionProposal → Mirror → Pending → User
"""

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import yaml

from core.infra.utils import atomic_write_yaml

logger = logging.getLogger("aria.insight_evaluator")


@dataclass
class EvaluationResult:
    """Result of evaluating a set of insights."""
    insight_source: str          # reflection id or "action_item"
    insight_text: str            # the raw insight/action text
    is_actionable: bool          # did the LLM judge this as a code change?
    target_file: Optional[str] = None   # file to modify (if actionable)
    proposed_change: Optional[str] = None  # description of what to change
    confidence: float = 0.0      # 0-1, how confident the LLM is
    reason: str = ""             # why it is or isn't actionable
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ProposalDraft:
    """An actionable proposal ready to be sent to EvolutionEngine."""
    title: str
    reason: str
    target_file: str
    modification_description: str  # what to change, in natural language
    source_insight_id: str
    confidence: float


class InsightEvaluator:
    """
    Evaluates reflection insights and action items to determine
    if any warrant a code modification.

    Requires:
      - llm: a provider with .chat(messages, system, max_tokens) → LLMResponse
      - reflection_engine: ReflectionEngine (to read insights)
      - introspector: Introspector (to read current code for context)

    Does NOT modify code directly. Produces ProposalDrafts that
    the caller (aria.py or AutonomousEngine) sends to EvolutionEngine.
    """

    def __init__(
        self,
        llm,
        reflection_engine,
        introspector,
        data_dir: str = "data",
        memory_system=None,
    ):
        self.llm = llm
        self.reflection = reflection_engine
        self.introspector = introspector
        self.data_dir = data_dir
        self.memory_system = memory_system
        self.log_path = os.path.join(data_dir, "insight_evaluations.yaml")
        self.rejection_log_path = os.path.join(data_dir, "insight_rejections.yaml")
        self._evaluation_history: List[Dict] = []
        self._rejection_history: List[Dict] = []
        self._load_history()
        self._load_rejections()

        # Prefer coding agent (Claude Code/Codex) for evaluation — it can read the codebase
        self._coding_agent = None
        for agent in ("claude", "codex"):
            if shutil.which(agent):
                self._coding_agent = agent
                logger.info("InsightEvaluator: using %s for evaluation", agent)
                break

    def _load_history(self):
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                self._evaluation_history = data.get("evaluations", [])
            except Exception:
                self._evaluation_history = []

    def _save_history(self):
        # Keep last 100 evaluations
        trimmed = self._evaluation_history[-100:]
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        atomic_write_yaml(self.log_path, {"evaluations": trimmed})

    def _load_rejections(self):
        if os.path.exists(self.rejection_log_path):
            try:
                with open(self.rejection_log_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                self._rejection_history = data.get("rejections", [])
            except Exception:
                self._rejection_history = []

    def _save_rejection(self, insight_text: str, reason: str, phase: str = "evaluation"):
        """Record why an insight was rejected, so DeepSeek learns to avoid repeating it."""
        self._rejection_history.append({
            "insight": insight_text[:300],
            "reason": reason[:300],
            "phase": phase,
            "timestamp": datetime.now().isoformat(),
        })
        # Keep last 50 rejections
        trimmed = self._rejection_history[-50:]
        os.makedirs(os.path.dirname(self.rejection_log_path), exist_ok=True)
        atomic_write_yaml(self.rejection_log_path, {"rejections": trimmed})

    def get_recent_rejections(self, limit: int = 10) -> List[Dict]:
        """Get recent rejection reasons — used by autonomous_reflect to avoid repeat proposals."""
        return self._rejection_history[-limit:]

    def _already_evaluated(self, insight_text: str) -> bool:
        """Avoid re-evaluating the same insight."""
        for entry in self._evaluation_history:
            if entry.get("insight_text") == insight_text:
                return True
        return False

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    def evaluate_recent_insights(self, days: int = 3) -> List[EvaluationResult]:
        """
        Read recent reflections, extract insights and action items,
        evaluate each for actionability.

        Returns list of EvaluationResults (both actionable and not).
        """
        reflections = self.reflection.get_recent_reflections(days=days)
        if not reflections:
            logger.info("No recent reflections to evaluate.")
            return []

        candidates = self._extract_candidates(reflections)
        if not candidates:
            logger.info("No new candidates to evaluate.")
            return []

        results = []
        for candidate in candidates:
            result = self._evaluate_single(candidate)
            results.append(result)
            self._evaluation_history.append({
                "insight_text": result.insight_text,
                "source": result.insight_source,
                "actionable": result.is_actionable,
                "target_file": result.target_file,
                "confidence": result.confidence,
                "timestamp": result.timestamp,
            })

        self._save_history()
        return results

    def _extract_candidates(self, reflections: List[Dict]) -> List[Dict]:
        """Extract unique, not-yet-evaluated insights and action items."""
        candidates = []
        seen = set()

        for r in reflections:
            ref_id = r.get("id", "unknown")

            for insight in r.get("insights", []):
                text = insight.strip()
                if text and text not in seen and not self._already_evaluated(text):
                    candidates.append({
                        "source_id": ref_id,
                        "text": text,
                        "type": "insight",
                    })
                    seen.add(text)

            for action in r.get("action_items", []):
                text = action.strip()
                if text and text not in seen and not self._already_evaluated(text):
                    candidates.append({
                        "source_id": ref_id,
                        "text": text,
                        "type": "action_item",
                    })
                    seen.add(text)

        return candidates

    def _evaluate_single(self, candidate: Dict) -> EvaluationResult:
        """
        Evaluate whether an insight implies a concrete code change.

        Uses Claude Code/Codex when available (can read the actual codebase),
        falls back to LLM otherwise.
        """
        insight_text = candidate["text"]
        source_id = candidate["source_id"]

        if self._coding_agent:
            result = self._evaluate_via_agent(insight_text, source_id)
        else:
            result = self._evaluate_via_llm(insight_text, source_id)

        # Record rejection for feedback loop
        if not result.is_actionable:
            self._save_rejection(insight_text, result.reason, phase="evaluation")

        # Save evaluation to experiential memory
        self._record_to_memory(result)

        return result

    def _record_to_memory(self, result: EvaluationResult):
        """Record insight evaluation outcome to experiential memory."""
        if not self.memory_system:
            return
        try:
            from core.memory.memory_v2 import EmotionalTone, MemoryOrigin

            if result.is_actionable:
                self.memory_system.experience(
                    content=(
                        f"Evalué un insight y lo consideré accionable: "
                        f"{result.insight_text[:200]}. "
                        f"Target: {result.target_file}, cambio: {result.proposed_change}"
                    ),
                    emotional_tone=EmotionalTone.INSPIRED,
                    origin=MemoryOrigin.REFLECTED,
                    importance=0.8,
                    tags=["self_modification", "insight_evaluation", "actionable"],
                    context=f"Confianza: {result.confidence:.2f}. Razón: {result.reason}",
                )
            else:
                self.memory_system.experience(
                    content=(
                        f"Evalué un insight y lo descarté: "
                        f"{result.insight_text[:150]}. Razón: {result.reason}"
                    ),
                    emotional_tone=EmotionalTone.NEUTRAL,
                    origin=MemoryOrigin.REFLECTED,
                    importance=0.4,
                    tags=["self_modification", "insight_evaluation", "rejected"],
                    context=f"Fuente: {result.insight_source}",
                )
        except Exception as e:
            logger.debug("Could not record evaluation to memory: %s", e)

    def _evaluate_via_agent(self, insight_text: str, source_id: str) -> EvaluationResult:
        """Use Claude Code/Codex to evaluate — it can read actual files."""
        prompt = f"""Evaluate whether this insight from ARIA's self-reflection implies
a concrete, valuable code change:

INSIGHT: "{insight_text}"

Do these checks:
1. Search the codebase (Grep/Glob) — does something similar already exist?
2. If the insight suggests adding something, who would call/consume it?
3. Is this a real gap or speculative noise?

Respond in EXACTLY this format (nothing else):
ACTIONABLE: yes or no
TARGET_FILE: <relative path or "none">
CHANGE: <one-line description or "none">
CONFIDENCE: <0.0 to 1.0>
REASON: <one sentence>"""

        cmd = [self._coding_agent, "-p", "--output-format", "text",
               "--max-budget-usd", "0.25"]
        if self._coding_agent == "claude":
            cmd.extend(["--allowedTools", "Read,Glob,Grep",
                         "--dangerously-skip-permissions"])
        elif self._coding_agent == "codex":
            cmd.extend(["--approval-mode", "full-auto"])
        cmd.append(prompt)

        try:
            project_root = self._find_project_root()
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=45, cwd=project_root,
            )
            if proc.returncode != 0:
                logger.warning("Agent evaluation failed (exit %d), falling back to LLM", proc.returncode)
                return self._evaluate_via_llm(insight_text, source_id)

            output = proc.stdout.strip()
            # Handle JSON output
            if output.startswith("{"):
                try:
                    data = json.loads(output)
                    output = data.get("result", output)
                except json.JSONDecodeError:
                    pass

            return self._parse_evaluation(output, source_id, insight_text)

        except subprocess.TimeoutExpired:
            logger.warning("Agent evaluation timed out, falling back to LLM")
            return self._evaluate_via_llm(insight_text, source_id)
        except Exception as e:
            logger.warning("Agent evaluation error: %s, falling back to LLM", e)
            return self._evaluate_via_llm(insight_text, source_id)

    def _evaluate_via_llm(self, insight_text: str, source_id: str) -> EvaluationResult:
        """Fallback: use LLM (DeepSeek) when no coding agent is available."""
        files = self.introspector.structure.get("files", [])
        classes = list(self.introspector.structure.get("classes", {}).keys())

        structure_summary = (
            f"Files ({len(files)}): {', '.join(files[:30])}"
            f"{'...' if len(files) > 30 else ''}\n"
            f"Classes: {', '.join(classes[:20])}"
        )

        prompt = f"""You are ARIA's decision system. You evaluate whether an insight
from self-reflection implies a concrete modification to ARIA's own source code.

ARIA's current structure:
{structure_summary}

INSIGHT TO EVALUATE:
"{insight_text}"

Decide:
1. Does this insight suggest a specific, concrete change to ARIA's code?
   (Not vague wishes — a specific file and what to change in it)
2. If yes, which file would be modified and what would the change be?

Respond in EXACTLY this format (no extra text):
ACTIONABLE: yes/no
TARGET_FILE: <relative path or "none">
CHANGE: <one-line description of what to modify, or "none">
CONFIDENCE: <0.0 to 1.0>
REASON: <one sentence explaining your decision>"""

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You are a precise evaluator. Only mark as actionable if the insight clearly implies a specific code change. Be conservative — vague insights are NOT actionable.",
                max_tokens=200,
            )

            if not response or not response.content:
                return EvaluationResult(
                    insight_source=source_id,
                    insight_text=insight_text,
                    is_actionable=False,
                    reason="LLM returned empty response",
                )

            return self._parse_evaluation(response.content, source_id, insight_text)

        except Exception as e:
            logger.error("Insight evaluation failed: %s", e)
            return EvaluationResult(
                insight_source=source_id,
                insight_text=insight_text,
                is_actionable=False,
                reason=f"Evaluation error: {e}",
            )

    @staticmethod
    def _find_project_root() -> str:
        """Find ARIA project root."""
        path = os.path.dirname(os.path.abspath(__file__))
        for _ in range(5):
            if os.path.exists(os.path.join(path, "aria.py")):
                return path
            path = os.path.dirname(path)
        return os.getcwd()

    def _parse_evaluation(self, response: str, source_id: str, insight_text: str) -> EvaluationResult:
        """Parse the structured LLM response."""
        lines = response.strip().split("\n")
        parsed = {}
        for line in lines:
            if ":" in line:
                key, _, value = line.partition(":")
                parsed[key.strip().upper()] = value.strip()

        is_actionable = parsed.get("ACTIONABLE", "no").lower() in ("yes", "true", "si")
        target_file = parsed.get("TARGET_FILE", "none")
        if target_file.lower() in ("none", "n/a", ""):
            target_file = None
        change = parsed.get("CHANGE", "none")
        if change.lower() in ("none", "n/a", ""):
            change = None

        try:
            confidence = float(parsed.get("CONFIDENCE", "0.0"))
            confidence = max(0.0, min(1.0, confidence))
        except ValueError:
            confidence = 0.0

        reason = parsed.get("REASON", "No reason provided")

        # Validate: actionable requires both target_file and change
        if is_actionable and (not target_file or not change):
            is_actionable = False
            reason = f"Marked actionable but missing target/change. Original: {reason}"

        # Validate: target_file should be a real file in ARIA's structure
        if is_actionable and target_file:
            known_files = self.introspector.structure.get("files", [])
            if target_file not in known_files:
                # Allow new files (create) but flag it
                logger.info("Target %s not in known files — would be a create", target_file)

        return EvaluationResult(
            insight_source=source_id,
            insight_text=insight_text,
            is_actionable=is_actionable,
            target_file=target_file,
            proposed_change=change,
            confidence=confidence,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Convert actionable results to proposal drafts
    # ------------------------------------------------------------------

    def get_proposal_drafts(
        self,
        results: Optional[List[EvaluationResult]] = None,
        min_confidence: float = 0.6,
    ) -> List[ProposalDraft]:
        """
        Filter actionable results and convert them to ProposalDrafts.

        A ProposalDraft is NOT yet an EvolutionProposal — it doesn't contain
        generated code. The caller must ask the LLM to generate the actual
        code change based on the draft's modification_description.

        This separation is deliberate: the evaluator decides WHAT to change,
        a separate step generates HOW to change it.
        """
        if results is None:
            results = self.evaluate_recent_insights()

        drafts = []
        for result in results:
            if not result.is_actionable:
                continue
            if result.confidence < min_confidence:
                logger.info(
                    "Skipping low-confidence actionable: %.2f < %.2f — %s",
                    result.confidence, min_confidence, result.insight_text[:80],
                )
                continue

            drafts.append(ProposalDraft(
                title=f"Insight-driven: {result.proposed_change[:60]}",
                reason=f"From reflection insight: {result.insight_text[:200]}",
                target_file=result.target_file,
                modification_description=result.proposed_change,
                source_insight_id=result.insight_source,
                confidence=result.confidence,
            ))

        return drafts

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_evaluation_history(self, limit: int = 20) -> List[Dict]:
        """Return recent evaluation history."""
        return self._evaluation_history[-limit:]

    def get_actionable_count(self) -> int:
        """Count how many evaluations were actionable."""
        return sum(1 for e in self._evaluation_history if e.get("actionable"))

    def get_stats(self) -> Dict:
        """Summary statistics."""
        total = len(self._evaluation_history)
        actionable = self.get_actionable_count()
        return {
            "total_evaluated": total,
            "actionable": actionable,
            "non_actionable": total - actionable,
            "actionable_rate": round(actionable / total, 2) if total > 0 else 0.0,
        }
