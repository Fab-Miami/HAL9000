import { AudioRecorder } from './audio-recorder.js';
import { AudioPlayer } from './audio-player.js';
import { WsClient } from './ws-client.js';
import { SpeechRecognizer } from './speech-recognizer.js';
import { MotionDetector } from './motion-detector.js';

// DOM Elements
const appEl = document.getElementById('app');
const halStage = document.getElementById('hal-stage');
const layerEverythingOff = document.getElementById('layer-everything-off');
const layer3LedOn = document.getElementById('layer-3-led-on');
const layerCenterOn = document.getElementById('layer-center-on');
const layerRingOn = document.getElementById('layer-ring-on');
const initOverlay = document.getElementById('init-overlay');

// System States
const State = {
  IDLE: 'IDLE',
  LISTENING: 'LISTENING',
  THINKING: 'THINKING',
  PROCESSING: 'PROCESSING',
  SLEEPING: 'SLEEPING',
};

let currentState = State.IDLE;
let wakeLockSentinel = null;
let wakeLockFailedLogged = false;
let tapCount = 0;
let tapTimer = null;
let conversationInterval = null;
let conversationTimeRemaining = 0;

// Subsystems declared early so log/sendTelemetry does not trigger Temporal Dead Zone ReferenceError
let wsClient = null;
let audioPlayer = null;
let audioRecorder = null;
let speechRecognizer = null;
let motionDetector = null;

// Sleep Mode State
let sleepTimer = null;
let pendingSleepCommand = false;
const SLEEP_TIMEOUT_MS = 120000; // 2 minutes
 
function sendTelemetry(msg) {
  if (wsClient && wsClient.isConnected) {
    try {
      wsClient.sendJson({ type: 'telemetry', message: msg });
    } catch (e) {}
  }
}

function wakeUp() {
  if (currentState !== State.SLEEPING) return;
  
  log('☀️ HAL waking up from Standby (Central eye illuminated).');
  document.body.classList.remove('sleep-mode');
  if (layerCenterOn) layerCenterOn.style.opacity = '1.0';
  if (typeof audioRecorder !== 'undefined' && audioRecorder) {
    audioRecorder.sleeping = false;
  }
  if (typeof speechRecognizer !== 'undefined' && speechRecognizer) {
    speechRecognizer.setSleeping(false);
    speechRecognizer.resume();
  }
  setState(State.LISTENING);
  resetSleepTimer();
  requestScreenWakeLock();
  ensureKeepAwakeVideoPlaying();
}

function goToSleep() {
  if (currentState === State.PROCESSING || currentState === State.THINKING) {
    resetSleepTimer();
    return;
  }
  
  log('🌙 HAL entering Standby (Listening for enclosure double-tap or "HAL wake up").');
  if (persistentLedOn) setPersistentLed(false);
  document.body.classList.add('sleep-mode');
  // Standby mode: ONLY central LED turns off. Faceplate stays 100% visible at all times!
  if (layerCenterOn) layerCenterOn.style.opacity = '0.0';
  if (layerRingOn) layerRingOn.style.opacity = '0.0';
  if (layer3LedOn) layer3LedOn.style.opacity = '0.0';
  if (typeof audioRecorder !== 'undefined' && audioRecorder) {
    audioRecorder.sleeping = true;
  }
  if (typeof speechRecognizer !== 'undefined' && speechRecognizer) {
    speechRecognizer.setSleeping(true);
    speechRecognizer.resume();
  }
  setState(State.SLEEPING);
}

function resetSleepTimer() {
  clearTimeout(sleepTimer);
  if (currentState !== State.SLEEPING) {
    sleepTimer = setTimeout(goToSleep, SLEEP_TIMEOUT_MS);
  }
}

// Logging with visual and remote telemetry
function log(msg) {
  console.log(msg);
  sendTelemetry(msg);
}

// State Machine Update
function setState(newState) {
  currentState = newState;
  document.body.className = document.body.className
    .replace(/state-\w+/g, '')
    .trim();
  if (newState === State.LISTENING || newState === State.IDLE || newState === State.THINKING) {
    resetToStandby();
  }

  log(`🔄 State Transition -> ${newState}`);
}

// Persistent LED State: stays ON until next prompt or explicit OFF command
let persistentLedOn = false;

function setPersistentLed(on) {
  persistentLedOn = on;
  if (layer3LedOn) {
    layer3LedOn.style.opacity = on ? '1.0' : '0.0';
  }
  log(`💡 [HAL Hardware] 3 Auxiliary LEDs ${on ? 'LOCKED ON (will stay on until next prompt)' : 'TURNED OFF'}.`);
}

// Standby State: Center dot strictly ON and STATIC; listening ring OFF; LEDs follow persistent state
function resetToStandby() {
  if (currentState === State.SLEEPING) return;
  if (layerCenterOn) layerCenterOn.style.opacity = '1.0';
  if (layerRingOn) layerRingOn.style.opacity = '0.0';
  if (layer3LedOn) layer3LedOn.style.opacity = persistentLedOn ? '1.0' : '0.0';
}

// HAL 2026 Optical Subsystem: 3 Auxiliary Satellite LEDs (Emotional Body Language)
let ledAnimTimeout = null;

function clearLedAnimations() {
  clearTimeout(ledAnimTimeout);
  if (!layer3LedOn) return;
  layer3LedOn.classList.remove(
    'led-anim-chuckle',
    'led-anim-laugh',
    'led-anim-wink',
    'led-anim-ponder',
    'led-anim-breathe',
    'led-anim-warm',
    'led-anim-alert',
    'led-anim-heartbeat',
    'led-anim-listen-done',
    'led-anim-search',
    'led-anim-api'
  );
}

function triggerLedExpression(exprName, durationMs = 1000) {
  if (!layer3LedOn) return;
  clearLedAnimations();

  // Set CSS variable for return opacity
  layer3LedOn.style.setProperty('--persistent-led', persistentLedOn ? '1.0' : '0.0');

  // Trigger reflow to restart animation if repeated
  void layer3LedOn.offsetWidth;

  const className = `led-anim-${exprName.toLowerCase()}`;
  layer3LedOn.classList.add(className);

  ledAnimTimeout = setTimeout(() => {
    clearLedAnimations();
    if (layer3LedOn) {
      layer3LedOn.style.opacity = persistentLedOn ? '1.0' : '0.0';
    }
  }, durationMs);
}

function handleEmotionTag(tag) {
  log(`💡 [HAL Emotion Tag] Received: ${tag}`);
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
  
  if (t === 'chuckle' || t === 'laugh' || t === 'amuse') {
    triggerLedExpression('chuckle', 750);
  } else if (t === 'wink' || t === 'cheeky' || t === 'tease') {
    triggerLedExpression('wink', 450);
  } else if (t === 'ponder' || t === 'breathe' || t === 'think') {
    triggerLedExpression('breathe', 1900);
  } else if (t === 'warm' || t === 'glow' || t === 'cozy') {
    triggerLedExpression('warm', 2500);
  } else if (t === 'alert' || t === 'danger' || t === 'warn' || t === 'shock') {
    triggerLedExpression('alert', 550);
  } else if (t === 'heartbeat' || t === 'love' || t === 'emotion') {
    triggerLedExpression('heartbeat', 950);
  } else if (t === 'search' || t === 'internet' || t === 'web') {
    triggerLedExpression('search', 1600);
  } else if (t === 'api' || t === 'task' || t === 'calendar') {
    triggerLedExpression('api', 600);
  } else if (t === 'listen-done' || t === 'ack' || t === 'received') {
    triggerLedExpression('listen-done', 400);
  } else {
    // Default expressive blink
    triggerLedExpression('wink', 450);
  }
}

// Visual Modulation: Authentic to 2001: A Space Odyssey
// =========================================================================================
// CRITICAL HARDWARE & UI REQUIREMENT - DO NOT REMOVE OR BREAK:
// The outer acoustic ring (#layer-ring-on / hal2026_ring_on.png) MUST visibly blink and
// pulse with the user's voice intensity whenever the user is speaking in State.LISTENING.
// This provides immediate visual confirmation to the user that HAL is hearing their message!
// =========================================================================================
function updateVisuals(intensity, isHalSpeech = false) {
  if (currentState === State.SLEEPING) return;

  // Normalize intensity to 0.0 - 1.0 range
  const norm = Math.min(1.0, Math.max(0.0, intensity));

  if (isHalSpeech) {
    // When HAL speaks:
    // 1. Listening ring is strictly OFF
    if (layerRingOn) {
      layerRingOn.style.opacity = '0.0';
    }
    // 2. Central dot slightly blinks with speech audio waveform
    if (layerCenterOn) {
      const halBlink = (0.72 + norm * 0.28).toFixed(2);
      layerCenterOn.style.opacity = halBlink;
    }
  } else {
    // When HAL is in listen mode (user speaks or standby):
    // Central light is kept illuminated in a static way (never animated/dimmed)
    if (layerCenterOn && layerCenterOn.style.opacity !== '1.0') {
      layerCenterOn.style.opacity = '1.0';
    }

    if (norm > 0.012) {
      // User is speaking: visibly animate (blink/pulse) the outer ring with voice energy
      if (layerRingOn) {
        const ringLevel = Math.min(1.0, 0.40 + (norm - 0.012) * 3.2).toFixed(2);
        layerRingOn.style.opacity = ringLevel;
      }
    } else {
      // Standby / silence between words: ring strictly OFF
      if (layerRingOn && layerRingOn.style.opacity !== '0.0') {
        layerRingOn.style.opacity = '0.0';
      }
    }
  }
}

// Instantiate Subsystems
audioPlayer = new AudioPlayer({
  onPlaybackStateChange: (isPlaying) => {
    if (isPlaying) {
      if (audioRecorder) audioRecorder.muted = true;
      if (speechRecognizer) speechRecognizer.pause();
      setState(State.PROCESSING);
    } else {
      if (audioRecorder) audioRecorder.muted = false;
      if (speechRecognizer) speechRecognizer.resume();
      resetToStandby();
      stopInteraction();
    }
  },
  onAudioLevel: (intensity) => {
    if (currentState === State.PROCESSING) {
      updateVisuals(intensity, true); // HAL Voice slightly blinks central dot
    }
  },
  onLog: log,
});

/**
 * Calibrated wake-word validator.
 * In sleep mode, HAL ONLY wakes on direct wake commands ("HAL wake up", "wake up HAL", "wake up")
 * including iOS Safari speech recognition's natural phonetic transcriptions ("How to wake up", "How wake up", "Al wake up").
 * Rejects general ambient speech that doesn't contain wake commands.
 */
function isHalWakeWord(text) {
  if (!text) return false;
  const clean = text.trim().toLowerCase().replace(/[.,!?;:]/g, '').replace(/\s+/g, ' ');

  // 1. Must contain "wake up"
  if (!/\bwake\s*up\b/i.test(clean)) {
    return false;
  }

  // 2. Reject long ambient sentences (avoid waking on ambient conversation talking about waking up)
  const words = clean.split(' ').filter(Boolean);
  if (words.length > 7) {
    return false;
  }

  // 3. Match wake phrases addressed to HAL or iOS phonetic variations (how, how to, al, hell):
  // e.g. "hal wake up", "how to wake up", "how to wake up wake up", "how wake up", "wake up hal", "wake up", "wake up wake up"
  const wakePattern = /^(?:(?:hey|ok|okay|hi|hello|please)\s+)?(?:(?:hal|how\s+to|how|al|hell)\s+)?(?:wake\s*up\s*)+(?:(?:hal|how|al|please)\s*)*$/i;
  if (wakePattern.test(clean)) {
    return true;
  }

  // Any short phrase containing (hal|how|al) + wake up
  if (/\b(?:hal|how|al)\b/i.test(clean) && /\bwake\s*up\b/i.test(clean)) {
    return true;
  }

  // Short direct "wake up"
  if (/^(?:please\s+)?(?:wake\s*up\s*)+(?:please)?$/i.test(clean)) {
    return true;
  }

  return false;
}

speechRecognizer = new SpeechRecognizer({
  onFinalSpeech: (text) => {
    if (currentState === State.SLEEPING) {
      if (!isHalWakeWord(text)) {
        log(`💤 [Sleeping] Ignored non-wake speech: "${text}"`);
        return;
      }
      log(`☀️ [Sleeping] Verified wake phrase ("${text}") + 2s silence! Waking up HAL.`);
      wakeUp();
    } else {
      resetSleepTimer();
    }

    if (persistentLedOn) {
      setPersistentLed(false);
    }
    if (text) {
      // Instantaneous hardware feedback: End of listening mode acknowledged
      triggerLedExpression('listen-done', 400);
    }
    if (wsClient && wsClient.isConnected && text) {
      log(`📤 [SpeechRecognizer] Sending transcript to HAL: "${text}"`);
      wsClient.sendJson({ type: 'user_text', text: text });
      setState(State.THINKING);
    }
  },
  onInterimSpeech: (text) => {
    if (currentState === State.SLEEPING) {
      // In sleep mode, strictly wait for finalized phrase + 2s silence.
      // Do NOT wake on partial speech or interim results.
      return;
    }
    resetSleepTimer();
    if (persistentLedOn && text && text.trim()) {
      setPersistentLed(false);
    }
    // CRITICAL HARDWARE FEEDBACK: Outer ring (#layer-ring-on) blinks to visually acknowledge user speech
    if (currentState !== State.PROCESSING && currentState !== State.SLEEPING && text && text.trim()) {
      if (layerRingOn && parseFloat(layerRingOn.style.opacity || '0') < 0.6) {
        layerRingOn.style.opacity = '0.85';
        setTimeout(() => {
          if (currentState !== State.PROCESSING && currentState !== State.SLEEPING) {
            if (layerRingOn && parseFloat(layerRingOn.style.opacity || '0') === 0.85) {
              layerRingOn.style.opacity = '0.25';
            }
          }
        }, 120);
      }
    }
  },
  onStatusChange: (status) => {
    log(`🗣️ SpeechRecognizer status: ${status}`);
  },
  onLog: log,
});

motionDetector = new MotionDetector({
  threshold: 2.5,
  onKnock: (magnitude) => {
    // MOTION DETECTOR IS EXCLUSIVELY FOR WAKE UP IN SLEEP MODE!
    // If HAL is awake or speaking, never listen or intercept.
    if (currentState !== State.SLEEPING) return;

    log(`💥 Enclosure knock detected via accelerometer (${magnitude.toFixed(1)} m/s²)! Waking up HAL.`);
    triggerLedExpression('wink', 450);
    wakeUp();
    requestScreenWakeLock();
    ensureKeepAwakeVideoPlaying();
  },
  onLog: log,
});

audioRecorder = new AudioRecorder({
  onAudioData: (pcmBuffer) => {
    // Single Input Pipeline: SpeechRecognizer is primary; only stream raw PCM as fallback if Web Speech is unsupported
    if (!speechRecognizer.isSupported && wsClient && wsClient.isConnected) {
      wsClient.sendAudio(pcmBuffer);
    }
  },
  onAudioLevel: (intensity) => {
    if (currentState !== State.PROCESSING && currentState !== State.SLEEPING) {
      updateVisuals(intensity, false); // User Voice Modulates Acoustic Ring
    }
  },
  onSpeechDetected: () => {
    if (currentState === State.PROCESSING) {
      triggerVoiceBargeIn();
    }
    if (persistentLedOn) {
      setPersistentLed(false);
    }
  },
  onWakeTrigger: (reason) => {
    log(`🥁 Enclosure double-tap detected acoustically (${reason})! Waking up HAL.`);
    triggerLedExpression('wink', 450);
    if (currentState === State.SLEEPING) {
      wakeUp();
    }
    requestScreenWakeLock();
    ensureKeepAwakeVideoPlaying();
  },
  onLog: log,
});

wsClient = new WsClient({
  onAudioReceived: (arrayBuffer) => {
    if (currentState !== State.PROCESSING) {
      setState(State.PROCESSING);
    }
    audioPlayer.playChunk(arrayBuffer);
  },
  onStringReceived: (text) => {
    if (text.startsWith('VOLUME:')) {
      const vol = parseInt(text.split(':')[1], 10);
      if (!isNaN(vol)) {
        audioPlayer.setVolumeLevel(vol);
        log(`🔊 HAL adjusted vocal volume to: ${vol}/10`);
      }
    } else if (text.startsWith('LED:')) {
      const state = text.substring(4).trim().toUpperCase();
      if (state === 'ON') {
        setPersistentLed(true);
      } else if (state === 'OFF') {
        setPersistentLed(false);
      } else if (state === 'SEARCH') {
        log('🔍 [HAL Hardware] Live Search active -> triggering LED:SEARCH animation.');
        triggerLedExpression('search', 1600);
      } else if (state === 'API') {
        log('⚡ [HAL Hardware] API Tool execution -> triggering LED:API animation.');
        triggerLedExpression('api', 600);
      } else if (state === 'LISTEN_DONE' || state === 'ACK') {
        log('👂 [HAL Hardware] End of listening -> triggering LED:LISTEN-DONE animation.');
        triggerLedExpression('listen-done', 400);
      }
    } else if (text.startsWith('TAG:')) {
      const tag = text.substring(4).trim();
      handleEmotionTag(tag);
    } else if (text === 'THINKING') {
      log('🤔 Received THINKING signal from server.');
      setState(State.THINKING);
    } else if (text === 'SLEEP') {
      log('🌙 Received SLEEP signal from server. Queueing sleep mode for after voice playback.');
      pendingSleepCommand = true;
    } else if (text === 'DONE') {
      log('🏁 Received DONE signal from server.');
      audioPlayer.finishStream();
    }
  },
  onStatusChange: (status) => {
    log(`🌐 WebSocket: ${status}`);
    if (status === 'CONNECTED') {
      wsClient.sendJson({ type: 'init', volume: audioPlayer.volumeLevel });
      log(`🎛️ Synced hardware volume ${audioPlayer.volumeLevel}/10 to HAL backend.`);
    }
  },
  onLog: log,
});

// Interaction Flow
function stopInteraction() {
  setState(State.LISTENING);
  log('💬 Audio response finished. Resuming continuous listening.');
  
  if (pendingSleepCommand) {
    pendingSleepCommand = false;
    goToSleep();
  } else {
    resetSleepTimer();
  }

  try {
    audioRecorder.start();
  } catch (e) {}
}

function startConversationTimer(seconds) {
  clearConversationTimer();
  conversationTimeRemaining = seconds;

  conversationInterval = setInterval(() => {
    conversationTimeRemaining--;

    if (conversationTimeRemaining <= 0) {
      clearConversationTimer();
      log('⏳ Continuous conversation mode timed out.');
    }
  }, 1000);
}

function clearConversationTimer() {
  if (conversationInterval) {
    clearInterval(conversationInterval);
    conversationInterval = null;
  }
}

// Barge-in (Interruption of HAL speech when user speaks)
function triggerVoiceBargeIn() {
  log('⚡ User voice barge-in detected! Halting HAL speech playback immediately.');
  audioPlayer.stopPlayback();
  wsClient.sendInterrupt();
  if (speechRecognizer) speechRecognizer.resume();
  setState(State.LISTENING);
}

// ==========================================================================
// PERMANENT SCREEN WAKE LOCK & KEEP-AWAKE SUBSYSTEM
// HARD ARCHITECTURAL REQUIREMENT:
// The hosting iPhone is permanently mounted inside the physical aluminum 
// desktop monolith on Fab's desk in Miami and permanently plugged into continuous 
// wall power.
// - NEVER turn the screen black or dim the faceplate artwork.
// - Battery saving logic is STRICTLY FORBIDDEN.
// - The faceplate (#layer-everything-off) must remain 100% visible (opacity: 1.0) 24/7.
// - Standby mode is expressed EXCLUSIVELY by extinguishing the central red LED.
// ==========================================================================

const SILENT_KEEP_AWAKE_MP4 = 'data:video/mp4;base64,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';

let keepAwakeVideo = null;

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

    const playPromise = keepAwakeVideo.play();
    if (playPromise !== undefined) {
      playPromise
        .then(() => log('📺 Silent Keep-Awake video active (Prevents iOS screen dimming & auto-lock).'))
        .catch((err) => log(`Note: Keep-Awake video play pending user gesture: ${err.message}`));
    }
  } catch (err) {
    log(`Keep-Awake video init note: ${err.message}`);
  }
}

function ensureKeepAwakeVideoPlaying() {
  if (keepAwakeVideo && keepAwakeVideo.paused) {
    keepAwakeVideo.play().catch(() => {});
  }
}

let isAcquiringWakeLock = false;

async function requestScreenWakeLock() {
  if (isAcquiringWakeLock) return;
  if ('wakeLock' in navigator) {
    try {
      if (wakeLockSentinel && !wakeLockSentinel.released) {
        return;
      }
      isAcquiringWakeLock = true;
      wakeLockSentinel = await navigator.wakeLock.request('screen');
      log('🔒 Screen Wake Lock active (Display will stay ON permanently).');

      wakeLockSentinel.addEventListener('release', () => {
        log('🔓 Screen Wake Lock was released by system. Scheduling re-acquisition...');
        wakeLockSentinel = null;
        setTimeout(() => {
          if (document.visibilityState === 'visible') {
            requestScreenWakeLock();
          }
        }, 1000);
      });
    } catch (err) {
      if (!wakeLockFailedLogged) {
        console.log(`⚠️ Wake Lock request note: ${err.name}, ${err.message} (Keep-Awake video maintains screen ON)`);
        wakeLockFailedLogged = true;
      }
      wakeLockSentinel = null;
    } finally {
      isAcquiringWakeLock = false;
    }
  } else {
    log('⚠️ Screen Wake Lock API not supported natively; relying on Keep-Awake video.');
  }
  ensureKeepAwakeVideoPlaying();
}

document.addEventListener('visibilitychange', async () => {
  if (document.visibilityState === 'visible') {
    log('📱 App visible: re-asserting Screen Wake Lock and Keep-Awake video.');
    await requestScreenWakeLock();
    ensureKeepAwakeVideoPlaying();
  }
});

// Periodic heartbeat: Re-check every 15s to guarantee the display never sleeps
setInterval(() => {
  if (document.visibilityState === 'visible') {
    if (!wakeLockSentinel || wakeLockSentinel.released) {
      requestScreenWakeLock();
    }
    ensureKeepAwakeVideoPlaying();
  }
}, 15000);

// Master Initialization (Triggered by one tap on INITIALIZE SYSTEM)
async function initializeSystem() {
  log('🚀 Initializing HAL 9000 system on iPhone...');

  // Fade out and completely remove initialization overlay from DOM to destroy GPU CALayers
  if (initOverlay) {
    initOverlay.classList.add('fade-out');
    setTimeout(() => {
      if (initOverlay && initOverlay.parentNode) {
        initOverlay.remove();
      }
    }, 400);
  }

  try {
    // 1. Ensure secure context
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error('iOS requires HTTPS for microphone access. Please open https://' + window.location.host);
    }

    // 2. Connect to WebSocket first so telemetry works immediately
    wsClient.connect();

    // 3. Initialize & Warm up Audio Player pipeline
    await audioPlayer.initialize();

    // 4. Start Microphone Capture (keeps mediaStream alive permanently)
    await audioRecorder.start();
    speechRecognizer.start();
    setState(State.LISTENING);
    resetSleepTimer();

    // 5. Request permanent Screen Wake Lock & start keep-awake video
    initKeepAwakeVideo();
    requestScreenWakeLock().catch((e) => log(`WakeLock note: ${e.message}`));

    // 6. Ensure accelerometer knock detection is started
    if (motionDetector) {
      await motionDetector.initialize();
    }

    log('✅ HAL 9000 fully operational and standing by.');
  } catch (err) {
    log(`❌ Initialization error: ${err.message}`);
  }
}

// Synchronous iOS gesture trigger for Accelerometer / Motion Sensors
function onInitializeGesture(e) {
  if (e && e.type === 'touchend') {
    e.preventDefault();
  }
  // CRITICAL FOR IOS SAFARI:
  // DeviceMotionEvent.requestPermission() MUST be invoked synchronously within the direct
  // user gesture call stack BEFORE any async/await; otherwise WebKit revokes user activation!
  if (motionDetector) {
    motionDetector.requestPermissionSync();
  }
  initializeSystem();
}

if (initOverlay) {
  initOverlay.addEventListener('click', onInitializeGesture);
  initOverlay.addEventListener('touchend', onInitializeGesture);
}

// Physical enclosure constraint: Phone is permanently sealed behind the glass fisheye lens.
// The screen is physically inaccessible. Enclosure wake is handled strictly via MotionDetector (accelerometer).

// Start directly in enclosure mode with calibrated vertical offset
document.body.classList.remove('mode-desk');
document.body.classList.add('mode-enclosure');

const halContainer = document.getElementById('hal-container');
const eyeOffsetY = -146.67;
if (halContainer) {
  halContainer.style.transform = `translateY(${eyeOffsetY}px)`;
}

// Ignore orientation sensor (lock to portrait)
if (screen.orientation && screen.orientation.lock) {
  screen.orientation.lock('portrait').catch((e) => log('Orientation lock note: ' + e.message));
} else if (window.screen && window.screen.lockOrientation) {
  window.screen.lockOrientation('portrait');
}

log('📱 Initialized HAL 9000 pure optical mode (ZERO text UI).');

