/**
 * MotionDetector
 * Listens to iPhone hardware accelerometer via DeviceMotionEvent.
 * Detects physical knocks/taps on the HAL 9000 enclosure to trigger
 * instant speech interruption (barge-in) and knock-to-wake.
 */

export class MotionDetector {
  constructor({ threshold = 0.35, cooldownMs = 500, onKnock, onLog } = {}) {
    this.threshold = threshold; // Acceleration magnitude spike in m/s² (calibrated for aluminum enclosure finger/knuckle knocks)
    this.cooldownMs = cooldownMs; // Prevent duplicate knock triggers from ringing vibrations
    this.onKnock = onKnock || (() => {});
    this.onLog = onLog || console.log;

    this.isSupported = typeof window !== 'undefined' && 'DeviceMotionEvent' in window;
    this.isActive = false;
    this.lastKnockTime = 0;
    this.lastSubVibrationTime = 0;
    this.lastX = 0;
    this.lastY = 0;
    this.lastZ = 0;
    this.hasPreviousGravitySample = false;
    this.permissionPromise = null;

    this._handleMotion = this._handleMotion.bind(this);
  }

  /**
   * Request iOS sensor permission synchronously in user gesture call stack.
   * In iOS Safari, DeviceMotionEvent.requestPermission() MUST be invoked directly
   * on the synchronous turn of a click/touchend event; any preceding 'await' causes
   * WebKit to reject with "requires a user gesture".
   */
  requestPermissionSync() {
    if (!this.isSupported) {
      this.onLog('⚠️ [MotionDetector] DeviceMotionEvent not supported in this browser environment.');
      return Promise.resolve(false);
    }

    if (this.permissionPromise) {
      return this.permissionPromise;
    }

    if (typeof DeviceMotionEvent.requestPermission === 'function') {
      try {
        this.permissionPromise = DeviceMotionEvent.requestPermission()
          .then((permissionState) => {
            if (permissionState === 'granted') {
              this.onLog('✅ [MotionDetector] iOS DeviceMotion permission GRANTED.');
              this.start();
              return true;
            } else {
              this.onLog(`⚠️ [MotionDetector] iOS DeviceMotion permission ${permissionState}.`);
              return false;
            }
          })
          .catch((err) => {
            this.onLog(`❌ [MotionDetector] Permission request error: ${err.message}`);
            return false;
          });
        return this.permissionPromise;
      } catch (err) {
        this.onLog(`❌ [MotionDetector] Sync request error: ${err.message}`);
        this.permissionPromise = Promise.resolve(false);
        return this.permissionPromise;
      }
    } else {
      this.start();
      this.permissionPromise = Promise.resolve(true);
      return this.permissionPromise;
    }
  }

  async initialize() {
    return this.requestPermissionSync();
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

    // Telemetry: Log subtle vibrations between 0.15 m/s² and threshold to monitor frame impacts
    if (magnitude >= 0.15 && magnitude < this.threshold) {
      const now = performance.now();
      if (now - this.lastSubVibrationTime > 400) {
        this.lastSubVibrationTime = now;
        this.onLog(`📳 [MotionDetector] Frame vibration detected: ${magnitude.toFixed(2)} m/s² (below threshold ${this.threshold} m/s²)`);
      }
    }

    // Check if mechanical shockwave exceeds knock threshold
    if (magnitude >= this.threshold) {
      const now = performance.now();
      if (now - this.lastKnockTime > this.cooldownMs) {
        this.lastKnockTime = now;
        this.onLog(`💥 [MotionDetector] ENCLOSURE KNOCK DETECTED (Shock magnitude: ${magnitude.toFixed(2)} m/s²)`);
        this.onKnock(magnitude);
      }
    }
  }
}
