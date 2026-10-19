/**
 * AudioRecorder
 * Captures microphone audio using Web Audio API ScriptProcessorNode (iOS Safari compatible),
 * downsamples to 16kHz 16-bit Mono PCM, and continuously streams binary chunks to WebSocket.
 */

export class AudioRecorder {
  constructor({ onAudioData, onAudioLevel, onSpeechDetected, onWakeTrigger, onLog }) {
    this.onAudioData = onAudioData || (() => {});
    this.onAudioLevel = onAudioLevel || (() => {});
    this.onSpeechDetected = onSpeechDetected || (() => {});
    this.onWakeTrigger = onWakeTrigger || (() => {});
    this.onLog = onLog || console.log;

    this.audioContext = null;
    this.mediaStream = null;
    this.sourceNode = null;
    this.scriptNode = null;
    this.isRecording = false;
    this.muted = false;
    this.sleeping = false;
    this.firstAcousticTapTime = 0;
    this.firstAcousticTapPeak = 0;
  }

  async start() {
    if (this.isRecording) return;

    try {
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

      if (!this.audioContext) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        this.audioContext = new AudioContextClass();
      }

      if (this.audioContext.state === 'suspended') {
        await this.audioContext.resume();
      }

      this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);

      // Buffer size 4096 gives ~92ms chunks at 44.1kHz / ~85ms at 48kHz
      this.scriptNode = this.audioContext.createScriptProcessor(4096, 1, 1);

      this.scriptNode.onaudioprocess = (event) => {
        if (!this.isRecording || this.muted) return;

        const inputBuffer = event.inputBuffer.getChannelData(0);
        const inputSampleRate = this.audioContext.sampleRate;

        // Downsample to 16kHz
        const targetSampleRate = 16000;
        const downsampled = this._downsample(inputBuffer, inputSampleRate, targetSampleRate);

        // Convert Float32 to 16-bit PCM (Little-Endian)
        const pcmBuffer = new ArrayBuffer(downsampled.length * 2);
        const pcmView = new DataView(pcmBuffer);

        let sum = 0;
        let maxPeak = 0;
        for (let i = 0; i < downsampled.length; i++) {
          const s = Math.max(-1, Math.min(1, downsampled[i]));
          const absVal = Math.abs(s);
          if (absVal > maxPeak) maxPeak = absVal;
          pcmView.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
          sum += s * s;
        }

        const rms = Math.sqrt(sum / downsampled.length);

        // Track ambient noise floor dynamically (smooth EMA)
        if (this.noiseFloor === undefined) {
          this.noiseFloor = rms;
        } else {
          if (rms < this.noiseFloor) {
            this.noiseFloor = this.noiseFloor * 0.95 + rms * 0.05;
          } else {
            this.noiseFloor = this.noiseFloor * 0.995 + rms * 0.005;
          }
        }

        // =========================================================================================
        // CRITICAL NOTE: CALIBRATED ACOUSTIC SENSITIVITY FOR USER SPEECH FEEDBACK (hal2026_ring_on.png)
        // Do NOT set noiseGate too high (> 0.015)! An iPhone inside an aluminum enclosure and behind
        // glass absorbs acoustic energy; normal human speech produces an RMS between 0.012 and 0.050.
        // Clamping noiseGate at 0.04 completely kills voice detection and stops the outer ring from blinking.
        // =========================================================================================
        const noiseGate = Math.max(0.005, this.noiseFloor * 1.25 + 0.003);
        const voiceDelta = rms - noiseGate;
        const intensity = voiceDelta > 0 ? Math.min(1.0, voiceDelta * 18.0) : 0.0;
        this.onAudioLevel(intensity);

        // =========================================================================================
        // DOUBLE-TAP ACOUSTIC WAKE DETECTION (STANDBY MODE)
        // Requires 2 consecutive impulse taps:
        // 1. Almost consecutive: 140ms - 850ms apart (avoids reverberation and separate events)
        // 2. Almost identical: peak amplitude ratio >= 0.40 (same knuckle/finger impact force)
        // Single isolated loud sounds (door slams, coughs, TV peaks) are strictly rejected!
        // =========================================================================================
        if (this.sleeping) {
          const now = performance.now();
          const crestFactor = maxPeak / (rms + 0.0001);
          const isImpulse = (maxPeak > 0.20 && crestFactor > 2.6) || (maxPeak > 0.35 && (rms - this.noiseFloor) > 0.04);

          if (isImpulse) {
            const timeSinceFirstTap = now - this.firstAcousticTapTime;

            if (this.firstAcousticTapTime > 0 && timeSinceFirstTap >= 140 && timeSinceFirstTap <= 850) {
              const peakRatio = Math.min(this.firstAcousticTapPeak, maxPeak) / Math.max(this.firstAcousticTapPeak, maxPeak);
              if (peakRatio >= 0.40) {
                this.onLog(`🥁 [AudioRecorder] Verified DOUBLE TAP on enclosure! (Tap 1: ${this.firstAcousticTapPeak.toFixed(2)}, Tap 2: ${maxPeak.toFixed(2)}, Match: ${(peakRatio * 100).toFixed(0)}%, Interval: ${Math.round(timeSinceFirstTap)}ms). Waking HAL.`);
                this.firstAcousticTapTime = 0;
                this.firstAcousticTapPeak = 0;
                this.onWakeTrigger('acoustic_double_tap');
                return;
              } else {
                this.onLog(`🥁 [AudioRecorder] Tap 2 rejected: amplitude mismatch (Tap 1: ${this.firstAcousticTapPeak.toFixed(2)}, Tap 2: ${maxPeak.toFixed(2)}, Ratio: ${(peakRatio * 100).toFixed(0)}%). Resetting first tap.`);
                this.firstAcousticTapTime = now;
                this.firstAcousticTapPeak = maxPeak;
              }
            } else if (timeSinceFirstTap > 850 || this.firstAcousticTapTime === 0) {
              this.firstAcousticTapTime = now;
              this.firstAcousticTapPeak = maxPeak;
              this.onLog(`🥁 [AudioRecorder] First tap detected (Peak: ${maxPeak.toFixed(2)}, Crest: ${crestFactor.toFixed(1)}). Awaiting second tap within 850ms...`);
            }
          } else if (this.firstAcousticTapTime > 0 && (now - this.firstAcousticTapTime) > 850) {
            this.firstAcousticTapTime = 0;
            this.firstAcousticTapPeak = 0;
          }

          // In standby mode, stream voice audio to server if human speech exceeds noise floor
          // so server can detect "HAL wake up" with 2-second silence window.
          if (voiceDelta > 0.015) {
            this.onAudioData(pcmBuffer);
          }
          return;
        }

        if (intensity > 0.45) {
          this.onSpeechDetected();
        }

        // Stream PCM chunk to WebSocket
        this.onAudioData(pcmBuffer);
      };

      this.sourceNode.connect(this.scriptNode);
      this.scriptNode.connect(this.audioContext.destination);

      this.isRecording = true;
      this.onLog('🎙️ AudioRecorder: Microphone capture active (16kHz 16-bit PCM streaming).');
    } catch (err) {
      this.onLog(`❌ AudioRecorder: Failed to start microphone: ${err.message}`);
      throw err;
    }
  }

  stop() {
    this.isRecording = false;
    if (this.scriptNode) {
      this.scriptNode.disconnect();
      this.scriptNode = null;
    }
    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }
    this.onAudioLevel(0);
  }

  _downsample(inputData, inputSampleRate, targetSampleRate) {
    if (inputSampleRate === targetSampleRate) {
      return inputData;
    }

    const ratio = inputSampleRate / targetSampleRate;
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
}
