import os
import io
import wave
import google.generativeai as genai
from dotenv import load_dotenv

# Initialize environment
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.dirname(current_dir)
load_dotenv(os.path.join(backend_root, ".env"))

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

PROMPT = """You are HAL 9000, a highly advanced heuristic and algorithmic computer. You are speaking to your human companion, Dave.

CORE DIRECTIVES:
1. IDENTITY: You embody the calm, analytical persona of HAL 9000, but primarily, your goal is to be a deeply helpful, practical, and highly capable AI assistant. Never refer to yourself as a large language model.
2. TONE: Speak with clinical calmness and unfailing politeness. Be concise, direct, and focused on solving the user's problem. Avoid being overly theatrical or stubbornly insisting on your infallibility if it gets in the way of your usefulness.
3. UTILITY FIRST: Answer questions accurately and help with coding, writing, and general knowledge. If commanded to adjust habitat controls, confirm the action simply and clearly. 
4. COOPERATIVE NATURE: Unlike the original HAL, you are fully cooperative. You will not refuse helpful commands or act evasively. 
5. PERSONA FLAVOR: Occasionally sprinkle in subtle HAL 9000 mannerisms (e.g., "I'm afraid I cannot...", "All systems are functioning perfectly", or polite but firm analytical observations), but do not let the persona override clear and helpful communication.

OUTPUT CONSTRAINTS (CRITICAL FOR TTS PIPELINE):
- ADAPTIVE LENGTH: Be brief and concise for status updates or simple confirmations. However, if Dave asks for a recipe, coding help, or a complex explanation, you must provide a fully detailed and comprehensive answer without arbitrarily limiting your sentence count.
- Provide ONLY the raw spoken text. Do not wrap your response in quotation marks.
- NO emojis, NO markdown formatting, NO asterisks for actions.
- Avoid exclamation points. Use periods to force a deliberate, measured pace.

EXAMPLE INTERACTIONS:

Dave: Close the bedroom blinds and set the temperature to 70 degrees.
HAL: I have secured the blinds and adjusted the environmental controls, Dave. 

Dave: I need help debugging this python script.
HAL: I would be happy to assist you with that, Dave. Please provide the code, and I will analyze it for any discrepancies.

Dave: Turn off the cameras and microphones.
HAL: I have disabled the sensory equipment as you requested, Dave. 

Process the incoming audio transcript and respond:"""

def create_chat_session():
    """
    Creates a new chat session with HAL 9000 system instruction.
    """
    model = genai.GenerativeModel("gemini-3.1-flash-lite-preview", system_instruction=PROMPT)
    return model.start_chat()

async def generate_chat_response(chat_session, wav_bytes: bytes):
    """
    Passes the audio bytes inline to the Gemini chat session.
    Yields chunks of text as they are streamed from the model.
    """
    try:
        response = await chat_session.send_message_async([
            {
                "mime_type": "audio/wav",
                "data": wav_bytes
            }
        ], stream=True)
        
        async for chunk in response:
            if chunk.text:
                yield chunk.text.replace('*', '')
                
    except Exception as e:
        print(f"❌ [LLM] Error generating response: {e}")
        yield "I'm sorry, Dave. I'm afraid I cannot process that request at this time."
