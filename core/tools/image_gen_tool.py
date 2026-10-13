"""
ARIA - Image Generation Tool
==============================

Generate images using AI providers (OpenAI DALL-E, Stability AI).
Saves generated images locally and returns the file path.
"""

import base64
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.image_gen")

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

DEFAULT_SIZE = "1024x1024"
DEFAULT_PROVIDER = "openai"
DEFAULT_DIR = "data/generated_images"


class ImageGenTool(ToolBase):
    """Generate images from text prompts using AI image generation APIs."""

    name = "image_generate"
    description = (
        "Generate an image from a text prompt using AI (DALL-E or Stability AI). "
        "Returns the local file path of the saved image and the revised prompt if any."
    )
    parameters = [
        ToolParam(
            name="prompt",
            type="string",
            description="Text description of the image to generate",
            required=True,
        ),
        ToolParam(
            name="size",
            type="string",
            description=f"Image dimensions (default: {DEFAULT_SIZE})",
            required=False,
            default=DEFAULT_SIZE,
            enum=["256x256", "512x512", "1024x1024"],
        ),
        ToolParam(
            name="output_path",
            type="string",
            description="File path to save the image (optional, auto-generated if omitted)",
            required=False,
        ),
        ToolParam(
            name="provider",
            type="string",
            description=f"Image generation provider (default: {DEFAULT_PROVIDER})",
            required=False,
            default=DEFAULT_PROVIDER,
            enum=["openai", "stability"],
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        prompt = kwargs["prompt"]
        size = kwargs.get("size", DEFAULT_SIZE)
        output_path = kwargs.get("output_path")
        provider = kwargs.get("provider", DEFAULT_PROVIDER)

        if provider == "openai":
            return self._generate_openai(prompt, size, output_path)
        elif provider == "stability":
            return ToolResult(
                success=False,
                error="Stability AI provider is not yet implemented.",
            )
        else:
            return ToolResult(success=False, error=f"Unknown provider: {provider}")

    # -------------------------------------------------------------------------
    # OpenAI DALL-E
    # -------------------------------------------------------------------------

    def _generate_openai(self, prompt: str, size: str, output_path: Optional[str]) -> ToolResult:
        if not OPENAI_AVAILABLE:
            return ToolResult(
                success=False,
                error="openai library not installed. Install with: pip install openai",
            )

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return ToolResult(
                success=False,
                error="OPENAI_API_KEY environment variable is not set.",
            )

        # Determine save path
        if not output_path:
            os.makedirs(DEFAULT_DIR, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(DEFAULT_DIR, f"img_{timestamp}.png")
        else:
            parent = os.path.dirname(output_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

        try:
            client = openai.OpenAI(api_key=api_key)
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                n=1,
                response_format="b64_json",
            )

            image_data = base64.b64decode(response.data[0].b64_json)
            revised_prompt = getattr(response.data[0], "revised_prompt", None)

            with open(output_path, "wb") as f:
                f.write(image_data)

            output_msg = f"Image saved to: {output_path}"
            if revised_prompt:
                output_msg += f"\nRevised prompt: {revised_prompt}"

            return ToolResult(
                success=True,
                output=output_msg,
                data={
                    "path": output_path,
                    "size": size,
                    "prompt": prompt,
                    "revised_prompt": revised_prompt,
                    "bytes": len(image_data),
                },
            )

        except openai.AuthenticationError:
            return ToolResult(success=False, error="Invalid OPENAI_API_KEY.")
        except openai.RateLimitError:
            return ToolResult(success=False, error="OpenAI rate limit exceeded. Try again later.")
        except Exception as e:
            return ToolResult(success=False, error=f"Image generation failed: {e}")
