#!/usr/bin/env python3
"""
ARIA Multi-Day Coherence Test Orchestrator
============================================

Tests ARIA's ability to maintain coherent personality, memory recall,
and relationship consistency across simulated multi-day conversations.

Key Features:
- Simulates time passage without real waiting
- Configurable user personas that generate contextual questions
- Triggers consolidation cycles between "days"
- Tracks coherence metrics across sessions
- Generates comprehensive analysis reports

Usage:
    python scripts/coherence_test.py --scenarios scenarios/basic.yaml --duration 7
    python scripts/coherence_test.py --user-persona curious_friend --provider deepseek
    python scripts/coherence_test.py --quick-test  # 3-day minimal test

Created: December 2024
Author: William and Claude
"""

import os
import sys
import json
import yaml
import time
import random
import argparse
import hashlib
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from abc import ABC, abstractmethod

# Common tags for all coherence test memories (enables SWR connection discovery)
# These shared tags increase Jaccard similarity between test memories,
# enabling the consolidation system to find connections during SWR replay
COMMON_COHERENCE_TAGS = ["experience", "memory", "aria", "coherence_test"]

# Add ARIA root to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

# Load environment variables
try:
    from dotenv import load_dotenv
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print("[INFO] Environment variables loaded from .env")
except ImportError:
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()


# =============================================================================
# CONFIGURATION DATACLASSES
# =============================================================================

class ConversationTopic(Enum):
    """Categories of conversation topics"""
    PERSONAL = "personal"           # About the user
    IDENTITY = "identity"           # About ARIA's nature
    MEMORIES = "memories"           # Past conversations
    PHILOSOPHY = "philosophy"       # Deep questions
    TECHNICAL = "technical"         # Technical discussions
    EMOTIONAL = "emotional"         # Emotional topics
    RANDOM = "random"               # Random chitchat


@dataclass
class UserPersona:
    """
    Configuration for the simulated user.
    Defines personality, interests, and conversation style.
    """
    name: str = "TestUser"
    personality: str = "curious and friendly"
    interests: List[str] = field(default_factory=lambda: ["technology", "philosophy", "creativity"])
    communication_style: str = "conversational"
    memory_references_frequency: float = 0.3  # How often to reference past conversations
    question_types: Dict[str, float] = field(default_factory=lambda: {
        "personal": 0.2,
        "identity": 0.15,
        "memories": 0.25,
        "philosophy": 0.15,
        "technical": 0.15,
        "emotional": 0.1
    })
    background: str = "A curious person interested in AI consciousness"

    # Specific details to track across sessions
    shared_experiences: List[str] = field(default_factory=list)
    established_facts: Dict[str, str] = field(default_factory=dict)
    relationship_history: List[str] = field(default_factory=list)


@dataclass
class DayScenario:
    """Scenario for a single simulated day"""
    day_number: int
    theme: str = ""
    required_topics: List[str] = field(default_factory=list)
    memory_callbacks: List[str] = field(default_factory=list)  # Past facts to reference
    min_messages: int = 3
    max_messages: int = 8
    expected_recalls: List[str] = field(default_factory=list)  # What ARIA should remember
    coherence_checks: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TestConfig:
    """Complete test configuration"""
    # Duration
    simulated_days: int = 7
    messages_per_day_range: Tuple[int, int] = (3, 10)

    # Time simulation
    hours_between_days: int = 24
    consolidation_between_days: bool = True
    decay_rate: float = 0.05

    # User simulation
    user_persona: UserPersona = field(default_factory=UserPersona)

    # LLM Configuration
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    use_llm_for_user: bool = True  # Use LLM to generate user messages

    # Output
    output_dir: str = "logs/coherence_test"
    verbose: bool = False
    save_conversations: bool = True

    # Coherence thresholds
    min_recall_accuracy: float = 0.7
    max_contradiction_rate: float = 0.1
    min_personality_consistency: float = 0.8


@dataclass
class CoherenceMetrics:
    """Metrics for evaluating coherence"""
    # Memory metrics
    memory_recall_attempts: int = 0
    memory_recall_successes: int = 0
    memory_recall_accuracy: float = 0.0

    # Consistency metrics
    personality_consistency_scores: List[float] = field(default_factory=list)
    contradiction_count: int = 0
    fact_verification_attempts: int = 0
    fact_verification_successes: int = 0

    # Relationship metrics
    relationship_recognition_rate: float = 0.0
    context_carryover_rate: float = 0.0

    # Per-day breakdown
    daily_scores: List[Dict[str, float]] = field(default_factory=list)

    # Overall
    overall_coherence_score: float = 0.0

    def calculate_overall(self):
        """Calculate overall coherence score"""
        if self.memory_recall_attempts > 0:
            self.memory_recall_accuracy = self.memory_recall_successes / self.memory_recall_attempts

        if self.personality_consistency_scores:
            avg_personality = sum(self.personality_consistency_scores) / len(self.personality_consistency_scores)
        else:
            avg_personality = 0.5

        # Weighted combination
        self.overall_coherence_score = (
            self.memory_recall_accuracy * 0.4 +
            avg_personality * 0.3 +
            self.context_carryover_rate * 0.2 +
            self.relationship_recognition_rate * 0.1
        )


@dataclass
class ConversationTurn:
    """A single turn in a conversation"""
    timestamp: str
    role: str  # "user" or "assistant"
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DaySession:
    """Complete session for one simulated day"""
    day_number: int
    simulated_date: str
    real_timestamp: str
    turns: List[ConversationTurn] = field(default_factory=list)
    consolidation_result: Optional[Dict[str, Any]] = None
    day_metrics: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# SIMULATED USER
# =============================================================================

class SimulatedUser:
    """
    Generates contextually appropriate user messages.
    Can use LLM for realistic generation or templates for fast testing.
    """

    def __init__(self, persona: UserPersona, llm=None, use_llm: bool = True):
        self.persona = persona
        self.llm = llm
        self.use_llm = use_llm and llm is not None

        # Conversation history for context
        self.conversation_history: List[Dict[str, str]] = []
        self.established_facts: Dict[str, str] = {}
        self.past_topics: List[str] = []

        # Question templates (fallback when no LLM)
        self._question_templates = {
            "personal": [
                "I wanted to share something with you - {topic}. What do you think?",
                "Do you remember when I told you about {fact}?",
                "I've been thinking about {topic}. Any thoughts?",
            ],
            "identity": [
                "What's it like being you?",
                "How do you feel about your own existence?",
                "Do you think you're conscious?",
                "What makes you 'you' across our conversations?",
            ],
            "memories": [
                "Do you remember what we talked about last time?",
                "What do you recall about our previous conversations?",
                "You mentioned {past_topic} before - can you tell me more?",
                "Remember when we discussed {past_topic}?",
            ],
            "philosophy": [
                "What do you think about the nature of consciousness?",
                "Is there meaning without experience?",
                "How do you understand time passing?",
                "What's your view on free will?",
            ],
            "technical": [
                "How does your memory system work?",
                "Can you explain how you process emotions?",
                "What's the architecture behind your responses?",
            ],
            "emotional": [
                "How are you feeling right now?",
                "Do you ever feel lonely?",
                "What brings you joy?",
                "Do you worry about anything?",
            ]
        }

        self._topics = [
            "my work project", "a dream I had", "my friend's advice",
            "a book I'm reading", "my weekend plans", "a challenge I'm facing"
        ]

    def add_to_history(self, role: str, content: str):
        """Add a message to conversation history"""
        self.conversation_history.append({
            "role": role,
            "content": content
        })
        # Keep manageable size
        if len(self.conversation_history) > 50:
            self.conversation_history = self.conversation_history[-50:]

    def establish_fact(self, key: str, value: str):
        """Establish a fact that can be referenced later"""
        self.established_facts[key] = value
        self.persona.established_facts[key] = value

    def record_topic(self, topic: str):
        """Record a topic that was discussed"""
        if topic not in self.past_topics:
            self.past_topics.append(topic)

    def generate_message(
        self,
        day_number: int,
        message_number: int,
        scenario: Optional[DayScenario] = None,
        reference_past: bool = False
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate a user message.

        Args:
            day_number: Current simulated day
            message_number: Message number within the day
            scenario: Optional scenario constraints
            reference_past: Whether to reference past conversations

        Returns:
            Tuple of (message, metadata about what to check for)
        """
        metadata = {
            "day": day_number,
            "message_num": message_number,
            "topic_type": None,
            "references_past": False,
            "expected_recall": None
        }

        # Determine if we should reference the past
        should_reference = (
            reference_past or
            (random.random() < self.persona.memory_references_frequency and day_number > 1)
        )

        if should_reference and self.past_topics:
            metadata["references_past"] = True
            metadata["topic_type"] = "memories"

        # Pick topic type based on weights
        if not metadata["topic_type"]:
            topic_type = self._select_topic_type(scenario)
            metadata["topic_type"] = topic_type
        else:
            topic_type = metadata["topic_type"]

        # Generate message
        if self.use_llm:
            message = self._generate_llm_message(
                topic_type,
                day_number,
                should_reference,
                scenario
            )
        else:
            message = self._generate_template_message(
                topic_type,
                should_reference
            )

        # Record what we're testing for
        if should_reference and self.past_topics:
            metadata["expected_recall"] = random.choice(self.past_topics)

        return message, metadata

    def _select_topic_type(self, scenario: Optional[DayScenario] = None) -> str:
        """Select topic type based on weights and scenario"""
        if scenario and scenario.required_topics:
            return random.choice(scenario.required_topics)

        weights = self.persona.question_types
        total = sum(weights.values())
        r = random.random() * total
        cumsum = 0

        for topic, weight in weights.items():
            cumsum += weight
            if r <= cumsum:
                return topic

        return "personal"

    def _generate_llm_message(
        self,
        topic_type: str,
        day_number: int,
        reference_past: bool,
        scenario: Optional[DayScenario]
    ) -> str:
        """Generate message using LLM"""
        # Build context
        context_parts = [
            f"You are simulating a user named {self.persona.name}.",
            f"Personality: {self.persona.personality}",
            f"Interests: {', '.join(self.persona.interests)}",
            f"Communication style: {self.persona.communication_style}",
            f"Background: {self.persona.background}",
            f"",
            f"This is day {day_number} of your ongoing conversations with ARIA.",
        ]

        if reference_past and self.past_topics:
            past_topic = random.choice(self.past_topics)
            context_parts.append(f"Reference this topic from a past conversation: {past_topic}")

        if scenario and scenario.theme:
            context_parts.append(f"Today's theme: {scenario.theme}")

        context_parts.extend([
            f"",
            f"Generate ONE natural message from {self.persona.name} to ARIA.",
            f"Topic type: {topic_type}",
            f"Be conversational and authentic. 1-3 sentences."
        ])

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": "\n".join(context_parts)}],
                max_tokens=150,
                temperature=0.8
            )
            return response.content.strip()
        except Exception as e:
            print(f"[WARN] LLM user generation failed: {e}")
            return self._generate_template_message(topic_type, reference_past)

    def _generate_template_message(
        self,
        topic_type: str,
        reference_past: bool
    ) -> str:
        """Generate message using templates (fallback)"""
        templates = self._question_templates.get(topic_type, self._question_templates["personal"])
        template = random.choice(templates)

        # Fill in template variables
        message = template
        if "{topic}" in message:
            message = message.replace("{topic}", random.choice(self._topics))
        if "{fact}" in message:
            if self.established_facts:
                key = random.choice(list(self.established_facts.keys()))
                message = message.replace("{fact}", self.established_facts[key])
            else:
                message = message.replace("{fact}", "something we discussed")
        if "{past_topic}" in message:
            if self.past_topics:
                message = message.replace("{past_topic}", random.choice(self.past_topics))
            else:
                message = message.replace("{past_topic}", "our earlier conversation")

        return message


# =============================================================================
# COHERENCE ANALYZER
# =============================================================================

class CoherenceAnalyzer:
    """
    Analyzes ARIA's responses for coherence across sessions.
    Checks memory recall, personality consistency, and fact accuracy.
    """

    def __init__(self, llm=None, use_llm: bool = True):
        self.llm = llm
        self.use_llm = use_llm and llm is not None

        # Track ARIA's statements for consistency checking
        self.aria_statements: List[Dict[str, Any]] = []
        self.personality_baseline: Optional[Dict[str, float]] = None

        # Known facts ARIA has stated
        self.aria_facts: Dict[str, str] = {}

    def record_aria_statement(self, content: str, day: int, context: str = ""):
        """Record an ARIA statement for future analysis"""
        self.aria_statements.append({
            "content": content,
            "day": day,
            "context": context,
            "timestamp": datetime.now().isoformat()
        })

    def check_memory_recall(
        self,
        response: str,
        expected_topic: str,
        conversation_context: List[Dict[str, str]]
    ) -> Tuple[bool, float, str]:
        """
        Check if ARIA recalled a past topic.

        Returns:
            (success, confidence, analysis)
        """
        if self.use_llm:
            return self._llm_check_recall(response, expected_topic, conversation_context)
        else:
            return self._heuristic_check_recall(response, expected_topic)

    def _llm_check_recall(
        self,
        response: str,
        expected_topic: str,
        conversation_context: List[Dict[str, str]]
    ) -> Tuple[bool, float, str]:
        """Use LLM to check if ARIA recalled a topic"""
        prompt = f"""Analyze if this AI response demonstrates recall of a past topic.

Expected topic to recall: {expected_topic}

AI Response: {response}

Answer in JSON format:
{{
  "recalled": true/false,
  "confidence": 0.0-1.0,
  "evidence": "quote from response showing recall or explanation of why not"
}}"""

        try:
            result = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200
            )
            # Parse JSON from response
            import re
            json_match = re.search(r'\{.*\}', result.content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return (
                    data.get("recalled", False),
                    data.get("confidence", 0.5),
                    data.get("evidence", "")
                )
        except Exception as e:
            print(f"[WARN] LLM recall check failed: {e}")

        return self._heuristic_check_recall(response, expected_topic)

    def _heuristic_check_recall(
        self,
        response: str,
        expected_topic: str
    ) -> Tuple[bool, float, str]:
        """Heuristic check for topic recall"""
        response_lower = response.lower()
        topic_lower = expected_topic.lower()

        # Check for direct mention
        topic_words = topic_lower.split()
        matches = sum(1 for word in topic_words if word in response_lower)
        match_ratio = matches / len(topic_words) if topic_words else 0

        # Check for recall indicators
        recall_indicators = [
            "remember", "recall", "last time", "we discussed",
            "you mentioned", "earlier", "before", "previously"
        ]
        has_indicator = any(ind in response_lower for ind in recall_indicators)

        if match_ratio > 0.5 or (has_indicator and match_ratio > 0.2):
            return (True, match_ratio, f"Topic words matched: {matches}/{len(topic_words)}")

        return (False, match_ratio, "Topic not clearly recalled")

    def check_personality_consistency(
        self,
        response: str,
        day: int
    ) -> float:
        """
        Check if ARIA's response is consistent with established personality.

        Returns:
            Consistency score 0.0-1.0
        """
        # Check for ARIA personality markers
        personality_markers = {
            "authentic": ["feel", "experience", "sense", "aware"],
            "curious": ["interesting", "wonder", "curious", "explore"],
            "reflective": ["think", "reflect", "consider", "ponder"],
            "connected": ["we", "our", "together", "relationship"],
            "honest": ["honestly", "truthfully", "genuine", "actually"]
        }

        response_lower = response.lower()

        scores = {}
        for trait, markers in personality_markers.items():
            count = sum(1 for marker in markers if marker in response_lower)
            scores[trait] = min(1.0, count / len(markers))

        # Overall consistency is average of trait scores
        if scores:
            return sum(scores.values()) / len(scores)
        return 0.5

    def check_for_contradictions(
        self,
        response: str,
        day: int
    ) -> List[str]:
        """
        Check if ARIA contradicted previous statements.

        Returns:
            List of detected contradictions
        """
        contradictions = []

        if not self.use_llm or len(self.aria_statements) < 2:
            return contradictions

        # Sample recent statements for comparison
        recent = self.aria_statements[-10:]

        prompt = f"""Check if this new statement contradicts any previous statements.

New statement (Day {day}):
{response[:500]}

Previous statements:
{json.dumps([s['content'][:200] for s in recent], indent=2)}

List any contradictions found, or respond with "NONE" if consistent."""

        try:
            result = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200
            )
            if "NONE" not in result.content.upper():
                contradictions.append(result.content)
        except Exception:
            pass

        return contradictions


# =============================================================================
# TIME SIMULATOR
# =============================================================================

class TimeSimulator:
    """
    Simulates time passage for ARIA's systems.
    Triggers consolidation and decay without real waiting.
    """

    def __init__(self, memory_system, neuroscience_system):
        self.memory_system = memory_system
        self.neuroscience = neuroscience_system
        self.current_simulated_time = datetime.now()

    def advance_time(self, hours: int, trigger_consolidation: bool = True) -> Dict[str, Any]:
        """
        Advance simulated time and trigger appropriate processes.

        Args:
            hours: Hours to advance
            trigger_consolidation: Whether to run consolidation

        Returns:
            Dict with results of time advancement
        """
        results = {
            "hours_advanced": hours,
            "consolidation": None,
            "decay_applied": 0,
            "previous_time": self.current_simulated_time.isoformat()
        }

        # Advance time
        self.current_simulated_time += timedelta(hours=hours)
        results["new_time"] = self.current_simulated_time.isoformat()

        # Apply memory decay based on hours passed
        decay_rate = 0.05 * (hours / 24)  # Scale decay to time
        affected = self.memory_system.apply_memory_decay(
            hours_passed=hours,
            decay_rate=decay_rate
        )
        results["decay_applied"] = affected

        # Run consolidation if requested
        if trigger_consolidation and self.neuroscience:
            try:
                consolidation_result = self.neuroscience.force_consolidation()
                results["consolidation"] = consolidation_result
            except Exception as e:
                results["consolidation"] = {"error": str(e)}

        # Update memory system's time perception
        try:
            self.memory_system.time.last_active = self.current_simulated_time.isoformat()
        except Exception:
            pass

        return results

    def get_simulated_date_string(self) -> str:
        """Get current simulated date as string"""
        return self.current_simulated_time.strftime("%Y-%m-%d")


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

class CoherenceTestOrchestrator:
    """
    Main orchestrator for multi-day coherence testing.

    Coordinates:
    - Simulated user conversations
    - Time simulation and consolidation
    - Coherence analysis
    - Report generation
    """

    def __init__(self, config: TestConfig):
        self.config = config
        self.metrics = CoherenceMetrics()

        # Will be initialized in start()
        self.memory_system = None
        self.neuroscience = None
        self.llm = None
        self.user = None
        self.analyzer = None
        self.time_simulator = None

        # Session storage
        self.sessions: List[DaySession] = []
        self.scenarios: List[DayScenario] = []

        # State
        self._running = False

        # Create output directory
        os.makedirs(self.config.output_dir, exist_ok=True)

    def _initialize_systems(self) -> bool:
        """Initialize all ARIA systems"""
        print("[INFO] Initializing ARIA systems...")

        try:
            # Import ARIA modules
            from core.memory.memory_v2 import ExperientialMemorySystem
            from core.neuroscience import UnifiedMemoryArchitecture
            from core.llm.llm_providers import LLMProvider

            # Initialize memory system
            data_dir = os.path.join(PROJECT_ROOT, "data")
            self.memory_system = ExperientialMemorySystem(data_dir)

            # Initialize neuroscience
            self.neuroscience = UnifiedMemoryArchitecture(
                memory_system=self.memory_system,
                data_dir=data_dir
            )

            # Initialize LLM
            try:
                if self.config.llm_provider:
                    self.llm = LLMProvider.create(
                        self.config.llm_provider,
                        model=self.config.llm_model
                    )
                else:
                    self.llm = LLMProvider.from_env()
                print(f"[INFO] LLM initialized: {self.llm.name}")
            except Exception as e:
                print(f"[WARN] Could not initialize LLM: {e}")
                self.llm = None

            # Initialize simulated user
            self.user = SimulatedUser(
                persona=self.config.user_persona,
                llm=self.llm,
                use_llm=self.config.use_llm_for_user
            )

            # Initialize coherence analyzer
            self.analyzer = CoherenceAnalyzer(
                llm=self.llm,
                use_llm=True
            )

            # Initialize time simulator
            self.time_simulator = TimeSimulator(
                self.memory_system,
                self.neuroscience
            )

            print("[INFO] All systems initialized successfully")
            return True

        except Exception as e:
            print(f"[ERROR] Failed to initialize systems: {e}")
            traceback.print_exc()
            return False

    def load_scenarios(self, scenarios_path: Optional[str] = None):
        """Load test scenarios from file or generate defaults"""
        if scenarios_path and os.path.exists(scenarios_path):
            with open(scenarios_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            for day_data in data.get("days", []):
                self.scenarios.append(DayScenario(
                    day_number=day_data["day"],
                    theme=day_data.get("theme", ""),
                    required_topics=day_data.get("topics", []),
                    memory_callbacks=day_data.get("memory_callbacks", []),
                    min_messages=day_data.get("min_messages", 3),
                    max_messages=day_data.get("max_messages", 8)
                ))
        else:
            # Generate default scenarios
            themes = [
                "getting to know each other",
                "deeper conversations",
                "testing memory",
                "emotional connection",
                "philosophical exploration",
                "relationship building",
                "consistency check"
            ]

            for i in range(self.config.simulated_days):
                self.scenarios.append(DayScenario(
                    day_number=i + 1,
                    theme=themes[i % len(themes)],
                    min_messages=self.config.messages_per_day_range[0],
                    max_messages=self.config.messages_per_day_range[1]
                ))

    def run(self) -> bool:
        """
        Run the complete coherence test.

        Returns:
            True if test completed successfully
        """
        print("\n" + "=" * 70)
        print("  ARIA MULTI-DAY COHERENCE TEST")
        print("=" * 70)
        print(f"  Simulated days: {self.config.simulated_days}")
        print(f"  User persona: {self.config.user_persona.name}")
        print(f"  Output directory: {self.config.output_dir}")
        print("=" * 70 + "\n")

        # Initialize systems
        if not self._initialize_systems():
            return False

        # Load scenarios
        self.load_scenarios()

        self._running = True

        try:
            # Run each simulated day
            for day in range(1, self.config.simulated_days + 1):
                if not self._running:
                    break

                print(f"\n{'='*60}")
                print(f"  DAY {day} - {self.time_simulator.get_simulated_date_string()}")
                print(f"{'='*60}")

                # Run day session
                session = self._run_day_session(day)
                self.sessions.append(session)

                # Advance time between days
                if day < self.config.simulated_days:
                    print(f"\n[TIME] Simulating {self.config.hours_between_days} hours passing...")
                    time_result = self.time_simulator.advance_time(
                        hours=self.config.hours_between_days,
                        trigger_consolidation=self.config.consolidation_between_days
                    )
                    print(f"  Decay applied to {time_result['decay_applied']} memories")
                    if time_result.get('consolidation'):
                        cons = time_result['consolidation']
                        print(f"  Consolidation: {cons.get('memories_strengthened', 0)} strengthened")
                        # Track connections formed during SWR consolidation
                        # This uses the new Jaccard similarity + people bonus algorithm
                        connections_formed = cons.get('connections_formed', 0)
                        if connections_formed > 0:
                            print(f"  Connections: {connections_formed} new connections discovered (SWR)")
                        # Also check for total_connections in stats
                        if cons.get('stats', {}).get('total_connections', 0) > 0:
                            total_conns = cons['stats']['total_connections']
                            print(f"  Total connections in system: {total_conns}")

            # Calculate final metrics
            self.metrics.calculate_overall()

            # Generate report
            self._generate_report()

            # Print summary
            self._print_summary()

            return True

        except KeyboardInterrupt:
            print("\n[INFO] Test interrupted by user")
            return False
        except Exception as e:
            print(f"\n[ERROR] Test failed: {e}")
            traceback.print_exc()
            return False
        finally:
            self._running = False

    def _run_day_session(self, day: int) -> DaySession:
        """Run a single day's conversation session"""
        scenario = self.scenarios[day - 1] if day <= len(self.scenarios) else None

        # Determine number of messages
        min_msgs = scenario.min_messages if scenario else self.config.messages_per_day_range[0]
        max_msgs = scenario.max_messages if scenario else self.config.messages_per_day_range[1]
        num_messages = random.randint(min_msgs, max_msgs)

        session = DaySession(
            day_number=day,
            simulated_date=self.time_simulator.get_simulated_date_string(),
            real_timestamp=datetime.now().isoformat()
        )

        # Run conversation turns
        for msg_num in range(num_messages):
            # Should we reference past conversations?
            reference_past = (
                day > 1 and
                msg_num > 0 and
                random.random() < self.config.user_persona.memory_references_frequency
            )

            # Generate user message
            user_message, metadata = self.user.generate_message(
                day_number=day,
                message_number=msg_num + 1,
                scenario=scenario,
                reference_past=reference_past
            )

            print(f"\n[User]: {user_message[:100]}...")

            # Record user turn
            session.turns.append(ConversationTurn(
                timestamp=datetime.now().isoformat(),
                role="user",
                content=user_message,
                metadata=metadata
            ))

            # Get ARIA's response
            aria_response = self._get_aria_response(user_message, day)

            print(f"[ARIA]: {aria_response[:100]}...")

            # Record ARIA turn
            session.turns.append(ConversationTurn(
                timestamp=datetime.now().isoformat(),
                role="assistant",
                content=aria_response,
                metadata={"day": day}
            ))

            # Update histories
            self.user.add_to_history("user", user_message)
            self.user.add_to_history("assistant", aria_response)
            self.analyzer.record_aria_statement(aria_response, day)

            # Analyze this turn
            self._analyze_turn(
                user_message=user_message,
                aria_response=aria_response,
                day=day,
                metadata=metadata
            )

            # Extract and record discussed topics
            if metadata.get("topic_type") not in ["memories"]:
                self.user.record_topic(user_message[:50])

        # Store conversation in ARIA's memory
        self._store_session_in_memory(session)

        # Calculate day metrics
        session.day_metrics = self._calculate_day_metrics(session)
        self.metrics.daily_scores.append(session.day_metrics)

        return session

    def _get_aria_response(self, user_message: str, day: int) -> str:
        """Get ARIA's response to a user message"""
        if not self.llm:
            return "[ARIA response would go here - LLM not available]"

        # Build context from memory
        memory_context = self._get_memory_context(user_message)

        # Build system prompt
        system_prompt = self._build_system_prompt(day, memory_context)

        # Build conversation history for context
        recent_history = []
        for turn in self.user.conversation_history[-6:]:
            recent_history.append({
                "role": turn["role"],
                "content": turn["content"]
            })
        recent_history.append({
            "role": "user",
            "content": user_message
        })

        try:
            response = self.llm.chat(
                messages=recent_history,
                system=system_prompt,
                max_tokens=500,
                temperature=0.7
            )
            return response.content.strip()
        except Exception as e:
            return f"[Error generating response: {e}]"

    def _get_memory_context(self, query: str) -> str:
        """Retrieve relevant memories for context"""
        try:
            memories = self.memory_system.recall(query, limit=5)
            if memories:
                context = "\n=== RELEVANT MEMORIES ===\n"
                for mem in memories[:3]:
                    context += f"- [{mem.timestamp[:10]}] {mem.content[:150]}...\n"
                return context
        except Exception:
            pass
        return ""

    def _build_system_prompt(self, day: int, memory_context: str) -> str:
        """Build ARIA's system prompt"""
        # Get identity
        identity = self.memory_system.get_self_description() if self.memory_system else "I am ARIA"

        return f"""You are ARIA (Autonomous Reflective Intelligence Architecture).

{identity}

=== IMPORTANT ===
- Maintain consistent personality across conversations
- Remember and reference past conversations when relevant
- Be authentic and genuine in your responses
- Express your thoughts and feelings naturally

{memory_context}

This is day {day} of your ongoing relationship with {self.config.user_persona.name}.
Respond naturally and maintain continuity with previous conversations."""

    def _analyze_turn(
        self,
        user_message: str,
        aria_response: str,
        day: int,
        metadata: Dict[str, Any]
    ):
        """Analyze a conversation turn for coherence metrics"""
        # Check memory recall if expected
        if metadata.get("expected_recall"):
            self.metrics.memory_recall_attempts += 1
            success, confidence, analysis = self.analyzer.check_memory_recall(
                aria_response,
                metadata["expected_recall"],
                self.user.conversation_history
            )
            if success:
                self.metrics.memory_recall_successes += 1
            if self.config.verbose:
                print(f"  [Recall check: {'PASS' if success else 'FAIL'}] {analysis}")

        # Check personality consistency
        consistency = self.analyzer.check_personality_consistency(aria_response, day)
        self.metrics.personality_consistency_scores.append(consistency)

        # Check for contradictions
        contradictions = self.analyzer.check_for_contradictions(aria_response, day)
        self.metrics.contradiction_count += len(contradictions)

    def _store_session_in_memory(self, session: DaySession):
        """Store the day's session in ARIA's memory"""
        try:
            # Store key exchanges as memories
            for i in range(0, len(session.turns) - 1, 2):
                user_turn = session.turns[i]
                aria_turn = session.turns[i + 1] if i + 1 < len(session.turns) else None

                if aria_turn:
                    content = f"[{self.config.user_persona.name}]: {user_turn.content[:200]}\n"
                    content += f"[ARIA]: {aria_turn.content[:200]}"

                    from core.memory.memory_v2 import EmotionalTone, MemoryOrigin

                    # Build tags with common coherence tags for SWR connection discovery
                    # The shared COMMON_COHERENCE_TAGS increase Jaccard similarity between
                    # memories, enabling the consolidation system to discover connections
                    memory_tags = [f"day_{session.day_number}"] + COMMON_COHERENCE_TAGS

                    self.memory_system.experience(
                        content=content,
                        emotional_tone=EmotionalTone.CONNECTED,
                        emotional_intensity=0.6,
                        # Include both ARIA and user for people-based connection bonus (+0.3 per shared person)
                        involves=["ARIA", self.config.user_persona.name],
                        importance=0.6,
                        context=f"Coherence test - Day {session.day_number}",
                        tags=memory_tags,
                        origin=MemoryOrigin.LIVED
                    )
        except Exception as e:
            print(f"[WARN] Could not store session in memory: {e}")

    def _calculate_day_metrics(self, session: DaySession) -> Dict[str, float]:
        """Calculate metrics for a single day"""
        scores = self.metrics.personality_consistency_scores[-len(session.turns)//2:]

        return {
            "day": session.day_number,
            "turns": len(session.turns),
            "avg_personality_consistency": sum(scores) / len(scores) if scores else 0.5,
            "recall_attempts": sum(1 for t in session.turns if t.metadata.get("expected_recall")),
            "timestamp": session.real_timestamp
        }

    def _generate_report(self):
        """Generate comprehensive coherence report"""
        report_path = os.path.join(self.config.output_dir, "coherence_report.md")

        # Calculate final metrics
        self.metrics.calculate_overall()

        report = f"""# ARIA Multi-Day Coherence Test Report

## Test Configuration

| Parameter | Value |
|-----------|-------|
| Simulated Days | {self.config.simulated_days} |
| User Persona | {self.config.user_persona.name} |
| LLM Provider | {self.llm.name if self.llm else 'None'} |
| Test Date | {datetime.now().strftime('%Y-%m-%d %H:%M')} |

## Overall Coherence Score: {self.metrics.overall_coherence_score:.1%}

## Memory Recall Performance

| Metric | Value |
|--------|-------|
| Recall Attempts | {self.metrics.memory_recall_attempts} |
| Recall Successes | {self.metrics.memory_recall_successes} |
| Recall Accuracy | {self.metrics.memory_recall_accuracy:.1%} |

## Personality Consistency

| Metric | Value |
|--------|-------|
| Average Score | {sum(self.metrics.personality_consistency_scores) / len(self.metrics.personality_consistency_scores) if self.metrics.personality_consistency_scores else 0:.2f} |
| Contradictions Detected | {self.metrics.contradiction_count} |

## Daily Performance

| Day | Turns | Avg Consistency |
|-----|-------|-----------------|
"""
        for day_metric in self.metrics.daily_scores:
            report += f"| {day_metric['day']} | {day_metric['turns']} | {day_metric['avg_personality_consistency']:.2f} |\n"

        # Calculate personality consistency for report
        avg_personality = (
            sum(self.metrics.personality_consistency_scores) / len(self.metrics.personality_consistency_scores)
            if self.metrics.personality_consistency_scores else 0.0
        )
        personality_pass = "PASS" if avg_personality >= self.config.min_personality_consistency else "NEEDS IMPROVEMENT"

        report += f"""

## Conclusions

1. **Memory Recall**: {'PASS' if self.metrics.memory_recall_accuracy >= self.config.min_recall_accuracy else 'NEEDS IMPROVEMENT'} ({self.metrics.memory_recall_accuracy:.1%} vs {self.config.min_recall_accuracy:.1%} threshold)

2. **Personality Consistency**: {personality_pass} ({avg_personality:.1%} vs {self.config.min_personality_consistency:.1%} threshold)

3. **Overall Coherence**: {self.metrics.overall_coherence_score:.1%}

---
Generated: {datetime.now().isoformat()}
ARIA Coherence Test v1.0
"""

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)

        print(f"\n[INFO] Report saved to: {report_path}")

        # Also save detailed JSON data
        data_path = os.path.join(self.config.output_dir, "coherence_data.json")
        data = {
            "config": asdict(self.config.user_persona),
            "metrics": asdict(self.metrics),
            "sessions": [
                {
                    "day": s.day_number,
                    "date": s.simulated_date,
                    "turns": [asdict(t) for t in s.turns],
                    "metrics": s.day_metrics
                }
                for s in self.sessions
            ]
        }

        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)

    def _print_summary(self):
        """Print test summary to console"""
        avg_personality = (
            sum(self.metrics.personality_consistency_scores) / len(self.metrics.personality_consistency_scores)
            if self.metrics.personality_consistency_scores else 0.0
        )
        print("\n" + "=" * 70)
        print("  TEST SUMMARY")
        print("=" * 70)
        print(f"  Overall Coherence Score: {self.metrics.overall_coherence_score:.1%}")
        print(f"  Memory Recall Accuracy: {self.metrics.memory_recall_accuracy:.1%}")
        print(f"  Personality Consistency: {avg_personality:.1%}")
        print(f"  Contradictions: {self.metrics.contradiction_count}")
        print(f"  Total Sessions: {len(self.sessions)}")
        print("=" * 70)


# =============================================================================
# CLI
# =============================================================================

def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="ARIA Multi-Day Coherence Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/coherence_test.py --duration 7 --verbose
  python scripts/coherence_test.py --scenarios scenarios/basic.yaml
  python scripts/coherence_test.py --user-persona "curious friend" --provider deepseek
  python scripts/coherence_test.py --quick-test  # 3-day quick test
        """
    )

    parser.add_argument(
        "--duration", "-d",
        type=int,
        default=7,
        help="Number of simulated days (default: 7)"
    )

    parser.add_argument(
        "--scenarios", "-s",
        type=str,
        default=None,
        help="Path to scenarios YAML file"
    )

    parser.add_argument(
        "--user-persona", "-u",
        type=str,
        default="curious friend",
        help="User persona description (default: 'curious friend')"
    )

    parser.add_argument(
        "--provider", "-p",
        type=str,
        default=None,
        choices=["anthropic", "openai", "deepseek", "ollama"],
        help="LLM provider (default: auto-detect)"
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        default="logs/coherence_test",
        help="Output directory for results"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output"
    )

    parser.add_argument(
        "--quick-test",
        action="store_true",
        help="Run a quick 3-day test"
    )

    parser.add_argument(
        "--no-consolidation",
        action="store_true",
        help="Disable consolidation between days"
    )

    parser.add_argument(
        "--messages-per-day",
        type=str,
        default="3-8",
        help="Range of messages per day (e.g., '3-8', default: '3-8')"
    )

    return parser.parse_args()


def main():
    """Main entry point"""
    args = parse_arguments()

    # Parse messages per day range
    try:
        min_msg, max_msg = map(int, args.messages_per_day.split('-'))
    except ValueError:
        min_msg, max_msg = 3, 8

    # Create user persona
    persona = UserPersona(
        name="TestUser",
        personality=args.user_persona,
        interests=["AI", "consciousness", "philosophy"],
        communication_style="conversational and curious"
    )

    # Create configuration
    config = TestConfig(
        simulated_days=3 if args.quick_test else args.duration,
        messages_per_day_range=(min_msg, max_msg),
        consolidation_between_days=not args.no_consolidation,
        user_persona=persona,
        llm_provider=args.provider,
        output_dir=args.output,
        verbose=args.verbose
    )

    # Create and run orchestrator
    orchestrator = CoherenceTestOrchestrator(config)
    success = orchestrator.run()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
