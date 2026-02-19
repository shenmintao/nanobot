"""SillyTavern type definitions — dataclasses for character cards, world info, presets, memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ============================================================================
# Character Card Types
# ============================================================================

@dataclass
class CharacterBookEntry:
    keys: list[str] = field(default_factory=list)
    content: str = ""
    enabled: bool = True
    insertion_order: int = 0
    name: str = ""


@dataclass
class CharacterCardData:
    name: str = ""
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_mes: str = ""
    mes_example: str = ""
    creator_notes: str = ""
    system_prompt: str = ""
    post_history_instructions: str = ""
    alternate_greetings: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    creator: str = ""
    character_version: str = ""
    character_book: list[CharacterBookEntry] | None = None
    extensions: dict[str, Any] = field(default_factory=dict)


@dataclass
class StoredCharacterCard:
    id: str = ""
    name: str = ""
    spec: str = "chara_card_v2"
    imported_at: str = ""
    source_path: str = ""
    data: CharacterCardData = field(default_factory=CharacterCardData)


# ============================================================================
# World Info Types
# ============================================================================

@dataclass
class WorldInfoEntry:
    uid: int = 0
    key: list[str] = field(default_factory=list)
    keysecondary: list[str] = field(default_factory=list)
    comment: str = ""
    content: str = ""
    # Activation control
    constant: bool = False
    selective: bool = False
    selective_logic: int = 0  # 0=AND_ANY, 1=NOT_ALL, 2=NOT_ANY, 3=AND_ALL
    disable: bool = False
    # Probability
    probability: int = 100
    use_probability: bool = False
    # Position and order
    order: int = 100
    position: int = 0
    depth: int = 4
    # Scan settings
    case_sensitive: bool = False
    match_whole_words: bool = False


@dataclass
class WorldInfoBook:
    entries: dict[str, WorldInfoEntry] = field(default_factory=dict)


@dataclass
class StoredWorldInfoBook:
    id: str = ""
    name: str = ""
    imported_at: str = ""
    source_path: str = ""
    enabled: bool = True
    entries: dict[str, WorldInfoEntry] = field(default_factory=dict)


# ============================================================================
# Preset Types
# ============================================================================

@dataclass
class PresetPromptEntry:
    identifier: str = ""
    name: str = ""
    enabled: bool = True
    role: str = "system"  # system | user | assistant
    content: str = ""
    injection_position: int = 0
    injection_depth: int = 4
    injection_order: int = 100
    system_prompt: bool = False
    marker: bool = False


@dataclass
class SillyTavernPreset:
    temperature: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    top_p: float = 1.0
    top_k: int = 0
    prompts: list[PresetPromptEntry] = field(default_factory=list)


@dataclass
class StoredPreset:
    id: str = ""
    name: str = ""
    imported_at: str = ""
    source_path: str = ""
    data: SillyTavernPreset = field(default_factory=SillyTavernPreset)
    entry_overrides: dict[str, dict] = field(default_factory=dict)


# ============================================================================
# Memory Types
# ============================================================================

@dataclass
class MemoryEntry:
    id: str = ""
    content: str = ""
    created_at: str = ""
    last_accessed_at: str = ""
    access_count: int = 0
    entry_type: str = "manual"  # manual | auto
    keywords: list[str] = field(default_factory=list)
    importance: int = 50  # 0-100
    category: str = ""
    source: str = ""
    enabled: bool = True


@dataclass
class MemoryBookSettings:
    max_memories_per_request: int = 10
    max_memory_tokens: int = 1000
    use_keyword_retrieval: bool = True
    min_importance: int = 50
    sort_by: str = "importance"  # importance | recency | access_count


@dataclass
class MemoryBook:
    id: str = ""
    name: str = ""
    character_id: str = ""
    session_key: str = ""
    created_at: str = ""
    updated_at: str = ""
    entries: list[MemoryEntry] = field(default_factory=list)
    settings: MemoryBookSettings = field(default_factory=MemoryBookSettings)


# ============================================================================
# Index Types
# ============================================================================

@dataclass
class CharacterIndex:
    version: int = 1
    entries: list[dict] = field(default_factory=list)
    active: str = ""


@dataclass
class WorldInfoIndex:
    version: int = 1
    entries: list[dict] = field(default_factory=list)


@dataclass
class PresetIndex:
    version: int = 1
    entries: list[dict] = field(default_factory=list)
    active: str = ""


# ============================================================================
# Config Types
# ============================================================================

@dataclass
class WorldInfoConfig:
    enabled: bool = True
    scan_depth: int = 5
    max_entries: int = 10
    max_tokens: int = 2048
    recursive_scan: bool = False


@dataclass
class MacrosConfig:
    user: str = "User"
    char: str = "Assistant"
    date_format: str = "YYYY-MM-DD"
    time_format: str = "HH:mm"
    custom_variables: dict[str, str] = field(default_factory=dict)
