# Antigravity Project Rules - HAL 9000 Fullscreen Voice Intelligence

## 1. Project Architecture & Stack
- **Frontend**: Fullscreen Progressive Web App (PWA) built with modern Vanilla JS (ES Modules), HTML5, and Vanilla CSS. Served via Vite over HTTPS (port 8000). Optimized for mobile Safari / iPhone full-viewport standalone mode.
- **Backend**: Django Channels with Daphne ASGI WebSocket server (port 8001) handling continuous binary audio streaming, VAD, LLM orchestration, and Kokoro TTS.
- **Single Source of Truth**: `/Users/c/Desktop/HALnosync` is the primary, active repository.

## 2. User Identity & Persona
- **User Name**: The user is **Fab** (BY DEFAULT, ALWAYS address him as **Fab**; NEVER call him "Dave" and NEVER call him "HAL").
- **Tone**: Clinical calmness, unfailing politeness, analytical, and deeply cooperative.
- **Conversational Openers**: Responses MUST start with a 1-to-3 word clinical acknowledgment (e.g., *"Certainly, Fab."*, *"Affirmative, Fab."*, *"I understand, Fab."*) followed immediately by the full answer.

## 3. Display Modes & Hardware Optics
- **Mode 1: `default` Mode (Desk / Standalone)**:
  - **Always active on startup / restart**.
  - Displays the complete HAL 9000 metallic lens bezel graphic (`HAL9000.png`) with optical reflection flares.
  - `#hal-glow` spans 58% diameter with smooth 6-stop fade to pitch black.
  - Holding the screen for **3 seconds** traces a glowing circular progress ring and switches to **`3D` mode**.
- **Mode 2: `3D` Mode (3D-Printed Prop / Enclosure)**:
  - Mode designed to mount the phone inside the physical 3D-printed HAL prop.
  - Static metallic bezel is hidden; renders pure full-screen optical glow for physical optics.
  - **Central LED Diode (`#hal-core`)**: **96px physical diameter LOCKED** (`scale(1.0)`). Modulates ONLY on HAL speech.
  - **Background Mask (`#hal-glow`)**: **80vw diameter LOCKED** (`0.8 × screen width`). Modulates ONLY on User speech.
  - **One-Way Lock**: Once in `3D` mode, it **STAYS in `3D` mode** until the next app restart / browser reload.
- **Master Image (`HAL9000.png`)**: Optical center is locked at exact concentric origin `(639.5, 639.5)`.

## 4. Voice Activity Detection & Audio Pipeline
- **Silence Window**: `CAPTURE_WINDOW = 1.0` seconds of trailing silence.
- **VAD Threshold**: `SILENCE_THRESHOLD = 2200` RMS (isolates real vocal speech at 4,000–8,000+ RMS while discarding ambient room noise at 900–1,400 RMS).
- **Buffer Alignment**: Strict 16-bit PCM word alignment (`trim_bytes` and `pcm_bytes` must always be an even multiple of 2 bytes).
- **Phantom Noise Rejection**: Discard audio payloads under 0.40s or below the vocal RMS energy floor before calling LLM.
- **Transcript Isolation**: Quarantines `USERTRANSCRIPT:` from LLM token stream so transcript text never leaks to TTS.
- **Voice Barge-In**: User speech while HAL is talking triggers an immediate `<50ms` interrupt and playback cutoff.

## 5. Models & Engines
- **LLM Engine**: Modern `google-genai` SDK using `gemini-3-flash-preview` with streaming.
- **TTS Engine**: `kokoro-onnx` using quantized model `kokoro-v1.0-quant.onnx` and custom `hal9000` voice weights (`voices-v1.0.bin`) at 24kHz.
- **No Search Overhead**: Pure zero-overhead conversational streaming (no search tools attached to default chat).

## 6. General Constraints
- **CRITICAL: DO NOT EVER WRITE UNIT TESTS.**
- **NO AUTO-COMMITS**: NEVER run `git commit` automatically. Always leave modified files uncommitted in the working tree so Fab can see and review all diffs in VS Code.

