/**
 * HAL 9000 Unified Web Audio Engine
 * Coordinates microphone capture, 16kHz downsampling, vocal RMS metering,
 * 1.8s turn-taking VAD, and 24kHz Kokoro TTS playback in a single cohesive graph.
 */

export class HalAudio {
  constructor({ onAudioLevel, onPlaybackLevel, onTurnComplete, onPlaybackStateChange, onBargeIn, onWake, onLog }) {
    this.onAudioLevel = onAudioLevel || (() => {});
    this.onPlaybackLevel = onPlaybackLevel || (() => {});
    this.onTurnComplete = onTurnComplete || (() => {});
    this.onPlaybackStateChange = onPlaybackStateChange || (() => {});
    this.onBargeIn = onBargeIn || (() => {});
    this.onWake = onWake || (() => {});
    this.onLog = onLog || console.log;

    this.audioContext = null;
    this.mediaStream = null;
    this.sourceNode = null;
    this.scriptNode = null;
    this.gainNode = null;
    this.analyserNode = null;

    // Recording & Turn-Taking State
    this.isRecording = false;
    this.isPlaying = false;
    this.isSpeaking = false;
    this.sleeping = false;
    this.turnBuffer = [];
    this.preRollBuffer = [];
    this.lastVoiceTime = 0;
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

    // Enclosure Tap Detection in Standby
    this.firstTapTime = 0;
    this.firstTapPeak = 0;
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
    this.turnBuffer = [];
    this.isSpeaking = false;
    this.onLog(`🌙 [HalAudio] Standby mode set to: ${this.sleeping} (Silence delay: ${this.sleeping ? 2500 : this.SILENCE_DELAY_MS}ms).`);
  }

  // =========================================================================
  // INPUT PROCESSING: RMS METERING & 1.8s TURN-TAKING VAD
  // =========================================================================
  _handleInputAudio(event) {
    if (!this.isRecording) return;

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
    // PHYSICAL MUTING DURING HAL PLAYBACK & 300ms ACOUSTIC REVERB DECAY
    // =======================================================================
    if (this.isPlaying || (performance.now() - this.playbackEndTime < 300)) {
      // Audio capture is strictly MUTED so HAL never hears his own voice.
      // Eliminates 100% of self-interruption, acoustic feedback, and echo loops.
      // Physical barge-in is handled via accelerometer knocks on the chassis.
      return;
    }

    // Dynamic noise floor tracking (EMA)
    if (this.noiseFloor === undefined) {
      this.noiseFloor = rms;
    } else {
      if (rms < this.noiseFloor) {
        this.noiseFloor = this.noiseFloor * 0.95 + rms * 0.05;
      } else {
        this.noiseFloor = this.noiseFloor * 0.995 + rms * 0.005;
      }
    }

    // Calibrated sensitivity for iPhone behind glass inside monolith enclosure
    const noiseGate = Math.max(0.005, this.noiseFloor * 1.25 + 0.003);
    const voiceDelta = rms - noiseGate;

    // =======================================================================
    // UNIFIED RING LEVEL FACTOR (0.0 = OFF / SILENCE, 0.40 - 1.0 = ACTIVE SPEECH)
    // Both optical feedback and turn-taking VAD are connected to this EXACT factor!
    // =======================================================================
    const ringLevel = (voiceDelta > 0.0007)
      ? Math.min(1.0, 0.40 + (voiceDelta - 0.0007) * 45.0)
      : 0.0;

    // Real-time optical pulse of the outer acoustic ring (#layer-ring-on)
    this.onAudioLevel(ringLevel);

    // =======================================================================
    // STANDBY DOUBLE-TAP ACOUSTIC WAKE DETECTION
    // =======================================================================
    if (this.sleeping) {
      const now = performance.now();
      const crestFactor = maxPeak / (rms + 0.0001);
      const isImpulse = (maxPeak > 0.20 && crestFactor > 2.6) || (maxPeak > 0.35 && (rms - this.noiseFloor) > 0.04);

      if (isImpulse) {
        const timeSinceFirstTap = now - this.firstTapTime;
        if (this.firstTapTime > 0 && timeSinceFirstTap >= 140 && timeSinceFirstTap <= 850) {
          const peakRatio = Math.min(this.firstTapPeak, maxPeak) / Math.max(this.firstTapPeak, maxPeak);
          if (peakRatio >= 0.40) {
            this.onLog(`🥁 [HalAudio] Verified DOUBLE TAP on enclosure! (Interval: ${Math.round(timeSinceFirstTap)}ms, Match: ${(peakRatio * 100).toFixed(0)}%). Waking HAL.`);
            this.firstTapTime = 0;
            this.firstTapPeak = 0;
            this.onWake('double_tap');
            return;
          } else {
            this.firstTapTime = now;
            this.firstTapPeak = maxPeak;
          }
        } else if (timeSinceFirstTap > 850 || this.firstTapTime === 0) {
          this.firstTapTime = now;
          this.firstTapPeak = maxPeak;
        }
      } else if (this.firstTapTime > 0 && (now - this.firstTapTime) > 850) {
        this.firstTapTime = 0;
        this.firstTapPeak = 0;
      }

      // In standby, stream wake turn if voice exceeds threshold ("HAL wake up")
      if (voiceDelta <= 0.012 && !this.isSpeaking) {
        return;
      }
    }

    // =======================================================================
    // TURN-TAKING ACCUMULATION & 1.8s SILENCE DETECTION
    // Synchronized 100% to the exact same acoustic factor as the optical ring:
    // When the acoustic ring is blinking (ringLevel > 0), speech is active!
    // When the acoustic ring turns off (ringLevel === 0), the 1.8s silence countdown begins.
    // =======================================================================
    const now = performance.now();
    const hasVocalEnergy = ringLevel > 0;

    if (hasVocalEnergy) {
      if (!this.isSpeaking) {
        this.isSpeaking = true;
        this.onLog('🗣️ [HalAudio] User speech detected (Turn started).');
        this.turnBuffer = [];
        // Prepend rolling pre-roll buffer (0.3s) so onset consonant is preserved
        for (let i = 0; i < this.preRollBuffer.length; i++) {
          this.turnBuffer.push(this.preRollBuffer[i]);
        }
        this.preRollBuffer = [];
      }
      this.lastVoiceTime = now;
      this.turnBuffer.push(pcmChunk);
    } else {
      if (this.isSpeaking) {
        // Accumulating silence tail
        this.turnBuffer.push(pcmChunk);
        const elapsedSinceVoice = now - this.lastVoiceTime;
        const requiredDelay = this.sleeping ? 2500 : this.SILENCE_DELAY_MS;

        if (elapsedSinceVoice >= requiredDelay) {
          // 1.8s (or 2.5s) of natural silence elapsed -> Finalize turn!
          this._finalizeTurn(elapsedSinceVoice);
        }
      } else {
        // Ambient silence: keep rolling 0.3s pre-roll buffer (~4 chunks)
        this.preRollBuffer.push(pcmChunk);
        if (this.preRollBuffer.length > 4) {
          this.preRollBuffer.shift();
        }
      }
    }
  }

  _finalizeTurn(elapsedSinceVoice = 1800) {
    try {
      this.isSpeaking = false;
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

      // Trim trailing dead silence from buffer, keeping a clean 0.15s cushion
      const trimMs = Math.max(0, elapsedSinceVoice - 150);
      const trimSamples = Math.floor(trimMs * 16); // 16 samples per ms at 16kHz
      if (trimSamples > 0 && fullPcm.length > trimSamples + 4800) {
        fullPcm = fullPcm.subarray(0, fullPcm.length - trimSamples);
      }

      const durationSeconds = fullPcm.length / 16000;
      // Package into clean WAV container for Gemini
      const wavBytes = this._pcmToWav(fullPcm, 16000);
      this.onLog(`🗣️ [HalAudio] Turn finalized (${durationSeconds.toFixed(1)}s speech audio, ${wavBytes.byteLength} bytes). Dispatching to Gemini.`);
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
    this.streamFinished = true;
    if (this.activeSources.length === 0) {
      this.isPlaying = false;
      this.scheduledTime = 0;
      this.playbackEndTime = performance.now();
      this.turnBuffer = [];
      this.preRollBuffer = [];
      this.isSpeaking = false;
      this.onPlaybackStateChange(false);
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
