"""SillyTavern storage — file-based JSON storage for character cards, world info, presets, and memories."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from nanobot.sillytavern.types import (
    CharacterIndex,
    WorldInfoIndex,
    PresetIndex,
    StoredCharacterCard,
    StoredWorldInfoBook,
    StoredPreset,
    CharacterCardData,
    WorldInfoEntry,
    WorldInfoBook,
    SillyTavernPreset,
    MemoryBook,
    MemoryBookSettings,
)


def _storage_root() -> Path:
    """Get the SillyTavern storage root directory."""
    return Path.home() / ".nanobot" / "sillytavern"


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: Any) -> None:
    _ensure(path.parent)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")


# ============================================================================
# Character Card Storage
# ============================================================================

def _char_dir() -> Path:
    return _ensure(_storage_root() / "characters")


def _char_index_path() -> Path:
    return _char_dir() / "characters.json"


def _load_char_index() -> CharacterIndex:
    raw = _read_json(_char_index_path())
    if raw and isinstance(raw, dict):
        return CharacterIndex(
            version=raw.get("version", 1),
            entries=raw.get("entries", []),
            active=raw.get("active", ""),
        )
    return CharacterIndex()


def _save_char_index(idx: CharacterIndex) -> None:
    _write_json(_char_index_path(), asdict(idx))


def import_character(card: StoredCharacterCard) -> StoredCharacterCard:
    """Import a character card to storage."""
    _write_json(_char_dir() / f"{card.id}.json", asdict(card))
    idx = _load_char_index()
    # Remove duplicate by name
    idx.entries = [e for e in idx.entries if e.get("name") != card.name]
    idx.entries.append({"id": card.id, "name": card.name, "imported_at": card.imported_at})
    _save_char_index(idx)
    return card


def list_characters() -> list[dict]:
    """List all imported characters."""
    return _load_char_index().entries


def get_character(char_id: str) -> StoredCharacterCard | None:
    """Load a stored character card by ID."""
    raw = _read_json(_char_dir() / f"{char_id}.json")
    if not raw:
        return None
    return _dict_to_stored_character(raw)


def get_character_by_name(name: str) -> StoredCharacterCard | None:
    """Find a character by name."""
    idx = _load_char_index()
    for entry in idx.entries:
        if entry.get("name", "").lower() == name.lower():
            return get_character(entry["id"])
    return None


def activate_character(char_id: str) -> bool:
    """Set a character as the active one."""
    idx = _load_char_index()
    if not any(e.get("id") == char_id for e in idx.entries):
        return False
    idx.active = char_id
    _save_char_index(idx)
    return True


def deactivate_character() -> None:
    """Clear the active character."""
    idx = _load_char_index()
    idx.active = ""
    _save_char_index(idx)


def get_active_character() -> StoredCharacterCard | None:
    """Get the currently active character card."""
    idx = _load_char_index()
    if not idx.active:
        return None
    return get_character(idx.active)


def delete_character(char_id: str) -> bool:
    """Delete a character card."""
    path = _char_dir() / f"{char_id}.json"
    if not path.exists():
        return False
    path.unlink()
    idx = _load_char_index()
    idx.entries = [e for e in idx.entries if e.get("id") != char_id]
    if idx.active == char_id:
        idx.active = ""
    _save_char_index(idx)
    return True


# ============================================================================
# World Info Storage
# ============================================================================

def _wi_dir() -> Path:
    return _ensure(_storage_root() / "worldinfo")


def _wi_index_path() -> Path:
    return _wi_dir() / "worldinfo.json"


def _load_wi_index() -> WorldInfoIndex:
    raw = _read_json(_wi_index_path())
    if raw and isinstance(raw, dict):
        return WorldInfoIndex(
            version=raw.get("version", 1),
            entries=raw.get("entries", []),
        )
    return WorldInfoIndex()


def _save_wi_index(idx: WorldInfoIndex) -> None:
    _write_json(_wi_index_path(), asdict(idx))


def import_world_info(book: StoredWorldInfoBook) -> StoredWorldInfoBook:
    """Import a world info book to storage."""
    _write_json(_wi_dir() / f"{book.id}.json", _stored_wi_to_dict(book))
    idx = _load_wi_index()
    idx.entries = [e for e in idx.entries if e.get("name") != book.name]
    entry_count = len(book.entries)
    idx.entries.append({
        "id": book.id, "name": book.name,
        "imported_at": book.imported_at, "enabled": book.enabled,
        "entry_count": entry_count,
    })
    _save_wi_index(idx)
    return book


def list_world_info() -> list[dict]:
    """List all imported world info books."""
    return _load_wi_index().entries


def get_world_info(book_id: str) -> StoredWorldInfoBook | None:
    """Load a stored world info book by ID."""
    raw = _read_json(_wi_dir() / f"{book_id}.json")
    if not raw:
        return None
    return _dict_to_stored_wi(raw)


def get_enabled_world_info() -> list[StoredWorldInfoBook]:
    """Get all enabled world info books."""
    idx = _load_wi_index()
    books = []
    for entry in idx.entries:
        if entry.get("enabled", True):
            book = get_world_info(entry["id"])
            if book:
                books.append(book)
    return books


def set_world_info_enabled(book_id: str, enabled: bool) -> bool:
    """Enable or disable a world info book."""
    idx = _load_wi_index()
    for entry in idx.entries:
        if entry.get("id") == book_id:
            entry["enabled"] = enabled
            _save_wi_index(idx)
            return True
    return False


def delete_world_info(book_id: str) -> bool:
    """Delete a world info book."""
    path = _wi_dir() / f"{book_id}.json"
    if not path.exists():
        return False
    path.unlink()
    idx = _load_wi_index()
    idx.entries = [e for e in idx.entries if e.get("id") != book_id]
    _save_wi_index(idx)
    return True


# ============================================================================
# Preset Storage
# ============================================================================

def _preset_dir() -> Path:
    return _ensure(_storage_root() / "presets")


def _preset_index_path() -> Path:
    return _preset_dir() / "presets.json"


def _load_preset_index() -> PresetIndex:
    raw = _read_json(_preset_index_path())
    if raw and isinstance(raw, dict):
        return PresetIndex(
            version=raw.get("version", 1),
            entries=raw.get("entries", []),
            active=raw.get("active", ""),
        )
    return PresetIndex()


def _save_preset_index(idx: PresetIndex) -> None:
    _write_json(_preset_index_path(), asdict(idx))


def import_preset(preset: StoredPreset) -> StoredPreset:
    """Import a preset to storage."""
    _write_json(_preset_dir() / f"{preset.id}.json", asdict(preset))
    idx = _load_preset_index()
    idx.entries = [e for e in idx.entries if e.get("name") != preset.name]
    idx.entries.append({
        "id": preset.id, "name": preset.name,
        "imported_at": preset.imported_at,
    })
    _save_preset_index(idx)
    return preset


def list_presets() -> list[dict]:
    """List all imported presets."""
    return _load_preset_index().entries


def get_preset(preset_id: str) -> StoredPreset | None:
    """Load a stored preset by ID."""
    raw = _read_json(_preset_dir() / f"{preset_id}.json")
    if not raw:
        return None
    return _dict_to_stored_preset(raw)


def activate_preset(preset_id: str) -> bool:
    """Set a preset as the active one."""
    idx = _load_preset_index()
    if not any(e.get("id") == preset_id for e in idx.entries):
        return False
    idx.active = preset_id
    _save_preset_index(idx)
    return True


def deactivate_preset() -> None:
    """Clear the active preset."""
    idx = _load_preset_index()
    idx.active = ""
    _save_preset_index(idx)


def get_active_preset() -> StoredPreset | None:
    """Get the currently active preset."""
    idx = _load_preset_index()
    if not idx.active:
        return None
    return get_preset(idx.active)


def delete_preset(preset_id: str) -> bool:
    """Delete a preset."""
    path = _preset_dir() / f"{preset_id}.json"
    if not path.exists():
        return False
    path.unlink()
    idx = _load_preset_index()
    idx.entries = [e for e in idx.entries if e.get("id") != preset_id]
    if idx.active == preset_id:
        idx.active = ""
    _save_preset_index(idx)
    return True


# ============================================================================
# Status
# ============================================================================

def get_status() -> dict:
    """Get overall SillyTavern status."""
    char_idx = _load_char_index()
    wi_idx = _load_wi_index()
    preset_idx = _load_preset_index()

    active_char = None
    if char_idx.active:
        c = get_character(char_idx.active)
        if c:
            active_char = c.name

    active_preset_name = None
    if preset_idx.active:
        p = get_preset(preset_idx.active)
        if p:
            active_preset_name = p.name

    enabled_wi = sum(1 for e in wi_idx.entries if e.get("enabled", True))

    return {
        "characters": len(char_idx.entries),
        "active_character": active_char,
        "world_info_books": len(wi_idx.entries),
        "world_info_enabled": enabled_wi,
        "presets": len(preset_idx.entries),
        "active_preset": active_preset_name,
    }


# ============================================================================
# Serialization Helpers
# ============================================================================

def _dict_to_stored_character(d: dict) -> StoredCharacterCard:
    data_dict = d.get("data", {})
    character_book = None
    if "character_book" in data_dict and data_dict["character_book"] is not None:
        from nanobot.sillytavern.types import CharacterBookEntry
        character_book = [
            CharacterBookEntry(**e) for e in data_dict["character_book"]
        ] if isinstance(data_dict["character_book"], list) else None

    card_data = CharacterCardData(
        name=data_dict.get("name", ""),
        description=data_dict.get("description", ""),
        personality=data_dict.get("personality", ""),
        scenario=data_dict.get("scenario", ""),
        first_mes=data_dict.get("first_mes", ""),
        mes_example=data_dict.get("mes_example", ""),
        creator_notes=data_dict.get("creator_notes", ""),
        system_prompt=data_dict.get("system_prompt", ""),
        post_history_instructions=data_dict.get("post_history_instructions", ""),
        alternate_greetings=data_dict.get("alternate_greetings", []),
        tags=data_dict.get("tags", []),
        creator=data_dict.get("creator", ""),
        character_version=data_dict.get("character_version", ""),
        character_book=character_book,
        extensions=data_dict.get("extensions", {}),
    )
    return StoredCharacterCard(
        id=d.get("id", ""),
        name=d.get("name", ""),
        spec=d.get("spec", "chara_card_v2"),
        imported_at=d.get("imported_at", ""),
        source_path=d.get("source_path", ""),
        data=card_data,
    )


def _stored_wi_to_dict(book: StoredWorldInfoBook) -> dict:
    entries_dict = {}
    for key, entry in book.entries.items():
        entries_dict[key] = asdict(entry)
    return {
        "id": book.id,
        "name": book.name,
        "imported_at": book.imported_at,
        "source_path": book.source_path,
        "enabled": book.enabled,
        "entries": entries_dict,
    }


def _dict_to_stored_wi(d: dict) -> StoredWorldInfoBook:
    entries = {}
    for key, entry_dict in d.get("entries", {}).items():
        if isinstance(entry_dict, dict):
            entries[key] = WorldInfoEntry(**{
                k: v for k, v in entry_dict.items()
                if k in WorldInfoEntry.__dataclass_fields__
            })
    return StoredWorldInfoBook(
        id=d.get("id", ""),
        name=d.get("name", ""),
        imported_at=d.get("imported_at", ""),
        source_path=d.get("source_path", ""),
        enabled=d.get("enabled", True),
        entries=entries,
    )


def _dict_to_stored_preset(d: dict) -> StoredPreset:
    from nanobot.sillytavern.types import PresetPromptEntry
    data_dict = d.get("data", {})
    prompts = []
    for p in data_dict.get("prompts", []):
        if isinstance(p, dict):
            prompts.append(PresetPromptEntry(**{
                k: v for k, v in p.items()
                if k in PresetPromptEntry.__dataclass_fields__
            }))
    preset = SillyTavernPreset(
        temperature=data_dict.get("temperature", 1.0),
        frequency_penalty=data_dict.get("frequency_penalty", 0.0),
        presence_penalty=data_dict.get("presence_penalty", 0.0),
        top_p=data_dict.get("top_p", 1.0),
        top_k=data_dict.get("top_k", 0),
        prompts=prompts,
    )
    return StoredPreset(
        id=d.get("id", ""),
        name=d.get("name", ""),
        imported_at=d.get("imported_at", ""),
        source_path=d.get("source_path", ""),
        data=preset,
        entry_overrides=d.get("entry_overrides", {}),
    )
