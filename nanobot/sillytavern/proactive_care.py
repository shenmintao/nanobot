"""Proactive care engine — trigger caring messages based on emotion state and interaction patterns."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ProactiveCareConfig
    from nanobot.providers.base import LLMProvider
    from nanobot.sillytavern.emotion import EmotionTracker
    from nanobot.sillytavern.scene_awareness import SceneAwareness


# ============================================================================
# Care Types
# ============================================================================

CARE_TYPE_GREETING = "greeting"
CARE_TYPE_EMOTION = "emotion_care"
CARE_TYPE_MISS_YOU = "miss_you"

_NEGATIVE_EMOTIONS = frozenset({"sad", "anxious", "angry", "lonely", "frustrated", "tired"})


# ============================================================================
# LLM Tool Definition for Care Message Generation
# ============================================================================

_GENERATE_CARE_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "send_care_message",
            "description": "Generate a caring message to send to the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The caring message to send. Should be warm, natural, and in-character.",
                    },
                },
                "required": ["message"],
            },
        },
    }
]


# ============================================================================
# Proactive Care Engine
# ============================================================================

class ProactiveCareEngine:
    """Proactive care engine — decides when and what caring messages to send.

    Integrates with CronService to periodically check care conditions.
    Uses LLM to generate natural, in-character caring messages.
    """

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        config: ProactiveCareConfig,
        emotion_tracker: EmotionTracker | None = None,
        scene_awareness: SceneAwareness | None = None,
        character_name: str = "",
        character_description: str = "",
    ):
        self.provider = provider
        self.model = model
        self.config = config
        self.emotion_tracker = emotion_tracker
        self.scene_awareness = scene_awareness
        self.character_name = character_name
        self.character_description = character_description

        # Cooldown tracking: session_key -> {care_type -> last_sent_timestamp}
        self._cooldowns: dict[str, dict[str, float]] = {}
        # Last interaction tracking: session_key -> timestamp
        self._last_interaction: dict[str, float] = {}

    def record_interaction(self, session_key: str) -> None:
        """Record that the user interacted (sent a message)."""
        self._last_interaction[session_key] = time.time()

    def get_last_interaction(self, session_key: str) -> float | None:
        """Get the timestamp of the last user interaction."""
        return self._last_interaction.get(session_key)

    async def check_and_generate(
        self,
        session_key: str,
        care_type_hint: str | None = None,
    ) -> str | None:
        """Check if care is needed and generate a message if so.

        Args:
            session_key: The session to check.
            care_type_hint: Optional hint for the care type (e.g. from cron).
                If None, the engine evaluates all care types.

        Returns:
            The care message string, or None if no care is needed.
        """
        if not self.config.enabled:
            return None

        care_type = care_type_hint or self._evaluate_care_need(session_key)
        if not care_type:
            return None

        if self._is_cooling_down(session_key, care_type):
            logger.debug("Care type '{}' is cooling down for session {}", care_type, session_key)
            return None

        message = await self._generate_care_message(session_key, care_type)
        if message:
            self._record_cooldown(session_key, care_type)
            logger.info("Proactive care sent: type={}, session={}", care_type, session_key)
        return message

    def _evaluate_care_need(self, session_key: str) -> str | None:
        """Evaluate what type of care is needed, if any.

        Priority: emotion_care > miss_you > greeting
        """
        # 1. Emotion care: check for negative streak
        if self.emotion_tracker and self.config.emotion_care_negative_threshold > 0:
            if self.emotion_tracker.is_negative_streak(
                session_key,
                threshold=self.config.emotion_care_negative_threshold,
            ):
                return CARE_TYPE_EMOTION

        # 2. Miss you: check last interaction time
        last = self._last_interaction.get(session_key)
        if last and self.config.miss_you_after_hours > 0:
            hours_since = (time.time() - last) / 3600
            if hours_since >= self.config.miss_you_after_hours:
                return CARE_TYPE_MISS_YOU

        return None

    def _is_cooling_down(self, session_key: str, care_type: str) -> bool:
        """Check if a care type is in cooldown for the given session."""
        session_cooldowns = self._cooldowns.get(session_key, {})
        last_sent = session_cooldowns.get(care_type)
        if last_sent is None:
            return False

        cooldown_minutes = self.config.cooldown_minutes.get(care_type, 240)
        elapsed_minutes = (time.time() - last_sent) / 60
        return elapsed_minutes < cooldown_minutes

    def _record_cooldown(self, session_key: str, care_type: str) -> None:
        """Record that a care message was sent (start cooldown)."""
        if session_key not in self._cooldowns:
            self._cooldowns[session_key] = {}
        self._cooldowns[session_key][care_type] = time.time()

    async def _generate_care_message(self, session_key: str, care_type: str) -> str | None:
        """Use LLM to generate a natural, in-character caring message."""
        context_parts: list[str] = []

        # Character context
        if self.character_name:
            context_parts.append(f"你是{self.character_name}。")
        if self.character_description:
            context_parts.append(f"角色设定: {self.character_description[:500]}")

        # Emotion context
        if self.emotion_tracker:
            emotion, intensity, trend = self.emotion_tracker.get_current_state(session_key)
            emotion_zh = {
                "happy": "开心", "sad": "难过", "anxious": "焦虑",
                "angry": "生气", "neutral": "平静", "excited": "兴奋",
                "lonely": "孤独", "tired": "疲惫", "grateful": "感恩",
                "frustrated": "沮丧",
            }
            context_parts.append(f"用户当前情绪: {emotion_zh.get(emotion, emotion)} (强度: {intensity}/100)")

        # Scene context
        if self.scene_awareness:
            scene = self.scene_awareness.build_context(session_key)
            context_parts.append(f"当前时间: {scene.time_period} ({scene.day_of_week}, {scene.day_type})")
            if scene.holiday:
                context_parts.append(f"今天是{scene.holiday}")
            if scene.anniversary_note:
                context_parts.append(scene.anniversary_note)

        # Last interaction
        last = self._last_interaction.get(session_key)
        if last:
            hours_ago = (time.time() - last) / 3600
            if hours_ago >= 1:
                context_parts.append(f"距离上次聊天已过去 {hours_ago:.0f} 小时")

        # Care type specific instructions
        care_instructions = {
            CARE_TYPE_GREETING: (
                "请生成一条自然的问候消息。根据时间段选择早安或晚安。"
                "语气温暖亲切，可以关心对方的状态。不要太长，1-2句话即可。"
            ),
            CARE_TYPE_EMOTION: (
                "用户最近情绪持续低落。请生成一条温暖的关怀消息。"
                "不要直接说'我注意到你情绪不好'，而是自然地表达关心。"
                "可以问问对方最近怎么样，或者分享一些温暖的话。1-3句话。"
            ),
            CARE_TYPE_MISS_YOU: (
                "已经很久没有和用户聊天了。请生成一条自然的思念消息。"
                "语气要自然，不要太刻意。可以说想到了对方，或者分享一个小事。1-2句话。"
            ),
        }

        instruction = care_instructions.get(care_type, care_instructions[CARE_TYPE_GREETING])
        context_parts.append(instruction)

        system_prompt = "\n".join(context_parts)

        try:
            response = await self.provider.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "请生成关怀消息。"},
                ],
                tools=_GENERATE_CARE_TOOL,
                model=self.model,
                max_tokens=256,
                temperature=0.8,
            )

            if response.has_tool_calls:
                args = response.tool_calls[0].arguments
                if isinstance(args, str):
                    args = json.loads(args)
                if isinstance(args, dict):
                    return args.get("message", "").strip() or None

            # Fallback: use content directly if no tool call
            if response.content and response.content.strip():
                return response.content.strip()

            return None

        except Exception:
            logger.exception("Failed to generate care message")
            return None

    def format_status(self, session_key: str) -> dict[str, Any]:
        """Get the current care status for a session (for debugging)."""
        status: dict[str, Any] = {
            "last_interaction": None,
            "cooldowns": {},
            "care_need": self._evaluate_care_need(session_key),
        }

        last = self._last_interaction.get(session_key)
        if last:
            status["last_interaction"] = datetime.fromtimestamp(last).isoformat()
            status["hours_since_interaction"] = round((time.time() - last) / 3600, 1)

        session_cooldowns = self._cooldowns.get(session_key, {})
        for care_type, last_sent in session_cooldowns.items():
            cooldown_min = self.config.cooldown_minutes.get(care_type, 240)
            elapsed_min = (time.time() - last_sent) / 60
            status["cooldowns"][care_type] = {
                "last_sent": datetime.fromtimestamp(last_sent).isoformat(),
                "cooldown_minutes": cooldown_min,
                "remaining_minutes": max(0, round(cooldown_min - elapsed_min, 1)),
                "is_active": elapsed_min < cooldown_min,
            }

        return status
