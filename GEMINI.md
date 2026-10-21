# HAL 9000 INVIOLABLE ARCHITECTURAL DIRECTIVES

## CRITICAL MANDATE #1: GEMINI NATIVE MULTIMODAL AUDIO LISTENING (ZERO WEBKIT STT & ZERO STANDBY LLM TOKENS)
- **Audio Capture on Phone, Listening on Gemini**: The iPhone captures microphone audio via Web Audio API, downsamples cleanly to 16kHz 16-bit Mono PCM, and streams audio to the backend.
- **Gemini Does 100% of the Speech Comprehension**: In active conversation, audio is fed directly to Gemini's native multimodal audio engine (`gemini-3.5-flash-lite`, the lowest-latency model in the fleet) via `types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav")`.
- **ZERO Cloud LLM Waste in Standby (Strict $0.00 Standby Gate)**: Gemini 3.5 API MUST NEVER be invoked simply to decide if HAL should wake up from standby, or to filter TV/ambient room chatter. Standby wake verification must run at strictly $0.00 cloud cost (via local on-prem CPU models on Hetzner or physical accelerometer knocks). Gemini is only engaged after a wake event is confirmed.
- **Single Gemini Stream per Active Turn**: Eliminate duplicate cloud transcription calls (`transcribe_audio` on Gemini is forbidden). Gemini's native multimodal audio stream handles vocal comprehension in a single pass.
- **Complete Elimination of `webkitSpeechRecognition`**: Web Speech API is permanently removed. This eliminates all iOS system dictation chimes ("BEEP BEEP"), eliminates Apple's delayed neural buffer lag / echo loops, eliminates Safari session dropouts, and provides native understanding of "HAL", proper nouns ("Fab", "Colozzi", "Mindolog"), and natural vocal inflection.
- **Physical Muting & Zero Echo**: When HAL is speaking, audio capture is strictly muted. When playback completes, listening resumes instantly. There are ZERO delayed ghost buffers or echo loops.
- **Strict Half-Duplex (Zero False Barge-In)**: Audio capture is strictly disabled whenever HAL is thinking or speaking. HAL is never interrupted during his turn, completely eliminating self-interruption, echo loops, and accidental cutoffs.
- **Turn-Taking & Silence Detection**: Handled on the iPhone via vocal RMS. Turns finalize after strictly 1.8 seconds of natural silence during active conversation (`SILENCE_DELAY_MS = 1800`), and 2.5 seconds in standby.
- **Optical Feedback**: The outer acoustic ring (`#layer-ring-on` / `hal2026_ring_on.png`) visibly blinks and pulses in real time with the user's vocal volume RMS while speaking.

## CRITICAL MANDATE #2: PHYSICAL HARDWARE DESKTOP CONSOLE CONSTRAINTS
- **Sealed Physical Enclosure**: The iPhone is permanently mounted inside a sealed 3D desktop console enclosure behind a curved glass fisheye lens on Fab's desk in Miami Beach, permanently connected to wall power.
- **No Touchscreen Access**: The screen is physically inaccessible behind glass. Physical interaction is handled exclusively via accelerometer knocks (threshold 1.0 m/s²) on the aluminum enclosure and wake words ("HAL wake up").
- **24/7 Screen On & Standby 50% Faceplate Fade**: The phone display MUST stay powered on 24/7 via Screen Wake Lock, NoSleep.js, and silent keep-awake video (never allow iOS to sleep/auto-lock). In standby/sleep mode, the central red LED (`layer-center-on`) turns OFF, and the faceplate background (`#layer-everything-off`) deliberately fades down to 50% opacity (`opacity: 0.5 !important; transition: opacity 2s ease-in-out 0.25s !important;`). KEEP THIS 50% FADE PERMANENTLY.
- **Location Context**: System prompt context must ALWAYS preserve: `"Your current location is Miami Beach."`.
- **Minimal Clean Architecture**: Strict maximum of 3 to 4 cohesive files total across frontend and backend. No fragmented bloated files or duplicate audio pipelines.

## CRITICAL MANDATE #3: NEVER BREAK ARCHITECTURE WITHOUT PERMISSION
- Do not refactor core subsystems, communication protocols, or listening architecture without explicit permission from Fab.
- Do not write unit tests.
- Always automatically commit, push, and deploy to Hetzner via `/home/docdoc1/deploy_hal9000.sh` when completing changes.
