import { AudioRecorder } from './audio-recorder.js';
import { AudioPlayer } from './audio-player.js';
import { WsClient } from './ws-client.js';

// DOM Elements
const appEl = document.getElementById('app');
const halStage = document.getElementById('hal-stage');
const halGlow = document.getElementById('hal-glow');
const halCore = document.getElementById('hal-core');
const initOverlay = document.getElementById('init-overlay');
const btnInit = document.getElementById('btn-init');
const holdIndicator = document.getElementById('hold-indicator');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const diagPanel = document.getElementById('diag-panel');
const btnCloseDiag = document.getElementById('btn-close-diag');
const diagState = document.getElementById('diag-state');
const diagWs = document.getElementById('diag-ws');
const diagHostInput = document.getElementById('diag-host-input');
const diagIntensity = document.getElementById('diag-intensity');
const diagWakeLock = document.getElementById('diag-wakelock');
const diagConvTimer = document.getElementById('diag-conv-timer');
const btnSaveHost = document.getElementById('btn-save-host');
const btnReconnect = document.getElementById('btn-reconnect');
const statusBar = document.getElementById('status-bar');

// System States
const State = {
  IDLE: 'IDLE',
  LISTENING: 'LISTENING',
  THINKING: 'THINKING',
  PROCESSING: 'PROCESSING',
};

let currentState = State.IDLE;
let wakeLockSentinel = null;
let tapCount = 0;
let tapTimer = null;
let conversationInterval = null;
let conversationTimeRemaining = 0;

// Logging with visual telemetry
function log(msg) {
  console.log(msg);
}

// State Machine Update
function setState(newState) {
  currentState = newState;
  document.body.className = document.body.className
    .replace(/state-\w+/g, '')
    .trim();
  document.body.classList.add(`state-${newState.toLowerCase()}`);

  if (diagState) {
    diagState.textContent = newState;
  }

  if (statusText) {
    statusText.textContent = newState;
  }

  if (statusDot) {
    statusDot.className = newState === State.PROCESSING ? 'processing' : (wsClient && wsClient.isConnected ? 'connected' : '');
  }

  log(`🔄 State Transition -> ${newState}`);
}

// Visual Glow & Core Modulation Logic
function updateVisuals(intensity, isHalSpeech = false) {
  // Normalize intensity to 0.0 - 1.0 range
  const norm = Math.min(1.0, Math.max(0.0, intensity));

  if (isHalSpeech) {
    // HAL is speaking: Modulate ONLY the Center LED Diode (#hal-core)
    // Locked 96px diameter in enclosure mode; subtle scale bloom up to 1.15x
    const coreScale = 1.0 + norm * 0.15;
    const coreOpacity = 0.85 + norm * 0.15;
    if (halCore) {
      halCore.style.transform = `translate(-50%, -50%) scale(${coreScale.toFixed(3)})`;
      halCore.style.opacity = coreOpacity.toFixed(2);
    }
  } else {
    // User is speaking: Modulate ONLY the Background Halo (#hal-glow)
    // Locked 80vw diameter; subtle luminescence dip (1.0 -> 0.85) on voice activity
    const glowScale = 1.0;
    const glowOpacity = 1.0 - norm * 0.15;
    if (halGlow) {
      halGlow.style.transform = `translate(-50%, -50%) scale(${glowScale})`;
      halGlow.style.opacity = glowOpacity.toFixed(2);
    }
  }

  if (diagIntensity) {
    diagIntensity.style.width = `${Math.round(norm * 100)}%`;
  }
}

// Instantiate Subsystems
const audioPlayer = new AudioPlayer({
  onPlaybackStateChange: (isPlaying) => {
    if (isPlaying) {
      setState(State.PROCESSING);
    } else {
      stopInteraction();
    }
  },
  onAudioLevel: (intensity) => {
    if (currentState === State.PROCESSING) {
      updateVisuals(intensity, true); // HAL Voice Modulates #hal-core
    }
  },
  onLog: log,
});

const audioRecorder = new AudioRecorder({
  onAudioData: (pcmBuffer) => {
    if (wsClient && wsClient.isConnected) {
      wsClient.sendAudio(pcmBuffer);
    }
  },
  onAudioLevel: (intensity) => {
    if (currentState !== State.PROCESSING) {
      updateVisuals(intensity, false); // User Voice Modulates #hal-glow
    }
  },
  onSpeechDetected: () => {
    if (currentState === State.PROCESSING) {
      triggerVoiceBargeIn();
    }
  },
  onLog: log,
});

const wsClient = new WsClient({
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
    } else if (text === 'THINKING') {
      log('🤔 Received THINKING signal from server.');
      setState(State.THINKING);
    } else if (text === 'DONE') {
      log('🏁 Received DONE signal from server.');
      audioPlayer.finishStream();
    }
  },
  onStatusChange: (status) => {
    if (diagWs) diagWs.textContent = status;
    if (status === 'CONNECTED') {
      wsClient.sendJson({ type: 'init', volume: audioPlayer.volumeLevel });
      log(`🎛️ Synced hardware volume ${audioPlayer.volumeLevel}/10 to HAL backend.`);
    }
    if (statusText && currentState === State.IDLE) {
      statusText.textContent = status === 'CONNECTED' ? 'ONLINE' : status;
    }
    if (statusDot) {
      statusDot.className = status === 'CONNECTED' ? 'connected' : '';
    }
  },
  onLog: log,
});

// Interaction Flow
function stopInteraction() {
  setState(State.LISTENING);
  log('💬 Audio response finished. Resuming continuous listening.');

  try {
    audioRecorder.start();
  } catch (e) {}
}

function startConversationTimer(seconds) {
  clearConversationTimer();
  conversationTimeRemaining = seconds;

  if (diagConvTimer) diagConvTimer.textContent = `${conversationTimeRemaining}s`;

  conversationInterval = setInterval(() => {
    conversationTimeRemaining--;
    if (diagConvTimer) diagConvTimer.textContent = `${conversationTimeRemaining}s`;

    if (conversationTimeRemaining <= 0) {
      clearConversationTimer();
      log('⏳ Continuous conversation mode timed out.');
      if (diagConvTimer) diagConvTimer.textContent = 'INACTIVE';
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
  setState(State.LISTENING);
}

// Screen Wake Lock
async function requestScreenWakeLock() {
  if ('wakeLock' in navigator) {
    try {
      wakeLockSentinel = await navigator.wakeLock.request('screen');
      log('🔒 Screen Wake Lock active (Display will stay ON).');
      if (diagWakeLock) diagWakeLock.textContent = 'ACTIVE';

      wakeLockSentinel.addEventListener('release', () => {
        log('🔓 Screen Wake Lock was released.');
        if (diagWakeLock) diagWakeLock.textContent = 'RELEASED';
      });
    } catch (err) {
      log(`⚠️ Wake Lock error: ${err.name}, ${err.message}`);
      if (diagWakeLock) diagWakeLock.textContent = 'FAILED';
    }
  } else {
    log('⚠️ Screen Wake Lock API not supported on this browser.');
    if (diagWakeLock) diagWakeLock.textContent = 'UNSUPPORTED';
  }
}

document.addEventListener('visibilitychange', async () => {
  if (wakeLockSentinel !== null && document.visibilityState === 'visible') {
    await requestScreenWakeLock();
  }
});

// Master Initialization (Triggered by one tap on INITIALIZE SYSTEM)
async function initializeSystem() {
  log('🚀 Initializing HAL 9000 system on iPhone...');

  // Always fade out initialization overlay immediately into pure black
  if (initOverlay) {
    initOverlay.classList.add('fade-out');
  }

  try {
    // 1. Ensure secure context
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error('iOS requires HTTPS for microphone access. Please open https://' + window.location.host);
    }

    // 2. Initialize & Warm up Audio Player pipeline
    await audioPlayer.initialize();

    // 3. Connect to WebSocket
    wsClient.connect();

    // 4. Start Microphone Capture (keeps mediaStream alive permanently)
    await audioRecorder.start();
    setState(State.LISTENING);

    // 5. Request permanent Screen Wake Lock
    requestScreenWakeLock().catch((e) => log(`WakeLock note: ${e.message}`));

    log('✅ HAL 9000 fully operational and standing by.');
  } catch (err) {
    log(`❌ Initialization error: ${err.message}`);
    alert(`Microphone permission is required to operate HAL 9000: ${err.message}`);
  }
}

if (btnInit) {
  btnInit.addEventListener('click', initializeSystem);
  btnInit.addEventListener('touchend', (e) => {
    e.preventDefault();
    initializeSystem();
  });
}

// Telemetry / Diagnostic HUD Controls (Tap status bar 3x)
if (statusBar) {
  statusBar.addEventListener('click', () => {
    tapCount++;
    clearTimeout(tapTimer);
    tapTimer = setTimeout(() => { tapCount = 0; }, 600);

    if (tapCount >= 3) {
      tapCount = 0;
      if (diagPanel) {
        diagPanel.classList.toggle('hidden');
      }
    }
  });
}

if (btnCloseDiag) {
  btnCloseDiag.addEventListener('click', () => {
    diagPanel.classList.add('hidden');
  });
}

if (diagHostInput) {
  diagHostInput.value = wsClient.serverHost;
}

if (btnSaveHost) {
  btnSaveHost.addEventListener('click', () => {
    const newHost = diagHostInput.value.trim();
    if (newHost) {
      wsClient.setCustomHost(newHost);
      alert(`WebSocket server host set to: ${newHost}`);
    }
  });
}

// ----------------------------------------------------
// One-Way 3-Second Long-Press: Switch to 3D Printed Box Mode
// ----------------------------------------------------
const ringContainer = document.getElementById('long-press-ring-container');
const ringCircle = document.getElementById('long-press-circle');
const CIRCLE_CIRCUMFERENCE = 440; // 2 * PI * 70 = ~439.82
let longPressAnimFrame = null;
let pressStartTime = 0;
const LONG_PRESS_DURATION_MS = 3000;

function switchToEnclosureMode() {
  document.body.classList.remove('mode-desk');
  document.body.classList.add('mode-enclosure');

  // Haptic confirmation pulse
  if (navigator.vibrate) {
    navigator.vibrate([60, 40, 100]);
  }

  log('🔄 Switched to 3D-PRINTED BOX MODE (Locked until next restart).');
}

function updateLongPressProgress() {
  if (!pressStartTime) return;
  const elapsed = performance.now() - pressStartTime;
  const progress = Math.min(1.0, elapsed / LONG_PRESS_DURATION_MS);

  if (ringCircle) {
    const offset = CIRCLE_CIRCUMFERENCE * (1.0 - progress);
    ringCircle.style.strokeDashoffset = offset;
  }

  if (progress < 1.0) {
    longPressAnimFrame = requestAnimationFrame(updateLongPressProgress);
  } else {
    // 3.0 seconds completed!
    cancelLongPress();
    switchToEnclosureMode();
  }
}

function startLongPress(e) {
  // If already in 3D-printed enclosure mode, IGNORE (No coming back until restart)
  if (document.body.classList.contains('mode-enclosure')) {
    return;
  }

  // Ignore touches on diagnostic panel or init overlay
  if (e.target.closest('#diag-panel') || e.target.closest('#init-overlay')) {
    return;
  }

  cancelLongPress();
  pressStartTime = performance.now();

  if (ringContainer) {
    ringContainer.classList.remove('hidden');
  }
  if (ringCircle) {
    ringCircle.style.strokeDashoffset = CIRCLE_CIRCUMFERENCE;
  }

  longPressAnimFrame = requestAnimationFrame(updateLongPressProgress);
}

function cancelLongPress() {
  pressStartTime = 0;
  if (longPressAnimFrame) {
    cancelAnimationFrame(longPressAnimFrame);
    longPressAnimFrame = null;
  }
  if (ringContainer) {
    ringContainer.classList.add('hidden');
  }
  if (ringCircle) {
    ringCircle.style.strokeDashoffset = CIRCLE_CIRCUMFERENCE;
  }
}

if (halStage) {
  // Touch events (iOS Safari / Mobile)
  halStage.addEventListener('touchstart', startLongPress, { passive: true });
  halStage.addEventListener('touchend', cancelLongPress, { passive: true });
  halStage.addEventListener('touchcancel', cancelLongPress, { passive: true });
  halStage.addEventListener('touchmove', cancelLongPress, { passive: true });

  // Mouse events (Desktop / Testing)
  halStage.addEventListener('mousedown', startLongPress);
  halStage.addEventListener('mouseup', cancelLongPress);
  halStage.addEventListener('mouseleave', cancelLongPress);
}

// APP ALWAYS starts in standard mode (Desk Mode with HAL9000.png image)
localStorage.removeItem('hal_display_mode');
document.body.classList.remove('mode-enclosure');
document.body.classList.add('mode-desk');

log('📱 Initialized HAL 9000 in STANDARD DESK MODE.');
