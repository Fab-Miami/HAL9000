/**
 * AudioRecorder
 * Captures microphone audio using Web Audio API ScriptProcessorNode (iOS Safari compatible),
 * downsamples to 16kHz 16-bit Mono PCM, and continuously streams binary chunks to WebSocket.
 */

export class AudioRecorder {
  constructor({ onAudioData, onAudioLevel, onSpeechDetected, onLog }) {
    this.onAudioData = onAudioData || (() => {});
    this.onAudioLevel = onAudioLevel || (() => {});
    this.onSpeechDetected = onSpeechDetected || (() => {});
    this.onLog = onLog || console.log;

    this.audioContext = null;
    this.mediaStream = null;
    this.sourceNode = null;
    this.scriptNode = null;
    this.isRecording = false;
    this.muted = false;
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
        for (let i = 0; i < downsampled.length; i++) {
          const s = Math.max(-1, Math.min(1, downsampled[i]));
          pcmView.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
          sum += s * s;
        }

        const rms = Math.sqrt(sum / downsampled.length);
        const intensity = Math.min(1.0, rms * 5.0);
        this.onAudioLevel(intensity);

        if (intensity > 0.35) {
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
