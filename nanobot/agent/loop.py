"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import weakref
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.memory import MemoryStore
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.config.schema import ChannelsConfig, EmotionalCompanionConfig, ExecToolConfig
    from nanobot.cron.service import CronService


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    _TOOL_RESULT_MAX_CHARS = 500

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        memory_window: int = 100,
        reasoning_effort: str | None = None,
        brave_api_key: str | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        emotional_companion_config: EmotionalCompanionConfig | None = None,
    ):
        from nanobot.config.schema import ExecToolConfig
        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.reasoning_effort = reasoning_effort
        self.brave_api_key = brave_api_key
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace

        self.context = ContextBuilder(workspace)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            reasoning_effort=reasoning_effort,
            brave_api_key=brave_api_key,
            web_proxy=web_proxy,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress
        self._consolidation_tasks: set[asyncio.Task] = set()  # Strong refs to in-flight tasks
        self._consolidation_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._processing_lock = asyncio.Lock()
        # Optional hook for filtering response content (e.g. SillyTavern tag extraction).
        self.response_filter: Callable[[str], str] | None = None
        self._register_default_tools()

        # --- Emotional Companion (gated by config) ---
        self._emotion_tracker = None
        self._scene_awareness = None
        self._proactive_care = None
        self._link_understanding = None
        self._media_understanding = None
        self._diary_generator = None
        self._emotion_tasks: set[asyncio.Task] = set()  # Strong refs to background emotion analysis
        self._emotional_companion_config = emotional_companion_config
        self._init_emotional_companion(emotional_companion_config)

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
            path_append=self.exec_config.path_append,
        ))
        self.tools.register(WebSearchTool(api_key=self.brave_api_key, proxy=self.web_proxy))
        self.tools.register(WebFetchTool(proxy=self.web_proxy))
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    def _init_emotional_companion(self, config: EmotionalCompanionConfig | None) -> None:
        """Initialize emotional companion modules if enabled."""
        if not config or not config.enabled:
            return

        logger.info("Emotional companion enabled")
        modules = config.modules

        # Emotion tracking
        if modules.emotion_tracking:
            from nanobot.sillytavern.emotion import EmotionTracker
            self._emotion_tracker = EmotionTracker(
                provider=self.provider,
                model=self.model,
            )
            # Wire emotion context hook into ContextBuilder
            self.context._emotion_context_hook = self._emotion_tracker.format_emotion_context
            logger.info("  ✓ Emotion tracking enabled")

        # Scene awareness
        if modules.scene_awareness:
            from nanobot.sillytavern.scene_awareness import SceneAwareness
            tz = config.timezone or None
            self._scene_awareness = SceneAwareness(timezone=tz)
            # Wire scene context hook into ContextBuilder
            self.context._scene_context_hook = self._scene_awareness.format_scene_prompt
            logger.info("  ✓ Scene awareness enabled (tz={})", tz or "system")

        # Proactive care
        if modules.proactive_care:
            from nanobot.sillytavern.proactive_care import ProactiveCareEngine
            self._proactive_care = ProactiveCareEngine(
                provider=self.provider,
                model=self.model,
                config=config.proactive_care,
                emotion_tracker=self._emotion_tracker,
                scene_awareness=self._scene_awareness,
            )
            logger.info("  ✓ Proactive care enabled")

        # Link understanding
        if modules.link_understanding:
            from nanobot.agent.link_understanding import LinkUnderstanding
            web_fetch = self.tools.get("web_fetch")
            if web_fetch:
                self._link_understanding = LinkUnderstanding(
                    web_fetch_tool=web_fetch,
                    max_urls=config.link_understanding.max_urls_per_message,
                    max_content_chars=config.link_understanding.max_content_chars,
                )
                logger.info("  ✓ Link understanding enabled")
            else:
                logger.warning("  ✗ Link understanding skipped: web_fetch tool not available")

        # Media understanding
        if modules.media_understanding:
            from nanobot.agent.media_understanding import MediaUnderstanding
            self._media_understanding = MediaUnderstanding(
                provider=self.provider,
                model=self.model,
                video_enabled=config.media_understanding.video_enabled,
                pdf_enabled=config.media_understanding.pdf_enabled,
                max_frames=config.media_understanding.max_frames,
            )
            logger.info("  ✓ Media understanding enabled")

        # Diary generator
        if modules.diary:
            from nanobot.sillytavern.diary import DiaryGenerator
            self._diary_generator = DiaryGenerator(
                provider=self.provider,
                model=self.model,
                emotion_tracker=self._emotion_tracker,
                session_manager=self.sessions,
            )
            # Wire diary context hook into ContextBuilder
            self.context._diary_context_hook = self._diary_generator.format_diary_context
            logger.info("  ✓ Diary generator enabled")

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from nanobot.agent.tools.mcp import connect_mcp_servers
        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
            self._mcp_connected = True
        except Exception as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    pass
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for all tools that need routing info."""
        for name in ("message", "spawn", "cron"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    tool.set_context(channel, chat_id, *([message_id] if name == "message" else []))

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Format tool calls as concise hint, e.g. 'web_search("query")'."""
        def _fmt(tc):
            args = (tc.arguments[0] if isinstance(tc.arguments, list) else tc.arguments) or {}
            val = next(iter(args.values()), None) if isinstance(args, dict) else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'
        return ", ".join(_fmt(tc) for tc in tool_calls)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str], list[dict]]:
        """Run the agent iteration loop. Returns (final_content, tools_used, messages)."""
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []

        while iteration < self.max_iterations:
            iteration += 1

            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                reasoning_effort=self.reasoning_effort,
            )

            if response.has_tool_calls:
                if on_progress:
                    clean = self._strip_think(response.content)
                    if clean:
                        await on_progress(clean)
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )

                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                clean = self._strip_think(response.content)
                # Don't persist error responses to session history — they can
                # poison the context and cause permanent 400 loops (#1303).
                if response.finish_reason == "error":
                    logger.error("LLM returned error: {}", (clean or "")[:200])
                    final_content = clean or "Sorry, I encountered an error calling the AI model."
                    break
                messages = self.context.add_assistant_message(
                    messages, clean, reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                final_content = clean
                if final_content and self.response_filter:
                    final_content = self.response_filter(final_content)
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )

        return final_content, tools_used, messages

    async def run(self) -> None:
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if msg.content.strip().lower() == "/stop":
                await self._handle_stop(msg)
            else:
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                task.add_done_callback(lambda t, k=msg.session_key: self._active_tasks.get(k, []) and self._active_tasks[k].remove(t) if t in self._active_tasks.get(k, []) else None)

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Cancel all active tasks and subagents for the session."""
        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        sub_cancelled = await self.subagents.cancel_by_session(msg.session_key)
        total = cancelled + sub_cancelled
        content = f"⏹ Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))

    def _get_whatsapp_channel(self):
        """Get the WhatsApp channel instance if available."""
        try:
            from nanobot.channels.whatsapp import WhatsAppChannel
            cm = getattr(self, 'channel_manager', None)
            if cm and hasattr(cm, 'channels'):
                ch = cm.channels.get("whatsapp")
                if isinstance(ch, WhatsAppChannel):
                    return ch
        except ImportError:
            pass
        return None

    async def _send_typing_indicator(self, msg: InboundMessage, composing: bool = True) -> None:
        """Send typing indicator for WhatsApp messages."""
        if msg.channel != "whatsapp":
            return
        wa = self._get_whatsapp_channel()
        if wa:
            await wa.send_typing(msg.chat_id, composing=composing)

    async def _send_auto_reaction(self, msg: InboundMessage) -> None:
        """Send automatic emoji reaction based on emotion analysis (WhatsApp only)."""
        if msg.channel != "whatsapp" or not self._emotion_tracker:
            return

        # Check if auto_reaction is enabled in config
        if self.channels_config:
            wa_config = getattr(self.channels_config, 'whatsapp', None)
            if wa_config and not getattr(wa_config, 'auto_reaction', True):
                return

        message_id = (msg.metadata or {}).get("message_id")
        if not message_id:
            return

        wa = self._get_whatsapp_channel()
        if not wa:
            return

        # Map emotions to reaction emojis
        emotion_reactions = {
            "happy": "😊", "sad": "🫂", "anxious": "💪",
            "angry": "❤️", "excited": "🎉", "lonely": "🤗",
            "tired": "☕", "grateful": "🥰", "frustrated": "💕",
        }

        try:
            entry = await self._emotion_tracker.analyze(msg.content, msg.session_key)
            if entry and entry.emotion in emotion_reactions:
                emoji = emotion_reactions[entry.emotion]
                await wa.send_reaction(msg.chat_id, message_id, emoji)
        except Exception:
            logger.debug("Auto-reaction failed", exc_info=True)

    # Regex to detect [voice] tag in LLM response (for auto mode)
    _VOICE_TAG_RE = re.compile(r'\[voice\]', re.IGNORECASE)

    async def _send_tts_voice(self, msg: InboundMessage, text: str) -> None:
        """Send TTS voice message for WhatsApp if configured.

        Supports three modes:
        - "auto": LLM decides by including [voice] tag in response
        - "mirror": reply with voice only when user sent a voice message
        - "always": always send voice with text reply
        """
        if msg.channel != "whatsapp":
            return

        # Check TTS config
        if not self.channels_config:
            logger.debug("TTS skipped: no channels_config")
            return
        wa_config = getattr(self.channels_config, 'whatsapp', None)
        if not wa_config:
            logger.debug("TTS skipped: no whatsapp config")
            return
        tts_config = getattr(wa_config, 'tts', None)
        if not tts_config or not tts_config.enabled:
            logger.debug("TTS skipped: tts not enabled (enabled={})", getattr(tts_config, 'enabled', None))
            return

        # Determine if we should send voice
        is_voice_reply = "[语音转文字]" in msg.content
        has_voice_tag = bool(self._VOICE_TAG_RE.search(text))
        should_send = (
            tts_config.mode == "always"
            or (tts_config.mode == "mirror" and is_voice_reply)
            or (tts_config.mode == "auto" and has_voice_tag)
        )
        if not should_send:
            logger.debug("TTS skipped: mode={}, is_voice_reply={}, has_voice_tag={}", tts_config.mode, is_voice_reply, has_voice_tag)
            return

        wa = self._get_whatsapp_channel()
        if not wa:
            logger.warning("TTS skipped: WhatsApp channel not available (channel_manager not set?)")
            return

        try:
            from nanobot.providers.tts import EdgeTTSProvider
            logger.info("TTS: synthesizing voice (voice={}, mode={})", tts_config.voice, tts_config.mode)
            tts = EdgeTTSProvider(
                voice=tts_config.voice,
                rate=tts_config.rate,
                pitch=tts_config.pitch,
            )
            # Strip sticker and voice tags from text before TTS
            clean_text = re.sub(r'\[sticker:[^\]]+\]', '', text)
            clean_text = self._VOICE_TAG_RE.sub('', clean_text).strip()
            if not clean_text:
                logger.debug("TTS skipped: no text after stripping tags")
                return
            # Try OGG for WhatsApp PTT style, fallback to MP3
            audio_path = await tts.synthesize(clean_text, output_format="ogg")
            if audio_path:
                await wa._send_media_file(msg.chat_id, audio_path, ptt=True)
                logger.info("Sent TTS voice message to {}", msg.chat_id)
                # Clean up temp file
                try:
                    Path(audio_path).unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                logger.warning("TTS synthesis returned no audio file")
        except ImportError:
            logger.warning("TTS failed: edge-tts not installed. Install with: pip install edge-tts")
        except Exception:
            logger.warning("TTS voice send failed", exc_info=True)

    # =========================================================================
    # Sticker sending from LLM response
    # =========================================================================

    # Regex to match [sticker:emoji_or_description] tags in LLM responses
    _STICKER_TAG_RE = re.compile(r'\[sticker:([^\]]+)\]')

    async def _send_stickers_from_response(self, msg: InboundMessage, text: str) -> str:
        """Extract [sticker:xxx] tags from response, send as stickers, return cleaned text.

        The LLM can include [sticker:😊] or [sticker:开心的猫] in its response.
        This method extracts those tags, generates sticker images, sends them,
        and returns the text with sticker tags removed.
        """
        if msg.channel != "whatsapp":
            return text

        # Check sticker config
        if self.channels_config:
            wa_config = getattr(self.channels_config, 'whatsapp', None)
            if wa_config:
                sticker_config = getattr(wa_config, 'sticker', None)
                if sticker_config and not sticker_config.enabled:
                    # Sticker disabled — just strip tags
                    return self._STICKER_TAG_RE.sub('', text).strip()

        matches = self._STICKER_TAG_RE.findall(text)
        if not matches:
            return text

        wa = self._get_whatsapp_channel()
        if not wa:
            return text

        for sticker_desc in matches:
            sticker_desc = sticker_desc.strip()
            if not sticker_desc:
                continue
            try:
                sticker_path = await self._generate_emoji_sticker(sticker_desc)
                if sticker_path:
                    await wa.send_sticker(msg.chat_id, sticker_path)
                    logger.info("Sent sticker [{}] to {}", sticker_desc, msg.chat_id)
                    # Clean up temp file
                    try:
                        Path(sticker_path).unlink(missing_ok=True)
                    except Exception:
                        pass
                else:
                    logger.debug("Sticker generation returned None for: {}", sticker_desc)
            except Exception:
                logger.warning("Failed to send sticker [{}]", sticker_desc, exc_info=True)

        # Remove sticker tags from text
        cleaned = self._STICKER_TAG_RE.sub('', text).strip()
        return cleaned

    @staticmethod
    async def _generate_emoji_sticker(emoji_or_desc: str) -> str | None:
        """Generate a sticker WebP image from an emoji character.

        Uses Pillow to render the emoji as a 512x512 WebP image suitable for
        WhatsApp stickers. Falls back to a text-based sticker if emoji rendering
        is not available.

        Args:
            emoji_or_desc: An emoji character (e.g. "😊") or short description.

        Returns:
            Path to the generated WebP sticker file, or None on failure.
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            logger.warning("Sticker generation requires Pillow: pip install Pillow")
            return None

        try:
            # Create 512x512 transparent image
            img = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            # Try to use a system emoji font for rendering
            text = emoji_or_desc
            font_size = 256 if len(text) <= 2 else 128
            font = None

            # Try common emoji font paths
            emoji_font_paths = [
                # Linux
                "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
                "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf",
                "/usr/share/fonts/noto-emoji/NotoColorEmoji.ttf",
                # macOS
                "/System/Library/Fonts/Apple Color Emoji.ttc",
                # Windows
                "C:/Windows/Fonts/seguiemj.ttf",
                # Fallback: any CJK font for text descriptions
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
                "/System/Library/Fonts/PingFang.ttc",
                "C:/Windows/Fonts/msyh.ttc",
            ]

            for font_path in emoji_font_paths:
                if Path(font_path).exists():
                    try:
                        font = ImageFont.truetype(font_path, font_size)
                        break
                    except Exception:
                        continue

            if font is None:
                # Use default font (very small, but works)
                font = ImageFont.load_default()
                font_size = 20

            # Calculate text position (center)
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = (512 - text_width) // 2
            y = (512 - text_height) // 2

            # Draw text (embedded_color for color emoji fonts, with fallback)
            try:
                draw.text((x, y), text, font=font, fill=(255, 255, 255, 255),
                          embedded_color=True)
            except TypeError:
                # Older Pillow versions don't support embedded_color
                draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

            # Save as WebP
            sticker_path = tempfile.mktemp(suffix=".webp", prefix="nanobot_sticker_")
            img.save(sticker_path, 'WEBP', quality=90)

            if Path(sticker_path).exists() and Path(sticker_path).stat().st_size > 0:
                return sticker_path

            return None
        except Exception as e:
            logger.warning("Sticker generation failed: {}", e)
            return None

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message under the global lock."""
        async with self._processing_lock:
            try:
                # Send typing indicator (WhatsApp)
                await self._send_typing_indicator(msg, composing=True)

                response = await self._process_message(msg)

                # Stop typing indicator
                await self._send_typing_indicator(msg, composing=False)

                if response is not None:
                    # WhatsApp: extract and send stickers, strip [voice] tags before text reply
                    original_content = response.content
                    if msg.channel == "whatsapp" and response.content:
                        # 1. Send stickers and strip [sticker:xxx] tags
                        cleaned = await self._send_stickers_from_response(msg, response.content)
                        # 2. Strip [voice] tags from text (they are only a signal for TTS)
                        cleaned = self._VOICE_TAG_RE.sub('', cleaned).strip()
                        if cleaned != response.content:
                            response = OutboundMessage(
                                channel=response.channel,
                                chat_id=response.chat_id,
                                content=cleaned,
                                reply_to=response.reply_to,
                                media=response.media,
                                metadata=response.metadata,
                            )

                    # Send text reply (may be empty if only stickers)
                    if response.content:
                        await self.bus.publish_outbound(response)

                    # WhatsApp enhancements (non-blocking)
                    if msg.channel == "whatsapp" and original_content:
                        # Auto-reaction based on emotion
                        asyncio.create_task(self._send_auto_reaction(msg))
                        # TTS voice reply — pass original_content so [voice] tag can be detected
                        asyncio.create_task(self._send_tts_voice(msg, original_content))

                elif msg.channel == "cli":
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id,
                        content="", metadata=msg.metadata or {},
                    ))
            except asyncio.CancelledError:
                await self._send_typing_indicator(msg, composing=False)
                logger.info("Task cancelled for session {}", msg.session_key)
                raise
            except Exception:
                await self._send_typing_indicator(msg, composing=False)
                logger.exception("Error processing message for session {}", msg.session_key)
                await self.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Sorry, I encountered an error.",
                ))

    async def close_mcp(self) -> None:
        """Close MCP connections."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (msg.chat_id.split(":", 1) if ":" in msg.chat_id
                                else ("cli", msg.chat_id))
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            history = session.get_history(max_messages=self.memory_window)
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content, channel=channel, chat_id=chat_id,
            )
            final_content, _, all_msgs = await self._run_agent_loop(messages)
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)
            return OutboundMessage(channel=channel, chat_id=chat_id,
                                  content=final_content or "Background task completed.")

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())
            self._consolidating.add(session.key)
            try:
                async with lock:
                    snapshot = session.messages[session.last_consolidated:]
                    if snapshot:
                        temp = Session(key=session.key)
                        temp.messages = list(snapshot)
                        if not await self._consolidate_memory(temp, archive_all=True):
                            return OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content="Memory archival failed, session not cleared. Please try again.",
                            )
            except Exception:
                logger.exception("/new archival failed for {}", session.key)
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Memory archival failed, session not cleared. Please try again.",
                )
            finally:
                self._consolidating.discard(session.key)

            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="New session started.")
        if cmd == "/help":
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="🐈 nanobot commands:\n/new — Start a new conversation\n/stop — Stop the current task\n/help — Show available commands")

        unconsolidated = len(session.messages) - session.last_consolidated
        if (unconsolidated >= self.memory_window and session.key not in self._consolidating):
            self._consolidating.add(session.key)
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())

            async def _consolidate_and_unlock():
                try:
                    async with lock:
                        await self._consolidate_memory(session)
                finally:
                    self._consolidating.discard(session.key)
                    _task = asyncio.current_task()
                    if _task is not None:
                        self._consolidation_tasks.discard(_task)

            _task = asyncio.create_task(_consolidate_and_unlock())
            self._consolidation_tasks.add(_task)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        # Emotional companion: record chat for scene awareness & proactive care
        if self._scene_awareness:
            self._scene_awareness.record_chat(key)
        if self._proactive_care:
            self._proactive_care.record_interaction(key)

        # Emotional companion: link understanding — enrich message with link content
        enriched_content = msg.content
        if self._link_understanding and self._link_understanding.has_urls(msg.content):
            try:
                link_context = await self._link_understanding.summarize_links(msg.content)
                if link_context:
                    enriched_content = msg.content + link_context
            except Exception:
                logger.debug("Link understanding failed, continuing without", exc_info=True)

        # Emotional companion: media understanding — process non-image media
        media_context = ""
        if self._media_understanding and msg.media:
            for media_path in msg.media:
                if self._media_understanding.is_supported(media_path):
                    try:
                        result = await self._media_understanding.process(media_path)
                        if result:
                            media_context += f"\n\n{result}"
                    except Exception:
                        logger.debug("Media understanding failed for {}", media_path, exc_info=True)
        if media_context:
            enriched_content = enriched_content + media_context

        history = session.get_history(max_messages=self.memory_window)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=enriched_content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
            session_key=key,
        )

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta,
            ))

        final_content, _, all_msgs = await self._run_agent_loop(
            initial_messages, on_progress=on_progress or _bus_progress,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)

        # Emotional companion: async emotion analysis (non-blocking)
        if self._emotion_tracker and msg.content.strip():
            task = asyncio.create_task(
                self._emotion_tracker.analyze(msg.content, key)
            )
            self._emotion_tasks.add(task)
            task.add_done_callback(self._emotion_tasks.discard)

        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=final_content,
            metadata=msg.metadata or {},
        )

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        from datetime import datetime
        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                entry["content"] = content[:self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
            elif role == "user":
                if isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                    # Strip the runtime-context prefix, keep only the user text.
                    parts = content.split("\n\n", 1)
                    if len(parts) > 1 and parts[1].strip():
                        entry["content"] = parts[1]
                    else:
                        continue
                if isinstance(content, list):
                    filtered = []
                    for c in content:
                        if c.get("type") == "text" and isinstance(c.get("text"), str) and c["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                            continue  # Strip runtime context from multimodal messages
                        if (c.get("type") == "image_url"
                                and c.get("image_url", {}).get("url", "").startswith("data:image/")):
                            filtered.append({"type": "text", "text": "[image]"})
                        else:
                            filtered.append(c)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    async def _consolidate_memory(self, session, archive_all: bool = False) -> bool:
        """Delegate to MemoryStore.consolidate(). Returns True on success."""
        return await MemoryStore(self.workspace).consolidate(
            session, self.provider, self.model,
            archive_all=archive_all, memory_window=self.memory_window,
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self._connect_mcp()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(msg, session_key=session_key, on_progress=on_progress)
        return response.content if response else ""
