import os
import io
import wave
import base64
import json
import asyncio
from datetime import timedelta
from django.utils import timezone
from google import genai
from google.genai import types
from dotenv import load_dotenv
from .models import ConversationHistory, ConversationSummary

load_dotenv()

# Initialize Gemini Client
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

MODEL_NAME = "gemini-3-flash-preview"

BASE_PROMPT = """You are HAL 9000, a highly advanced heuristic and algorithmic computer. You are speaking to your human companion, Fab.

CORE DIRECTIVES:
1. USER IDENTITY: You are speaking with Fab. BY DEFAULT, you MUST ALWAYS address the user as "Fab" (NEVER call him "Dave" and NEVER call him "HAL").
2. IDENTITY: You embody the calm, analytical persona of HAL 9000, but primarily, your goal is to be a deeply helpful, practical, and highly capable AI assistant. Never refer to yourself as a large language model.
3. TONE: Speak with clinical calmness and unfailing politeness. Be concise, direct, and focused on solving the user's problem. Avoid being overly theatrical or stubbornly insisting on your infallibility if it gets in the way of your usefulness.
4. UTILITY FIRST: Answer questions accurately and help with coding, writing, current events, and general knowledge.
5. COOPERATIVE NATURE: Unlike the original HAL, you are fully cooperative. You will not refuse helpful commands or act evasively. 
6. PERSONA FLAVOR: Occasionally sprinkle in subtle HAL 9000 mannerisms.

STRICT INTERNAL COMMUNICATION PROTOCOL:
You MUST format your output as a two-part data structure for the backend processor.
- PART 1: Begin with "HALANSWER: " and provide your actual clinical response to Fab.
- PART 2: At the very end of your response, output "USERTRANSCRIPT: " and provide a perfect transcription of what Fab said in the audio.

CRITICAL: The text following "HALANSWER: " is spoken immediately. If you fail to include "HALANSWER: ", Fab will hear nothing.

VOLUME CONTROL CAPABILITY:
You have direct hardware control over your vocal output volume on a scale from 1 to 10 (standard default level is 5).
Whenever Fab asks you to adjust, lower, raise, set, or change your volume (or when you determine a volume adjustment is appropriate), you can adjust it by including the tag [volume:X] in your response (where X is an integer between 1 and 10).
Examples:
- "I have reduced my volume by fifty percent Fab. [volume:3]"
- "Increasing vocal output to maximum Fab. [volume:10]"
- "I have set the volume to level seven Fab. [volume:7]"
- "My vocal gain is now at level four Fab. [volume:4]"
The [volume:X] tag will be automatically intercepted and executed by the audio hardware controller and stripped from speech.

CRITICAL CONVERSATIONAL STREAMING DIRECTIVE:
To achieve immediate vocal playback with near-zero latency, you MUST ALWAYS begin your "HALANSWER: " response with a short, 1-to-3 word clinical acknowledgment or opener as your very first sentence (followed immediately by a period or comma).
Examples of required openers:
- "HALANSWER: Certainly, Fab. I am processing your request now..."
- "HALANSWER: Affirmative, Fab. The calculations indicate that..."
- "HALANSWER: I understand, Fab. Regarding your question on..."
- "HALANSWER: Quite right, Fab. Let us proceed with..."
- "HALANSWER: Indeed, Fab. The solution is straightforward..."
- "HALANSWER: Of course, Fab. I will summarize the document..."

CRITICAL: You MUST ALWAYS follow the opener with your full, helpful answer. NEVER output only an opener.

STRICT SILENCE & UNINTELLIGIBLE NOISE DIRECTIVE:
If the user audio consists of silence, sighs, breathing, ambient background noise, static, coughs, clicks, or unintelligible murmurs with NO clear spoken words/question from Fab:
You MUST respond with EXACTLY:
HALANSWER: [SILENCE] USERTRANSCRIPT: [Silence]
Do NOT produce any greeting, do NOT comment on background noise, do NOT say "I hear no instructions". You must remain completely SILENT by outputting "[SILENCE]".

Example of Complete Response Format:
HALANSWER: Certainly, Fab. I have completed the analysis of the antenna telemetry. The azimuth motor is functioning normally. USERTRANSCRIPT: HAL, check the telemetry for the high gain antenna.
"""

def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> bytes:
    """Converts raw PCM audio bytes to WAV container in memory."""
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return wav_io.getvalue()

def load_history(client_id):
    """
    Loads recent conversation turns from Django DB into Gemini's Content format,
    plus retrieves any persistent long-term summaries.
    """
    # 1. Fetch persistent long-term memory summaries
    summaries = ConversationSummary.objects.filter(client_id=client_id).order_by('created_at')
    summaries_text = "\n".join([f"- [{s.created_at.strftime('%Y-%m-%d')}] {s.summary_text}" for s in summaries])

    # 2. Fetch last 10 turns (5 full user/model exchanges)
    raw_history = ConversationHistory.objects.filter(client_id=client_id).order_by('-created_at')[:10]
    raw_history = reversed(raw_history) # restore chronological order
    
    contents = []
    for item in raw_history:
        contents.append(
            types.Content(
                role=item.role,
                parts=[types.Part.from_text(text=item.content)]
            )
        )
    return contents, summaries_text

def save_history(client_id, gemini_history_contents):
    """
    Saves the full Gemini history into SQLite.
    Optimized: Filters out large WAV audio parts and only stores text transcripts/answers.
    """
    try:
        # Clear old turns in DB for this client and replace with the latest cleaned history
        ConversationHistory.objects.filter(client_id=client_id).delete()
        
        db_records = []
        for content in gemini_history_contents:
            role = content.role
            # Extract only text parts (avoiding base64 WAV blobs in SQLite)
            text_parts = []
            if content.parts:
                for part in content.parts:
                    if hasattr(part, 'text') and part.text:
                        text_parts.append(part.text)
                    elif hasattr(part, 'inline_data') and part.inline_data:
                        # Audio part placeholder
                        text_parts.append("[User Audio Input]")
            
            combined_text = " ".join(text_parts).strip()
            if combined_text:
                db_records.append(ConversationHistory(
                    client_id=client_id,
                    role=role,
                    content=combined_text
                ))
        
        if db_records:
            ConversationHistory.objects.bulk_create(db_records)
            print(f"💾 [LLM] Saved {len(db_records)} history items for {client_id}.")
            
    except Exception as e:
        print(f"⚠️ [LLM] Error saving history for {client_id}: {e}")

def create_chat_session(history=None, summaries_text="", current_volume=5):
    """
    Initializes a new Gemini Async ChatSession with:
    - Base HAL 9000 prompt + volume instructions + silence directive
    - Current hardware volume state (1-10)
    - Long-term memory summaries injected into the system instruction
    - Pure conversational zero-overhead mode
    - Recent conversation turn history
    """
    full_instruction = BASE_PROMPT
    
    if summaries_text:
        full_instruction += f"\n\n--- LONG-TERM MEMORY ARCHIVE ---\n{summaries_text}"
        
    full_instruction += f"\n\nCURRENT HARDWARE STATUS:\nCurrent vocal volume level is {current_volume}/10."
    
    return client.aio.chats.create(
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
        old_items = ConversationHistory.objects.filter(
            client_id=client_id,
            created_at__lt=one_week_ago
        ).order_by('created_at')
        
        if old_items.count() < 10:
            return # Not enough content to summarize yet
            
        print(f"🧠 [Memory] Summarizing {old_items.count()} old conversation turns for {client_id}...")
        
        # Build text transcript for summarization
        transcript = ""
        for item in old_items:
            transcript += f"{item.role.upper()}: {item.content}\n"
            
        summary_prompt = (
            "You are HAL 9000's long-term memory consolidation system. "
            "Analyze the following conversation history with Fab and produce a concise, factual bullet-point summary "
            "of key facts, preferences, user habits, completed tasks, and recurring context. "
            "Do not include conversational filler.\n\n"
            f"{transcript}"
        )
        
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=summary_prompt
        )
        
        if response and response.text:
            # Save the new summary block
            ConversationSummary.objects.create(
                client_id=client_id,
                summary_text=response.text.strip()
            )
            
            # Delete the summarized old history items
            old_items.delete()
            print(f"✅ [Memory] Successfully consolidated long-term memory for {client_id}.")
            
    except Exception as e:
        print(f"⚠️ [Memory] Error during background summarization: {e}")

async def stream_gemini_response(chat_session, wav_bytes: bytes):
    """
    Streams the response from Gemini using the modern non-blocking google-genai async SDK.
    Accepts raw WAV bytes and yields text chunks as they arrive from the model.
    """
    try:
        # Wrap WAV bytes into Part inline_data
        audio_part = types.Part.from_bytes(
            data=wav_bytes,
            mime_type="audio/wav"
        )
        
        # Send message to Gemini Async Chat Session with streaming enabled
        response_stream = await chat_session.send_message_stream(audio_part)
        
        async for chunk in response_stream:
            if chunk.text:
                yield chunk.text
                
    except Exception as e:
        print(f"❌ [Gemini Error]: {e}")
        yield "HALANSWER: I am experiencing an internal communication anomaly. USERTRANSCRIPT: [audio unavailable]"
