/**
 * HAL 9000 Monolith Controller
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

// Calibrated vertical offset for physical aluminum monolith enclosure
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
const SLEEP_TIMEOUT_MS = 120000; // 2 minutes inactivity timeout

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
// MONOLITH STATE MACHINE & OPTICAL FACEPLATE
// ===========================================================================
function setHalState(newState) {
  currentState = newState;
  log(`🔄 [State] Transition -> ${newState}`);

  if (newState === State.SLEEPING) {
    document.body.classList.add('sleep-mode');
    // Standby: ONLY the central red LED is extinguished. Faceplate stays 100% visible 24/7!
    if (layerCenterOn) layerCenterOn.style.opacity = '0.0';
    if (layerRingOn) layerRingOn.style.opacity = '0.0';
    if (layer3LedOn) layer3LedOn.style.opacity = '0.0';
  } else {
    document.body.classList.remove('sleep-mode');
    // Active states: Central eye is illuminated
    if (layerCenterOn) layerCenterOn.style.opacity = '1.0';
    if (newState !== State.LISTENING && layerRingOn) {
      layerRingOn.style.opacity = '0.0';
    }
    if (layer3LedOn) {
      layer3LedOn.style.opacity = persistentLedOn ? '1.0' : '0.0';
    }
  }
}

function resetSleepTimer() {
  clearTimeout(sleepTimer);
  if (currentState !== State.SLEEPING) {
    sleepTimer = setTimeout(goToSleep, SLEEP_TIMEOUT_MS);
  }
}

function wakeUp() {
  if (currentState !== State.SLEEPING) return;
  log('☀️ [HAL Monolith] Waking up from Standby (Central eye illuminated).');
  if (halAudio) halAudio.setSleeping(false);
  setHalState(State.LISTENING);
  resetSleepTimer();
  requestScreenWakeLock();
  ensureKeepAwakeVideoPlaying();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'sleep_state', sleeping: false }));
  }
}

function goToSleep() {
  if (currentState === State.THINKING || currentState === State.SPEAKING) {
    resetSleepTimer();
    return;
  }
  log('🌙 [HAL Monolith] Entering Standby (Listening for enclosure knock or double-tap).');
  if (persistentLedOn) setPersistentLed(false);
  if (halAudio) halAudio.setSleeping(true);
  setHalState(State.SLEEPING);
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'sleep_state', sleeping: true }));
  }
}

// ===========================================================================
// 3 AUXILIARY SATELLITE LEDS (EMOTIONAL BODY LANGUAGE)
// ===========================================================================
function setPersistentLed(on) {
  persistentLedOn = on;
  if (layer3LedOn && currentState !== State.SLEEPING) {
    layer3LedOn.style.opacity = on ? '1.0' : '0.0';
  }
  log(`💡 [HAL Hardware] 3 Auxiliary LEDs ${on ? 'LOCKED ON' : 'TURNED OFF'}.`);
}

function clearLedAnimations() {
  clearTimeout(ledAnimTimeout);
  if (!layer3LedOn) return;
  layer3LedOn.classList.remove(
    'led-anim-chuckle', 'led-anim-laugh', 'led-anim-wink',
    'led-anim-ponder', 'led-anim-breathe', 'led-anim-warm',
    'led-anim-alert', 'led-anim-heartbeat', 'led-anim-listen-done',
    'led-anim-search', 'led-anim-api'
  );
}

function triggerLedTag(tag) {
  if (!layer3LedOn || currentState === State.SLEEPING) return;
  const t = (tag || '').toLowerCase().trim();

  if (t === 'on' || t === 'led_on' || t === 'lights_on') {
    clearLedAnimations();
    setPersistentLed(true);
    return;
  }
  if (t === 'off' || t === 'led_off' || t === 'lights_off') {
    clearLedAnimations();
    setPersistentLed(false);
    return;
  }

  clearLedAnimations();
  layer3LedOn.style.setProperty('--persistent-led', persistentLedOn ? '1.0' : '0.0');
  void layer3LedOn.offsetWidth; // Reflow to restart animation

  let animName = 'wink';
  let duration = 450;

  if (t.includes('chuckle') || t.includes('laugh')) { animName = 'chuckle'; duration = 750; }
  else if (t.includes('ponder') || t.includes('breathe') || t.includes('think')) { animName = 'breathe'; duration = 1900; }
  else if (t.includes('warm') || t.includes('glow')) { animName = 'warm'; duration = 2500; }
  else if (t.includes('alert') || t.includes('danger') || t.includes('warn')) { animName = 'alert'; duration = 550; }
  else if (t.includes('heartbeat') || t.includes('love')) { animName = 'heartbeat'; duration = 950; }
  else if (t.includes('search') || t.includes('web')) { animName = 'search'; duration = 1600; }
  else if (t.includes('api') || t.includes('task') || t.includes('calendar')) { animName = 'api'; duration = 600; }
  else if (t.includes('listen-done') || t.includes('ack')) { animName = 'listen-done'; duration = 400; }

  layer3LedOn.classList.add(`led-anim-${animName}`);
  ledAnimTimeout = setTimeout(() => {
    clearLedAnimations();
    if (layer3LedOn && currentState !== State.SLEEPING) {
      layer3LedOn.style.opacity = persistentLedOn ? '1.0' : '0.0';
    }
  }, duration);
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
      log('✅ [WS] Connected to HAL backend (v2 Clean Architecture).');
      ws.send(JSON.stringify({
        type: 'init',
        version: 'v2',
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
        } else if (msg === 'THINKING') {
          setHalState(State.THINKING);
        } else if (msg === 'WAKE') {
          wakeUp();
        } else if (msg === 'SLEEP') {
          goToSleep();
        } else if (msg === 'RELOAD') {
          log('🔄 [WS] Remote RELOAD received. Refreshing page...');
          window.location.reload();
        } else if (msg.startsWith('VOLUME:')) {
          const vol = parseInt(msg.split(':')[1], 10);
          if (!isNaN(vol)) halAudio.setVolume(vol);
        } else if (msg.startsWith('LED:')) {
          const val = msg.substring(4).trim().toUpperCase();
          if (val === 'ON') setPersistentLed(true);
          else if (val === 'OFF') setPersistentLed(false);
          else triggerLedTag(val);
        } else if (msg.startsWith('TAG:')) {
          triggerLedTag(msg.substring(4).trim());
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
  // Vocal RMS feedback -> Pulses outer acoustic ring (#layer-ring-on)
  onAudioLevel: (intensity) => {
    if (currentState === State.LISTENING) {
      if (intensity > 0.012) {
        if (layerRingOn) {
          const ringLevel = Math.min(1.0, 0.40 + (intensity - 0.012) * 3.2).toFixed(2);
          layerRingOn.style.opacity = ringLevel;
        }
      } else {
        if (layerRingOn && layerRingOn.style.opacity !== '0.0') {
          layerRingOn.style.opacity = '0.0';
        }
      }
    }
  },

  // Playback RMS feedback -> Pulses central eye (#layer-center-on)
  onPlaybackLevel: (intensity) => {
    if (currentState === State.SPEAKING && layerCenterOn) {
      layerCenterOn.style.opacity = (0.72 + intensity * 0.28).toFixed(2);
    }
  },

  // User finished speaking (1.8s silence detected) -> Send audio turn to Gemini
  onTurnComplete: (wavBytes) => {
    if (persistentLedOn) setPersistentLed(false);
    triggerLedTag('listen-done');
    setHalState(State.THINKING);

    if (ws && ws.readyState === WebSocket.OPEN) {
      log(`📤 [HalAudio] Transmitting audio turn (${wavBytes.byteLength} bytes) to Gemini.`);
      ws.send(wavBytes);
    }
    resetSleepTimer();
  },

  // HAL voice playback finished -> Resume active listening immediately
  onPlaybackStateChange: (isPlaying) => {
    if (isPlaying) {
      setHalState(State.SPEAKING);
    } else {
      setHalState(State.LISTENING);
      resetSleepTimer();
    }
  },

  // User barge-in during speech -> Send interrupt to server
  onBargeIn: () => {
    log('⚡ [HAL Monolith] Voice barge-in detected. Halting speech playback.');
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send('INTERRUPT');
    }
    setHalState(State.LISTENING);
    resetSleepTimer();
  },

  // Standby double-tap acoustic wake
  onWake: (reason) => {
    log(`🥁 [HAL Monolith] Acoustic wake triggered (${reason}).`);
    triggerLedTag('wink');
    wakeUp();
  },

  onLog: log,
});

// ===========================================================================
// HARDWARE ACCELEROMETER KNOCK SENSOR (PHYSICAL MONOLITH INTERACTION)
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

      if (currentState === State.SLEEPING) {
        triggerLedTag('wink');
        wakeUp();
      } else if (currentState === State.SPEAKING) {
        log('💥 [Motion] Knock barge-in during speech. Halting playback.');
        halAudio.stopPlayback();
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send('INTERRUPT');
        }
        setHalState(State.LISTENING);
      }
    }
  }
}

// ===========================================================================
// 24/7 SCREEN WAKE LOCK & KEEP-AWAKE MP4
// ===========================================================================
const SILENT_KEEP_AWAKE_MP4 = 'data:video/mp4;base64,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';

let keepAwakeVideo = null;
let wakeLockSentinel = null;

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
    keepAwakeVideo.muted = true;
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
    document.body.appendChild(keepAwakeVideo);
    keepAwakeVideo.play().catch(() => {});
  } catch (e) {}
}

function ensureKeepAwakeVideoPlaying() {
  if (keepAwakeVideo && keepAwakeVideo.paused) {
    keepAwakeVideo.play().catch(() => {});
  }
}

async function requestScreenWakeLock() {
  if ('wakeLock' in navigator) {
    try {
      if (wakeLockSentinel && !wakeLockSentinel.released) return;
      wakeLockSentinel = await navigator.wakeLock.request('screen');
      log('🔒 [WakeLock] Screen Wake Lock acquired.');
      wakeLockSentinel.addEventListener('release', () => {
        wakeLockSentinel = null;
        setTimeout(requestScreenWakeLock, 1000);
      });
    } catch (e) {}
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

// ===========================================================================
// MASTER INITIALIZATION GESTURE (ACTIVATED BY TOUCHING OVERLAY)
// ===========================================================================
let isSystemInitialized = false;

async function initializeSystem() {
  if (isSystemInitialized) return;
  isSystemInitialized = true;
  log('🚀 [HAL Monolith] Initializing audio, sensors, and network...');

  if (initOverlay) {
    initOverlay.classList.add('fade-out');
    setTimeout(() => {
      if (initOverlay && initOverlay.parentNode) initOverlay.remove();
    }, 400);
  }

  try {
    // 1. Connect WebSocket
    connectWebSocket();

    // 2. Initialize Unified Web Audio Engine
    await halAudio.initialize();
    setHalState(State.LISTENING);
    resetSleepTimer();

    // 3. Screen Wake Lock & Video Keep-Awake
    initKeepAwakeVideo();
    requestScreenWakeLock();

    // 4. Accelerometer knock sensor
    window.addEventListener('devicemotion', handleDeviceMotion, { passive: true });

    log('✅ [HAL Monolith] Fully operational and standing by on Fab\'s desk.');
  } catch (err) {
    isSystemInitialized = false;
    log(`❌ [HAL Monolith] Initialization error: ${err.message}`);
  }
}

function onInitializeGesture(e) {
  if (isSystemInitialized) return;
  if (e && e.cancelable) e.preventDefault();

  // iOS Safari requires DeviceMotionEvent permission to be requested synchronously inside gesture
  if (typeof DeviceMotionEvent !== 'undefined' && typeof DeviceMotionEvent.requestPermission === 'function') {
    DeviceMotionEvent.requestPermission().catch(() => {});
  }
  initializeSystem();
}

if (initOverlay) {
  initOverlay.addEventListener('click', onInitializeGesture);
  initOverlay.addEventListener('touchend', onInitializeGesture, { passive: false });
}

// Connect WebSocket immediately so backend telemetry & remote control work 24/7
connectWebSocket();

// Attach motion listener immediately so enclosure knocks can activate system behind glass
window.addEventListener('devicemotion', (e) => {
  if (!isSystemInitialized) {
    onInitializeGesture(e);
  } else {
    handleDeviceMotion(e);
  }
}, { passive: true });

// Lock orientation to portrait
if (screen.orientation && screen.orientation.lock) {
  screen.orientation.lock('portrait').catch(() => {});
}
