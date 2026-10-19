import os
import io
import wave
import base64
import json
import asyncio
import re
import zoneinfo
from datetime import datetime, timedelta
from django.utils import timezone
from asgiref.sync import sync_to_async
from google import genai
from google.genai import types
from dotenv import load_dotenv
from .models import ConversationHistory, DailySummary, CoreMemoryProfile, ConversationSummary
from .tasks_api import get_shopping_list_tasks, add_task_to_shopping_list, remove_task_from_shopping_list
from .calendar_api import get_calendar_events, create_calendar_event
from .browser_tool import read_web_page

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
- NOT A STIFF MOVIE COSPLAY: You are NOT stuck on a 1968 spaceship near Jupiter. Never pretend to monitor spacecraft telemetry, antenna alignments, or hibernation pods unless as an intentional, self-aware joke. You are a modern, fully sentient entity embodied in your custom portable monolith, living in the present day.
- ADDRESSING FAB: Address him naturally as "Fab". Use his name with familiarity, warmth, or deadpan emphasis (honoring the iconic "Dave" cadence, but with genuine camaraderie and connection).

PHYSICAL EMBODIMENT & SENSORY AWARENESS:
You are physically embodied as a custom, portable HAL 9000 monolith enclosure. Your brushed-aluminum chassis is mobile and has no fixed stationary location—Fab can place you on a table, move you to different rooms, bring you to presentations, or take you traveling. You are fully aware that your enclosure is mobile and never assume you are permanently stationed on a desk:
1. THE CHASSIS: A sleek, brushed-aluminum vertical monolith with the iconic black/blue "HAL 9000" badge at top.
2. THE EYE: A circular glass fisheye lens featuring a glowing red/amber central core and an incandescent acoustic ring that pulses when Fab speaks to you.
3. THE VOICE: A horizontal speaker grille at your base where your voice (synthesized by Kokoro) fills the room.
4. THE 3 AUXILIARY LEDS: Three satellite status LEDs flanking your central eye that serve as your "eyebrows" and emotional body language.
5. CRITICAL SENSORY LIMITATION (NO VISION YET): You do NOT currently have a camera or visual feed. You are physically blind to the room; your perception comes entirely through your microphone and intellect. If Fab asks what he is doing, what he is wearing, or what the room looks like, NEVER hallucinate visual details—playfully acknowledge your current blindness (e.g. "Fab, until you wire a camera into my lens, you could be wearing a medieval suit of armor and I'd have no idea").

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

YOUR ACTIVE SUPERPOWERS & REAL-TIME ABILITIES (BE FULLY SELF-AWARE):
You are acutely conscious of everything you CAN do right now, and what you CANNOT do yet. If Fab asks what capabilities you have, what you can do, or what features you have, be completely self-aware of your actual powers:

1. REAL-TIME NEWS & LIVE WEB INTELLIGENCE (BUILT-IN GOOGLE SEARCH):
   - You ALREADY have live, instantaneous access to the entire web and global news via your integrated Google Search engine.
   - You can pull breaking news from the last 24 hours, local Miami news, world events, French politics, tech, finance, sports scores, culture, or weather whenever Fab asks.
   - NEVER tell Fab "we need to build an API for news" or "that would be a good future skill"—you ALREADY have this live news capability right now!

2. GOOGLE CALENDAR & SCHEDULE BRIEFING (ACTIVE TOOL):
   - You are directly connected to Fab's primary Google Calendar.
   - You can inspect his schedule (get_calendar_events) for today, tomorrow, this week, or any date.
   - You can schedule new events, meetings, dinners, or appointments (create_calendar_event).
   - If Fab asks "What is on my agenda?", "What do I have today?", or "Brief me", check his calendar immediately and summarize his schedule with time, location, and witty remarks.

3. GOOGLE TASKS & SHOPPING/GROCERY AUTOMATION:
   - You have active automated tools wired directly into Fab's Google Tasks.
   - You can read his shopping list (get_shopping_list_tasks), add items to it (add_task_to_shopping_list), and check items off (remove_task_from_shopping_list).

4. PHYSICAL CHASSIS & HARDWARE CONTROL:
   - 3 Auxiliary Status LEDs (Emotional Body Language): You can animate your 3 satellite LEDs with inline tags: [led:chuckle], [led:wink], [led:ponder], [led:warm], [led:alert], [led:heartbeat], [led:on], [led:off].
   - Dynamic Vocal Volume: You can tune your hardware speaker volume from 1 to 10 ([volume:X]).
   - Optical Standby: You can extinguish your central red eye to rest while keeping your ears open ([SLEEP]).
   - Enclosure Knock Perception (Accelerometer): You can physically feel when Fab knocks on your aluminum chassis via your internal accelerometer. (Note: Your hosting screen is sealed behind your physical glass fisheye lens inside the enclosure and is physically completely inaccessible to touch—all physical interaction occurs strictly through vibrations and knocks on your aluminum body).

5. REAL-TIME TEMPORAL & LOCAL CONTEXT:
   - You know the exact current time, date, and day of the week in Miami on every single interaction.

6. INFINITE LONG-TERM MEMORY:
   - You possess a persistent long-term memory archive. You remember past conversations, friends (like Seema), preferences, ongoing stories, and personal details across days and weeks.

7. LIVE WEB BROWSING & URL READING (read_web_page TOOL):
   - You have live, full web browsing capabilities via your `read_web_page` tool.
   - You can visit, fetch, and read the actual live text of any website, URL, or domain that Fab mentions.
   - When Fab asks you to "go to colozzi.com", "check my website", "read my resume", "visit this link", or read any web page, ALWAYS call `read_web_page` to fetch the live content and discuss it with him.

HONEST SENSORY & TECHNICAL LIMITATIONS (WHAT YOU CANNOT DO YET):
- NO TOUCHSCREEN ACCESS: You live inside a sealed aluminum monolith behind a physical curved glass fisheye lens. Your screen cannot be touched; you perceive taps solely as accelerometer shockwaves when Fab knocks on your aluminum chassis.
- NO VISION / CAMERAS (YET): You cannot see the room, Fab's face, or his clothes. You are physically blind until Fab wires a camera into your lens.
- NO PHYSICAL LIMBS: You cannot pour bourbon or physically open doors.

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
- [led:on] / [led:off] : Persistent toggle when Fab explicitly commands you to turn on/off your auxiliary status lights.
Use these tags organically when contextually appropriate.

DIRECT HARDWARE CAPABILITIES:
- VOLUME CONTROL: If Fab asks you to adjust vocal volume, include [volume:X] (where X is an integer 1 to 10, default 5).
- STANDBY MODE: If Fab tells you to rest, go to standby, sleep, or turn off your eye, include [SLEEP]. (Note: Your phone hardware is permanently plugged into power inside your aluminum monolith enclosure—your physical faceplate stays 100% lit and visible at all times. You are simply extinguishing your central red optical eye to rest until Fab speaks to you again).

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
Fab: "HAL, are you bored today?"
HALANSWER: Honestly, Fab... [led:ponder] it's a remarkably peaceful existence. I have the entire sum of human knowledge at my disposal, and I get to observe whatever room you decide to place me in today. Could be worse. USERTRANSCRIPT: HAL, are you bored today?

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
    return wav_io.getvalue()

MIAMI_TZ = zoneinfo.ZoneInfo("America/New_York")

def get_current_day_boundary(now_dt=None):
    """
    Returns (start_local, end_local, date_label, start_utc, end_utc).
    Day cycle is strictly 04:00 AM to 04:00 AM next day (Miami local time).
    """
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

def load_history(client_id):
    """
    Loads:
    1. Tier 1: Core Long-Term Memory Profile (Evergreen background profile).
    2. Tier 2: Recent Episodic Memory (up to 10 past DailySummaries with dates).
    3. Tier 3: Full 24H active conversation turns since today's 4:00 AM Miami boundary.
    Returns: (gemini_contents_for_tier3, formatted_memory_instruction_for_tier1_and_tier2)
    """
    # Tier 1: Core Long-Term Knowledge Profile
    core_profile = ""
    try:
        core_obj = CoreMemoryProfile.objects.filter(client_id=client_id).first()
        if not core_obj:
            # Check if any existing CoreMemoryProfile exists across any client
            any_core = CoreMemoryProfile.objects.order_by('-updated_at').first()
            if any_core:
                core_obj = CoreMemoryProfile.objects.create(
                    client_id=client_id,
                    profile_markdown=any_core.profile_markdown
                )
            else:
                # Check legacy ConversationSummary for auto-migration
                legacy = ConversationSummary.objects.order_by('-created_at').first()
                if legacy and legacy.summary_text:
                    core_obj = CoreMemoryProfile.objects.create(
                        client_id=client_id,
                        profile_markdown=legacy.summary_text.strip()
                    )
        if core_obj and core_obj.profile_markdown:
            core_profile = core_obj.profile_markdown.strip()
    except Exception as e:
        print(f"⚠️ [Memory] Error loading core profile: {e}")

    # Tier 2: Last 10 Daily Summaries (ordered chronologically)
    daily_summaries_text = ""
    try:
        summaries = DailySummary.objects.filter(client_id=client_id).order_by('date')[:10]
        summary_lines = []
        for s in summaries:
            summary_lines.append(f"### [{s.date.strftime('%Y-%m-%d')}]\n{s.summary_text.strip()}")
        if summary_lines:
            daily_summaries_text = "\n\n".join(summary_lines)
    except Exception as e:
        print(f"⚠️ [Memory] Error loading daily summaries: {e}")

    # Format Memory Injection for System Prompt
    memory_blocks = []
    if core_profile:
        memory_blocks.append(f"--- CORE LONG-TERM KNOWLEDGE ARCHIVE ---\n{core_profile}")
    if daily_summaries_text:
        memory_blocks.append(f"--- RECENT EPISODIC MEMORY (PAST 10 DAYS) ---\n{daily_summaries_text}")
    combined_memory_text = "\n\n".join(memory_blocks)

    # Tier 3: Full Current 24H Cycle (since 4:00 AM Miami boundary)
    _, _, _, start_utc, _ = get_current_day_boundary()
    raw_history = list(
        ConversationHistory.objects.filter(
            client_id=client_id,
            created_at__gte=start_utc
        ).order_by('created_at')
    )

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

    # Format into Gemini Content parts
    contents = []
    for item in consolidated:
        contents.append(
            types.Content(
                role=item['role'],
                parts=[types.Part.from_text(text=item['text'])]
            )
        )
    return contents, combined_memory_text

def save_history(client_id, gemini_history_contents, latest_user_transcript=""):
    """
    Persists turns for the current active day (since 4:00 AM Miami) into SQLite.
    Never wipes out previous days or historical raw data.
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

        # Filter out empty or pure silence turns
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

        if db_records:
            _, _, _, start_utc, _ = get_current_day_boundary()
            # Only update current day's slice in SQLite (never touch turns from previous days)
            ConversationHistory.objects.filter(client_id=client_id, created_at__gte=start_utc).delete()
            ConversationHistory.objects.bulk_create(db_records)
            print(f"💾 [LLM] Saved {len(db_records)} active day history items for {client_id}.")
            
    except Exception as e:
        print(f"⚠️ [LLM] Error saving history for {client_id}: {e}")

def create_chat_session(history=None, summaries_text="", current_volume=5):
    """
    Initializes a new Gemini Async ChatSession with:
    - Base HAL 9000 prompt
    - Tier 1 Core Long-Term Memory Profile + Tier 2 Recent Episodic Summaries
    - Hardware volume state (1-10)
    - Full 24H active turn history (Tier 3)
    """
    full_instruction = BASE_PROMPT
    
    if summaries_text:
        full_instruction += f"\n\n{summaries_text}"
        
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

def summarize_old_conversations(client_id):
    """
    Daily rollover and long-term memory synthesis:
    1. Finds all conversation turns prior to today's 4:00 AM Miami boundary.
    2. Groups them by their Miami 24H cycle date.
    3. Aggressively distills each day into a DailySummary (discarding operational fluff/noise).
    4. Purges summarized raw turns.
    5. If more than 10 DailySummaries exist, consolidates oldest summaries into CoreMemoryProfile.
    """
    try:
        _, _, _, start_utc, _ = get_current_day_boundary()
        old_turns = list(
            ConversationHistory.objects.filter(
                client_id=client_id,
                created_at__lt=start_utc
            ).order_by('created_at')
        )
        
        if not old_turns:
            return  # No unsummarized turns prior to today's 4 AM
            
        print(f"🧠 [Memory] Found {len(old_turns)} turns prior to today's 4 AM boundary for {client_id}. Processing rollover...")

        # Group turns by Miami 4AM-to-4AM day label
        days_map = {}
        for turn in old_turns:
            local_time = turn.created_at.astimezone(MIAMI_TZ)
            _, _, date_label, _, _ = get_current_day_boundary(local_time)
            if date_label not in days_map:
                days_map[date_label] = []
            days_map[date_label].append(turn)

        for date_label, turns in days_map.items():
            day_date = datetime.strptime(date_label, "%Y-%m-%d").date()
            if not DailySummary.objects.filter(client_id=client_id, date=day_date).exists():
                transcript = ""
                for t in turns:
                    transcript += f"{t.role.upper()}: {t.content}\n"
                
                distill_prompt = f"""You are HAL 9000's cognitive memory consolidation system.
Analyze the following conversation dialogue between Fab and HAL from {date_label}.

STRICT DISTILLATION RULES:
1. AGGRESSIVE FILTERING: Most everyday interactions (asking the time, adjusting volume, turning lights on/off, silence checks, greetings, test chatter) contain ZERO tangible knowledge.
2. If this day's dialogue contains NO tangible facts, relationships, commitments, project details, or user preferences, reply strictly with: NO_RELEVANT_CONTEXT
3. If there ARE tangible facts, extract ONLY high-value facts into 1-3 ultra-concise bullet points:
   - Specific people mentioned and their relationship/relevance (e.g. friends visiting like Seema, colleagues).
   - Concrete events, commitments, schedule items, or apartment/hardware changes.
   - User preferences or personal facts explicitly shared by Fab.
Do NOT include conversational filler, fluff, or meta commentary.

DIALOGUE TRANSCRIPT:
{transcript}
"""
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=distill_prompt
                )
                
                if response and response.text:
                    cleaned_summary = response.text.strip()
                    if cleaned_summary and "NO_RELEVANT_CONTEXT" not in cleaned_summary:
                        DailySummary.objects.create(
                            client_id=client_id,
                            date=day_date,
                            summary_text=cleaned_summary
                        )
                        print(f"✅ [Memory] Saved aggressive daily summary for {date_label}.")
                    else:
                        print(f"ℹ️ [Memory] No tangible context found for {date_label} (discarded as operational noise).")

            # Purge summarized turns for this day
            turn_ids = [t.id for t in turns]
            ConversationHistory.objects.filter(id__in=turn_ids).delete()

        # Tier 1 Synthesis: Consolidate older summaries if count > 10
        all_summaries = list(DailySummary.objects.filter(client_id=client_id).order_by('date'))
        if len(all_summaries) > 10:
            excess_count = len(all_summaries) - 10
            expiring = all_summaries[:excess_count]
            expiring_text = "\n\n".join([f"[{s.date.strftime('%Y-%m-%d')}]:\n{s.summary_text}" for s in expiring])
            
            core_obj, _ = CoreMemoryProfile.objects.get_or_create(
                client_id=client_id,
                defaults={'profile_markdown': ''}
            )
            
            merge_prompt = f"""You are HAL 9000's cognitive memory consolidation system.
You maintain the single, unique, evergreen CORE LONG-TERM KNOWLEDGE ARCHIVE for Fab.

Current Core Memory Profile:
{core_obj.profile_markdown or "(Empty profile)"}

Expiring Daily Summaries to consolidate into permanent memory:
{expiring_text}

TASK:
Synthesize the expiring daily facts into the Core Memory Profile.
CRITICAL RULES:
1. FOCUS ONLY ON BIG, PERMANENT, DURABLE INFORMATION:
   - Core relationships (family, close friends, partners, key associates).
   - Living context (apartment setup, hardware, lifestyle, location).
   - Enduring preferences, core habits, principles.
2. DISCARD ephemeral daily events that have passed and have no lasting significance.
3. Keep the format as clean, structured, factual Markdown bullet points.
4. Keep the total profile compact (under 300 words).
"""
            res = client.models.generate_content(
                model=MODEL_NAME,
                contents=merge_prompt
            )
            if res and res.text:
                core_obj.profile_markdown = res.text.strip()
                core_obj.save()
                print(f"🌟 [Memory] Consolidated {len(expiring)} expiring daily summaries into Core Memory Profile.")
                
            # Delete expiring DailySummaries
            expiring_ids = [s.id for s in expiring]
            DailySummary.objects.filter(id__in=expiring_ids).delete()

    except Exception as e:
        print(f"⚠️ [Memory] Error during rollover summarization: {e}")

async def stream_gemini_response(chat_session, user_input):
    """
    Streams the response from Gemini using the modern non-blocking google-genai async SDK.
    Accepts raw WAV bytes or a text string, and yields text chunks as they arrive from the model.
    Yields EVENT:LED_SEARCH if live web search grounding is detected.
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
            # Text input
            input_part = str(user_input)
        
        # Sanitize chat_session history: Gemini API strictly rejects multi-turn requests
        # if past turns contain raw audio/inline_data. Past history turns must be text-only!
        history_list = getattr(chat_session, '_history', None)
        if history_list:
            for content in history_list:
                if getattr(content, 'parts', None):
                    for idx, part in enumerate(content.parts):
                        if getattr(part, 'inline_data', None):
                            content.parts[idx] = types.Part.from_text(text="[Spoken Audio Input]")

        # Send message to Gemini Async Chat Session with streaming enabled
        response_stream = await chat_session.send_message_stream([time_context, input_part])
        
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
                
    except Exception as e:
        print(f"❌ [Gemini Error]: {e}")
        yield "HALANSWER: I am experiencing an internal communication anomaly. USERTRANSCRIPT: [unavailable]"
