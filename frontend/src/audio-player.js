/**
 * AudioPlayer
 * Handles Web Audio API output, continuous PCM chunk streaming, volume scaling, and playback meter.
 */

export class AudioPlayer {
  constructor({ onPlaybackStateChange, onAudioLevel, onLog }) {
    this.onPlaybackStateChange = onPlaybackStateChange || (() => {});
    this.onAudioLevel = onAudioLevel || (() => {});
    this.onLog = onLog || console.log;

    this.audioContext = null;
    this.gainNode = null;
    this.analyser = null;
    this.isPlaying = false;
    this.volumeLevel = 5; // 1 to 10 scale (default 5 = 100% standard unity gain)
    this.scheduledTime = 0;
    this.activeSources = [];
    this.meterInterval = null;
  }

  async initialize() {
    if (!this.audioContext) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      this.audioContext = new AudioContextClass({ sampleRate: 24000 });

      // Create Gain Node
      this.gainNode = this.audioContext.createGain();
      this._applyVolume();

      // Create Analyser Node for visual metering
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.smoothingTimeConstant = 0.4;

      this.gainNode.connect(this.analyser);
      this.analyser.connect(this.audioContext.destination);

      this._startMeter();
    }

    if (this.audioContext.state === 'suspended') {
      await this.audioContext.resume();
    }

    // Play a silent buffer to prime the iOS audio pipeline
    const silentBuffer = this.audioContext.createBuffer(1, 1, 24000);
    const source = this.audioContext.createBufferSource();
    source.buffer = silentBuffer;
    source.connect(this.gainNode);
    source.start();

    this.onLog('🔈 AudioPlayer initialized and unlocked on iOS AudioContext.');
  }

  setVolumeLevel(level) {
    this.volumeLevel = Math.max(1, Math.min(10, level));
    this._applyVolume();
    this.onLog(`🔊 AudioPlayer: Set hardware volume to ${this.volumeLevel}/10`);
  }

  _applyVolume() {
    if (this.gainNode) {
      // Map 1-10 scale to linear gain (Level 5 = 1.0, Level 10 = 2.0, Level 1 = 0.2)
      const gainValue = this.volumeLevel / 5.0;
      this.gainNode.gain.setValueAtTime(gainValue, this.audioContext ? this.audioContext.currentTime : 0);
    }
  }

  playChunk(arrayBuffer) {
    if (!this.audioContext) return;

    if (this.audioContext.state === 'suspended') {
      this.audioContext.resume();
    }

    // Kokoro outputs raw 24kHz 16-bit Mono PCM
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

    if (!this.isPlaying) {
      this.isPlaying = true;
      this.onPlaybackStateChange(true);
    }

    source.onended = () => {
      const index = this.activeSources.indexOf(source);
      if (index > -1) {
        this.activeSources.splice(index, 1);
      }

      if (this.activeSources.length === 0 && this.scheduledTime <= this.audioContext.currentTime + 0.1) {
        this.isPlaying = false;
        this.onPlaybackStateChange(false);
      }
    };
  }

  finishStream() {
    // Called when DONE signal arrives from server
    if (this.activeSources.length === 0) {
      this.isPlaying = false;
      this.onPlaybackStateChange(false);
    }
  }

  stopPlayback() {
    // Immediately cut off all queued audio chunks (Barge-in)
    this.activeSources.forEach((src) => {
      try {
        src.stop();
        src.disconnect();
      } catch (e) {}
    });
    this.activeSources = [];
    this.scheduledTime = 0;

    if (this.isPlaying) {
      this.isPlaying = false;
      this.onPlaybackStateChange(false);
    }
  }

  _startMeter() {
    if (this.meterInterval) return;

    const dataArray = new Uint8Array(this.analyser.frequencyBinCount);

    this.meterInterval = setInterval(() => {
      if (!this.isPlaying || !this.analyser) {
        this.onAudioLevel(0);
        return;
      }

      this.analyser.getByteTimeDomainData(dataArray);

      let sum = 0;
      for (let i = 0; i < dataArray.length; i++) {
        const val = (dataArray[i] - 128) / 128.0;
        sum += val * val;
      }

      const rms = Math.sqrt(sum / dataArray.length);
      const intensity = Math.min(1.0, rms * 4.0); // Boosted for visible LED modulation
      this.onAudioLevel(intensity);
    }, 30);
  }
}
