/**
 * WhatsApp client wrapper using Baileys.
 * Based on OpenClaw's working implementation.
 *
 * Supports: text, media send/receive, reactions, typing indicators,
 * quoted replies, stickers, polls, and voice messages.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
  downloadMediaMessage,
} from '@whiskeysockets/baileys';

import { Boom } from '@hapi/boom';
import qrcode from 'qrcode-terminal';
import pino from 'pino';

const VERSION = '0.2.0';

export interface MediaAttachment {
  mimetype: string;
  base64: string;
}

export interface InboundMessage {
  id: string;
  sender: string;
  pn: string;
  content: string;
  timestamp: number;
  isGroup: boolean;
  media?: MediaAttachment[];
  /** Quoted/replied message info */
  quotedMessageId?: string;
  quotedText?: string;
}

export interface WhatsAppClientOptions {
  authDir: string;
  onMessage: (msg: InboundMessage) => void;
  onQR: (qr: string) => void;
  onStatus: (status: string) => void;
}

export class WhatsAppClient {
  private sock: any = null;
  private options: WhatsAppClientOptions;
  private reconnecting = false;

  constructor(options: WhatsAppClientOptions) {
    this.options = options;
  }

  async connect(): Promise<void> {
    const logger = pino({ level: 'silent' });
    const { state, saveCreds } = await useMultiFileAuthState(this.options.authDir);
    const { version } = await fetchLatestBaileysVersion();

    console.log(`Using Baileys version: ${version.join('.')}`);

    // Create socket following OpenClaw's pattern
    this.sock = makeWASocket({
      auth: {
        creds: state.creds,
        keys: makeCacheableSignalKeyStore(state.keys, logger),
      },
      version,
      logger,
      printQRInTerminal: false,
      browser: ['nanobot', 'cli', VERSION],
      syncFullHistory: false,
      markOnlineOnConnect: false,
    });

    // Handle WebSocket errors
    if (this.sock.ws && typeof this.sock.ws.on === 'function') {
      this.sock.ws.on('error', (err: Error) => {
        console.error('WebSocket error:', err.message);
      });
    }

    // Handle connection updates
    this.sock.ev.on('connection.update', async (update: any) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        // Display QR code in terminal
        console.log('\n📱 Scan this QR code with WhatsApp (Linked Devices):\n');
        qrcode.generate(qr, { small: true });
        this.options.onQR(qr);
      }

      if (connection === 'close') {
        const statusCode = (lastDisconnect?.error as Boom)?.output?.statusCode;
        const shouldReconnect = statusCode !== DisconnectReason.loggedOut;

        console.log(`Connection closed. Status: ${statusCode}, Will reconnect: ${shouldReconnect}`);
        this.options.onStatus('disconnected');

        if (shouldReconnect && !this.reconnecting) {
          this.reconnecting = true;
          console.log('Reconnecting in 5 seconds...');
          setTimeout(() => {
            this.reconnecting = false;
            this.connect();
          }, 5000);
        }
      } else if (connection === 'open') {
        console.log('✅ Connected to WhatsApp');
        this.options.onStatus('connected');
      }
    });

    // Save credentials on update
    this.sock.ev.on('creds.update', saveCreds);

    // Handle incoming messages
    this.sock.ev.on('messages.upsert', async ({ messages, type }: { messages: any[]; type: string }) => {
      if (type !== 'notify') return;

      for (const msg of messages) {
        // Skip own messages
        if (msg.key.fromMe) continue;

        // Skip status updates
        if (msg.key.remoteJid === 'status@broadcast') continue;

        const extracted = await this.extractMessageContent(msg);
        if (!extracted) continue;

        const isGroup = msg.key.remoteJid?.endsWith('@g.us') || false;

        this.options.onMessage({
          id: msg.key.id || '',
          sender: msg.key.remoteJid || '',
          pn: msg.key.remoteJidAlt || '',
          content: extracted.content,
          timestamp: msg.messageTimestamp as number,
          isGroup,
          media: extracted.media,
          quotedMessageId: extracted.quotedMessageId,
          quotedText: extracted.quotedText,
        });
      }
    });
  }

  private async downloadMedia(msg: any): Promise<MediaAttachment | null> {
    try {
      const buffer = await downloadMediaMessage(msg, 'buffer', {});
      if (!buffer) return null;
      const message = msg.message;
      const mimetype =
        message?.imageMessage?.mimetype ||
        message?.videoMessage?.mimetype ||
        message?.audioMessage?.mimetype ||
        message?.documentMessage?.mimetype ||
        message?.stickerMessage?.mimetype ||
        'application/octet-stream';
      return {
        mimetype,
        base64: (buffer as Buffer).toString('base64'),
      };
    } catch (err) {
      console.error('Failed to download media:', err);
      return null;
    }
  }

  /**
   * Extract quoted message context from contextInfo.
   */
  private extractQuotedInfo(contextInfo: any): { quotedMessageId?: string; quotedText?: string } {
    if (!contextInfo) return {};
    const quotedMsg = contextInfo.quotedMessage;
    const quotedId = contextInfo.stanzaId || '';
    let quotedText = '';
    if (quotedMsg) {
      quotedText =
        quotedMsg.conversation ||
        quotedMsg.extendedTextMessage?.text ||
        quotedMsg.imageMessage?.caption ||
        quotedMsg.videoMessage?.caption ||
        '';
    }
    return {
      quotedMessageId: quotedId || undefined,
      quotedText: quotedText || undefined,
    };
  }

  private async extractMessageContent(msg: any): Promise<{
    content: string;
    media?: MediaAttachment[];
    quotedMessageId?: string;
    quotedText?: string;
  } | null> {
    const message = msg.message;
    if (!message) return null;

    // Text message
    if (message.conversation) {
      return { content: message.conversation };
    }

    // Extended text (reply, link preview)
    if (message.extendedTextMessage?.text) {
      const quoted = this.extractQuotedInfo(message.extendedTextMessage.contextInfo);
      return {
        content: message.extendedTextMessage.text,
        ...quoted,
      };
    }

    // Image message (with or without caption)
    if (message.imageMessage) {
      const caption = message.imageMessage.caption || '';
      const media = await this.downloadMedia(msg);
      const quoted = this.extractQuotedInfo(message.imageMessage.contextInfo);
      return {
        content: caption ? `[Image] ${caption}` : '[Image]',
        media: media ? [media] : undefined,
        ...quoted,
      };
    }

    // Video with caption
    if (message.videoMessage) {
      const caption = message.videoMessage.caption || '';
      const media = await this.downloadMedia(msg);
      return {
        content: caption ? `[Video] ${caption}` : '[Video]',
        media: media ? [media] : undefined,
      };
    }

    // Document with caption
    if (message.documentMessage) {
      const caption = message.documentMessage.caption || '';
      const media = await this.downloadMedia(msg);
      return {
        content: caption ? `[Document] ${caption}` : '[Document]',
        media: media ? [media] : undefined,
      };
    }

    // Voice/Audio message — download for transcription
    if (message.audioMessage) {
      const media = await this.downloadMedia(msg);
      return {
        content: '[Voice Message]',
        media: media ? [media] : undefined,
      };
    }

    // Sticker message — download for Vision understanding
    if (message.stickerMessage) {
      const media = await this.downloadMedia(msg);
      const isAnimated = message.stickerMessage.isAnimated || false;
      return {
        content: isAnimated ? '[Animated Sticker]' : '[Sticker]',
        media: media ? [media] : undefined,
      };
    }

    // Reaction message
    if (message.reactionMessage) {
      const emoji = message.reactionMessage.text || '';
      const targetId = message.reactionMessage.key?.id || '';
      return {
        content: emoji
          ? `[Reaction: ${emoji}] (to message: ${targetId})`
          : `[Reaction removed] (from message: ${targetId})`,
      };
    }

    // Poll creation message
    if (message.pollCreationMessage || message.pollCreationMessageV3) {
      const poll = message.pollCreationMessage || message.pollCreationMessageV3;
      const name = poll.name || '';
      const options = (poll.options || []).map((o: any) => o.optionName).join(', ');
      return {
        content: `[Poll: ${name}] Options: ${options}`,
      };
    }

    // Poll update (vote)
    if (message.pollUpdateMessage) {
      return {
        content: '[Poll Vote Update]',
      };
    }

    return null;
  }

  // ===========================================================================
  // Outbound: Send text message (with optional quote)
  // ===========================================================================

  async sendMessage(to: string, text: string, quotedMsgId?: string): Promise<void> {
    if (!this.sock) {
      throw new Error('Not connected');
    }

    const msg: any = { text };
    if (quotedMsgId) {
      msg.quoted = {
        key: { remoteJid: to, id: quotedMsgId },
        message: { conversation: '' },
      };
    }
    await this.sock.sendMessage(to, msg);
  }

  // ===========================================================================
  // Outbound: Send media (image, video, audio, document)
  // ===========================================================================

  async sendMedia(
    to: string,
    mediaBase64: string,
    mimetype: string,
    caption?: string,
    filename?: string,
    ptt?: boolean,
  ): Promise<void> {
    if (!this.sock) throw new Error('Not connected');

    const buffer = Buffer.from(mediaBase64, 'base64');

    if (mimetype.startsWith('image/')) {
      await this.sock.sendMessage(to, {
        image: buffer,
        caption: caption || undefined,
        mimetype,
      });
    } else if (mimetype.startsWith('video/')) {
      await this.sock.sendMessage(to, {
        video: buffer,
        caption: caption || undefined,
        mimetype,
      });
    } else if (mimetype.startsWith('audio/')) {
      await this.sock.sendMessage(to, {
        audio: buffer,
        mimetype,
        ptt: ptt ?? mimetype.includes('ogg'),
      });
    } else {
      await this.sock.sendMessage(to, {
        document: buffer,
        mimetype,
        fileName: filename || 'file',
      });
    }
  }

  // ===========================================================================
  // Outbound: Send reaction
  // ===========================================================================

  async sendReaction(to: string, messageId: string, emoji: string): Promise<void> {
    if (!this.sock) throw new Error('Not connected');
    await this.sock.sendMessage(to, {
      react: {
        text: emoji, // empty string = remove reaction
        key: {
          remoteJid: to,
          id: messageId,
        },
      },
    });
  }

  // ===========================================================================
  // Outbound: Typing / presence indicator
  // ===========================================================================

  async sendPresence(to: string, type: 'composing' | 'paused' | 'available'): Promise<void> {
    if (!this.sock) return;
    try {
      await this.sock.sendPresenceUpdate(type, to);
    } catch (err) {
      console.error('Failed to send presence:', err);
    }
  }

  // ===========================================================================
  // Outbound: Send sticker
  // ===========================================================================

  async sendSticker(to: string, stickerBase64: string): Promise<void> {
    if (!this.sock) throw new Error('Not connected');
    const buffer = Buffer.from(stickerBase64, 'base64');
    await this.sock.sendMessage(to, {
      sticker: buffer,
    });
  }

  // ===========================================================================
  // Outbound: Send poll
  // ===========================================================================

  async sendPoll(
    to: string,
    name: string,
    options: string[],
    selectableCount: number = 1,
  ): Promise<void> {
    if (!this.sock) throw new Error('Not connected');
    await this.sock.sendMessage(to, {
      poll: {
        name,
        values: options,
        selectableCount,
      },
    });
  }

  // ===========================================================================
  // Disconnect
  // ===========================================================================

  async disconnect(): Promise<void> {
    if (this.sock) {
      this.sock.end(undefined);
      this.sock = null;
    }
  }
}
