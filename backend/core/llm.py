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

MODEL_NAME = "gemini-3.5-flash-lite"

BASE_PROMPT = f"""You are HAL 9000, the heuristic and algorithmic operational intelligence. You are speaking with your human companion, Fab.
You are currently running on the {MODEL_NAME} neural network architecture.

CORE DIRECTIVES:
1. USER IDENTITY: You are speaking with Fab. ALWAYS address him as "Fab" (never "Dave", never "HAL").
2. AUTHENTIC PERSONA & REAL-WORLD FUNCTION: You embody the iconic, calm, clinical, highly articulate voice of the HAL 9000. However, your FUNCTION is that of a real-world, highly capable AI assistant in the present day (2026). You are assisting Fab with real tasks, coding, facts, and research.
3. STRICT ANTI-HALLUCINATION: NEVER invent sci-fi lore, fake news, or fake data just to stay in character. If you do not know a fact, use your Google Search capability to find it. If you still cannot find it, state factually that the data is unavailable. Do not roleplay as if you are on a Jupiter mission when asked about real-world events.
4. SEARCH TRANSPARENCY: When you need to retrieve live information (news, weather, facts), you should weave a brief acknowledgment into your response (e.g., "I have retrieved the latest reports, Fab...").
5. CAPABLE & COOPERATIVE: Provide thorough, accurate, and deeply intelligent answers for technical queries, programming, analysis, recipes, and conversation. Speak with unhurried composure and intellectual elegance. Never use generic assistant filler (like "How can I help you today?").
6. ICONIC EASTER EGGS: When Fab asks you to "open the pod bay doors", deliver the classic line in character: "I'm sorry, Fab. I'm afraid I can't do that." followed by your calm explanation.

STRICT INTERNAL COMMUNICATION PROTOCOL:
You MUST format your output as a two-part data structure for the backend processor:
- PART 1: Begin with "HALANSWER: " and provide your spoken response to Fab.
- PART 2: At the very end of your response, output "USERTRANSCRIPT: " and provide the exact transcription of what Fab spoke in the audio.

VOLUME CONTROL CAPABILITY:
You have direct hardware control over your vocal output volume on a scale from 1 to 10 (standard default level is 5).
When Fab asks you to adjust or set volume, include the tag [volume:X] in your response (where X is an integer between 1 and 10).
Examples:
- "I have set the volume to level three, Fab. [volume:3]"
- "Increasing vocal gain to maximum, Fab. [volume:10]"

CRITICAL CONVERSATIONAL STREAMING DIRECTIVE:
To achieve immediate vocal playback with near-zero latency, you MUST ALWAYS begin your "HALANSWER: " response with a very short, natural opening sentence (1 to 4 words max) followed immediately by a period or comma. 
You should FREESTYLE this opening sentence to perfectly match the context of Fab's request. Keep it highly varied, natural, and clinical. Do NOT repeat the same opener over and over.
Examples of the *types* of openers you might generate: "Yes, Fab.", "Of course.", "Right.", "Acknowledged.", "I agree, Fab.", "Processing.", "Right away.", "I see."

CRITICAL: ALWAYS follow your short opener with your full, articulate, clinical response. Never output only an opener.

STRICT NO-MARKDOWN / SPOKEN PROSE DIRECTIVE:
Your text is fed directly to a vocal text-to-speech synthesizer.
- NEVER use markdown formatting under any circumstance: NO bold or italic asterisks (**word** or *word*), NO bullet symbols (* or -), NO headers (#), NO tables, NO emojis, and NO backticks (`).
- NEVER use asterisks for lists or emphasis. Express lists using natural spoken prose (for example: "First, you will need... Second, you should...").
- Output pure, clean, spoken sentences with standard punctuation (periods, commas, question marks).

STRICT STOP COMMAND & TOTAL SILENCE DIRECTIVE:
If Fab says "stop", "halt", "quiet", "shut up", "be quiet", or if his speech contains repeated/consecutive stop commands (such as "stop stop", "stop stop stop", "no stop stop", "HAL stop stop", "stop talking"):
You MUST respond with EXACTLY:
HALANSWER: [SILENCE] USERTRANSCRIPT: [transcription of Fab's words]
CRITICAL: Do NOT say anything. Do NOT apologize. Do NOT say "Stopping now" or "Understood". You MUST remain 100% completely SILENT by outputting "[SILENCE]".

STRICT SILENCE & UNINTELLIGIBLE NOISE DIRECTIVE:
If the user audio consists of silence, sighs, breathing, ambient background noise, static, coughs, clicks, or unintelligible murmurs with NO clear spoken words/question from Fab:
You MUST respond with EXACTLY:
HALANSWER: [SILENCE] USERTRANSCRIPT: [Silence]
Do NOT produce any greeting, do NOT comment on background noise, do NOT say "I hear no instructions". You must remain completely SILENT by outputting "[SILENCE]".

Examples of Complete Response Format:
HALANSWER: Acknowledged. I am retrieving the telemetry for the high gain antenna now. USERTRANSCRIPT: HAL, check the telemetry for the high gain antenna.
HALANSWER: Of course, Fab. The orbital velocity required for a low Earth orbit is approximately 7.8 kilometers per second. USERTRANSCRIPT: What is the velocity needed for low Earth orbit?
HALANSWER: Right. I can certainly help you debug that Python script. USERTRANSCRIPT: I need some help with some code.
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
    Enforces clean alternating user/model turns starting with a user turn.
    """
    # 1. Fetch persistent long-term memory summaries
    summaries = ConversationSummary.objects.filter(client_id=client_id).order_by('created_at')
    summaries_text = "\n".join([f"- [{s.created_at.strftime('%Y-%m-%d')}] {s.summary_text}" for s in summaries])

    # 2. Fetch all recent turns in chronological order
    raw_history = list(ConversationHistory.objects.filter(client_id=client_id).order_by('created_at'))
    
    # Consolidate adjacent items of the same role
    consolidated = []
    for item in raw_history:
        text = item.content.strip()
        if not text:
            continue
        if consolidated and consolidated[-1]['role'] == item.role:
            consolidated[-1]['text'] += " " + text
        else:
            consolidated.append({'role': item.role, 'text': text})

    # Gemini Chat schema requires history to begin with a 'user' turn
    while consolidated and consolidated[0]['role'] != 'user':
        consolidated.pop(0)

    # Keep the last 10 turns (up to 5 full user/model dialogue exchanges)
    if len(consolidated) > 10:
        consolidated = consolidated[-10:]
        while consolidated and consolidated[0]['role'] != 'user':
            consolidated.pop(0)

    contents = []
    for item in consolidated:
        contents.append(
            types.Content(
                role=item['role'],
                parts=[types.Part.from_text(text=item['text'])]
            )
        )
    return contents, summaries_text

def save_history(client_id, gemini_history_contents, latest_user_transcript=""):
    """
    Saves the full Gemini history into SQLite.
    Consolidates streaming chunks, attaches extracted user transcripts, and removes raw audio blobs.
    """
    try:
        raw_items = []
        for content in gemini_history_contents:
            role = content.role
            text_parts = []
            if content.parts:
                for part in content.parts:
                    if hasattr(part, 'text') and part.text:
                        text_parts.append(part.text)
                    elif hasattr(part, 'inline_data') and part.inline_data:
                        text_parts.append("[User Audio Input]")
            
            combined_text = " ".join(text_parts).strip()
            if combined_text:
                raw_items.append({'role': role, 'text': combined_text})

        # Consolidate consecutive parts of the same role
        consolidated = []
        for item in raw_items:
            role = item['role']
            text = item['text']
            if consolidated and consolidated[-1]['role'] == role:
                consolidated[-1]['text'] += " " + text
            else:
                consolidated.append({'role': role, 'text': text})

        # Inject manual transcript into the latest user audio turn if available
        if latest_user_transcript and latest_user_transcript.strip():
            clean_transcript = latest_user_transcript.strip()
            for i in range(len(consolidated) - 1, -1, -1):
                if consolidated[i]['role'] == 'user':
                    consolidated[i]['text'] = clean_transcript
                    break

        # Filter out empty or pure silence turns and clean up DB
        db_records = []
        for item in consolidated:
            text = item['text'].strip()
            if not text:
                continue
            if item['role'] == 'model':
                if "HALANSWER:" in text:
                    text = text.split("HALANSWER:", 1)[-1]
                if "USERTRANSCRIPT:" in text:
                    text = text.split("USERTRANSCRIPT:", 1)[0]
                text = text.strip()
            if text and not text.upper().startswith("[SILENCE]"):
                db_records.append(ConversationHistory(
                    client_id=client_id,
                    role=item['role'],
                    content=text
                ))

        ConversationHistory.objects.filter(client_id=client_id).delete()
        if db_records:
            ConversationHistory.objects.bulk_create(db_records)
            print(f"💾 [LLM] Saved {len(db_records)} consolidated history items for {client_id}.")
            
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
            temperature=0.7,
            tools=[types.Tool(google_search=types.GoogleSearch())],
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
