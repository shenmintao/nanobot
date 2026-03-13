"""Image generation tool supporting OpenAI, Gemini, and Grok API formats."""

import base64
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.config.paths import get_media_dir


class ImageGenTool(Tool):
    """Generate or edit images via OpenAI, Gemini, or Grok API (auto-detects format based on model name)."""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        model: str = "dall-e-3",
        proxy: str | None = None,
        reference_image: str = "",
    ):
        self._api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.proxy = proxy
        self._default_reference = reference_image

    def _resolve_default_reference(self) -> str | None:
        """Resolve the default reference image: active character > global config.

        Supports two formats in character card extensions.nanobot:
          - reference_image_base64: base64-encoded image (most portable, stored in JSON)
          - reference_image: file path to an image file
        """
        # 1. Check active SillyTavern character's extensions
        try:
            from nanobot.sillytavern.storage import get_active_character
            char = get_active_character()
            if char and char.data.extensions:
                nanobot_ext = char.data.extensions.get("nanobot", {})
                if isinstance(nanobot_ext, dict):
                    # Prefer base64 (self-contained in the card JSON)
                    b64_data = nanobot_ext.get("reference_image_base64", "")
                    if b64_data:
                        # Save to a temp file so downstream code can read it
                        cache_path = self._cache_base64_reference(char.id, b64_data)
                        if cache_path:
                            logger.debug("Using character '{}' embedded reference image", char.name)
                            return cache_path

                    # Fall back to file path
                    char_ref = nanobot_ext.get("reference_image", "")
                    if char_ref and Path(char_ref).exists():
                        logger.debug("Using character '{}' reference image: {}", char.name, char_ref)
                        return char_ref
        except Exception:
            pass

        # 2. Fall back to global config
        if self._default_reference and Path(self._default_reference).exists():
            return self._default_reference

        return None

    def _cache_base64_reference(self, char_id: str, b64_data: str) -> str | None:
        """Decode base64 reference image and cache to disk. Returns cached file path."""
        try:
            cache_dir = get_media_dir("reference")
            cache_path = cache_dir / f"ref_{char_id}.png"
            # Only write if not already cached (avoid repeated I/O)
            if not cache_path.exists():
                cache_path.write_bytes(base64.b64decode(b64_data))
            return str(cache_path)
        except Exception as e:
            logger.warning("Failed to cache reference image for {}: {}", char_id, e)
            return None

    def _is_gemini_model(self) -> bool:
        """Check if the model uses Gemini API format."""
        return "gemini" in self.model.lower() and "image" in self.model.lower()

    def _is_grok_model(self) -> bool:
        """Check if the model uses Grok/xAI API format."""
        lower = self.model.lower()
        return "grok" in lower or "aurora" in lower

    @property
    def name(self) -> str:
        return "image_gen"

    @property
    def description(self) -> str:
        base = (
            "Generate an image from a text prompt, or edit/transform an existing image. "
            "To edit an existing image, provide the file path in 'reference_image'. "
            "IMPORTANT: After generating, you MUST call the 'message' tool "
            "with the returned file path in the 'media' parameter to send the image to the user. "
            "Do not just reply with text - the user expects to receive the actual image."
        )
        base += (
            " When generating images of yourself or your character, set reference_image to "
            "'__default__' to use the character's avatar as a base for consistent appearance. "
            "This automatically picks up the active character's reference image."
        )
        return base

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Text description of the image to generate, or instructions for editing the reference image",
                },
                "reference_image": {
                    "type": "string",
                    "description": "Optional file path to a source image for image-to-image editing. "
                    "When provided, the model will use this image as a base and apply the prompt as editing instructions.",
                },
                "size": {
                    "type": "string",
                    "description": "Image size (e.g., '1024x1024', '1792x1024', '1024x1792')",
                },
                "quality": {
                    "type": "string",
                    "enum": ["standard", "hd"],
                    "description": "Image quality (for DALL-E 3, default: standard)",
                },
                "style": {
                    "type": "string",
                    "enum": ["vivid", "natural"],
                    "description": "Image style (for DALL-E 3, default: vivid)",
                },
            },
            "required": ["prompt"],
        }

    async def execute(
        self,
        prompt: str,
        reference_image: str | None = None,
        size: str | None = None,
        quality: str = "standard",
        style: str = "vivid",
        **kwargs: Any,
    ) -> str:
        if not self._api_key:
            return "Error: Image generation API key not configured. Set tools.imageGen.apiKey in config."

        # Resolve __default__ to the best available reference image
        if reference_image == "__default__":
            reference_image = self._resolve_default_reference()

        # Validate reference image if provided
        ref_image_data: bytes | None = None
        ref_mime: str = "image/jpeg"
        if reference_image:
            ref_path = Path(reference_image)
            if not ref_path.exists():
                return f"Error: Reference image not found: {reference_image}"
            try:
                ref_image_data = ref_path.read_bytes()
                ext = ref_path.suffix.lower()
                ref_mime = {
                    '.png': 'image/png', '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg', '.webp': 'image/webp',
                    '.gif': 'image/gif',
                }.get(ext, 'image/jpeg')
            except Exception as e:
                return f"Error reading reference image: {e}"

        # Route to appropriate implementation
        if self._is_gemini_model():
            return await self._execute_gemini(prompt, size, ref_image_data, ref_mime)
        elif self._is_grok_model():
            if ref_image_data:
                return await self._execute_grok_edit(prompt, ref_image_data, ref_mime)
            else:
                return await self._execute_openai(prompt, size, quality, style)
        else:
            return await self._execute_openai(prompt, size, quality, style)

    async def _execute_openai(
        self,
        prompt: str,
        size: str | None,
        quality: str,
        style: str,
    ) -> str:
        """Execute image generation using OpenAI format."""
        if not size:
            size = "1024x1024"

        url = f"{self.base_url}/images/generations"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        body: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "size": size,
            "n": 1,
        }

        if quality and quality != "standard":
            body["quality"] = quality
        if style and style != "vivid":
            body["style"] = style

        logger.info(
            "ImageGen (OpenAI): model={} size={} quality={} prompt={!r}",
            self.model, size, quality, prompt[:80],
        )

        try:
            async with httpx.AsyncClient(
                proxy=self.proxy, timeout=120.0, trust_env=True,
            ) as client:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                if "data" in data and len(data["data"]) > 0:
                    image_data = data["data"][0]
                    if "b64_json" in image_data:
                        return await self._save_base64(image_data["b64_json"])
                    elif "url" in image_data:
                        return await self._download_image(image_data["url"])

                return "Error: No image data in API response"

        except httpx.HTTPStatusError as e:
            return self._format_http_error(e)
        except httpx.TimeoutException:
            return "Error: Request timed out (120s). Try again or use a smaller size."
        except Exception as e:
            logger.error("ImageGen error: {}", e)
            return f"Error generating image: {e}"

    async def _execute_gemini(
        self,
        prompt: str,
        size: str | None,
        ref_image_data: bytes | None = None,
        ref_mime: str = "image/jpeg",
    ) -> str:
        """Execute image generation/editing using Gemini format."""
        aspect_ratio = "1:1"
        image_size = "2K"

        if size:
            parts = size.lower().split('x')
            if len(parts) == 2:
                try:
                    w, h = int(parts[0]), int(parts[1])
                    if w == h:
                        aspect_ratio = "1:1"
                    elif w > h:
                        aspect_ratio = "16:9" if w / h >= 1.7 else "4:3"
                    else:
                        aspect_ratio = "9:16" if h / w >= 1.7 else "3:4"

                    max_dim = max(w, h)
                    if max_dim <= 1024:
                        image_size = "1K"
                    elif max_dim <= 2048:
                        image_size = "2K"
                    else:
                        image_size = "4K"
                except ValueError:
                    pass

        url = f"{self.base_url}/v1beta/models/{self.model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        # Build content parts
        content_parts: list[dict[str, Any]] = []

        # Add reference image if provided (img2img)
        if ref_image_data:
            content_parts.append({
                "inlineData": {
                    "mimeType": ref_mime,
                    "data": base64.b64encode(ref_image_data).decode(),
                }
            })

        content_parts.append({"text": prompt})

        body = {
            "contents": [{"parts": content_parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                    "image_size": image_size,
                },
            },
        }

        mode = "img2img" if ref_image_data else "text2img"
        logger.info(
            "ImageGen (Gemini {}): model={} aspectRatio={} size={} prompt={!r}",
            mode, self.model, aspect_ratio, image_size, prompt[:80],
        )

        try:
            async with httpx.AsyncClient(
                proxy=self.proxy, timeout=600.0, trust_env=True,
            ) as client:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                try:
                    parts = data["candidates"][0]["content"]["parts"]
                    image_part = next(p for p in parts if "inlineData" in p)
                    b64_data = image_part["inlineData"]["data"]
                    return await self._save_base64(b64_data)
                except (KeyError, IndexError, StopIteration):
                    snippet = str(data)[:500]
                    return f"Error: No image data in Gemini API response: {snippet}"

        except httpx.HTTPStatusError as e:
            return self._format_http_error(e)
        except httpx.TimeoutException:
            return "Error: Request timed out (600s). Try again or use a smaller size."
        except Exception as e:
            logger.error("ImageGen (Gemini) error: {}", e)
            return f"Error generating image: {e}"

    async def _execute_grok_edit(
        self,
        prompt: str,
        ref_image_data: bytes,
        ref_mime: str = "image/jpeg",
    ) -> str:
        """Execute image editing using Grok/xAI format."""
        url = f"{self.base_url}/images/edits"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        # Build data URI from image bytes
        b64_str = base64.b64encode(ref_image_data).decode()
        data_uri = f"data:{ref_mime};base64,{b64_str}"

        body = {
            "model": self.model,
            "prompt": prompt,
            "image": {
                "url": data_uri,
                "type": "image_url",
            },
        }

        logger.info(
            "ImageGen (Grok img2img): model={} prompt={!r}",
            self.model, prompt[:80],
        )

        try:
            async with httpx.AsyncClient(
                proxy=self.proxy, timeout=120.0, trust_env=True,
            ) as client:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                if "data" in data and len(data["data"]) > 0:
                    image_data = data["data"][0]
                    if "b64_json" in image_data:
                        return await self._save_base64(image_data["b64_json"])
                    elif "url" in image_data:
                        return await self._download_image(image_data["url"])

                return "Error: No image data in Grok API response"

        except httpx.HTTPStatusError as e:
            return self._format_http_error(e)
        except httpx.TimeoutException:
            return "Error: Request timed out (120s). Try again."
        except Exception as e:
            logger.error("ImageGen (Grok) error: {}", e)
            return f"Error generating image: {e}"

    def _format_http_error(self, e: httpx.HTTPStatusError) -> str:
        """Format HTTP error response."""
        try:
            error_detail = e.response.json()
            error_msg = error_detail.get("error", {}).get("message", e.response.text[:300])
        except Exception:
            error_msg = e.response.text[:300]
        return f"Error: API {e.response.status_code} - {error_msg}"

    async def _save_base64(self, b64_data: str) -> str:
        """Save base64-encoded image to file."""
        try:
            media_dir = get_media_dir("image_gen")
            fname = f"gen_{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
            path = media_dir / fname
            path.write_bytes(base64.b64decode(b64_data))
            logger.info("ImageGen: saved {}", path)
            return f"✓ Image generated successfully.\nFile path: {path}\n\nNext step: Call the 'message' tool with media=['{path}'] to send this image to the user."
        except Exception as e:
            return f"Error saving image: {e}"

    async def _download_image(self, url: str) -> str:
        """Download image from URL and save to file."""
        try:
            async with httpx.AsyncClient(
                proxy=self.proxy, timeout=60.0, trust_env=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()

                content_type = resp.headers.get("content-type", "")
                ext = "png"
                if "jpeg" in content_type or "jpg" in content_type:
                    ext = "jpg"
                elif "webp" in content_type:
                    ext = "webp"

                media_dir = get_media_dir("image_gen")
                fname = f"gen_{int(time.time())}_{uuid.uuid4().hex[:8]}.{ext}"
                path = media_dir / fname
                path.write_bytes(resp.content)

                logger.info("ImageGen: downloaded and saved {}", path)
                return f"✓ Image generated successfully.\nFile path: {path}\n\nNext step: Call the 'message' tool with media=['{path}'] to send this image to the user."
        except Exception as e:
            return f"Error downloading image: {e}"
