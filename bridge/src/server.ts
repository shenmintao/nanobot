/**
 * WebSocket server for Python-Node.js bridge communication.
 * Security: binds to 127.0.0.1 only; optional BRIDGE_TOKEN auth.
 *
 * Supported commands from Python:
 *   - send: Send text message (with optional quote)
 *   - send_media: Send image/video/audio/document
 *   - react: Send emoji reaction
 *   - presence: Send typing indicator
 *   - send_poll: Send a poll
 */

import { WebSocketServer, WebSocket } from 'ws';
import { WhatsAppClient, InboundMessage } from './whatsapp.js';

// ---------------------------------------------------------------------------
// Command types from Python
// ---------------------------------------------------------------------------

interface SendCommand {
  type: 'send';
  to: string;
  text: string;
  quotedMsgId?: string;
}

interface SendMediaCommand {
  type: 'send_media';
  to: string;
  base64: string;
  mimetype: string;
  caption?: string;
  filename?: string;
  ptt?: boolean;
}

interface ReactCommand {
  type: 'react';
  to: string;
  messageId: string;
  emoji: string;
}

interface PresenceCommand {
  type: 'presence';
  to: string;
  presenceType: 'composing' | 'paused' | 'available';
}

interface SendPollCommand {
  type: 'send_poll';
  to: string;
  name: string;
  options: string[];
  selectableCount?: number;
}

type BridgeCommand =
  | SendCommand
  | SendMediaCommand
  | ReactCommand
  | PresenceCommand
  | SendPollCommand;

// ---------------------------------------------------------------------------
// Bridge message types to Python
// ---------------------------------------------------------------------------

interface BridgeMessage {
  type: 'message' | 'status' | 'qr' | 'error' | 'sent';
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Bridge Server
// ---------------------------------------------------------------------------

export class BridgeServer {
  private wss: WebSocketServer | null = null;
  private wa: WhatsAppClient | null = null;
  private clients: Set<WebSocket> = new Set();

  constructor(private port: number, private authDir: string, private token?: string) {}

  async start(): Promise<void> {
    // Bind to localhost only — never expose to external network
    this.wss = new WebSocketServer({ host: '127.0.0.1', port: this.port });
    console.log(`🌉 Bridge server listening on ws://127.0.0.1:${this.port}`);
    if (this.token) console.log('🔒 Token authentication enabled');

    // Initialize WhatsApp client
    this.wa = new WhatsAppClient({
      authDir: this.authDir,
      onMessage: (msg) => this.broadcast({ type: 'message', ...msg }),
      onQR: (qr) => this.broadcast({ type: 'qr', qr }),
      onStatus: (status) => this.broadcast({ type: 'status', status }),
    });

    // Handle WebSocket connections
    this.wss.on('connection', (ws) => {
      if (this.token) {
        // Require auth handshake as first message
        const timeout = setTimeout(() => ws.close(4001, 'Auth timeout'), 5000);
        ws.once('message', (data) => {
          clearTimeout(timeout);
          try {
            const msg = JSON.parse(data.toString());
            if (msg.type === 'auth' && msg.token === this.token) {
              console.log('🔗 Python client authenticated');
              this.setupClient(ws);
            } else {
              ws.close(4003, 'Invalid token');
            }
          } catch {
            ws.close(4003, 'Invalid auth message');
          }
        });
      } else {
        console.log('🔗 Python client connected');
        this.setupClient(ws);
      }
    });

    // Connect to WhatsApp
    await this.wa.connect();
  }

  private setupClient(ws: WebSocket): void {
    this.clients.add(ws);

    ws.on('message', async (data) => {
      try {
        const cmd = JSON.parse(data.toString()) as BridgeCommand;
        await this.handleCommand(cmd);
        ws.send(JSON.stringify({ type: 'sent', commandType: cmd.type, to: (cmd as any).to }));
      } catch (error) {
        console.error('Error handling command:', error);
        ws.send(JSON.stringify({ type: 'error', error: String(error) }));
      }
    });

    ws.on('close', () => {
      console.log('🔌 Python client disconnected');
      this.clients.delete(ws);
    });

    ws.on('error', (error) => {
      console.error('WebSocket error:', error);
      this.clients.delete(ws);
    });
  }

  private async handleCommand(cmd: BridgeCommand): Promise<void> {
    if (!this.wa) {
      throw new Error('WhatsApp client not initialized');
    }

    switch (cmd.type) {
      case 'send':
        await this.wa.sendMessage(cmd.to, cmd.text, cmd.quotedMsgId);
        break;

      case 'send_media':
        await this.wa.sendMedia(
          cmd.to,
          cmd.base64,
          cmd.mimetype,
          cmd.caption,
          cmd.filename,
          cmd.ptt,
        );
        break;

      case 'react':
        await this.wa.sendReaction(cmd.to, cmd.messageId, cmd.emoji);
        break;

      case 'presence':
        await this.wa.sendPresence(cmd.to, cmd.presenceType);
        break;

      case 'send_poll':
        await this.wa.sendPoll(cmd.to, cmd.name, cmd.options, cmd.selectableCount ?? 1);
        break;

      default:
        console.warn('Unknown command type:', (cmd as any).type);
    }
  }

  private broadcast(msg: BridgeMessage): void {
    const data = JSON.stringify(msg);
    for (const client of this.clients) {
      if (client.readyState === WebSocket.OPEN) {
        client.send(data);
      }
    }
  }

  async stop(): Promise<void> {
    // Close all client connections
    for (const client of this.clients) {
      client.close();
    }
    this.clients.clear();

    // Close WebSocket server
    if (this.wss) {
      this.wss.close();
      this.wss = null;
    }

    // Disconnect WhatsApp
    if (this.wa) {
      await this.wa.disconnect();
      this.wa = null;
    }
  }
}
