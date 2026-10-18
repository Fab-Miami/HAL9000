/**
 * MotionDetector
 * Listens to iPhone hardware accelerometer via DeviceMotionEvent.
 * Detects physical knocks/taps on the HAL 9000 enclosure to trigger
 * instant speech interruption (barge-in) and knock-to-wake.
 */

export class MotionDetector {
  constructor({ threshold = 2.5, cooldownMs = 500, onKnock, onLog } = {}) {
    this.threshold = threshold; // Acceleration magnitude spike in m/s² (calibrated for enclosure/desk finger taps)
    this.cooldownMs = cooldownMs; // Prevent duplicate knock triggers from ringing vibrations
    this.onKnock = onKnock || (() => {});
    this.onLog = onLog || console.log;

    this.isSupported = typeof window !== 'undefined' && 'DeviceMotionEvent' in window;
    this.isActive = false;
    this.lastKnockTime = 0;
    this.lastX = 0;
    this.lastY = 0;
    this.lastZ = 0;
    this.hasPreviousGravitySample = false;

    this._handleMotion = this._handleMotion.bind(this);
  }

  /**
   * Request iOS sensor permission and begin motion monitoring.
   * MUST be invoked directly inside a user touch/click gesture (e.g. INITIALIZE SYSTEM).
   */
  async initialize() {
    if (!this.isSupported) {
      this.onLog('⚠️ [MotionDetector] DeviceMotionEvent not supported in this browser environment.');
      return false;
    }

    try {
      // iOS 13+ permission model
      if (typeof DeviceMotionEvent.requestPermission === 'function') {
        const permissionState = await DeviceMotionEvent.requestPermission();
        if (permissionState === 'granted') {
          this.onLog('✅ [MotionDetector] iOS DeviceMotion permission GRANTED.');
          this.start();
          return true;
        } else {
          this.onLog(`⚠️ [MotionDetector] iOS DeviceMotion permission ${permissionState}.`);
          return false;
        }
      } else {
        // Non-iOS or older Safari: permission granted by default
        this.start();
        return true;
      }
    } catch (err) {
      this.onLog(`❌ [MotionDetector] Permission request error: ${err.message}`);
      return false;
    }
  }

  start() {
    if (this.isActive || !this.isSupported) return;
    window.addEventListener('devicemotion', this._handleMotion, { passive: true });
    this.isActive = true;
    this.onLog(`🎯 [MotionDetector] Active: monitoring enclosure knocks (Threshold: ${this.threshold} m/s²).`);
  }

  stop() {
    if (!this.isActive) return;
    window.removeEventListener('devicemotion', this._handleMotion);
    this.isActive = false;
    this.hasPreviousGravitySample = false;
  }

  _handleMotion(event) {
    let magLinear = 0;
    // Primary: Linear acceleration (gravity isolated by iOS hardware fusion)
    if (event.acceleration && event.acceleration.x !== null) {
      const ax = event.acceleration.x || 0;
      const ay = event.acceleration.y || 0;
      const az = event.acceleration.z || 0;
      magLinear = Math.hypot(ax, ay, az);
    }

    let magJerk = 0;
    // Secondary: High-pass jerk filter on raw acceleration including gravity
    if (event.accelerationIncludingGravity) {
      const gx = event.accelerationIncludingGravity.x || 0;
      const gy = event.accelerationIncludingGravity.y || 0;
      const gz = event.accelerationIncludingGravity.z || 0;

      if (this.hasPreviousGravitySample) {
        const dx = gx - this.lastX;
        const dy = gy - this.lastY;
        const dz = gz - this.lastZ;
        magJerk = Math.hypot(dx, dy, dz);
      }

      this.lastX = gx;
      this.lastY = gy;
      this.lastZ = gz;
      this.hasPreviousGravitySample = true;
    }

    // Capture highest impulse between linear acceleration and jerk filter
    const magnitude = Math.max(magLinear, magJerk);

    // Check if mechanical shockwave exceeds knock threshold
    if (magnitude > this.threshold) {
      const now = performance.now();
      if (now - this.lastKnockTime > this.cooldownMs) {
        this.lastKnockTime = now;
        this.onLog(`💥 [MotionDetector] ENCLOSURE KNOCK DETECTED (Shock magnitude: ${magnitude.toFixed(1)} m/s²)`);
        this.onKnock(magnitude);
      }
    }
  }
}
