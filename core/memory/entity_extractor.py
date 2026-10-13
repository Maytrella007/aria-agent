"""
Entity Extractor for ARIA Memory System

Extracts named entities (locations, people, organizations, facts) from text
to improve memory recall and searchability.

Phase 3 of Memory Recall Improvement Plan
"""

import re
from typing import Dict, List, Set
from dataclasses import dataclass


@dataclass
class ExtractedEntities:
    """Container for extracted entities"""
    locations: List[str]
    people: List[str]
    organizations: List[str]
    key_facts: List[str]
    tags: List[str]


class EntityExtractor:
    """
    Simple rule-based entity extractor.

    For production, consider using spaCy or a transformer-based NER model.
    This implementation uses regex patterns for common entity types.
    """

    # Common location indicators
    LOCATION_PATTERNS = [
        r'\b(?:in|to|from|at|near)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b',  # "in Tokyo", "to Portland"
        r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:city|town|country|state)\b',  # "New York city"
        r'\b(?:live|living|lives|moved|moving)\s+(?:in|to)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b',
    ]

    # Common people indicators
    PEOPLE_PATTERNS = [
        r'\b(?:my|their|his|her)\s+(mother|father|sister|brother|partner|spouse|wife|husband|friend|boss|colleague|grandmother|grandfather|mom|dad|son|daughter)\b',
        r'\b([A-Z][a-z]+)\s+(?:said|told|asked|mentioned|thinks|believes)\b',  # "Sarah said"
        r'\bnamed?\s+([A-Z][a-z]+)\b',  # "named Alex"
    ]

    # Fact patterns (subject-verb-object structures)
    FACT_PATTERNS = [
        r'\b(?:I|i)\s+(?:got|received|have)\s+(?:a|an)\s+([^.!?]{5,50})\b',  # "I got a job offer"
        r'\b(?:my|their)\s+(\w+)\s+(?:is|are|was|were)\s+([^.!?]{3,30})\b',  # "my dream is..."
        r"(?:don't|doesn't|won't|can't)\s+(?:want|like)\s+(?:to\s+)?([^.!?]{5,40})",  # "doesn't want to leave"
    ]

    # Known location names (expandable)
    KNOWN_LOCATIONS: Set[str] = {
        # US Cities
        'Tokyo', 'Portland', 'New York', 'Los Angeles', 'San Francisco',
        'Chicago', 'Boston', 'Seattle', 'Austin', 'Denver', 'Miami',
        'Monterey', 'Houston', 'Dallas', 'Phoenix', 'Philadelphia',
        'San Diego', 'San Jose', 'Jacksonville', 'Columbus', 'Charlotte',
        'Indianapolis', 'Detroit', 'Memphis', 'Nashville', 'Baltimore',
        'Milwaukee', 'Albuquerque', 'Tucson', 'Fresno', 'Sacramento',
        'Atlanta', 'Minneapolis', 'Cleveland', 'Pittsburgh', 'Orlando',
        # International
        'London', 'Paris', 'Berlin', 'Sydney', 'Toronto', 'Vancouver',
        'Montreal', 'Madrid', 'Barcelona', 'Rome', 'Milan', 'Amsterdam',
        'Brussels', 'Vienna', 'Munich', 'Frankfurt', 'Zurich', 'Geneva',
        'Dublin', 'Edinburgh', 'Manchester', 'Liverpool', 'Birmingham',
        'Melbourne', 'Brisbane', 'Perth', 'Auckland', 'Wellington',
        'Singapore', 'Hong Kong', 'Shanghai', 'Beijing', 'Seoul',
        'Osaka', 'Kyoto', 'Bangkok', 'Mumbai', 'Delhi', 'Bangalore',
        'Dubai', 'Tel Aviv', 'Cairo', 'Johannesburg', 'Cape Town',
        'Mexico City', 'Buenos Aires', 'Sao Paulo', 'Rio de Janeiro',
        'Lima', 'Bogota', 'Santiago', 'Havana',
        # Regions
        'Bay Area', 'Silicon Valley', 'Wall Street', 'Hollywood',
        # Countries (common)
        'Japan', 'USA', 'America', 'Canada', 'Mexico', 'Brazil',
        'UK', 'England', 'France', 'Germany', 'Italy', 'Spain',
        'Australia', 'China', 'India', 'Korea', 'Russia',
    }

    # Common non-location capitalized words to filter out
    FILTER_WORDS: Set[str] = {
        'The', 'And', 'But', 'For', 'This', 'That', 'What', 'When', 'Where',
        'Who', 'Why', 'How', 'Yes', 'No', 'Maybe', 'Just', 'Only', 'Also',
        'Very', 'Really', 'Actually', 'Basically', 'Honestly', 'Seriously',
        'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
        'January', 'February', 'March', 'April', 'May', 'June', 'July',
        'August', 'September', 'October', 'November', 'December',
        'ARIA', 'User', 'Sam', 'Hey', 'Hello', 'Hi', 'Thanks', 'Thank',
    }

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile regex patterns for efficiency"""
        self._location_re = [re.compile(p, re.IGNORECASE) for p in self.LOCATION_PATTERNS]
        self._people_re = [re.compile(p, re.IGNORECASE) for p in self.PEOPLE_PATTERNS]
        self._fact_re = [re.compile(p, re.IGNORECASE) for p in self.FACT_PATTERNS]

    def extract(self, text: str) -> ExtractedEntities:
        """
        Extract all entity types from text.

        Args:
            text: Input text to analyze

        Returns:
            ExtractedEntities with locations, people, organizations, facts, tags
        """
        locations = self._extract_locations(text)
        people = self._extract_people(text)
        facts = self._extract_facts(text)

        # Generate tags from all extracted entities
        tags = self._generate_tags(locations, people, facts)

        organizations = self._extract_organizations(text)

        return ExtractedEntities(
            locations=locations,
            people=people,
            organizations=organizations,
            key_facts=facts,
            tags=tags
        )

    def _extract_locations(self, text: str) -> List[str]:
        """Extract location names from text"""
        locations = set()

        # Check for known locations first (case-insensitive)
        text_lower = text.lower()
        for loc in self.KNOWN_LOCATIONS:
            if loc.lower() in text_lower:
                locations.add(loc)

        # Apply regex patterns
        for pattern in self._location_re:
            matches = pattern.findall(text)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                # Filter out common non-location words
                if match and len(match) > 2 and match not in self.FILTER_WORDS:
                    # Check if it looks like a proper noun (capitalized)
                    if match[0].isupper():
                        locations.add(match)

        return list(locations)

    def _extract_people(self, text: str) -> List[str]:
        """Extract people references from text"""
        people = set()

        for pattern in self._people_re:
            matches = pattern.findall(text)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                if match and match.lower() not in {'i', 'me', 'my', 'you', 'your'}:
                    people.add(match.lower())

        return list(people)

    def _extract_organizations(self, text: str) -> List[str]:
        """Extract organization names from text using suffix patterns"""
        organizations = set()
        # Match words/phrases ending with common corporate suffixes
        org_pattern = re.compile(
            r'\b([A-Z][\w&\'\-]*(?:\s+[A-Z][\w&\'\-]*)*'
            r'\s+(?:Inc\.?|Corp\.?|LLC|Ltd\.?|Company|Co\.?|Group|Foundation|Association|Institute|University))\b'
        )
        for match in org_pattern.findall(text):
            if match and match not in self.FILTER_WORDS:
                organizations.add(match.strip())
        return list(organizations)

    def _extract_facts(self, text: str) -> List[str]:
        """Extract key facts from text"""
        facts = []

        for pattern in self._fact_re:
            matches = pattern.findall(text)
            for match in matches:
                if isinstance(match, tuple):
                    match = ' '.join(m for m in match if m)
                if match and len(match) > 5:
                    # Clean up the fact
                    fact = match.strip()
                    if fact and fact not in facts:
                        facts.append(fact)

        return facts[:5]  # Limit to top 5 facts

    def _generate_tags(
        self,
        locations: List[str],
        people: List[str],
        facts: List[str]
    ) -> List[str]:
        """Generate searchable tags from extracted entities"""
        tags = []

        # Add locations as tags
        tags.extend([f"location:{loc}" for loc in locations])

        # Add people as tags
        tags.extend([f"person:{p}" for p in people])

        # Extract keywords from facts
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                      'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
                      'and', 'or', 'but', 'not', 'no', 'yes', 'my', 'their', 'our'}

        for fact in facts:
            words = fact.split()
            for word in words:
                word_clean = word.lower().strip('.,!?;:')
                if len(word_clean) > 4 and word_clean.isalpha() and word_clean not in stop_words:
                    tags.append(word_clean)

        return list(set(tags))[:15]  # Limit to 15 unique tags


# Singleton instance
entity_extractor = EntityExtractor()


def extract_entities(text: str) -> ExtractedEntities:
    """Convenience function for entity extraction"""
    return entity_extractor.extract(text)


# Quick test
if __name__ == "__main__":
    test_text = """I got a job offer in Tokyo - my dream city.
    But my partner doesn't want to leave their family here in Portland.
    We're trying to figure out what to do."""

    entities = extract_entities(test_text)
    print("Locations:", entities.locations)
    print("People:", entities.people)
    print("Facts:", entities.key_facts)
    print("Tags:", entities.tags)
