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
let tapCount = 0;
let tapTimer = null;
let conversationInterval = null;
let conversationTimeRemaining = 0;

// Sleep Mode State
let sleepTimer = null;
let pendingSleepCommand = false;
const SLEEP_TIMEOUT_MS = 120000; // 2 minutes

function wakeUp() {
  if (currentState !== State.SLEEPING) return;
  
  log('☀️ System awoken from Sleep Mode.');
  document.body.classList.remove('sleep-mode');
  if (audioRecorder) audioRecorder.sleeping = false;
  if (speechRecognizer) speechRecognizer.resume();
  setState(State.LISTENING);
  resetSleepTimer();
}

function goToSleep() {
  if (currentState === State.PROCESSING || currentState === State.THINKING) {
    resetSleepTimer();
    return;
  }
  
  log('🌙 System entering Sleep Mode to conserve OLED power.');
  if (persistentLedOn) setPersistentLed(false);
  document.body.classList.add('sleep-mode');
  if (audioRecorder) audioRecorder.sleeping = true;
  if (speechRecognizer) speechRecognizer.pause();
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
    'led-anim-heartbeat'
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
  } else {
    // Default expressive blink
    triggerLedExpression('wink', 450);
  }
}

// Visual Modulation: Authentic to 2001: A Space Odyssey
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

    if (norm > 0.05) {
      // User is speaking: visibly animate (blink/pulse) the outer ring with voice energy
      if (layerRingOn) {
        const ringLevel = Math.min(1.0, 0.45 + norm * 1.8).toFixed(2);
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
const audioPlayer = new AudioPlayer({
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

const speechRecognizer = new SpeechRecognizer({
  onFinalSpeech: (text) => {
    if (currentState === State.SLEEPING) {
      wakeUp();
    }
    if (persistentLedOn) {
      setPersistentLed(false);
    }
    if (wsClient && wsClient.isConnected && text) {
      log(`📤 [SpeechRecognizer] Sending transcript to HAL: "${text}"`);
      wsClient.sendJson({ type: 'user_text', text });
      setState(State.THINKING);
    }
  },
  onInterimSpeech: (text) => {
    if (persistentLedOn && text && text.trim()) {
      setPersistentLed(false);
    }
  },
  onStatusChange: (status) => {
    log(`🗣️ SpeechRecognizer status: ${status}`);
  },
  onLog: log,
});

const motionDetector = new MotionDetector({
  threshold: 12.0,
  onKnock: (magnitude) => {
    log(`💥 Enclosure knock detected (${magnitude.toFixed(1)} m/s²)!`);
    // Physical tap blinks the 3 auxiliary dots immediately!
    triggerLedExpression('wink', 400);

    if (currentState === State.SLEEPING) {
      wakeUp();
    } else if (currentState === State.PROCESSING || currentState === State.THINKING) {
      log('⚡ Intercepting HAL via physical enclosure knock.');
      triggerVoiceBargeIn();
    } else {
      resetSleepTimer();
    }
  },
  onLog: log,
});

const audioRecorder = new AudioRecorder({
  onAudioData: (pcmBuffer) => {
    // Single Input Pipeline: SpeechRecognizer is primary; only stream raw PCM as fallback if Web Speech is unsupported
    if (!speechRecognizer.isSupported && wsClient && wsClient.isConnected) {
      wsClient.sendAudio(pcmBuffer);
    }
  },
  onAudioLevel: (intensity) => {
    if (currentState !== State.PROCESSING) {
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
    } else if (text.startsWith('LED:')) {
      const state = text.substring(4).trim().toUpperCase();
      if (state === 'ON') {
        setPersistentLed(true);
      } else if (state === 'OFF') {
        setPersistentLed(false);
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

// Screen Wake Lock
async function requestScreenWakeLock() {
  if ('wakeLock' in navigator) {
    try {
      wakeLockSentinel = await navigator.wakeLock.request('screen');
      log('🔒 Screen Wake Lock active (Display will stay ON).');

      wakeLockSentinel.addEventListener('release', () => {
        log('🔓 Screen Wake Lock was released.');
      });
    } catch (err) {
      log(`⚠️ Wake Lock error: ${err.name}, ${err.message}`);
    }
  } else {
    log('⚠️ Screen Wake Lock API not supported on this browser.');
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
    speechRecognizer.start();
    setState(State.LISTENING);
    resetSleepTimer();

    // 5. Request permanent Screen Wake Lock
    requestScreenWakeLock().catch((e) => log(`WakeLock note: ${e.message}`));

    // 6. Request accelerometer motion permission & begin knock detection
    await motionDetector.initialize();

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

