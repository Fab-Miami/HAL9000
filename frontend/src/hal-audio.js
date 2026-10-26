/**
 * HAL 9000 Unified Web Audio Engine
 * Coordinates microphone capture, 16kHz downsampling, vocal RMS metering,
 * 1.8s turn-taking VAD, and 24kHz Kokoro TTS playback in a single cohesive graph.
 */

export class HalAudio {
  constructor({ onAudioLevel, onPlaybackLevel, onTurnComplete, onPlaybackStateChange, onWake, onStandbyDispatch, onLog }) {
    this.onAudioLevel = onAudioLevel || (() => {});
    this.onPlaybackLevel = onPlaybackLevel || (() => {});
    this.onTurnComplete = onTurnComplete || (() => {});
    this.onPlaybackStateChange = onPlaybackStateChange || (() => {});
    this.onWake = onWake || (() => {});
    this.onStandbyDispatch = onStandbyDispatch || (() => {});
    this.onLog = onLog || console.log;

    this.audioContext = null;
    this.mediaStream = null;
    this.sourceNode = null;
    this.scriptNode = null;
    this.gainNode = null;
    this.analyserNode = null;

    // Recording & Turn-Taking State
    this.isRecording = false;
    this.isListeningActive = true;
    this.isPlaying = false;
    this.isSpeaking = false;
    this.sleeping = false;
    this.turnBuffer = [];
    this.preRollBuffer = [];
    this.lastVoiceTime = 0;
    this.standbySilenceStart = performance.now();
    this.noiseFloor = undefined;
    this.SILENCE_DELAY_MS = 1800; // Strict 1.8s natural conversational pause

    // Playback State
    this.volumeLevel = 5; // 1-10 scale (default 5 = unity gain 1.0)
    this.scheduledTime = 0;
    this.activeSources = [];
    this.streamFinished = false;
    this.playbackMeterInterval = null;
    this.playbackEndTime = 0;
    this.speechActiveDuration = 0;

  }

  async initialize() {
    if (!this.audioContext) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      this.audioContext = new AudioContextClass();

      // Output Gain & Visual Analyser
      this.gainNode = this.audioContext.createGain();
      this._applyVolume();

      this.analyserNode = this.audioContext.createAnalyser();
      this.analyserNode.fftSize = 256;
      this.analyserNode.smoothingTimeConstant = 0.4;

      this.gainNode.connect(this.analyserNode);
      this.analyserNode.connect(this.audioContext.destination);

      this._startPlaybackMeter();
    }

    if (this.audioContext.state === 'suspended') {
      await this.audioContext.resume();
    }

    // Play 1-sample silent buffer to unlock iOS Safari Web Audio hardware pipeline
    const silentBuffer = this.audioContext.createBuffer(1, 1, 24000);
    const silentSource = this.audioContext.createBufferSource();
    silentSource.buffer = silentBuffer;
    silentSource.connect(this.gainNode);
    silentSource.start();

    // Acquire microphone stream
    if (!this.mediaStream) {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
    }

    this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);
    // Buffer size 4096 gives ~85ms chunks at 48kHz
    this.scriptNode = this.audioContext.createScriptProcessor(4096, 1, 1);

    this.scriptNode.onaudioprocess = (event) => this._handleInputAudio(event);

    this.sourceNode.connect(this.scriptNode);
    this.scriptNode.connect(this.audioContext.destination);

    // CRITICAL FOR IOS SAFARI: Anchor scriptNode to window to prevent WebKit GC
    window._halAudioScriptNode = this.scriptNode;

    this.isRecording = true;
    this.onLog('🎙️ [HalAudio] Web Audio pipeline operational (16kHz capture, 1.8s turn-taking, 24kHz output).');
  }

  setVolume(level) {
    this.volumeLevel = Math.max(1, Math.min(10, level));
    this._applyVolume();
    this.onLog(`🔊 [HalAudio] Volume adjusted to: ${this.volumeLevel}/10`);
  }

  _applyVolume() {
    if (this.gainNode && this.audioContext) {
      // Map 1-10 to linear gain: Level 5 = 1.0, Level 10 = 2.0, Level 1 = 0.2
      const gainVal = this.volumeLevel / 5.0;
      this.gainNode.gain.setValueAtTime(gainVal, this.audioContext.currentTime);
    }
  }

  setSleeping(sleeping) {
    this.sleeping = !!sleeping;
    if (this.sleeping) {
      this.turnBuffer = [];
      this.preRollBuffer = [];
      this.isSpeaking = false;
      this.consecutiveVoiceFrames = 0;
      this.standbySilenceStart = performance.now();
    } else {
      this.lastHalSpeechTime = performance.now();
      this.activeSilenceStart = performance.now();
    }
    this.onLog(`🌙 [HalAudio] Standby mode set to: ${this.sleeping} (Sandwich: >=0.5s silence -> <=3.5s speech -> 1.0s silence).`);
  }

  notifySpeechFinished() {
    this.lastHalSpeechTime = performance.now();
    this.activeSilenceStart = performance.now();
  }

  setListeningActive(active) {
    this.isListeningActive = !!active;
    if (this.isListeningActive) {
      if (this.sleeping) {
        this.standbySilenceStart = performance.now();
      }
      // Ensure AudioContext is actively running and not suspended by iOS
      if (this.audioContext && this.audioContext.state === 'suspended') {
        this.audioContext.resume().catch(() => {});
      }
    } else {
      this.turnBuffer = [];
      this.preRollBuffer = [];
      this.isSpeaking = false;
      this.onAudioLevel(0.0);
    }
  }

  // =========================================================================
  // INPUT PROCESSING: RMS METERING & 1.8s TURN-TAKING VAD
  // =========================================================================
  _handleInputAudio(event) {
    if (!this.isRecording || !this.isListeningActive) return;

    const inputData = event.inputBuffer.getChannelData(0);
    const sampleRate = this.audioContext.sampleRate;

    // Downsample input from native rate (44.1/48kHz) to 16kHz
    const downsampled = this._downsampleTo16k(inputData, sampleRate);
    if (!downsampled || downsampled.length === 0) return;

    // Convert Float32 to 16-bit PCM (Little-Endian) & compute RMS
    const pcmChunk = new Int16Array(downsampled.length);
    let sum = 0;
    let maxPeak = 0;

    for (let i = 0; i < downsampled.length; i++) {
      const s = Math.max(-1, Math.min(1, downsampled[i]));
      const absVal = Math.abs(s);
      if (absVal > maxPeak) maxPeak = absVal;
      pcmChunk[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      sum += s * s;
    }

    const rms = Math.sqrt(sum / downsampled.length);

    // =======================================================================
    // PHYSICAL MUTING DURING HAL PLAYBACK & 400ms ACOUSTIC REVERB DECAY
    // =======================================================================
    if (this.isPlaying || (performance.now() - this.playbackEndTime < 400)) {
      // Audio capture is strictly MUTED so HAL never hears his own voice.
      return;
    }

    // =======================================================================
    // AUTO-ADAPTIVE ACOUSTIC NOISE BASELINE (Asymmetric Leaky Minimum Follower)
    // Seamlessly adapts to quiet rooms, air conditioning, and room rumble.
    // =======================================================================
    if (this.noiseFloor === undefined) {
      this.noiseFloor = Math.max(0.0010, rms);
    } else {
      if (this.isSpeaking) {
        // PRINCIPLE 1: SPEECH INHIBIT
        // When speech is actively in progress, FREEZE upward tracking completely.
        // Never allow user speech or dialogue to drag the ambient floor upward!
        if (rms < this.noiseFloor) {
          this.noiseFloor = this.noiseFloor * 0.98 + rms * 0.02;
        }
      } else {
        // PRINCIPLE 2: ASYMMETRIC AMBIENT TRACKING
        if (rms < this.noiseFloor) {
          // Noise dropped (AC turned off, room quieted):
          // Fast descent (~1.5s recovery) to restore sensitivity immediately.
          this.noiseFloor = this.noiseFloor * 0.92 + rms * 0.08;
        } else {
          // Noise rose (AC turned on, fan running):
          // Adapt SLOWLY upwards (~10-15s time constant).
          // If it's a huge transient spike (> 3.5x baseline), don't treat it as baseline yet.
          const creepRate = (rms > this.noiseFloor * 3.5) ? 0.0005 : 0.0025;
          this.noiseFloor = this.noiseFloor * (1.0 - creepRate) + rms * creepRate;
        }
      }
      // Calibrated physical noise floor baseline (never drop below 0.0025)
      if (this.noiseFloor < 0.0025) this.noiseFloor = 0.0025;
    }

    // =======================================================================
    // DYNAMIC SIGNAL-TO-NOISE RATIO (SNR) VOICE GATE
    // Calibrated for Miami Beach apartment console behind sealed glass enclosure:
    // Standby: baseGateFloor 0.0120 (drops room air/TV; real wake word is >= 0.017-0.050)
    // Active: baseGateFloor 0.0085 (drops room ambient 0.002-0.004; real speech is >= 0.015-0.045)
    // =======================================================================
    const snrMultiplier = this.sleeping ? 1.85 : 1.60;
    const safetyMargin = this.sleeping ? 0.0050 : 0.0035;
    const baseGateFloor = this.sleeping ? 0.0120 : 0.0085;
    const voiceGate = Math.max(baseGateFloor, this.noiseFloor * snrMultiplier + safetyMargin);

    const voiceDelta = rms - voiceGate;
    const ringLevel = (voiceDelta > 0)
      ? Math.min(1.0, 0.35 + (voiceDelta / (this.noiseFloor * 2.0 + 0.01)) * 0.65)
      : 0.0;

    // Real-time optical pulse of the outer acoustic ring (#layer-ring-on)
    // STRICT MANDATE: Acoustic ring only pulses during active conversation (State.LISTENING).
    // In standby / sleeping mode, all optical LEDs are strictly OFF (0.0 opacity).
    if (!this.sleeping) {
      this.onAudioLevel(ringLevel);
    } else {
      this.onAudioLevel(0.0);
    }

    const now = performance.now();
    const hasVocalEnergy = ringLevel > 0;

    if (this.sleeping) {
      // =====================================================================
      // STANDBY SANDWICH PROFILE VAD:
      // 1. Preceding continuous silence >= 750ms
      // 2. Spoken wake utterance <= 3.5s
      // 3. Trailing silence == 800ms
      // =====================================================================
      if (hasVocalEnergy) {
        if (!this.isSpeaking) {
          const silenceDuration = now - this.standbySilenceStart;
          if (silenceDuration < 500) {
            // Preceding continuous silence not met (< 500ms). Reset timer and log (throttled).
            if (now - (this.lastSilenceRejectLog || 0) > 1500) {
              this.onLog(`🥪 [Standby Sandwich] Audio above gate (RMS: ${rms.toFixed(4)}, Gate: ${voiceGate.toFixed(4)}), but preceding silence was only ${silenceDuration.toFixed(0)}ms (< 500ms). Resetting silence window.`);
              this.lastSilenceRejectLog = now;
            }
            this.standbySilenceStart = now;
            this.consecutiveVoiceFrames = 0;
            return;
          }

          this.consecutiveVoiceFrames = (this.consecutiveVoiceFrames || 0) + 1;
          // Require 2 consecutive frames (~170ms) of sustained vocal energy to confirm intentional speech onset
          if (this.consecutiveVoiceFrames >= 2) {
            this.isSpeaking = true;
            this.turnStartTime = now;
            this.lastVoiceTime = now;
            this.onLog(`🗣️ [HalAudio] Standby speech onset detected (RMS: ${rms.toFixed(4)}, Floor: ${this.noiseFloor.toFixed(4)}, Gate: ${voiceGate.toFixed(4)}).`);
            this.turnBuffer = [];
            for (let i = 0; i < this.preRollBuffer.length; i++) {
              this.turnBuffer.push(this.preRollBuffer[i]);
            }
            this.preRollBuffer = [];
            this.turnBuffer.push(pcmChunk);
          } else {
            this.preRollBuffer.push(pcmChunk);
            if (this.preRollBuffer.length > 6) {
              this.preRollBuffer.shift();
            }
          }
        } else {
          // Already speaking in standby
          this.lastVoiceTime = now;
          this.turnBuffer.push(pcmChunk);
          const utteranceDuration = now - this.turnStartTime;
          // Sandwich rule #2: utterance cap at 3.5s (relaxed so natural phrasing is never cut off)
          if (utteranceDuration >= 3500) {
            this.onLog(`🔇 [HalAudio] Standby utterance exceeded 3.5s (${(utteranceDuration / 1000).toFixed(2)}s). Discarding non-wake audio.`);
            this.turnBuffer = [];
            this.preRollBuffer = [];
            this.isSpeaking = false;
            this.consecutiveVoiceFrames = 0;
            this.standbySilenceStart = now;
            return;
          }
        }
      } else {
        // hasVocalEnergy is FALSE in standby
        if (this.isSpeaking) {
          this.turnBuffer.push(pcmChunk);
          const elapsedSinceVoice = now - this.lastVoiceTime;
          // Sandwich rule #3: trailing silence >= 1000ms
          const requiredDelay = this.sleeping ? 1000 : this.SILENCE_DELAY_MS;
          if (elapsedSinceVoice >= requiredDelay) {
            const spokenDuration = (this.lastVoiceTime - this.turnStartTime) / 1000;
            // CRITICAL DEFENSE: Drop phantom blips (< 0.40s) in standby right on the phone
            if (this.sleeping && spokenDuration < 0.40) {
              this.onLog(`🔇 [HalAudio] Standby phantom blip discarded (spoken: ${spokenDuration.toFixed(2)}s < 0.40s).`);
              this.turnBuffer = [];
              this.preRollBuffer = [];
              this.isSpeaking = false;
              this.consecutiveVoiceFrames = 0;
              this.standbySilenceStart = performance.now();
              return;
            }
            this.onLog(`🥪 [HalAudio] Sandwich profile matched! Spoken turn: ${spokenDuration.toFixed(2)}s, trailing silence: ${(elapsedSinceVoice / 1000).toFixed(2)}s.`);
            this._finalizeTurn(elapsedSinceVoice);
            this.standbySilenceStart = performance.now();
          }
        } else {
          // Ambient quiet in standby
          if (this.consecutiveVoiceFrames > 0) {
            // A 1-frame transient noise occurred and vanished; reset silence baseline
            this.standbySilenceStart = now;
            this.consecutiveVoiceFrames = 0;
          }
          this.preRollBuffer.push(pcmChunk);
          if (this.preRollBuffer.length > 6) {
            this.preRollBuffer.shift();
          }
        }
      }
    } else {
      // =====================================================================
      // ACTIVE CONVERSATION TURN-TAKING & 1.8s SILENCE DETECTION
      // =====================================================================
      if (hasVocalEnergy) {
        this.consecutiveVoiceFrames = (this.consecutiveVoiceFrames || 0) + 1;
        if (!this.isSpeaking) {
          // DIRECTED ADDRESSING PROTOCOL: 20s Grace Period & 1.8s Pre-Speech Silence Gate
          const timeSinceLastSpeech = now - (this.lastHalSpeechTime || 0);
          const isGracePeriod = timeSinceLastSpeech <= 20000;
          const preSilence = now - (this.activeSilenceStart || now);

          if (!isGracePeriod && preSilence < 1800) {
            // In idle mode, require at least 1.8s of silence before speech onset to ignore mid-sentence room/phone chatter
            this.activeSilenceStart = now;
            this.consecutiveVoiceFrames = 0;
            return;
          }

          if (this.consecutiveVoiceFrames >= 2) {
            this.isSpeaking = true;
            this.turnStartTime = now;
            this.onLog(`🗣️ [HalAudio] User speech detected (RMS: ${rms.toFixed(4)}, Floor: ${this.noiseFloor.toFixed(4)}, Gate: ${voiceGate.toFixed(4)}, Grace: ${isGracePeriod ? 'YES' : 'NO'}).`);
            this.turnBuffer = [];
            for (let i = 0; i < this.preRollBuffer.length; i++) {
              this.turnBuffer.push(this.preRollBuffer[i]);
            }
            this.preRollBuffer = [];
            this.lastVoiceTime = now;
            this.turnBuffer.push(pcmChunk);
          } else {
            this.preRollBuffer.push(pcmChunk);
            if (this.preRollBuffer.length > 6) {
              this.preRollBuffer.shift();
            }
          }
        } else {
          this.lastVoiceTime = now;
          this.turnBuffer.push(pcmChunk);
          // Active conversation protection: cap maximum turn duration at 25s
          if (now - this.turnStartTime >= 25000) {
            this._finalizeTurn(200);
            return;
          }
        }
      } else {
        this.consecutiveVoiceFrames = 0;
        if (this.isSpeaking) {
          this.turnBuffer.push(pcmChunk);
          const elapsedSinceVoice = now - this.lastVoiceTime;
          if (elapsedSinceVoice >= this.SILENCE_DELAY_MS) {
            this._finalizeTurn(elapsedSinceVoice);
            this.activeSilenceStart = performance.now();
          }
        } else {
          if (!this.activeSilenceStart) {
            this.activeSilenceStart = now;
          }
          this.preRollBuffer.push(pcmChunk);
          if (this.preRollBuffer.length > 6) {
            this.preRollBuffer.shift();
          }
        }
      }
    }
  }

  _finalizeTurn(elapsedSinceVoice = 1800) {
    try {
      this.isSpeaking = false;
      this.isListeningActive = false; // Immediately disable listening while HAL thinks and speaks
      this.onAudioLevel(0.0);

      if (this.turnBuffer.length === 0) return;

      // Concatenate all Int16 chunks
      let totalSamples = 0;
      for (let i = 0; i < this.turnBuffer.length; i++) {
        totalSamples += this.turnBuffer[i].length;
      }

      let fullPcm = new Int16Array(totalSamples);
      let offset = 0;
      for (let i = 0; i < this.turnBuffer.length; i++) {
        fullPcm.set(this.turnBuffer[i], offset);
        offset += this.turnBuffer[i].length;
      }
      this.turnBuffer = [];

      // Trim trailing dead silence from buffer, keeping a clean cushion
      const cushionMs = this.sleeping ? 100 : 150;
      const trimMs = Math.max(0, elapsedSinceVoice - cushionMs);
      const trimSamples = Math.floor(trimMs * 16); // 16 samples per ms at 16kHz
      if (trimSamples > 0 && fullPcm.length > trimSamples + 4800) {
        fullPcm = fullPcm.subarray(0, fullPcm.length - trimSamples);
      }

      const durationSeconds = fullPcm.length / 16000;
      const minDuration = this.sleeping ? 0.35 : 0.45;
      if (durationSeconds < minDuration) {
        this.onLog(`🔇 [HalAudio] Discarded brief noise glitch (${durationSeconds.toFixed(2)}s).`);
        this.isListeningActive = true;
        if (this.sleeping) {
          this.standbySilenceStart = performance.now();
        }
        return;
      }

      // Standby safety watchdog: automatically re-arm listening if no speech/playback occurs within 3.5s
      if (this.sleeping) {
        clearTimeout(this._standbySafetyWatchdog);
        this._standbySafetyWatchdog = setTimeout(() => {
          if (!this.isPlaying && this.sleeping) {
            this.isListeningActive = true;
            this.standbySilenceStart = performance.now();
          }
        }, 3500);

        // Blinks the 3 auxiliary LEDs as immediate visual dispatch feedback
        this.onStandbyDispatch();
      }

      // Package into clean WAV container for Gemini / Whisper
      const wavBytes = this._pcmToWav(fullPcm, 16000);
      this.onLog(`🗣️ [HalAudio] Turn finalized (${durationSeconds.toFixed(1)}s speech audio, ${wavBytes.byteLength} bytes). Dispatching.`);
      this.onTurnComplete(wavBytes);
    } catch (e) {
      this.onLog(`❌ [HalAudio] Turn finalization error: ${e.message}`);
    }
  }

  // =========================================================================
  // PLAYBACK: 24kHz KOKORO TTS STREAMING & VISUAL EYE PULSE
  // =========================================================================
  playChunk(arrayBuffer) {
    if (!this.audioContext) return;
    if (this.audioContext.state === 'suspended') {
      this.audioContext.resume();
    }

    const int16Array = new Int16Array(arrayBuffer);
    if (int16Array.length === 0) return;

    const float32Array = new Float32Array(int16Array.length);
    for (let i = 0; i < int16Array.length; i++) {
      float32Array[i] = int16Array[i] / 32768.0;
    }

    const audioBuffer = this.audioContext.createBuffer(1, float32Array.length, 24000);
    audioBuffer.getChannelData(0).set(float32Array);

    const source = this.audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(this.gainNode);

    const currentTime = this.audioContext.currentTime;
    if (this.scheduledTime < currentTime) {
      this.scheduledTime = currentTime;
    }

    source.start(this.scheduledTime);
    this.scheduledTime += audioBuffer.duration;
    this.activeSources.push(source);
    this.streamFinished = false;

    if (!this.isPlaying) {
      this.isPlaying = true;
      this.onPlaybackStateChange(true);
    }

    // Safety Watchdog: If no new chunk arrives within 2.5s and all active sources finished,
    // automatically unfreeze isPlaying so HAL never stays stuck in playback!
    if (this._playbackWatchdog) clearTimeout(this._playbackWatchdog);
    this._playbackWatchdog = setTimeout(() => {
      if (this.isPlaying && this.activeSources.length === 0) {
        this.onLog('⚠️ [HalAudio] Watchdog: Recovered from unfinalized playback state.');
        this.isPlaying = false;
        this.scheduledTime = 0;
        this.playbackEndTime = performance.now();
        this.turnBuffer = [];
        this.preRollBuffer = [];
        this.isSpeaking = false;
        this.onPlaybackStateChange(false);
      }
    }, 2500);

    source.onended = () => {
      const idx = this.activeSources.indexOf(source);
      if (idx > -1) {
        this.activeSources.splice(idx, 1);
      }

      if (this.streamFinished && this.activeSources.length === 0) {
        this.isPlaying = false;
        this.scheduledTime = 0;
        this.playbackEndTime = performance.now();
        this.turnBuffer = [];
        this.preRollBuffer = [];
        this.isSpeaking = false;
        this.onPlaybackStateChange(false);
      }
    };
  }

  finishStream() {
    if (this._playbackWatchdog) clearTimeout(this._playbackWatchdog);
    this.streamFinished = true;
    if (this.activeSources.length === 0) {
      const wasPlaying = this.isPlaying;
      this.isPlaying = false;
      this.scheduledTime = 0;
      this.playbackEndTime = performance.now();
      this.turnBuffer = [];
      this.preRollBuffer = [];
      this.isSpeaking = false;
      if (wasPlaying) {
        this.onPlaybackStateChange(false);
      }
    } else {
      const remainingMs = Math.max(100, Math.round(((this.scheduledTime - (this.audioContext ? this.audioContext.currentTime : 0)) * 1000) + 200));
      setTimeout(() => {
        if (this.isPlaying && this.activeSources.length === 0) {
          this.isPlaying = false;
          this.scheduledTime = 0;
          this.playbackEndTime = performance.now();
          this.turnBuffer = [];
          this.preRollBuffer = [];
          this.isSpeaking = false;
          this.onPlaybackStateChange(false);
        }
      }, remainingMs);
    }
  }

  stopPlayback() {
    if (this._playbackWatchdog) clearTimeout(this._playbackWatchdog);
    this.streamFinished = true;
    this.playbackEndTime = performance.now();
    for (let i = 0; i < this.activeSources.length; i++) {
      try {
        this.activeSources[i].stop();
        this.activeSources[i].disconnect();
      } catch (e) {}
    }
    this.activeSources = [];
    this.scheduledTime = 0;
    this.turnBuffer = [];
    this.preRollBuffer = [];
    this.isSpeaking = false;

    if (this.isPlaying) {
      this.isPlaying = false;
      this.onPlaybackStateChange(false);
    }
  }

  _startPlaybackMeter() {
    if (this.playbackMeterInterval) return;
    const dataArray = new Uint8Array(this.analyserNode.frequencyBinCount);

    this.playbackMeterInterval = setInterval(() => {
      if (!this.isPlaying || !this.analyserNode) {
        this.onPlaybackLevel(0);
        return;
      }

      this.analyserNode.getByteTimeDomainData(dataArray);
      let sum = 0;
      for (let i = 0; i < dataArray.length; i++) {
        const val = (dataArray[i] - 128) / 128.0;
        sum += val * val;
      }
      const rms = Math.sqrt(sum / dataArray.length);
      const intensity = Math.min(1.0, rms * 4.0);
      this.onPlaybackLevel(intensity);
    }, 30);
  }

  // =========================================================================
  // AUDIO CONVERSION UTILITIES
  // =========================================================================
  _downsampleTo16k(inputData, inputSampleRate) {
    if (inputSampleRate === 16000) return inputData;
    const ratio = inputSampleRate / 16000;
    const newLength = Math.round(inputData.length / ratio);
    const result = new Float32Array(newLength);

    let offsetResult = 0;
    let offsetBuffer = 0;

    while (offsetResult < result.length) {
      const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
      let accum = 0;
      let count = 0;

      for (let i = offsetBuffer; i < nextOffsetBuffer && i < inputData.length; i++) {
        accum += inputData[i];
        count++;
      }

      result[offsetResult] = count > 0 ? accum / count : 0;
      offsetResult++;
      offsetBuffer = nextOffsetBuffer;
    }
    return result;
  }

  _pcmToWav(int16Array, sampleRate = 16000) {
    const numChannels = 1;
    const bitsPerSample = 16;
    const byteRate = sampleRate * numChannels * (bitsPerSample / 8);
    const blockAlign = numChannels * (bitsPerSample / 8);
    const dataByteCount = int16Array.length * 2;
    const headerByteCount = 44;
    const buffer = new ArrayBuffer(headerByteCount + dataByteCount);
    const view = new DataView(buffer);

    // RIFF chunk descriptor
    this._writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + dataByteCount, true);
    this._writeString(view, 8, 'WAVE');

    // fmt sub-chunk
    this._writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true); // Subchunk1Size (16 for PCM)
    view.setUint16(20, 1, true);  // AudioFormat (1 for PCM)
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, byteRate, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, bitsPerSample, true);

    // data sub-chunk
    this._writeString(view, 36, 'data');
    view.setUint32(40, dataByteCount, true);

    // Copy 16-bit PCM samples with exact byteOffset & byteLength
    const pcmDataView = new Uint8Array(buffer, 44);
    pcmDataView.set(new Uint8Array(int16Array.buffer, int16Array.byteOffset, int16Array.byteLength));

    return buffer;
  }

  _writeString(view, offset, string) {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  }
}
