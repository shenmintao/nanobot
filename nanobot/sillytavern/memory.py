"""Enhanced memory — structured entries with importance, keywords, and keyword-based retrieval."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.sillytavern.types import MemoryBook, MemoryBookSettings, MemoryEntry


# ============================================================================
# Memory Store
# ============================================================================

class STMemoryStore:
    """Structured memory store for SillyTavern-style memory books.

    Stores memory books as JSON files under ~/.nanobot/sillytavern/memories/.
    Each character or session can have its own memory book.
    """

    def __init__(self) -> None:
        self._storage_dir = Path.home() / ".nanobot" / "sillytavern" / "memories"
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _book_path(self, book_id: str) -> Path:
        return self._storage_dir / f"{book_id}.json"

    # -- CRUD --

    def load_book(self, book_id: str) -> MemoryBook | None:
        path = self._book_path(book_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text("utf-8"))
            return _dict_to_memory_book(raw)
        except (json.JSONDecodeError, KeyError):
            return None

    def save_book(self, book: MemoryBook) -> None:
        path = self._book_path(book.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_memory_book_to_dict(book), indent=2, ensure_ascii=False), "utf-8")

    def list_books(self) -> list[dict]:
        results: list[dict] = []
        for p in self._storage_dir.glob("*.json"):
            try:
                raw = json.loads(p.read_text("utf-8"))
                results.append({
                    "id": raw.get("id", p.stem),
                    "name": raw.get("name", ""),
                    "character_id": raw.get("character_id", ""),
                    "entries": len(raw.get("entries", [])),
                })
            except (json.JSONDecodeError, KeyError):
                pass
        return results

    def get_or_create_book(
        self,
        character_id: str = "",
        character_name: str = "",
        session_key: str = "",
    ) -> MemoryBook:
        """Get existing book by character_id or create a new one."""
        # Try finding by character_id
        if character_id:
            for p in self._storage_dir.glob("*.json"):
                try:
                    raw = json.loads(p.read_text("utf-8"))
                    if raw.get("character_id") == character_id:
                        return _dict_to_memory_book(raw)
                except (json.JSONDecodeError, KeyError):
                    pass

        # Create new
        now = datetime.now().isoformat()
        book_id = _generate_id(character_name or session_key or "default")
        book = MemoryBook(
            id=book_id,
            name=character_name or session_key or "Default",
            character_id=character_id,
            session_key=session_key,
            created_at=now,
            updated_at=now,
        )
        self.save_book(book)
        return book

    def delete_book(self, book_id: str) -> bool:
        path = self._book_path(book_id)
        if path.exists():
            path.unlink()
            return True
        return False

    # -- Memory Entry Operations --

    def add_memory(
        self,
        book_id: str,
        content: str,
        *,
        entry_type: str = "manual",
        keywords: list[str] | None = None,
        importance: int = 50,
        category: str = "",
        source: str = "",
    ) -> MemoryEntry | None:
        book = self.load_book(book_id)
        if not book:
            return None

        now = datetime.now().isoformat()
        entry = MemoryEntry(
            id=_generate_mem_id(),
            content=content,
            created_at=now,
            last_accessed_at=now,
            access_count=0,
            entry_type=entry_type,
            keywords=keywords or [],
            importance=importance,
            category=category,
            source=source,
            enabled=True,
        )
        book.entries.append(entry)
        book.updated_at = now
        self.save_book(book)
        return entry

    def delete_memory(self, book_id: str, memory_id: str) -> bool:
        book = self.load_book(book_id)
        if not book:
            return False
        before = len(book.entries)
        book.entries = [e for e in book.entries if e.id != memory_id]
        if len(book.entries) == before:
            return False
        self.save_book(book)
        return True

    # -- Retrieval --

    def retrieve_memories(
        self,
        book_id: str,
        context: str = "",
        *,
        max_memories: int | None = None,
        min_importance: int | None = None,
        sort_by: str | None = None,
    ) -> list[MemoryEntry]:
        """Retrieve relevant memories with keyword matching and sorting."""
        book = self.load_book(book_id)
        if not book:
            return []

        settings = book.settings
        limit = max_memories or settings.max_memories_per_request
        min_imp = min_importance if min_importance is not None else settings.min_importance
        order = sort_by or settings.sort_by

        # Filter enabled + minimum importance
        filtered = [
            e for e in book.entries
            if e.enabled and e.importance >= min_imp
        ]

        # Keyword-based filtering if context and keyword retrieval enabled
        if context.strip() and settings.use_keyword_retrieval:
            keywords = _extract_keywords(context)
            if keywords:
                scored = []
                for entry in filtered:
                    score = _keyword_score(entry, keywords)
                    if score > 0:
                        scored.append((entry, score))
                # If keyword matching found results, use those; otherwise fall through to all
                if scored:
                    scored.sort(key=lambda x: x[1], reverse=True)
                    filtered = [e for e, _ in scored]

        # Sort
        if order == "importance":
            filtered.sort(key=lambda e: e.importance, reverse=True)
        elif order == "recency":
            filtered.sort(key=lambda e: e.last_accessed_at, reverse=True)
        elif order == "access_count":
            filtered.sort(key=lambda e: e.access_count, reverse=True)

        # Truncate
        result = filtered[:limit]

        # Update access counts
        now = datetime.now().isoformat()
        for entry in result:
            entry.last_accessed_at = now
            entry.access_count += 1
        if result:
            book.updated_at = now
            self.save_book(book)

        return result


def build_memory_prompt(memories: list[MemoryEntry]) -> str:
    """Build a memory prompt section for injection into system prompt."""
    if not memories:
        return ""

    lines = ["## Long-term Memories", ""]
    for memory in memories:
        prefix = f"[{memory.category}] " if memory.category else ""
        lines.append(f"- {prefix}{memory.content}")
    return "\n".join(lines)


# ============================================================================
# Keyword Matching
# ============================================================================

_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "can", "and", "or", "but", "if",
    "then", "else", "when", "where", "why", "how", "what", "which", "who",
    "whom", "this", "that", "these", "those", "for", "with", "about",
    "into", "through", "during", "before", "after", "above", "below",
    "from", "up", "down", "in", "out", "on", "off", "over", "under",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
})


def _extract_keywords(text: str) -> list[str]:
    """Extract keywords from text, filtering stop words."""
    if not text.strip():
        return []
    import re
    words = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text.lower()).split()
    return list(dict.fromkeys(
        w for w in words if len(w) > 2 and w not in _STOP_WORDS
    ))


def _keyword_score(entry: MemoryEntry, keywords: list[str]) -> float:
    """Score a memory entry against search keywords."""
    score = 0.0

    # Check entry keywords
    if entry.keywords:
        for ek in entry.keywords:
            for kw in keywords:
                if kw.lower() in ek.lower():
                    score += 2.0

    # Check content
    content_lower = entry.content.lower()
    for kw in keywords:
        if kw in content_lower:
            score += 1.0

    return score


# ============================================================================
# Helpers
# ============================================================================

def _generate_id(name: str) -> str:
    import re
    sanitized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", name.lower()).strip("-")[:20]
    ts = hex(int(time.time() * 1000))[2:]
    return f"mb-{sanitized}-{ts}"


def _generate_mem_id() -> str:
    ts = hex(int(time.time() * 1000))[2:]
    import random
    r = hex(random.randint(0, 0xFFFFFF))[2:]
    return f"mem-{ts}-{r}"


def _memory_book_to_dict(book: MemoryBook) -> dict:
    from dataclasses import asdict
    return asdict(book)


def _dict_to_memory_book(d: dict) -> MemoryBook:
    entries = []
    for e in d.get("entries", []):
        if isinstance(e, dict):
            entries.append(MemoryEntry(**{
                k: v for k, v in e.items()
                if k in MemoryEntry.__dataclass_fields__
            }))

    settings_raw = d.get("settings", {})
    settings = MemoryBookSettings(**{
        k: v for k, v in settings_raw.items()
        if k in MemoryBookSettings.__dataclass_fields__
    }) if isinstance(settings_raw, dict) else MemoryBookSettings()

    return MemoryBook(
        id=d.get("id", ""),
        name=d.get("name", ""),
        character_id=d.get("character_id", ""),
        session_key=d.get("session_key", ""),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
        entries=entries,
        settings=settings,
    )
