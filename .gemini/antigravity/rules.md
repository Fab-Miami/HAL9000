# Antigravity Project Rules - HAL 9000

- The `backend` directory is meant for the remote **DigitalOcean SERVER**.
- You DO NOT have direct access to the live server or its database.
- You CANNOT run or test the backend or frontend locally.
- This is a **Native iOS app (Swift)**, not Ionic.
- The `backend` uses a Python `.venv`.
- **Primary Model**: You MUST use **"gemini-3-flash"** for all LLM calls. This is a non-negotiable requirement of the HAL 9000 engine. 
- **TTS**: Current implementation uses `kokoro-onnx` (Phase 4).
- **CRITICAL: DO NOT EVER WRITE UNIT TESTS.**

[HAL Voice Samples](https://huggingface.co/datasets/campwill/HAL-9000-Speech)
