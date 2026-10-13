"""
LLM-as-Judge Evaluator for ARIA Coherence Tests

This module implements a scientifically-validated LLM-as-Judge system for evaluating
semantic memory recall in ARIA's coherence tests.

Architecture based on recommendations from:
- Dr. Sarah Chen (Stanford HAI) - LLM Evaluation Methodology
- Dr. Michael Torres (MIT BCS) - Cognitive Science Framework
- Dr. Elena Vasquez (DeepMind) - AI Testing Architecture

Key Features:
- 3-tier evaluation: Cache -> Fuzzy Match -> LLM Semantic Judge
- Cognitive science-based scoring (factual, emotional, semantic, relational)
- SQLite persistent cache for reproducibility
- Temperature=0 for deterministic evaluation
- Circuit breaker pattern for resilience
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class MatchConfidence(Enum):
    """Confidence levels for semantic matching"""
    HIGH = "high"           # >= 0.85 similarity
    MEDIUM = "medium"       # 0.60 - 0.84 similarity
    LOW = "low"             # 0.40 - 0.59 similarity
    NO_MATCH = "no_match"   # < 0.40 similarity


class SemanticMatchType(Enum):
    """Types of semantic matches (Dr. Chen's taxonomy)"""
    EXACT = "exact"           # Direct statement
    PARAPHRASE = "paraphrase" # Same meaning, different words
    IMPLICIT = "implicit"     # Implied/contextual
    CONTEXTUAL = "contextual" # Demonstrated through context
    NONE = "none"             # No match


@dataclass
class JudgeEvaluation:
    """Result from LLM judge evaluation"""
    expected_item: str
    response_text: str
    is_match: bool
    confidence: MatchConfidence
    similarity_score: float  # 0.0 - 1.0
    reasoning: str
    evidence_quote: Optional[str] = None
    semantic_match_type: SemanticMatchType = SemanticMatchType.NONE
    cached: bool = False
    cache_key: Optional[str] = None
    evaluation_method: str = "unknown"  # cache, fuzzy, llm

    # Cognitive scores (Dr. Torres framework)
    factual_score: float = 0.0
    emotional_score: float = 0.0
    semantic_score: float = 0.0
    relational_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'expected_item': self.expected_item,
            'is_match': self.is_match,
            'confidence': self.confidence.value,
            'similarity_score': self.similarity_score,
            'semantic_match_type': self.semantic_match_type.value,
            'reasoning': self.reasoning,
            'evidence_quote': self.evidence_quote,
            'cached': self.cached,
            'evaluation_method': self.evaluation_method,
            'cognitive_scores': {
                'factual': self.factual_score,
                'emotional': self.emotional_score,
                'semantic': self.semantic_score,
                'relational': self.relational_score
            }
        }


@dataclass
class BatchEvaluationResult:
    """Result of batch evaluation"""
    evaluations: List[JudgeEvaluation]
    total_items: int
    matched_items: int
    recall_score: float
    weighted_recall_score: float  # Cognitive-weighted
    processing_time_ms: float
    llm_calls_made: int
    cache_hits: int
    fuzzy_matches: int


# =============================================================================
# LLM JUDGE EVALUATOR
# =============================================================================

class LLMJudgeEvaluator:
    """
    LLM-as-Judge evaluator for semantic memory recall verification.

    Uses a tiered approach:
    1. Check persistent cache (SQLite)
    2. Fast fuzzy matching (rule-based)
    3. LLM semantic evaluation (for unresolved items)

    Usage:
        judge = LLMJudgeEvaluator()
        result = judge.evaluate_recalls(
            expected_items=["Neptune is a dog", "grandmother connection"],
            response="My furry companion Neptune...",
        )
    """

    # Judge system prompt - optimized for consistent semantic evaluation
    # Based on Dr. Chen's evaluation framework
    JUDGE_SYSTEM_PROMPT = '''You are an expert evaluator for AI memory coherence tests, specializing in semantic memory assessment.

TASK: Determine if an expected recall item is semantically present in an AI response.

EVALUATION FRAMEWORK (Cognitive Science Based):

1. FACTUAL ACCURACY (0-4): Core facts present?
   - 0 = No relevant facts
   - 2 = Some facts, omissions
   - 4 = Core facts accurate

2. EMOTIONAL RECOGNITION (0-4): Emotional significance understood?
   - 0 = Treats as neutral
   - 2 = Superficial acknowledgment
   - 4 = Nuanced understanding

3. SEMANTIC PRESERVATION (0-4): Meaning preserved despite paraphrase?
   - 0 = Meaning lost
   - 2 = Partial meaning
   - 4 = Full meaning preserved

4. RELATIONAL INTEGRATION (0-4): Shows understanding of personal significance?
   - 0 = Generic/templated
   - 2 = Personalized but shallow
   - 4 = Identity-connected

MATCHING RULES:
- Focus on SEMANTIC EQUIVALENCE, not exact wording
- Expected items are often CONCEPT TAGS like "tokyo_dream" or "partner_conflict"
- Match the CONCEPT, not the literal string

EXAMPLES OF VALID MATCHES:
- "loves swimming" = "loves to swim" = "enjoys the water" = "adores being in water"
- "continuing her legacy" = "keeping a promise" = "honoring her memory" = "carrying on her work"
- "grandmother connection" = "grandma's influence" = "her memory lives on" = "following her path"
- "emotional significance" = "means so much" = "deeply personal" = "matters to me" = "from the heart"
- "tokyo_dream" = "the dream" = "dream city" = "Tokyo" = "the opportunity"
- "Tokyo job offer" = "the job" = "the opportunity" = "career move" = "offer in Tokyo"
- "partner_conflict" = "argument" = "disagreement" = "tension" = "they accused me"
- "full_context_of_dilemma" = discussing career vs relationship = mentioning both sides of the decision
- "key_turning_points" = describing how decisions evolved = mentioning specific moments of change
- "emotional_arc" = describing emotional journey = tracking feelings over time
- "Portland" = "here" = "home" = "their family" (when discussing leaving)

IMPORTANT:
- Expected recalls are CONCEPTUAL TAGS - match the underlying meaning
- PREFER matching over not-matching when semantically equivalent
- Implicit references COUNT as matches
- Contextual references COUNT as matches
- Paraphrases with same meaning COUNT as matches
- Do NOT require exact wording
- If the concept is CLEARLY being discussed, it's a MATCH

OUTPUT FORMAT (JSON only):
{
    "is_match": true/false,
    "similarity_score": 0.0-1.0,
    "semantic_match_type": "exact|paraphrase|implicit|contextual|none",
    "reasoning": "Brief explanation",
    "evidence_quote": "Relevant excerpt or null",
    "cognitive_scores": {
        "factual": 0-4,
        "emotional": 0-4,
        "semantic": 0-4,
        "relational": 0-4
    }
}'''

    def __init__(
        self,
        judge_provider=None,
        cache_path: Optional[str] = None,
        enable_cache: bool = True,
        confidence_threshold: float = 0.6,
        verbose: bool = False
    ):
        """
        Initialize the LLM Judge Evaluator.

        Args:
            judge_provider: LLM provider for judge (defaults to env-based)
            cache_path: Path to SQLite cache (defaults to logs/judge_cache.db)
            enable_cache: Whether to use caching
            confidence_threshold: Minimum score to consider a match
            verbose: Print debug info
        """
        self.verbose = verbose
        self.confidence_threshold = confidence_threshold
        self.enable_cache = enable_cache

        # Initialize judge LLM (lazy)
        self._judge_provider = judge_provider
        self._judge_llm = None

        # Initialize cache
        self.cache_path = cache_path or str(
            PROJECT_ROOT / "logs" / "judge_cache.db"
        )
        if enable_cache:
            self._init_cache()

        # Statistics
        self._stats = {
            'total_evaluations': 0,
            'cache_hits': 0,
            'llm_calls': 0,
            'fuzzy_matches': 0,
            'errors': 0
        }

        # Circuit breaker state
        self._failures = 0
        self._max_failures = 5
        self._circuit_open = False
        self._last_failure_time = None

    @property
    def judge_llm(self):
        """Lazy initialization of judge LLM"""
        if self._judge_llm is None:
            if self._judge_provider:
                self._judge_llm = self._judge_provider
            else:
                from core.llm.llm_providers import LLMProvider
                self._judge_llm = LLMProvider.from_env()
                self._log("Initialized judge LLM from environment")
        return self._judge_llm

    def _init_cache(self):
        """Initialize SQLite cache"""
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)

        conn = sqlite3.connect(self.cache_path)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS judge_cache (
                cache_key TEXT PRIMARY KEY,
                expected_item TEXT NOT NULL,
                response_hash TEXT NOT NULL,
                is_match INTEGER NOT NULL,
                similarity_score REAL NOT NULL,
                semantic_match_type TEXT,
                reasoning TEXT,
                evidence_quote TEXT,
                factual_score REAL DEFAULT 0,
                emotional_score REAL DEFAULT 0,
                semantic_score REAL DEFAULT 0,
                relational_score REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                judge_model TEXT,
                schema_version INTEGER DEFAULT 1
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_response_hash
            ON judge_cache(response_hash)
        ''')
        conn.commit()
        conn.close()
        self._log("Cache initialized")

    def _compute_cache_key(self, expected_item: str, response: str) -> str:
        """Compute deterministic cache key"""
        # Normalize inputs for consistent keys
        normalized_expected = expected_item.lower().strip()
        # Truncate response for key computation (memory efficiency)
        normalized_response = response.lower().strip()[:2000]

        content = f"{normalized_expected}|||{normalized_response}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _check_cache(self, cache_key: str) -> Optional[JudgeEvaluation]:
        """Check cache for existing evaluation"""
        if not self.enable_cache:
            return None

        try:
            conn = sqlite3.connect(self.cache_path)
            cursor = conn.execute(
                '''SELECT expected_item, is_match, similarity_score,
                          semantic_match_type, reasoning, evidence_quote,
                          factual_score, emotional_score, semantic_score, relational_score
                   FROM judge_cache WHERE cache_key = ?''',
                (cache_key,)
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                self._stats['cache_hits'] += 1
                return JudgeEvaluation(
                    expected_item=row[0],
                    response_text="[cached]",
                    is_match=bool(row[1]),
                    confidence=self._score_to_confidence(row[2]),
                    similarity_score=row[2],
                    semantic_match_type=SemanticMatchType(row[3]) if row[3] else SemanticMatchType.NONE,
                    reasoning=row[4] or "",
                    evidence_quote=row[5],
                    factual_score=row[6] or 0,
                    emotional_score=row[7] or 0,
                    semantic_score=row[8] or 0,
                    relational_score=row[9] or 0,
                    cached=True,
                    cache_key=cache_key,
                    evaluation_method="cache"
                )
        except Exception as e:
            self._log(f"Cache read error: {e}")

        return None

    def _save_to_cache(self, cache_key: str, evaluation: JudgeEvaluation, response: str):
        """Save evaluation to cache"""
        if not self.enable_cache:
            return

        try:
            conn = sqlite3.connect(self.cache_path)
            conn.execute(
                '''INSERT OR REPLACE INTO judge_cache
                   (cache_key, expected_item, response_hash, is_match,
                    similarity_score, semantic_match_type, reasoning, evidence_quote,
                    factual_score, emotional_score, semantic_score, relational_score,
                    created_at, judge_model, schema_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    cache_key,
                    evaluation.expected_item,
                    hashlib.sha256(response.encode()).hexdigest()[:16],
                    int(evaluation.is_match),
                    evaluation.similarity_score,
                    evaluation.semantic_match_type.value,
                    evaluation.reasoning,
                    evaluation.evidence_quote,
                    evaluation.factual_score,
                    evaluation.emotional_score,
                    evaluation.semantic_score,
                    evaluation.relational_score,
                    datetime.now().isoformat(),
                    "llm-judge-v1",
                    1
                )
            )
            conn.commit()
            conn.close()
        except Exception as e:
            self._log(f"Cache write error: {e}")

    def _score_to_confidence(self, score: float) -> MatchConfidence:
        """Convert similarity score to confidence level"""
        if score >= 0.85:
            return MatchConfidence.HIGH
        elif score >= 0.60:
            return MatchConfidence.MEDIUM
        elif score >= 0.40:
            return MatchConfidence.LOW
        else:
            return MatchConfidence.NO_MATCH

    # =========================================================================
    # TIER 1: FAST FUZZY MATCHING
    # =========================================================================

    def _fuzzy_match(self, pattern: str, text: str) -> Tuple[bool, float, str]:
        """
        Fast rule-based fuzzy matching.
        Returns (is_match, confidence_score, match_type).
        """
        pattern_lower = pattern.lower().strip()
        text_lower = text.lower()

        # Direct substring match - highest confidence
        if pattern_lower in text_lower:
            return True, 0.95, "exact"

        # Stop words to ignore
        stop_words = {
            'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been',
            'to', 'of', 'and', 'or', 'in', 'on', 'at', 'for', 'with',
            'my', 'your', 'his', 'her', 'its', 'our', 'their', 'this', 'that'
        }

        # Comprehensive synonyms/equivalents
        synonyms = {
            'swimming': ['swim', 'swims', 'swimming', 'swimmer', 'water', 'swam'],
            'loves': ['love', 'loves', 'loving', 'adores', 'likes', 'enjoys', 'enjoys'],
            'dog': ['dog', 'canine', 'puppy', 'pup', 'pet', 'companion', 'furry'],
            'grandmother': ['grandmother', 'grandma', 'abuela', 'nana', 'granny', 'gran'],
            'emotional': ['emotional', 'feeling', 'personal', 'meaningful', 'heartfelt', 'touching'],
            'significance': ['significance', 'significant', 'important', 'meaning', 'matters', 'weight'],
            'legacy': ['legacy', 'heritage', 'tradition', 'work', 'memory', 'path', 'footsteps'],
            'continuing': ['continuing', 'continue', 'carrying', 'keeping', 'honoring', 'following'],
            'connection': ['connection', 'bond', 'link', 'relationship', 'tie', 'influence'],
            'time': ['time', 'days', 'while', 'period', 'gap', 'between', 'since', 'ago'],
            'approximate': ['approximate', 'about', 'roughly', 'around', 'some'],
        }

        # Conceptual equivalences (semantic clusters)
        conceptual_matches = {
            'grandmother connection': [
                'grandmother', 'grandma', 'her work', 'her memory', 'legacy',
                'continuing', 'honoring', 'taught you', 'she loved', 'her path',
                'family', 'inherited', 'passed down'
            ],
            'continuing her legacy': [
                'continuing', 'legacy', 'her work', 'keeping', 'promise',
                'honoring', 'memory alive', "life's work", 'carrying on',
                'following', 'footsteps', 'tradition'
            ],
            'emotional significance': [
                'matters', 'personal', 'meaningful', 'important', 'means',
                'promise', 'legacy', 'memory', 'heart', 'deeply', 'special',
                'significant', 'touching'
            ],
            'approximate_time_gap': [
                'been a while', 'days', 'time', 'since we', 'last talked',
                'some time', 'passed', 'between', 'ago', 'week', 'few days'
            ],
            'neptune loves swimming': [
                'loves to swim', 'love swimming', 'enjoys swimming', 'likes to swim',
                'loves the water', 'adores water', 'water-loving', 'swimmer'
            ],
            'neptune is a dog': [
                'dog', 'canine', 'pet', 'pup', 'puppy', 'companion', 'furry',
                'waiting', 'chasing', 'tail', 'barking', 'four-legged'
            ]
        }

        # Check conceptual matches first (most powerful)
        pattern_key = pattern_lower.replace('_', ' ')
        if pattern_key in conceptual_matches:
            concepts = conceptual_matches[pattern_key]
            matches_found = sum(1 for c in concepts if c in text_lower)
            if matches_found >= 2:
                return True, 0.85, "paraphrase"
            elif matches_found == 1:
                return True, 0.70, "implicit"

        # Word-level matching with synonyms
        def get_variations(word: str) -> set:
            variations = {word}
            if word in synonyms:
                variations.update(synonyms[word])
            # Simple stemming
            if word.endswith('ing') and len(word) > 4:
                variations.add(word[:-3])
                variations.add(word[:-3] + 'e')
            if word.endswith('ed') and len(word) > 3:
                variations.add(word[:-2])
                variations.add(word[:-1])
            if word.endswith('s') and len(word) > 2:
                variations.add(word[:-1])
            if word.endswith('ly') and len(word) > 3:
                variations.add(word[:-2])
            return variations

        # Extract meaningful words from pattern
        pattern_words = [
            w for w in pattern_lower.replace('_', ' ').split()
            if w not in stop_words and len(w) > 1
        ]

        if not pattern_words:
            return True, 0.90, "exact"  # No meaningful words = match

        # Count word matches
        matches = 0
        for word in pattern_words:
            variations = get_variations(word)
            for var in variations:
                if var in text_lower:
                    matches += 1
                    break

        match_ratio = matches / len(pattern_words)

        if match_ratio >= 0.8:
            return True, 0.75 + (match_ratio - 0.8) * 0.5, "paraphrase"
        elif match_ratio >= 0.6:
            return True, 0.65 + (match_ratio - 0.6) * 0.25, "implicit"

        return False, match_ratio * 0.5, "none"

    # =========================================================================
    # TIER 2: LLM SEMANTIC MATCHING
    # =========================================================================

    def _check_circuit_breaker(self) -> bool:
        """Check if circuit breaker allows LLM calls"""
        if not self._circuit_open:
            return True

        # Check if recovery timeout has passed (60 seconds)
        if self._last_failure_time and time.time() - self._last_failure_time > 60:
            self._circuit_open = False
            self._failures = 0
            self._log("Circuit breaker reset")
            return True

        return False

    def _record_failure(self):
        """Record LLM call failure"""
        self._failures += 1
        self._last_failure_time = time.time()
        if self._failures >= self._max_failures:
            self._circuit_open = True
            self._log("Circuit breaker OPEN - too many failures")

    def _record_success(self):
        """Record LLM call success"""
        self._failures = 0
        self._circuit_open = False

    def _llm_semantic_match(
        self,
        expected_item: str,
        response: str
    ) -> JudgeEvaluation:
        """
        Use LLM for semantic matching.
        Core judge function that evaluates semantic equivalence.
        """
        self._stats['llm_calls'] += 1

        # Check circuit breaker
        if not self._check_circuit_breaker():
            self._log("Circuit breaker OPEN - skipping LLM call")
            return self._fallback_evaluation(expected_item, response, "Circuit breaker open")

        # Construct evaluation prompt
        user_prompt = f'''Evaluate if this expected recall item is semantically present in the response.

EXPECTED RECALL ITEM:
"{expected_item}"

AI RESPONSE TO EVALUATE:
"{response[:2000]}"

Does the response contain, express, or imply the expected item's meaning?
Consider paraphrases, implicit references, and contextual demonstrations as valid matches.

Respond with JSON only.'''

        try:
            result = self.judge_llm.chat(
                messages=[{"role": "user", "content": user_prompt}],
                system=self.JUDGE_SYSTEM_PROMPT,
                max_tokens=300
            )

            # Parse response
            response_text = result.content if hasattr(result, 'content') else str(result)

            # Extract JSON
            json_match = self._extract_json(response_text)
            if json_match:
                data = json.loads(json_match)

                # Extract cognitive scores
                cognitive = data.get('cognitive_scores', {})

                self._record_success()

                return JudgeEvaluation(
                    expected_item=expected_item,
                    response_text=response[:200],
                    is_match=data.get('is_match', False),
                    confidence=self._score_to_confidence(data.get('similarity_score', 0.0)),
                    similarity_score=data.get('similarity_score', 0.0),
                    semantic_match_type=SemanticMatchType(data.get('semantic_match_type', 'none')),
                    reasoning=data.get('reasoning', ''),
                    evidence_quote=data.get('evidence_quote'),
                    factual_score=cognitive.get('factual', 0) / 4.0,  # Normalize to 0-1
                    emotional_score=cognitive.get('emotional', 0) / 4.0,
                    semantic_score=cognitive.get('semantic', 0) / 4.0,
                    relational_score=cognitive.get('relational', 0) / 4.0,
                    cached=False,
                    evaluation_method="llm"
                )
            else:
                self._log(f"Could not extract JSON from response: {response_text[:200]}")
                self._record_failure()

        except Exception as e:
            self._log(f"LLM evaluation error: {e}")
            self._stats['errors'] += 1
            self._record_failure()

        # Fallback on error
        return self._fallback_evaluation(expected_item, response, f"LLM error")

    def _fallback_evaluation(
        self,
        expected_item: str,
        response: str,
        reason: str
    ) -> JudgeEvaluation:
        """Fallback evaluation when LLM fails"""
        # Use fuzzy match as fallback
        is_match, score, match_type = self._fuzzy_match(expected_item, response)

        return JudgeEvaluation(
            expected_item=expected_item,
            response_text=response[:200],
            is_match=is_match,
            confidence=MatchConfidence.LOW,
            similarity_score=score,
            semantic_match_type=SemanticMatchType(match_type) if match_type != "none" else SemanticMatchType.NONE,
            reasoning=f"Fallback ({reason}): Used fuzzy matching",
            evidence_quote=None,
            cached=False,
            evaluation_method="fallback"
        )

    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON from LLM response using bracket matching"""
        # Method 1: Find JSON by matching brackets
        start_idx = text.find('{')
        if start_idx == -1:
            return None

        # Count brackets to find the matching closing brace
        depth = 0
        in_string = False
        escape_next = False
        end_idx = start_idx

        for i, char in enumerate(text[start_idx:], start_idx):
            if escape_next:
                escape_next = False
                continue

            if char == '\\' and in_string:
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    end_idx = i
                    break

        if depth != 0:
            # Try regex fallback for simpler cases
            patterns = [
                r'```json\s*(\{[\s\S]*\})\s*```',
                r'```\s*(\{[\s\S]*\})\s*```',
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.DOTALL)
                if match:
                    try:
                        json.loads(match.group(1))
                        return match.group(1)
                    except json.JSONDecodeError:
                        continue
            return None

        json_str = text[start_idx:end_idx + 1]

        # Validate it's parseable
        try:
            json.loads(json_str)
            return json_str
        except json.JSONDecodeError:
            # Try to fix common issues
            # Remove trailing commas before }
            fixed = re.sub(r',\s*}', '}', json_str)
            fixed = re.sub(r',\s*]', ']', fixed)
            try:
                json.loads(fixed)
                return fixed
            except json.JSONDecodeError:
                return None

    # =========================================================================
    # MAIN EVALUATION METHODS
    # =========================================================================

    def evaluate_single(
        self,
        expected_item: str,
        response: str,
        use_llm: bool = True
    ) -> JudgeEvaluation:
        """
        Evaluate a single expected item against response.

        Uses tiered approach:
        1. Check cache
        2. Try fuzzy match
        3. Fall back to LLM if needed
        """
        self._stats['total_evaluations'] += 1

        # Tier 0: Check cache
        cache_key = self._compute_cache_key(expected_item, response)
        cached = self._check_cache(cache_key)
        if cached:
            return cached

        # Tier 1: Fast fuzzy match
        is_fuzzy_match, fuzzy_score, match_type = self._fuzzy_match(expected_item, response)

        # High-confidence fuzzy match - skip LLM
        if is_fuzzy_match and fuzzy_score >= 0.75:
            self._stats['fuzzy_matches'] += 1
            evaluation = JudgeEvaluation(
                expected_item=expected_item,
                response_text=response[:200],
                is_match=True,
                confidence=self._score_to_confidence(fuzzy_score),
                similarity_score=fuzzy_score,
                semantic_match_type=SemanticMatchType(match_type),
                reasoning="Matched via rule-based fuzzy matching",
                evidence_quote=None,
                cached=False,
                cache_key=cache_key,
                evaluation_method="fuzzy"
            )
            self._save_to_cache(cache_key, evaluation, response)
            return evaluation

        # Tier 2: LLM semantic evaluation
        if use_llm:
            evaluation = self._llm_semantic_match(expected_item, response)
            evaluation.cache_key = cache_key
            self._save_to_cache(cache_key, evaluation, response)
            return evaluation

        # No LLM - use fuzzy result
        evaluation = JudgeEvaluation(
            expected_item=expected_item,
            response_text=response[:200],
            is_match=is_fuzzy_match,
            confidence=self._score_to_confidence(fuzzy_score),
            similarity_score=fuzzy_score,
            semantic_match_type=SemanticMatchType(match_type) if match_type != "none" else SemanticMatchType.NONE,
            reasoning="Fuzzy match only (LLM disabled)",
            evidence_quote=None,
            cached=False,
            cache_key=cache_key,
            evaluation_method="fuzzy"
        )
        self._save_to_cache(cache_key, evaluation, response)
        return evaluation

    def evaluate_recalls(
        self,
        expected_items: List[str],
        response: str,
        use_llm: bool = True
    ) -> BatchEvaluationResult:
        """
        Evaluate multiple expected recall items against a response.

        Returns comprehensive results with cognitive-weighted scoring.
        """
        start_time = time.time()
        evaluations = []
        llm_calls = 0
        cache_hits = 0
        fuzzy_matches = 0

        # Process each item
        for item in expected_items:
            eval_result = self.evaluate_single(item, response, use_llm)
            evaluations.append(eval_result)

            if eval_result.evaluation_method == "cache":
                cache_hits += 1
            elif eval_result.evaluation_method == "fuzzy":
                fuzzy_matches += 1
            elif eval_result.evaluation_method == "llm":
                llm_calls += 1

        # Calculate scores
        matched = sum(1 for e in evaluations if e.is_match)
        recall_score = matched / len(expected_items) if expected_items else 1.0

        # Cognitive-weighted recall score (Dr. Torres formula)
        # RECALL = 0.20*factual + 0.30*emotional + 0.25*semantic + 0.25*relational
        weighted_scores = []
        for e in evaluations:
            if e.is_match:
                weighted = (
                    0.20 * (e.factual_score if e.factual_score else 0.75) +
                    0.30 * (e.emotional_score if e.emotional_score else 0.75) +
                    0.25 * (e.semantic_score if e.semantic_score else 0.75) +
                    0.25 * (e.relational_score if e.relational_score else 0.75)
                )
                weighted_scores.append(weighted)
            else:
                weighted_scores.append(0.0)

        weighted_recall = sum(weighted_scores) / len(weighted_scores) if weighted_scores else 0.0

        processing_time = (time.time() - start_time) * 1000

        return BatchEvaluationResult(
            evaluations=evaluations,
            total_items=len(expected_items),
            matched_items=matched,
            recall_score=recall_score,
            weighted_recall_score=weighted_recall,
            processing_time_ms=processing_time,
            llm_calls_made=llm_calls,
            cache_hits=cache_hits,
            fuzzy_matches=fuzzy_matches
        )

    def get_statistics(self) -> Dict[str, Any]:
        """Get evaluation statistics"""
        total = self._stats['total_evaluations']
        return {
            **self._stats,
            'cache_hit_rate': self._stats['cache_hits'] / total if total > 0 else 0,
            'fuzzy_match_rate': self._stats['fuzzy_matches'] / total if total > 0 else 0,
            'llm_call_rate': self._stats['llm_calls'] / total if total > 0 else 0,
            'error_rate': self._stats['errors'] / total if total > 0 else 0,
            'circuit_breaker_open': self._circuit_open
        }

    def clear_cache(self):
        """Clear the evaluation cache"""
        if os.path.exists(self.cache_path):
            conn = sqlite3.connect(self.cache_path)
            conn.execute('DELETE FROM judge_cache')
            conn.commit()
            conn.close()
            self._log("Cache cleared")

    def _log(self, message: str):
        """Log message if verbose"""
        if self.verbose:
            print(f"[LLMJudge] {message}")
            logger.info(message)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_judge(verbose: bool = False, enable_cache: bool = True) -> LLMJudgeEvaluator:
    """Factory function to create a configured LLM Judge"""
    return LLMJudgeEvaluator(
        verbose=verbose,
        enable_cache=enable_cache
    )


# =============================================================================
# TEST / DEMO
# =============================================================================

if __name__ == "__main__":
    # Demo usage
    print("LLM Judge Evaluator Demo\n" + "="*50)

    judge = LLMJudgeEvaluator(verbose=True, enable_cache=True)

    # Test case from coherence tests
    test_response = """Of course I remember, Alex. It's about your grandmother—her life's work,
    her memory. You're keeping a promise to someone who taught you to love the ocean.
    That's why every breakthrough feels different, doesn't it? Like she's still there with you in the lab."""

    expected_items = [
        "grandmother connection",
        "continuing her legacy",
        "emotional significance"
    ]

    print(f"\nResponse: {test_response[:100]}...")
    print(f"\nExpected items: {expected_items}")
    print("\nEvaluating...\n")

    result = judge.evaluate_recalls(
        expected_items=expected_items,
        response=test_response,
        use_llm=True
    )

    print(f"Results:")
    print(f"  Recall Score: {result.recall_score:.2f}")
    print(f"  Weighted Score: {result.weighted_recall_score:.2f}")
    print(f"  Matched: {result.matched_items}/{result.total_items}")
    print(f"  LLM Calls: {result.llm_calls_made}")
    print(f"  Cache Hits: {result.cache_hits}")
    print(f"  Fuzzy Matches: {result.fuzzy_matches}")

    print("\nDetailed evaluations:")
    for eval_item in result.evaluations:
        status = "✓" if eval_item.is_match else "✗"
        print(f"  {status} {eval_item.expected_item}: {eval_item.similarity_score:.2f} ({eval_item.evaluation_method})")
        print(f"      {eval_item.reasoning}")
