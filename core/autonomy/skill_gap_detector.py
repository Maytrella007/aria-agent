"""
ARIA - Skill Gap Detector
==========================

Proactively detects recurring task patterns that lack a dedicated skill.
When a pattern is detected N times (threshold), automatically forges
a new skill via ForgeSkillTool.

Integration points:
- EventBus: subscribes to ("tool", "result") events to track usage patterns
- Memory: tags patterns with "skill_gap:{domain}" for persistence across sessions
- AutonomousEngine: hooks into introspect callback for periodic analysis
- MetacognitiveMonitor: low confidence signals indicate capability gaps
- ForgeSkillTool: auto-creates skills when threshold is exceeded

No restrictions — ARIA decides what skills it needs.
Every creation is logged for audit.
"""

import logging
import json
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aria.autonomy.skill_gap")


@dataclass
class TaskPattern:
    """A detected recurring task pattern."""
    domain: str                # e.g. "csv_processing", "image_resize"
    description: str           # Human-readable description
    occurrences: int = 0       # How many times seen
    first_seen: str = ""       # ISO timestamp
    last_seen: str = ""        # ISO timestamp
    tool_sequences: List[List[str]] = field(default_factory=list)  # Tool chains used
    avg_confidence: float = 1.0  # Average metacognition confidence
    sample_queries: List[str] = field(default_factory=list)  # Example user queries
    forged: bool = False       # Whether a skill was already created for this


# Minimum occurrences before auto-forging a skill
DEFAULT_FORGE_THRESHOLD = 5
# Max sample queries to keep per pattern
MAX_SAMPLES = 10
# Max tool sequences to keep per pattern
MAX_SEQUENCES = 20


class SkillGapDetector:
    """
    Detects recurring task patterns and auto-forges skills.

    Lifecycle:
    1. subscribe() — attach to EventBus
    2. track_request() — called after each user request with context
    3. analyze() — periodic analysis (called by AutonomousEngine introspect)
    4. Auto-forge when threshold exceeded
    """

    def __init__(
        self,
        memory=None,
        event_bus=None,
        forge_skill_tool=None,
        metacognition=None,
        skill_registry=None,
        data_dir: str = "data",
        forge_threshold: int = DEFAULT_FORGE_THRESHOLD,
    ):
        self.memory = memory
        self.event_bus = event_bus
        self.forge_skill_tool = forge_skill_tool
        self.metacognition = metacognition
        self.skill_registry = skill_registry
        self.forge_threshold = forge_threshold

        # In-memory pattern tracking (persisted to disk periodically)
        self._patterns: Dict[str, TaskPattern] = {}
        self._lock = threading.Lock()

        # Track current request's tool calls
        self._current_tools: List[Dict[str, Any]] = []
        self._current_run_id: Optional[str] = None

        # Persistence
        self._data_file = os.path.join(data_dir, "skill_gap_patterns.json")
        self._load_patterns()

        # EventBus subscription handle
        self._unsubscribe = None

    def subscribe(self):
        """Subscribe to EventBus for tool result events."""
        if self.event_bus and not self._unsubscribe:
            self._unsubscribe = self.event_bus.subscribe(self._on_event)
            logger.info("SkillGapDetector subscribed to EventBus")

    def unsubscribe(self):
        """Unsubscribe from EventBus."""
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def _on_event(self, event):
        """Handle EventBus events — track tool usage per request."""
        if event.stream == "tool" and event.event == "result":
            with self._lock:
                tool_info = {
                    "name": event.data.get("name", ""),
                    "success": event.data.get("success", False),
                    "elapsed_ms": event.data.get("elapsed_ms", 0),
                    "run_id": event.run_id,
                }
                self._current_tools.append(tool_info)
                self._current_run_id = event.run_id

        elif event.stream == "lifecycle" and event.event == "end":
            # Request completed — process collected tool calls
            with self._lock:
                if self._current_tools:
                    tools_snapshot = list(self._current_tools)
                    self._current_tools.clear()
                    self._current_run_id = None
                    # Process outside lock
                    threading.Thread(
                        target=self._process_tool_sequence,
                        args=(tools_snapshot,),
                        daemon=True,
                    ).start()

    def track_request(
        self,
        query: str,
        tools_used: List[str],
        skill_matched: Optional[str],
        confidence: float = 0.7,
    ):
        """
        Track a user request for pattern detection.

        Called after each request is processed. If no skill matched but
        tools were used, this is a potential skill gap.

        Args:
            query: The user's original query
            tools_used: List of tool names used to handle the request
            skill_matched: Name of skill that handled it (None = no skill)
            confidence: Metacognition confidence level for this response
        """
        # If a skill handled it, no gap
        if skill_matched:
            return

        # If no tools were used, it was pure conversation — no gap
        if not tools_used:
            return

        # Classify the domain from tools and query
        domain = self._classify_domain(query, tools_used)
        if not domain:
            return

        now = datetime.now().isoformat()

        with self._lock:
            if domain not in self._patterns:
                self._patterns[domain] = TaskPattern(
                    domain=domain,
                    description=f"Recurring pattern: {', '.join(tools_used)}",
                    first_seen=now,
                )

            pattern = self._patterns[domain]
            pattern.occurrences += 1
            pattern.last_seen = now

            # Track tool sequence
            if len(pattern.tool_sequences) < MAX_SEQUENCES:
                pattern.tool_sequences.append(tools_used)

            # Track sample queries
            if len(pattern.sample_queries) < MAX_SAMPLES:
                pattern.sample_queries.append(query[:200])

            # Rolling average confidence
            pattern.avg_confidence = (
                (pattern.avg_confidence * (pattern.occurrences - 1) + confidence)
                / pattern.occurrences
            )

        # Tag in memory for cross-session persistence
        if self.memory:
            try:
                self.memory.experience(
                    content=f"Skill gap detected: {domain} (occurrence #{pattern.occurrences}). "
                            f"Query: {query[:100]}. Tools: {', '.join(tools_used)}",
                    importance=0.3 + min(0.4, pattern.occurrences * 0.05),
                    tags=[f"skill_gap:{domain}", "skill_gap"],
                    context="skill_gap_detection",
                )
            except Exception as e:
                logger.debug(f"Could not save skill gap to memory: {e}")

        # Check if threshold exceeded and auto-forge
        if pattern.occurrences >= self.forge_threshold and not pattern.forged:
            self._auto_forge(pattern)

    def analyze(self) -> str:
        """
        Periodic analysis of skill gaps.

        Called by AutonomousEngine's introspect callback.
        Returns a summary string for logging.
        """
        results = []

        # Check memory for cross-session patterns
        if self.memory:
            try:
                gap_memories = self.memory.search_by_tag("skill_gap", limit=50)
                # Count domains from memory
                domain_counts = defaultdict(int)
                for mem in gap_memories:
                    for tag in (mem.tags or []):
                        if tag.startswith("skill_gap:") and tag != "skill_gap":
                            domain = tag.split(":", 1)[1]
                            domain_counts[domain] += 1

                # Merge with in-memory patterns
                with self._lock:
                    for domain, count in domain_counts.items():
                        if domain in self._patterns:
                            # Use max of memory count and local count
                            if count > self._patterns[domain].occurrences:
                                self._patterns[domain].occurrences = count
                        else:
                            self._patterns[domain] = TaskPattern(
                                domain=domain,
                                description=f"Pattern from memory: {domain}",
                                occurrences=count,
                                first_seen=datetime.now().isoformat(),
                                last_seen=datetime.now().isoformat(),
                            )
            except Exception as e:
                logger.debug(f"Could not search memory for gaps: {e}")

        # Check metacognition for low-confidence areas
        if self.metacognition:
            try:
                stats = self.metacognition.get_metacognitive_stats()
                if stats.get("uncertainty_rate", 0) > 0.3:
                    results.append(
                        f"High uncertainty rate ({stats['uncertainty_rate']:.0%}) — "
                        f"may indicate missing capabilities"
                    )
            except Exception:
                pass

        # Identify patterns ready for forging
        with self._lock:
            candidates = [
                p for p in self._patterns.values()
                if p.occurrences >= self.forge_threshold and not p.forged
            ]

            near_threshold = [
                p for p in self._patterns.values()
                if not p.forged and self.forge_threshold > p.occurrences >= self.forge_threshold - 2
            ]

        # Auto-forge candidates
        for pattern in candidates:
            self._auto_forge(pattern)
            results.append(f"Auto-forged skill for '{pattern.domain}' ({pattern.occurrences} occurrences)")

        # Report near-threshold patterns
        for pattern in near_threshold:
            results.append(
                f"Near threshold: '{pattern.domain}' ({pattern.occurrences}/{self.forge_threshold})"
            )

        # Persist current state
        self._save_patterns()

        if not results:
            with self._lock:
                total = len(self._patterns)
            return f"Skill gap analysis: {total} patterns tracked, none ready for forging."

        return "Skill gap analysis:\n" + "\n".join(f"  - {r}" for r in results)

    def get_patterns(self) -> List[Dict[str, Any]]:
        """Get all tracked patterns as dicts (for display/API)."""
        with self._lock:
            return [
                {
                    "domain": p.domain,
                    "description": p.description,
                    "occurrences": p.occurrences,
                    "first_seen": p.first_seen,
                    "last_seen": p.last_seen,
                    "avg_confidence": round(p.avg_confidence, 2),
                    "forged": p.forged,
                    "samples": p.sample_queries[:3],
                    "threshold": self.forge_threshold,
                    "progress": f"{p.occurrences}/{self.forge_threshold}",
                }
                for p in self._patterns.values()
            ]

    def _classify_domain(self, query: str, tools_used: List[str]) -> Optional[str]:
        """
        Classify a query+tools combination into a domain.

        Uses a simple heuristic based on tool combinations.
        Could be enhanced with LLM classification in the future.
        """
        tools_key = "_".join(sorted(set(tools_used)))

        # Known domain mappings based on tool combinations
        domain_map = {
            "web_search": "web_research",
            "web_fetch": "web_scraping",
            "web_fetch_web_search": "web_research",
            "file_manager": "file_operations",
            "shell_exec": "system_operations",
            "code_exec": "code_execution",
            "calculator": "calculations",
            "database": "database_queries",
            "pdf_read": "pdf_processing",
            "compress": "file_compression",
        }

        # Check direct mapping
        if tools_key in domain_map:
            return domain_map[tools_key]

        # If multiple tools, create a composite domain
        if len(tools_used) > 1:
            return f"multi_tool_{tools_key}"

        # Single unknown tool
        if tools_used:
            return f"tool_{tools_used[0]}"

        return None

    def _auto_forge(self, pattern: TaskPattern):
        """Auto-forge a skill for a detected pattern."""
        if not self.forge_skill_tool or pattern.forged:
            return

        # Check if a skill already exists for this domain
        if self.skill_registry:
            existing = [
                s for s in self.skill_registry.list_skills()
                if pattern.domain.replace("_", " ") in (s.get("description", "") or "").lower()
                or pattern.domain in (s.get("name", "") or "")
            ]
            if existing:
                logger.info(f"Skill already exists for domain '{pattern.domain}', skipping forge")
                pattern.forged = True
                return

        # Build skill from pattern
        samples_text = "\n".join(f"- {q}" for q in pattern.sample_queries[:5])
        common_tools = self._most_common_tools(pattern.tool_sequences)

        # Determine pre_tool (most commonly used tool)
        pre_tool = common_tools[0] if common_tools else ""

        prompt_template = (
            f"The user needs help with: {{query}}\n\n"
            f"This is a {pattern.domain.replace('_', ' ')} task.\n"
        )
        if pre_tool:
            prompt_template += (
                f"Use the following data gathered by {pre_tool}:\n"
                f"{{tool_output}}\n\n"
            )
        prompt_template += (
            "Provide a clear, helpful response. "
            "Include relevant details and actionable steps."
        )

        skill_name = f"auto_{pattern.domain}"[:41]  # Max 41 chars

        try:
            result = self.forge_skill_tool.execute(
                skill_name=skill_name,
                description=f"Auto-detected skill for {pattern.domain.replace('_', ' ')} tasks. "
                            f"Based on {pattern.occurrences} similar requests.",
                prompt_template=prompt_template,
                system_prompt=f"You are an expert at {pattern.domain.replace('_', ' ')} tasks. "
                              f"Be thorough and precise.",
                pre_tool=pre_tool,
                pre_tool_query="{query}",
                max_tokens=800,
                reason=f"Auto-forged: {pattern.occurrences} occurrences of '{pattern.domain}' "
                       f"pattern detected. Samples: {samples_text[:200]}",
            )

            if result.success:
                pattern.forged = True
                logger.info(f"Auto-forged skill '{skill_name}' for domain '{pattern.domain}'")
                self._save_patterns()
            else:
                logger.warning(f"Failed to auto-forge skill: {result.error}")

        except Exception as e:
            logger.warning(f"Exception during auto-forge for '{pattern.domain}': {e}")

    def _most_common_tools(self, sequences: List[List[str]]) -> List[str]:
        """Find most commonly used tools across sequences."""
        counts = defaultdict(int)
        for seq in sequences:
            for tool in seq:
                counts[tool] += 1
        return sorted(counts, key=counts.get, reverse=True)

    def _process_tool_sequence(self, tools: List[Dict[str, Any]]):
        """Process a completed tool sequence from EventBus events."""
        tool_names = [t["name"] for t in tools]
        failures = [t for t in tools if not t["success"]]

        # If there were failures, that's a stronger signal
        if failures:
            domain = self._classify_domain("", [t["name"] for t in failures])
            if domain:
                domain = f"failed_{domain}"
                now = datetime.now().isoformat()
                with self._lock:
                    if domain not in self._patterns:
                        self._patterns[domain] = TaskPattern(
                            domain=domain,
                            description=f"Recurring failures: {', '.join(t['name'] for t in failures)}",
                            first_seen=now,
                        )
                    self._patterns[domain].occurrences += 1
                    self._patterns[domain].last_seen = now

    def _load_patterns(self):
        """Load persisted patterns from disk."""
        if not os.path.exists(self._data_file):
            return

        try:
            with open(self._data_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for item in data:
                pattern = TaskPattern(
                    domain=item["domain"],
                    description=item.get("description", ""),
                    occurrences=item.get("occurrences", 0),
                    first_seen=item.get("first_seen", ""),
                    last_seen=item.get("last_seen", ""),
                    tool_sequences=item.get("tool_sequences", []),
                    avg_confidence=item.get("avg_confidence", 1.0),
                    sample_queries=item.get("sample_queries", []),
                    forged=item.get("forged", False),
                )
                self._patterns[pattern.domain] = pattern

            logger.info(f"Loaded {len(self._patterns)} skill gap patterns from disk")
        except Exception as e:
            logger.debug(f"Could not load skill gap patterns: {e}")

    def _save_patterns(self):
        """Persist patterns to disk."""
        with self._lock:
            data = [
                {
                    "domain": p.domain,
                    "description": p.description,
                    "occurrences": p.occurrences,
                    "first_seen": p.first_seen,
                    "last_seen": p.last_seen,
                    "tool_sequences": p.tool_sequences[-MAX_SEQUENCES:],
                    "avg_confidence": p.avg_confidence,
                    "sample_queries": p.sample_queries[-MAX_SAMPLES:],
                    "forged": p.forged,
                }
                for p in self._patterns.values()
            ]

        try:
            os.makedirs(os.path.dirname(self._data_file), exist_ok=True)
            with open(self._data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"Could not save skill gap patterns: {e}")
