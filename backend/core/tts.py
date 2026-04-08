import os
import numpy as np
from kokoro_onnx import Kokoro

# Locate the models we downloaded into the core directory
current_dir = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(current_dir, "kokoro-v1.0.onnx")
voices_path = os.path.join(current_dir, "voices-v1.0.bin")

try:
    print(f"👂 [Kokoro] Loading TTS Engine from {model_path}...")
    if not os.path.exists(model_path):
        print(f"❌ [Kokoro] ERROR: Model file not found at {model_path}")
    if not os.path.exists(voices_path):
        print(f"❌ [Kokoro] ERROR: Voices file not found at {voices_path}")
        
    kokoro = Kokoro(model_path, voices_path)
    print("✅ [Kokoro] TTS Engine loaded successfully.")
except Exception as e:
    print(f"💀 [Kokoro] CRITICAL FAILURE to initialize: {e}")
    import traceback
    traceback.print_exc()
    kokoro = None

def text_to_speech(text: str) -> bytes:
    """
    Synthesizes speech using Kokoro-ONNX and returns raw 16-bit PCM bytes.
    """
    print(f"🗣️ [TTS] Engine generating audio for: {text}")
    if kokoro is None:
        print("⚠️ [Kokoro] Engine is not available. Yielding silence.")
        return b'\x00' * 1024
        
    try:
        # Custom generated HAL 9000 voice
        # Speed set to 0.9 for the ideal cadence
        samples, sample_rate = kokoro.create(
            text, 
            voice="hal9000", 
            speed=0.9, 
            lang="en-us"
        )
        
        # Kokoro returns float32 array in range [-1.0, 1.0]. Convert to 16-bit PCM.
        audio_int16 = (samples * 32767).astype(np.int16)
        return audio_int16.tobytes()
        
    except Exception as e:
        print(f"❌ [Kokoro] Error generating speech: {e}")
        return b'\x00' * 1024

