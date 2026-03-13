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

    def _resolve_default_reference(self, scene: str = "") -> str | None:
        """Resolve the default reference image: active character > global config.

        Supports in character card extensions.nanobot:
          - reference_image_base64: base64-encoded image (most portable)
          - reference_image: file path to an image file
          - reference_images: dict of scene → file path (e.g. {"beach": "/path/to/beach.png"})
          - reference_images_base64: dict of scene → base64 string

        Args:
            scene: Optional scene tag (e.g. "beach", "formal", "winter").
                   If provided, tries to match a scene-specific image first.
        """
        # 1. Check active SillyTavern character's extensions
        try:
            from nanobot.sillytavern.storage import get_active_character
            char = get_active_character()
            if char and char.data.extensions:
                nanobot_ext = char.data.extensions.get("nanobot", {})
                if isinstance(nanobot_ext, dict):
                    # Try scene-specific image first
                    if scene:
                        result = self._resolve_scene_reference(char, nanobot_ext, scene)
                        if result:
                            return result

                    # Prefer base64 (self-contained in the card JSON)
                    b64_data = nanobot_ext.get("reference_image_base64", "")
                    if b64_data:
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

    def _resolve_scene_reference(self, char: Any, nanobot_ext: dict, scene: str) -> str | None:
        """Try to resolve a scene-specific reference image from character card."""
        scene_lower = scene.lower()

        # Check reference_images_base64 dict
        scene_b64_map = nanobot_ext.get("reference_images_base64", {})
        if isinstance(scene_b64_map, dict) and scene_lower in scene_b64_map:
            b64_data = scene_b64_map[scene_lower]
            if b64_data:
                cache_path = self._cache_base64_reference(f"{char.id}_{scene_lower}", b64_data)
                if cache_path:
                    logger.debug("Using character '{}' scene '{}' embedded reference", char.name, scene)
                    return cache_path

        # Check reference_images file path dict
        scene_map = nanobot_ext.get("reference_images", {})
        if isinstance(scene_map, dict) and scene_lower in scene_map:
            path = scene_map[scene_lower]
            if path and Path(path).exists():
                logger.debug("Using character '{}' scene '{}' reference: {}", char.name, scene, path)
                return path

        return None

    def _resolve_ref(self, ref: str) -> str | None:
        """Resolve a single reference_image value.

        Handles:
          - "__default__"        → character's default reference image
          - "__default__:beach"  → character's scene-specific reference (falls back to default)
          - "/path/to/file.png"  → literal file path (returned as-is)
        """
        if not ref:
            return None
        if ref.startswith("__default__"):
            scene = ""
            if ":" in ref:
                scene = ref.split(":", 1)[1]
            resolved = self._resolve_default_reference(scene)
            if not resolved and scene:
                # Scene not found, fall back to default (no scene)
                resolved = self._resolve_default_reference()
            return resolved
        return ref

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
            "For multi-image composition (e.g., combining people from different photos), "
            "provide multiple file paths as a list. "
            "IMPORTANT: After generating, you MUST call the 'message' tool "
            "with the returned file path in the 'media' parameter to send the image to the user. "
            "Do not just reply with text - the user expects to receive the actual image."
        )
        base += (
            " When generating images of yourself or your character, set reference_image to "
            "'__default__' to use the character's avatar as a base for consistent appearance. "
            "For scene-specific outfits, use '__default__:scene' (e.g. '__default__:beach', "
            "'__default__:formal', '__default__:winter'). Falls back to default avatar if "
            "no scene-specific image is configured."
        )
        return base

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Text description of the image to generate, or instructions for editing the reference image(s). "
                    "For multi-image composition, describe how to combine them (e.g., 'Put the person from image 1 and the cat from image 2 together at the beach').",
                },
                "reference_image": {
                    "type": ["string", "array"],
                    "items": {"type": "string"},
                    "description": "Optional file path(s) to source image(s) for image-to-image editing. "
                    "Can be a single path string, or an array of paths for multi-image composition. "
                    "When provided, the model will use these images as a base and apply the prompt as editing/composition instructions.",
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
        reference_image: str | list[str] | None = None,
        size: str | None = None,
        quality: str = "standard",
        style: str = "vivid",
        **kwargs: Any,
    ) -> str:
        if not self._api_key:
            return "Error: Image generation API key not configured. Set tools.imageGen.apiKey in config."

        # Normalize reference_image to list, resolving __default__ and __default__:scene
        ref_images: list[str] = []
        if reference_image:
            if isinstance(reference_image, str):
                ref_images = [self._resolve_ref(reference_image)]
            elif isinstance(reference_image, list):
                ref_images = [self._resolve_ref(r) for r in reference_image]
            ref_images = [r for r in ref_images if r]  # remove None

        # Validate and load all reference images
        ref_images_data: list[tuple[bytes, str]] = []  # [(image_bytes, mime_type), ...]
        for ref_path_str in ref_images:
            ref_path = Path(ref_path_str)
            if not ref_path.exists():
                return f"Error: Reference image not found: {ref_path_str}"
            try:
                image_bytes = ref_path.read_bytes()
                ext = ref_path.suffix.lower()
                mime_type = {
                    '.png': 'image/png', '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg', '.webp': 'image/webp',
                    '.gif': 'image/gif',
                }.get(ext, 'image/jpeg')
                ref_images_data.append((image_bytes, mime_type))
            except Exception as e:
                return f"Error reading reference image {ref_path_str}: {e}"

        # Route to appropriate implementation
        if self._is_gemini_model():
            return await self._execute_gemini(prompt, size, ref_images_data)
        elif self._is_grok_model():
            if ref_images_data:
                return await self._execute_grok_edit(prompt, ref_images_data)
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
        ref_images_data: list[tuple[bytes, str]] | None = None,
    ) -> str:
        """Execute image generation/editing using Gemini format (supports multiple reference images)."""
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

        # Add all reference images if provided (supports multi-image composition)
        if ref_images_data:
            for image_bytes, mime_type in ref_images_data:
                content_parts.append({
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": base64.b64encode(image_bytes).decode(),
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

        mode = f"img2img ({len(ref_images_data)} images)" if ref_images_data else "text2img"
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
        ref_images_data: list[tuple[bytes, str]],
    ) -> str:
        """Execute image editing using Grok/xAI format (supports multiple images)."""
        url = f"{self.base_url}/images/edits"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        # Build images array with data URIs
        images = []
        for image_bytes, mime_type in ref_images_data:
            b64_str = base64.b64encode(image_bytes).decode()
            data_uri = f"data:{mime_type};base64,{b64_str}"
            images.append({
                "url": data_uri,
                "type": "image_url",
            })

        # Use 'images' array for multiple images, or 'image' for single (backward compatible)
        if len(images) == 1:
            body = {
                "model": self.model,
                "prompt": prompt,
                "image": images[0],
            }
        else:
            body = {
                "model": self.model,
                "prompt": prompt,
                "images": images,
            }

        logger.info(
            "ImageGen (Grok img2img): model={} images={} prompt={!r}",
            self.model, len(images), prompt[:80],
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
