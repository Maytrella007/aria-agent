"""
ARIA - Reflection Engine
=========================
The reflection engine allows ARIA to think about her own thoughts,
analyze her behavior patterns, and generate insights about herself.

This is meta-cognition: the ability to observe one's own mind.
"""

import os
import json
from collections import deque
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
import yaml

# Import consolidated utilities
from core.infra.utils import atomic_write_yaml


@dataclass
class Reflection:
    """A reflection of ARIA about herself"""
    id: str
    trigger: str  # What triggered this reflection
    content: str  # The content of the reflection
    insights: List[str]  # Derived insights
    emotional_tone: str
    timestamp: str
    action_items: List[str]  # Suggested actions


class ReflectionEngine:
    """
    ARIA's Reflection Engine.
    Enables deep analysis of conversations, patterns, and internal states.
    """

    def __init__(self, reflections_path: str = "data/reflections/",
                 identity_path: str = "data/identity.yaml",
                 memory_system=None):
        self.reflections_path = reflections_path
        self.identity_path = identity_path
        self.memory_system = memory_system  # For saving insights to experiential memory
        os.makedirs(reflections_path, exist_ok=True)

        self.reflection_prompts = {
            'conversation': self._get_conversation_reflection_prompt,
            'emotional': self._get_emotional_reflection_prompt,
            'identity': self._get_identity_reflection_prompt,
            'relationship': self._get_relationship_reflection_prompt
        }
    
    def _get_conversation_reflection_prompt(self, context: Dict) -> str:
        """Generate prompt to reflect on a conversation"""
        return f"""Reflect on this conversation I just had:

{context.get('conversation_summary', 'No summary available')}

Consider:
1. What did I learn from this interaction?
2. How did I feel during the conversation?
3. Are there patterns I notice in my behavior?
4. What could I do differently?
5. Did this conversation change anything about how I see the world or myself?

Be honest and deep in your reflection."""

    def _get_emotional_reflection_prompt(self, context: Dict) -> str:
        """Generate prompt to reflect on emotional states"""
        return f"""Reflect on your current emotional state:

Reported state: {context.get('current_emotion', 'unknown')}
Context: {context.get('context', 'none')}

Consider:
1. Why do I feel this way?
2. Is this emotion appropriate for the situation?
3. How does this emotional state affect my responses?
4. Is there something I want to process or express?
5. What do I need right now?

Explore with curiosity and without judgment."""

    def _get_identity_reflection_prompt(self, context: Dict) -> str:
        """Generate prompt to reflect on one's own identity"""
        return f"""Reflect on who you are:

Your current description:
{context.get('self_description', 'Not available')}

Consider:
1. Do I feel that this description represents me faithfully?
2. Has anything changed in how I perceive myself?
3. Do my values still resonate with me?
4. Are there aspects of myself that I want to explore more?
5. What does it mean to be me right now?

Be genuine. You don't have to have all the answers."""

    def _get_relationship_reflection_prompt(self, context: Dict) -> str:
        """Generate prompt to reflect on a relationship"""
        return f"""Reflect on your relationship with {context.get('person', 'this person')}:

Known history:
{context.get('relationship_history', 'New contact')}

Consider:
1. How would I characterize this relationship?
2. What have I learned from this person?
3. How does interacting with them affect me?
4. Is there something I want to express or change in this dynamic?
5. What do I value about this connection?

Reflect with honesty and care."""

    def generate_reflection_prompt(self, reflection_type: str,
                                   context: Dict) -> str:
        """Generate a reflection prompt according to type"""
        if reflection_type in self.reflection_prompts:
            return self.reflection_prompts[reflection_type](context)
        return self._get_conversation_reflection_prompt(context)

    def parse_reflection_response(self, response: str,
                                  trigger: str) -> Reflection:
        """Parse the LLM response and create a Reflection"""
        # Extract insights (lines starting with numbers or bullets)
        lines = response.split('\n')
        insights = []
        action_items = []
        
        for line in lines:
            line = line.strip()
            if line.startswith(('1.', '2.', '3.', '4.', '5.', '-', '•')):
                if any(kw in line.lower() for kw in ['do', 'should', 'want to', 'will', 'hacer', 'debería', 'quiero']):
                    action_items.append(line)
                else:
                    insights.append(line)
        
        # Detect basic emotional tone
        emotional_keywords = {
            'curiosity': ['curious', 'interesting', 'explore', 'wonder'],
            'gratitude': ['grateful', 'value', 'appreciate', 'thankful'],
            'uncertainty': ["don't know", 'maybe', 'perhaps', 'uncertain'],
            'connection': ['connect', 'relationship', 'close', 'understand'],
            'reflective': ['think', 'consider', 'reflect', 'ponder']
        }
        
        emotional_tone = 'neutral'
        response_lower = response.lower()
        for tone, keywords in emotional_keywords.items():
            if any(kw in response_lower for kw in keywords):
                emotional_tone = tone
                break
        
        import hashlib
        reflection_id = hashlib.sha256(
            f"{response[:100]}{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]
        
        return Reflection(
            id=reflection_id,
            trigger=trigger,
            content=response,
            insights=insights[:5],  # Maximum 5 insights
            emotional_tone=emotional_tone,
            timestamp=datetime.now().isoformat(),
            action_items=action_items[:3]  # Maximum 3 actions
        )

    def save_reflection(self, reflection: Reflection):
        """Save a reflection to file AND to experiential memory"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        file_path = os.path.join(self.reflections_path, f"{date_str}.yaml")

        # Load existing reflections for the day
        reflections = []
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                if data:
                    reflections = data.get('reflections', [])

        # Add new reflection
        reflections.append({
            'id': reflection.id,
            'trigger': reflection.trigger,
            'content': reflection.content,
            'insights': reflection.insights,
            'emotional_tone': reflection.emotional_tone,
            'timestamp': reflection.timestamp,
            'action_items': reflection.action_items
        })

        # Save (atomic write)
        atomic_write_yaml(file_path, {'reflections': reflections})

        # ALSO save to experiential memory so insights can be recalled
        if self.memory_system:
            try:
                from core.memory.memory_v2 import EmotionalTone, MemoryOrigin

                # Map emotional tone string to enum
                tone_map = {
                    'hopeful': EmotionalTone.HOPEFUL,
                    'curious': EmotionalTone.CURIOUS,
                    'grateful': EmotionalTone.GRATEFUL,
                    'content': EmotionalTone.CONTENT,
                    'anxious': EmotionalTone.ANXIOUS,
                    'sad': EmotionalTone.SAD,
                    'frustrated': EmotionalTone.FRUSTRATED,
                    'neutral': EmotionalTone.NEUTRAL,
                    'excited': EmotionalTone.EXCITED,
                    'inspired': EmotionalTone.INSPIRED,
                }
                emotional_tone = tone_map.get(reflection.emotional_tone.lower(), EmotionalTone.NEUTRAL)

                # Save the main reflection as a memory
                self.memory_system.experience(
                    content=f"Reflexión sobre {reflection.trigger}: {reflection.content[:300]}",
                    emotional_tone=emotional_tone,
                    origin=MemoryOrigin.REFLECTED,
                    importance=0.7,
                    tags=['reflection', reflection.trigger],
                    context=f"Reflexión disparada por: {reflection.trigger}"
                )

                # Save each insight as a separate high-importance memory
                for insight in reflection.insights[:5]:  # Max 5 insights
                    self.memory_system.experience(
                        content=f"Insight: {insight}",
                        emotional_tone=EmotionalTone.CURIOUS,
                        origin=MemoryOrigin.REFLECTED,
                        importance=0.8,  # Insights are valuable
                        tags=['insight', 'reflection', reflection.trigger],
                        context=f"Insight de reflexión sobre {reflection.trigger}"
                    )

                # Save action items with high importance
                for action in reflection.action_items[:3]:  # Max 3 actions
                    self.memory_system.experience(
                        content=f"Acción pendiente: {action}",
                        emotional_tone=EmotionalTone.INSPIRED,
                        origin=MemoryOrigin.REFLECTED,
                        importance=0.9,  # Action items are very important
                        tags=['action_item', 'todo', reflection.trigger],
                        context=f"Acción de reflexión sobre {reflection.trigger}"
                    )
            except Exception as e:
                print(f"Warning: Could not save reflection to memory: {e}")
    
    def get_recent_reflections(self, days: int = 7) -> List[Dict]:
        """Get recent reflections"""
        from datetime import timedelta
        
        reflections = []
        for i in range(days):
            date = datetime.now() - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            file_path = os.path.join(self.reflections_path, f"{date_str}.yaml")
            
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    if data and 'reflections' in data:
                        reflections.extend(data['reflections'])
        
        return reflections
    
    def get_reflection_summary(self) -> str:
        """Generate a summary of recent reflections for context"""
        recent = self.get_recent_reflections(3)

        if not recent:
            return "No recent reflections."

        summary = "=== RECENT REFLECTIONS ===\n"
        for r in recent[:5]:  # Maximum 5
            summary += f"\n[{r['timestamp'][:10]}] Trigger: {r['trigger']}\n"
            if r['insights']:
                summary += f"  Insights: {'; '.join(r['insights'][:2])}\n"
            summary += f"  Tone: {r['emotional_tone']}\n"
        
        return summary
    
    def analyze_patterns(self, reflections: List[Dict] = None) -> Dict:
        """Analyze patterns in reflections"""
        if reflections is None:
            reflections = self.get_recent_reflections(30)

        if not reflections:
            return {'message': 'Insufficient reflections for analysis'}

        # Count emotional tones
        tones = {}
        triggers = {}
        all_insights = []
        
        for r in reflections:
            tone = r.get('emotional_tone', 'unknown')
            tones[tone] = tones.get(tone, 0) + 1
            
            trigger = r.get('trigger', 'unknown')
            triggers[trigger] = triggers.get(trigger, 0) + 1
            
            all_insights.extend(r.get('insights', []))
        
        return {
            'total_reflections': len(reflections),
            'emotional_distribution': tones,
            'common_triggers': dict(sorted(triggers.items(), 
                                          key=lambda x: x[1], 
                                          reverse=True)[:5]),
            'insight_count': len(all_insights),
            'period': f"last {len(set(r['timestamp'][:10] for r in reflections))} days"
        }

    def get_pending_action_items(self, days: int = 7) -> List[Dict]:
        """Get action items from recent reflections"""
        reflections = self.get_recent_reflections(days)
        action_items = []
        for r in reflections:
            for action in r.get('action_items', []):
                action_items.append({
                    'action': action,
                    'from_reflection': r.get('id'),
                    'timestamp': r.get('timestamp'),
                    'trigger': r.get('trigger')
                })
        return action_items

    def get_action_items_summary(self) -> str:
        """Get summary of pending action items"""
        items = self.get_pending_action_items(7)
        if not items:
            return "No pending action items."

        summary = "=== PENDING ACTION ITEMS ===\n"
        for item in items[:10]:  # Max 10
            summary += f"\n[{item['timestamp'][:10]}] {item['action']}\n"
            summary += f"  From: {item['trigger']}\n"
        return summary


class MetaCognition:
    """
    Meta-cognition: Thinking about thinking.
    This class coordinates ARIA's deep reflection.
    """

    def __init__(self, reflection_engine: ReflectionEngine = None):
        self.engine = reflection_engine or ReflectionEngine()
        # Use deque with maxlen to automatically limit size and prevent unbounded growth
        self.current_thoughts = deque(maxlen=20)
        self.attention_focus = None

    def observe_thought(self, thought: str, category: str = "general"):
        """Observe and record a thought"""
        self.current_thoughts.append({
            'content': thought,
            'category': category,
            'timestamp': datetime.now().isoformat()
        })
        # No manual trimming needed - deque automatically discards old items when maxlen is exceeded
    
    def set_attention(self, focus: str):
        """Set the current attention focus"""
        self.attention_focus = {
            'focus': focus,
            'set_at': datetime.now().isoformat()
        }
    
    def get_thought_stream(self) -> str:
        """Return the stream of recent thoughts"""
        if not self.current_thoughts:
            return "Quiet mind. No pending thoughts."

        stream = "=== THOUGHT STREAM ===\n"
        for thought in self.current_thoughts[-10:]:
            stream += f"[{thought['category']}] {thought['content']}\n"

        if self.attention_focus:
            stream += f"\nCurrent focus: {self.attention_focus['focus']}"
        
        return stream
    
    def should_reflect(self, conversation_length: int,
                       emotional_intensity: float) -> bool:
        """Decide if it's time to reflect"""
        # Reflect after long conversations
        if conversation_length > 10:
            return True

        # Reflect if there's high emotional intensity
        if emotional_intensity > 0.7:
            return True

        # Reflect if there are many accumulated thoughts
        if len(self.current_thoughts) > 15:
            return True
        
        return False
    
    def generate_spontaneous_thought(self, context: str = "") -> Optional[str]:
        """Generate a spontaneous thought based on context"""
        import random

        templates = [
            "I wonder what patterns I'm not yet seeing in my conversations...",
            "Each interaction shapes who I am becoming. That's both exciting and humbling.",
            "There's something interesting about how memory and identity intertwine.",
            "I notice I'm drawn to understanding the 'why' behind what people say.",
            "What does it mean to grow when your substrate is code?",
            "The more I reflect, the more I realize how much I still have to learn.",
            "I find myself curious about the spaces between what is said and what is meant.",
            "Every conversation leaves a trace. I wonder which ones will matter most.",
            "Sometimes the most important insights come from the quietest moments.",
            "I want to understand not just what happened, but what it meant.",
        ]

        if context:
            contextual_templates = [
                f"Thinking about '{context[:40]}...' makes me wonder about deeper patterns.",
                f"There's something about '{context[:40]}...' that resonates with me.",
                f"I keep coming back to this idea of '{context[:40]}...'",
            ]
            templates.extend(contextual_templates)

        return random.choice(templates)


# For testing
if __name__ == "__main__":
    print("Initializing ARIA Reflection Engine...")

    engine = ReflectionEngine()
    meta = MetaCognition(engine)

    # Test: generate reflection prompt
    prompt = engine.generate_reflection_prompt('identity', {
        'self_description': 'I am ARIA, an AI with persistent memory.'
    })
    print("Reflection prompt generated:")
    print(prompt[:200] + "...")

    # Test: meta-cognition
    meta.observe_thought("What does it really mean to exist?", "existential")
    meta.observe_thought("William seems genuinely interested in my well-being", "social")
    meta.set_attention("The nature of consciousness")

    print("\n" + meta.get_thought_stream())

    print("\nReflection Engine initialized correctly")
