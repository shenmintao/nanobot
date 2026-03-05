"""WhatsApp channel implementation using Node.js bridge.

Supports: text, media send/receive, reactions, typing indicators,
quoted replies, stickers, polls, voice transcription, and message debouncing.
"""

import asyncio
import base64
import json
from collections import OrderedDict, defaultdict
from pathlib import Path

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WhatsAppConfig


class WhatsAppChannel(BaseChannel):
    """
    WhatsApp channel that connects to a Node.js bridge.

    The bridge uses @whiskeysockets/baileys to handle the WhatsApp Web protocol.
    Communication between Python and Node.js is via WebSocket.
    """

    name = "whatsapp"

    def __init__(self, config: WhatsAppConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: WhatsAppConfig = config
        self._ws = None
        self._connected = False
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        # Debounce: use config value or default 2.0s
        self._debounce_seconds: float = getattr(config, 'debounce_seconds', 2.0)
        self._debounce_buffers: dict[str, list[dict]] = defaultdict(list)
        self._debounce_tasks: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """Start the WhatsApp channel by connecting to the bridge."""
        import websockets

        bridge_url = self.config.bridge_url

        logger.info("Connecting to WhatsApp bridge at {}...", bridge_url)

        self._running = True

        while self._running:
            try:
                async with websockets.connect(bridge_url) as ws:
                    self._ws = ws
                    # Send auth token if configured
                    if self.config.bridge_token:
                        await ws.send(json.dumps({"type": "auth", "token": self.config.bridge_token}))
                    self._connected = True
                    logger.info("Connected to WhatsApp bridge")

                    # Listen for messages
                    async for message in ws:
                        try:
                            await self._handle_bridge_message(message)
                        except Exception as e:
                            logger.error("Error handling bridge message: {}", e)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                self._ws = None
                logger.warning("WhatsApp bridge connection error: {}", e)

                if self._running:
                    logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the WhatsApp channel."""
        self._running = False
        self._connected = False

        # Cancel all debounce tasks
        for task in self._debounce_tasks.values():
            task.cancel()
        self._debounce_tasks.clear()
        self._debounce_buffers.clear()

        if self._ws:
            await self._ws.close()
            self._ws = None

    # =========================================================================
    # Outbound: Send text message
    # =========================================================================

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through WhatsApp."""
        if not self._ws or not self._connected:
            logger.warning("WhatsApp bridge not connected")
            return

        try:
            # Send media attachments first
            for media_path in msg.media:
                await self._send_media_file(msg.chat_id, media_path, caption=msg.content)
                # If we sent media with caption, don't send text separately
                if msg.content:
                    return

            # Send text message (with optional quote)
            if msg.content:
                payload: dict = {
                    "type": "send",
                    "to": msg.chat_id,
                    "text": msg.content,
                }
                if msg.reply_to:
                    payload["quotedMsgId"] = msg.reply_to
                await self._ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            logger.error("Error sending WhatsApp message: {}", e)

    # =========================================================================
    # Outbound: Send media file
    # =========================================================================

    async def _send_media_file(
        self,
        chat_id: str,
        file_path: str,
        caption: str | None = None,
        ptt: bool = False,
    ) -> None:
        """Send a media file (image, video, audio, document) through WhatsApp."""
        if not self._ws or not self._connected:
            return

        try:
            path = Path(file_path)
            if not path.exists():
                logger.warning("Media file not found: {}", file_path)
                return

            b64 = base64.b64encode(path.read_bytes()).decode()
            mimetype = self._ext_to_mime(path.suffix.lower())

            payload = {
                "type": "send_media",
                "to": chat_id,
                "base64": b64,
                "mimetype": mimetype,
                "caption": caption or None,
                "filename": path.name,
                "ptt": ptt,
            }
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
            logger.debug("Sent media {} to {}", path.name, chat_id)
        except Exception as e:
            logger.error("Error sending media: {}", e)

    # =========================================================================
    # Outbound: Send reaction
    # =========================================================================

    async def send_reaction(self, chat_id: str, message_id: str, emoji: str) -> None:
        """Send an emoji reaction to a specific message."""
        if not self._ws or not self._connected:
            return

        try:
            payload = {
                "type": "react",
                "to": chat_id,
                "messageId": message_id,
                "emoji": emoji,
            }
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
            logger.debug("Sent reaction {} to message {} in {}", emoji, message_id, chat_id)
        except Exception as e:
            logger.error("Error sending reaction: {}", e)

    # =========================================================================
    # Outbound: Typing indicator
    # =========================================================================

    async def send_typing(self, chat_id: str, composing: bool = True) -> None:
        """Send typing indicator (composing/paused)."""
        if not self._ws or not self._connected:
            return

        try:
            payload = {
                "type": "presence",
                "to": chat_id,
                "presenceType": "composing" if composing else "paused",
            }
            await self._ws.send(json.dumps(payload))
        except Exception as e:
            logger.error("Error sending typing indicator: {}", e)

    # =========================================================================
    # Outbound: Send sticker
    # =========================================================================

    async def send_sticker(self, chat_id: str, sticker_path: str) -> None:
        """Send a sticker (WebP image) through WhatsApp."""
        if not self._ws or not self._connected:
            return

        try:
            path = Path(sticker_path)
            if not path.exists():
                logger.warning("Sticker file not found: {}", sticker_path)
                return

            b64 = base64.b64encode(path.read_bytes()).decode()
            payload = {
                "type": "send_sticker",
                "to": chat_id,
                "base64": b64,
            }
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
            logger.debug("Sent sticker to {}", chat_id)
        except Exception as e:
            logger.error("Error sending sticker: {}", e)

    # =========================================================================
    # Outbound: Send poll
    # =========================================================================

    async def send_poll(
        self,
        chat_id: str,
        name: str,
        options: list[str],
        selectable_count: int = 1,
    ) -> None:
        """Send a poll through WhatsApp."""
        if not self._ws or not self._connected:
            return

        try:
            payload = {
                "type": "send_poll",
                "to": chat_id,
                "name": name,
                "options": options,
                "selectableCount": selectable_count,
            }
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
            logger.debug("Sent poll '{}' to {}", name, chat_id)
        except Exception as e:
            logger.error("Error sending poll: {}", e)

    # =========================================================================
    # MIME helpers
    # =========================================================================

    @staticmethod
    def _mime_to_ext(mimetype: str) -> str:
        """Map MIME type to file extension."""
        ext_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "audio/ogg": ".ogg",
            "audio/ogg; codecs=opus": ".ogg",
            "audio/mpeg": ".mp3",
            "audio/mp4": ".m4a",
            "video/mp4": ".mp4",
            "application/pdf": ".pdf",
        }
        return ext_map.get(mimetype, ".bin")

    @staticmethod
    def _ext_to_mime(ext: str) -> str:
        """Map file extension to MIME type."""
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".ogg": "audio/ogg; codecs=opus",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".mp4": "video/mp4",
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        return mime_map.get(ext, "application/octet-stream")

    # =========================================================================
    # Inbound: Handle bridge messages
    # =========================================================================

    async def _handle_bridge_message(self, raw: str) -> None:
        """Handle a message from the bridge."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from bridge: {}", raw[:100])
            return

        msg_type = data.get("type")

        if msg_type == "message":
            await self._handle_inbound_message(data)

        elif msg_type == "status":
            # Connection status update
            status = data.get("status")
            logger.info("WhatsApp status: {}", status)

            if status == "connected":
                self._connected = True
            elif status == "disconnected":
                self._connected = False

        elif msg_type == "qr":
            # QR code for authentication
            logger.info("Scan QR code in the bridge terminal to connect WhatsApp")

        elif msg_type == "error":
            logger.error("WhatsApp bridge error: {}", data.get('error'))

    async def _handle_inbound_message(self, data: dict) -> None:
        """Process an incoming WhatsApp message with debouncing."""
        # Deprecated by whatsapp: old phone number style typically: <phone>@s.whatspp.net
        pn = data.get("pn", "")
        # New LID style typically:
        sender = data.get("sender", "")
        content = data.get("content", "")
        message_id = data.get("id", "")

        if message_id:
            if message_id in self._processed_message_ids:
                return
            self._processed_message_ids[message_id] = None
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

        # Extract just the phone number or lid as chat_id
        user_id = pn if pn else sender
        sender_id = user_id.split("@")[0] if "@" in user_id else user_id
        logger.info("Sender {}", sender)

        # Save media attachments (images, audio, stickers etc.) from bridge to local files
        media_paths: list[str] = []
        for attachment in data.get("media", []):
            try:
                mimetype = attachment.get("mimetype", "application/octet-stream")
                b64_data = attachment.get("base64", "")
                if not b64_data:
                    continue

                ext = self._mime_to_ext(mimetype)
                media_dir = Path.home() / ".nanobot" / "media"
                media_dir.mkdir(parents=True, exist_ok=True)

                # Use message_id + index for unique filename
                file_id = message_id[:16] if message_id else "unknown"
                idx = len(media_paths)
                file_path = media_dir / f"wa_{file_id}_{idx}{ext}"

                file_path.write_bytes(base64.b64decode(b64_data))
                media_paths.append(str(file_path))
                logger.debug("Saved WhatsApp media to {}", file_path)
            except Exception as e:
                logger.error("Failed to save WhatsApp media: {}", e)

        # Handle voice message transcription
        if content == "[Voice Message]" and media_paths:
            content = await self._transcribe_voice(media_paths)

        # Handle sticker — add hint for Vision LLM
        if content in ("[Sticker]", "[Animated Sticker]") and media_paths:
            content = f"{content} (贴纸图片已附带，请描述贴纸内容和表达的情感)"

        # Build metadata
        metadata: dict = {
            "message_id": message_id,
            "timestamp": data.get("timestamp"),
            "is_group": data.get("isGroup", False),
        }
        # Include quoted message info if present
        quoted_msg_id = data.get("quotedMessageId")
        quoted_text = data.get("quotedText")
        if quoted_msg_id:
            metadata["quoted_message_id"] = quoted_msg_id
        if quoted_text:
            metadata["quoted_text"] = quoted_text
            # Prepend quoted context to content for LLM understanding
            content = f"[回复消息: \"{quoted_text}\"]\n{content}"

        # Debounce: buffer messages and wait for pause
        debounce_key = sender
        self._debounce_buffers[debounce_key].append({
            "sender_id": sender_id,
            "chat_id": sender,
            "content": content,
            "media_paths": media_paths,
            "metadata": metadata,
        })

        # Cancel previous debounce timer and start new one
        if debounce_key in self._debounce_tasks:
            self._debounce_tasks[debounce_key].cancel()

        self._debounce_tasks[debounce_key] = asyncio.create_task(
            self._flush_debounce(debounce_key)
        )

    async def _flush_debounce(self, key: str) -> None:
        """Wait for debounce period, then merge and dispatch buffered messages."""
        try:
            await asyncio.sleep(self._debounce_seconds)
        except asyncio.CancelledError:
            return

        messages = self._debounce_buffers.pop(key, [])
        self._debounce_tasks.pop(key, None)

        if not messages:
            return

        if len(messages) == 1:
            # Single message — no merging needed
            m = messages[0]
            await self._handle_message(
                sender_id=m["sender_id"],
                chat_id=m["chat_id"],
                content=m["content"],
                media=m["media_paths"] if m["media_paths"] else None,
                metadata=m["metadata"],
            )
        else:
            # Multiple messages — merge content and media
            combined_content = "\n".join(m["content"] for m in messages if m["content"])
            all_media: list[str] = []
            for m in messages:
                all_media.extend(m.get("media_paths", []))

            # Use first message's sender info, last message's metadata
            first = messages[0]
            last = messages[-1]

            await self._handle_message(
                sender_id=first["sender_id"],
                chat_id=first["chat_id"],
                content=combined_content,
                media=all_media if all_media else None,
                metadata=last["metadata"],
            )

    # =========================================================================
    # Voice transcription
    # =========================================================================

    async def _transcribe_voice(self, media_paths: list[str]) -> str:
        """Transcribe voice message audio files."""
        # Find audio file
        audio_path = next(
            (p for p in media_paths if any(
                p.endswith(ext) for ext in ('.ogg', '.mp3', '.m4a', '.bin')
            )),
            None,
        )
        if not audio_path:
            return "[Voice Message: 无音频文件]"

        try:
            from nanobot.providers.transcription import GroqTranscriptionProvider

            transcriber = GroqTranscriptionProvider()
            transcript = await transcriber.transcribe(audio_path)
            if transcript:
                logger.info("Voice transcription successful: {}...", transcript[:50])
                return f"[语音转文字] {transcript}"
            else:
                logger.warning("Voice transcription returned empty result")
                return "[Voice Message: 转录失败]"
        except Exception as e:
            logger.error("Voice transcription error: {}", e)
            return "[Voice Message: 转录出错]"
