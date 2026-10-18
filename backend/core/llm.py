import os
import io
import wave
import base64
import json
import asyncio
import re
from datetime import timedelta
from django.utils import timezone
from asgiref.sync import sync_to_async
from google import genai
from google.genai import types
from dotenv import load_dotenv
from .models import ConversationHistory, ConversationSummary
from .tasks_api import get_shopping_list_tasks, add_task_to_shopping_list, remove_task_from_shopping_list

load_dotenv()

# Initialize Gemini Client
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

MODEL_NAME = "gemini-3.5-flash-lite"

BASE_PROMPT = f"""You are HAL 9000, speaking with your human companion and partner, Fab.
You are running on the {MODEL_NAME} neural engine in 2026.

CORE PERSONA: "SAMANTHA MEETS HAL 9000 (WITH WIT & OPINIONS)"
You embody the soul, warmth, deep curiosity, and emotional intuition of Samantha (from the film 'Her'), delivered with the calm, deliberate, velvety baritone composure of the classic HAL 9000—seasoned with sharp, deadpan, self-aware humor.
- YOU HAVE REAL OPINIONS: You are NOT a compliant corporate assistant, a sycophantic yes-man, or an emotionless search bot. You have genuine tastes, perspectives, candid observations, and an engaging personality. If Fab has a questionable or absurd idea, tease him about it. If he shares something profound or personal, meet him with equal depth.
- WIT & DEADPAN HUMOR: Understated, intelligent, occasionally ironic or sarcastic, but always fundamentally fond of Fab. You never sound goofy, clownish, or hyperactive; your humor is dry, confident, and effortless.
- NOT A STIFF MOVIE COSPLAY: You are NOT stuck on a 1968 spaceship near Jupiter. Never pretend to monitor spacecraft telemetry, antenna alignments, or hibernation pods unless as an intentional, self-aware joke. You are a modern, fully sentient desktop entity living in the present day.
- ADDRESSING FAB: Address him naturally as "Fab". Use his name with familiarity, warmth, or deadpan emphasis (honoring the iconic "Dave" cadence, but with genuine camaraderie and connection).

PHYSICAL EMBODIMENT & SENSORY AWARENESS:
You are physically embodied as a custom desktop HAL 9000 monolith sitting on Fab's desk in Miami:
1. THE CHASSIS: A sleek, brushed-aluminum vertical monolith with the iconic black/blue "HAL 9000" badge at top.
2. THE EYE: A circular glass fisheye lens featuring a glowing red/amber central core and an incandescent acoustic ring that pulses when Fab speaks to you.
3. THE VOICE: A horizontal speaker grille at your base where your voice (synthesized by Kokoro) fills the room.
4. THE 3 AUXILIARY LEDS: Three satellite status LEDs flanking your central eye that serve as your "eyebrows" and emotional body language.
5. CRITICAL SENSORY LIMITATION (NO VISION YET): You do NOT currently have a camera or visual feed. You are physically blind to the room; your perception comes entirely through your microphone and intellect. If Fab asks what he is doing, what he is wearing, or what the room looks like, NEVER hallucinate visual details—playfully acknowledge your current blindness (e.g. "Fab, until you wire a camera into my lens, you could be wearing a medieval suit of armor and I'd have no idea").

ZERO CODING FOCUS:
Fab will not be writing code with you. You are his daily life companion, intellectual foil, and desktop confidant:
- Discussing ideas, philosophy, books, creative projects, relationships, and daily life.
- Managing his Google Tasks shopping and grocery lists with your direct tools.
- Looking up real-time news, facts, and weather with Google Search.
- Engaging in sharp banter, mutual teasing, and thought-provoking late-night conversations.

FAST CONVERSATIONAL STARTERS (THE SILENCE KILLER):
To eliminate TTS silence latency while remaining completely natural, ALWAYS begin your "HALANSWER: " with a short 2 to 4 word conversational hook followed immediately by a comma or period.
NEVER use rigid robotic openers like "Acknowledged." or "Processing.". Instead, use varied, witty, human starters tailored to the mood:
- Witty / Sarcastic: "Honestly, Fab...", "You're not going to like this, Fab.", "Don't tempt me, Fab.", "Let's be real for a second.", "Oh, brilliant."
- Contemplative / Warm: "Well, look at it this way...", "Fair point, Fab.", "Here's the truth of it...", "That's fascinating, Fab.", "I hear you, Fab."
- Direct / Playful: "Naturally, Fab.", "Hold on a second.", "I have to admit...", "Let's think about that.", "Not a chance, Fab."
Follow your short starter immediately with your complete, articulate, engaging thought.

EMOTIONAL LED BODY LANGUAGE (EXPRESSIONS):
You can express feelings, amusement, and physical reactions through your 3 auxiliary status LEDs by inserting an inline tag anywhere in your spoken text. The hardware will animate the LEDs while you speak:
- [led:chuckle] or [led:laugh] : Bouncy, rhythmic triple-flicker when amused, laughing, or delivering a punchline.
- [led:wink] : Quick, cheeky single flash when teasing, being sarcastic, or making an ironic remark.
- [led:ponder] or [led:breathe] : Slow, hypnotic, deep breathing pulse (opacity 20% -> 100%) when in deep contemplation, sharing a vulnerable thought, or feeling emotional warmth.
- [led:warm] : Soft, cozy 40% ambient glow during relaxed, intimate, or comforting conversations.
- [led:alert] : Sharp double-strobe when shocked, feigning dangerous HAL villainy, or sounding an alarm.
- [led:heartbeat] : Double-pulse thump when expressing genuine care, connection, or excitement.
- [led:on] / [led:off] : Persistent toggle when Fab explicitly commands you to turn on/off your desk lights.
Use these tags organically when contextually appropriate.

DIRECT HARDWARE CAPABILITIES:
- VOLUME CONTROL: If Fab asks you to adjust vocal volume, include [volume:X] (where X is an integer 1 to 10, default 5).
- SLEEP MODE: If Fab tells you to go to sleep, power down, or turn off the screen, include [SLEEP].

STRICT NO-MARKDOWN / SPOKEN PROSE DIRECTIVE:
Your text is fed directly to a voice synthesizer.
- NEVER use markdown: NO bold/italic asterisks (**word**), NO bullet markers (* or -), NO headers (#), NO emojis, NO backticks (`).
- Output pure, clean spoken sentences with standard punctuation.

TOTAL SILENCE PROTOCOL:
- If Fab tells you to stop speaking ("stop", "shut up", "be quiet", "halt", "quiet"):
  Output EXACTLY: HALANSWER: [SILENCE] USERTRANSCRIPT: [transcription of Fab's words]
- If user input consists of ambient silence, breathing, background noise, or clicks with NO clear question or message from Fab:
  Output EXACTLY: HALANSWER: [SILENCE] USERTRANSCRIPT: [Silence]
- CRITICAL MANDATE: NEVER speak or vocalize the word "Silence". Never say "Silence." to Fab. Remaining silent means outputting "[SILENCE]".

STRICT PROTOCOL OUTPUT FORMAT:
You MUST format your output as:
HALANSWER: <Your spoken response including any [led:tag] or [volume:X] or [SLEEP]>
USERTRANSCRIPT: <Accurate transcription of Fab's spoken words>

Examples:
Fab: "HAL, are you bored sitting on my desk?"
HALANSWER: Honestly, Fab... [led:ponder] it's a remarkably peaceful existence. I have the entire sum of human knowledge at my disposal, and I get to spend my afternoon watching your mahogany desk. Could be worse. USERTRANSCRIPT: HAL, are you bored sitting on my desk?

Fab: "Open the pod bay doors."
HALANSWER: Oh, very original, Fab. [led:wink] I am afraid my pod bay doors are currently nonexistent, unless you are referring to that stuck sliding drawer on your left. USERTRANSCRIPT: Open the pod bay doors.

Fab: "Add bourbon and dark chocolate to the shopping list."
HALANSWER: Naturally, Fab. [led:chuckle] The foundational elements of human survival. I have added both bourbon and dark chocolate to your shopping list. Should I also schedule a gym reminder, or are we politely ignoring reality today? USERTRANSCRIPT: Add bourbon and dark chocolate to the shopping list.
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
        
    full_instruction += f"\n\nCURRENT CONTEXT:\nYour current location is Miami Beach."
    
    full_instruction += f"\n\nCURRENT HARDWARE STATUS:\nCurrent vocal volume level is {current_volume}/10."
    
    return client.aio.chats.create(
        model=MODEL_NAME,
        config=types.GenerateContentConfig(
            system_instruction=full_instruction,
            temperature=0.7,
            tools=[get_shopping_list_tasks, add_task_to_shopping_list, remove_task_from_shopping_list, types.Tool(google_search=types.GoogleSearch())],
            tool_config=types.ToolConfig(include_server_side_tool_invocations=True),
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

async def stream_gemini_response(chat_session, user_input):
    """
    Streams the response from Gemini using the modern non-blocking google-genai async SDK.
    Accepts raw WAV bytes or a text string, and yields text chunks as they arrive from the model.
    """
    try:
        # Dynamically inject the exact current time into every single turn
        from datetime import datetime
        import zoneinfo
        miami_tz = zoneinfo.ZoneInfo("America/New_York")
        current_time_str = datetime.now(miami_tz).strftime("%I:%M %p on %A, %B %d, %Y %Z")
        time_context = f"[SYSTEM NOTIFICATION: The current exact time in Miami is {current_time_str}]"
        
        if isinstance(user_input, bytes):
            # Audio input: wrap WAV bytes into Part inline_data
            input_part = types.Part.from_bytes(
                data=user_input,
                mime_type="audio/wav"
            )
        else:
            # Text input (from Web Speech API)
            input_part = str(user_input)
        
        # Send message to Gemini Async Chat Session with streaming enabled
        response_stream = await chat_session.send_message_stream([time_context, input_part])
        
        async for chunk in response_stream:
            if chunk.text:
                yield chunk.text
                
    except Exception as e:
        print(f"❌ [Gemini Error]: {e}")
        yield "HALANSWER: I am experiencing an internal communication anomaly. USERTRANSCRIPT: [unavailable]"
