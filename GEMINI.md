# HAL 9000 INVIOLABLE ARCHITECTURAL DIRECTIVES

## CRITICAL MANDATE #1: GEMINI NATIVE MULTIMODAL AUDIO LISTENING (ZERO WEBKIT STT)
- **Audio Capture on Phone, Listening on Gemini**: The iPhone captures microphone audio via Web Audio API, downsamples cleanly to 16kHz 16-bit Mono PCM, and streams audio to the backend.
- **Gemini Does 100% of the Speech Comprehension**: Audio is fed directly to Gemini's native multimodal audio engine (`gemini-3.5-flash-lite`, the lowest-latency model in the fleet) via `types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav")`.
- **Complete Elimination of `webkitSpeechRecognition`**: Web Speech API is permanently removed. This eliminates all iOS system dictation chimes ("BEEP BEEP"), eliminates Apple's delayed neural buffer lag / echo loops, eliminates Safari session dropouts, and provides native understanding of "HAL", proper nouns ("Fab", "Colozzi", "Mindolog"), and natural vocal inflection.
- **Physical Muting & Zero Echo**: When HAL is speaking, audio capture is strictly muted. When playback completes, listening resumes instantly. There are ZERO delayed ghost buffers or echo loops.
- **Strict Half-Duplex (Zero False Barge-In)**: Audio capture is strictly disabled whenever HAL is thinking or speaking. HAL is never interrupted during his turn, completely eliminating self-interruption, echo loops, and accidental cutoffs.
- **Turn-Taking & Silence Detection**: Handled on the iPhone via vocal RMS. Turns finalize after strictly 1.8 seconds of natural silence during active conversation (`SILENCE_DELAY_MS = 1800`), and 2.5 seconds in standby.
- **Optical Feedback**: The outer acoustic ring (`#layer-ring-on` / `hal2026_ring_on.png`) visibly blinks and pulses in real time with the user's vocal volume RMS while speaking.

## CRITICAL MANDATE #2: PHYSICAL HARDWARE MONOLITH CONSTRAINTS
- **Sealed Physical Enclosure**: The iPhone is permanently mounted inside a sealed aluminum desktop monolith behind a curved glass fisheye lens on Fab's desk in Miami Beach, permanently connected to wall power.
- **No Touchscreen Access**: The screen is physically inaccessible behind glass. Physical interaction is handled exclusively via accelerometer knocks (threshold 1.0 m/s²) and acoustic double-taps for wake.
- **24/7 Screen On**: Screen dimming or power saving is STRICTLY FORBIDDEN. Standby/sleep mode turns off ONLY the central red LED (`layer-center-on`). The faceplate remains 100% visible 24/7 via Screen Wake Lock and looping silent keep-awake video.
- **Location Context**: System prompt context must ALWAYS preserve: `"Your current location is Miami Beach."`.
- **Minimal Clean Architecture**: Strict maximum of 3 to 4 cohesive files total across frontend and backend. No fragmented bloated files or duplicate audio pipelines.

## CRITICAL MANDATE #3: NEVER BREAK ARCHITECTURE WITHOUT PERMISSION
- Do not refactor core subsystems, communication protocols, or listening architecture without explicit permission from Fab.
- Do not write unit tests.
- Always automatically commit, push, and deploy to Hetzner via `/home/docdoc1/deploy_hal9000.sh` when completing changes.
