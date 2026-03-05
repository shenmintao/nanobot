"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
        # Optional hook for injecting extra context (e.g. SillyTavern).
        # Must return a string or empty string.
        self.context_hook: Callable[[], str] | None = None
        # Emotional companion hooks (set by AgentLoop when enabled)
        self._emotion_context_hook: Callable[[str], str] | None = None
        self._scene_context_hook: Callable[[str], str] | None = None
        self._diary_context_hook: Callable[[str], str] | None = None

    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        session_key: str = "",
    ) -> str:
        """Build the system prompt from identity, bootstrap files, memory, skills, and companion context."""
        parts = [self._get_identity()]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

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

        # Emotional companion: scene awareness context
        if self._scene_context_hook and session_key:
            try:
                scene_ctx = self._scene_context_hook(session_key)
                if scene_ctx:
                    parts.append(scene_ctx)
            except Exception:
                pass

        # Emotional companion: emotion context
        if self._emotion_context_hook and session_key:
            try:
                emotion_ctx = self._emotion_context_hook(session_key)
                if emotion_ctx:
                    parts.append(f"## 用户情感状态\n{emotion_ctx}")
            except Exception:
                pass

        # Emotional companion: diary context (recent diary entries)
        if self._diary_context_hook and session_key:
            try:
                diary_ctx = self._diary_context_hook(session_key)
                if diary_ctx:
                    parts.append(diary_ctx)
            except Exception:
                pass

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
        # WhatsApp-specific capabilities hint
        if channel == "whatsapp":
            lines.append(
                "\n## WhatsApp 特殊能力\n"
                "- 发送表情包：在回复中使用 [sticker:😊] 或 [sticker:❤️] 标记，系统会自动将 emoji 渲染为 WhatsApp 贴纸发送。"
                "适合在表达情感、打招呼、庆祝等场景使用。可以和文字混合使用，例如：'早上好！[sticker:🌅]'\n"
                "- 语音回复：在回复中加入 [voice] 标记，系统会将你的文字回复同时转为语音消息发送。"
                "适合在安慰、鼓励、晚安问候等温馨场景使用。[voice] 标记不会显示给用户。"
                "例如：'晚安，做个好梦 [voice]'\n"
                "注意：不要每条消息都发语音或表情包，根据对话情境自然地使用。"
            )
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

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        session_key: str = "",
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call."""
        runtime_ctx = self._build_runtime_context(channel, chat_id)
        user_content = self._build_user_content(current_message, media)

        # Collect extra context from hook (e.g. SillyTavern)
        hook_content = ""
        if self.context_hook:
            try:
                hook_content = self.context_hook() or ""
            except Exception:
                hook_content = ""

        # Merge runtime context, hook content, and user content into a single
        # user message to avoid consecutive same-role messages that some
        # providers reject.
        if isinstance(user_content, str):
            text_parts = [p for p in [hook_content, runtime_ctx, user_content] if p]
            merged = "\n\n".join(text_parts)
        else:
            prefix_parts = [p for p in [hook_content, runtime_ctx] if p]
            prefix = [{"type": "text", "text": "\n\n".join(prefix_parts)}] if prefix_parts else []
            merged = prefix + user_content

        return [
            {"role": "system", "content": self.build_system_prompt(skill_names, session_key=session_key)},
            *history,
            {"role": "user", "content": merged},
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
        thinking_blocks: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """Add an assistant message to the message list."""
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content
        if thinking_blocks:
            msg["thinking_blocks"] = thinking_blocks
        messages.append(msg)
        return messages
