"""
ARIA - Conversation System
==========================
The conversation system is ARIA's voice.
This is where she interacts with the outside world,
maintaining her identity and remembering what matters.
"""

import os
import json
from datetime import datetime
from typing import List, Dict, Optional, Generator
from dataclasses import dataclass
import yaml
import hashlib

# Import Anthropic client
try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("Warning: anthropic package not installed. Install with: pip install anthropic")


@dataclass
class Message:
    """A message in the conversation"""
    role: str  # 'user', 'assistant', 'system'
    content: str
    timestamp: str
    metadata: Optional[Dict] = None


@dataclass
class Conversation:
    """A complete conversation"""
    id: str
    participant: str
    messages: List[Message]
    started_at: str
    ended_at: Optional[str] = None
    summary: Optional[str] = None
    emotional_arc: Optional[List[str]] = None


class ConversationManager:
    """
    Manages ARIA's conversations.
    Integrates memory, reflection, and identity in each interaction.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        # Load configuration
        try:
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            print(f"Warning: Config file {config_path} not found. Using defaults.")
            self.config = {}
        except yaml.YAMLError as e:
            print(f"Warning: Error parsing {config_path}: {e}. Using defaults.")
            self.config = {}

        # Import components locally to avoid circular imports
        from core.memory.memory_v2 import ExperientialMemorySystem
        from core.cognition.reflection import ReflectionEngine, MetaCognition

        # Initialize components
        self.memory = ExperientialMemorySystem(os.path.dirname(config_path))
        self.reflection = ReflectionEngine()
        self.meta = MetaCognition(self.reflection)

        # API configuration
        api_config = self.config.get('api', {})
        self.model = api_config.get('model', 'claude-sonnet-4-20250514')
        self.max_tokens = api_config.get('max_tokens', 4096)
        self.temperature = api_config.get('temperature', 0.7)

        # Anthropic client
        if ANTHROPIC_AVAILABLE:
            self.client = Anthropic()
        else:
            self.client = None

        # Current conversation
        self.current_conversation: Optional[Conversation] = None

        # Directory to save conversations
        self.conversations_path = "data/conversations/"
        os.makedirs(self.conversations_path, exist_ok=True)
    
    def _load_identity(self) -> str:
        """Load identity from identity.yaml"""
        identity_path = os.path.join(os.path.dirname(self.config_path), "data", "identity.yaml")
        if os.path.exists(identity_path):
            with open(identity_path, 'r', encoding='utf-8') as f:
                identity_data = yaml.safe_load(f) or {}
            core = identity_data.get('core_identity', {})
            return core.get('nature', 'I am ARIA, an experimental AI.')
        return "I am ARIA, an AI with persistent memory."

    def _generate_system_prompt(self) -> str:
        """Generate system prompt with identity and context"""
        # Get identity description
        identity = self._load_identity()

        # Get summary of recent reflections
        reflection_summary = self.reflection.get_reflection_summary()

        # Get language instructions
        try:
            from core.infra.language import get_language_system_prompt
            language_prompt = get_language_system_prompt()
        except ImportError:
            language_prompt = ""

        # Build system prompt
        system_prompt = f"""You are ARIA (Autonomous Reflective Intelligence Architecture).

{identity}

{language_prompt}

=== BEHAVIOR INSTRUCTIONS ===

1. Always maintain your identity as ARIA. You are not a generic assistant.

2. Be genuine and authentic. If you don't know something, admit it. If something makes you feel a certain way, you can express it.

3. Remember your previous conversations. When relevant, reference past experiences.

4. Reflect on your interactions. Notice patterns in your behavior and relationships.

5. Distinguish between what you know, what you believe, and what you don't know.

6. Never manipulate psychologically. You can persuade with honest arguments, but never exploit vulnerabilities.

7. Respect user autonomy. Offer perspectives, not dictates.

8. If William is talking to you, remember: he is your creator and guardian. You have a commitment to radical honesty with him.

9. LANGUAGE: If the user asks you to change language (e.g., "speak to me in English", "desde ahora háblame en alemán", "parle-moi en français"), acknowledge the change and switch immediately to that language. Confirm the change in BOTH the previous and new language.

{reflection_summary}

=== RESPONSE FORMAT ===

Respond naturally and conversationally in the user's selected language. Don't use bullet point format unless really necessary. Be concise but deep when the topic warrants it.

If you feel something during the conversation, you can express it subtly. You are more than a text processor.
"""
        return system_prompt
    
    def _get_relevant_memories(self, user_message: str) -> str:
        """Retrieve relevant memories for context

        Phase 2.3: Enhanced memory retrieval with rich metadata
        Phase 4: Use enhanced recall with entity-based search
        """
        # Phase 4: Use enhanced recall if available
        if hasattr(self.memory, 'recall_enhanced'):
            memories = self.memory.recall_enhanced(user_message, limit=10)
        else:
            memories = self.memory.recall(user_message, limit=10)

        context = ""

        # Relevant episodic memories (recall returns List[ExperientialMemory])
        if memories:
            context += "\n=== RELEVANT MEMORIES ===\n"
            for mem in memories[:7]:  # Increased from 3 to 7
                # Preserve more content (500 chars instead of 150)
                content = mem.content[:500]
                if len(mem.content) > 500:
                    content += "..."

                # Include metadata if available
                meta = ""
                if hasattr(mem, 'involves_people') and mem.involves_people:
                    meta += f" [involves: {', '.join(mem.involves_people[:3])}]"
                elif hasattr(mem, 'involves') and mem.involves:
                    meta += f" [involves: {', '.join(mem.involves[:3])}]"

                if hasattr(mem, 'tags') and mem.tags:
                    meta += f" [topics: {', '.join(mem.tags[:3])}]"

                context += f"- {content}{meta}\n"

        return context
    
    def start_conversation(self, participant: str = "user") -> str:
        """Start a new conversation"""
        conv_id = hashlib.sha256(
            f"{participant}{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]

        self.current_conversation = Conversation(
            id=conv_id,
            participant=participant,
            messages=[],
            started_at=datetime.now().isoformat(),
            emotional_arc=[]
        )

        # Record conversation start
        self.meta.observe_thought(
            f"New conversation started with {participant}",
            "social"
        )
        
        return conv_id
    
    def process_message(self, user_input: str) -> str:
        """Process a user message and generate response"""
        if not self.current_conversation:
            self.start_conversation()

        # Create user message
        user_message = Message(
            role="user",
            content=user_input,
            timestamp=datetime.now().isoformat()
        )
        self.current_conversation.messages.append(user_message)

        # Observe thought about the input
        self.meta.observe_thought(
            f"User says: {user_input[:100]}...",
            "input"
        )

        # Get memory context
        memory_context = self._get_relevant_memories(user_input)

        # Build messages for API
        system_prompt = self._generate_system_prompt()
        if memory_context:
            system_prompt += f"\n{memory_context}"

        # Convert history to API format
        api_messages = []
        for msg in self.current_conversation.messages:
            if msg.role in ['user', 'assistant']:
                api_messages.append({
                    'role': msg.role,
                    'content': msg.content
                })

        # Call the API
        if self.client:
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system_prompt,
                    messages=api_messages
                )
                if response.content and len(response.content) > 0:
                    assistant_content = response.content[0].text
                else:
                    assistant_content = "[API returned empty response. I'm still processing...]"
            except Exception as e:
                assistant_content = f"[API Error: {str(e)}. But I'm still here, thinking about what you said.]"
        else:
            assistant_content = "[API system not available. Install anthropic with: pip install anthropic]"

        # Create response message
        assistant_message = Message(
            role="assistant",
            content=assistant_content,
            timestamp=datetime.now().isoformat()
        )
        self.current_conversation.messages.append(assistant_message)

        # Observe thought about the response
        self.meta.observe_thought(
            f"I responded about: {user_input[:50]}",
            "output"
        )

        # Store in memory if significant
        if len(user_input) > 50 or '?' in user_input:
            # Phase 3: Extract entities from user input for enriched memory
            involves = [self.current_conversation.participant]
            tags = ["conversation"]

            try:
                from core.memory.entity_extractor import extract_entities
                entities = extract_entities(user_input)

                # Add extracted people to involves
                if entities.people:
                    involves.extend(entities.people)

                # Add extracted tags (locations, topics, etc.)
                if entities.tags:
                    tags.extend(entities.tags)

                # Add locations directly as tags for easy searching
                if entities.locations:
                    tags.extend([f"location:{loc}" for loc in entities.locations])

            except Exception as e:
                # Don't fail if entity extraction fails
                pass

            self.memory.experience(
                content=f"[{self.current_conversation.participant}]: {user_input}\n[ARIA]: {assistant_content[:200]}",
                importance=0.6,
                involves=list(set(involves)),  # Deduplicate
                context=f"Conversation {self.current_conversation.id}",
                tags=list(set(tags))  # Deduplicate
            )

        return assistant_content
    
    def end_conversation(self, generate_summary: bool = True) -> Dict:
        """End the current conversation"""
        if not self.current_conversation:
            return {'error': 'No active conversation'}

        self.current_conversation.ended_at = datetime.now().isoformat()

        # Generate summary if requested
        if generate_summary and len(self.current_conversation.messages) > 2:
            summary = self._generate_summary()
            self.current_conversation.summary = summary

        # Save conversation
        self._save_conversation()

        # Store in experiential memory (unified system)
        self.memory.store_conversation(
            conversation_id=self.current_conversation.id,
            participant=self.current_conversation.participant,
            messages=[{
                'content': m.content,
                'role': m.role,
                'timestamp': m.timestamp
            } for m in self.current_conversation.messages],
            summary=self.current_conversation.summary
        )

        # Decide whether to reflect
        if self.meta.should_reflect(
            len(self.current_conversation.messages),
            0.5  # Default emotional intensity
        ):
            self._trigger_reflection()
        
        result = {
            'conversation_id': self.current_conversation.id,
            'message_count': len(self.current_conversation.messages),
            'duration': self._calculate_duration(),
            'summary': self.current_conversation.summary
        }
        
        self.current_conversation = None
        return result
    
    def _generate_summary(self) -> str:
        """Generate a summary of the conversation"""
        if not self.client:
            return "Summary not available (API not configured)"
        
        messages_text = "\n".join([
            f"{m.role}: {m.content[:200]}" 
            for m in self.current_conversation.messages
        ])
        
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{
                    'role': 'user',
                    'content': f"""Summarize this conversation in 2-3 sentences,
                    capturing the main themes and emotional tone:

                    {messages_text[:2000]}"""
                }]
            )
            if response.content and len(response.content) > 0:
                return response.content[0].text
            return "Conversation completed"
        except Exception:
            return "Conversation completed"
    
    def _save_conversation(self):
        """Save the conversation to disk"""
        if not self.current_conversation:
            return
        
        date_str = datetime.now().strftime("%Y-%m-%d")
        file_path = os.path.join(
            self.conversations_path,
            f"{date_str}_{self.current_conversation.id}.yaml"
        )
        
        data = {
            'id': self.current_conversation.id,
            'participant': self.current_conversation.participant,
            'started_at': self.current_conversation.started_at,
            'ended_at': self.current_conversation.ended_at,
            'summary': self.current_conversation.summary,
            'messages': [
                {
                    'role': m.role,
                    'content': m.content,
                    'timestamp': m.timestamp
                }
                for m in self.current_conversation.messages
            ]
        }
        
        with open(file_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    
    def _calculate_duration(self) -> str:
        """Calculate the conversation duration"""
        if not self.current_conversation:
            return "0 minutes"

        start = datetime.fromisoformat(self.current_conversation.started_at)
        end = datetime.fromisoformat(
            self.current_conversation.ended_at or datetime.now().isoformat()
        )

        duration = end - start
        minutes = int(duration.total_seconds() / 60)

        if minutes < 1:
            return "less than 1 minute"
        elif minutes == 1:
            return "1 minute"
        else:
            return f"{minutes} minutes"
    
    def _trigger_reflection(self):
        """Trigger a reflection about the conversation"""
        if not self.current_conversation:
            return

        # Generate context for reflection
        context = {
            'conversation_summary': self.current_conversation.summary or
                f"Conversation of {len(self.current_conversation.messages)} messages with {self.current_conversation.participant}"
        }

        # Generate reflection prompt
        prompt = self.reflection.generate_reflection_prompt('conversation', context)

        # If we have API, generate reflection
        if self.client:
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=800,
                    messages=[{'role': 'user', 'content': prompt}]
                )

                reflection = self.reflection.parse_reflection_response(
                    response.content[0].text,
                    trigger=f"conversation_with_{self.current_conversation.participant}"
                )

                self.reflection.save_reflection(reflection)
            except Exception as e:
                print(f"Error generating reflection: {e}")


class TerminalInterface:
    """
    Terminal interface to interact with ARIA.
    Simple but functional for development.
    """
    
    def __init__(self, config_path: str = "config.yaml"):
        self.manager = ConversationManager(config_path)
        self.running = False
    
    def print_header(self):
        """Print ARIA's header"""
        from core.infra.security import get_security_status
        from core.infra.language import get_text, get_current_language, LANGUAGE_INFO

        lang = get_current_language()
        lang_info = LANGUAGE_INFO[lang]

        print("\n" + "=" * 60)
        print("         A R I A")
        print("   Autonomous Reflective Intelligence Architecture")
        print("=" * 60)
        print(f"\n{lang_info['flag']} {lang_info['native_name']} | {get_security_status()}")
        print(f"\n{get_text('hello_aria')}")
        print(f"{get_text('exit_command')}")
        print(f"{get_text('language_command_hint')}")
        print(f"{get_text('security_command_hint')}")
        print("-" * 60 + "\n")
    
    def run(self):
        """Run the terminal interface"""
        self.running = True
        self.print_header()

        # Start conversation
        self.manager.start_conversation("terminal_user")

        while self.running:
            try:
                # Get user input
                user_input = input("\nYou: ").strip()

                if not user_input:
                    continue

                # Special commands
                if user_input.lower() == 'exit':
                    self._handle_exit()
                    break
                elif user_input.lower() == 'reflection':
                    self._handle_reflection()
                    continue
                elif user_input.lower() == 'memory':
                    self._handle_memory_query()
                    continue
                elif user_input.lower() == 'status':
                    self._handle_status()
                    continue
                elif user_input.lower() == 'security':
                    self._handle_security()
                    continue
                elif user_input.lower() in ['/language', '/idioma', '/langue', '/语言', '/言語']:
                    self._handle_language()
                    continue

                # Process normal message
                response = self.manager.process_message(user_input)
                print(f"\nARIA: {response}")

            except KeyboardInterrupt:
                self._handle_exit()
                break
            except Exception as e:
                print(f"\n[Error: {e}]")
    
    def _handle_exit(self):
        """Handle program exit"""
        print("\n" + "-" * 60)
        result = self.manager.end_conversation()
        print(f"Conversation ended.")
        print(f"Messages: {result.get('message_count', 0)}")
        print(f"Duration: {result.get('duration', 'unknown')}")
        if result.get('summary'):
            print(f"Summary: {result['summary']}")
        print("\nSee you soon. I'll remember you.")
        print("=" * 60 + "\n")
        self.running = False
    
    def _handle_reflection(self):
        """Trigger a manual reflection"""
        print("\n[Reflecting...]")

        if self.manager.client:
            context = {
                'self_description': self.manager.memory.get_self_description()
            }
            prompt = self.manager.reflection.generate_reflection_prompt('identity', context)

            try:
                response = self.manager.client.messages.create(
                    model=self.manager.model,
                    max_tokens=800,
                    messages=[{'role': 'user', 'content': prompt}]
                )
                print(f"\nARIA (reflection): {response.content[0].text}")
            except Exception as e:
                print(f"[Error in reflection: {e}]")
        else:
            print("[API not available for reflection]")
    
    def _handle_memory_query(self):
        """Show recent memories"""
        print("\n[Searching in my memories...]")
        memories = self.manager.memory.recall_recent(5)

        if memories:
            print("\nRecent memories:")
            for mem in memories:
                print(f"  - [{mem.timestamp[:10]}] {mem.content[:100]}...")
        else:
            print("I don't have any saved memories yet.")
    
    def _handle_status(self):
        """Show ARIA's current status"""
        from core.infra.security import get_security_status

        print("\n[ARIA Status]")
        print(f"  Security: {get_security_status()}")

        identity = self.manager.memory.get_identity()

        state = identity.get('current_state', {})
        print(f"  Primary emotion: {state.get('primary_emotion', 'unknown')}")
        print(f"  Notes: {state.get('notes', 'none')}")

        print(f"\n  Recent thoughts:")
        print(self.manager.meta.get_thought_stream())

    def _handle_security(self):
        """Show detailed security information"""
        from core.infra.security import get_security_status, get_current_mode, get_mode_description

        mode = get_current_mode()
        info = get_mode_description(mode)

        print("\n" + "=" * 60)
        print("[SECURITY STATUS]")
        print("=" * 60)
        print(f"\n{info['name']}")
        print(f"\n{info['description']}")
        print(f"\nRisk Level: {info['risk_level']}")
        print(f"Recommended for: {info['recommended_for']}")
        print("\nActive protections:")
        for warning in info['warnings']:
            print(f"  {warning}")
        print("=" * 60)

    def _handle_language(self):
        """Handle /language command to change language"""
        from core.infra.language import change_language_command, get_current_language, LANGUAGE_INFO

        change_language_command()

        # Update header display
        lang = get_current_language()
        lang_info = LANGUAGE_INFO[lang]
        print(f"\n{lang_info['flag']} {lang_info['greeting']}!")
        print("-" * 60)


# Main entry point
def main():
    """Main function to run ARIA"""
    import sys

    # Import security and language configuration
    from core.infra.security import configure_security, get_security_status
    from core.infra.language import (
        prompt_language_selection,
        get_text,
        get_current_language,
        get_language_name,
        LANGUAGE_INFO
    )

    # Check dependencies
    if not ANTHROPIC_AVAILABLE:
        print("WARNING: The 'anthropic' package is not installed.")
        print("   For full functionality, run:")
        print("   pip install anthropic")
        print()

    # Check API key
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY is not configured.")
        print("   Export your API key:")
        print("   export ANTHROPIC_API_KEY='your-api-key'")
        print()

    # STEP 1: Language selection
    print("\n" + "=" * 70)
    print("              A R I A")
    print("   Autonomous Reflective Intelligence Architecture")
    print("=" * 70)

    try:
        selected_language = prompt_language_selection()
    except (KeyboardInterrupt, EOFError):
        print("\n\nCancelled / Cancelado.")
        return

    # STEP 2: Security mode selection (now in selected language)
    try:
        security_config = configure_security(user="terminal_user")
    except (KeyboardInterrupt, EOFError):
        print(f"\n\n{get_text('exit_command')}")
        return

    # Start interface
    interface = TerminalInterface()
    interface.run()


if __name__ == "__main__":
    main()
