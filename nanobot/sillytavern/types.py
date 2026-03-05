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


# ============================================================================
# Emotion Types (情感陪伴)
# ============================================================================

@dataclass
class EmotionEntry:
    """A single emotion observation extracted from a conversation turn."""
    id: str = ""
    timestamp: str = ""                # ISO timestamp
    session_key: str = ""
    emotion: str = "neutral"           # happy/sad/anxious/angry/neutral/excited/lonely/tired
    intensity: int = 50                # 0-100
    trigger: str = ""                  # Brief reason for the emotion
    context_snippet: str = ""          # The user message that triggered it
    character_id: str = ""


@dataclass
class EmotionProfile:
    """Aggregated emotion state for a character-user pair."""
    id: str = ""
    character_id: str = ""
    session_key: str = ""
    entries: list[EmotionEntry] = field(default_factory=list)
    current_emotion: str = "neutral"
    current_intensity: int = 50
    trend: str = "stable"              # rising/falling/stable
    updated_at: str = ""


# ============================================================================
# Scene Awareness Types (场景感知)
# ============================================================================

@dataclass
class SceneContext:
    """Current scene/context information for the conversation."""
    time_period: str = ""              # 凌晨/早晨/上午/中午/下午/傍晚/晚上/深夜
    day_type: str = ""                 # 工作日/周末
    day_of_week: str = ""              # 星期一...星期日
    holiday: str = ""                  # 节日名称 or ""
    weather: str = ""                  # 天气描述 or ""
    user_emotion: str = ""             # 当前情感状态
    user_emotion_intensity: int = 50
    today_chat_count: int = 0          # 今天聊天次数
    last_chat_time: str = ""           # 上次聊天时间
    days_since_first_chat: int = 0     # 认识天数
    anniversary_note: str = ""         # 纪念日提示 or ""


# ============================================================================
# Diary Types (共享日记)
# ============================================================================

@dataclass
class DiaryEntry:
    """A single diary entry for a day."""
    id: str = ""
    date: str = ""                     # YYYY-MM-DD
    timestamp: str = ""                # ISO timestamp
    title: str = ""                    # Diary title
    content: str = ""                  # Diary content (markdown)
    mood: str = ""                     # Primary mood of the day
    highlights: list[str] = field(default_factory=list)  # Key moments
    character_id: str = ""
    session_key: str = ""
    auto_generated: bool = True        # Whether auto-generated by cron
    user_edited: bool = False          # Whether user has edited it


@dataclass
class DiarySettings:
    """Settings for diary generation."""
    auto_generate: bool = True
    generate_time: str = "23:00"       # Daily generation time (HH:MM)
    min_messages_for_entry: int = 5    # Minimum messages to trigger generation
    include_emotion_summary: bool = True


@dataclass
class DiaryBook:
    """Collection of diary entries for a character-user pair."""
    id: str = ""
    character_id: str = ""
    session_key: str = ""
    entries: list[DiaryEntry] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    settings: DiarySettings = field(default_factory=DiarySettings)
