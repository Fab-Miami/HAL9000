/**
 * SpeechRecognizer
 * Uses Web Speech API (webkitSpeechRecognition in Safari/iOS) for zero-latency,
 * on-device speech-to-text. Continuous, chime-free turn-taking loop.
 */

export class SpeechRecognizer {
  constructor({ onFinalSpeech, onInterimSpeech, onStatusChange, onLog, getLastVoiceTime }) {
    this.onFinalSpeech = onFinalSpeech || (() => {});
    this.onInterimSpeech = onInterimSpeech || (() => {});
    this.onStatusChange = onStatusChange || (() => {});
    this.onLog = onLog || console.log;
    this.getLastVoiceTime = getLastVoiceTime || (() => 0);

    const SpeechRecognitionClass = window.SpeechRecognition || window.webkitSpeechRecognition;
    this.isSupported = !!SpeechRecognitionClass;
    this.recognition = null;
    this.isListening = false;
    this.isPaused = false;
    this.isCooldown = false;
    this.cooldownTimer = null;
    this.turnStartIndex = 0;
    this.currentText = '';
    this.isActive = false;
    this.isStarting = false;
    this.restartTimeout = null;
    this.interimDebounceTimer = null;
    this.watchdogInterval = null;
    this.sleeping = false;
    this.SILENCE_DELAY_MS = 1800; // 1,800ms natural conversational pause
    this.lastTextReceivedTime = 0;
    this.latestSnapshotIndex = 0;

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
      this.turnStartIndex = 0;
      this.latestSnapshotIndex = 0;
      this.lastTextReceivedTime = 0;
      this.currentText = '';
      this.onLog('🎙️ [SpeechRecognizer] Speech recognition session started.');
      this.onStatusChange('LISTENING');
    };

    this.recognition.onresult = (event) => {
      // Safety bounds check: only reset if buffer was actually flushed (length < turnStartIndex)
      if (this.turnStartIndex > event.results.length) {
        this.turnStartIndex = 0;
      }

      // While HAL is speaking or during 0.5s post-playback holdoff:
      // discard everything and advance turnStartIndex past any speech heard during output
      if (this.isPaused || this.isCooldown) {
        this.turnStartIndex = event.results.length;
        this.currentText = '';
        clearTimeout(this.interimDebounceTimer);
        return;
      }

      // Read current turn's speech directly from WebKit's results array
      let speech = '';
      for (let i = this.turnStartIndex; i < event.results.length; ++i) {
        const item = event.results[i];
        if (item && item[0] && item[0].transcript) {
          speech += item[0].transcript + ' ';
        }
      }
      speech = speech.trim();

      if (speech) {
        this.currentText = speech;
        this.lastTextReceivedTime = Date.now();
        this.latestSnapshotIndex = event.results.length;
        this.onInterimSpeech(speech);

        // Natural silence debounce: 1.8s during active conversation, 2.5s when in standby
        const delay = this.sleeping ? 2500 : this.SILENCE_DELAY_MS;
        clearTimeout(this.interimDebounceTimer);
        const snapshotIndex = event.results.length;
        this.interimDebounceTimer = setTimeout(() => {
          this._finalizeSpeech(snapshotIndex);
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
      this.turnStartIndex = 0;
      this.currentText = '';
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

  _finalizeSpeech(snapshotIndex) {
    clearTimeout(this.interimDebounceTimer);
    if (this.isPaused || this.isCooldown) {
      this.currentText = '';
      return;
    }

    // Acoustic Voice Activity Verification:
    // If user was speaking acoustically within the required silence window, do NOT finalize!
    // WebKit on iOS batches speech tokens and may delay emitting the next chunk while user speaks.
    const lastVoice = this.getLastVoiceTime();
    if (lastVoice > 0) {
      const elapsedSinceVoice = Date.now() - lastVoice;
      const requiredDelay = this.sleeping ? 2500 : this.SILENCE_DELAY_MS;
      const timeSinceLastText = Date.now() - (this.lastTextReceivedTime || 0);

      // Defer finalization if acoustic speech was detected recently,
      // with a 4.0s timeout on WebKit text stalls to avoid locking on constant ambient noise.
      if (elapsedSinceVoice < requiredDelay && timeSinceLastText < 4000) {
        const waitRemaining = Math.max(150, requiredDelay - elapsedSinceVoice);
        clearTimeout(this.interimDebounceTimer);
        this.interimDebounceTimer = setTimeout(() => {
          this._finalizeSpeech(this.latestSnapshotIndex || snapshotIndex);
        }, waitRemaining);
        return;
      }
    }

    const speechToSend = this.currentText.trim();
    this.currentText = '';
    const finalIndex = typeof snapshotIndex === 'number' ? Math.max(snapshotIndex, this.latestSnapshotIndex || 0) : this.latestSnapshotIndex;
    if (typeof finalIndex === 'number' && finalIndex > 0) {
      this.turnStartIndex = finalIndex;
    }

    if (speechToSend) {
      this.onLog(`🗣️ [SpeechRecognizer] Speech finalized (${this.SILENCE_DELAY_MS}ms pause). Sending: "${speechToSend}"`);
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
    this.currentText = '';
    clearTimeout(this.interimDebounceTimer);
    this.onLog(`🗣️ [SpeechRecognizer] Standby/sleep mode set to: ${this.sleeping} (silence delay: ${this.sleeping ? 2500 : this.SILENCE_DELAY_MS}ms).`);
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
    this.currentText = '';
    this.lastTextReceivedTime = 0;
    this.onLog('🔇 [SpeechRecognizer] Muted recognition (HAL output in progress).');
  }

  resume() {
    // Resume listening after HAL finishes speaking
    if (!this.isSupported) return;
    this.isPaused = false;
    this.isCooldown = true;
    this.currentText = '';
    this.lastTextReceivedTime = 0;
    clearTimeout(this.interimDebounceTimer);
    clearTimeout(this.cooldownTimer);

    // 500ms post-playback holdoff window:
    // Completely suppresses room reverberations and audio pipeline latency
    this.cooldownTimer = setTimeout(() => {
      this.isCooldown = false;
      this.currentText = '';
      this.onLog('🎙️ [SpeechRecognizer] Holdoff complete (0.5s). Resumed active user listening.');
    }, 500);

    this.onLog('🎙️ [SpeechRecognizer] Audio playback finished. Holding off recognition for 0.5s...');
    // Only start if the session genuinely ended or dropped in the background
    if (this.isListening && !this.isActive && !this.isStarting) {
      this._safeStart();
    }
  }
}
