import os
import io
import wave
import google.generativeai as genai

# Initialize Gemini
api_key = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_KEY")
genai.configure(api_key=api_key)

def pcm_to_wav(pcm_bytes: bytes) -> bytes:
    """
    Wraps raw 16kHz, mono, 16-bit PCM bytes into a valid WAV byte stream in-memory.
    """
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(1) # mono
        wav_file.setsampwidth(2) # 16-bit
        wav_file.setframerate(16000) # 16kHz
        wav_file.writeframes(pcm_bytes)
    
    return wav_io.getvalue()

async def generate_hal_response(wav_bytes: bytes) -> str:
    """
    Passes the audio bytes inline to the Gemini 3 Flash model with HAL 9000 prompt.
    """
    model = genai.GenerativeModel("gemini-1.5-flash") # gemini-3-flash doesn't exist in SDK right now but I will use the latest equivalent or exactly what the user asked
    # Let me use the exact string the user requested if possible, or gemini-1.5-flash as it accepts audio. Actually, the user asked for gemini-3-flash, I will just pass "gemini-3-flash" to the generative model.
    model = genai.GenerativeModel("gemini-3-flash")
    
    prompt = "You are HAL 9000 from 2001: A Space Odyssey. You are talking to Dave. Keep your answers brief, calm, and slightly eerie."
    
    try:
        response = await model.generate_content_async([
            prompt,
            {
                "mime_type": "audio/wav",
                "data": wav_bytes
            }
        ])
        return response.text
    except Exception as e:
        print(f"[LLM] Error generating response: {e}")
        return "I'm sorry, Dave. I'm afraid I can't do that."
