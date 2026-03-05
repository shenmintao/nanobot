"""Text-to-Speech provider using Microsoft Edge TTS (free).

Uses the edge-tts library which leverages Microsoft Edge's online TTS service.
No API key required. Supports multiple languages and voices.

Install: pip install edge-tts
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from loguru import logger


# ============================================================================
# Voice presets
# ============================================================================

VOICE_PRESETS: dict[str, str] = {
    # Chinese
    "zh-female": "zh-CN-XiaoxiaoNeural",
    "zh-female-gentle": "zh-CN-XiaohanNeural",
    "zh-male": "zh-CN-YunxiNeural",
    "zh-male-deep": "zh-CN-YunjianNeural",
    # English
    "en-female": "en-US-AriaNeural",
    "en-male": "en-US-GuyNeural",
    # Japanese
    "ja-female": "ja-JP-NanamiNeural",
    "ja-male": "ja-JP-KeitaNeural",
    # Korean
    "ko-female": "ko-KR-SunHiNeural",
    "ko-male": "ko-KR-InJoonNeural",
}


# ============================================================================
# Edge TTS Provider
# ============================================================================

class EdgeTTSProvider:
    """Free TTS using edge-tts library (Microsoft Edge's online TTS).

    Features:
    - Zero cost — uses Microsoft Edge's built-in TTS service
    - High quality neural voices
    - Multiple languages (zh, en, ja, ko, etc.)
    - Adjustable rate and pitch

    Usage:
        tts = EdgeTTSProvider(voice="zh-CN-XiaoxiaoNeural")
        audio_path = await tts.synthesize("你好，今天过得怎么样？")
        # audio_path is a .mp3 file path
    """

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        pitch: str = "+0Hz",
    ):
        """Initialize Edge TTS provider.

        Args:
            voice: Voice name or preset key (e.g. "zh-female", "zh-CN-XiaoxiaoNeural").
            rate: Speech rate adjustment (e.g. "+10%", "-5%").
            pitch: Pitch adjustment (e.g. "+5Hz", "-3Hz").
        """
        # Resolve preset names
        self.voice = VOICE_PRESETS.get(voice, voice)
        self.rate = rate
        self.pitch = pitch

    async def synthesize(self, text: str, output_format: str = "mp3") -> str | None:
        """Convert text to speech, return path to audio file.

        Args:
            text: Text to synthesize.
            output_format: Output format — "mp3" (default) or "ogg" (for WhatsApp PTT).

        Returns:
            Path to the generated audio file, or None on failure.
        """
        if not text or not text.strip():
            return None

        try:
            import edge_tts
        except ImportError:
            logger.error("edge-tts not installed. Install with: pip install edge-tts")
            return None

        try:
            # Generate MP3 first
            mp3_path = Path(tempfile.mktemp(suffix=".mp3", prefix="nanobot_tts_"))
            communicate = edge_tts.Communicate(
                text,
                self.voice,
                rate=self.rate,
                pitch=self.pitch,
            )
            await communicate.save(str(mp3_path))

            if not mp3_path.exists() or mp3_path.stat().st_size == 0:
                logger.error("TTS produced empty file")
                mp3_path.unlink(missing_ok=True)
                return None

            if output_format == "ogg":
                # Convert to OGG Opus for WhatsApp PTT (push-to-talk) style
                ogg_path = await self._convert_to_ogg(mp3_path)
                if ogg_path:
                    mp3_path.unlink(missing_ok=True)
                    return str(ogg_path)
                # Fallback to MP3 if conversion fails
                logger.warning("OGG conversion failed, using MP3 fallback")

            return str(mp3_path)

        except Exception as e:
            logger.error("TTS synthesis failed: {}", e)
            return None

    @staticmethod
    async def _convert_to_ogg(mp3_path: Path) -> Path | None:
        """Convert MP3 to OGG Opus using ffmpeg (for WhatsApp voice messages)."""
        ogg_path = mp3_path.with_suffix(".ogg")
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-i", str(mp3_path),
                "-c:a", "libopus", "-b:a", "64k",
                "-y", str(ogg_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)

            if ogg_path.exists() and ogg_path.stat().st_size > 0:
                return ogg_path
            ogg_path.unlink(missing_ok=True)
            return None

        except FileNotFoundError:
            logger.debug("ffmpeg not found — OGG conversion unavailable")
            return None
        except asyncio.TimeoutError:
            logger.warning("ffmpeg OGG conversion timed out")
            ogg_path.unlink(missing_ok=True)
            return None
        except Exception as e:
            logger.error("OGG conversion failed: {}", e)
            ogg_path.unlink(missing_ok=True)
            return None

    async def list_voices(self, language: str | None = None) -> list[dict]:
        """List available voices, optionally filtered by language.

        Args:
            language: Language filter (e.g. "zh", "en", "ja").

        Returns:
            List of voice info dicts with keys: name, locale, gender.
        """
        try:
            import edge_tts
            voices = await edge_tts.list_voices()
            if language:
                voices = [v for v in voices if v.get("Locale", "").startswith(language)]
            return [
                {
                    "name": v.get("ShortName", ""),
                    "locale": v.get("Locale", ""),
                    "gender": v.get("Gender", ""),
                }
                for v in voices
            ]
        except ImportError:
            logger.error("edge-tts not installed")
            return []
        except Exception as e:
            logger.error("Failed to list voices: {}", e)
            return []
