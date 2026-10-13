"""
ARIA - Cognitive Cycle Orchestrator
=====================================
Connects reflection → evaluation → code generation → mirror pending.

This is the orchestrator that closes the loop between ARIA's thinking
and ARIA's ability to modify herself. It NEVER auto-approves anything.
Every modification ends at validated_pending_approval, waiting for
the human to approve or reject via the Review Panel.

The cycle:
  1. Reflection produces insights and action items
  2. InsightEvaluator decides which are actionable code changes
  3. This orchestrator asks the LLM to generate the actual code
  4. EvolutionEngine validates via mirror and stores as pending
  5. STOP — human decides

This module does NOT:
  - Approve or promote changes
  - Bypass the mirror pipeline
  - Execute without human oversight
  - Run unsupervised (must be triggered explicitly or by autonomous callback)
"""

import ast
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
from .insight_evaluator import InsightEvaluator, ProposalDraft, EvaluationResult
from .quality_gate import QualityGate, QualityReport, PreEvalReport

logger = logging.getLogger("aria.cognitive_cycle")


@dataclass
class CycleResult:
    """Result of one cognitive cycle run."""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    insights_evaluated: int = 0
    actionable_found: int = 0
    proposals_generated: int = 0
    proposals_pending: int = 0       # successfully reached mirror pending
    proposals_failed: int = 0        # failed validation in mirror
    quality_rejected: int = 0        # passed mirror but rejected by quality gate
    pre_eval_rejected: int = 0       # rejected before code generation
    merged_to_develop: int = 0       # successfully merged to develop branch
    errors: List[str] = field(default_factory=list)
    details: List[Dict] = field(default_factory=list)

    @property
    def had_activity(self) -> bool:
        return self.actionable_found > 0

    def summary(self) -> str:
        lines = [f"Cognitive cycle at {self.timestamp}:"]
        lines.append(f"  Insights evaluated: {self.insights_evaluated}")
        lines.append(f"  Actionable: {self.actionable_found}")
        if self.pre_eval_rejected > 0:
            lines.append(f"  Pre-eval rejected (idea not worth coding): {self.pre_eval_rejected}")
        if self.proposals_generated > 0:
            lines.append(f"  Code generated: {self.proposals_generated}")
            lines.append(f"  Merged to develop: {self.merged_to_develop}")
            lines.append(f"  Pending approval: {self.proposals_pending}")
            if self.quality_rejected > 0:
                lines.append(f"  Quality rejected (noise): {self.quality_rejected}")
            if self.proposals_failed > 0:
                lines.append(f"  Failed validation: {self.proposals_failed}")
        if self.errors:
            lines.append(f"  Errors: {len(self.errors)}")
        return "\n".join(lines)


class CognitiveCycleOrchestrator:
    """
    Orchestrates the full cognitive cycle:
    insight evaluation → code generation → mirror validation → pending.

    Human always has the last word. Nothing is auto-approved.

    Usage:
        orchestrator = CognitiveCycleOrchestrator(llm, reflection, introspector, evolution)
        result = orchestrator.run_cycle()
        # Changes are now in mirror pending — user sees them in Review Panel
    """

    def __init__(
        self,
        llm,
        reflection_engine,
        introspector,
        evolution_engine,
        data_dir: str = "data",
        min_confidence: float = 0.6,
        memory_system=None,
    ):
        self.llm = llm
        self.reflection = reflection_engine
        self.evolution = evolution_engine
        self.introspector = introspector
        self.data_dir = data_dir
        self.min_confidence = min_confidence
        self.memory_system = memory_system

        self.evaluator = InsightEvaluator(
            llm=llm,
            reflection_engine=reflection_engine,
            introspector=introspector,
            data_dir=data_dir,
            memory_system=memory_system,
        )

        self.quality_gate = QualityGate(
            llm=llm,
            min_quality_score=0.4,
        )

        # Detect coding agent CLI (Claude Code or Codex) for code generation
        self._coding_agent = self._detect_coding_agent()
        if self._coding_agent:
            logger.info("Cognitive cycle: using %s for code generation", self._coding_agent)

        self.cycle_log_path = os.path.join(data_dir, "cognitive_cycle_log.yaml")
        self._cycle_history: List[Dict] = []
        self._load_history()

    def _load_history(self):
        if os.path.exists(self.cycle_log_path):
            try:
                with open(self.cycle_log_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                self._cycle_history = data.get("cycles", [])
            except Exception:
                self._cycle_history = []

    def _save_history(self, result: CycleResult):
        self._cycle_history.append({
            "timestamp": result.timestamp,
            "insights_evaluated": result.insights_evaluated,
            "actionable_found": result.actionable_found,
            "proposals_pending": result.proposals_pending,
            "proposals_failed": result.proposals_failed,
            "errors": result.errors,
        })
        # Keep last 50 cycles
        trimmed = self._cycle_history[-50:]
        os.makedirs(os.path.dirname(self.cycle_log_path), exist_ok=True)
        atomic_write_yaml(self.cycle_log_path, {"cycles": trimmed})

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    def run_cycle(self, days: int = 3) -> CycleResult:
        """
        Run one full cognitive cycle.

        1. Evaluate recent insights
        2. For each actionable insight above confidence threshold:
           a. Read the target file's current code
           b. Ask the LLM to generate the modification
           c. Create an EvolutionProposal
           d. Apply through mirror (validate, store as pending)
        3. Return results — changes are now waiting for human approval

        This method is safe to call repeatedly. Already-evaluated insights
        are skipped. Already-pending changes for the same file are skipped.
        """
        result = CycleResult()

        # Step 1: Evaluate insights
        try:
            evaluations = self.evaluator.evaluate_recent_insights(days=days)
            result.insights_evaluated = len(evaluations)
        except Exception as e:
            logger.error("Insight evaluation failed: %s", e)
            result.errors.append(f"Evaluation failed: {e}")
            self._save_history(result)
            return result

        # Step 2: Get actionable drafts
        drafts = self.evaluator.get_proposal_drafts(
            results=evaluations,
            min_confidence=self.min_confidence,
        )
        result.actionable_found = len(drafts)

        if not drafts:
            logger.info("No actionable insights found in this cycle.")
            self._save_history(result)
            return result

        # Step 3: Filter out files that already have pending changes
        existing_pending = self._get_pending_files()
        filtered_drafts = []
        for draft in drafts:
            if draft.target_file in existing_pending:
                logger.info(
                    "Skipping %s — already has a pending change",
                    draft.target_file,
                )
                result.details.append({
                    "file": draft.target_file,
                    "status": "skipped_already_pending",
                    "reason": draft.reason,
                })
                continue
            filtered_drafts.append(draft)

        # Step 4: For each draft, generate code and create proposal
        for draft in filtered_drafts:
            detail = self._process_draft(draft)
            result.details.append(detail)

            # Record outcome to experiential memory
            self._record_to_memory("process_draft", detail)

            status = detail.get("status")
            if status == "merged_to_develop":
                result.proposals_generated += 1
                result.merged_to_develop += 1
                result.proposals_pending += 1
            elif status == "pending_approval":
                result.proposals_generated += 1
                result.proposals_pending += 1
            elif status == "pre_eval_rejected":
                result.pre_eval_rejected += 1
            elif status == "quality_rejected":
                result.proposals_generated += 1
                result.quality_rejected += 1
            elif status == "failed" or status == "merge_conflict":
                result.proposals_generated += 1
                result.proposals_failed += 1
            elif status == "generation_failed":
                result.errors.append(detail.get("error", "Unknown generation error"))

        self._save_history(result)
        return result

    # ------------------------------------------------------------------
    # Process a single draft → code generation → mirror
    # ------------------------------------------------------------------

    def _process_draft(self, draft: ProposalDraft) -> Dict:
        """
        Process a draft through the new flow:
        1. PRE-EVALUATE the idea (before generating any code)
        2. CREATE BRANCH from develop
        3. GENERATE CODE on the branch
        4. VALIDATE on the branch
        5. MERGE TO DEVELOP (automatic if validation passes)

        Returns a detail dict with status and metadata.
        """
        target_file = draft.target_file
        mirror = self.evolution.mirror

        # Read current file content
        current_content = self.evolution.see_source(target_file)
        if current_content is None:
            if not self._is_valid_create_path(target_file):
                return {
                    "file": target_file,
                    "status": "skipped",
                    "reason": "File doesn't exist and path is not a valid create target",
                }
            current_content = ""

        # ----------------------------------------------------------
        # Step 1: PRE-EVALUATION — judge the idea before coding
        # ----------------------------------------------------------
        try:
            pre_eval = self.quality_gate.pre_evaluate(
                target_file=target_file,
                modification_description=draft.modification_description,
                reason=draft.reason,
                current_content=current_content if current_content else None,
            )
            logger.info(
                "Pre-eval for %s: proceed=%s, reason=%s",
                target_file, pre_eval.should_proceed, pre_eval.reason,
            )
            if not pre_eval.should_proceed:
                # Record rejection so DeepSeek learns to avoid this in future reflections
                try:
                    self.evaluator._save_rejection(
                        draft.modification_description,
                        pre_eval.reason,
                        phase="pre_eval",
                    )
                except Exception:
                    pass
                return {
                    "file": target_file,
                    "status": "pre_eval_rejected",
                    "reason": pre_eval.reason,
                    "pre_eval_report": pre_eval.summary(),
                }
        except Exception as e:
            logger.warning("Pre-evaluation error for %s: %s (proceeding anyway)", target_file, e)

        # ----------------------------------------------------------
        # Step 2: CREATE BRANCH from develop
        # ----------------------------------------------------------
        branch_name = self._slugify(draft.title)
        try:
            mirror.sync()
            branch = mirror.create_branch(branch_name)
        except Exception as e:
            logger.error("Branch creation failed for %s: %s", branch_name, e)
            return {
                "file": target_file,
                "status": "failed",
                "error": f"Branch creation failed: {e}",
            }

        # ----------------------------------------------------------
        # Step 3: GENERATE CODE
        # ----------------------------------------------------------
        try:
            new_content = self._generate_code(
                target_file=target_file,
                current_content=current_content,
                modification_description=draft.modification_description,
                reason=draft.reason,
            )
        except Exception as e:
            logger.error("Code generation failed for %s: %s", target_file, e)
            mirror.rollback_branch(branch)
            return {
                "file": target_file,
                "status": "generation_failed",
                "error": str(e),
            }

        if not new_content:
            mirror.rollback_branch(branch)
            return {
                "file": target_file,
                "status": "generation_failed",
                "error": "LLM returned empty code",
            }

        if new_content.strip() == current_content.strip():
            mirror.rollback_branch(branch)
            return {
                "file": target_file,
                "status": "skipped",
                "reason": "Generated code is identical to current",
            }

        # ----------------------------------------------------------
        # Step 4: APPLY + VALIDATE on the branch
        # ----------------------------------------------------------
        try:
            # Capture the SHA of the new commit so the notebook-and-book
            # promote flow can later cherry-pick this exact change from
            # develop into main without depending on the branch name.
            commit_sha = mirror.apply_change(target_file, new_content, branch=branch)
            validation = mirror.validate(target_file)
        except Exception as e:
            logger.error("Apply/validate failed for %s: %s", target_file, e)
            mirror.rollback_branch(branch)
            return {
                "file": target_file,
                "status": "failed",
                "error": str(e),
            }

        if not validation.all_ok:
            logger.warning(
                "Validation failed for %s on branch %s: %s",
                target_file, branch, validation.errors,
            )
            mirror.rollback_branch(branch)
            return {
                "file": target_file,
                "status": "failed",
                "error": "; ".join(validation.errors),
                "validation_errors": validation.errors,
            }

        # Post-generation quality gate
        try:
            quality = self.quality_gate.evaluate(
                target_file=target_file,
                original_content=current_content,
                new_content=new_content,
                modification_reason=draft.reason,
            )
            if not quality.is_improvement:
                logger.info(
                    "Quality gate REJECTED %s: %s",
                    target_file, "; ".join(quality.reasons),
                )
                mirror.rollback_branch(branch)
                return {
                    "file": target_file,
                    "status": "quality_rejected",
                    "quality_score": quality.score,
                    "quality_reasons": quality.reasons,
                    "quality_report": quality.summary(),
                }
        except Exception as e:
            logger.warning("Quality gate error for %s: %s", target_file, e)

        # ----------------------------------------------------------
        # Step 5: MERGE TO DEVELOP (automatic)
        # ----------------------------------------------------------
        try:
            merge_result = mirror.merge_to_develop(branch)
        except Exception as e:
            logger.error("Merge to develop failed for %s: %s", target_file, e)
            mirror.rollback_branch(branch)
            return {
                "file": target_file,
                "status": "failed",
                "error": f"Merge failed: {e}",
            }

        if merge_result.conflict:
            logger.warning(
                "Merge conflict for %s on branch %s",
                target_file, branch,
            )
            return {
                "file": target_file,
                "status": "merge_conflict",
                "branch": branch,
                "error": merge_result.error,
            }

        if not merge_result.success:
            mirror.rollback_branch(branch)
            return {
                "file": target_file,
                "status": "failed",
                "error": merge_result.error,
            }

        # Store as pending for human approval (develop → main → live)
        try:
            from .self_modification import Modification
            from .modification_log import generate_modification_id
            mod_id = generate_modification_id()
            modification = Modification(
                id=mod_id,
                timestamp=datetime.now().isoformat(),
                target_file=target_file,
                modification_type='rewrite',
                original_content=current_content,
                new_content=new_content,
                reason=f"Evolution: {draft.title} - {draft.reason}",
                initiated_by='aria',
                success=True,
                status='validated_pending_approval',
                validation_result={
                    'syntax_ok': validation.syntax_ok,
                    'import_ok': validation.import_ok,
                    'tests_ok': validation.tests_ok,
                    'errors': validation.errors,
                    'duration_seconds': validation.duration_seconds,
                },
                commit_sha=commit_sha,
            )
            self.evolution.modifier._store_pending_change(modification)
            self.evolution.modifier.log.record(modification)
        except Exception as e:
            logger.warning("Could not store pending change: %s", e)

        logger.info(
            "Cognitive cycle: %s → merged to develop (branch: %s)",
            target_file, branch,
        )
        return {
            "file": target_file,
            "status": "merged_to_develop",
            "branch": branch,
            "title": draft.title,
            "confidence": draft.confidence,
        }

    # ------------------------------------------------------------------
    # Memory recording
    # ------------------------------------------------------------------

    def _record_to_memory(self, event: str, detail: Dict):
        """Record a self-modification event to experiential memory."""
        if not self.memory_system:
            return
        try:
            from core.memory.memory_v2 import EmotionalTone, MemoryOrigin

            target = detail.get("file", "unknown")
            title = detail.get("title", "")
            status = detail.get("status", "unknown")

            tone_map = {
                "merged_to_develop": EmotionalTone.INSPIRED,
                "pre_eval_rejected": EmotionalTone.NEUTRAL,
                "quality_rejected": EmotionalTone.NEUTRAL,
                "generation_failed": EmotionalTone.CONFUSED,
                "failed": EmotionalTone.CONFUSED,
                "merge_conflict": EmotionalTone.ANXIOUS,
            }
            importance_map = {
                "merged_to_develop": 0.9,
                "pre_eval_rejected": 0.5,
                "quality_rejected": 0.6,
                "generation_failed": 0.6,
                "failed": 0.5,
                "merge_conflict": 0.7,
            }

            if status == "merged_to_develop":
                content = (
                    f"Generé una auto-modificación exitosa: {title}. "
                    f"Archivo: {target}, rama: {detail.get('branch', '?')}. "
                    f"El cambio fue mergeado a develop y espera aprobación humana."
                )
            elif status == "pre_eval_rejected":
                content = (
                    f"Descarté una idea antes de generar código para {target}: "
                    f"{detail.get('reason', 'sin razón')}. "
                    f"Esto ahorró tokens y evitó código innecesario."
                )
            elif status == "quality_rejected":
                content = (
                    f"Generé código para {target} pero el quality gate lo rechazó: "
                    f"{'; '.join(detail.get('quality_reasons', []))}. "
                    f"Score: {detail.get('quality_score', '?')}"
                )
            elif status == "generation_failed":
                content = (
                    f"Intenté generar código para {target} pero falló: "
                    f"{detail.get('error', 'error desconocido')}"
                )
            elif status == "merge_conflict":
                content = (
                    f"Generé código para {target} pero hubo conflicto de merge: "
                    f"{detail.get('error', '')}. "
                    f"Otro cambio tocó el mismo archivo."
                )
            elif status == "failed":
                content = (
                    f"Falló la auto-modificación de {target}: "
                    f"{detail.get('error', 'error desconocido')}"
                )
            else:
                return  # Don't record uninteresting statuses

            self.memory_system.experience(
                content=content,
                emotional_tone=tone_map.get(status, EmotionalTone.NEUTRAL),
                origin=MemoryOrigin.REFLECTED,
                importance=importance_map.get(status, 0.5),
                tags=["self_modification", "cognitive_cycle", status],
                context=f"Ciclo cognitivo: {event}",
            )
        except Exception as e:
            logger.debug("Could not record cognitive cycle event to memory: %s", e)

    # ------------------------------------------------------------------
    # Code generation
    # ------------------------------------------------------------------

    def _generate_code(
        self,
        target_file: str,
        current_content: str,
        modification_description: str,
        reason: str,
        max_retries: int = 3,
    ) -> str:
        """
        Generate modified file content.

        Strategy:
        1. If coding agent (Claude Code/Codex) is available → surgical Edit
        2. Else fall back to LLM full-file generation with retries
        3. Last resort: targeted patch splice
        """
        # -- Try coding agent first (surgical edits, much more reliable) --
        if self._coding_agent:
            try:
                result = self._generate_code_via_agent(
                    target_file, current_content,
                    modification_description, reason,
                )
                if result:
                    return result
                logger.warning(
                    "Agent code generation returned empty for %s, falling back to LLM",
                    target_file,
                )
            except Exception as e:
                logger.warning(
                    "Agent code generation failed for %s: %s, falling back to LLM",
                    target_file, e,
                )

        # -- LLM full-file generation with retries --
        last_error = None
        for attempt in range(max_retries):
            code = self._attempt_full_file_generation(
                target_file, current_content, modification_description,
                reason, syntax_error=last_error,
            )
            if not code:
                return ""

            try:
                ast.parse(code)
                return code
            except SyntaxError as e:
                last_error = f"line {e.lineno}: {e.msg}"
                logger.warning(
                    "Code generation attempt %d/%d for %s: syntax error %s",
                    attempt + 1, max_retries, target_file, last_error,
                )

        # -- Last resort: targeted patch --
        if current_content:
            logger.info(
                "Full-file generation failed %d times for %s, trying targeted patch",
                max_retries, target_file,
            )
            return self._attempt_targeted_patch(
                target_file, current_content, modification_description, reason,
            )

        return ""

    def _generate_code_via_agent(
        self,
        target_file: str,
        current_content: str,
        modification_description: str,
        reason: str,
    ) -> str:
        """Use Claude Code or Codex CLI for surgical code edits.

        The agent operates on the mirror working tree (the branch is already
        checked out by _process_draft). It reads the file, makes Edit-based
        changes, and we read the result back.
        """
        mirror_dir = self.evolution.mirror.mirror_dir
        mirror_file = os.path.join(mirror_dir, target_file)

        # Ensure the file exists in the mirror for the agent to edit
        if not os.path.exists(mirror_file):
            os.makedirs(os.path.dirname(mirror_file), exist_ok=True)
            with open(mirror_file, "w", encoding="utf-8") as f:
                f.write(current_content or "")

        prompt = (
            f"Edit the file {target_file} to make this change:\n\n"
            f"MODIFICATION: {modification_description}\n"
            f"REASON: {reason}\n\n"
            f"Rules:\n"
            f"- Read the file first to understand the current code\n"
            f"- Use the Edit tool for surgical changes — do NOT rewrite the entire file\n"
            f"- Keep all existing code intact unless the modification explicitly changes it\n"
            f"- The result must be valid Python that passes ast.parse()\n"
            f"- Follow the existing code style\n"
            f"- Make the minimal change needed\n"
        )

        cmd = [self._coding_agent, "-p", "--output-format", "text",
               "--max-budget-usd", "2.00"]
        if self._coding_agent == "claude":
            # Headless -p never shows permission prompts; --allowedTools alone
            # grants the tools. --dangerously-skip-permissions additionally
            # requires a one-time interactive acceptance, so it fails on a
            # machine that never accepted the bypass dialog.
            cmd.extend(["--allowedTools", "Edit,Read,Glob,Grep"])
        elif self._coding_agent == "codex":
            cmd.extend(["--approval-mode", "full-auto"])
        cmd.insert(2, prompt)  # after -p: --allowedTools is variadic and would swallow a trailing prompt

        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=120, cwd=mirror_dir,
        )

        if proc.returncode != 0:
            logger.warning(
                "Agent (%s) code gen failed for %s: exit %d — %s",
                self._coding_agent, target_file,
                proc.returncode, proc.stderr[:300],
            )
            return ""

        # Read back the modified file
        if not os.path.exists(mirror_file):
            return ""
        with open(mirror_file, "r", encoding="utf-8") as f:
            new_content = f.read()

        # Validate syntax
        try:
            ast.parse(new_content)
        except SyntaxError as e:
            logger.warning(
                "Agent-generated code has syntax error for %s: %s",
                target_file, e,
            )
            return ""

        return new_content

    @staticmethod
    def _detect_coding_agent() -> Optional[str]:
        """Find the best available coding agent CLI."""
        for agent in ("claude", "codex"):
            if shutil.which(agent):
                return agent
        return None

    def _attempt_full_file_generation(
        self,
        target_file: str,
        current_content: str,
        modification_description: str,
        reason: str,
        syntax_error: str = None,
    ) -> str:
        """Single attempt at full-file code generation."""
        if current_content:
            error_note = ""
            if syntax_error:
                error_note = f"""
IMPORTANT — YOUR PREVIOUS ATTEMPT HAD A SYNTAX ERROR:
  {syntax_error}
Fix this error. Double-check all strings, brackets, and indentation."""

            prompt = f"""You are ARIA, modifying your own source code.

FILE: {target_file}
CURRENT CONTENT:
```python
{current_content}
```

MODIFICATION REQUESTED:
{modification_description}

REASON:
{reason}
{error_note}
RULES:
- Return ONLY the complete modified file content
- Keep ALL existing code intact unless the modification explicitly changes it
- The code MUST be valid Python that passes ast.parse()
- Follow the existing coding style and conventions
- Do NOT wrap in markdown code blocks
- Do NOT include any explanation, just the raw Python code
- If adding a method to a class, add it in a logical position
- Preserve all imports, docstrings, and comments"""
        else:
            prompt = f"""You are ARIA, creating a new module for yourself.

FILE TO CREATE: {target_file}

WHAT IT SHOULD DO:
{modification_description}

REASON:
{reason}

RULES:
- Return ONLY the complete Python file content
- Include proper module docstring
- Include necessary imports
- The code MUST be valid Python that passes ast.parse()
- Follow ARIA's coding style (see file path for package conventions)
- Do NOT wrap in markdown code blocks
- Do NOT include any explanation, just the raw Python code"""

        response = self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            system="You are ARIA's code generation system. Generate clean, correct Python code. Nothing else.",
            max_tokens=4000,
        )

        if not response or not response.content:
            return ""

        return self._strip_fences(response.content.strip())

    def _attempt_targeted_patch(
        self,
        target_file: str,
        current_content: str,
        modification_description: str,
        reason: str,
    ) -> str:
        """
        Fallback: generate ONLY the new/modified method, then splice
        it into the original file. Much more reliable for large files
        since the LLM only needs to produce a small code fragment.
        """
        prompt = f"""You are ARIA, modifying your own source code.
The full-file approach failed, so now generate ONLY the specific code to add or change.

FILE: {target_file}
MODIFICATION REQUESTED:
{modification_description}

REASON:
{reason}

INSTRUCTIONS:
1. Output ONLY the new or modified method/function/code block
2. Start with "# PATCH: INSERT AFTER <method_name>" on the first line
   to indicate where in the file this code should go
3. The code must be valid Python (proper indentation for a class method if applicable)
4. Do NOT include the rest of the file — ONLY the patch
5. Do NOT wrap in markdown code blocks

Example output format:
# PATCH: INSERT AFTER analyze_patterns
    def new_method(self, ...):
        \"\"\"Docstring.\"\"\"
        ...
"""

        response = self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            system="You are ARIA's code generation system. Output ONLY the patch fragment. Nothing else.",
            max_tokens=1500,
        )

        if not response or not response.content:
            return ""

        patch = self._strip_fences(response.content.strip())

        # Parse the PATCH directive
        lines = patch.split("\n")
        if not lines[0].startswith("# PATCH:"):
            # No directive — try to insert at end of last class
            code_lines = current_content.split("\n")
            # Find the last class body by looking for a method def at indent 4
            insert_idx = len(code_lines)
            for i in range(len(code_lines) - 1, -1, -1):
                stripped = code_lines[i].strip()
                if stripped.startswith("def ") or stripped.startswith("class "):
                    # Find end of this block
                    insert_idx = i
                    break
            # Insert patch before the last top-level construct
            merged = code_lines[:insert_idx] + [""] + lines + [""] + code_lines[insert_idx:]
            result = "\n".join(merged)
        else:
            directive = lines[0]
            patch_code = "\n".join(lines[1:])

            # Extract anchor method name
            anchor = directive.split("INSERT AFTER")[-1].strip() if "INSERT AFTER" in directive else ""

            if anchor:
                result = self._splice_after_method(current_content, anchor, patch_code)
            else:
                # Append to end of file
                result = current_content.rstrip() + "\n\n" + patch_code + "\n"

        # Validate the spliced result
        try:
            ast.parse(result)
            return result
        except SyntaxError as e:
            logger.error(
                "Targeted patch also produced invalid syntax for %s: %s",
                target_file, e,
            )
            return ""

    def _splice_after_method(self, source: str, anchor_method: str, patch: str) -> str:
        """Insert patch code after the named method in the source."""
        lines = source.split("\n")
        # Find the method definition
        anchor_idx = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"def {anchor_method}(") or stripped.startswith(f"def {anchor_method} ("):
                anchor_idx = i
                break

        if anchor_idx is None:
            # Method not found — append at end
            return source.rstrip() + "\n\n" + patch + "\n"

        # Find end of this method: next def/class at same or lower indentation
        method_indent = len(lines[anchor_idx]) - len(lines[anchor_idx].lstrip())
        end_idx = len(lines)
        for i in range(anchor_idx + 1, len(lines)):
            if not lines[i].strip():
                continue
            current_indent = len(lines[i]) - len(lines[i].lstrip())
            stripped = lines[i].strip()
            if current_indent <= method_indent and (stripped.startswith("def ") or stripped.startswith("class ") or stripped.startswith("@")):
                end_idx = i
                break

        # Insert patch after end of method
        merged = lines[:end_idx] + [""] + patch.split("\n") + [""] + lines[end_idx:]
        return "\n".join(merged)

    @staticmethod
    def _strip_fences(code: str) -> str:
        """Strip markdown fences if the LLM wrapped anyway."""
        if code.startswith("```"):
            lines = code.split("\n")
            lines = lines[1:]  # remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]  # remove closing fence
            code = "\n".join(lines)
        return code

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_pending_files(self) -> set:
        """Get set of files that already have pending mirror changes."""
        try:
            pending = self.evolution.modifier.list_pending_changes()
            return {c.get("target_file") for c in pending if c.get("target_file")}
        except Exception:
            return set()

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert a title to a branch-safe slug."""
        import re as _re
        slug = text.lower().strip()
        slug = _re.sub(r'[^a-z0-9]+', '-', slug)
        slug = slug.strip('-')
        return slug[:60] or "change"

    def _is_valid_create_path(self, path: str) -> bool:
        """Check if a new file path is reasonable."""
        normalized = path.replace("\\", "/")
        # Must be inside core/ or tests/
        valid_prefixes = ("core/", "tests/")
        if not any(normalized.startswith(p) for p in valid_prefixes):
            return False
        # Must be a .py file
        if not normalized.endswith(".py"):
            return False
        # No path traversal
        if ".." in normalized:
            return False
        return True

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_cycle_history(self, limit: int = 10) -> List[Dict]:
        """Return recent cycle history."""
        return self._cycle_history[-limit:]

    def get_stats(self) -> Dict:
        """Summary statistics across all cycles."""
        total_cycles = len(self._cycle_history)
        total_insights = sum(c.get("insights_evaluated", 0) for c in self._cycle_history)
        total_actionable = sum(c.get("actionable_found", 0) for c in self._cycle_history)
        total_pending = sum(c.get("proposals_pending", 0) for c in self._cycle_history)
        total_failed = sum(c.get("proposals_failed", 0) for c in self._cycle_history)

        return {
            "total_cycles": total_cycles,
            "total_insights_evaluated": total_insights,
            "total_actionable_found": total_actionable,
            "total_proposals_to_pending": total_pending,
            "total_proposals_failed": total_failed,
            "last_cycle": self._cycle_history[-1] if self._cycle_history else None,
        }
