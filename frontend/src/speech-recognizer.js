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
    this.restartTimeout = null;
    this.interimDebounceTimer = null;
    this.lastInterimText = '';

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
      this.onLog('🎙️ [SpeechRecognizer] Speech recognition session started.');
      this.onStatusChange('LISTENING');
    };

    this.recognition.onresult = (event) => {
      if (this.isPaused) return;

      let interim = '';
      let finalTranscript = '';

      for (let i = event.resultIndex; i < event.results.length; ++i) {
        const item = event.results[i];
        const text = item[0] ? item[0].transcript : '';
        if (item.isFinal) {
          finalTranscript += text;
        } else {
          interim += text;
        }
      }

      // Handle final transcript immediately
      if (finalTranscript.trim()) {
        clearTimeout(this.interimDebounceTimer);
        this.lastInterimText = '';
        const cleanFinal = finalTranscript.trim();
        this.onLog(`🗣️ [SpeechRecognizer] Final transcript recognized: "${cleanFinal}"`);
        this.onFinalSpeech(cleanFinal);
        return;
      }

      // Handle interim updates
      if (interim.trim()) {
        this.lastInterimText = interim.trim();
        this.onInterimSpeech(this.lastInterimText);

        // Safari fallback: if Safari doesn't set isFinal, debounce finalize after 800ms of silence
        clearTimeout(this.interimDebounceTimer);
        this.interimDebounceTimer = setTimeout(() => {
          if (this.lastInterimText && !this.isPaused) {
            const debounced = this.lastInterimText;
            this.lastInterimText = '';
            this.onLog(`⏱️ [SpeechRecognizer] Debounce-finalized interim speech: "${debounced}"`);
            this.onFinalSpeech(debounced);
          }
        }, 800);
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
        this.onStatusChange('DENIED');
      }
    };

    this.recognition.onend = () => {
      clearTimeout(this.interimDebounceTimer);

      // If speech was captured but pending when session ended, flush it
      if (this.lastInterimText && !this.isPaused) {
        const remaining = this.lastInterimText;
        this.lastInterimText = '';
        this.onLog(`🏁 [SpeechRecognizer] Flushed pending speech on session end: "${remaining}"`);
        this.onFinalSpeech(remaining);
      }

      // Automatically maintain continuous listening in Safari
      if (this.isListening && !this.isPaused) {
        clearTimeout(this.restartTimeout);
        this.restartTimeout = setTimeout(() => {
          this._safeStart();
        }, 200);
      } else {
        this.onStatusChange('IDLE');
      }
    };
  }

  _safeStart() {
    if (!this.recognition || !this.isListening || this.isPaused) return;
    try {
      this.recognition.start();
    } catch (e) {
      // If already started or transitioning, ignore
      if (e.name !== 'InvalidStateError') {
        this.onLog(`⚠️ [SpeechRecognizer] Start warning: ${e.message}`);
      }
    }
  }

  start() {
    if (!this.isSupported) return;
    this.isListening = true;
    this.isPaused = false;
    this._safeStart();
  }

  stop() {
    if (!this.isSupported) return;
    this.isListening = false;
    this.isPaused = false;
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
    clearTimeout(this.interimDebounceTimer);
    try {
      this.recognition.abort();
    } catch (e) {}
    this.onLog('🔇 [SpeechRecognizer] Muted recognition (HAL output in progress).');
  }

  resume() {
    // Resume listening after HAL finishes speaking
    if (!this.isSupported || !this.isListening) return;
    this.isPaused = false;
    this.lastInterimText = '';
    this.onLog('🎙️ [SpeechRecognizer] Resumed active speech listening.');
    this._safeStart();
  }
}
