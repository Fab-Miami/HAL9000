import asyncio
import os
from core import llm, tts

async def main():
    print("--- TESTING BACKEND PIPELINE ---")
    
    # 1. Test TTS directly
    print("\n[Test 1] Testing TTS generation...")
    audio = tts.text_to_speech("I'm sorry, Dave. I'm afraid I can't do that.")
    print(f"Generated audio size: {len(audio)} bytes")
    
    if len(audio) == 1024:
        print("CRITICAL: TTS returned exactly 1024 bytes (Silence Fallback).")
    else:
        print(f"SUCCESS: TTS generated {len(audio)} bytes.")

    # 2. Test LLM model name
    print("\n[Test 2] Testing LLM generation (checks if 'gemini-3-flash' is valid)...")
    # Using dummy WAV bytes (very small)
    dummy_wav = b'RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80\x3e\x00\x00\x00\x7d\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00'
    try:
        response = await llm.generate_hal_response(dummy_wav)
        print(f"LLM Response: {response}")
    except Exception as e:
        print(f"LLM Error: {e}")

if __name__ == "__main__":
    # Ensure current directory is backend/
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    asyncio.run(main())
