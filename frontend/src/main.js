/**
 * HAL 9000 Console Controller
 * Coordinates the optical faceplate, 24/7 screen wake lock, accelerometer knock sensor,
 * native WebSocket transport, and HalAudio engine.
 */

import { HalAudio } from './hal-audio.js';

// DOM Elements
const layerEverythingOff = document.getElementById('layer-everything-off');
const layer3LedOn = document.getElementById('layer-3-led-on');
const layerCenterOn = document.getElementById('layer-center-on');
const layerRingOn = document.getElementById('layer-ring-on');
const initOverlay = document.getElementById('init-overlay');
const halContainer = document.getElementById('hal-container');

// Calibrated vertical offset for physical aluminum console enclosure
if (halContainer) {
  halContainer.style.transform = 'translateY(-146.67px)';
}

// System States
const State = {
  IDLE: 'IDLE',
  LISTENING: 'LISTENING',
  THINKING: 'THINKING',
  SPEAKING: 'SPEAKING',
  SLEEPING: 'SLEEPING',
};

let currentState = State.IDLE;
let persistentLedOn = false;
let ledAnimTimeout = null;
let sleepTimer = null;
const SLEEP_TIMEOUT_MS = 300000; // 5 minutes inactivity timeout (Active Idle before Deep Standby)

// Telemetry & WebSocket
let ws = null;
let wsReconnectTimer = null;
const clientId = getOrCreateClientId();

function getOrCreateClientId() {
  let id = localStorage.getItem('hal_client_id');
  if (!id) {
    id = 'hal_device_' + Math.random().toString(36).substring(2, 11);
    localStorage.setItem('hal_client_id', id);
  }
  return id;
}

function log(msg) {
  console.log(msg);
  if (ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(JSON.stringify({ type: 'telemetry', message: msg }));
    } catch (e) {}
  }
}

// ===========================================================================
// HAL 9000 STATE MACHINE & OPTICAL FACEPLATE
// ===========================================================================
function setHalState(newState) {
  currentState = newState;
  log(`🔄 [State] Transition -> ${newState}`);

  // Strict half-duplex gating: mic is ONLY active when in LISTENING or SLEEPING
  if (halAudio) {
    if (newState === State.LISTENING || newState === State.SLEEPING) {
      halAudio.setListeningActive(true);
    } else {
      halAudio.setListeningActive(false);
    }
  }

  if (newState === State.SLEEPING) {
    document.body.classList.add('sleep-mode');
    document.body.classList.remove('state-thinking');
    clearLedAnimations();
    // Standby: ALL LEDs strictly OFF (0.0 opacity). Faceplate background dims to 50% opacity via .sleep-mode CSS.
    if (layerCenterOn) {
      clearTimeout(eyeWakeTimer);
      layerCenterOn.classList.remove('eye-waking');
      layerCenterOn.classList.remove('eye-wake-ignite');
      layerCenterOn.style.opacity = '0.0';
    }
    if (layerRingOn) layerRingOn.style.opacity = '0.0';
    if (layer3LedOn) layer3LedOn.style.opacity = '0.0';
  } else {
    document.body.classList.remove('sleep-mode');
    if (newState === State.THINKING) {
      document.body.classList.add('state-thinking');
    } else {
      document.body.classList.remove('state-thinking');
    }

    // Active states: Central eye is illuminated
    if (layerCenterOn) {
      layerCenterOn.style.opacity = '1.0';
    }
    // Acoustic ring is strictly OFF whenever not in LISTENING (and starts at 0.0 in LISTENING until user speaks)
    if (layerRingOn) {
      layerRingOn.style.opacity = '0.0';
    }
    // 4 Auxiliary LEDs are strictly OFF in SPEAKING and LISTENING
    if (newState === State.SPEAKING || newState === State.LISTENING) {
      clearLedAnimations();
      if (layer3LedOn) layer3LedOn.style.opacity = '0.0';
    }
  }
}

function resetSleepTimer() {
  clearTimeout(sleepTimer);
  if (currentState !== State.SLEEPING) {
    sleepTimer = setTimeout(goToSleep, SLEEP_TIMEOUT_MS);
  }
}

let pendingSleep = false;
let eyeWakeTimer = null;
let thinkingLedTimer = null;

function wakeUp() {
  pendingSleep = false;
  if (currentState !== State.SLEEPING) return;
  log('☀️ [HAL 9000] Waking up from Standby (Central eye ignites with immediate optical feedback).');
  setPersistentLed(false);
  clearLedAnimations();
  if (layer3LedOn) layer3LedOn.style.opacity = '0.0';
  if (halAudio) {
    halAudio.setSleeping(false);
    halAudio.notifySpeechFinished();
  }

  // Optical assembly: Immediate ignition flare for the central eye
  setHalState(State.LISTENING);
  if (layerCenterOn) {
    clearTimeout(eyeWakeTimer);
    layerCenterOn.classList.remove('eye-wake-ignite');
    layerCenterOn.classList.remove('eye-waking');
    void layerCenterOn.offsetWidth; // Force reflow
    layerCenterOn.classList.add('eye-waking');
    layerCenterOn.style.opacity = '1.0';
    eyeWakeTimer = setTimeout(() => {
      if (layerCenterOn) layerCenterOn.classList.remove('eye-waking');
    }, 2600);
  }
  triggerLedTag('wink'); // Single brief blink acknowledging wake call

  resetSleepTimer();
  requestScreenWakeLock();
  ensureKeepAwakeVideoPlaying();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'sleep_state', sleeping: false }));
  }
}

function goToSleep(force = false) {
  if (!force && halAudio && halAudio.isPlaying) {
    log('🌙 [HAL 9000] Speech playing. Will enter Standby once playback finishes.');
    pendingSleep = true;
    return;
  }
  clearTimeout(window._thinkingSafetyTimer);
  pendingSleep = false;
  log('🌙 [HAL 9000] Entering Standby (Listening for wake word).');
  if (persistentLedOn) setPersistentLed(false);
  if (halAudio) halAudio.setSleeping(true);
  setHalState(State.SLEEPING);
  // CRITICAL MANDATE #2: Screen stays ON 24/7 in standby! Re-assert wake lock & keep-awake video immediately!
  requestScreenWakeLock();
  ensureKeepAwakeVideoPlaying();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'sleep_state', sleeping: true }));
  }
}

// ===========================================================================
// 4 AUXILIARY SATELLITE LEDS (TURN ACKNOWLEDGEMENT & SERVER WAIT FEEDBACK)
// ===========================================================================
function setPersistentLed(on) {
  persistentLedOn = false;
  if (layer3LedOn && !on) {
    layer3LedOn.style.opacity = '0.0';
  }
}

function clearLedAnimations() {
  clearTimeout(ledAnimTimeout);
  clearTimeout(thinkingLedTimer);
  if (!layer3LedOn) return;
  layer3LedOn.classList.remove(
    'led-anim-chuckle', 'led-anim-laugh', 'led-anim-wink',
    'led-anim-ponder', 'led-anim-breathe', 'led-anim-warm',
    'led-anim-alert', 'led-anim-heartbeat', 'led-anim-listen-done',
    'led-anim-search', 'led-anim-api', 'led-anim-thinking'
  );
}

function triggerLedTag(tag) {
  if (!layer3LedOn || currentState === State.SLEEPING || currentState === State.SPEAKING) return;
  // Never turn on 4 LEDs if acoustic ring is active
  if (layerRingOn && parseFloat(layerRingOn.style.opacity || '0') > 0) return;

  const t = (tag || '').toLowerCase().trim();
  if (t === 'off' || t === 'led_off' || t === 'lights_off') {
    clearLedAnimations();
    layer3LedOn.style.opacity = '0.0';
    return;
  }

  clearLedAnimations();
  layer3LedOn.style.removeProperty('opacity');
  layer3LedOn.style.setProperty('--persistent-led', '0.0');
  void layer3LedOn.offsetWidth; // Reflow to restart animation

  let animName = 'listen-done';
  let duration = 450;

  if (t.includes('wink')) { animName = 'wink'; duration = 450; }
  else if (t.includes('listen-done') || t.includes('ack')) { animName = 'listen-done'; duration = 450; }

  layer3LedOn.classList.add(`led-anim-${animName}`);
  ledAnimTimeout = setTimeout(() => {
    if (layer3LedOn && !layer3LedOn.classList.contains('led-anim-thinking')) {
      clearLedAnimations();
      layer3LedOn.style.opacity = '0.0';
    }
  }, duration);
}

function blinkStandbyDispatchLeds() {
  if (!layer3LedOn) return;
  clearLedAnimations();
  layer3LedOn.style.removeProperty('opacity');
  layer3LedOn.style.setProperty('--persistent-led', '0.0');
  void layer3LedOn.offsetWidth;
  layer3LedOn.classList.add('led-anim-wink');
  ledAnimTimeout = setTimeout(() => {
    clearLedAnimations();
    if (layer3LedOn) {
      layer3LedOn.style.opacity = '0.0';
    }
  }, 450);
}

function startThinkingLeds() {
  if (!layer3LedOn || currentState !== State.THINKING) return;
  clearLedAnimations();
  if (layerRingOn) layerRingOn.style.opacity = '0.0';
  layer3LedOn.style.removeProperty('opacity');
  layer3LedOn.style.setProperty('--persistent-led', '0.0');
  void layer3LedOn.offsetWidth; // Force reflow to cleanly start animation
  layer3LedOn.classList.add('led-anim-thinking');
  log('⏳ [HAL Hardware] 4 Auxiliary LEDs blinking slowly (Waiting for server data).');
}

// ===========================================================================
// WEBSOCKET CLIENT (DAPHNE ASGI CONNECTION)
// ===========================================================================
function connectWebSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  clearTimeout(wsReconnectTimer);

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/hal/${clientId}/`;
  log(`🌐 [WS] Connecting: ${wsUrl}`);

  try {
    ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
      log('✅ [WS] Connected to HAL backend (v30 Real-Time Telemetry & Robust Wake).');
      ws.send(JSON.stringify({
        type: 'init',
        version: 'v30',
        volume: halAudio.volumeLevel,
        sleeping: currentState === State.SLEEPING,
      }));
    };

    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        // Binary 24kHz PCM chunk from Kokoro TTS
        if (currentState === State.SLEEPING) wakeUp();
        if (currentState !== State.SPEAKING) setHalState(State.SPEAKING);
        halAudio.playChunk(event.data);
      } else if (typeof event.data === 'string') {
        const msg = event.data;
        if (msg === 'DONE') {
          log('🏁 [WS] Received DONE from server.');
          halAudio.finishStream();
          // If HAL was THINKING or SPEAKING and no audio was received (silent turn) or playback completed, immediately restore LISTENING
          if ((currentState === State.THINKING || currentState === State.SPEAKING) && !halAudio.isPlaying && halAudio.activeSources.length === 0) {
            clearTimeout(window._thinkingSafetyTimer);
            setHalState(State.LISTENING);
            resetSleepTimer();
            halAudio && halAudio.notifySpeechFinished();
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'playback_complete' }));
            }
          }
          if (pendingSleep && !halAudio.isPlaying) {
            goToSleep(true);
          }
          if (currentState === State.SLEEPING) {
            halAudio.setListeningActive(true);
          }
        } else if (msg === 'UNADDRESSED') {
          log('🤫 [WS] Received UNADDRESSED from server -> Restoring LISTENING.');
          clearTimeout(window._thinkingSafetyTimer);
          if (currentState === State.THINKING) {
            setHalState(State.LISTENING);
            resetSleepTimer();
          }
        } else if (msg === 'THINKING') {
          if (currentState !== State.SLEEPING && currentState !== State.THINKING) {
            setHalState(State.THINKING);
            startThinkingLeds();
          }
        } else if (msg === 'WAKE') {
          wakeUp();
        } else if (msg === 'SLEEP') {
          goToSleep(true);
        } else if (msg === 'RELOAD') {
          log('🔄 [WS] Remote RELOAD received. Refreshing page with cache-bust...');
          window.location.href = window.location.pathname + '?v=' + Date.now();
        } else if (msg.startsWith('VOLUME:')) {
          const vol = parseInt(msg.split(':')[1], 10);
          if (!isNaN(vol)) halAudio.setVolume(vol);
        } else if (msg.startsWith('LED:') || msg.startsWith('TAG:')) {
          // Strict LED policy: 4 LEDs are only used for turn-end acknowledgement and server-wait blinking
        }
      }
    };

    ws.onerror = (err) => {
      log(`⚠️ [WS] Connection error: ${err.message || 'Error'}`);
    };

    ws.onclose = (event) => {
      log(`🔴 [WS] Disconnected (Code: ${event.code}). Auto-reconnecting in 3s...`);
      wsReconnectTimer = setTimeout(connectWebSocket, 3000);
    };
  } catch (e) {
    log(`❌ [WS] Instantiation failure: ${e.message}`);
  }
}

// ===========================================================================
// UNIFIED HAL AUDIO ENGINE INSTANTIATION
// ===========================================================================
const halAudio = new HalAudio({
  // Vocal RMS feedback -> Directly pulses outer acoustic ring (#layer-ring-on) between 70% and 100%
  // STRICT INVIOLABLE DIRECTIVE: Only pulses during active conversation (State.LISTENING).
  // NEVER have hal2026_4_led_on and hal2026_ring_on ON at the same time.
  onAudioLevel: (ringLevel) => {
    if (currentState === State.LISTENING && layerRingOn) {
      if (ringLevel > 0) {
        if (layer3LedOn) {
          clearLedAnimations();
          layer3LedOn.style.opacity = '0.0';
        }
        const clampedRing = Math.min(1.0, Math.max(0.70, ringLevel));
        layerRingOn.style.opacity = clampedRing.toFixed(2);
      } else {
        layerRingOn.style.opacity = '0.0';
      }
    }
  },

  // Playback RMS feedback -> Pulses ONLY central eye (#layer-center-on) with x1.5 amplitude (0.58 to 1.00)
  onPlaybackLevel: (intensity) => {
    if (currentState === State.SPEAKING && layerCenterOn) {
      layerCenterOn.style.opacity = (0.58 + intensity * 0.42).toFixed(2);
    }
  },

  // User finished speaking -> Blink 4 LEDs once, then blink slowly while waiting for server data
  onTurnComplete: (wavBytes) => {
    if (currentState !== State.SLEEPING) {
      if (layerRingOn) layerRingOn.style.opacity = '0.0';
      setPersistentLed(false);
      clearLedAnimations();
      if (layer3LedOn) layer3LedOn.style.opacity = '0.0';
      setHalState(State.THINKING);
      triggerLedTag('listen-done'); // Blink once (450ms) when finished listening
      thinkingLedTimer = setTimeout(() => {
        if (currentState === State.THINKING) {
          startThinkingLeds(); // Then blink slowly while waiting for / receiving server data
        }
      }, 800);
      clearTimeout(window._thinkingSafetyTimer);
      window._thinkingSafetyTimer = setTimeout(() => {
        if (currentState === State.THINKING) {
          log('⚠️ [State Safety] Thinking safety watchdog (20s) -> Restoring LISTENING.');
          setHalState(State.LISTENING);
          resetSleepTimer();
        }
      }, 20000);
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
      log(`📤 [HalAudio] Transmitting audio turn (${wavBytes.byteLength} bytes) to Gemini.`);
      ws.send(wavBytes);
    }
  },

  // HAL voice playback finished -> Enter standby if sleep was requested, else resume listening
  onPlaybackStateChange: (isPlaying) => {
    if (isPlaying) {
      setHalState(State.SPEAKING);
    } else {
      setPersistentLed(false);
      clearLedAnimations();
      if (layer3LedOn) layer3LedOn.style.opacity = '0.0';

      if (pendingSleep) {
        log('🌙 [HAL 9000] Speech playback completed. Entering Standby now.');
        goToSleep(true);
        return;
      }

      if (currentState === State.SLEEPING) {
        // In standby sleep mode: strictly remain asleep!
        if (halAudio) halAudio.setListeningActive(true);
        return;
      }

      // Active conversation mode: speech playback actually completed on speaker
      if (ws && ws.readyState === WebSocket.OPEN) {
        log('⏱️ [HAL 9000] Speech playback finished -> Grace clock starts NOW.');
        ws.send(JSON.stringify({ type: 'playback_complete' }));
      }

      setHalState(State.LISTENING);
      resetSleepTimer();
      if (halAudio) halAudio.notifySpeechFinished();
    }
  },

  // Standby double-tap acoustic wake
  onWake: (reason) => {
    log(`🥁 [HAL 9000] Acoustic wake triggered (${reason}).`);
    triggerLedTag('wink');
    wakeUp();
  },

  // Standby sandwich matched -> Blink 3 auxiliary LEDs as immediate visual feedback
  onStandbyDispatch: () => {
    log('🥪 [HalAudio] Sandwich profile matched. Blinking 3 LEDs & dispatching to server.');
    blinkStandbyDispatchLeds();
  },

  onLog: log,
});

// ===========================================================================
// HARDWARE ACCELEROMETER KNOCK SENSOR (PHYSICAL CONSOLE INTERACTION)
// ===========================================================================
let lastKnockTime = 0;
let lastX = 0, lastY = 0, lastZ = 0;
let hasGravitySample = false;
const KNOCK_THRESHOLD = 1.0; // Calibrated for knuckle taps on aluminum enclosure (m/s²)

function handleDeviceMotion(event) {
  let magLinear = 0;
  if (event.acceleration && event.acceleration.x !== null) {
    magLinear = Math.hypot(event.acceleration.x || 0, event.acceleration.y || 0, event.acceleration.z || 0);
  }

  let magJerk = 0;
  if (event.accelerationIncludingGravity) {
    const gx = event.accelerationIncludingGravity.x || 0;
    const gy = event.accelerationIncludingGravity.y || 0;
    const gz = event.accelerationIncludingGravity.z || 0;
    if (hasGravitySample) {
      magJerk = Math.hypot(gx - lastX, gy - lastY, gz - lastZ);
    }
    lastX = gx; lastY = gy; lastZ = gz;
    hasGravitySample = true;
  }

  const magnitude = Math.max(magLinear, magJerk);
  if (magnitude >= KNOCK_THRESHOLD) {
    const now = performance.now();
    if (now - lastKnockTime > 500) {
      lastKnockTime = now;
      log(`💥 [Motion] Enclosure knock detected (${magnitude.toFixed(2)} m/s²)!`);

      if (!isSystemInitialized) {
        log('💥 [Motion] Knock on uninitialized system -> Auto-starting system...');
        initializeSystem().then(() => {
          wakeUp();
        });
        return;
      }

      // Knock ONLY wakes up HAL from standby. Never interrupts him while speaking!
      if (currentState === State.SLEEPING) {
        triggerLedTag('wink');
        wakeUp();
      }
    }
  }
}

// Register motion listener immediately so enclosure knocks work before and after initialization
window.addEventListener('devicemotion', handleDeviceMotion, { passive: true });

// ===========================================================================
// 24/7 SCREEN WAKE LOCK & KEEP-AWAKE MP4
// ===========================================================================
const SILENT_KEEP_AWAKE_MP4 = 'data:video/mp4;base64,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';

let keepAwakeVideo = null;
let wakeLockSentinel = null;
let isAcquiringWakeLock = false;

function initKeepAwakeVideo() {
  if (keepAwakeVideo) {
    ensureKeepAwakeVideoPlaying();
    return;
  }
  try {
    keepAwakeVideo = document.createElement('video');
    keepAwakeVideo.setAttribute('playsinline', '');
    keepAwakeVideo.setAttribute('webkit-playsinline', '');
    keepAwakeVideo.setAttribute('muted', '');
    keepAwakeVideo.setAttribute('autoplay', '');
    keepAwakeVideo.muted = true;
    keepAwakeVideo.autoplay = true;
    keepAwakeVideo.loop = true;
    keepAwakeVideo.style.position = 'fixed';
    keepAwakeVideo.style.top = '0';
    keepAwakeVideo.style.left = '0';
    keepAwakeVideo.style.width = '1px';
    keepAwakeVideo.style.height = '1px';
    keepAwakeVideo.style.opacity = '0.001';
    keepAwakeVideo.style.pointerEvents = 'none';
    keepAwakeVideo.style.zIndex = '-999';
    keepAwakeVideo.src = SILENT_KEEP_AWAKE_MP4;

    keepAwakeVideo.onpause = () => {
      ensureKeepAwakeVideoPlaying();
    };
    keepAwakeVideo.onended = () => {
      ensureKeepAwakeVideoPlaying();
    };
    keepAwakeVideo.ontimeupdate = () => {
      if (keepAwakeVideo.currentTime > 0.5) {
        keepAwakeVideo.currentTime = 0;
      }
    };

    document.body.appendChild(keepAwakeVideo);

    const playPromise = keepAwakeVideo.play();
    if (playPromise !== undefined) {
      playPromise
        .then(() => log('📺 [KeepAwake] Silent video playing (iOS screen sleep blocked 24/7).'))
        .catch((err) => log(`⚠️ [KeepAwake] Video play pending gesture: ${err.message}`));
    }
  } catch (e) {
    log(`⚠️ [KeepAwake] Video element init error: ${e.message}`);
  }
}

function ensureKeepAwakeVideoPlaying() {
  if (!keepAwakeVideo) {
    initKeepAwakeVideo();
    return;
  }
  if (keepAwakeVideo.paused) {
    const playPromise = keepAwakeVideo.play();
    if (playPromise !== undefined) {
      playPromise
        .then(() => log('📺 [KeepAwake] Silent video resumed.'))
        .catch(() => {});
    }
  }
}

async function requestScreenWakeLock() {
  if (isAcquiringWakeLock) return;
  if ('wakeLock' in navigator) {
    try {
      if (wakeLockSentinel && !wakeLockSentinel.released) return;
      isAcquiringWakeLock = true;
      wakeLockSentinel = await navigator.wakeLock.request('screen');
      log('🔒 [WakeLock] Screen Wake Lock acquired (24/7 display lock engaged).');
      wakeLockSentinel.addEventListener('release', () => {
        log('🔓 [WakeLock] Screen Wake Lock released by OS. Scheduling re-acquisition...');
        wakeLockSentinel = null;
        setTimeout(() => {
          if (document.visibilityState === 'visible') {
            requestScreenWakeLock();
          }
        }, 1000);
      });
    } catch (e) {
      // Keep-Awake video maintains screen ON 24/7. Avoid spamming backend logs on routine iOS permission note.
      console.debug(`[WakeLock] Note: ${e.name} - ${e.message}`);
      wakeLockSentinel = null;
    } finally {
      isAcquiringWakeLock = false;
    }
  } else {
    console.debug('[WakeLock] Native API unavailable; Keep-Awake video maintains 24/7 screen ON.');
  }
  ensureKeepAwakeVideoPlaying();
}

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    requestScreenWakeLock();
    ensureKeepAwakeVideoPlaying();
  }
});

setInterval(() => {
  if (document.visibilityState === 'visible') {
    if (!wakeLockSentinel || wakeLockSentinel.released) {
      requestScreenWakeLock();
    }
    ensureKeepAwakeVideoPlaying();
  }
}, 15000);

// Initialize Keep-Awake element immediately on load
initKeepAwakeVideo();

// ===========================================================================
// MASTER INITIALIZATION GESTURE (ACTIVATED BY TOUCHING OVERLAY)
// ===========================================================================
let isSystemInitialized = false;
let isInitializing = false;

// If system was already authorized and running on console, attempt warm initialization
try {
  if (localStorage.getItem('hal_initialized') === 'true') {
    initializeSystem();
  }
} catch {}

async function initializeSystem() {
  if (isSystemInitialized || isInitializing) return;
  isInitializing = true;
  log('🚀 [HAL 9000] Initializing audio, sensors, and network...');

  // 1. Ensure Screen Wake Lock & Keep-Awake video are active BEFORE any async permissions
  initKeepAwakeVideo();
  requestScreenWakeLock();

  try {
    // 2. Connect WebSocket & Accelerometer knock sensor immediately
    connectWebSocket();
    window.addEventListener('devicemotion', handleDeviceMotion, { passive: true });

    // 3. Initialize Unified Web Audio Engine (Microphone permission prompt)
    await halAudio.initialize();
    goToSleep(true);

    // 5. Dismiss overlay now that permissions were granted and system is operational
    const overlay = document.getElementById('init-overlay');
    if (overlay) {
      overlay.classList.add('fade-out');
      setTimeout(() => {
        if (overlay && overlay.parentNode) overlay.remove();
      }, 400);
    }

    isSystemInitialized = true;
    try {
      localStorage.setItem('hal_initialized', 'true');
    } catch {}
    log('✅ [HAL 9000] Fully operational and standing by on Fab\'s desk.');
  } catch (err) {
    isSystemInitialized = false;
    log(`❌ [HAL 9000] Initialization error: ${err.message}`);
    const overlay = document.getElementById('init-overlay');
    if (overlay) {
      overlay.classList.remove('fade-out');
    }
  } finally {
    isInitializing = false;
  }
}

function onInitializeGesture(e) {
  // If system is already initialized and the overlay is dismissed, just keep awake
  if (isSystemInitialized && !document.getElementById('init-overlay')) {
    ensureKeepAwakeVideoPlaying();
    requestScreenWakeLock();
    return;
  }

  log('👆 [HAL 9000] Activation tap received.');

  // CRITICAL FOR IOS SAFARI:
  // DeviceMotionEvent.requestPermission() MUST be invoked synchronously within the direct
  // user gesture call stack BEFORE any async/await; otherwise WebKit revokes user activation!
  if (typeof DeviceMotionEvent !== 'undefined' && typeof DeviceMotionEvent.requestPermission === 'function') {
    DeviceMotionEvent.requestPermission()
      .then(permissionState => {
        log(`📱 [Motion] iOS DeviceMotion permission: ${permissionState}`);
      })
      .catch(err => {
        log(`⚠️ [Motion] Permission request error: ${err.message}`);
      });
  }

  // Synchronously resume Web Audio pipeline within user gesture
  if (halAudio && halAudio.audioContext && halAudio.audioContext.state === 'suspended') {
    halAudio.audioContext.resume().catch(() => {});
  }

  initKeepAwakeVideo();
  requestScreenWakeLock();

  initializeSystem().then(() => {
    wakeUp();
  });
}

if (initOverlay) {
  initOverlay.addEventListener('pointerdown', onInitializeGesture);
  initOverlay.addEventListener('click', onInitializeGesture);
  initOverlay.addEventListener('touchend', onInitializeGesture);
}

// Global tap fallback so touching anywhere on the screen triggers initialization & re-asserts keep-awake
window.addEventListener('click', onInitializeGesture);
window.addEventListener('touchend', onInitializeGesture);

// Periodic AudioContext and Keep-Awake Heartbeat (guarantees iOS Safari never leaves mic suspended)
setInterval(() => {
  if (halAudio && halAudio.isRecording && halAudio.isListeningActive) {
    if (halAudio.audioContext && halAudio.audioContext.state === 'suspended') {
      halAudio.audioContext.resume().catch(() => {});
    }
  }
}, 3000);

// Connect WebSocket immediately so backend telemetry & remote control work 24/7
connectWebSocket();

// Lock orientation to portrait
if (screen.orientation && screen.orientation.lock) {
  screen.orientation.lock('portrait').catch(() => {});
}
