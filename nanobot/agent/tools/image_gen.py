"""Image generation tool using ikun API (Gemini 3 Pro Image Preview)."""

import base64
import time
import uuid
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.config.paths import get_media_dir

# ikun API endpoint
_BASE_URL = "https://api.ikuncode.cc"
_MODEL_PATH = "/v1beta/models/gemini-3-pro-image-preview:generateContent"

_VALID_RATIOS = [
    "1:1", "16:9", "9:16", "4:3", "3:4",
    "3:2", "2:3", "21:9", "5:4", "4:5",
]
_VALID_SIZES = ["1K", "2K", "4K"]
_TIMEOUT = {"1K": 360, "2K": 600, "4K": 1200}
_RETRYABLE = {429, 500, 502, 503, 504}


class ImageGenTool(Tool):
    """Generate images via ikun API (Gemini image model)."""

    def __init__(
        self,
        api_key: str = "",
        proxy: str | None = None,
    ):
        self._api_key = api_key
        self.proxy = proxy

    @property
    def name(self) -> str:
        return "image_gen"

    @property
    def description(self) -> str:
        return (
            "Generate an image from a text prompt. "
            "Returns the local file path. Use the message "
            "tool with the media parameter to send it."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Text description of the image to generate",
                },
                "ratio": {
                    "type": "string",
                    "enum": _VALID_RATIOS,
                    "description": "Aspect ratio (default 1:1)",
                },
                "size": {
                    "type": "string",
                    "enum": _VALID_SIZES,
                    "description": "Resolution: 1K, 2K, or 4K (default 1K)",
                },
            },
            "required": ["prompt"],
        }

    async def execute(
        self,
        prompt: str,
        ratio: str = "1:1",
        size: str = "1K",
        **kwargs: Any,
    ) -> str:
        if not self._api_key:
            return (
                "Error: ikun API key not configured. "
                "Set tools.imageGen.apiKey in config."
            )

        url = f"{_BASE_URL}{_MODEL_PATH}"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["image", "text"],
                "imageGenerationConfig": {
                    "aspectRatio": ratio,
                    "outputImageSize": size,
                },
            },
        }

        timeout = _TIMEOUT.get(size, 360)
        logger.info("ImageGen: prompt={!r} ratio={} size={}", prompt[:80], ratio, size)

        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    proxy=self.proxy, timeout=float(timeout)
                ) as client:
                    resp = await client.post(url, json=body, headers=headers)

                if resp.status_code in _RETRYABLE and attempt < max_retries:
                    logger.warning("ImageGen: {} retry {}", resp.status_code, attempt + 1)
                    continue
                resp.raise_for_status()
                return await self._save_image(resp.json())

            except httpx.TimeoutException:
                if attempt < max_retries:
                    logger.warning("ImageGen: timeout, retry {}", attempt + 1)
                    continue
                return f"Error: Request timed out after {timeout}s"
            except httpx.HTTPStatusError as e:
                body_text = e.response.text[:300] if e.response else ""
                return f"Error: API {e.response.status_code} - {body_text}"
            except Exception as e:
                return f"Error generating image: {e}"

        return "Error: Max retries exceeded"

    async def _save_image(self, data: dict) -> str:
        """Extract base64 image from response and save to file."""
        try:
            candidates = data.get("candidates", [])
            for candidate in candidates:
                for part in candidate.get("content", {}).get("parts", []):
                    if "inlineData" in part:
                        b64 = part["inlineData"]["data"]
                        mime = part["inlineData"].get("mimeType", "image/png")
                        ext = "png" if "png" in mime else "jpg"

                        media_dir = get_media_dir("image_gen")
                        fname = f"gen_{int(time.time())}_{uuid.uuid4().hex[:8]}.{ext}"
                        path = media_dir / fname
                        path.write_bytes(base64.b64decode(b64))

                        logger.info("ImageGen: saved {}", path)
                        return f"Image saved to: {path}"

            # No image in response, check for text
            for candidate in candidates:
                for part in candidate.get("content", {}).get("parts", []):
                    if "text" in part:
                        return f"No image generated. Model response: {part['text'][:300]}"

            return "Error: No image data in API response"
        except Exception as e:
            return f"Error saving image: {e}"
