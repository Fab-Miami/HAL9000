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
    this.isCooldown = false;
    this.cooldownTimer = null;
    this.ignoreUpToIndex = 0;
    this.isActive = false;
    this.isStarting = false;
    this.restartTimeout = null;
    this.interimDebounceTimer = null;
    this.watchdogInterval = null;
    this.accumulatedText = '';
    this.sleeping = false;
    this.SILENCE_DELAY_MS = 1800; // 1,800ms pause window in conversation; 2,500ms when sleeping

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
      this.ignoreUpToIndex = 0; // Fresh WebKit session, reset result cursor
      this.accumulatedText = '';
      this.onLog('🎙️ [SpeechRecognizer] Speech recognition session started.');
      this.onStatusChange('LISTENING');
    };

    this.recognition.onresult = (event) => {
      // If WebKit recycled its buffer or started a new sub-session
      if (event.resultIndex < this.ignoreUpToIndex) {
        this.ignoreUpToIndex = 0;
      }

      // While HAL is speaking or during 0.5s post-playback acoustic holdoff:
      // discard everything and bump ignoreUpToIndex to ignore all audio played during speech
      if (this.isPaused || this.isCooldown) {
        this.ignoreUpToIndex = event.results.length;
        this.accumulatedText = '';
        clearTimeout(this.interimDebounceTimer);
        return;
      }

      const startIndex = Math.max(event.resultIndex, this.ignoreUpToIndex || 0);
      if (startIndex >= event.results.length) {
        return;
      }

      let interim = '';
      let finals = '';

      for (let i = startIndex; i < event.results.length; ++i) {
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

        // When sleeping, wait for ~2.5s of verified silence after "HAL wake up" before waking.
        // During active conversation, use 1.8s debounce for natural conversational pacing.
        const delay = this.sleeping ? 2500 : this.SILENCE_DELAY_MS;
        clearTimeout(this.interimDebounceTimer);
        this.interimDebounceTimer = setTimeout(() => {
          this._finalizeSpeech();
        }, delay);
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
      this.ignoreUpToIndex = 0; // Session ended, reset cursor for next start
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
    if (this.isPaused || this.isCooldown) {
      this.accumulatedText = '';
      return;
    }
    const speechToSend = this.accumulatedText.trim();
    this.accumulatedText = '';

    if (speechToSend) {
      this.onLog(`🗣️ [SpeechRecognizer] Thought complete (${this.SILENCE_DELAY_MS}ms pause). Sending: "${speechToSend}"`);
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
    try {
      this.recognition.stop();
    } catch (e) {}
  }

  setSleeping(sleeping) {
    this.sleeping = !!sleeping;
    this.accumulatedText = '';
    clearTimeout(this.interimDebounceTimer);
    this.onLog(`🗣️ [SpeechRecognizer] Standby/sleep mode set to: ${this.sleeping} (silence delay: ${this.sleeping ? 2000 : this.SILENCE_DELAY_MS}ms).`);
  }

  pause() {
    // Mute speech recognition while HAL is actively speaking
    // CRITICAL: NEVER call recognition.abort() or recognition.stop() here!
    // In iOS Safari, aborting or stopping speech recognition causes the iOS system to
    // emit an audible system dictation chime ("BEEP BEEP").
    // By keeping recognition running continuously and simply setting isPaused = true,
    // onresult silently ignores speech during HAL audio playback with zero system beeps.
    if (!this.isSupported || this.isPaused) return;
    this.isPaused = true;
    this.isCooldown = false;
    clearTimeout(this.cooldownTimer);
    clearTimeout(this.interimDebounceTimer);
    this.accumulatedText = '';
    this.onLog('🔇 [SpeechRecognizer] Muted recognition (HAL output in progress).');
  }

  resume() {
    // Resume listening after HAL finishes speaking
    if (!this.isSupported) return;
    this.isPaused = false;
    this.isCooldown = true;
    this.accumulatedText = '';
    clearTimeout(this.interimDebounceTimer);
    clearTimeout(this.cooldownTimer);

    // 500ms post-playback holdoff window:
    // Completely suppresses any enclosure acoustic reverberations and trailing WebKit recognition
    this.cooldownTimer = setTimeout(() => {
      this.isCooldown = false;
      this.accumulatedText = '';
      this.onLog('🎙️ [SpeechRecognizer] Holdoff complete (0.5s). Resumed active user listening.');
    }, 500);

    this.onLog('🎙️ [SpeechRecognizer] Audio playback finished. Holding off recognition for 0.5s...');
    // Only start if the session genuinely ended or dropped in the background
    if (this.isListening && !this.isActive && !this.isStarting) {
      this._safeStart();
    }
  }
}
