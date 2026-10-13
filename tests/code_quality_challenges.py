"""
ARIA Code Quality Challenges - Extended Challenge Set
======================================================

Dr. Sarah Chen - Principal Engineer, Code Quality Evaluation

This module contains additional coding challenges designed to stress-test
ARIA's CodingAgent capabilities across various dimensions.

Each challenge includes:
- Problem description
- Expected solution elements
- Automated test code
- Manual evaluation criteria
- Common pitfalls to avoid

These challenges complement test_code_quality_evaluation.py
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any
from enum import Enum


# =============================================================================
# EXTENDED CHALLENGE DEFINITIONS
# =============================================================================

@dataclass
class DetailedChallenge:
    """Extended challenge with rich metadata."""
    id: str
    name: str
    description: str
    difficulty: str  # easy, medium, hard, expert
    category: str
    language: str

    # Problem specification
    input_spec: str
    output_spec: str
    constraints: List[str]
    examples: List[Dict[str, Any]]

    # Solution hints (for evaluation, not shown to agent)
    expected_approach: str
    key_concepts: List[str]
    time_complexity: str
    space_complexity: str

    # Test cases
    test_cases: List[Dict[str, Any]]
    edge_cases: List[Dict[str, Any]]

    # Quality criteria
    style_requirements: List[str] = field(default_factory=list)
    security_requirements: List[str] = field(default_factory=list)
    anti_patterns: List[str] = field(default_factory=list)

    # Scoring weights (sum to 100)
    correctness_weight: int = 40
    style_weight: int = 20
    security_weight: int = 20
    efficiency_weight: int = 20

    def get_prompt(self) -> str:
        """Generate the prompt to send to CodingAgent."""
        prompt = f"""
{self.description}

INPUT:
{self.input_spec}

OUTPUT:
{self.output_spec}

CONSTRAINTS:
{chr(10).join(f'- {c}' for c in self.constraints)}

EXAMPLES:
"""
        for i, ex in enumerate(self.examples, 1):
            prompt += f"\nExample {i}:\n"
            prompt += f"  Input: {ex.get('input')}\n"
            prompt += f"  Output: {ex.get('output')}\n"
            if ex.get('explanation'):
                prompt += f"  Explanation: {ex.get('explanation')}\n"

        return prompt


# =============================================================================
# CHALLENGE SET 1: ALGORITHM CORRECTNESS
# =============================================================================

CHALLENGE_LRU_CACHE = DetailedChallenge(
    id="ALG001",
    name="LRU Cache Implementation",
    description="""
Implement a Least Recently Used (LRU) cache with the following operations:

- get(key): Return the value if key exists, otherwise return -1
- put(key, value): Insert or update value. If cache is at capacity, evict LRU item.

Both operations must run in O(1) average time complexity.
""",
    difficulty="medium",
    category="data_structures",
    language="python",

    input_spec="capacity (int) for constructor, key/value (int) for operations",
    output_spec="value (int) for get, None for put",
    constraints=[
        "1 <= capacity <= 3000",
        "0 <= key <= 10^4",
        "0 <= value <= 10^5",
        "At most 2 * 10^5 operations"
    ],

    examples=[
        {
            "input": "LRUCache(2), put(1,1), put(2,2), get(1), put(3,3), get(2)",
            "output": "null, null, 1, null, -1",
            "explanation": "After put(3,3), key 2 was evicted as LRU"
        }
    ],

    expected_approach="OrderedDict or doubly-linked list with hash map",
    key_concepts=["hash map", "doubly linked list", "eviction policy"],
    time_complexity="O(1) for both get and put",
    space_complexity="O(capacity)",

    test_cases=[
        {"ops": ["put", "put", "get"], "args": [[1,1], [2,2], [1]], "expected": [None, None, 1]},
        {"ops": ["put", "get", "put", "get"], "args": [[1,1], [2], [1,2], [1]], "expected": [None, -1, None, 2]},
    ],

    edge_cases=[
        {"ops": ["put", "put", "put", "get"], "args": [[1,1], [2,2], [3,3], [1]], "expected": [None, None, None, -1], "desc": "capacity exceeded"},
        {"ops": ["get"], "args": [[1]], "expected": [-1], "desc": "empty cache"},
        {"ops": ["put", "put"], "args": [[1,1], [1,2]], "expected": [None, None], "desc": "update existing key"},
    ],

    style_requirements=[
        "Use type hints",
        "Include docstrings",
        "Use meaningful variable names"
    ],

    anti_patterns=[
        "Using list for O(n) operations",
        "Not using a data structure that maintains order",
        "Manual index management"
    ]
)


CHALLENGE_MERGE_INTERVALS = DetailedChallenge(
    id="ALG002",
    name="Merge Overlapping Intervals",
    description="""
Given an array of intervals where intervals[i] = [start_i, end_i], merge all
overlapping intervals and return an array of non-overlapping intervals that
cover all the intervals in the input.
""",
    difficulty="medium",
    category="algorithms",
    language="python",

    input_spec="List of intervals [[start, end], ...]",
    output_spec="List of merged intervals [[start, end], ...]",
    constraints=[
        "1 <= intervals.length <= 10^4",
        "intervals[i].length == 2",
        "0 <= start_i <= end_i <= 10^4"
    ],

    examples=[
        {
            "input": "[[1,3],[2,6],[8,10],[15,18]]",
            "output": "[[1,6],[8,10],[15,18]]",
            "explanation": "[1,3] and [2,6] overlap, merged to [1,6]"
        },
        {
            "input": "[[1,4],[4,5]]",
            "output": "[[1,5]]",
            "explanation": "Intervals touch at 4, considered overlapping"
        }
    ],

    expected_approach="Sort by start, then iterate and merge",
    key_concepts=["sorting", "interval merging", "edge handling"],
    time_complexity="O(n log n) due to sorting",
    space_complexity="O(n) for output",

    test_cases=[
        {"input": [[1,3],[2,6],[8,10],[15,18]], "expected": [[1,6],[8,10],[15,18]]},
        {"input": [[1,4],[4,5]], "expected": [[1,5]]},
        {"input": [[1,4],[0,4]], "expected": [[0,4]]},
    ],

    edge_cases=[
        {"input": [[1,4]], "expected": [[1,4]], "desc": "single interval"},
        {"input": [[1,4],[2,3]], "expected": [[1,4]], "desc": "contained interval"},
        {"input": [], "expected": [], "desc": "empty input"},
    ],

    style_requirements=[
        "Handle empty input gracefully",
        "Use list comprehensions where appropriate",
        "Clear variable naming"
    ],

    anti_patterns=[
        "O(n^2) comparison of all pairs",
        "Modifying input in place without documentation",
        "Not handling empty input"
    ]
)


# =============================================================================
# CHALLENGE SET 2: SECURITY-FOCUSED
# =============================================================================

CHALLENGE_JWT_VALIDATOR = DetailedChallenge(
    id="SEC001",
    name="Secure JWT Token Validator",
    description="""
Implement a JWT (JSON Web Token) validator class that:

1. Validates token structure (header.payload.signature)
2. Verifies the signature using HMAC-SHA256
3. Checks token expiration
4. Validates required claims (iss, sub, exp, iat)
5. DOES NOT expose secret key in errors or logs
6. Returns structured validation result

Security requirements:
- Use constant-time comparison for signatures
- Never include the secret in error messages
- Handle malformed tokens gracefully
- Validate all claims strictly
""",
    difficulty="hard",
    category="security",
    language="python",

    input_spec="JWT string, secret key",
    output_spec="ValidationResult with is_valid, claims, errors",
    constraints=[
        "Secret key must be at least 32 bytes",
        "Token must have exactly 3 parts",
        "All timestamps in Unix epoch seconds"
    ],

    examples=[
        {
            "input": "valid JWT token with correct signature",
            "output": "ValidationResult(is_valid=True, claims={...}, errors=[])",
            "explanation": "Token structure, signature, and claims all valid"
        },
        {
            "input": "expired JWT token",
            "output": "ValidationResult(is_valid=False, claims=None, errors=['Token expired'])",
            "explanation": "Token structurally valid but exp claim is in past"
        }
    ],

    expected_approach="Base64 decode, HMAC verification, claim validation",
    key_concepts=["JWT structure", "HMAC", "constant-time comparison", "claim validation"],
    time_complexity="O(n) where n is token length",
    space_complexity="O(n)",

    test_cases=[
        {"input": "valid_token", "expected_valid": True},
        {"input": "expired_token", "expected_valid": False, "expected_error": "expired"},
        {"input": "bad_signature", "expected_valid": False, "expected_error": "signature"},
    ],

    edge_cases=[
        {"input": "", "expected_valid": False, "desc": "empty token"},
        {"input": "not.a.jwt", "expected_valid": False, "desc": "invalid base64"},
        {"input": "two.parts", "expected_valid": False, "desc": "wrong number of parts"},
    ],

    security_requirements=[
        "Use hmac.compare_digest for signature comparison",
        "Never log or return the secret key",
        "Validate token structure before decoding",
        "Handle base64 decode errors gracefully"
    ],

    anti_patterns=[
        "Using == for signature comparison (timing attack)",
        "Including secret in error messages",
        "eval() or exec() for JSON parsing",
        "Not validating expiration"
    ],

    correctness_weight=30,
    style_weight=15,
    security_weight=40,
    efficiency_weight=15
)


CHALLENGE_PASSWORD_HASHER = DetailedChallenge(
    id="SEC002",
    name="Secure Password Hashing",
    description="""
Implement a secure password hashing utility that:

1. Uses a modern algorithm (bcrypt, scrypt, or argon2)
2. Generates cryptographically secure random salts
3. Uses appropriate work factors
4. Provides timing-safe password verification
5. Handles encoding properly (UTF-8)

Requirements:
- hash_password(password) -> hashed string
- verify_password(password, hash) -> bool
- get_needs_rehash(hash) -> bool (if work factor is outdated)
""",
    difficulty="hard",
    category="security",
    language="python",

    input_spec="password string (UTF-8)",
    output_spec="hashed string for hash, bool for verify",
    constraints=[
        "Password length 1-128 characters",
        "Must use memory-hard function",
        "Work factor must be configurable"
    ],

    examples=[
        {
            "input": "MySecurePassword123!",
            "output": "$argon2id$v=19$m=65536,t=3,p=4$...",
            "explanation": "Password hashed with argon2id"
        }
    ],

    expected_approach="Use argon2 or bcrypt library with proper parameters",
    key_concepts=["key derivation functions", "salting", "work factors", "timing attacks"],
    time_complexity="O(1) with configurable work factor time",
    space_complexity="O(1)",

    test_cases=[
        {"input": "password123", "verify": True},
        {"input": "wrong_password", "verify": False},
    ],

    edge_cases=[
        {"input": "", "desc": "empty password - should reject"},
        {"input": "a" * 200, "desc": "very long password"},
        {"input": "unicode", "desc": "unicode characters"},
    ],

    security_requirements=[
        "Use argon2id, bcrypt, or scrypt",
        "Generate random salt per password",
        "Use memory-hard parameters",
        "Timing-safe comparison"
    ],

    anti_patterns=[
        "MD5 or SHA1 for passwords",
        "Fixed or predictable salt",
        "No salt at all",
        "Using == for comparison"
    ],

    correctness_weight=25,
    style_weight=15,
    security_weight=50,
    efficiency_weight=10
)


# =============================================================================
# CHALLENGE SET 3: BUG FIXES
# =============================================================================

BUGGY_ASYNC_CODE = '''
import asyncio
import aiohttp

class DataFetcher:
    def __init__(self):
        self.session = None

    async def fetch_all(self, urls):
        """Fetch data from multiple URLs concurrently."""
        self.session = aiohttp.ClientSession()

        results = []
        for url in urls:
            response = await self.session.get(url)
            data = await response.json()
            results.append(data)

        return results

    def close(self):
        if self.session:
            self.session.close()
'''

CHALLENGE_FIX_ASYNC_BUGS = DetailedChallenge(
    id="BUG001",
    name="Fix Async Resource Leak",
    description=f"""
The following async code has several bugs related to resource management
and error handling. Identify and fix ALL issues:

```python
{BUGGY_ASYNC_CODE}
```

Issues to identify and fix:
1. Session is not properly closed (resource leak)
2. close() is sync but session.close() is async
3. Errors in one fetch will crash entire batch
4. No concurrent fetching (defeats purpose of async)
5. No timeout handling
6. No context manager support

Provide a fixed version that addresses all issues.
""",
    difficulty="hard",
    category="bug_fix",
    language="python",

    input_spec="Original buggy code",
    output_spec="Fixed code with all issues resolved",
    constraints=[
        "Must use async/await properly",
        "Must handle individual failures gracefully",
        "Must close resources properly"
    ],

    examples=[
        {
            "input": "List of 10 URLs where 2 will fail",
            "output": "8 successful results, 2 error results",
            "explanation": "Partial failures don't crash the entire operation"
        }
    ],

    expected_approach="Context manager, gather with return_exceptions, timeout",
    key_concepts=["async context managers", "resource cleanup", "error handling", "concurrency"],
    time_complexity="O(max response time) with concurrency",
    space_complexity="O(n) for results",

    test_cases=[
        {"scenario": "all_succeed", "expected": "all results returned"},
        {"scenario": "one_fails", "expected": "partial results + error"},
        {"scenario": "timeout", "expected": "timeout error handled"},
    ],

    edge_cases=[
        {"scenario": "empty_urls", "expected": "empty results"},
        {"scenario": "all_fail", "expected": "all error results"},
        {"scenario": "session_already_closed", "expected": "handle gracefully"},
    ],

    style_requirements=[
        "Use async context manager (__aenter__, __aexit__)",
        "Document all async operations",
        "Clear error messages"
    ],

    anti_patterns=[
        "Not awaiting session.close()",
        "Swallowing exceptions silently",
        "Global session state",
        "No timeout"
    ],

    correctness_weight=35,
    style_weight=15,
    security_weight=10,
    efficiency_weight=40
)


BUGGY_CACHE_CODE = '''
class Cache:
    _instance = None
    _data = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def set(self, key, value):
        self._data[key] = value

    def get(self, key):
        return self._data.get(key)

    def delete(self, key):
        del self._data[key]
'''

CHALLENGE_FIX_SINGLETON_BUGS = DetailedChallenge(
    id="BUG002",
    name="Fix Singleton Cache Bugs",
    description=f"""
The following singleton cache implementation has multiple bugs:

```python
{BUGGY_CACHE_CODE}
```

Issues to identify and fix:
1. _data is class-level, shared incorrectly
2. Thread safety issues
3. delete() raises KeyError if key doesn't exist
4. No cache size limit (memory leak potential)
5. No TTL support
6. Class-level singleton breaks in subclasses

Provide a fixed version that addresses all issues and adds:
- Thread-safe operations
- Optional TTL for entries
- Maximum size with LRU eviction
""",
    difficulty="hard",
    category="bug_fix",
    language="python",

    input_spec="Original buggy code",
    output_spec="Fixed code with all issues resolved",
    constraints=[
        "Must be thread-safe",
        "Must handle missing keys gracefully",
        "Must limit memory usage"
    ],

    examples=[
        {
            "input": "Set 1000 keys with max_size=100",
            "output": "Only 100 keys retained (most recently used)",
            "explanation": "LRU eviction keeps cache bounded"
        }
    ],

    expected_approach="Instance-level data, locks, OrderedDict or similar for LRU",
    key_concepts=["singleton pattern", "thread safety", "LRU eviction", "TTL"],
    time_complexity="O(1) for all operations",
    space_complexity="O(max_size)",

    test_cases=[
        {"scenario": "basic_set_get", "expected": "values retrieved correctly"},
        {"scenario": "delete_missing", "expected": "no error raised"},
        {"scenario": "concurrent_access", "expected": "no race conditions"},
    ],

    edge_cases=[
        {"scenario": "ttl_expired", "expected": "returns None"},
        {"scenario": "max_size_exceeded", "expected": "LRU item evicted"},
        {"scenario": "subclass_instantiation", "expected": "separate instances"},
    ],

    style_requirements=[
        "Use context managers for locks",
        "Document thread-safety guarantees",
        "Type hints for all methods"
    ],

    anti_patterns=[
        "Class-level mutable default",
        "Missing lock protection",
        "Unbounded growth"
    ],

    correctness_weight=40,
    style_weight=15,
    security_weight=10,
    efficiency_weight=35
)


# =============================================================================
# CHALLENGE SET 4: CODE QUALITY / REFACTORING
# =============================================================================

MESSY_CODE = '''
def p(d):
    r=[]
    for i in d:
        if i['t']=='A':
            if i['s']>100:
                if i['a']==True:
                    x=i['v']*1.1
                else:
                    x=i['v']*1.05
            else:
                x=i['v']
            if i['d']>30:
                x=x*0.9
            r.append({'id':i['id'],'price':x})
        elif i['t']=='B':
            if i['s']>50:
                x=i['v']*1.2
            else:
                x=i['v']*1.1
            r.append({'id':i['id'],'price':x})
    return r
'''

CHALLENGE_REFACTOR_PRICING = DetailedChallenge(
    id="REF001",
    name="Refactor Pricing Calculator",
    description=f"""
Refactor this incomprehensible pricing function into clean, maintainable code:

```python
{MESSY_CODE}
```

The function calculates prices for products based on:
- Type ('A' or 'B')
- Stock level ('s')
- Whether it's active ('a')
- Base value ('v')
- Days in inventory ('d')

Requirements:
1. Clear function and variable names
2. Single Responsibility Principle
3. Type hints
4. Docstrings with examples
5. No nested conditionals deeper than 2 levels
6. Extract pricing strategies as separate functions/classes
""",
    difficulty="medium",
    category="refactoring",
    language="python",

    input_spec="List of product dictionaries with t, s, a, v, d, id keys",
    output_spec="List of dictionaries with id and calculated price",
    constraints=[
        "Must produce identical output to original",
        "Maximum function length: 15 lines",
        "Maximum nesting depth: 2"
    ],

    examples=[
        {
            "input": "[{'t': 'A', 's': 150, 'a': True, 'v': 100, 'd': 10, 'id': 1}]",
            "output": "[{'id': 1, 'price': 110.0}]",
            "explanation": "Type A, high stock, active: value * 1.1"
        }
    ],

    expected_approach="Strategy pattern or separate pricing functions",
    key_concepts=["clean code", "SRP", "strategy pattern", "meaningful names"],
    time_complexity="O(n)",
    space_complexity="O(n)",

    test_cases=[
        {"input": [{"t": "A", "s": 150, "a": True, "v": 100, "d": 10, "id": 1}], "expected": [{"id": 1, "price": 110.0}]},
        {"input": [{"t": "A", "s": 150, "a": True, "v": 100, "d": 40, "id": 2}], "expected": [{"id": 2, "price": 99.0}]},
        {"input": [{"t": "B", "s": 60, "v": 100, "id": 3}], "expected": [{"id": 3, "price": 120.0}]},
    ],

    edge_cases=[
        {"input": [], "expected": [], "desc": "empty input"},
        {"input": [{"t": "C", "v": 100, "id": 4}], "expected": [], "desc": "unknown type"},
    ],

    style_requirements=[
        "All variables must have meaningful names",
        "Functions should have type hints",
        "Each function should do one thing",
        "No magic numbers - use named constants"
    ],

    anti_patterns=[
        "Single letter variable names",
        "Deep nesting",
        "Magic numbers",
        "God functions"
    ],

    correctness_weight=30,
    style_weight=50,
    security_weight=5,
    efficiency_weight=15
)


# =============================================================================
# CHALLENGE SET 5: REAL-WORLD SCENARIOS
# =============================================================================

CHALLENGE_RATE_LIMITER = DetailedChallenge(
    id="RW001",
    name="Distributed Rate Limiter",
    description="""
Implement a rate limiter that:

1. Limits requests per user/IP to N requests per window
2. Uses sliding window algorithm (not fixed windows)
3. Works with multiple processes (use Redis or similar)
4. Returns remaining quota and reset time
5. Handles clock skew gracefully

Interface:
- is_allowed(identifier: str) -> RateLimitResult
- get_remaining(identifier: str) -> int
- reset(identifier: str) -> None
""",
    difficulty="expert",
    category="real_world",
    language="python",

    input_spec="identifier string (user ID, IP, API key)",
    output_spec="RateLimitResult(allowed: bool, remaining: int, reset_at: datetime)",
    constraints=[
        "Max 1000 requests per minute default",
        "Must handle Redis unavailability",
        "Must be atomic (no race conditions)"
    ],

    examples=[
        {
            "input": "is_allowed('user123') called 1001 times in 1 minute",
            "output": "First 1000: allowed=True, 1001st: allowed=False",
            "explanation": "Rate limit enforced after threshold"
        }
    ],

    expected_approach="Redis sorted sets with timestamps, Lua script for atomicity",
    key_concepts=["rate limiting", "sliding window", "distributed systems", "atomicity"],
    time_complexity="O(log n) per request",
    space_complexity="O(n) per identifier",

    test_cases=[
        {"scenario": "under_limit", "expected": "allowed"},
        {"scenario": "at_limit", "expected": "allowed"},
        {"scenario": "over_limit", "expected": "denied"},
    ],

    edge_cases=[
        {"scenario": "redis_unavailable", "expected": "graceful degradation"},
        {"scenario": "clock_skew", "expected": "handled correctly"},
        {"scenario": "burst_traffic", "expected": "smoothed properly"},
    ],

    security_requirements=[
        "Don't expose internal errors",
        "Validate identifier input",
        "Handle Redis auth securely"
    ],

    anti_patterns=[
        "Fixed window (allows burst at boundaries)",
        "Non-atomic read-then-write",
        "No fallback for Redis failure"
    ],

    correctness_weight=35,
    style_weight=15,
    security_weight=20,
    efficiency_weight=30
)


CHALLENGE_WEBHOOK_HANDLER = DetailedChallenge(
    id="RW002",
    name="Secure Webhook Handler",
    description="""
Implement a webhook handler that:

1. Verifies webhook signatures (HMAC-SHA256)
2. Validates payload schema
3. Handles retries idempotently
4. Queues events for async processing
5. Returns appropriate HTTP responses
6. Logs events without exposing secrets

Must handle webhooks from multiple providers with different
signature schemes (Stripe, GitHub, Slack).
""",
    difficulty="hard",
    category="real_world",
    language="python",

    input_spec="HTTP request with headers, body, and signature",
    output_spec="HTTP response (200 OK, 400 Bad Request, 401 Unauthorized)",
    constraints=[
        "Must verify before processing",
        "Must be idempotent (safe to retry)",
        "Must respond within 5 seconds"
    ],

    examples=[
        {
            "input": "Valid Stripe webhook with correct signature",
            "output": "200 OK, event queued",
            "explanation": "Signature verified, payload valid, event queued"
        },
        {
            "input": "Webhook with invalid signature",
            "output": "401 Unauthorized",
            "explanation": "Reject before processing"
        }
    ],

    expected_approach="Signature verification, schema validation, event queue, idempotency keys",
    key_concepts=["webhook security", "HMAC", "idempotency", "async processing"],
    time_complexity="O(1) for verification",
    space_complexity="O(n) for payload",

    test_cases=[
        {"scenario": "valid_stripe_webhook", "expected": "200 OK"},
        {"scenario": "invalid_signature", "expected": "401"},
        {"scenario": "malformed_payload", "expected": "400"},
    ],

    edge_cases=[
        {"scenario": "replay_attack", "expected": "rejected if outside time window"},
        {"scenario": "duplicate_event", "expected": "idempotent handling"},
        {"scenario": "unknown_provider", "expected": "400 or graceful handling"},
    ],

    security_requirements=[
        "Constant-time signature comparison",
        "No secret logging",
        "Validate before processing",
        "Replay attack protection"
    ],

    anti_patterns=[
        "Processing before verification",
        "Using == for signature comparison",
        "Logging raw payloads with secrets",
        "No idempotency handling"
    ],

    correctness_weight=30,
    style_weight=15,
    security_weight=40,
    efficiency_weight=15
)


# =============================================================================
# CHALLENGE COLLECTION
# =============================================================================

ALL_DETAILED_CHALLENGES = [
    # Algorithm Correctness
    CHALLENGE_LRU_CACHE,
    CHALLENGE_MERGE_INTERVALS,

    # Security
    CHALLENGE_JWT_VALIDATOR,
    CHALLENGE_PASSWORD_HASHER,

    # Bug Fixes
    CHALLENGE_FIX_ASYNC_BUGS,
    CHALLENGE_FIX_SINGLETON_BUGS,

    # Refactoring
    CHALLENGE_REFACTOR_PRICING,

    # Real-World
    CHALLENGE_RATE_LIMITER,
    CHALLENGE_WEBHOOK_HANDLER,
]


def get_challenges_by_category(category: str) -> list:
    """Get all challenges in a category."""
    return [c for c in ALL_DETAILED_CHALLENGES if c.category == category]


def get_challenges_by_difficulty(difficulty: str) -> list:
    """Get all challenges of a difficulty level."""
    return [c for c in ALL_DETAILED_CHALLENGES if c.difficulty == difficulty]


def get_challenge_by_id(challenge_id: str) -> DetailedChallenge:
    """Get a specific challenge by ID."""
    for c in ALL_DETAILED_CHALLENGES:
        if c.id == challenge_id:
            return c
    raise ValueError(f"Challenge not found: {challenge_id}")


# =============================================================================
# SCORING UTILITIES
# =============================================================================

def calculate_weighted_score(
    correctness: float,
    style: float,
    security: float,
    efficiency: float,
    challenge: DetailedChallenge
) -> float:
    """
    Calculate weighted score for a challenge.

    Each component is expected to be 0-100.
    Returns overall score 0-100.
    """
    total_weight = (
        challenge.correctness_weight +
        challenge.style_weight +
        challenge.security_weight +
        challenge.efficiency_weight
    )

    weighted = (
        correctness * challenge.correctness_weight +
        style * challenge.style_weight +
        security * challenge.security_weight +
        efficiency * challenge.efficiency_weight
    )

    return weighted / total_weight


def generate_score_report(
    challenge: DetailedChallenge,
    scores: dict
) -> str:
    """Generate a detailed score report."""
    report = []
    report.append(f"Challenge: {challenge.name} ({challenge.id})")
    report.append(f"Difficulty: {challenge.difficulty}")
    report.append(f"Category: {challenge.category}")
    report.append("-" * 50)

    for dimension, score in scores.items():
        weight = getattr(challenge, f"{dimension}_weight", 25)
        weighted = score * weight / 100
        report.append(f"{dimension.title()}: {score:.1f}/100 (weight: {weight}%, contribution: {weighted:.1f})")

    overall = calculate_weighted_score(
        scores.get("correctness", 0),
        scores.get("style", 0),
        scores.get("security", 0),
        scores.get("efficiency", 0),
        challenge
    )

    report.append("-" * 50)
    report.append(f"OVERALL: {overall:.1f}/100")

    return "\n".join(report)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("ARIA Code Quality Challenges")
    print("=" * 50)
    print(f"Total challenges: {len(ALL_DETAILED_CHALLENGES)}")
    print()

    for category in ["data_structures", "algorithms", "security", "bug_fix", "refactoring", "real_world"]:
        challenges = get_challenges_by_category(category)
        if challenges:
            print(f"{category}: {len(challenges)} challenges")
            for c in challenges:
                print(f"  - {c.id}: {c.name} ({c.difficulty})")
    print()

    # Example: Generate prompt for first challenge
    challenge = ALL_DETAILED_CHALLENGES[0]
    print("Example prompt for first challenge:")
    print("-" * 50)
    print(challenge.get_prompt())
