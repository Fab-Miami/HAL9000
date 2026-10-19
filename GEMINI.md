# HAL 9000 INVIOLABLE ARCHITECTURAL DIRECTIVES

## CRITICAL MANDATE #1: THE PHONE DOES 100% OF THE LISTENING
- **On-Device Speech Recognition (`webkitSpeechRecognition`) is PERMANENT and NON-NEGOTIABLE.**
- The iPhone Safari frontend handles all voice detection and speech-to-text locally via `SpeechRecognizer` (`frontend/src/speech-recognizer.js`).
- The phone transcribes words in real time, modulates the optical acoustic ring (`#layer-ring-on`), and sends finalized text JSON (`{"type": "user_text", "text": "..."}`) to the backend.
- **NEVER REMOVE, DISABLE, OR BYPASS `SpeechRecognizer` in `frontend/src/main.js`.**
- **NEVER STREAM RAW AUDIO PCM TO THE BACKEND AS PRIMARY INPUT.** Raw audio streaming is strictly a fallback for non-Safari browsers (`!speechRecognizer.isSupported`).
- The backend processes `user_text` in `_process_text_pipeline()` directly without audio buffering delay, without server VAD thresholds, without 2.0-second silence timers, and without cutting off sentences mid-speech.

## CRITICAL MANDATE #2: ZERO iOS SYSTEM DICTATION CHIMES ("BEEP BEEP")
- In `frontend/src/speech-recognizer.js`:
  - `pause()` sets `this.isPaused = true`. It **MUST NEVER** call `recognition.abort()` or `recognition.stop()`.
  - `resume()` sets `this.isPaused = false`. It **MUST NEVER** call `recognition.start()` unless the session genuinely died.
- Calling `abort()` or `start()` during turn-taking causes iOS Safari to emit the loud system dictation chime ("BEEP BEEP"). Keeping the session continuously alive and muting `onresult` in memory guarantees completely silent operation.

## CRITICAL MANDATE #3: PHYSICAL HARDWARE MONOLITH CONSTRAINTS
- **Sealed Physical Enclosure**: The iPhone is permanently mounted inside a sealed aluminum desktop monolith behind a curved glass fisheye lens on Fab's desk in Miami Beach, permanently connected to wall power.
- **No Touchscreen Access**: The screen is physically inaccessible behind glass. Physical interaction is handled exclusively via accelerometer knocks (`MotionDetector`, threshold 0.35 m/s²) and acoustic double-taps.
- **24/7 Screen On**: Screen dimming or power saving is STRICTLY FORBIDDEN. Standby/sleep mode turns off ONLY the central red LED (`layer-center-on`). The faceplate remains 100% visible 24/7 via Screen Wake Lock and looping silent keep-awake video.
- **Location Context**: Line 355 in `backend/core/llm.py` must ALWAYS preserve: `"Your current location is Miami Beach."`.

## CRITICAL MANDATE #4: NEVER BREAK ARCHITECTURE WITHOUT PERMISSION
- Do not refactor core subsystems, communication protocols, or listening architecture without explicit permission from Fab.
- Do not write unit tests.
- Always automatically commit, push, and deploy to Hetzner via `/home/docdoc1/deploy_hal9000.sh` when completing changes.
