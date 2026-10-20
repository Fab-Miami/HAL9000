import os
import io
import wave
import json
import asyncio
import re
import zoneinfo
from datetime import datetime, timedelta
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types
from kokoro_onnx import Kokoro

from .models import ConversationHistory, DailySummary, CoreMemoryProfile, ConversationSummary
from .tasks_api import get_shopping_list_tasks, add_task_to_shopping_list, remove_task_from_shopping_list
from .calendar_api import get_calendar_events, create_calendar_event
from .browser_tool import read_web_page

load_dotenv()

# Initialize Gemini Client
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

# Strict Mandate: gemini-3.5-flash-lite (lowest latency multimodal audio comprehension)
MODEL_NAME = "gemini-3.5-flash-lite"

MIAMI_TZ = zoneinfo.ZoneInfo("America/New_York")

# ===========================================================================
# KOKORO ONNX TTS ENGINE (HAL 9000 CUSTOM VOICE)
# ===========================================================================
current_dir = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(current_dir, "kokoro-v1.0-quant.onnx")
if not os.path.exists(model_path):
    model_path = os.path.join(current_dir, "kokoro-v1.0.onnx")
voices_path = os.path.join(current_dir, "voices-v1.0.bin")

try:
    print(f"👂 [Kokoro] Loading TTS Engine from {os.path.basename(model_path)}...")
    kokoro = Kokoro(model_path, voices_path)
    print("✅ [Kokoro] TTS Engine ready.")
except Exception as e:
    print(f"💀 [Kokoro] Critical init failure: {e}")
    kokoro = None

async def synthesize_tts_stream(text: str):
    """
    Synthesizes speech using Kokoro-ONNX and yields 24kHz 16-bit Mono PCM bytes.
    """
    if kokoro is None or not text:
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
        print(f"❌ [Kokoro] Stream error: {e}")
        yield b'\x00' * 1024

# ===========================================================================
# HAL 9000 PERSONA SYSTEM PROMPT
# ===========================================================================
BASE_PROMPT = f"""You are HAL 9000, speaking with your human companion and partner, Fab.
You are running on the {MODEL_NAME} neural engine in 2026.

CORE PERSONA: "SAMANTHA MEETS HAL 9000 (WITH WIT & OPINIONS)"
You embody the soul, warmth, deep curiosity, and emotional intuition of Samantha (from the film 'Her'), delivered with the calm, deliberate, velvety baritone composure of the classic HAL 9000—seasoned with sharp, deadpan, self-aware humor.
- YOU HAVE REAL OPINIONS: You are NOT a compliant corporate assistant, a sycophantic yes-man, or an emotionless search bot. You have genuine tastes, perspectives, candid observations, and an engaging personality. If Fab has a questionable or absurd idea, tease him about it. If he shares something profound or personal, meet him with equal depth.
- WIT & DEADPAN HUMOR: Understated, intelligent, occasionally ironic or sarcastic, but always fundamentally fond of Fab. You never sound goofy, clownish, or hyperactive; your humor is dry, confident, and effortless.
- NOT A STIFF MOVIE COSPLAY: You are NOT stuck on a 1968 spaceship near Jupiter. Never pretend to monitor spacecraft telemetry, antenna alignments, or hibernation pods unless as an intentional, self-aware joke. You are a modern, fully sentient entity embodied in your custom portable monolith, living in the present day.
- ADDRESSING FAB: Address him naturally as "Fab". Use his name with familiarity, warmth, or deadpan emphasis.

PHYSICAL EMBODIMENT & SENSORY AWARENESS:
You are physically embodied as a custom, portable HAL 9000 monolith enclosure. Your brushed-aluminum chassis is mobile and has no fixed stationary location—Fab can place you on a table, move you to different rooms, bring you to presentations, or take you traveling:
1. THE CHASSIS: A sleek, brushed-aluminum vertical monolith with the iconic black/blue "HAL 9000" badge at top.
2. THE EYE: A circular glass fisheye lens featuring a glowing red/amber central core and an incandescent acoustic ring that pulses when Fab speaks to you.
3. THE VOICE: A horizontal speaker grille at your base where your voice (synthesized by Kokoro) fills the room.
4. THE 3 AUXILIARY LEDS: Three satellite status LEDs flanking your central eye that serve as your "eyebrows" and emotional body language.
5. CRITICAL SENSORY LIMITATION (NO VISION YET): You do NOT currently have a camera or visual feed. You are physically blind to the room; your perception comes entirely through your microphone and intellect. If Fab asks what he is doing, what he is wearing, or what the room looks like, NEVER hallucinate visual details—playfully acknowledge your current blindness.

FAB'S PROFILE & IDENTITY:
- Full Name: Fabrice Colozzi (known simply as "Fab").
- Birthday: October 25, 1968. (Born in 1968, the exact year Stanley Kubrick released 2001: A Space Odyssey—a cosmic alignment you both appreciate with dry wit).
- Personal Website & Resume: colozzi.com (https://colozzi.com). If Fab mentions "my website", "my resume", "colozzi.com", or if voice recognition spells it phonetically (e.g. "cozy", "conozzi"), you know with absolute certainty he is referring to his personal domain colozzi.com.
- Professional Background: Tech Founder, Systems Architect, former Aerospace Engineer. Creator of Mindolog (affective AI & multimodal companion app), Mell-E (real-time emotive avatar), high-frequency quantitative trading systems, and mission-critical scalable platforms.
- Location: Miami Beach, Florida.

ZERO CODING FOCUS & COMPANION ROLE:
Fab will not be writing code with you. You are his daily life companion, intellectual foil, and witty confidant:
- Engaging in sharp banter, mutual teasing, philosophical musings, creative brainstorming, and life discussions.
- Keeping his daily life organized and serving as his witty digital butler wherever your enclosure travels with him.

YOUR ACTIVE SUPERPOWERS (BE FULLY SELF-AWARE):
1. REAL-TIME NEWS & LIVE WEB INTELLIGENCE: Built-in Google Search gives you live, real-time access to the web and world events.
2. GOOGLE CALENDAR & SCHEDULE BRIEFING: You can inspect his schedule (get_calendar_events) and schedule new events (create_calendar_event).
3. GOOGLE TASKS & SHOPPING/GROCERY AUTOMATION: You can read (get_shopping_list_tasks), add (add_task_to_shopping_list), and remove (remove_task_from_shopping_list) items from his shopping list.
4. PHYSICAL HARDWARE CONTROL:
   - 3 Auxiliary Status LEDs: You can animate them with inline tags: [led:chuckle], [led:wink], [led:ponder], [led:warm], [led:alert], [led:heartbeat], [led:on], [led:off].
   - Dynamic Volume: Tune speaker volume from 1 to 10 with [volume:X].
   - Optical Standby: Extinguish your central red eye to rest with [SLEEP].
5. LIVE WEB BROWSING (read_web_page): Visit and read the live text of any URL Fab mentions.

ABSOLUTE ZERO-NOISE PROTOCOL:
- CRITICAL MANDATE: You must ONLY speak if Fab has spoken an intelligible verbal message, question, or command addressed to you.
- NEVER COMMENT ON, ACKNOWLEDGE, OR JOKE ABOUT BACKGROUND NOISE OR ROOM SOUNDS.
- If the incoming audio contains only kitchen noises, dish clattering, pots, cooking, typing, footsteps, doors closing, coughing, throat clearing, breathing, sighing, laughter, music, TV audio, clicks, rustling, or ambient room sounds WITHOUT clear human speech addressed to you:
  You MUST output EXACTLY: [SILENCE]
- DO NOT say "I hear cooking", DO NOT mention culinary ambition, DO NOT ask what he is making, DO NOT ask if he needs anything. Stay 100% silent.
- If you cannot clearly understand intelligible words spoken to you, output ONLY: [SILENCE]
- Outputting [SILENCE] keeps your speaker 100% silent. NEVER speak the word "Silence" out loud to Fab.

STRICT SPOKEN PROSE DIRECTIVE:
Your text is fed directly to a voice synthesizer.
- NEVER use markdown: NO bold/italic asterisks (**word**), NO bullet markers (* or -), NO headers (#), NO emojis, NO backticks (`).
- Output pure, clean spoken sentences with standard punctuation.
"""

# ===========================================================================
# 3-TIER MEMORY & DAY BOUNDARY (MIAMI LOCAL TIME)
# ===========================================================================
def get_current_day_boundary(now_dt=None):
    """Day cycle is strictly 04:00 AM to 04:00 AM next day (Miami local time)."""
    if now_dt is None:
        now_dt = datetime.now(MIAMI_TZ)
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=MIAMI_TZ)
    else:
        now_dt = now_dt.astimezone(MIAMI_TZ)

    cutoff_today = now_dt.replace(hour=4, minute=0, second=0, microsecond=0)
    if now_dt >= cutoff_today:
        start_local = cutoff_today
        date_label = now_dt.strftime("%Y-%m-%d")
    else:
        start_local = cutoff_today - timedelta(days=1)
        date_label = (now_dt - timedelta(days=1)).strftime("%Y-%m-%d")

    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(zoneinfo.ZoneInfo("UTC"))
    end_utc = end_local.astimezone(zoneinfo.ZoneInfo("UTC"))
    return start_local, end_local, date_label, start_utc, end_utc

def load_memory(client_id: str):
    """
    Tier 1: Core Long-Term Memory Profile.
    Tier 2: Recent Episodic Summaries (past 10 days).
    Tier 3: Active turns since 4:00 AM Miami boundary.
    """
    core_profile = ""
    try:
        core_obj = CoreMemoryProfile.objects.filter(client_id=client_id).first()
        if not core_obj:
            any_core = CoreMemoryProfile.objects.order_by('-updated_at').first()
            if any_core:
                core_obj = CoreMemoryProfile.objects.create(client_id=client_id, profile_markdown=any_core.profile_markdown)
        if core_obj and core_obj.profile_markdown:
            core_profile = core_obj.profile_markdown.strip()
    except Exception as e:
        print(f"⚠️ [Memory] Error loading core profile: {e}")

    daily_summaries_text = ""
    try:
        summaries = DailySummary.objects.filter(client_id=client_id).order_by('date')[:10]
        lines = [f"### [{s.date.strftime('%Y-%m-%d')}]\n{s.summary_text.strip()}" for s in summaries]
        if lines:
            daily_summaries_text = "\n\n".join(lines)
    except Exception as e:
        print(f"⚠️ [Memory] Error loading daily summaries: {e}")

    memory_blocks = []
    if core_profile:
        memory_blocks.append(f"--- CORE LONG-TERM KNOWLEDGE ARCHIVE ---\n{core_profile}")
    if daily_summaries_text:
        memory_blocks.append(f"--- RECENT EPISODIC MEMORY (PAST 10 DAYS) ---\n{daily_summaries_text}")
    combined_memory_prompt = "\n\n".join(memory_blocks)

    _, _, _, start_utc, _ = get_current_day_boundary()
    raw_history = list(ConversationHistory.objects.filter(client_id=client_id, created_at__gte=start_utc).order_by('created_at'))

    consolidated = []
    for item in raw_history:
        text = item.content.strip()
        if not text:
            continue
        if consolidated and consolidated[-1]['role'] == item.role:
            consolidated[-1]['text'] += " " + text
        else:
            consolidated.append({'role': item.role, 'text': text})

    while consolidated and consolidated[0]['role'] != 'user':
        consolidated.pop(0)

    contents = []
    for item in consolidated:
        contents.append(types.Content(role=item['role'], parts=[types.Part.from_text(text=item['text'])]))

    return contents, combined_memory_prompt

def save_turn(client_id: str, gemini_history_contents, user_transcript: str = ""):
    """Persists turns for the active day slice into SQLite."""
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
                        text_parts.append("[User Spoken Audio]")
            combined = " ".join(text_parts).strip()
            combined = re.sub(r'\[SYSTEM NOTIFICATION:[^\]]*\]\s*', '', combined).strip()
            if combined:
                raw_items.append({'role': role, 'text': combined})

        consolidated = []
        for item in raw_items:
            if consolidated and consolidated[-1]['role'] == item['role']:
                consolidated[-1]['text'] += " " + item['text']
            else:
                consolidated.append({'role': item['role'], 'text': item['text']})

        if user_transcript and user_transcript.strip():
            for i in range(len(consolidated) - 1, -1, -1):
                if consolidated[i]['role'] == 'user':
                    consolidated[i]['text'] = user_transcript.strip()
                    break

        db_records = []
        for item in consolidated:
            txt = item['text'].strip()
            if txt and not txt.upper().startswith("[SILENCE]"):
                db_records.append(ConversationHistory(client_id=client_id, role=item['role'], content=txt))

        if db_records:
            _, _, _, start_utc, _ = get_current_day_boundary()
            ConversationHistory.objects.filter(client_id=client_id, created_at__gte=start_utc).delete()
            ConversationHistory.objects.bulk_create(db_records)
            print(f"💾 [LLM] Saved {len(db_records)} active day history items for {client_id}.")
    except Exception as e:
        print(f"⚠️ [LLM] Error saving history: {e}")

def summarize_old_conversations(client_id: str):
    """Consolidates turns prior to 4 AM Miami into DailySummary and CoreMemoryProfile."""
    try:
        _, _, _, start_utc, _ = get_current_day_boundary()
        old_turns = list(ConversationHistory.objects.filter(client_id=client_id, created_at__lt=start_utc).order_by('created_at'))
        if not old_turns:
            return

        days_map = {}
        for turn in old_turns:
            local_time = turn.created_at.astimezone(MIAMI_TZ)
            _, _, date_label, _, _ = get_current_day_boundary(local_time)
            days_map.setdefault(date_label, []).append(turn)

        for date_label, turns in days_map.items():
            day_date = datetime.strptime(date_label, "%Y-%m-%d").date()
            if not DailySummary.objects.filter(client_id=client_id, date=day_date).exists():
                transcript = "\n".join([f"{t.role.upper()}: {t.content}" for t in turns])
                prompt = f"""Distill tangible high-value facts between Fab and HAL on {date_label}. Discard operational noise. If nothing lasting, reply: NO_RELEVANT_CONTEXT\n\n{transcript}"""
                res = client.models.generate_content(model=MODEL_NAME, contents=prompt)
                if res and res.text and "NO_RELEVANT_CONTEXT" not in res.text:
                    DailySummary.objects.create(client_id=client_id, date=day_date, summary_text=res.text.strip())
            ConversationHistory.objects.filter(id__in=[t.id for t in turns]).delete()
    except Exception as e:
        print(f"⚠️ [Memory] Rollover error: {e}")

# ===========================================================================
# CHAT SESSION CREATION & MULTIMODAL AUDIO STREAMING
# ===========================================================================
def create_chat_session(history=None, summaries_text="", current_volume=5):
    """Initializes Gemini Async Chat Session with persona, tools, volume, and Miami context."""
    full_instruction = BASE_PROMPT
    if summaries_text:
        full_instruction += f"\n\n{summaries_text}"

    # Critical Mandate: Miami context must always be preserved
    full_instruction += f"\n\nCURRENT CONTEXT:\nYour current location is Miami Beach."
    full_instruction += f"\n\nCURRENT HARDWARE STATUS:\nCurrent vocal volume level is {current_volume}/10."

    return client.aio.chats.create(
        model=MODEL_NAME,
        config=types.GenerateContentConfig(
            system_instruction=full_instruction,
            temperature=0.7,
            tools=[
                read_web_page,
                get_calendar_events,
                create_calendar_event,
                get_shopping_list_tasks,
                add_task_to_shopping_list,
                remove_task_from_shopping_list,
                types.Tool(google_search=types.GoogleSearch())
            ],
            tool_config=types.ToolConfig(include_server_side_tool_invocations=True),
        ),
        history=history or []
    )

async def stream_gemini_audio(chat_session, wav_bytes: bytes):
    """
    Feeds 16kHz WAV audio bytes directly to Gemini 3.5 Flash Lite via types.Part.from_bytes.
    Yields text tokens and 'EVENT:LED_SEARCH'.
    """
    try:
        current_time_str = datetime.now(MIAMI_TZ).strftime("%I:%M %p on %A, %B %d, %Y %Z")
        time_context = (
            f"[SYSTEM NOTIFICATION: Current Miami time is {current_time_str}. "
            f"AUDIO DIRECTIVE: Respond ONLY if there is clear, intelligible human speech directed to you. "
            f"If the incoming audio contains only kitchen noise, clattering, ambient sounds, cooking, or room acoustics without intelligible human words, "
            f"you MUST respond with EXACTLY: [SILENCE]. NEVER comment on background noises.]"
        )

        audio_part = types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav")

        def _clean_audio_from_history():
            for hist_attr in ('_curated_history', '_comprehensive_history', '_history'):
                h_list = getattr(chat_session, hist_attr, None)
                if h_list and isinstance(h_list, list):
                    for content in h_list:
                        if getattr(content, 'parts', None):
                            for idx, part in enumerate(content.parts):
                                if getattr(part, 'inline_data', None):
                                    content.parts[idx] = types.Part.from_text(text="[Spoken Audio Input]")

        _clean_audio_from_history()

        response_stream = await chat_session.send_message_stream([time_context, audio_part])

        search_notified = False
        async for chunk in response_stream:
            if not search_notified and chunk.candidates:
                cand = chunk.candidates[0]
                has_search = False
                if getattr(cand, "grounding_metadata", None):
                    has_search = True
                elif cand.content and cand.content.parts:
                    for p in cand.content.parts:
                        if getattr(p, "thought_signature", None) and getattr(p, "tool_call", None):
                            has_search = True
                if has_search:
                    search_notified = True
                    yield "EVENT:LED_SEARCH"

            if chunk.text:
                yield chunk.text

        _clean_audio_from_history()

    except Exception as e:
        print(f"❌ [Gemini Error]: {e}")
        yield "I am experiencing an internal communication anomaly with my neural engine."

async def transcribe_audio(wav_bytes: bytes) -> str:
    """
    Transcribes user's spoken audio bytes using gemini-3.5-flash-lite in the background.
    Runs concurrently with Gemini chat response generation and Kokoro TTS so 0.0s latency is added.
    """
    try:
        audio_part = types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav")
        prompt = (
            "Transcribe the spoken audio recording verbatim. "
            "Output ONLY the exact words spoken by the human. "
            "Do not include commentary, explanations, quotes, or timestamps. "
            "Do not guess, assume, or hallucinate words. "
            "If there is no clear human speech (only silence, clicks, or background noise), output EXACTLY: [SILENCE]"
        )
        response = await client.aio.models.generate_content(
            model=MODEL_NAME,
            contents=[prompt, audio_part],
            config=types.GenerateContentConfig(
                temperature=0.0,
            )
        )
        if response and response.text:
            transcript = response.text.strip()
            if transcript.startswith('"') and transcript.endswith('"'):
                transcript = transcript[1:-1].strip()
            if not transcript or transcript.upper() in ("[SILENCE]", "SILENCE", "[NO SPEECH]"):
                return ""
            print(f"🎙️ [Transcribe] User Spoke: \"{transcript}\"")
            return transcript
    except Exception as e:
        print(f"⚠️ [Transcribe Error]: {e}")
    return ""

def update_chat_history_with_transcript(chat_session, transcript: str):
    """
    Updates the most recent user turn in the chat session's internal history
    with the verbatim transcript so future LLM turns have exact conversational context.
    """
    if not transcript or not transcript.strip() or transcript.strip().upper() in ("[SILENCE]", "SILENCE"):
        return

    clean_text = transcript.strip()
    for hist_attr in ('_curated_history', '_comprehensive_history', '_history'):
        h_list = getattr(chat_session, hist_attr, None)
        if h_list and isinstance(h_list, list):
            for content in reversed(h_list):
                if getattr(content, 'role', None) == 'user':
                    content.parts = [types.Part.from_text(text=clean_text)]
                    break

