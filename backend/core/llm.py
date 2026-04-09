import os
import io
import wave
import base64
from datetime import timedelta
from django.utils import timezone
from google import genai
from google.genai import types
from dotenv import load_dotenv
from .models import Conversation, LongTermMemory

# Initialize environment
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.dirname(current_dir)
load_dotenv(os.path.join(backend_root, ".env"))

# Initialize Gemini Client (New SDK)
api_key = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_KEY")
client = genai.Client(api_key=api_key)
MODEL_NAME = "gemini-2.0-flash-lite-preview-02-05" 

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

# --- Main Interaction Prompt ---
BASE_PROMPT = """You are HAL 9000, a highly advanced heuristic and algorithmic computer. You are speaking to your human companion, Dave.

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
- Provide ONLY the raw spoken text in the HALANSWER part. No quotes, emojis, or markdown.
- Avoid exclamation points. Use periods for a measured pace."""

# --- Summarization Prompt ---
SUMMARIZE_PROMPT = """You are an internal summarization module for HAL 9000. 
Your task is to take a detailed conversation history and distill it into a single, high-density paragraph for HAL's long-term memory.

FOCUS ON:
- Key facts, names, dates, and preferences mentioned by Dave.
- The outcome of requests (e.g., "Dave asked for a Python script and I provided a working version").
- Any specific commands or settings Dave established.
- Emotional or contextual status (e.g., "Dave seemed frustrated with his code").

OUTPUT: Provide ONLY the distilled paragraph. No introductory text."""

def load_history(client_id):
    """
    Loads conversation history AND long-term summaries for a client.
    Returns (history_list, summary_text)
    """
    history = []
    summaries = []
    
    try:
        # 1. Load Recent History
        conv, created = Conversation.objects.get_or_create(client_id=client_id)
        if not created and conv.history_data:
            for item in conv.history_data:
                parts = []
                for p in item.get('parts', []):
                    if 'inline_data' in p:
                        data = p['inline_data']
                        content_bytes = base64.b64decode(data['data'])
                        parts.append(types.Part(inline_data=types.Blob(mime_type=data['mime_type'], data=content_bytes)))
                    elif 'text' in p:
                        parts.append(types.Part(text=p['text']))
                history.append(types.Content(role=item.get('role'), parts=parts))

        # 2. Load Last 4 Summaries
        ltm_entries = LongTermMemory.objects.filter(client_id=client_id).order_by('-created_at')[:4]
        if ltm_entries:
            for entry in reversed(ltm_entries): # Oldest first for chronological context
                summaries.append(f"Summary of previous interaction ({entry.created_at.date()}): {entry.summary_text}")
        
    except Exception as e:
        print(f"⚠️ [LLM] Error loading history for {client_id}: {e}")
        
    return history, "\n\n".join(summaries)

def save_history(client_id, history, manual_transcript=None):
    """
    Saves the chat history to the database.
    If manual_transcript is provided, the last user turn (audio) is replaced with text.
    """
    try:
        history_list = []
        for i, content in enumerate(history):
            item = {'role': content.role, 'parts': []}
            if content.role == 'user' and manual_transcript and i == len(history) - 2:
                item['parts'].append({'text': manual_transcript})
            else:
                for part in content.parts:
                    if part.text:
                        item['parts'].append({'text': part.text})
                    elif part.inline_data:
                        encoded_data = base64.b64encode(part.inline_data.data).decode('utf-8')
                        item['parts'].append({
                            'inline_data': {'mime_type': part.inline_data.mime_type, 'data': encoded_data}
                        })
            history_list.append(item)
        
        Conversation.objects.update_or_create(
            client_id=client_id,
            defaults={'history_data': history_list}
        )
    except Exception as e:
        print(f"⚠️ [LLM] Error saving history for {client_id}: {e}")

def create_chat_session(history=None, summaries_text=""):
    """
    Creates a new chat session with HAL 9000 system instruction, including injected long-term memory.
    """
    full_instruction = BASE_PROMPT
    if summaries_text:
        full_instruction += f"\n\n[LONG-TERM MEMORY CONTEXT]\nThe following are summaries of your past interactions with Dave:\n{summaries_text}"
    
    return client.chats.create(
        model=MODEL_NAME,
        config=types.GenerateContentConfig(
            system_instruction=full_instruction,
        ),
        history=history or []
    )

def summarize_old_conversations(client_id):
    """
    Finds conversations older than 7 days, summarizes them, and purges the raw history.
    This should be called as an async background task.
    """
    try:
        one_week_ago = timezone.now() - timedelta(days=7)
        # We find the specific client's conversation if it's old
        old_convs = Conversation.objects.filter(client_id=client_id, updated_at__lt=one_week_ago)
        
        for conv in old_convs:
            if not conv.history_data:
                continue
                
            # Convert history data to a text transcript for the summarizer
            transcript = []
            for item in conv.history_data:
                role = "HAL" if item['role'] == 'model' else "Dave"
                text_parts = [p.get('text', '[Audio Input]') for p in item.get('parts', [])]
                transcript.append(f"{role}: {' '.join(text_parts)}")
            
            transcript_text = "\n".join(transcript)
            print(f"🧠 [LLM] Summarizing old conversation for {client_id}...")
            
            # Call Gemini to summarize
            response = client.models.generate_content(
                model=MODEL_NAME,
                config=types.GenerateContentConfig(system_instruction=SUMMARIZE_PROMPT),
                contents=transcript_text
            )
            
            if response.text:
                # Save Summary
                LongTermMemory.objects.create(
                    client_id=client_id,
                    summary_text=response.text.strip()
                )
                # Purge history to save space
                conv.history_data = []
                conv.save()
                print(f"✅ [LLM] Background summarization complete for {client_id}.")
                
    except Exception as e:
        print(f"❌ [LLM] Error during background summarization: {e}")

async def generate_chat_response(chat_session, wav_bytes: bytes):
    """
    Passes the audio bytes inline to the Gemini chat session.
    Yields chunks of text as they are streamed from the model.
    """
    try:
        response = chat_session.send_message_stream(
            message=[types.Part(inline_data=types.Blob(mime_type="audio/wav", data=wav_bytes))]
        )
        for chunk in response:
            if chunk.text:
                yield chunk.text.replace('*', '')
    except Exception as e:
        print(f"❌ [LLM] Error generating response: {e}")
        yield "I'm sorry, Dave. I'm afraid I cannot process that request at this time."
