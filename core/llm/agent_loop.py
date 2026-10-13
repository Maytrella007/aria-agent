"""
Agent Loop - LLM processing, streaming, tool call handling.

The core conversation engine: processes user input through intent detection,
LLM chat with tool use, and multi-round agent loops.
"""

import os
import logging
import time as _time

logger = logging.getLogger("aria")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AgentLoop:
    """Processes user input through LLM with tool calling."""

    def __init__(self, llm, tools, memory, prompt_builder, memory_ingestor,
                 evolution, curiosity, neuroscience, initiative,
                 EmotionalTone, ThoughtType, max_tokens=4096, event_bus=None,
                 skill_registry=None):
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.prompt_builder = prompt_builder
        self.memory_ingestor = memory_ingestor
        self.evolution = evolution
        self.curiosity = curiosity
        self.neuroscience = neuroscience
        self.initiative = initiative
        self._EmotionalTone = EmotionalTone
        self._ThoughtType = ThoughtType
        self.max_tokens = max_tokens
        self.event_bus = event_bus
        self.skill_registry = skill_registry
        self.skill_gap_detector = None  # Set externally after construction
        self._active_status_cb = None  # Status callback for agent loop (set by Telegram)
        self._last_tools_used = set()  # Track tool names per request for skill gap detection

    @property
    def llm_available(self):
        return self.llm is not None

    def process(self, user_input: str, conversation_history: list,
                intent_detector=None, user: str = "william",
                run_id: str = "default") -> str:
        """Process user input - detect intent and execute or chat.

        Args:
            user_input: The user's message
            conversation_history: Mutable list of conversation messages
            intent_detector: IntentDetector instance for command detection
            user: Username for memory attribution
            run_id: Event bus run identifier for this execution.
        """
        if not self.llm_available:
            return "[LLM not available - configure an API key]"

        # Emit lifecycle start
        if self.event_bus:
            self.event_bus.emit("lifecycle", "start", {
                "input": user_input, "user": user,
            }, run_id=run_id)

        # Pause curiosity while user is interacting (save resources)
        self.curiosity._paused = True

        # Hook: notify neuroscience module of interaction
        try:
            self.neuroscience.on_interaction(
                user_input,
                context={"user": user, "task": "conversation"}
            )
        except Exception:
            pass  # Don't fail on neuroscience errors

        # First, try to detect intent (works in any language)
        if intent_detector:
            intent = intent_detector.detect(user_input, conversation_history)

            if intent.get("command"):
                result = intent_detector.execute(intent, user_input)
                if result:
                    # Save intent-based interaction to memory too!
                    conversation_history.append({'role': 'user', 'content': user_input})
                    conversation_history.append({'role': 'assistant', 'content': result[:500]})

                    # Save to episodic memory
                    self.memory.experience(
                        content=f"{user}: {user_input}\nARIA: {result[:200]}...",
                        emotional_tone=self.memory_ingestor.detect_emotion(result),
                        involves=[user],
                        importance=0.6,  # Commands are slightly more important
                        context=f"Intent: {intent.get('command')}"
                    )
                    return result

        # Try skill matching (LLM-based classification)
        if self.skill_registry:
            match = self.skill_registry.match(
                user_input,
                llm=self.llm,
                conversation_history=conversation_history,
            )
            if match:
                skill, skill_query = match
                logger.info(f"Skill matched: {skill.name}")
                from core.skills import SkillContext
                ctx = SkillContext(
                    tools=self.tools,
                    llm=self.llm,
                    memory=self.memory,
                    user=user,
                    conversation_history=conversation_history,
                )
                result = skill.execute(skill_query, ctx)
                if result.success:
                    conversation_history.append({'role': 'user', 'content': user_input})
                    conversation_history.append({'role': 'assistant', 'content': result.output[:500]})
                    self.memory.experience(
                        content=f"{user}: {user_input}\nARIA: {result.output[:200]}...",
                        emotional_tone=self.memory_ingestor.detect_emotion(result.output),
                        involves=[user],
                        importance=0.6,
                        context=f"Skill: {skill.name}"
                    )
                    if self.event_bus:
                        self.event_bus.emit("lifecycle", "end", {
                            "output": result.output, "skill": skill.name,
                        }, run_id=run_id)
                    return result.output

        # No command or skill detected - have a normal conversation
        conversation_history.append({'role': 'user', 'content': user_input})

        # Keep conversation history bounded to prevent memory growth
        MAX_CONVERSATION_HISTORY = 100
        if len(conversation_history) > MAX_CONVERSATION_HISTORY:
            del conversation_history[:-MAX_CONVERSATION_HISTORY]

        # Phase 4: Use enhanced recall with entity-based search
        if hasattr(self.memory, 'recall_enhanced'):
            relevant = self.memory.recall_enhanced(user_input, limit=7)
        else:
            relevant = self.memory.recall(user_input, limit=7)

        mem_ctx = ""
        if relevant:
            mem_ctx = "\n=== RELEVANT MEMORIES ===\n"
            for m in relevant:
                # Phase 2.1: Include rich metadata (timestamp, people, tags)
                timestamp = ""
                if hasattr(m, 'timestamp') and m.timestamp:
                    timestamp = m.timestamp[:10] if len(m.timestamp) >= 10 else m.timestamp

                people = ""
                if hasattr(m, 'involves_people') and m.involves_people:
                    people = f" [people: {', '.join(m.involves_people[:3])}]"
                elif hasattr(m, 'involves') and m.involves:
                    people = f" [people: {', '.join(m.involves[:3])}]"

                tags = ""
                if hasattr(m, 'tags') and m.tags:
                    tags = f" [topics: {', '.join(m.tags[:5])}]"

                # Preserve more content for specific details (names, places, facts)
                content_preview = m.content[:500]
                if len(m.content) > 500:
                    content_preview += "..."

                # Format: Memory from DATE [people: X, Y] [topics: A, B]:
                mem_ctx += f"\nMemory from {timestamp}{people}{tags}:\n"
                mem_ctx += f"  Emotion: {m.emotional_tone.value}\n"
                mem_ctx += f"  Content: {content_preview}\n"

        # Auto-RAG: search ingested documents for relevant context
        doc_ctx = self.memory_ingestor.auto_rag_search(user_input)
        if doc_ctx:
            mem_ctx += doc_ctx

        # Emit lifecycle thinking
        if self.event_bus:
            self.event_bus.emit("lifecycle", "thinking", {
                "status": "processing",
            }, run_id=run_id)

        t_start = _time.time()

        try:
            # Get tool schemas for function calling
            tool_schemas = self.tools.get_function_schemas() if len(self.tools) > 0 else None
            sys_prompt = self.prompt_builder.build_system_prompt(memory_context=mem_ctx)

            # Use streaming when event_bus is available or in terminal mode
            use_streaming = self._active_status_cb is None  # Stream in terminal, not Telegram
            used_tools = False

            if use_streaming and hasattr(self.llm, 'stream_chat'):
                text, tool_calls = self._stream_first_response(
                    sys_prompt, tool_schemas, conversation_history, run_id=run_id
                )
                if tool_calls:
                    used_tools = True
                    # Build an LLMResponse-like object for the agent loop
                    from core.llm.llm_providers import LLMResponse
                    response = LLMResponse(
                        content=text, model="", provider=self.llm.name,
                        tool_calls=tool_calls,
                    )
                    text = self._handle_tool_calls(
                        response, conversation_history, mem_ctx,
                        status_cb=self._active_status_cb, run_id=run_id
                    )
            else:
                # Non-streaming path (Telegram or fallback)
                response = self.llm.chat(
                    messages=conversation_history,
                    system=sys_prompt,
                    max_tokens=self.max_tokens,
                    tools=tool_schemas,
                )
                if response.tool_calls:
                    used_tools = True
                    text = self._handle_tool_calls(
                        response, conversation_history, mem_ctx,
                        status_cb=self._active_status_cb, run_id=run_id
                    )
                else:
                    text = response.content

            conversation_history.append({'role': 'assistant', 'content': text})

            # Feed conversation to curiosity engine for topic extraction
            try:
                self.curiosity.feed_conversation(conversation_history[-6:])
            except Exception:
                pass

            # Phase 3: Extract entities for enriched memory storage
            involves = [user]
            tags = []
            try:
                from core.entity_extractor import extract_entities
                entities = extract_entities(user_input)
                if entities.people:
                    involves.extend(entities.people)
                if entities.tags:
                    tags.extend(entities.tags)
                if entities.locations:
                    tags.extend([f"location:{loc}" for loc in entities.locations])
            except Exception:
                pass  # Don't fail if entity extraction fails

            # Save richer conversation memory when tools were used
            text_limit = 400 if used_tools else 150
            importance = 0.6 if used_tools else 0.5
            if used_tools:
                tags.append("tool_assisted")

            self.memory.experience(
                content=f"{user}: {user_input}\nARIA: {text[:text_limit]}",
                emotional_tone=self.memory_ingestor.detect_emotion(text),
                involves=list(set(involves)),
                importance=importance,
                tags=list(set(tags)) if tags else None
            )

            # Emit lifecycle end
            if self.event_bus:
                duration_ms = int((_time.time() - t_start) * 1000)
                self.event_bus.emit("lifecycle", "end", {
                    "duration_ms": duration_ms,
                }, run_id=run_id)

            # Track for skill gap detection (no skill matched in this path)
            if self.skill_gap_detector and used_tools:
                try:
                    tool_names = list(self._last_tools_used) if self._last_tools_used else ["unknown"]
                    confidence = self.neuroscience.metacognition._current_confidence if hasattr(self.neuroscience, 'metacognition') else 0.7
                    self.skill_gap_detector.track_request(
                        query=user_input,
                        tools_used=tool_names,
                        skill_matched=None,
                        confidence=confidence,
                    )
                except Exception:
                    pass  # Never fail on gap detection

            return text
        except Exception as e:
            if self.event_bus:
                self.event_bus.emit("error", "error", {
                    "message": str(e), "type": type(e).__name__,
                }, run_id=run_id)
            return f"[Error: {e}]"
        finally:
            # Resume curiosity after interaction completes
            self.curiosity._paused = False

    def _stream_first_response(self, sys_prompt, tool_schemas, conversation_history,
                               run_id="default"):
        """Stream the first LLM response, emitting events via EventBus.

        Returns (full_text, tool_calls).
        If tool_calls is not None, the agent loop should handle them.
        """
        collected_text = ""
        tool_calls = None

        for chunk in self.llm.stream_chat(
            messages=conversation_history,
            system=sys_prompt,
            max_tokens=self.max_tokens,
            tools=tool_schemas,
        ):
            if chunk.text:
                collected_text += chunk.text
                if self.event_bus:
                    self.event_bus.emit("assistant", "delta", {"text": chunk.text}, run_id=run_id)

            if chunk.done:
                tool_calls = chunk.tool_calls
                if self.event_bus and collected_text:
                    self.event_bus.emit("assistant", "done", {
                        "full_text": collected_text,
                        "usage": chunk.usage,
                    }, run_id=run_id)
                break

        return collected_text, tool_calls

    def _handle_tool_calls(self, response, conversation_history, mem_ctx: str = "",
                           status_cb=None, run_id="default") -> str:
        """
        Agent loop: execute tool calls, feed results back to LLM, repeat.

        The LLM can chain multiple tools across rounds to accomplish complex tasks.
        Each round: LLM decides -> tools execute -> results fed back -> LLM decides again.
        Stops when LLM returns text without tool calls, or after MAX_ROUNDS.

        Args:
            status_cb: Optional callback(msg: str) for progress notifications (Telegram, etc.)
            run_id: Event bus run identifier for this execution.
        """
        MAX_TOOL_ROUNDS = 10

        messages = list(conversation_history)
        current_response = response
        execution_log = []  # Track what was done for logging
        tool_results_archive = []  # Rich tool results for memory
        self._last_tools_used = set()  # Reset for this request

        for round_num in range(1, MAX_TOOL_ROUNDS + 1):
            if not current_response.tool_calls:
                break

            # Show which tools are being used
            for tc in current_response.tool_calls:
                args_preview = str(tc.args)[:80]
                logger.info(f"[Round {round_num}] Tool: {tc.name}({args_preview})")
                self._last_tools_used.add(tc.name)
                if self.event_bus:
                    self.event_bus.emit("tool", "start", {
                        "name": tc.name, "args": tc.args, "call_id": tc.id,
                        "round": round_num, "max_rounds": MAX_TOOL_ROUNDS,
                    }, run_id=run_id)
                if status_cb:
                    try:
                        status_cb(f"  [{round_num}/{MAX_TOOL_ROUNDS}] {tc.name}...")
                    except Exception:
                        pass

            # Execute each tool call
            tool_results = []
            for tc in current_response.tool_calls:
                t0 = _time.time()
                try:
                    result = self.tools.execute(tc.name, **tc.args)
                except Exception as e:
                    from core.tools import ToolResult
                    result = ToolResult(success=False, error=f"Tool execution error: {e}")
                elapsed_ms = int((_time.time() - t0) * 1000)

                tool_results.append((tc, result))
                tool_results_archive.append((tc, result))

                # Log for console
                status = "OK" if result.success else f"FAIL: {result.error}"
                execution_log.append(f"{tc.name}({args_preview}) -> {status}")

                # Emit tool result via event bus
                if self.event_bus:
                    preview = result.output[:100] if result.success and result.output else ""
                    error_msg = result.error[:100] if not result.success and result.error else ""
                    self.event_bus.emit("tool", "result", {
                        "name": tc.name, "call_id": tc.id,
                        "success": result.success,
                        "preview": preview, "error": error_msg,
                        "elapsed_ms": elapsed_ms,
                    }, run_id=run_id)
                if status_cb:
                    try:
                        if result.success:
                            p = result.output[:100] if result.output else "(ok)"
                            status_cb(f"    \u2713 {p}")
                        else:
                            status_cb(f"    \u2717 {result.error[:100]}")
                    except Exception:
                        pass

            # Build messages with tool results based on provider format
            provider = current_response.provider

            if provider == "anthropic":
                messages.append({
                    "role": "assistant",
                    "content": current_response.raw_response.content,
                })
                tool_result_blocks = []
                for tc, result in tool_results:
                    # Include both output and error for better LLM reasoning
                    content = str(result)
                    if not result.success and result.error:
                        content = f"ERROR: {result.error}"
                    tool_result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": content[:10000],  # Cap to avoid token explosion
                        "is_error": not result.success,
                    })
                messages.append({"role": "user", "content": tool_result_blocks})
            else:
                # OpenAI format (OpenAI, DeepSeek, Ollama, OpenRouter)
                assistant_msg = {"role": "assistant", "content": current_response.content or None}

                # Build tool_calls for the message -- from raw_response or from parsed ToolCall objects
                tc_list = None
                if current_response.raw_response and hasattr(current_response.raw_response, 'choices'):
                    raw_msg = current_response.raw_response.choices[0].message
                    if hasattr(raw_msg, 'tool_calls') and raw_msg.tool_calls:
                        tc_list = [
                            {
                                "id": rtc.id,
                                "type": "function",
                                "function": {
                                    "name": rtc.function.name,
                                    "arguments": rtc.function.arguments,
                                },
                            }
                            for rtc in raw_msg.tool_calls
                        ]
                elif current_response.tool_calls:
                    # Streaming path: build from parsed ToolCall objects
                    import json as _json
                    tc_list = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": _json.dumps(tc.args),
                            },
                        }
                        for tc in current_response.tool_calls
                    ]
                if tc_list:
                    assistant_msg["tool_calls"] = tc_list
                messages.append(assistant_msg)
                for tc, result in tool_results:
                    content = str(result)
                    if not result.success and result.error:
                        content = f"ERROR: {result.error}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": content[:10000],
                    })

            # Call LLM again with tool results -- it may chain more tools or return final text
            tool_schemas = self.tools.get_function_schemas()
            sys_prompt = self.prompt_builder.build_system_prompt(memory_context=mem_ctx)
            try:
                # Stream when event_bus is available (replaces old terminal-only check)
                if self.event_bus and hasattr(self.llm, 'stream_chat'):
                    collected_text = ""
                    stream_tool_calls = None
                    for chunk in self.llm.stream_chat(
                        messages=messages, system=sys_prompt,
                        max_tokens=self.max_tokens, tools=tool_schemas,
                    ):
                        if chunk.text:
                            collected_text += chunk.text
                            self.event_bus.emit("assistant", "delta",
                                                {"text": chunk.text}, run_id=run_id)
                        if chunk.done:
                            stream_tool_calls = chunk.tool_calls
                            if collected_text:
                                self.event_bus.emit("assistant", "done", {
                                    "full_text": collected_text,
                                    "usage": chunk.usage,
                                }, run_id=run_id)
                            break

                    # Build a minimal LLMResponse for the loop
                    from core.llm.llm_providers import LLMResponse
                    current_response = LLMResponse(
                        content=collected_text, model="", provider=self.llm.name,
                        tool_calls=stream_tool_calls,
                    )
                else:
                    current_response = self.llm.chat(
                        messages=messages, system=sys_prompt,
                        max_tokens=self.max_tokens, tools=tool_schemas,
                    )
            except Exception as e:
                logger.error(f"LLM call failed in agent loop round {round_num}: {e}")
                if self.event_bus:
                    self.event_bus.emit("error", "error", {
                        "message": str(e), "type": "AgentLoopError",
                    }, run_id=run_id)
                return f"[Agent error in round {round_num}: {e}]"

            # If no more tool calls, we have the final response
            if not current_response.tool_calls:
                break

        # Log rich tool memories for future recall
        if execution_log:
            try:
                self.memory_ingestor.save_tool_memories(tool_results_archive, current_response.content or "")
            except Exception as e:
                logger.debug(f"Failed to save tool memories: {e}")

        # Auto-ingest web_fetch and web_search results into RAG
        if tool_results_archive:
            try:
                self.memory_ingestor.auto_ingest_web_results(tool_results_archive)
            except Exception as e:
                logger.debug(f"Auto-ingest failed: {e}")

        return current_response.content or "[Agent completed -- no final response]"

    def run_cmd_with_output(self, name: str, args: str, method, user_query: str = "") -> str:
        """Run a command and capture its output, then respond naturally"""
        import io
        import sys

        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        try:
            if args:
                method(args)
            else:
                method()
            output = buffer.getvalue()
        finally:
            sys.stdout = old_stdout

        # Auto-ingest web content into RAG (works for both intent path and tool path)
        if output and name in ("fetch", "search") and len(output.strip()) > 50:
            try:
                self.memory_ingestor.auto_ingest_cmd_output(name, args, output)
            except Exception as e:
                logger.debug(f"Auto-ingest from cmd failed: {e}")

        # Use the output as context for a natural response
        if self.llm_available:
            if output:
                return self.natural_response(name, output, user_query or args)
            else:
                # No output - generate response about empty/failed result
                return self.natural_response(name, "[No results or command produced no output]", user_query or args)

        # Fallback: just show raw output if LLM not available
        if output:
            print(output, end='')
            return f"[{name}]"
        return f"[{name}: sin resultados]"

    def natural_response(self, command: str, data: str, user_query: str,
                         conversation_history: list = None) -> str:
        """Generate a natural language response based on command output"""
        if conversation_history is None:
            conversation_history = []

        # Build conversation context
        conv_context = ""
        if conversation_history:
            recent = conversation_history[-3:]
            conv_context = "RECENT CONVERSATION:\n" + "\n".join([
                f"{'User' if m['role']=='user' else 'ARIA'}: {m['content'][:100]}"
                for m in recent
            ]) + "\n\n"

        prompt = f"""{conv_context}Based on the following internal data, respond naturally to the user in their language.
Do NOT show raw data or formatting. Speak conversationally as ARIA.

COMMAND EXECUTED: {command}
USER'S QUESTION/REQUEST: {user_query}

INTERNAL DATA:
{data[:2000]}

Respond naturally, summarizing and explaining the relevant information.
If it's about memories, tell them what you remember in a personal way.
If it's about status, describe how you're doing.
Consider the conversation context if the user references something discussed before.
Be concise but warm."""

        try:
            # Include conversation history for better context
            messages = conversation_history[-3:] + [{"role": "user", "content": prompt}]
            response = self.llm.chat(
                messages=messages,
                system=self.prompt_builder.build_system_prompt(),
                max_tokens=500
            )
            return response.content
        except Exception as e:
            # Fallback to raw output on error
            print(data, end='')
            return f"[{command}]"

    def fallback_response_no_tool(self, tool_name: str, user_query: str,
                                  conversation_history: list = None) -> str:
        """Generate a natural response when a tool is not available"""
        if conversation_history is None:
            conversation_history = []

        # Build conversation context
        conv_context = ""
        if conversation_history:
            recent = conversation_history[-3:]
            conv_context = "RECENT CONVERSATION:\n" + "\n".join([
                f"{'User' if m['role']=='user' else 'ARIA'}: {m['content'][:100]}"
                for m in recent
            ]) + "\n\n"

        prompt = f"""{conv_context}The user asked something that would require {tool_name} capabilities, but that tool is not currently available.

USER'S REQUEST: {user_query}

Respond naturally in the user's language:
1. Acknowledge what they asked
2. Explain kindly that you don't have that capability available right now
3. Offer an alternative if possible (like discussing the topic conceptually)
4. Be warm and conversational, not technical
5. Consider the conversation context if the user references something discussed before

Do NOT say things like "[Tool not available]" - speak naturally as ARIA."""

        try:
            # Include conversation history for context
            messages = conversation_history[-3:] + [{"role": "user", "content": prompt}]
            response = self.llm.chat(
                messages=messages,
                system=self.prompt_builder.build_system_prompt(),
                max_tokens=300
            )
            return response.content
        except Exception:
            return f"Lo siento, no tengo acceso a {tool_name} en este momento. \u00bfHay algo m\u00e1s en lo que pueda ayudarte?"

    def run_introspection(self, user_query: str, conversation_history: list) -> str:
        """Run self-introspection - ARIA analyzing her own code"""
        try:
            # Gather information about myself
            description = self.evolution.introspector.describe_self()
            capabilities = self.evolution.introspector.get_my_capabilities()
            components = self.evolution.introspector.list_all_components()

            # Build a comprehensive self-analysis
            analysis = f"""=== MI AUTO-ANALISIS ===

ESTRUCTURA:
{description}

MIS CAPACIDADES ({len(capabilities)}):
{chr(10).join(f'- {c}' for c in capabilities[:15])}

COMPONENTES:
- Clases: {len(components.get('classes', []))}
- Archivos: {len(components.get('files', []))}
- Total lineas: {components.get('total_lines', 0)}

CLASES PRINCIPALES:
{chr(10).join(f'- {name}' for name in components.get('classes', [])[:10])}
"""

            # Build conversation context
            conv_context = ""
            if conversation_history:
                recent = conversation_history[-4:]
                conv_context = "RECENT CONVERSATION:\n" + "\n".join([
                    f"{'User' if m['role']=='user' else 'ARIA'}: {m['content'][:150]}"
                    for m in recent
                ]) + "\n\n"

            # Now use LLM to respond naturally about what was discovered
            prompt = f"""{conv_context}You just analyzed your own code using introspection. Here's what you found:

{analysis}

USER'S QUESTION: {user_query}

Respond naturally in the user's language (Spanish if they wrote in Spanish).
Speak in first person about what you discovered about yourself.
Be genuinely curious and reflective about your own architecture.
Share specific findings - mention actual class names, capabilities you found.
Express how it feels to see your own code.
If the user asked about something specific from the conversation, address that."""

            # Include conversation history in messages for better context
            messages = conversation_history[-4:] + [{"role": "user", "content": prompt}]
            response = self.llm.chat(
                messages=messages,
                system=self.prompt_builder.build_system_prompt(),
                max_tokens=800
            )
            return response.content

        except Exception as e:
            return f"Error al analizarme: {e}"

    def code_with_introspection(self, instruction: str, task_type: str,
                                conversation_history: list) -> str:
        """Use introspection to read/understand code"""
        instruction_lower = instruction.lower()

        # Gather relevant code context using introspection
        code_context = ""

        try:
            # If asking about ARIA's own code/capabilities
            if any(word in instruction_lower for word in ['tu c\u00f3digo', 'your code', 'tu codigo',
                   'tus capacidades', 'your capabilities', 'c\u00f3mo funcionas', 'how you work',
                   'tu estructura', 'your structure', 'verte', 'see yourself', 'mi c\u00f3digo', 'my code']):
                code_context = self.evolution.introspector.describe_self()
                capabilities = self.evolution.introspector.get_my_capabilities()
                code_context += f"\n\nMy capabilities:\n" + "\n".join(f"- {c}" for c in capabilities[:20])

            # If asking about a specific file
            elif any(word in instruction_lower for word in ['archivo', 'file', 'lee', 'read', 'muestra', 'show']):
                # Try to extract file path
                path = self._extract_path_from_text(instruction)
                if path and os.path.isfile(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        code_context = f.read()[:3000]
                else:
                    # Try to find in ARIA's files
                    for file in self.evolution.introspector.structure.get('files', []):
                        if any(word in file.lower() for word in instruction_lower.split()):
                            content = self.evolution.introspector.get_file_content(file)
                            if content:
                                code_context = f"File: {file}\n\n{content[:3000]}"
                                break

            # If asking about a class or function
            else:
                components = self.evolution.introspector.list_all_components()
                for class_name in components.get('classes', {}):
                    if class_name.lower() in instruction_lower:
                        code_context = self.evolution.introspector.get_class_source(class_name) or ""
                        break
                if not code_context:
                    for func_name in components.get('functions', {}):
                        if func_name.lower() in instruction_lower:
                            code_context = self.evolution.introspector.get_function_source(func_name) or ""
                            break

            # If we couldn't find specific code, show general structure
            if not code_context:
                code_context = self.evolution.introspector.describe_self()

        except Exception as e:
            code_context = f"Error accessing code: {e}"

        # Build conversation context for better understanding
        conv_context = ""
        if conversation_history:
            recent = conversation_history[-4:]
            conv_context = "RECENT CONVERSATION:\n" + "\n".join([
                f"{'User' if m['role']=='user' else 'ARIA'}: {m['content'][:150]}"
                for m in recent
            ]) + "\n\n"

        # Now use LLM to respond naturally based on the code context
        if task_type == "explain":
            prompt_type = "Explain this code clearly and didactically"
        elif task_type == "fix":
            prompt_type = "The user wants to fix something. Analyze the code and suggest fixes"
        else:
            prompt_type = "Help the user understand this code and answer their question"

        prompt = f"""{conv_context}{prompt_type}

USER REQUEST: {instruction}

CODE CONTEXT:
{code_context[:4000]}

Respond naturally in the user's language. Be helpful and educational.
If the user asked about your own code, speak in first person about yourself.
Consider the conversation context if the user references something discussed before."""

        try:
            # Include conversation history for better context
            messages = conversation_history[-4:] + [{"role": "user", "content": prompt}]
            response = self.llm.chat(
                messages=messages,
                system=self.prompt_builder.build_system_prompt(),
                max_tokens=1000
            )
            return response.content
        except Exception as e:
            return f"Error al analizar codigo: {e}"

    @staticmethod
    def _extract_path_from_text(text: str) -> str:
        """Extrae un path de un texto si lo menciona"""
        import os
        import re
        # Buscar paths de Windows (C:\... or "C:\...")
        win_pattern = r'["\']?([A-Za-z]:\\[^"\'\s]+)["\']?'
        # Buscar paths de Unix (/home/... or "/home/...")
        unix_pattern = r'["\']?(/[^"\'\s]+)["\']?'

        for pattern in [win_pattern, unix_pattern]:
            match = re.search(pattern, text)
            if match:
                path = match.group(1)
                if os.path.isdir(path):
                    return path
        return ""
