"""Character Card parser — supports SillyTavern V2/V3/legacy JSON format."""

from __future__ import annotations

import json
import time as _time
from typing import Any

from nanobot.sillytavern.types import CharacterCardData, CharacterBookEntry, StoredCharacterCard


def parse_character_card(json_string: str) -> tuple[CharacterCardData | None, str | None, str]:
    """Parse a character card JSON string.

    Returns:
        Tuple of (data, error, spec) where data is CharacterCardData or None on error.
    """
    try:
        obj = json.loads(json_string)
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}", ""

    return parse_character_card_object(obj)


def parse_character_card_object(obj: Any) -> tuple[CharacterCardData | None, str | None, str]:
    """Parse a character card from a dict/object.

    Returns:
        Tuple of (data, error, spec).
    """
    if not isinstance(obj, dict):
        return None, "Input is not an object", ""

    spec = obj.get("spec", "")
    data_obj = obj.get("data")

    # V2/V3 format: has spec and data fields
    if spec in ("chara_card_v2", "chara_card_v3") and isinstance(data_obj, dict):
        data = _validate_character_data(data_obj)
        if data is None:
            return None, "Character name is required", spec
        return data, None, spec

    # Legacy format with data field but no spec
    if isinstance(data_obj, dict):
        data = _validate_character_data(data_obj)
        if data is not None:
            return data, None, "chara_card_v2"

    # Flat structure (V1-like) — the object itself is the data
    if isinstance(obj.get("name"), str) and obj["name"].strip():
        data = _validate_character_data(obj)
        if data is not None:
            return data, None, "chara_card_v2"

    return None, "Unknown character card format. Expected chara_card_v2 or chara_card_v3.", ""


def _validate_character_data(d: dict) -> CharacterCardData | None:
    """Validate and build CharacterCardData from a dict."""
    name = d.get("name", "")
    if not isinstance(name, str) or not name.strip():
        return None

    # Parse character book entries if present
    character_book = None
    book_data = d.get("character_book")
    if isinstance(book_data, dict):
        entries_data = book_data.get("entries", [])
        if isinstance(entries_data, list):
            character_book = [
                CharacterBookEntry(
                    keys=e.get("keys", []) if isinstance(e.get("keys"), list) else [],
                    content=str(e.get("content", "")),
                    enabled=e.get("enabled", True),
                    insertion_order=e.get("insertion_order", 0),
                    name=str(e.get("name", "")),
                )
                for e in entries_data
                if isinstance(e, dict)
            ]

    return CharacterCardData(
        name=name.strip(),
        description=str(d.get("description", "")),
        personality=str(d.get("personality", "")),
        scenario=str(d.get("scenario", "")),
        first_mes=str(d.get("first_mes", "")),
        mes_example=str(d.get("mes_example", "")),
        creator_notes=str(d.get("creator_notes", "")),
        system_prompt=str(d.get("system_prompt", "")),
        post_history_instructions=str(d.get("post_history_instructions", "")),
        alternate_greetings=[g for g in d.get("alternate_greetings", []) if isinstance(g, str)],
        tags=[t for t in d.get("tags", []) if isinstance(t, str)],
        creator=str(d.get("creator", "")),
        character_version=str(d.get("character_version", "")),
        character_book=character_book,
        extensions=d.get("extensions", {}) if isinstance(d.get("extensions"), dict) else {},
    )


def build_character_prompt(
    data: CharacterCardData,
    *,
    include_system_prompt: bool = True,
    include_description: bool = True,
    include_personality: bool = True,
    include_scenario: bool = True,
    include_examples: bool = True,
    include_post_history: bool = False,
) -> str:
    """Build a markdown prompt from character card data."""
    sections: list[str] = [f"# Character: {data.name}"]

    if include_system_prompt and data.system_prompt.strip():
        sections.append("\n## System Instructions")
        sections.append(data.system_prompt.strip())

    if include_description and data.description.strip():
        sections.append("\n## Description")
        sections.append(data.description.strip())

    if include_personality and data.personality.strip():
        sections.append("\n## Personality")
        sections.append(data.personality.strip())

    if include_scenario and data.scenario.strip():
        sections.append("\n## Scenario")
        sections.append(data.scenario.strip())

    if include_examples and data.mes_example.strip():
        sections.append("\n## Example Dialogue")
        sections.append(data.mes_example.strip())

    if include_post_history and data.post_history_instructions.strip():
        sections.append("\n## Additional Instructions")
        sections.append(data.post_history_instructions.strip())

    return "\n".join(sections)


def generate_character_id(name: str) -> str:
    """Generate a unique ID for a character card."""
    import re
    sanitized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", name.lower()).strip("-")
    timestamp = _int_to_base36(int(_time.time() * 1000))
    return f"{sanitized}-{timestamp}"


def to_stored_character_card(
    data: CharacterCardData, spec: str, source_path: str = "",
) -> StoredCharacterCard:
    """Convert parsed data to stored format."""
    from datetime import datetime
    return StoredCharacterCard(
        id=generate_character_id(data.name),
        name=data.name,
        spec=spec,
        imported_at=datetime.now().isoformat(),
        source_path=source_path,
        data=data,
    )


def _int_to_base36(n: int) -> str:
    """Convert integer to base36 string."""
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0:
        return "0"
    result = []
    while n:
        result.append(chars[n % 36])
        n //= 36
    return "".join(reversed(result))
