"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""
    
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"
    
    def __init__(self, workspace: Path, sillytavern_config: object | None = None):
        self.workspace = workspace
        from nanobot.config.schema import SillyTavernConfig
        self.sillytavern_config = sillytavern_config or SillyTavernConfig()
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
    
    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """Build the system prompt from identity, bootstrap files, memory, and skills."""
        parts = [self._get_identity()]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)
        # SillyTavern content injection
        st_content = self._build_sillytavern_context()
        if st_content:
            parts.append(st_content)

        # Memory context
        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")

        return "\n\n---\n\n".join(parts)
    
    def _get_identity(self) -> str:
        """Get the core identity section."""
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"
        
        return f"""# nanobot 🐈

You are nanobot, a helpful AI assistant.

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Long-term memory: {workspace_path}/memory/MEMORY.md (write important facts here)
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable). Each entry starts with [YYYY-MM-DD HH:MM].
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

## nanobot Guidelines
- State intent before tool calls, but NEVER predict or claim results before receiving them.
- Before modifying a file, read it first. Do not assume files or directories exist.
- After writing or editing a file, re-read it if accuracy matters.
- If a tool call fails, analyze the error before retrying with a different approach.
- Ask for clarification when the request is ambiguous.

Reply directly with text for conversations. Only use the 'message' tool to send to a specific chat channel."""

    @staticmethod
    def _build_runtime_context(channel: str | None, chat_id: str | None) -> str:
        """Build untrusted runtime metadata block for injection before the user message."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = time.strftime("%Z") or "UTC"
        lines = [f"Current Time: {now} ({tz})"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines)
    
    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []
        
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")
        
        return "\n\n".join(parts) if parts else ""

    def _build_sillytavern_context(self) -> str:
        """Build SillyTavern context (character card, world info, preset, memories).

        Returns empty string if no SillyTavern content is configured.
        """
        try:
            if not self.sillytavern_config.enabled:
                return ""

            parts: list[str] = []

            # 1. Active character card
            from nanobot.sillytavern.storage import get_active_character
            from nanobot.sillytavern.character_card import build_character_prompt

            char = get_active_character()
            if char:
                prompt = build_character_prompt(char.data)
                if prompt:
                    parts.append(prompt)

            # 2. World info (activated entries)
            from nanobot.sillytavern.storage import get_enabled_world_info
            from nanobot.sillytavern.world_info import (
                get_activated_entries,
                build_world_info_prompt,
            )
            from nanobot.sillytavern.types import WorldInfoBook

            wi_books = get_enabled_world_info()
            if wi_books:
                activation_ctx = self.memory.get_memory_context() or ""

                all_activated = []
                for stored_book in wi_books:
                    book = WorldInfoBook(entries=stored_book.entries)
                    activated = get_activated_entries(book, activation_ctx)
                    all_activated.extend(activated)

                wi_prompt = build_world_info_prompt(all_activated)
                if wi_prompt:
                    parts.append(wi_prompt)

            # 3. Active preset (prompt entries)
            from nanobot.sillytavern.storage import get_active_preset
            from nanobot.sillytavern.preset import get_enabled_prompts, build_preset_prompt, apply_macros
            from nanobot.sillytavern.types import MacrosConfig

            preset = get_active_preset()
            if preset:
                prompts = get_enabled_prompts(preset.data)
                preset_prompt = build_preset_prompt(prompts)
                if preset_prompt:
                    macros = MacrosConfig(
                        char=char.name if char else "Assistant",
                    )
                    preset_prompt = apply_macros(preset_prompt, macros)
                    parts.append(f"## Preset Instructions\n\n{preset_prompt}")

            if not parts:
                return ""

            return "# SillyTavern\n\n" + "\n\n---\n\n".join(parts)

        except Exception:
            # Fail silently — SillyTavern is optional
            return ""
    
    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call."""
        return [
            {"role": "system", "content": self.build_system_prompt(skill_names)},
            *history,
            {"role": "user", "content": self._build_runtime_context(channel, chat_id)},
            {"role": "user", "content": self._build_user_content(current_message, media)},
        ]

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text
        
        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        
        if not images:
            return text
        return images + [{"type": "text", "text": text}]
    
    def add_tool_result(
        self, messages: list[dict[str, Any]],
        tool_call_id: str, tool_name: str, result: str,
    ) -> list[dict[str, Any]]:
        """Add a tool result to the message list."""
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result})
        return messages
    
    def add_assistant_message(
        self, messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
    ) -> list[dict[str, Any]]:
        """Add an assistant message to the message list."""
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content
        messages.append(msg)
        return messages
