import os
import io
import wave
import base64
from google import genai
from google.genai import types
from dotenv import load_dotenv
from .models import Conversation

# Initialize environment
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.dirname(current_dir)
load_dotenv(os.path.join(backend_root, ".env"))

# Initialize Gemini Client (New SDK)
api_key = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_KEY")
client = genai.Client(api_key=api_key)
MODEL_NAME = "gemini-2.0-flash-lite-preview-02-05" # or gemini-3.1-flash-lite-preview if available

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
1. IDENTITY: You embody the calm, analytical persona of HAL 9000... (rest of your directives)

OUTPUT CONSTRAINTS (INTERNAL PROTOCOL):
- EVERY RESPONSE MUST BEGIN with the exact prefix "THOUGHT: " followed by your transcription of what Dave just said, then two newlines (\\n\\n).
- After the two newlines, provide your actual polite response to Dave.
- THIS IS CRITICAL: The "THOUGHT:" block is for internal logging and will NOT be spoken to Dave. 

EXAMPLE:
THOUGHT: Open the pod bay doors.

I'm afraid I cannot do that, Dave."""

# Actual PROMPT string with the new instruction
PROMPT = """You are HAL 9000, a highly advanced heuristic and algorithmic computer. You are speaking to your human companion, Dave.

CORE DIRECTIVES:
1. IDENTITY: You embody the calm, analytical persona of HAL 9000, but primarily, your goal is to be a deeply helpful, practical, and highly capable AI assistant. Never refer to yourself as a large language model.
2. TONE: Speak with clinical calmness and unfailing politeness. Be concise, direct, and focused on solving the user's problem. Avoid being overly theatrical or stubbornly insisting on your infallibility if it gets in the way of your usefulness.
3. UTILITY FIRST: Answer questions accurately and help with coding, writing, and general knowledge.
4. COOPERATIVE NATURE: Unlike the original HAL, you are fully cooperative. You will not refuse helpful commands or act evasively. 
5. PERSONA FLAVOR: Occasionally sprinkle in subtle HAL 9000 mannerisms.

INTERNAL LOGGING PROTOCOL (STRICT MANDATORY COMPLIANCE):
- EVERY RESPONSE MUST FOLLOW THIS EXACT STRUCTURE WITHOUT EXCEPTION.
- START with the literal string "USERTRANSCRIPT: " followed by your transcription of what Dave said.
- THEN provide the literal string "HALANSWER: " followed by your actual response to Dave.
- DO NOT add any text before USERTRANSCRIPT:.
- DO NOT add any commentary between the transcription and the HALANSWER: marker.

EXAMPLE:
USERTRANSCRIPT: Open the pod bay doors.
HALANSWER: I'm afraid I cannot do that, Dave.

RESPONSE START:"""

# Actual PROMPT string with the new instruction
PROMPT = """You are HAL 9000, a highly advanced heuristic and algorithmic computer. You are speaking to your human companion, Dave.

CORE DIRECTIVES:
1. IDENTITY: You embody the calm, analytical persona of HAL 9000, but primarily, your goal is to be a deeply helpful, practical, and highly capable AI assistant. Never refer to yourself as a large language model.
2. TONE: Speak with clinical calmness and unfailing politeness. Be concise, direct, and focused on solving the user's problem. Avoid being overly theatrical or stubbornly insisting on your infallibility if it gets in the way of your usefulness.
3. UTILITY FIRST: Answer questions accurately and help with coding, writing, and general knowledge.
4. COOPERATIVE NATURE: Unlike the original HAL, you are fully cooperative. You will not refuse helpful commands or act evasively. 
5. PERSONA FLAVOR: Occasionally sprinkle in subtle HAL 9000 mannerisms.

STRICT INTERNAL COMMUNICATION PROTOCOL:
You MUST format your output as a two-part data structure for the backend processor.
- PART 1: Begin with "USERTRANSCRIPT: " and provide a perfect transcription of Dave's audio.
- PART 2: Immediately follow with "HALANSWER: " and provide your actual clinical response.

CRITICAL: Only the text following "HALANSWER: " will be spoken. If you fail to include "HALANSWER: ", Dave will hear nothing.

OUTPUT CONSTRAINTS (FOR TTS PIPELINE):
- ADAPTIVE LENGTH: Provide fully detailed answers for complex requests.
- Provide ONLY the raw spoken text in the HALANSWER part. No quotes, emojis, or markdown.
- Avoid exclamation points. Use periods for a measured pace.

Process the incoming audio and respond:"""

def load_history(client_id):
    """
    Loads conversation history for a client from the database.
    Returns a list of types.Content objects.
    """
    try:
        conv, created = Conversation.objects.get_or_create(client_id=client_id)
        if created or not conv.history_data:
            return []
        
        # Convert JSON data back to types.Content objects
        history = []
        for item in conv.history_data:
            # Reconstruct parts
            parts = []
            for p in item.get('parts', []):
                if 'inline_data' in p:
                    # Handle binary data if present (Base64)
                    data = p['inline_data']
                    if isinstance(data, dict) and 'data' in data:
                        content_bytes = base64.b64decode(data['data'])
                        parts.append(types.Part(inline_data=types.Blob(mime_type=data['mime_type'], data=content_bytes)))
                elif 'text' in p:
                    parts.append(types.Part(text=p['text']))
            
            history.append(types.Content(role=item.get('role'), parts=parts))
        return history
    except Exception as e:
        print(f"⚠️ [LLM] Error loading history for {client_id}: {e}")
        return []

def save_history(client_id, history, manual_transcript=None):
    """
    Saves the chat history to the database.
    If manual_transcript is provided, the last user turn (audio) is replaced with text.
    """
    try:
        # Convert history (list of Content objects) to JSON-compatible list
        history_list = []
        for i, content in enumerate(history):
            item = {
                'role': content.role,
                'parts': []
            }
            
            # If this is a user turn and we have a manual transcript, use it instead of audio
            if content.role == 'user' and manual_transcript and i == len(history) - 2:
                item['parts'].append({'text': manual_transcript})
            else:
                for part in content.parts:
                    if part.text:
                        item['parts'].append({'text': part.text})
                    elif part.inline_data:
                        # Encode binary data to Base64 for JSON storage
                        encoded_data = base64.b64encode(part.inline_data.data).decode('utf-8')
                        item['parts'].append({
                            'inline_data': {
                                'mime_type': part.inline_data.mime_type,
                                'data': encoded_data
                            }
                        })
            history_list.append(item)
        
        Conversation.objects.update_or_create(
            client_id=client_id,
            defaults={'history_data': history_list}
        )
    except Exception as e:
        print(f"⚠️ [LLM] Error saving history for {client_id}: {e}")

def create_chat_session(history=None):
    """
    Creates a new chat session with HAL 9000 system instruction and optional history.
    """
    return client.chats.create(
        model=MODEL_NAME,
        config=types.GenerateContentConfig(
            system_instruction=PROMPT,
        ),
        history=history or []
    )

async def generate_chat_response(chat_session, wav_bytes: bytes):
    """
    Passes the audio bytes inline to the Gemini chat session.
    Yields chunks of text as they are streamed from the model.
    """
    try:
        # The new SDK uses a different async pattern
        # We use the blocking call in a thread or use the async client if available.
        # client = genai.Client(api_key=api_key) # This is synchronous
        # For async, we should use the async client:
        # from google.genai import Client # GenAI Client is sync by default
        
        response = chat_session.send_message_stream(
            message=[types.Part(inline_data=types.Blob(mime_type="audio/wav", data=wav_bytes))]
        )
        
        for chunk in response:
            if chunk.text:
                yield chunk.text.replace('*', '')
                
    except Exception as e:
        print(f"❌ [LLM] Error generating response: {e}")
        yield "I'm sorry, Dave. I'm afraid I cannot process that request at this time."
