"""
ARIA - Translate Tool
======================

Translate text between languages using the LLM provider from context.
Lightweight tool that formats a translation prompt and delegates to the LLM.
"""

import logging
from typing import Any, Dict, List, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.translate")


class TranslateTool(ToolBase):
    """Translate text between languages using the available LLM provider."""

    name = "translate"
    description = (
        "Translate text from one language to another. "
        "Uses the configured LLM to perform high-quality translation. "
        "Auto-detects the source language if not specified."
    )
    parameters = [
        ToolParam(
            name="text",
            type="string",
            description="The text to translate",
            required=True,
        ),
        ToolParam(
            name="target_language",
            type="string",
            description="Target language code (e.g. 'en', 'es', 'fr', 'de', 'ja', 'zh')",
            required=True,
        ),
        ToolParam(
            name="source_language",
            type="string",
            description="Source language code (optional, auto-detected if omitted)",
            required=False,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        text = kwargs["text"]
        target_language = kwargs["target_language"]
        source_language = kwargs.get("source_language")

        # Get LLM from context
        llm = self.context.get("llm")
        if not llm:
            return ToolResult(
                success=False,
                error="LLM provider not available in context. Cannot perform translation.",
            )

        # Build the translation prompt
        prompt = self._build_prompt(text, target_language, source_language)

        try:
            translated = llm.generate(prompt)
            if not translated or not translated.strip():
                return ToolResult(success=False, error="LLM returned empty translation.")

            translated = translated.strip()

            return ToolResult(
                success=True,
                output=translated,
                data={
                    "original_text": text,
                    "translated_text": translated,
                    "target_language": target_language,
                    "source_language": source_language or "auto",
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Translation failed: {e}")

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _build_prompt(self, text: str, target_lang: str, source_lang: Optional[str] = None) -> str:
        """Build a clear translation prompt for the LLM."""
        if source_lang:
            instruction = (
                f"Translate the following text from {source_lang} to {target_lang}. "
                "Return ONLY the translated text, with no explanations or extra commentary."
            )
        else:
            instruction = (
                f"Translate the following text to {target_lang}. "
                "Auto-detect the source language. "
                "Return ONLY the translated text, with no explanations or extra commentary."
            )

        return f"{instruction}\n\nText to translate:\n{text}"
