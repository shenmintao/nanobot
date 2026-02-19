"""World Info parser — keyword-based activation with constant/selective/probability logic."""

from __future__ import annotations

import json
import random
import re
from typing import Any

from nanobot.sillytavern.types import WorldInfoEntry, WorldInfoBook, WorldInfoConfig


def parse_world_info(json_string: str) -> tuple[WorldInfoBook | None, str | None]:
    """Parse a world info JSON string.

    Returns:
        Tuple of (book, error).
    """
    try:
        obj = json.loads(json_string)
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"

    return parse_world_info_object(obj)


def parse_world_info_object(obj: Any) -> tuple[WorldInfoBook | None, str | None]:
    """Parse a world info book from a dict."""
    if not isinstance(obj, dict):
        return None, "Input is not an object"

    entries_raw = obj.get("entries")

    # SillyTavern format: { entries: { "0": {...}, "1": {...} } }
    if isinstance(entries_raw, dict):
        entries = {}
        for key, entry_data in entries_raw.items():
            if not isinstance(entry_data, dict):
                continue
            entry = _parse_entry(entry_data)
            entries[key] = entry
        return WorldInfoBook(entries=entries), None

    # Array format: { entries: [{...}, {...}] }
    if isinstance(entries_raw, list):
        entries = {}
        for i, entry_data in enumerate(entries_raw):
            if not isinstance(entry_data, dict):
                continue
            entry = _parse_entry(entry_data)
            entries[str(i)] = entry
        return WorldInfoBook(entries=entries), None

    return None, "World info has no entries field"


def _parse_entry(d: dict) -> WorldInfoEntry:
    """Parse a single world info entry from a dict."""
    return WorldInfoEntry(
        uid=d.get("uid", 0),
        key=_coerce_list(d.get("key", [])),
        keysecondary=_coerce_list(d.get("keysecondary", [])),
        comment=str(d.get("comment", "")),
        content=str(d.get("content", "")),
        constant=bool(d.get("constant", False)),
        selective=bool(d.get("selective", False)),
        selective_logic=d.get("selectiveLogic", d.get("selective_logic", 0)),
        disable=bool(d.get("disable", False)),
        probability=d.get("probability", 100),
        use_probability=bool(d.get("useProbability", d.get("use_probability", False))),
        order=d.get("order", 100),
        position=d.get("position", 0),
        depth=d.get("depth", 4),
        case_sensitive=bool(d.get("caseSensitive", d.get("case_sensitive", False))),
        match_whole_words=bool(d.get("matchWholeWords", d.get("match_whole_words", False))),
    )


def _coerce_list(val: Any) -> list[str]:
    """Ensure a value is a list of strings (handles comma-separated string)."""
    if isinstance(val, list):
        return [str(v).strip() for v in val if str(v).strip()]
    if isinstance(val, str) and val.strip():
        return [s.strip() for s in val.split(",") if s.strip()]
    return []


# ============================================================================
# Activation Logic
# ============================================================================

def get_activated_entries(
    book: WorldInfoBook,
    context: str,
    config: WorldInfoConfig | None = None,
) -> list[WorldInfoEntry]:
    """Get activated entries based on keywords and context.

    Args:
        book: The world info book.
        context: Conversation context to match against.
        config: Optional config (defaults used if None).

    Returns:
        List of activated entries, sorted by order.
    """
    cfg = config or WorldInfoConfig()
    activated: list[WorldInfoEntry] = []

    for entry in book.entries.values():
        if entry.disable:
            continue
        if not entry.content.strip():
            continue

        if _check_entry_activation(entry, context, cfg):
            activated.append(entry)

    # Sort by order (lower = earlier)
    activated.sort(key=lambda e: e.order)

    # Apply max entries limit
    if cfg.max_entries > 0 and len(activated) > cfg.max_entries:
        activated = activated[: cfg.max_entries]

    return activated


def _check_entry_activation(
    entry: WorldInfoEntry,
    context: str,
    config: WorldInfoConfig,
) -> bool:
    """Check if a single entry should be activated."""
    # Constant entries are always active
    if entry.constant:
        return True

    # No keys defined → skip
    if not entry.key:
        return False

    # Check probability
    if entry.use_probability and entry.probability < 100:
        if random.randint(1, 100) > entry.probability:
            return False

    # Primary key matching
    primary_match = _any_key_matches(entry.key, context, entry.case_sensitive, entry.match_whole_words)

    if not primary_match:
        return False

    # Selective logic with secondary keys
    if entry.selective and entry.keysecondary:
        return _check_selective(entry, context)

    return True


def _check_selective(entry: WorldInfoEntry, context: str) -> bool:
    """Check selective logic with secondary keys."""
    secondary_matches = [
        _key_matches(k, context, entry.case_sensitive, entry.match_whole_words)
        for k in entry.keysecondary
    ]

    logic = entry.selective_logic
    if logic == 0:  # AND_ANY — at least one secondary key matches
        return any(secondary_matches)
    elif logic == 1:  # NOT_ALL — not all secondary keys match
        return not all(secondary_matches)
    elif logic == 2:  # NOT_ANY — no secondary key matches
        return not any(secondary_matches)
    elif logic == 3:  # AND_ALL — all secondary keys match
        return all(secondary_matches)
    return True


def _any_key_matches(keys: list[str], context: str, case_sensitive: bool, whole_words: bool) -> bool:
    """Check if any key matches in the context."""
    return any(_key_matches(k, context, case_sensitive, whole_words) for k in keys)


def _key_matches(key: str, context: str, case_sensitive: bool, whole_words: bool) -> bool:
    """Check if a single key matches in the context."""
    if not key.strip():
        return False

    if whole_words:
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = r"\b" + re.escape(key) + r"\b"
        return bool(re.search(pattern, context, flags))
    else:
        if case_sensitive:
            return key in context
        return key.lower() in context.lower()


def build_world_info_prompt(entries: list[WorldInfoEntry]) -> str:
    """Build a prompt string from activated world info entries."""
    if not entries:
        return ""

    lines = ["## World Information", ""]
    for entry in entries:
        if entry.comment:
            lines.append(f"### {entry.comment}")
        lines.append(entry.content.strip())
        lines.append("")

    return "\n".join(lines).strip()


def summarize_world_info(book: WorldInfoBook) -> str:
    """Build a human-readable summary of a world info book."""
    total = len(book.entries)
    enabled = sum(1 for e in book.entries.values() if not e.disable)
    constant = sum(1 for e in book.entries.values() if e.constant and not e.disable)
    return f"{total} entries ({enabled} enabled, {constant} always-on)"
