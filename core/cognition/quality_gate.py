"""
ARIA - Quality Gate for Self-Modifications
============================================
Determines whether a generated code change is a REAL improvement
or just well-formatted noise.

The mirror validates structure (syntax, imports, tests).
This module validates VALUE (does the change actually help?).

Checks:
  1. Dead code detection — does anything call the new code?
  2. Semantic diff analysis — what specifically changed and why?
  3. LLM review — second opinion on the diff quality
  4. Integration check — does the change connect to existing flows?

Scoring: 0.0 (pure noise) to 1.0 (clear improvement)
Threshold: changes below min_quality_score get rejected before pending.
"""

import ast
import difflib
import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger("aria.quality_gate")


@dataclass
class PreEvalReport:
    """Assessment of whether an idea is worth generating code for."""
    target_file: str
    should_proceed: bool = False
    reason: str = ""
    analysis: Dict = field(default_factory=dict)

    def summary(self) -> str:
        verdict = "PROCEED" if self.should_proceed else "SKIP"
        return f"Pre-eval: {verdict} — {self.reason}"


@dataclass
class QualityReport:
    """Assessment of whether a code change is a real improvement."""
    target_file: str
    score: float = 0.0               # 0.0-1.0 overall quality
    is_improvement: bool = False      # final verdict
    dead_code: bool = False           # new code is never called
    adds_functionality: bool = False  # adds new callable behavior
    modifies_existing: bool = False   # changes existing behavior
    breaks_interface: bool = False    # removes/renames public methods
    diff_stats: Dict = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    llm_assessment: str = ""          # second LLM opinion

    def summary(self) -> str:
        verdict = "IMPROVEMENT" if self.is_improvement else "NOISE"
        lines = [f"Quality: {self.score:.2f} — {verdict}"]
        for r in self.reasons:
            lines.append(f"  - {r}")
        return "\n".join(lines)


class QualityGate:
    """
    Evaluates whether a proposed code change is a genuine improvement.

    Used between mirror validation (syntax OK) and pending storage,
    to filter out changes that compile but don't help.
    """

    # Supported review backends (in preference order)
    AGENTS = ["claude", "codex"]

    def __init__(self, llm=None, min_quality_score: float = 0.4, review_backend: str = "auto"):
        """
        Args:
            llm: LLM provider with .chat() — used if review_backend="llm"
            min_quality_score: minimum score to pass the gate
            review_backend: "auto" (detect best agent), "agent" (Claude Code/Codex),
                            "llm" (use llm.chat()), or None (heuristics only)
        """
        self.llm = llm
        self.min_quality_score = min_quality_score
        self.review_backend = review_backend
        self._detected_agent = None

        if review_backend == "auto":
            self._detected_agent = self._detect_agent()
            if self._detected_agent:
                logger.info("Quality gate: using %s as review agent", self._detected_agent)
            elif llm:
                logger.info("Quality gate: no coding agent found, falling back to llm.chat()")
            else:
                logger.info("Quality gate: heuristics only (no agent, no LLM)")

    def _detect_agent(self) -> Optional[str]:
        """Find the best available coding agent CLI."""
        for agent in self.AGENTS:
            if shutil.which(agent):
                return agent
        return None

    # ------------------------------------------------------------------
    # Pre-evaluation: judge the IDEA before generating code
    # ------------------------------------------------------------------

    def pre_evaluate(
        self,
        target_file: str,
        modification_description: str,
        reason: str,
        current_content: Optional[str] = None,
    ) -> PreEvalReport:
        """
        Decide if an idea is worth generating code for BEFORE spending tokens.

        Checks:
        1. Does the target file exist?
        2. Does the modification duplicate existing functionality?
        3. Does the change connect to an existing flow (who calls it)?
        4. Is this a real improvement or speculative noise?

        Returns PreEvalReport with should_proceed and reason.
        """
        report = PreEvalReport(target_file=target_file)
        analysis = {}

        # Check 1: Target file exists (for modifications)
        if current_content is None:
            project_root = self._find_project_root()
            full_path = os.path.join(project_root, target_file)
            if os.path.exists(full_path):
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        current_content = f.read()
                except Exception:
                    pass

        if current_content is not None:
            analysis["file_exists"] = True
            analysis["file_lines"] = len(current_content.splitlines())
        else:
            analysis["file_exists"] = False

        # Check 2: AST analysis — does the modification description mention
        # something that already exists in the file?
        if current_content and target_file.endswith(".py"):
            try:
                tree = ast.parse(current_content)
                existing_funcs = {
                    n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                }
                existing_classes = {
                    n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
                }
                analysis["existing_functions"] = len(existing_funcs)
                analysis["existing_classes"] = len(existing_classes)

                # Simple keyword overlap check
                desc_lower = modification_description.lower()
                overlapping = [f for f in existing_funcs if f.lower() in desc_lower]
                if overlapping:
                    analysis["potential_duplicates"] = overlapping
            except SyntaxError:
                pass

        # Check 3: Use agent or LLM for deeper judgment if available
        use_agent = (
            (self.review_backend == "auto" and self._detected_agent) or
            self.review_backend == "agent"
        )
        use_llm = (
            (self.review_backend == "auto" and not self._detected_agent and self.llm) or
            self.review_backend == "llm"
        )

        if use_agent:
            agent = self._detected_agent or self._detect_agent()
            if agent:
                self._agent_pre_evaluate(report, analysis, target_file,
                                         modification_description, reason, agent)
        elif use_llm and self.llm:
            self._llm_pre_evaluate(report, analysis, target_file,
                                   modification_description, reason)
        else:
            # Heuristics-only pre-evaluation
            self._heuristic_pre_evaluate(report, analysis, target_file,
                                         modification_description, reason)

        report.analysis = analysis
        return report

    def _heuristic_pre_evaluate(
        self, report: PreEvalReport, analysis: Dict,
        target_file: str, description: str, reason: str,
    ):
        """Pre-evaluate using heuristics only (no LLM)."""
        # If the file doesn't exist and it's a create, allow it
        if not analysis.get("file_exists"):
            report.should_proceed = True
            report.reason = "New file creation — proceed"
            return

        # If there are potential duplicates, flag it
        dupes = analysis.get("potential_duplicates", [])
        if dupes:
            report.should_proceed = False
            report.reason = f"Potential duplicate of existing: {', '.join(dupes)}"
            return

        # Default: proceed (heuristics can't judge intent well)
        report.should_proceed = True
        report.reason = "Heuristic pre-eval: no red flags detected"

    def _llm_pre_evaluate(
        self, report: PreEvalReport, analysis: Dict,
        target_file: str, description: str, reason: str,
    ):
        """Use LLM to judge if the idea is worth coding."""
        file_info = ""
        if analysis.get("file_exists"):
            file_info = f"File has {analysis.get('file_lines', '?')} lines, {analysis.get('existing_functions', '?')} functions, {analysis.get('existing_classes', '?')} classes."
            dupes = analysis.get("potential_duplicates", [])
            if dupes:
                file_info += f"\nPotential overlaps with existing: {', '.join(dupes)}"

        prompt = f"""Before generating any code, evaluate this idea:

TARGET FILE: {target_file}
{file_info}

PROPOSED CHANGE: {description}
REASON: {reason}

Questions:
1. Does this solve a real problem or add genuine value?
2. Is this likely to duplicate something that already exists?
3. Who would call/use this change? Is there a clear consumer?
4. Is this a real improvement or speculative padding?

Respond in EXACTLY this format:
VERDICT: PROCEED or SKIP
REASON: one sentence"""

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You are a strict code change evaluator. Most AI-proposed changes are noise. Only say PROCEED if the change clearly adds value.",
                max_tokens=100,
            )
            if response and response.content:
                text = response.content.strip()
                for line in text.split("\n"):
                    if line.strip().upper().startswith("VERDICT:"):
                        verdict = line.split(":", 1)[1].strip().upper()
                        report.should_proceed = verdict == "PROCEED"
                    elif line.strip().upper().startswith("REASON:"):
                        report.reason = line.split(":", 1)[1].strip()
                if not report.reason:
                    report.reason = text
        except Exception as e:
            logger.warning("LLM pre-evaluation failed: %s", e)
            report.should_proceed = True
            report.reason = f"LLM pre-eval failed ({e}), defaulting to proceed"

    def _agent_pre_evaluate(
        self, report: PreEvalReport, analysis: Dict,
        target_file: str, description: str, reason: str, agent: str,
    ):
        """Use coding agent to judge if the idea is worth coding."""
        prompt = f"""Before writing any code, evaluate this proposed change:

TARGET FILE: {target_file}
PROPOSED CHANGE: {description}
REASON: {reason}

Do these checks:
1. Read the target file. Does something similar already exist?
2. Search the codebase: who would call/consume this change?
3. Is this a real improvement or speculative code nobody needs?
4. Was proper analysis done before proposing code?

Respond in EXACTLY this format (nothing else):
VERDICT: PROCEED or SKIP
REASON: one sentence"""

        cmd = [agent, "-p", "--output-format", "text", "--max-budget-usd", "0.25"]
        if agent == "claude":
            cmd.extend(["--allowedTools", "Read", "Glob", "Grep"])
        elif agent == "codex":
            cmd.extend(["--approval-mode", "full-auto"])
        cmd.insert(2, prompt)  # after -p: --allowedTools is variadic and would swallow a trailing prompt

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=45,
                cwd=self._find_project_root(),
            )
            if proc.returncode != 0:
                report.should_proceed = True
                report.reason = f"Agent pre-eval failed (exit {proc.returncode}), defaulting to proceed"
                return

            output = proc.stdout.strip()
            if output.startswith("{"):
                try:
                    data = json.loads(output)
                    output = data.get("result", output)
                except json.JSONDecodeError:
                    pass

            for line in output.split("\n"):
                if line.strip().upper().startswith("VERDICT:"):
                    verdict = line.split(":", 1)[1].strip().upper()
                    report.should_proceed = verdict == "PROCEED"
                elif line.strip().upper().startswith("REASON:"):
                    report.reason = line.split(":", 1)[1].strip()
            if not report.reason:
                report.reason = output[:200]

        except subprocess.TimeoutExpired:
            report.should_proceed = True
            report.reason = "Agent pre-eval timed out, defaulting to proceed"
        except Exception as e:
            report.should_proceed = True
            report.reason = f"Agent pre-eval error ({e}), defaulting to proceed"

    def evaluate(
        self,
        target_file: str,
        original_content: str,
        new_content: str,
        modification_reason: str = "",
    ) -> QualityReport:
        """
        Full quality evaluation of a proposed change.

        Returns QualityReport with score and verdict.
        """
        report = QualityReport(target_file=target_file)

        # Step 1: Diff analysis
        self._analyze_diff(report, original_content, new_content)

        # Step 2: AST-level analysis
        self._analyze_ast(report, original_content, new_content)

        # Step 3: Dead code detection
        self._detect_dead_code(report, original_content, new_content)

        # Step 4: Interface preservation
        self._check_interface(report, original_content, new_content)

        # Step 5: Review by best available backend
        use_agent = (
            (self.review_backend == "auto" and self._detected_agent) or
            self.review_backend == "agent"
        )
        use_llm = (
            (self.review_backend == "auto" and not self._detected_agent and self.llm) or
            self.review_backend == "llm"
        )

        if use_agent:
            agent = self._detected_agent or self._detect_agent()
            if agent:
                self._agent_review(report, original_content, new_content, modification_reason, agent)
        elif use_llm and self.llm:
            self._llm_review(report, original_content, new_content, modification_reason)

        # Calculate final score
        self._calculate_score(report)

        return report

    # ------------------------------------------------------------------
    # Step 1: Diff statistics
    # ------------------------------------------------------------------

    def _analyze_diff(self, report: QualityReport, original: str, new: str):
        """Compute diff statistics."""
        orig_lines = original.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)

        diff = list(difflib.unified_diff(orig_lines, new_lines, n=0))

        added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

        # Filter out blank/whitespace-only changes
        added_real = sum(
            1 for l in diff
            if l.startswith("+") and not l.startswith("+++") and l[1:].strip()
        )
        removed_real = sum(
            1 for l in diff
            if l.startswith("-") and not l.startswith("---") and l[1:].strip()
        )

        report.diff_stats = {
            "lines_added": added,
            "lines_removed": removed,
            "lines_added_real": added_real,
            "lines_removed_real": removed_real,
            "total_original": len(orig_lines),
            "total_new": len(new_lines),
            "change_ratio": round(
                (added_real + removed_real) / max(len(orig_lines), 1), 3
            ),
        }

        # Flag suspicious patterns
        if added_real == 0 and removed_real == 0:
            report.reasons.append("Only whitespace changes — no real modification")
        elif added_real > 0 and removed_real == 0:
            report.reasons.append(f"Pure addition: {added_real} new lines, nothing removed")
        elif removed_real > added_real * 2:
            report.reasons.append(f"Mostly deletion: {removed_real} removed vs {added_real} added")

    # ------------------------------------------------------------------
    # Step 2: AST-level analysis
    # ------------------------------------------------------------------

    def _analyze_ast(self, report: QualityReport, original: str, new: str):
        """Compare AST structures to find what actually changed."""
        try:
            orig_tree = ast.parse(original)
            new_tree = ast.parse(new)
        except SyntaxError:
            report.reasons.append("Could not parse for AST comparison")
            return

        orig_entities = self._extract_entities(orig_tree)
        new_entities = self._extract_entities(new_tree)

        added_funcs = new_entities["functions"] - orig_entities["functions"]
        removed_funcs = orig_entities["functions"] - new_entities["functions"]
        added_classes = new_entities["classes"] - orig_entities["classes"]
        removed_classes = orig_entities["classes"] - new_entities["classes"]

        # Modified: same name, different body
        common_funcs = orig_entities["functions"] & new_entities["functions"]
        modified_funcs = set()
        for fname in common_funcs:
            orig_src = orig_entities["function_sources"].get(fname, "")
            new_src = new_entities["function_sources"].get(fname, "")
            if orig_src != new_src:
                modified_funcs.add(fname)

        if added_funcs:
            report.adds_functionality = True
            report.reasons.append(f"New functions/methods: {', '.join(sorted(added_funcs))}")
        if added_classes:
            report.adds_functionality = True
            report.reasons.append(f"New classes: {', '.join(sorted(added_classes))}")
        if modified_funcs:
            report.modifies_existing = True
            report.reasons.append(f"Modified functions: {', '.join(sorted(modified_funcs))}")
        if removed_funcs:
            report.reasons.append(f"Removed functions: {', '.join(sorted(removed_funcs))}")
        if removed_classes:
            report.breaks_interface = True
            report.reasons.append(f"Removed classes: {', '.join(sorted(removed_classes))}")

        if not added_funcs and not modified_funcs and not added_classes:
            report.reasons.append("No new or modified functions detected at AST level")

    def _extract_entities(self, tree: ast.AST) -> Dict:
        """Extract function names, class names, and function sources."""
        functions = set()
        classes = set()
        function_sources = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.add(node.name)
                try:
                    function_sources[node.name] = ast.dump(node)
                except Exception:
                    pass
            elif isinstance(node, ast.ClassDef):
                classes.add(node.name)

        return {
            "functions": functions,
            "classes": classes,
            "function_sources": function_sources,
        }

    # ------------------------------------------------------------------
    # Step 3: Dead code detection
    # ------------------------------------------------------------------

    def _detect_dead_code(self, report: QualityReport, original: str, new: str):
        """Check if newly added functions/methods are called anywhere in the file."""
        try:
            orig_tree = ast.parse(original)
            new_tree = ast.parse(new)
        except SyntaxError:
            return

        orig_funcs = {
            n.name for n in ast.walk(orig_tree) if isinstance(n, ast.FunctionDef)
        }
        new_funcs = {
            n.name for n in ast.walk(new_tree) if isinstance(n, ast.FunctionDef)
        }

        added_funcs = new_funcs - orig_funcs
        if not added_funcs:
            return

        # Collect all names that are CALLED in the new file
        called_names = set()
        for node in ast.walk(new_tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called_names.add(node.func.attr)

        # Also collect names referenced as attributes (self.method_name)
        for node in ast.walk(new_tree):
            if isinstance(node, ast.Attribute):
                called_names.add(node.attr)

        uncalled = added_funcs - called_names
        # Exclude dunder methods and known lifecycle methods
        lifecycle = {"__init__", "__str__", "__repr__", "__enter__", "__exit__",
                     "__len__", "__iter__", "__next__", "__getitem__", "__setitem__"}
        uncalled -= lifecycle

        if uncalled and uncalled == added_funcs:
            report.dead_code = True
            report.reasons.append(
                f"Dead code: new functions {sorted(uncalled)} are never called in this file"
            )
        elif uncalled:
            report.reasons.append(
                f"Possibly dead: {sorted(uncalled)} not called in this file (may be called externally)"
            )

    # ------------------------------------------------------------------
    # Step 4: Interface preservation
    # ------------------------------------------------------------------

    def _check_interface(self, report: QualityReport, original: str, new: str):
        """Check if public interfaces were broken."""
        try:
            orig_tree = ast.parse(original)
            new_tree = ast.parse(new)
        except SyntaxError:
            return

        # Public functions = no leading underscore
        orig_public = {
            n.name for n in ast.walk(orig_tree)
            if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
        }
        new_public = {
            n.name for n in ast.walk(new_tree)
            if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
        }

        removed_public = orig_public - new_public
        if removed_public:
            report.breaks_interface = True
            report.reasons.append(
                f"Public interface broken: removed {sorted(removed_public)}"
            )

        # Check class removal
        orig_classes = {
            n.name for n in ast.walk(orig_tree) if isinstance(n, ast.ClassDef)
        }
        new_classes = {
            n.name for n in ast.walk(new_tree) if isinstance(n, ast.ClassDef)
        }
        removed_classes = orig_classes - new_classes
        if removed_classes:
            report.breaks_interface = True
            report.reasons.append(
                f"Classes removed: {sorted(removed_classes)}"
            )

    # ------------------------------------------------------------------
    # Step 5: LLM second opinion
    # ------------------------------------------------------------------

    def _llm_review(
        self, report: QualityReport, original: str, new: str, reason: str
    ):
        """Ask a second LLM pass to judge the diff quality."""
        # Generate a compact diff (not the full files)
        orig_lines = original.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(
            orig_lines, new_lines,
            fromfile="original", tofile="modified", n=3
        ))

        # Truncate for token efficiency
        if len(diff) > 3000:
            diff = diff[:3000] + "\n... (truncated)"

        prompt = f"""You are a code reviewer evaluating whether a self-modification is a REAL improvement or just noise.

STATED REASON FOR CHANGE:
{reason}

DIFF:
```
{diff}
```

Evaluate honestly:
1. Does this change solve a real problem or add genuine value?
2. Is the new code likely to be used by existing callers?
3. Could this have been generated by an LLM just adding plausible-looking code?
4. Is the implementation correct and complete?

Respond in EXACTLY this format:
VERDICT: real_improvement / noise / marginal
SCORE: 0.0-1.0
REASON: one sentence"""

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You are a strict code reviewer. Be honest. Most LLM-generated changes are noise. Only mark as real_improvement if the change clearly adds value.",
                max_tokens=150,
            )

            if response and response.content:
                report.llm_assessment = response.content.strip()
                self._parse_llm_verdict(report, response.content)
        except Exception as e:
            logger.warning("LLM review failed: %s", e)
            report.llm_assessment = f"Review failed: {e}"

    def _parse_llm_verdict(self, report: QualityReport, response: str):
        """Parse the structured LLM review response."""
        parsed = {}
        for line in response.strip().split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                parsed[key.strip().upper()] = value.strip()

        verdict = parsed.get("VERDICT", "noise").lower()
        report.reasons.append(f"LLM review: {verdict} — {parsed.get('REASON', 'no reason')}")

        try:
            llm_score = float(parsed.get("SCORE", "0.0"))
            llm_score = max(0.0, min(1.0, llm_score))
            report.diff_stats["llm_score"] = llm_score
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Step 5b: Coding agent review (Claude Code / Codex)
    # ------------------------------------------------------------------

    def _agent_review(
        self, report: QualityReport, original: str, new: str,
        reason: str, agent: str,
    ):
        """
        Use a coding agent CLI (Claude Code, Codex) to review the diff.

        Stronger than llm.chat() because the agent can read surrounding
        files, understand the codebase, and give context-aware verdicts.
        """
        orig_lines = original.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(
            orig_lines, new_lines,
            fromfile="original", tofile="modified", n=3
        ))

        if len(diff) > 4000:
            diff = diff[:4000] + "\n... (truncated)"

        prompt = f"""You are reviewing a code change that ARIA (an AI) generated about its own source code.

Your job: determine if this is a REAL improvement or just well-formatted noise.

STATED REASON FOR CHANGE:
{reason}

TARGET FILE: {report.target_file}

DIFF:
```
{diff}
```

Check these things:
1. Does the new code solve a real problem or add genuine value?
2. Is the new code called by anything, or is it dead code?
3. Does it break any existing public interfaces?
4. Is this the kind of change a careful human developer would make, or does it look like an LLM padding a file?
5. Read the actual target file if you need more context.

Respond in EXACTLY this format (nothing else):
VERDICT: real_improvement / noise / marginal
SCORE: 0.0-1.0
REASON: one sentence explaining your judgment"""

        cmd = [agent, "-p", "--output-format", "text", "--max-budget-usd", "0.50"]

        # Agent-specific flags
        if agent == "claude":
            cmd.extend(["--allowedTools", "Read", "Glob", "Grep"])
        elif agent == "codex":
            cmd.extend(["--approval-mode", "full-auto"])

        cmd.insert(2, prompt)  # after -p: --allowedTools is variadic and would swallow a trailing prompt

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=self._find_project_root(),
            )

            if proc.returncode != 0:
                logger.warning(
                    "Agent review (%s) failed with code %d: %s",
                    agent, proc.returncode, proc.stderr[:200],
                )
                report.llm_assessment = f"Agent review failed: exit {proc.returncode}"
                return

            output = proc.stdout.strip()

            # If JSON output, extract result text
            if output.startswith("{"):
                try:
                    data = json.loads(output)
                    output = data.get("result", output)
                except json.JSONDecodeError:
                    pass

            report.llm_assessment = f"[{agent}] {output}"
            self._parse_llm_verdict(report, output)
            # Tag the review source
            report.diff_stats["review_agent"] = agent

        except subprocess.TimeoutExpired:
            logger.warning("Agent review (%s) timed out", agent)
            report.llm_assessment = f"Agent review timed out ({agent})"
        except Exception as e:
            logger.warning("Agent review (%s) error: %s", agent, e)
            report.llm_assessment = f"Agent review error: {e}"

    @staticmethod
    def _find_project_root() -> str:
        """Find ARIA project root by walking up from this file."""
        path = os.path.dirname(os.path.abspath(__file__))
        for _ in range(5):
            if os.path.exists(os.path.join(path, "aria.py")):
                return path
            path = os.path.dirname(path)
        return os.getcwd()

    # ------------------------------------------------------------------
    # Final scoring
    # ------------------------------------------------------------------

    def _calculate_score(self, report: QualityReport):
        """
        Calculate final quality score from all signals.

        Heuristic scoring (without LLM, max = 0.70):
          +0.30  adds new functionality (new functions/classes)
          +0.30  modifies existing behavior (not just adding)
          +0.10  real lines changed (not just whitespace)

        LLM review bonus (with LLM, max = 1.0):
          +0.30  LLM review score (scaled)

        Penalties:
          -0.50  breaks public interface (removes public methods/classes)
          -0.35  all new code is dead (never called anywhere in file)
          -0.20  only whitespace changes

        Threshold: 0.4 by default. A modification to existing code
        that doesn't break anything scores 0.40 without LLM review.
        Dead code addition scores 0.05 (noise).
        """
        score = 0.0

        # Positive signals
        if report.adds_functionality:
            score += 0.30
        if report.modifies_existing:
            score += 0.30

        real_changes = report.diff_stats.get("lines_added_real", 0) + \
                       report.diff_stats.get("lines_removed_real", 0)
        if real_changes > 0:
            score += 0.10

        # LLM score contribution
        llm_score = report.diff_stats.get("llm_score")
        if llm_score is not None:
            score += 0.30 * llm_score

        # Penalties
        if report.breaks_interface:
            score -= 0.50
        if report.dead_code:
            score -= 0.35
        if real_changes == 0:
            score -= 0.20

        score = max(0.0, min(1.0, score))
        report.score = round(score, 2)
        report.is_improvement = score >= self.min_quality_score
