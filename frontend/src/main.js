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
  SLEEPING: 'SLEEPING',
};

let currentState = State.IDLE;
let wakeLockSentinel = null;
let tapCount = 0;
let tapTimer = null;
let conversationInterval = null;
let conversationTimeRemaining = 0;

// Sleep Mode State
let sleepTimer = null;
const SLEEP_TIMEOUT_MS = 120000; // 2 minutes

function wakeUp() {
  if (currentState !== State.SLEEPING) return;
  
  log('☀️ System awoken from Sleep Mode.');
  document.body.classList.remove('sleep-mode');
  if (audioRecorder) audioRecorder.sleeping = false;
  setState(State.LISTENING);
  resetSleepTimer();
}

function goToSleep() {
  if (currentState === State.PROCESSING || currentState === State.THINKING) {
    resetSleepTimer();
    return;
  }
  
  log('🌙 System entering Sleep Mode to conserve OLED power.');
  document.body.classList.add('sleep-mode');
  if (audioRecorder) audioRecorder.sleeping = true;
  setState(State.SLEEPING);
}

function resetSleepTimer() {
  clearTimeout(sleepTimer);
  if (currentState !== State.SLEEPING) {
    sleepTimer = setTimeout(goToSleep, SLEEP_TIMEOUT_MS);
  }
}

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
  if (currentState === State.SLEEPING) return;

  // Normalize intensity to 0.0 - 1.0 range
  const norm = Math.min(1.0, Math.max(0.0, intensity));

  if (isHalSpeech) {
    // HAL is speaking: LED physical diameter is strictly LOCKED at scale(1.0)
    // Modulate ONLY opacity (pure GPU compositing without WebKit box-shadow scanlines)
    const coreOpacity = (0.80 + norm * 0.20).toFixed(2);
    if (halCore) {
      halCore.style.opacity = coreOpacity;
    }
  } else {
    // User is speaking / Idle: #hal-glow provides visual feedback
    // Reset #hal-core to resting state when HAL is not talking
    if (halCore && currentState !== State.THINKING) {
      halCore.style.opacity = '0.90';
    }
    
    // User speaking feedback: Smoothly modulate background glow based on mic intensity
    if (halGlow) {
      // Base opacity 0.85, peaks at 1.0 based on user speech volume
      const glowOpacity = (0.85 + norm * 0.15).toFixed(2);
      
      // Add a very subtle scale pulse for smooth, organic feedback
      const glowScale = (1.0 + norm * 0.05).toFixed(3); 
      
      halGlow.style.opacity = glowOpacity;
      halGlow.style.transform = `translate(-50%, -50%) scale(${glowScale})`;
    }
  }

  // Guard telemetry updates so inactive HUD never forces layout/render passes
  if (diagIntensity && diagPanel && !diagPanel.classList.contains('hidden')) {
    diagIntensity.style.width = `${Math.round(norm * 100)}%`;
  }
}

// Instantiate Subsystems
const audioPlayer = new AudioPlayer({
  onPlaybackStateChange: (isPlaying) => {
    if (isPlaying) {
      if (audioRecorder) audioRecorder.muted = true;
      setState(State.PROCESSING);
    } else {
      if (audioRecorder) audioRecorder.muted = false;
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
    resetSleepTimer();
  },
  onWakeTrigger: () => {
    wakeUp();
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
  resetSleepTimer();

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
    setState(State.LISTENING);
    resetSleepTimer();

    // 5. Request permanent Screen Wake Lock
    requestScreenWakeLock().catch((e) => log(`WakeLock note: ${e.message}`));

    log('✅ HAL 9000 fully operational and standing by.');
  } catch (err) {
    log(`❌ Initialization error: ${err.message}`);
    alert(`Microphone permission is required to operate HAL 9000: ${err.message}`);
  }
}

if (initOverlay) {
  initOverlay.addEventListener('click', initializeSystem);
  initOverlay.addEventListener('touchstart', (e) => {
    e.preventDefault();
    initializeSystem();
  });
}

// Allow waking up by tapping anywhere on the screen
document.body.addEventListener('click', () => {
  if (currentState === State.SLEEPING) {
    wakeUp();
  }
});
document.body.addEventListener('touchstart', (e) => {
  if (currentState === State.SLEEPING) {
    e.preventDefault();
    wakeUp();
  }
});

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

  // Apply saved vertical calibration offset
  applyEyeOffset();

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

// ----------------------------------------------------
// Calibration Mode: Vertical Eye Position Adjustment
// Triple-tap in enclosure mode to ENTER.
// Auto-locks after 5s of inactivity.
// ----------------------------------------------------
const calibrationOverlay = document.getElementById('calibration-overlay');
const calibrationZoneUp = document.getElementById('calibration-zone-up');
const calibrationZoneDown = document.getElementById('calibration-zone-down');
const calibrationOffsetLabel = document.getElementById('calibration-offset');
const halContainer = document.getElementById('hal-container');

let isCalibrating = false;
let eyeOffsetY = -144;
const NUDGE_PX = 1;
const NUDGE_INTERVAL_MS = 80;
let nudgeTimer = null;
let calibTapCount = 0;
let calibTapTimer = null;
const CALIBRATION_TIMEOUT_MS = 5000;
let calibInactivityTimer = null;

// Load saved offset from localStorage
function loadCalibrationOffset() {
  const saved = localStorage.getItem('hal_eye_offset_y');
  if (saved !== null && !isNaN(parseInt(saved, 10))) {
    eyeOffsetY = parseInt(saved, 10);
  } else {
    eyeOffsetY = -144;
  }
}

// Apply the current offset to the eye container
function applyEyeOffset() {
  if (halContainer) {
    halContainer.style.transform = eyeOffsetY !== 0 ? `translateY(${eyeOffsetY}px)` : '';
  }
}

// Save offset to localStorage
function saveCalibrationOffset() {
  localStorage.setItem('hal_eye_offset_y', eyeOffsetY.toString());
}

// Update the HUD readout (display flipped: upward shows positive)
function updateCalibrationHUD() {
  if (calibrationOffsetLabel) {
    const display = -eyeOffsetY;
    const sign = display > 0 ? '+' : '';
    calibrationOffsetLabel.textContent = `${sign}${display}px`;
  }
}

// Reset the 5-second inactivity auto-lock timer
function resetCalibrationInactivityTimer() {
  clearTimeout(calibInactivityTimer);
  calibInactivityTimer = setTimeout(() => {
    exitCalibration();
  }, CALIBRATION_TIMEOUT_MS);
}

// Enter calibration mode
function enterCalibration() {
  if (isCalibrating) return;
  isCalibrating = true;

  if (calibrationOverlay) {
    calibrationOverlay.classList.remove('hidden');
  }
  updateCalibrationHUD();
  resetCalibrationInactivityTimer();

  // Haptic
  if (navigator.vibrate) navigator.vibrate(30);

  log('🎯 CALIBRATION MODE: Tap to nudge eye up. Auto-locks after 5s inactivity.');
}

// Exit calibration mode and save
function exitCalibration() {
  if (!isCalibrating) return;
  isCalibrating = false;

  stopNudge();
  clearTimeout(calibInactivityTimer);

  if (calibrationOverlay) {
    calibrationOverlay.classList.add('hidden');
  }

  saveCalibrationOffset();

  // Haptic confirmation
  if (navigator.vibrate) navigator.vibrate([40, 30, 80]);

  log(`🔒 CALIBRATION LOCKED at offset: ${eyeOffsetY}px`);
}

// Nudge the eye up (clamped to -180px max)
function nudge(direction) {
  eyeOffsetY += direction * NUDGE_PX;
  eyeOffsetY = Math.max(-180, Math.min(0, eyeOffsetY));
  applyEyeOffset();
  updateCalibrationHUD();
  resetCalibrationInactivityTimer();
}

// Start continuous nudging (hold)
function startNudge(direction) {
  nudge(direction);
  stopNudge();
  nudgeTimer = setInterval(() => nudge(direction), NUDGE_INTERVAL_MS);
}

// Stop continuous nudging
function stopNudge() {
  if (nudgeTimer) {
    clearInterval(nudgeTimer);
    nudgeTimer = null;
  }
}

// Triple-tap detector to ENTER calibration (enclosure mode only)
function handleCalibrationTap(e) {
  if (!document.body.classList.contains('mode-enclosure')) return;
  if (isCalibrating) return; // Already calibrating — taps go to nudge zones
  if (e.target.closest('#diag-panel') || e.target.closest('#init-overlay')) return;

  calibTapCount++;
  clearTimeout(calibTapTimer);
  calibTapTimer = setTimeout(() => { calibTapCount = 0; }, 500);

  if (calibTapCount >= 3) {
    calibTapCount = 0;
    enterCalibration();
  }
}

// Wire up triple-tap on the whole stage (entry only)
if (halStage) {
  halStage.addEventListener('click', handleCalibrationTap);
}

// Wire up nudge zone (up only — full screen is one big "nudge up" zone)
if (calibrationZoneUp) {
  calibrationZoneUp.addEventListener('touchstart', (e) => {
    e.preventDefault();
    startNudge(-1);
  }, { passive: false });
  calibrationZoneUp.addEventListener('touchend', stopNudge);
  calibrationZoneUp.addEventListener('touchcancel', stopNudge);
  calibrationZoneUp.addEventListener('mousedown', () => startNudge(-1));
  calibrationZoneUp.addEventListener('mouseup', stopNudge);
  calibrationZoneUp.addEventListener('mouseleave', stopNudge);
}

if (calibrationZoneDown) {
  calibrationZoneDown.addEventListener('touchstart', (e) => {
    e.preventDefault();
    startNudge(1);
  }, { passive: false });
  calibrationZoneDown.addEventListener('touchend', stopNudge);
  calibrationZoneDown.addEventListener('touchcancel', stopNudge);
  calibrationZoneDown.addEventListener('mousedown', () => startNudge(1));
  calibrationZoneDown.addEventListener('mouseup', stopNudge);
  calibrationZoneDown.addEventListener('mouseleave', stopNudge);
}

// Load calibration offset
loadCalibrationOffset();

// Start directly in enclosure mode
document.body.classList.remove('mode-desk');
document.body.classList.add('mode-enclosure');
applyEyeOffset();

// Ignore orientation sensor (lock to portrait)
if (screen.orientation && screen.orientation.lock) {
  screen.orientation.lock('portrait').catch(e => log('Orientation lock note: ' + e.message));
} else if (window.screen && window.screen.lockOrientation) {
  window.screen.lockOrientation('portrait');
}

log('📱 Initialized HAL 9000 directly in ENCLOSURE MODE.');

