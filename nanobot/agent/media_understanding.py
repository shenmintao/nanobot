"""Media understanding — extract content from videos, PDFs, and documents."""

from __future__ import annotations

import asyncio
import base64
import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


# ============================================================================
# Supported Extensions
# ============================================================================

_VIDEO_EXTS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"})
_PDF_EXTS = frozenset({".pdf"})
_DOC_EXTS = frozenset({".doc", ".docx"})

_ALL_SUPPORTED = _VIDEO_EXTS | _PDF_EXTS | _DOC_EXTS


# ============================================================================
# Media Understanding
# ============================================================================

class MediaUnderstanding:
    """Unified media understanding interface.

    Handles:
    - Video: extract keyframes with ffmpeg, describe with Vision LLM
    - PDF: extract text with pdfplumber or PyPDF2
    - Documents: extract text with python-docx

    All methods are designed to fail gracefully — returning None or a
    helpful error message when dependencies are missing.
    """

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        video_enabled: bool = True,
        pdf_enabled: bool = True,
        max_frames: int = 3,
    ):
        self.provider = provider
        self.model = model
        self.video_enabled = video_enabled
        self.pdf_enabled = pdf_enabled
        self.max_frames = max_frames

    @staticmethod
    def is_supported(file_path: str) -> bool:
        """Check if the file type is supported for media understanding."""
        return Path(file_path).suffix.lower() in _ALL_SUPPORTED

    async def process(self, file_path: str) -> str | None:
        """Process a media file and return a text description/content.

        Returns None if the file type is not supported or processing fails.
        """
        ext = Path(file_path).suffix.lower()

        if ext in _VIDEO_EXTS:
            if not self.video_enabled:
                return None
            return await self._process_video(file_path)
        elif ext in _PDF_EXTS:
            if not self.pdf_enabled:
                return None
            return self._process_pdf(file_path)
        elif ext in _DOC_EXTS:
            return self._process_document(file_path)

        return None

    # ========================================================================
    # Video Processing
    # ========================================================================

    async def _process_video(self, file_path: str) -> str | None:
        """Extract keyframes from a video and describe them with Vision LLM."""
        if not Path(file_path).is_file():
            return None

        frames = await self._extract_keyframes(file_path)
        if not frames:
            return "[视频处理失败: 无法提取关键帧。请确保已安装 ffmpeg。]"

        try:
            # Build multimodal message with keyframes
            content: list[dict[str, Any]] = []
            for frame_path in frames:
                try:
                    b64 = base64.b64encode(Path(frame_path).read_bytes()).decode()
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    })
                except Exception:
                    continue

            if not content:
                return None

            frame_desc = f"{len(content)}个关键帧（开头、中间、结尾）" if len(content) == 3 else f"{len(content)}个关键帧"
            content.append({
                "type": "text",
                "text": f"这是一个视频的{frame_desc}。请简要描述这个视频的内容。",
            })

            response = await self.provider.chat(
                messages=[{"role": "user", "content": content}],
                model=self.model,
                max_tokens=512,
                temperature=0.3,
            )

            return f"[视频内容描述]\n{response.content}" if response.content else None

        except Exception:
            logger.exception("Video understanding failed for {}", file_path)
            return None
        finally:
            # Clean up temporary frame files
            for frame_path in frames:
                try:
                    Path(frame_path).unlink(missing_ok=True)
                except Exception:
                    pass

    async def _extract_keyframes(self, file_path: str) -> list[str]:
        """Extract keyframes from a video using ffmpeg.

        Returns a list of temporary file paths for the extracted frames.
        """
        # First, get video duration
        duration = await self._get_video_duration(file_path)
        if duration is None or duration <= 0:
            return []

        # Calculate timestamps for keyframes
        if duration <= 2:
            timestamps = [0]
        elif duration <= 5:
            timestamps = [0, duration - 0.5]
        else:
            timestamps = [0, duration / 2, max(0, duration - 1)]

        timestamps = timestamps[: self.max_frames]

        frames: list[str] = []
        for i, ts in enumerate(timestamps):
            try:
                output = tempfile.mktemp(suffix=f"_frame{i}.jpg", prefix="nanobot_")
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-ss", str(ts), "-i", file_path,
                    "-vframes", "1", "-q:v", "2", "-y", output,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.communicate(), timeout=30)
                if Path(output).exists() and Path(output).stat().st_size > 0:
                    frames.append(output)
                else:
                    # Clean up empty file
                    Path(output).unlink(missing_ok=True)
            except asyncio.TimeoutError:
                logger.warning("ffmpeg frame extraction timed out at ts={}", ts)
            except FileNotFoundError:
                logger.debug("ffmpeg not found — video processing unavailable")
                return []
            except Exception:
                logger.debug("Frame extraction failed at ts={}", ts, exc_info=True)

        return frames

    @staticmethod
    async def _get_video_duration(file_path: str) -> float | None:
        """Get video duration in seconds using ffprobe."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            if stdout:
                data = json.loads(stdout)
                return float(data.get("format", {}).get("duration", 0))
        except FileNotFoundError:
            logger.debug("ffprobe not found — video processing unavailable")
        except (asyncio.TimeoutError, json.JSONDecodeError, ValueError, KeyError):
            pass
        return None

    # ========================================================================
    # PDF Processing
    # ========================================================================

    @staticmethod
    def _process_pdf(file_path: str, max_pages: int = 20, max_chars: int = 5000) -> str | None:
        """Extract text from a PDF file."""
        if not Path(file_path).is_file():
            return None

        # Try pdfplumber first (better quality)
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                pages = pdf.pages[:max_pages]
                text = "\n\n".join(
                    page.extract_text() or "" for page in pages
                )
            if text.strip():
                truncated = len(text) > max_chars
                result = text[:max_chars]
                suffix = f"\n\n[... 共{len(pdf.pages)}页，已截取前{max_pages}页]" if truncated else ""
                return f"[PDF 内容]\n{result}{suffix}"
        except ImportError:
            pass
        except Exception:
            logger.debug("pdfplumber failed for {}", file_path, exc_info=True)

        # Fallback to PyPDF2
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(file_path)
            pages = reader.pages[:max_pages]
            text = "\n\n".join(
                page.extract_text() or "" for page in pages
            )
            if text.strip():
                truncated = len(text) > max_chars
                result = text[:max_chars]
                suffix = f"\n\n[... 共{len(reader.pages)}页，已截取前{max_pages}页]" if truncated else ""
                return f"[PDF 内容]\n{result}{suffix}"
        except ImportError:
            return "[PDF 处理需要安装 pdfplumber 或 PyPDF2: pip install pdfplumber]"
        except Exception:
            logger.debug("PyPDF2 failed for {}", file_path, exc_info=True)

        return None

    # ========================================================================
    # Document Processing
    # ========================================================================

    @staticmethod
    def _process_document(file_path: str, max_chars: int = 5000) -> str | None:
        """Extract text from a Word document (.docx)."""
        if not Path(file_path).is_file():
            return None

        ext = Path(file_path).suffix.lower()
        if ext == ".doc":
            return "[.doc 格式暂不支持，请转换为 .docx 格式]"

        try:
            from docx import Document
            doc = Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            text = "\n\n".join(paragraphs)
            if text.strip():
                truncated = len(text) > max_chars
                result = text[:max_chars]
                suffix = "\n\n[... 内容已截取]" if truncated else ""
                return f"[文档内容]\n{result}{suffix}"
        except ImportError:
            return "[Word 文档处理需要安装 python-docx: pip install python-docx]"
        except Exception:
            logger.debug("docx processing failed for {}", file_path, exc_info=True)

        return None
