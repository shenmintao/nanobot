/**
 * WhatsApp client wrapper using Baileys.
 * Based on OpenClaw's working implementation.
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
import { Buffer } from 'buffer';

const VERSION = '0.1.0';

export interface MediaItem {
  data: string; // base64
  mimetype: string;
  filename?: string;
}

export interface InboundMessage {
  id: string;
  sender: string;
  pn: string;
  content: string;
  timestamp: number;
  isGroup: boolean;
  media?: MediaItem[];
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
  private logger = pino({ level: 'silent' });

  constructor(options: WhatsAppClientOptions) {
    this.options = options;
  }

  async connect(): Promise<void> {
    const { state, saveCreds } = await useMultiFileAuthState(this.options.authDir);
    const { version } = await fetchLatestBaileysVersion();

    console.log(`Using Baileys version: ${version.join('.')}`);

    // Create socket following OpenClaw's pattern
    this.sock = makeWASocket({
      auth: {
        creds: state.creds,
        keys: makeCacheableSignalKeyStore(state.keys, this.logger),
      },
      version,
      logger: this.logger,
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

        try {
          const { content, media } = await this.extractMessageContent(msg);
          if (!content && (!media || media.length === 0)) continue;

          const isGroup = msg.key.remoteJid?.endsWith('@g.us') || false;

          this.options.onMessage({
            id: msg.key.id || '',
            sender: msg.key.remoteJid || '',
            pn: msg.key.remoteJidAlt || '',
            content: content || '[Media Message]',
            timestamp: msg.messageTimestamp as number,
            isGroup,
            media,
          });
        } catch (error) {
          console.error('Error processing message:', error);
        }
      }
    });
  }

  private async extractMessageContent(msg: any): Promise<{ content: string | null; media?: MediaItem[] }> {
    const message = msg.message;
    if (!message) return { content: null };

    let content: string | null = null;
    const media: MediaItem[] = [];

    // Protocol buffers often nest the actual message (e.g. viewOnceMessage)
    // We should unwrap it if needed, but for now we handle common structure.
    // If msg.message.viewOnceMessageV2?.message...
    const msgContent = message.viewOnceMessageV2?.message || message.viewOnceMessage?.message || message;

    // Text message
    if (msgContent.conversation) {
      content = msgContent.conversation;
    }
    // Extended text
    else if (msgContent.extendedTextMessage?.text) {
      content = msgContent.extendedTextMessage.text;
    }

    // Image
    if (msgContent.imageMessage) {
      content = msgContent.imageMessage.caption || content; // Use caption as content if available
      try {
        const buffer = await downloadMediaMessage(
          msg,
          'buffer',
          {},
          { logger: this.logger, reuploadRequest: this.sock.updateMediaMessage }
        );
        media.push({
          data: buffer.toString('base64'),
          mimetype: msgContent.imageMessage.mimetype || 'image/jpeg',
          filename: 'image.jpg'
        });
      } catch (e) {
        console.error('Failed to download image:', e);
      }
    }

    // Video
    if (msgContent.videoMessage) {
      content = msgContent.videoMessage.caption || content;
      // Nanobot backend mainly supports images via vision models, but we can forward video too if needed.
      // For now, treat valid video as media if user wants it, but maybe skip large videos?
      // Check file size? msgContent.videoMessage.fileLength
    }

    // Audio / Voice
    if (msgContent.audioMessage) {
      // Support voice transcription in backend if needed
      try {
        const buffer = await downloadMediaMessage(
          msg,
          'buffer',
          {},
          { logger: this.logger, reuploadRequest: this.sock.updateMediaMessage }
        );
        media.push({
          data: buffer.toString('base64'),
          mimetype: msgContent.audioMessage.mimetype || 'audio/ogg; codecs=opus',
          filename: 'audio.ogg'
        });
      } catch (e) {
        console.error('Failed to download audio:', e);
      }
    }

    // Document
    if (msgContent.documentMessage) {
      content = msgContent.documentMessage.caption || content;
    }

    return { content, media };
  }

  async sendMessage(to: string, text: string): Promise<void> {
    if (!this.sock) {
      throw new Error('Not connected');
    }

    await this.sock.sendMessage(to, { text });
  }

  async disconnect(): Promise<void> {
    if (this.sock) {
      this.sock.end(undefined);
      this.sock = null;
    }
  }
}
