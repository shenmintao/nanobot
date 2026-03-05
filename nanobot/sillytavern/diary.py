"""Shared diary / timeline — auto-generate daily diary entries from conversations."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.sillytavern.types import DiaryBook, DiaryEntry, DiarySettings

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session, SessionManager
    from nanobot.sillytavern.emotion import EmotionTracker


# ============================================================================
# LLM Tool Definition for Diary Generation
# ============================================================================

_SAVE_DIARY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_diary",
            "description": "Save a diary entry summarizing today's conversations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "A short, warm title for the diary entry (e.g. '一起看了日落').",
                    },
                    "content": {
                        "type": "string",
                        "description": "The diary content in markdown, 2-3 paragraphs, written from 'our' perspective.",
                    },
                    "highlights": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "3-5 key moments or highlights from today.",
                    },
                    "mood": {
                        "type": "string",
                        "description": "The overall mood of the day (e.g. '开心', '平静', '温馨').",
                    },
                },
                "required": ["title", "content", "highlights", "mood"],
            },
        },
    }
]

_DIARY_SYSTEM_PROMPT = """你是一个日记助手。请根据以下今天的对话记录和情感变化，以第一人称（"我们"的视角）写一篇温馨的日记。

## 今天的对话摘要
{conversation_summary}

## 今天的情感变化
{emotion_timeline}

请调用 save_diary 工具，包含：
- title: 简短标题（如"一起看了日落"）
- content: 2-3段温馨的日记内容（markdown格式）
- highlights: 3-5个今天的重要时刻
- mood: 今天的主要情绪

注意：
- 用温暖、亲密的语气
- 不要提及"AI"、"模型"、"系统"等技术词汇
- 把对话中的有趣、温暖、重要的时刻记录下来
- 如果对话内容较少，日记也可以简短"""


# ============================================================================
# Diary Store
# ============================================================================

class DiaryStore:
    """Persistent storage for diary entries (JSON files)."""

    def __init__(self, storage_dir: Path | None = None):
        self._storage_dir = storage_dir or (Path.home() / ".nanobot" / "sillytavern" / "diaries")
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _book_path(self, book_id: str) -> Path:
        return self._storage_dir / f"{book_id}.json"

    def load_book(self, session_key: str, character_id: str = "") -> DiaryBook:
        """Load or create a diary book for a session/character pair."""
        book_id = self._make_id(session_key, character_id)
        path = self._book_path(book_id)

        if path.exists():
            try:
                raw = json.loads(path.read_text("utf-8"))
                return self._dict_to_book(raw)
            except (json.JSONDecodeError, KeyError):
                logger.warning("Corrupt diary book {}, creating new", book_id)

        now = datetime.now().isoformat()
        return DiaryBook(
            id=book_id,
            character_id=character_id,
            session_key=session_key,
            created_at=now,
            updated_at=now,
        )

    def save_book(self, book: DiaryBook) -> None:
        """Save a diary book to disk."""
        path = self._book_path(book.id)
        path.write_text(
            json.dumps(self._book_to_dict(book), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def save_entry(self, entry: DiaryEntry, session_key: str, character_id: str = "") -> None:
        """Add a diary entry to the book and save."""
        book = self.load_book(session_key, character_id)
        # Replace existing entry for the same date
        book.entries = [e for e in book.entries if e.date != entry.date]
        book.entries.append(entry)
        book.entries.sort(key=lambda e: e.date)
        book.updated_at = datetime.now().isoformat()
        self.save_book(book)

    def get_entry_by_date(self, session_key: str, target_date: str, character_id: str = "") -> DiaryEntry | None:
        """Get a diary entry for a specific date (YYYY-MM-DD)."""
        book = self.load_book(session_key, character_id)
        for entry in book.entries:
            if entry.date == target_date:
                return entry
        return None

    def get_recent_entries(self, session_key: str, character_id: str = "", count: int = 7) -> list[DiaryEntry]:
        """Get the most recent diary entries."""
        book = self.load_book(session_key, character_id)
        return book.entries[-count:]

    def search_entries(self, session_key: str, keyword: str, character_id: str = "") -> list[DiaryEntry]:
        """Search diary entries by keyword."""
        book = self.load_book(session_key, character_id)
        keyword_lower = keyword.lower()
        return [
            e for e in book.entries
            if keyword_lower in e.title.lower()
            or keyword_lower in e.content.lower()
            or any(keyword_lower in h.lower() for h in e.highlights)
        ]

    def get_timeline_summary(self, session_key: str, character_id: str = "") -> str:
        """Generate a timeline summary of all diary entries."""
        book = self.load_book(session_key, character_id)
        if not book.entries:
            return "还没有日记记录。"

        lines = [f"📖 我们的故事 — 共{len(book.entries)}篇日记\n"]
        for entry in book.entries:
            mood_emoji = _mood_to_emoji(entry.mood)
            lines.append(f"**{entry.date}** {mood_emoji} {entry.title}")
            if entry.highlights:
                lines.append(f"  · {' · '.join(entry.highlights[:3])}")
        return "\n".join(lines)

    @staticmethod
    def _make_id(session_key: str, character_id: str) -> str:
        raw = f"{session_key}_{character_id}" if character_id else session_key
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", raw.lower()).strip("-")[:60]

    @staticmethod
    def _book_to_dict(book: DiaryBook) -> dict:
        from dataclasses import asdict
        return asdict(book)

    @staticmethod
    def _dict_to_book(d: dict) -> DiaryBook:
        entries = []
        for e in d.get("entries", []):
            if isinstance(e, dict):
                entries.append(DiaryEntry(**{
                    k: v for k, v in e.items()
                    if k in DiaryEntry.__dataclass_fields__
                }))

        settings_raw = d.get("settings", {})
        settings = DiarySettings(**{
            k: v for k, v in settings_raw.items()
            if k in DiarySettings.__dataclass_fields__
        }) if isinstance(settings_raw, dict) else DiarySettings()

        return DiaryBook(
            id=d.get("id", ""),
            character_id=d.get("character_id", ""),
            session_key=d.get("session_key", ""),
            entries=entries,
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            settings=settings,
        )


# ============================================================================
# Diary Generator
# ============================================================================

class DiaryGenerator:
    """Generates daily diary entries from conversation history.

    Designed to be triggered by CronService at the configured time each day.
    Uses LLM to create warm, in-character diary entries.
    """

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        emotion_tracker: EmotionTracker | None = None,
        session_manager: SessionManager | None = None,
        store: DiaryStore | None = None,
    ):
        self.provider = provider
        self.model = model
        self.emotion_tracker = emotion_tracker
        self.sessions = session_manager
        self.store = store or DiaryStore()

    async def generate_daily_diary(
        self,
        session_key: str,
        character_id: str = "",
        min_messages: int = 5,
    ) -> DiaryEntry | None:
        """Generate a diary entry for today's conversations.

        Returns the DiaryEntry on success, None if not enough messages
        or generation fails.
        """
        today = date.today().isoformat()

        # Check if diary already exists for today
        existing = self.store.get_entry_by_date(session_key, today, character_id)
        if existing and not existing.user_edited:
            logger.debug("Diary already exists for {} on {}", session_key, today)
            return existing

        # Get today's conversation messages
        today_messages = self._get_today_messages(session_key)
        if len(today_messages) < min_messages:
            logger.debug(
                "Not enough messages for diary: {} < {} (session={})",
                len(today_messages), min_messages, session_key,
            )
            return None

        # Build conversation summary
        conversation_summary = self._summarize_messages(today_messages)

        # Build emotion timeline
        emotion_timeline = self._build_emotion_timeline(session_key, character_id)

        # Generate diary via LLM
        prompt = _DIARY_SYSTEM_PROMPT.format(
            conversation_summary=conversation_summary,
            emotion_timeline=emotion_timeline or "今天没有明显的情感波动。",
        )

        try:
            response = await self.provider.chat(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "请为今天写一篇日记。"},
                ],
                tools=_SAVE_DIARY_TOOL,
                model=self.model,
                max_tokens=1024,
                temperature=0.7,
            )

            if not response.has_tool_calls:
                logger.warning("Diary generation did not produce a tool call")
                return None

            args = response.tool_calls[0].arguments
            if isinstance(args, str):
                args = json.loads(args)
            if not isinstance(args, dict):
                return None

            now = datetime.now()
            entry = DiaryEntry(
                id=f"diary-{hex(int(time.time() * 1000))[2:]}",
                date=today,
                timestamp=now.isoformat(),
                title=args.get("title", "今天的日记"),
                content=args.get("content", ""),
                mood=args.get("mood", "平静"),
                highlights=args.get("highlights", []),
                character_id=character_id,
                session_key=session_key,
                auto_generated=True,
                user_edited=False,
            )

            self.store.save_entry(entry, session_key, character_id)
            logger.info("Diary generated for {} on {}: {}", session_key, today, entry.title)
            return entry

        except Exception:
            logger.exception("Diary generation failed for session {}", session_key)
            return None

    def _get_today_messages(self, session_key: str) -> list[dict]:
        """Get today's messages from the session."""
        if not self.sessions:
            return []

        session = self.sessions.get_or_create(session_key)
        today_str = date.today().isoformat()

        today_msgs: list[dict] = []
        for msg in session.messages:
            ts = msg.get("timestamp", "")
            if isinstance(ts, str) and ts.startswith(today_str):
                today_msgs.append(msg)

        return today_msgs

    @staticmethod
    def _summarize_messages(messages: list[dict], max_chars: int = 3000) -> str:
        """Create a concise summary of messages for the diary prompt."""
        lines: list[str] = []
        total_chars = 0

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            # Skip tool messages and system messages
            if role in ("tool", "system"):
                continue

            # Handle multimodal content
            if isinstance(content, list):
                text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                content = " ".join(text_parts)

            if not isinstance(content, str) or not content.strip():
                continue

            # Truncate individual messages
            snippet = content[:200]
            if len(content) > 200:
                snippet += "..."

            prefix = "用户" if role == "user" else "角色"
            line = f"- {prefix}: {snippet}"
            lines.append(line)
            total_chars += len(line)

            if total_chars >= max_chars:
                lines.append(f"... (共{len(messages)}条消息)")
                break

        return "\n".join(lines) if lines else "今天的对话内容较少。"

    def _build_emotion_timeline(self, session_key: str, character_id: str = "") -> str:
        """Build an emotion timeline string from today's emotion entries."""
        if not self.emotion_tracker:
            return ""

        entries = self.emotion_tracker.get_recent_entries(session_key, character_id, count=20)
        if not entries:
            return ""

        today_str = date.today().isoformat()
        today_entries = [e for e in entries if e.timestamp.startswith(today_str)]
        if not today_entries:
            return ""

        emotion_zh = {
            "happy": "开心", "sad": "难过", "anxious": "焦虑",
            "angry": "生气", "neutral": "平静", "excited": "兴奋",
            "lonely": "孤独", "tired": "疲惫", "grateful": "感恩",
            "frustrated": "沮丧",
        }

        lines: list[str] = []
        for entry in today_entries:
            ts = entry.timestamp[11:16] if len(entry.timestamp) > 16 else ""  # HH:MM
            emo = emotion_zh.get(entry.emotion, entry.emotion)
            trigger = f" — {entry.trigger}" if entry.trigger else ""
            lines.append(f"- {ts} {emo} (强度{entry.intensity}){trigger}")

        return "\n".join(lines)

    def format_diary_context(self, session_key: str, character_id: str = "") -> str:
        """Format recent diary entries for injection into conversation context.

        This allows the character to reference past diary entries naturally.
        """
        recent = self.store.get_recent_entries(session_key, character_id, count=3)
        if not recent:
            return ""

        lines = ["## 最近的日记"]
        for entry in recent:
            lines.append(f"\n### {entry.date} — {entry.title}")
            # Only include a brief excerpt
            content_preview = entry.content[:200]
            if len(entry.content) > 200:
                content_preview += "..."
            lines.append(content_preview)

        return "\n".join(lines)


# ============================================================================
# Helpers
# ============================================================================

def _mood_to_emoji(mood: str) -> str:
    """Convert a mood string to an emoji."""
    mood_emojis = {
        "开心": "😊", "快乐": "😊", "happy": "😊",
        "难过": "😢", "伤心": "😢", "sad": "😢",
        "平静": "😌", "neutral": "😌",
        "兴奋": "🤩", "excited": "🤩",
        "温馨": "🥰", "温暖": "🥰", "warm": "🥰",
        "焦虑": "😰", "anxious": "😰",
        "疲惫": "😴", "tired": "😴",
        "感恩": "🙏", "grateful": "🙏",
    }
    return mood_emojis.get(mood, "📝")
