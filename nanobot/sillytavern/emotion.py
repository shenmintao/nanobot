"""Emotion tracking — extract and store user emotional state from conversations."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.sillytavern.types import EmotionEntry, EmotionProfile

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


# ============================================================================
# LLM Tool Definition for Emotion Extraction
# ============================================================================

_EXTRACT_EMOTION_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "record_emotion",
            "description": "Record the user's emotional state observed in the conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "emotion": {
                        "type": "string",
                        "enum": [
                            "happy", "sad", "anxious", "angry", "neutral",
                            "excited", "lonely", "tired", "grateful", "frustrated",
                        ],
                        "description": "The primary emotion detected in the user's message.",
                    },
                    "intensity": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                        "description": "Intensity of the emotion (0=barely noticeable, 100=overwhelming).",
                    },
                    "trigger": {
                        "type": "string",
                        "description": "Brief reason or trigger for this emotion (1 sentence).",
                    },
                },
                "required": ["emotion", "intensity", "trigger"],
            },
        },
    }
]

_EMOTION_SYSTEM_PROMPT = (
    "You are an emotion analysis assistant. Analyze the user's message and "
    "call the record_emotion tool to record their emotional state. "
    "Focus on the USER's emotions, not the assistant's. "
    "Be sensitive to subtle emotional cues. "
    "If the message is purely factual with no emotional content, use 'neutral' with intensity 30."
)


# ============================================================================
# Emotion Store
# ============================================================================

class EmotionStore:
    """Persistent storage for emotion profiles (JSON files)."""

    def __init__(self, storage_dir: Path | None = None):
        self._storage_dir = storage_dir or (Path.home() / ".nanobot" / "sillytavern" / "emotions")
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _profile_path(self, profile_id: str) -> Path:
        return self._storage_dir / f"{profile_id}.json"

    def load_profile(self, session_key: str, character_id: str = "") -> EmotionProfile:
        """Load or create an emotion profile for a session/character pair."""
        profile_id = self._make_id(session_key, character_id)
        path = self._profile_path(profile_id)

        if path.exists():
            try:
                raw = json.loads(path.read_text("utf-8"))
                return self._dict_to_profile(raw)
            except (json.JSONDecodeError, KeyError):
                logger.warning("Corrupt emotion profile {}, creating new", profile_id)

        now = datetime.now().isoformat()
        return EmotionProfile(
            id=profile_id,
            character_id=character_id,
            session_key=session_key,
            updated_at=now,
        )

    def save_profile(self, profile: EmotionProfile) -> None:
        """Save an emotion profile to disk."""
        path = self._profile_path(profile.id)
        path.write_text(
            json.dumps(self._profile_to_dict(profile), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _make_id(session_key: str, character_id: str) -> str:
        import re
        raw = f"{session_key}_{character_id}" if character_id else session_key
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", raw.lower()).strip("-")[:60]

    @staticmethod
    def _profile_to_dict(p: EmotionProfile) -> dict:
        from dataclasses import asdict
        return asdict(p)

    @staticmethod
    def _dict_to_profile(d: dict) -> EmotionProfile:
        entries = []
        for e in d.get("entries", []):
            if isinstance(e, dict):
                entries.append(EmotionEntry(**{
                    k: v for k, v in e.items()
                    if k in EmotionEntry.__dataclass_fields__
                }))
        return EmotionProfile(
            id=d.get("id", ""),
            character_id=d.get("character_id", ""),
            session_key=d.get("session_key", ""),
            entries=entries,
            current_emotion=d.get("current_emotion", "neutral"),
            current_intensity=d.get("current_intensity", 50),
            trend=d.get("trend", "stable"),
            updated_at=d.get("updated_at", ""),
        )


# ============================================================================
# Emotion Tracker
# ============================================================================

class EmotionTracker:
    """Tracks user emotional state across conversations.

    Uses a lightweight LLM call (tool-call mode) to extract emotion from
    each user message. Runs asynchronously after the main response is sent,
    so it does not block the conversation flow.
    """

    # Keep at most this many entries per profile
    _MAX_ENTRIES = 200
    # Number of recent entries used for trend calculation
    _TREND_WINDOW = 5

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        storage_dir: Path | None = None,
    ):
        self.provider = provider
        self.model = model
        self.store = EmotionStore(storage_dir)

    async def analyze(
        self,
        user_message: str,
        session_key: str,
        character_id: str = "",
    ) -> EmotionEntry | None:
        """Analyze a user message and record the emotion.

        Returns the EmotionEntry on success, None on failure.
        This method is designed to be called via asyncio.create_task()
        so it does not block the main agent loop.
        """
        if not user_message.strip():
            return None

        try:
            response = await self.provider.chat(
                messages=[
                    {"role": "system", "content": _EMOTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message[:500]},  # Limit input size
                ],
                tools=_EXTRACT_EMOTION_TOOL,
                model=self.model,
                max_tokens=256,
                temperature=0.1,
            )

            if not response.has_tool_calls:
                return None

            args = response.tool_calls[0].arguments
            if isinstance(args, str):
                args = json.loads(args)
            if not isinstance(args, dict):
                return None

            now = datetime.now().isoformat()
            entry = EmotionEntry(
                id=f"emo-{hex(int(time.time() * 1000))[2:]}",
                timestamp=now,
                session_key=session_key,
                emotion=args.get("emotion", "neutral"),
                intensity=max(0, min(100, args.get("intensity", 50))),
                trigger=args.get("trigger", ""),
                context_snippet=user_message[:200],
                character_id=character_id,
            )

            # Update profile
            profile = self.store.load_profile(session_key, character_id)
            profile.entries.append(entry)

            # Trim old entries
            if len(profile.entries) > self._MAX_ENTRIES:
                profile.entries = profile.entries[-self._MAX_ENTRIES:]

            # Update current state
            profile.current_emotion = entry.emotion
            profile.current_intensity = entry.intensity
            profile.trend = self._compute_trend(profile.entries)
            profile.updated_at = now

            self.store.save_profile(profile)
            logger.debug(
                "Emotion tracked: {} (intensity={}, trend={})",
                entry.emotion, entry.intensity, profile.trend,
            )
            return entry

        except Exception:
            logger.exception("Emotion analysis failed")
            return None

    def get_current_state(
        self,
        session_key: str,
        character_id: str = "",
    ) -> tuple[str, int, str]:
        """Get current emotion state: (emotion, intensity, trend)."""
        profile = self.store.load_profile(session_key, character_id)
        return profile.current_emotion, profile.current_intensity, profile.trend

    def get_recent_entries(
        self,
        session_key: str,
        character_id: str = "",
        count: int = 5,
    ) -> list[EmotionEntry]:
        """Get the most recent emotion entries."""
        profile = self.store.load_profile(session_key, character_id)
        return profile.entries[-count:]

    def is_negative_streak(
        self,
        session_key: str,
        character_id: str = "",
        threshold: int = 3,
    ) -> bool:
        """Check if the user has had consecutive negative emotions."""
        negative_emotions = {"sad", "anxious", "angry", "lonely", "frustrated", "tired"}
        recent = self.get_recent_entries(session_key, character_id, count=threshold)
        if len(recent) < threshold:
            return False
        return all(e.emotion in negative_emotions for e in recent)

    @classmethod
    def _compute_trend(cls, entries: list[EmotionEntry]) -> str:
        """Compute emotion trend from recent entries."""
        recent = entries[-cls._TREND_WINDOW:]
        if len(recent) < 2:
            return "stable"

        # Map emotions to valence scores
        valence_map = {
            "happy": 80, "excited": 85, "grateful": 75,
            "neutral": 50,
            "tired": 35, "anxious": 30, "lonely": 25,
            "frustrated": 20, "sad": 15, "angry": 10,
        }

        scores = [valence_map.get(e.emotion, 50) for e in recent]

        # Compare first half vs second half
        mid = len(scores) // 2
        first_avg = sum(scores[:mid]) / max(mid, 1)
        second_avg = sum(scores[mid:]) / max(len(scores) - mid, 1)

        diff = second_avg - first_avg
        if diff > 10:
            return "rising"
        elif diff < -10:
            return "falling"
        return "stable"

    def format_emotion_context(
        self,
        session_key: str,
        character_id: str = "",
    ) -> str:
        """Format emotion state for injection into system prompt."""
        emotion, intensity, trend = self.get_current_state(session_key, character_id)

        if emotion == "neutral" and intensity < 40:
            return ""  # Don't inject for low-intensity neutral

        # Translate emotion to Chinese for more natural context
        emotion_zh = {
            "happy": "开心", "sad": "难过", "anxious": "焦虑",
            "angry": "生气", "neutral": "平静", "excited": "兴奋",
            "lonely": "孤独", "tired": "疲惫", "grateful": "感恩",
            "frustrated": "沮丧",
        }
        trend_zh = {"rising": "好转中", "falling": "下降中", "stable": "稳定"}

        intensity_desc = (
            "非常" if intensity >= 80 else
            "比较" if intensity >= 60 else
            "有点" if intensity >= 40 else
            "略微"
        )

        lines = [
            f"用户当前情绪: {intensity_desc}{emotion_zh.get(emotion, emotion)}",
            f"情绪趋势: {trend_zh.get(trend, trend)}",
        ]

        # Add care hint for negative streaks
        if self.is_negative_streak(session_key, character_id):
            lines.append("⚠️ 用户连续多次表现出负面情绪，请给予更多关心和温暖。")

        return "\n".join(lines)
