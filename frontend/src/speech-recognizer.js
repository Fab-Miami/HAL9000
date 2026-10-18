/**
 * SpeechRecognizer
 * Uses Web Speech API (webkitSpeechRecognition in Safari/iOS) for zero-latency,
 * on-device speech-to-text. Falls back gracefully when unsupported.
 */

export class SpeechRecognizer {
  constructor({ onFinalSpeech, onInterimSpeech, onStatusChange, onLog }) {
    this.onFinalSpeech = onFinalSpeech || (() => {});
    this.onInterimSpeech = onInterimSpeech || (() => {});
    this.onStatusChange = onStatusChange || (() => {});
    this.onLog = onLog || console.log;

    const SpeechRecognitionClass = window.SpeechRecognition || window.webkitSpeechRecognition;
    this.isSupported = !!SpeechRecognitionClass;
    this.recognition = null;
    this.isListening = false;
    this.isPaused = false;
    this.isActive = false;
    this.isStarting = false;
    this.restartTimeout = null;
    this.interimDebounceTimer = null;
    this.watchdogInterval = null;
    this.accumulatedText = '';
    this.SILENCE_DELAY_MS = 1200; // 1,200ms pause window before dispatching speech

    if (this.isSupported) {
      try {
        this.recognition = new SpeechRecognitionClass();
        this.recognition.continuous = true;
        this.recognition.interimResults = true;
        this.recognition.lang = 'en-US';
        this.recognition.maxAlternatives = 1;
        this._bindEvents();
        this.onLog('🗣️ [SpeechRecognizer] Web Speech API initialized (webkitSpeechRecognition supported).');
      } catch (e) {
        this.onLog(`⚠️ [SpeechRecognizer] Initialization error: ${e.message}`);
        this.isSupported = false;
      }
    } else {
      this.onLog('⚠️ [SpeechRecognizer] Web Speech API not supported in this browser. Fallback to audio VAD.');
    }
  }

  _bindEvents() {
    if (!this.recognition) return;

    this.recognition.onstart = () => {
      this.isActive = true;
      this.isStarting = false;
      this.onLog('🎙️ [SpeechRecognizer] Speech recognition session started.');
      this.onStatusChange('LISTENING');
    };

    this.recognition.onresult = (event) => {
      if (this.isPaused) return;

      let interim = '';
      let finals = '';

      for (let i = event.resultIndex; i < event.results.length; ++i) {
        const item = event.results[i];
        const text = item[0] ? item[0].transcript : '';
        if (item.isFinal) {
          finals += ' ' + text;
        } else {
          interim += ' ' + text;
        }
      }

      if (finals.trim()) {
        this.accumulatedText = (this.accumulatedText + ' ' + finals.trim()).trim();
      }

      const currentLiveSpeech = (this.accumulatedText + ' ' + interim.trim()).trim();
      if (currentLiveSpeech) {
        this.onInterimSpeech(currentLiveSpeech);

        // Unified 1,200ms debounce: Wait for 1.2s of real silence before finalizing thought
        clearTimeout(this.interimDebounceTimer);
        this.interimDebounceTimer = setTimeout(() => {
          this._finalizeSpeech();
        }, this.SILENCE_DELAY_MS);
      }
    };

    this.recognition.onerror = (event) => {
      // 'no-speech' is routine in quiet rooms
      if (event.error === 'no-speech') {
        return;
      }
      this.onLog(`⚠️ [SpeechRecognizer] Error: ${event.error}`);
      if (event.error === 'not-allowed') {
        this.isListening = false;
        this.isActive = false;
        this.onStatusChange('DENIED');
      }
    };

    this.recognition.onend = () => {
      this.isActive = false;
      this.isStarting = false;
      // Automatically maintain continuous listening in Safari without cutting speech
      if (this.isListening && !this.isPaused) {
        clearTimeout(this.restartTimeout);
        this.restartTimeout = setTimeout(() => {
          this._safeStart();
        }, 150);
      } else {
        this._finalizeSpeech();
        this.onStatusChange('IDLE');
      }
    };
  }

  _finalizeSpeech() {
    clearTimeout(this.interimDebounceTimer);
    const speechToSend = this.accumulatedText.trim();
    this.accumulatedText = '';

    if (speechToSend && !this.isPaused) {
      this.onLog(`🗣️ [SpeechRecognizer] Thought complete (1,200ms pause). Sending: "${speechToSend}"`);
      this.onFinalSpeech(speechToSend);
    }
  }

  _safeStart() {
    if (!this.recognition || !this.isListening || this.isPaused) return;
    if (this.isStarting) return;
    this.isStarting = true;
    try {
      this.recognition.start();
      this.isActive = true;
      this.isStarting = false;
    } catch (e) {
      this.isStarting = false;
      if (e.name === 'InvalidStateError') {
        // iOS Safari speech service is still cycling; retry in 250ms
        clearTimeout(this.restartTimeout);
        this.restartTimeout = setTimeout(() => {
          this._safeStart();
        }, 250);
      } else {
        this.onLog(`⚠️ [SpeechRecognizer] Start warning: ${e.message}`);
      }
    }
  }

  start() {
    if (!this.isSupported) return;
    this.isListening = true;
    this.isPaused = false;
    this._safeStart();

    // Watchdog heartbeat: Guarantee speech recognition never hangs or dies silently
    if (!this.watchdogInterval) {
      this.watchdogInterval = setInterval(() => {
        if (this.isListening && !this.isPaused && !this.isActive && !this.isStarting) {
          this.onLog('🔄 [SpeechRecognizer] Watchdog: session inactive while listening. Restarting...');
          this._safeStart();
        }
      }, 2500);
    }
  }

  stop() {
    if (!this.isSupported) return;
    this.isListening = false;
    this.isPaused = false;
    this.isActive = false;
    this.isStarting = false;
    if (this.watchdogInterval) {
      clearInterval(this.watchdogInterval);
      this.watchdogInterval = null;
    }
    clearTimeout(this.restartTimeout);
    clearTimeout(this.interimDebounceTimer);
    try {
      this.recognition.stop();
    } catch (e) {}
  }

  pause() {
    // Mute speech recognition while HAL is actively speaking
    if (!this.isSupported || this.isPaused) return;
    this.isPaused = true;
    this.isActive = false;
    this.isStarting = false;
    clearTimeout(this.interimDebounceTimer);
    this.accumulatedText = '';
    try {
      this.recognition.abort();
    } catch (e) {}
    this.onLog('🔇 [SpeechRecognizer] Muted recognition (HAL output in progress).');
  }

  resume() {
    // Resume listening after HAL finishes speaking
    if (!this.isSupported || !this.isListening) return;
    this.isPaused = false;
    this.accumulatedText = '';
    this.onLog('🎙️ [SpeechRecognizer] Resumed active speech listening.');
    this._safeStart();
  }
}
