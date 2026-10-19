/**
 * WsClient
 * Manages WebSocket connection to Daphne ASGI server (/ws/hal/<client_id>/).
 * Sends binary PCM chunks; receives binary Kokoro audio chunks and JSON/text control signals.
 */

export class WsClient {
  constructor({ onAudioReceived, onStringReceived, onStatusChange, onLog }) {
    this.onAudioReceived = onAudioReceived || (() => {});
    this.onStringReceived = onStringReceived || (() => {});
    this.onStatusChange = onStatusChange || (() => {});
    this.onLog = onLog || console.log;

    this.socket = null;
    this.isConnected = false;
    this.reconnectTimer = null;
    this.clientId = this._getOrCreateClientId();
    this.serverHost = localStorage.getItem('hal_ws_host') || '192.168.40.189:8001';
  }

  _getOrCreateClientId() {
    let id = localStorage.getItem('hal_client_id');
    if (!id) {
      id = 'hal_device_' + Math.random().toString(36).substring(2, 11);
      localStorage.setItem('hal_client_id', id);
    }
    return id;
  }

  setCustomHost(host) {
    this.serverHost = host;
    localStorage.setItem('hal_ws_host', host);
    this.connect();
  }

  connect() {
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return;
    }

    clearTimeout(this.reconnectTimer);

    // Auto-detect protocol and host for seamless same-origin WebSocket proxying
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/hal/${this.clientId}/`;
    this.onLog(`🌐 Connecting WebSocket: ${wsUrl}`);
    this.onStatusChange('CONNECTING');

    try {
      this.socket = new WebSocket(wsUrl);
      this.socket.binaryType = 'arraybuffer';

      this.socket.onopen = () => {
        this.isConnected = true;
        this.onLog('✅ WebSocket connected successfully to HAL server.');
        this.onStatusChange('CONNECTED');
      };

      this.socket.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
          // Binary audio chunk from Kokoro TTS
          this.onAudioReceived(event.data);
        } else if (typeof event.data === 'string') {
          // Text control message (e.g. "DONE", "THINKING", "VOLUME:7")
          this.onStringReceived(event.data);
        }
      };

      this.socket.onerror = (err) => {
        this.onLog(`⚠️ WebSocket error: ${err.message || 'Connection error'}`);
      };

      this.socket.onclose = (event) => {
        this.isConnected = false;
        this.onLog(`🔴 WebSocket disconnected (Code: ${event.code}). Auto-reconnecting in 3s...`);
        this.onStatusChange('DISCONNECTED');
        this.reconnectTimer = setTimeout(() => this.connect(), 3000);
      };
    } catch (e) {
      this.onLog(`❌ WebSocket instantiation failure: ${e.message}`);
      this.onStatusChange('FAILED');
    }
  }

  sendAudio(arrayBuffer) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(arrayBuffer);
    }
  }

  sendJson(obj) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(obj));
    }
  }

  sendInterrupt() {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send('INTERRUPT');
      this.onLog('🛑 Sent INTERRUPT signal to HAL server.');
    }
  }
}
