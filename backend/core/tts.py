import os
import numpy as np
from kokoro_onnx import Kokoro

# Model selection (v1.0-quant is ~2.2x faster than v1.0 standard)
MODEL_NAME = "kokoro-v1.0-quant.onnx"
# MODEL_NAME = "kokoro-v1.0.onnx" # Original FP32 backup

current_dir = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(current_dir, MODEL_NAME)
voices_path = os.path.join(current_dir, "voices-v1.0.bin")

try:
    print(f"👂 [Kokoro] Loading TTS Engine ({MODEL_NAME})...")
    if not os.path.exists(model_path):
        print(f"❌ [Kokoro] ERROR: Model file not found at {model_path}")
        # Fallback to original if quant is missing
        if "quant" in MODEL_NAME:
            print("⚠️ [Kokoro] Falling back to original FP32 model...")
            model_path = os.path.join(current_dir, "kokoro-v1.0.onnx")
    
    if not os.path.exists(voices_path):
        print(f"❌ [Kokoro] ERROR: Voices file not found at {voices_path}")
        
    kokoro = Kokoro(model_path, voices_path)
    print(f"✅ [Kokoro] TTS Engine loaded successfully from {os.path.basename(model_path)}.")
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

async def text_to_speech_stream(text: str):
    """
    Synthesizes speech using Kokoro-ONNX and yields raw 16-bit PCM bytes as soon as they are ready.
    """
    print(f"🗣️ [TTS] Engine generating audio stream for: {text}")
    if kokoro is None:
        print("⚠️ [Kokoro] Engine is not available. Yielding silence.")
        yield b'\x00' * 1024
        return
        
    try:
        stream = kokoro.create_stream(
            text, 
            voice="hal9000", 
            speed=0.9, 
            lang="en-us"
        )
        
        async for samples, sample_rate in stream:
            audio_int16 = (samples * 32767).astype(np.int16)
            yield audio_int16.tobytes()
            
    except Exception as e:
        print(f"❌ [Kokoro] Error generating speech stream: {e}")
        yield b'\x00' * 1024

