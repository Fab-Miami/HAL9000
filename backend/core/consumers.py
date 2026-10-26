import asyncio
import json
import re
import time
import datetime
import collections
from channels.generic.websocket import AsyncWebsocketConsumer
from . import hal_brain

# Global in-memory log buffer & real-time subscriber set for https://hal.tuning.net/logs
RECENT_LOGS = collections.deque(maxlen=400)
LOG_SUBSCRIBERS = set()
MAIN_EVENT_LOOP = None

def log(msg):
    """Print with immediate flush so journalctl shows output in real time and broadcasts to live debug viewers."""
    global MAIN_EVENT_LOOP
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    entry = {"time": timestamp, "msg": str(msg)}
    RECENT_LOGS.append(entry)
    print(f"[{timestamp}] {msg}", flush=True)

    if LOG_SUBSCRIBERS:
        payload = json.dumps({"type": "log", "entry": entry})
        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = MAIN_EVENT_LOOP

        if loop and loop.is_running():
            for sub in list(LOG_SUBSCRIBERS):
                try:
                    asyncio.run_coroutine_threadsafe(sub.send(text_data=payload), loop)
                except Exception:
                    pass

def clean_speech_text(text: str) -> str:
    """
    Sanitizes raw LLM output text so that Kokoro TTS generates natural human speech
    without pronouncing markdown punctuation, asterisks, bullet markers, or code symbols.
    """
    if not text:
        return ""
    t = text
    # Remove markdown links [text](url) -> text
    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)
    # Remove code blocks and inline backticks
    t = re.sub(r'```.*?```', '', t, flags=re.DOTALL)
    t = re.sub(r'`([^`]+)`', r'\1', t)
    # Remove markdown headers (# Header)
    t = re.sub(r'#+\s*', '', t)
    # Remove bullet markers like * or - or + or •
    t = re.sub(r'(?:^|\n|\s)[\*\-\+•]\s+', ' ', t)
    # Remove all asterisks, underscores, tildes, backticks, hashes, carets, slashes, @, |, <, >
    t = re.sub(r'[\*\_~`#^|><\\@]', '', t)
    # Convert & to 'and', % to 'percent', + to 'plus'
    t = re.sub(r'\s*&\s*', ' and ', t)
    t = re.sub(r'(\d+)\s*%', r'\1 percent', t)
    t = re.sub(r'\s*\+\s*', ' plus ', t)
    # Remove parentheses and brackets around words
    t = re.sub(r'[\(\)\[\]\{\}]', ' ', t)
    # Collapse multiple whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    return t

ABBREVIATIONS = {'dr.', 'mr.', 'mrs.', 'ms.', 'prof.', 'sr.', 'jr.', 'vs.', 'etc.', 'e.g.', 'i.e.'}

def split_first_sentence(text: str):
    """
    Extracts the first complete sentence from streaming text while strictly respecting:
    - Domain names (e.g., colozzi.com, mindolog.ai)
    - Decimals (e.g., 2.5, 3.14)
    - Honorifics and abbreviations (e.g., Dr., Mr., e.g., i.e.)
    Returns (sentence, remainder). Returns (None, text) if no complete sentence boundary is reached yet.
    """
    matches = list(re.finditer(r'([.!?]+)(?=[\s\n])|(\n+)', text))
    for m in matches:
        punct = m.group(1) or m.group(2)
        candidate = text[:m.end()].strip()

        if '\n' in punct:
            return candidate, text[m.end():].lstrip()

        last_word = candidate.split()[-1].lower() if candidate.split() else ''
        if last_word in ABBREVIATIONS:
            continue

        if re.search(r'\b\d+\.$', candidate):
            remainder_start = text[m.end():]
            if re.match(r'^\d', remainder_start.strip()):
                continue

        return candidate, text[m.end():].lstrip()

    return None, text

# ===========================================================================
# STANDBY WAKE WORD VERIFICATION ($0.00 CLOUD GATE)
# ===========================================================================
# INVIOLABLE ARCHITECTURAL DIRECTIVE (FAB COLOZZI - DO NOT MODIFY):
# Standby wake-up MUST STRICTLY REQUIRE BOTH HAL's identity AND the command "WAKE UP".
# Under NO circumstances should a single-syllable "HAL", a lone greeting ("Hey HAL"),
# or a generic "Wake up" trigger a wake-up.
# Supported compound forms:
# 1. [HAL variations] -> WAKE UP:
#    - "HAL wake up", "Hey HAL wake up", "Hi HAL wake up", "Hello HAL wake up", "OK HAL wake up"
#    - Optional courtesy: "HAL please wake up", "Hey HAL please wake up"
# 2. WAKE UP -> [HAL variations]:
#    - "Wake up HAL", "Wake up, HAL", "Wake up please HAL", "Wake up hey HAL"
# ===========================================================================
def is_hal_wake_word(text: str) -> bool:
    if not text:
        return False
    # Normalize Whisper acronym/hyphen variations: "H.A.L.", "H-A-L", "h-a-l", "H. A. L.", "H A L" -> "hal"
    normalized = re.sub(r'\bh\s*[\.\-]?\s*a\s*[\.\-]?\s*l[\.\-]?\b', 'hal', text, flags=re.IGNORECASE)
    clean = re.sub(r'[.,!?;:\"\'\-]', ' ', normalized.strip().lower())
    clean = re.sub(r'\bh\s+a\s+l\b', 'hal', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    if not clean:
        return False

    # Phonetic variations of HAL heard through glass enclosure (pruned of common words like 'have'):
    hal_tokens = r'(?:hal|hall|hard|heart|hot|how|hold|hawk|hole|hell|hel|al|all|el|ell|hah|huh|ha|hu|ho|haw|hi|high|hai|hy|hie|hey|hay|hug|hugg|hugs|half)'
    # Phonetic variations of WAKE UP heard through glass enclosure and vocal inflections:
    wake_tokens = r'(?:wake\s*up|wakeup|waiker|waker|wake\s*her|wake\s*in|wake\s*it|wait\s*her|wake|woke\s*up|woke|we\s*(?:get|go|got)(?:\s*up)?|wait\s*up|way\s*cup|wick\s*up|wack\s*up|whack\s*up|make\s*up|break\s*up|waking(?:\s*up)?|(?:luke|look|lock)\s*it|(?:luke|look|lock)\s*at|wake\s*cup)'
    greetings = r'(?:hey|hi|hello|ok|okay)'
    filler = r'(?:do\s+|please\s+|can\s+you\s+|you\s+|to\s+|i\s*m\s+|i\s+am\s+|it\s*s\s+|the\s+|a\s+)*'

    # Direction 1: [HAL variation] + [filler] + [wake variation]
    if re.search(rf'\b(?:{greetings}\s+)?{hal_tokens}\s+{filler}{wake_tokens}\b', clean, re.IGNORECASE):
        return True

    # Direction 2: [wake variation] + [filler] + [HAL variation]
    if re.search(rf'\b{wake_tokens}\s+{filler}(?:{greetings}\s+)?{hal_tokens}\b', clean, re.IGNORECASE):
        return True

    # Direction 3: Compound greetings like "ok hal", "okay how" with wake word
    if re.search(rf'\b(?:ok|okay)\s+{hal_tokens}\b', clean, re.IGNORECASE) and re.search(r'\b(?:wake|woke|we\s*(?:get|go))\b', clean, re.IGNORECASE):
        return True

    return False


def is_addressed_to_hal(text: str) -> bool:
    """
    Checks if an utterance is explicitly addressed to HAL.
    Used during active idle mode (> 15s since last interaction) to prevent HAL
    from picking up background room conversations, phone calls, or video audio.
    """
    if not text:
        return False
    normalized = re.sub(r'\bh\s*[\.\-]?\s*a\s*[\.\-]?\s*l[\.\-]?\b', 'hal', text, flags=re.IGNORECASE)
    clean = re.sub(r'[.,!?;:\"\'\-]', ' ', normalized.strip().lower())
    clean = re.sub(r'\bh\s+a\s+l\b', 'hal', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    if not clean:
        return False

    hal_names = r'(?:hal|hall|hard|heart|hot|how|hold|hawk|hole|hell|hel|hah|huh|ha|hu|ho|haw|hi|high|hai|hy|hie|hey|hay|hug|half)'
    greetings = r'(?:hey|hi|hello|ok|okay|so|well|dear|please)'

    # Anchor to start of speech: must begin directly with HAL or Greeting + HAL
    pattern = rf'^(?:{greetings}\s+)?{hal_names}\b'
    return bool(re.search(pattern, clean))


ACTIVE_HAL_CLIENTS = set()


class LogsConsumer(AsyncWebsocketConsumer):
    """Real-time log streaming consumer for https://hal.tuning.net/logs debug viewer."""
    async def connect(self):
        global MAIN_EVENT_LOOP
        MAIN_EVENT_LOOP = asyncio.get_running_loop()
        await self.accept()
        LOG_SUBSCRIBERS.add(self)
        history = list(RECENT_LOGS)
        await self.send(text_data=json.dumps({"type": "history", "logs": history}))

    async def disconnect(self, close_code):
        LOG_SUBSCRIBERS.discard(self)

    async def receive(self, text_data=None, bytes_data=None):
        if text_data == "CLEAR":
            RECENT_LOGS.clear()
            payload = json.dumps({"type": "history", "logs": []})
            for sub in list(LOG_SUBSCRIBERS):
                try:
                    await sub.send(text_data=payload)
                except Exception:
                    LOG_SUBSCRIBERS.discard(sub)
        elif text_data == "SLEEP":
            log("🌙 [Remote Control] SLEEP command received from logs page. Putting console to sleep.")
            for client in list(ACTIVE_HAL_CLIENTS):
                try:
                    await client.send(text_data="SLEEP")
                except Exception:
                    ACTIVE_HAL_CLIENTS.discard(client)
        elif text_data == "RELOAD":
            log("🔄 [Remote Control] RELOAD command received from logs page. Reloading console.")
            for client in list(ACTIVE_HAL_CLIENTS):
                try:
                    await client.send(text_data="RELOAD")
                except Exception:
                    ACTIVE_HAL_CLIENTS.discard(client)


class HalConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        global MAIN_EVENT_LOOP
        MAIN_EVENT_LOOP = asyncio.get_running_loop()
        self.client_id = self.scope['url_route']['kwargs'].get('client_id', 'anonymous')
        log(f"🔌 [HalConsumer] Connection from client: {self.client_id}")
        await self.accept()
        ACTIVE_HAL_CLIENTS.add(self)
        log(f"✅ [HalConsumer] Accepted connection for {self.client_id}.")

        self.processing_task = None
        self.current_volume = 5
        self.is_client_sleeping = False
        self.last_wake_time = 0.0
        self.last_speech_time = 0.0

        # Load 3-tier memory and initialize Gemini chat session
        self.history, self.summaries = await asyncio.to_thread(hal_brain.load_memory, self.client_id)
        self.chat_session = hal_brain.create_chat_session(
            history=self.history,
            summaries_text=self.summaries,
            current_volume=self.current_volume
        )

        # Trigger background summarization for turns prior to 4 AM
        asyncio.create_task(asyncio.to_thread(hal_brain.summarize_old_conversations, self.client_id))

        # Register for tool callback events (LED:API trigger)
        from .tool_events import register_tool_callback
        self._tool_callback = self._on_tool_invoked
        register_tool_callback(self._tool_callback)

    async def disconnect(self, close_code):
        ACTIVE_HAL_CLIENTS.discard(self)
        log(f"🔴 [HalConsumer] Client disconnected (Code: {close_code}).")
        from .tool_events import unregister_tool_callback
        if hasattr(self, '_tool_callback'):
            unregister_tool_callback(self._tool_callback)
        if self.processing_task and not self.processing_task.done():
            self.processing_task.cancel()

    async def _on_tool_invoked(self, tool_name):
        log(f"⚡ [HalConsumer] Tool API execution event: {tool_name} -> Sending LED:API")
        try:
            await self.send(text_data="LED:API")
        except Exception:
            pass

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            try:
                msg = json.loads(text_data)
                if isinstance(msg, dict):
                    if msg.get('type') == 'init':
                        client_ver = msg.get('version')
                        if client_ver != 'v30':
                            log(f"🔄 [HalConsumer] Legacy client detected (version: {client_ver} != v30). Triggering remote reload...")
                            await self.send(text_data="RELOAD")
                            return
                        log("✅ [HalConsumer] Verified v30 client architecture connected.")
                        if 'sleeping' in msg:
                            self.is_client_sleeping = bool(msg.get('sleeping'))
                            log(f"🌙 [HalConsumer] Initial client sleep state synced: {self.is_client_sleeping}")

                    if msg.get('type') == 'playback_complete':
                        self.last_speech_time = time.time()
                        log("⏱️ [HalConsumer] Client voice playback completed on phone speaker. 19s Follow-up Grace Period active.")
                        return

                    if msg.get('type') == 'telemetry':
                        telemetry_msg = str(msg.get('message', ''))
                        if '[WakeLock]' in telemetry_msg:
                            return
                        log(f"📱 [Client Telemetry] {telemetry_msg}")
                        return
                    if msg.get('type') == 'sleep_state':
                        self.is_client_sleeping = bool(msg.get('sleeping'))
                        log(f"🌙 [HalConsumer] Client sleep state: {self.is_client_sleeping}")
                        return
                    if 'volume' in msg:
                        self.current_volume = max(1, min(10, int(msg['volume'])))
                        log(f"🎛️ [HalConsumer] Client volume: {self.current_volume}/10")
            except Exception as e:
                log(f"⚠️ [HalConsumer] JSON parse error: {e}")

        if bytes_data:
            # Strict turn isolation: ignore any stray packets while a turn is actively processing
            if self.processing_task and not self.processing_task.done():
                log("⚠️ [HalConsumer] Ignored incoming audio packet: turn is currently in progress.")
                return

            # Incoming finalized user audio turn (16kHz Mono WAV container)
            duration_s = len(bytes_data) / (16000 * 2)
            log(f"🎙️ [HalConsumer] Received audio turn payload: {len(bytes_data)} bytes (~{duration_s:.1f}s). Dispatching to Gemini...")
            self.processing_task = asyncio.create_task(self._process_audio_turn(bytes_data))

    async def _process_hardware_directives(self, text: str) -> str:
        """Parses and dispatches hardware tags (volume, sleep, optical emotion tags) via WebSocket."""
        if not text:
            return ""

        # 1. Volume tags: [volume: 5]
        vol_match = re.search(r'\[?volume:\s*(\d+)\]?', text, re.IGNORECASE)
        if vol_match:
            new_vol = max(1, min(10, int(vol_match.group(1))))
            self.current_volume = new_vol
            log(f"🔊 [HalConsumer] Volume command parsed: {new_vol}/10")
            await self.send(text_data=f"VOLUME:{new_vol}")
            text = re.sub(r'\[?volume:\s*\d+\]?', '', text, flags=re.IGNORECASE).strip()

        # 2. Sleep tags: strictly [SLEEP]
        if "[SLEEP]" in text.upper():
            log("🌙 [HalConsumer] Sleep command parsed: [SLEEP]")
            self._turn_should_sleep = True
            text = re.sub(r'\[?SLEEP\]?', '', text, flags=re.IGNORECASE).strip()

        # 3. Direct LED Hardware commands: [LED: ON], [LED: OFF]
        led_match = re.search(r'\[?(?:led|lights):\s*(on|off)\]?|\[LED[_\-\s]*(ON|OFF)\]|\[LIGHTS[_\-\s]*(ON|OFF)\]', text, re.IGNORECASE)
        if led_match:
            led_state = (led_match.group(1) or led_match.group(2) or led_match.group(3)).upper()
            log(f"💡 [HalConsumer] LED command parsed: {led_state}")
            await self.send(text_data=f"LED:{led_state}")
            text = re.sub(r'\[?(?:led|lights):\s*(?:on|off)\]?|\[LED[_\-\s]*(?:ON|OFF)\]|\[LIGHTS[_\-\s]*(?:ON|OFF)\]', '', text, flags=re.IGNORECASE).strip()

        # 4. Emotional LED Expressions: [led: chuckle], [led: wink], [led: ponder], etc.
        tag_match = re.search(r'\[?(?:led|lights|tag|mood|emotion):\s*([a-zA-Z0-9_\-]+)\]?|\[(ALERT|EMOTION|SURPRISE|ANGER|WARN|PONDER|CHUCKLE|LAUGH|WINK|BREATHE|WARM|HEARTBEAT)\]', text, re.IGNORECASE)
        if tag_match:
            tag_name = (tag_match.group(1) or tag_match.group(2)).upper()
            log(f"💡 [HalConsumer] Emotional LED tag parsed: {tag_name}")
            await self.send(text_data=f"TAG:{tag_name}")
            text = re.sub(r'\[?(?:led|lights|tag|mood|emotion):\s*[a-zA-Z0-9_\-]+\]?|\[(ALERT|EMOTION|SURPRISE|ANGER|WARN|PONDER|CHUCKLE|LAUGH|WINK|BREATHE|WARM|HEARTBEAT)\]', '', text, flags=re.IGNORECASE).strip()

        return text

    async def _process_audio_turn(self, wav_bytes: bytes):
        """Streams Gemini native audio multimodal response, segments sentences, and feeds Kokoro TTS."""
        transcribe_task = None
        try:
            start_time = time.time()
            self._turn_should_sleep = False

            # Capture history checkpoint before this turn adds anything to memory
            history_checkpoint = hal_brain.get_history_checkpoint(self.chat_session)

            # Standby audio length gate: in sleep mode, reject brief clips < 0.40s (clicks, room spikes)
            duration_s = len(wav_bytes) / (16000 * 2)
            if self.is_client_sleeping and duration_s < 0.40:
                log(f"🔇 [Standby] Discarded brief audio packet ({duration_s:.2f}s < 0.40s threshold). Remaining asleep.")
                await self.send(text_data="DONE")
                return

            # STANDBY WAKE WORD GATE (100% Local Hetzner CPU - $0.00 Cloud Cost):
            # When HAL is in sleep mode, strictly verify wake words locally BEFORE calling Gemini!
            # TV chatter, ambient room noise, or background speech are rejected with ZERO cloud LLM tokens.
            user_transcript = ""
            if self.is_client_sleeping:
                try:
                    local_transcript = await asyncio.wait_for(
                        asyncio.to_thread(hal_brain.transcribe_local_pcm, wav_bytes, log),
                        timeout=3.5
                    )
                except asyncio.TimeoutError:
                    log("⚠️ [Standby] Local Whisper timed out (3.5s). Resetting.")
                    await self.send(text_data="DONE")
                    return

                # DIRECTIVE (FAB COLOZZI): Reject any transcript exceeding 6 words in standby!
                # Wake phrases ("HAL wake up", "Hey HAL wake up") are at most 3-4 words.
                # Transcripts > 6 words are ambient room conversations or Whisper hallucination loops.
                words = local_transcript.strip().split()
                if len(words) > 6:
                    log(f"💤 [Standby] Rejected transcript exceeding 6 words ({len(words)} words): \"{local_transcript[:60]}...\" ($0.00 cost). Remaining asleep.")
                    await self.send(text_data="DONE")
                    return

                if not is_hal_wake_word(local_transcript):
                    log(f"💤 [Standby] Ignored non-wake audio: \"{local_transcript or '[No Speech]'}\" ($0.00 cost). Remaining asleep.")
                    await self.send(text_data="DONE")
                    return

                log(f"☀️ [Standby] Verified wake phrase: \"{local_transcript}\"! Optical wake triggered (silent eye ignition).")
                self.is_client_sleeping = False
                self.last_wake_time = time.time()
                self.last_speech_time = time.time()
                await self.send(text_data="WAKE")
                await self.send(text_data="LED:WINK")
                await self.send(text_data="DONE")
                return
            else:
                # Active conversation turn
                # REDUNDANT WAKE SUPPRESSION:
                # If HAL woke up recently (< 8s) and the incoming audio is a repeated wake phrase
                # (e.g. Fab said "HAL wake up" twice before seeing the eye turn on):
                # remain 100% SILENT. Do NOT invoke Gemini or Kokoro TTS!
                is_recent_wake = (time.time() - getattr(self, 'last_wake_time', 0)) < 8.0
                if is_recent_wake:
                    check_text = await asyncio.to_thread(hal_brain.transcribe_local_pcm, wav_bytes)
                    if is_hal_wake_word(check_text) or re.search(r'\b(?:wake\s*up|wakeup|waker|waiker)\b', check_text, re.IGNORECASE):
                        log(f"☀️ [Active] Ignored redundant wake phrase \"{check_text}\" spoken while waking up. Remaining silent.")
                        await self.send(text_data="LED:WINK")
                        await self.send(text_data="DONE")
                        return

                # DIRECTED ADDRESSING PROTOCOL (FAB COLOZZI DIRECTIVE):
                # Follow-Up Grace Period: 24.0 seconds (21s sinusoidal pulse + 3s fade).
                # The Grace Clock starts strictly at the END of HAL's vocal response on the iPhone speaker.
                # If Fab begins speaking within 24s after HAL finished speaking, Fab can speak freely without saying "HAL".
                # If more than 24s have passed (idle while awake), Fab MUST explicitly address HAL to trigger speech.
                # Non-addressed background conversations (phone calls, TV, thinking aloud) are silently dropped at $0.00 cost.
                turn_duration_s = len(wav_bytes) / 32000.0  # 16kHz 16-bit Mono WAV PCM: 32000 bytes/sec
                speech_onset_time = time.time() - turn_duration_s
                last_spoke = getattr(self, 'last_speech_time', 0.0)
                if last_spoke > 0:
                    time_since_speech = speech_onset_time - last_spoke
                else:
                    time_since_speech = 999999.0

                is_in_grace_period = (time_since_speech <= 24.0)
                log(f"⏱️ [Follow-Up Gate] Speech onset: {max(0.0, time_since_speech):.1f}s after speech end (Turn: {turn_duration_s:.1f}s, Grace: 24.0s, Active: {is_in_grace_period})")

                if not is_in_grace_period:
                    check_text = await asyncio.to_thread(hal_brain.transcribe_local_pcm, wav_bytes)
                    if not is_addressed_to_hal(check_text):
                        log(f"🤫 [Active Idle] Speech not addressed to HAL ({max(0.0, time_since_speech):.1f}s idle): \"{check_text or '[No Speech]'}\" ($0.00 cost). Remaining silent.")
                        if time_since_speech > 300.0:
                            log("🌙 [HalConsumer] Inactivity threshold reached (>300s idle). Dispatching SLEEP to console.")
                            await self.send(text_data="SLEEP")
                        else:
                            await self.send(text_data="DONE")
                        return
                    log(f"🗣️ [Active Idle] Addressing HAL verified: \"{check_text}\"! Engaging conversation.")

                await self.send(text_data="THINKING")
                # In active conversation: transcribe in the background with Gemini 3.5 Flash-Lite
                # STRICT MANDATE: Whisper is NEVER invoked during active conversation (0% CPU on Hetzner)!
                transcribe_task = asyncio.create_task(hal_brain.transcribe_audio_gemini(wav_bytes))

            sentence_queue = asyncio.Queue()

            # Dedicated TTS Streaming Worker Task
            total_tts_bytes = 0
            async def tts_worker():
                nonlocal total_tts_bytes
                sentence_count = 0
                while True:
                    sentence = await sentence_queue.get()
                    if sentence is None:
                        break  # Poison pill

                    speech_text = clean_speech_text(sentence)
                    if not speech_text:
                        sentence_queue.task_done()
                        continue

                    # Safety check: never vocalize silence markers
                    clean_lower = re.sub(r'[^a-z0-9]', '', speech_text.lower())
                    if clean_lower in ('silence', 'none', 'ambient', 'nospeech'):
                        sentence_queue.task_done()
                        continue

                    # Safety check: if response is an accidental wake acknowledgement, stay silent
                    if any(phrase in speech_text.lower() for phrase in ("wide awake", "i am awake", "standing by", "what are we testing")):
                        if (time.time() - getattr(self, 'last_wake_time', 0)) < 15.0:
                            log(f"🤫 [HalConsumer] Suppressed wake response speech: '{speech_text}'")
                            sentence_queue.task_done()
                            continue

                    sentence_count += 1
                    if sentence_count == 1 and self.is_client_sleeping:
                        self.is_client_sleeping = False
                        await self.send(text_data="WAKE")

                    log(f"🗣️ [HalConsumer] Synthesizing sentence #{sentence_count}: {speech_text}")
                    async for audio_chunk in hal_brain.synthesize_tts_stream(speech_text):
                        total_tts_bytes += len(audio_chunk)
                        await self.send(bytes_data=audio_chunk)

                    sentence_queue.task_done()

            tts_task = asyncio.create_task(tts_worker())

            accumulated_text = ""
            full_response_text = ""
            is_silent_response = False

            # Feed raw WAV directly to Gemini 3.5 Flash Lite
            async for token in hal_brain.stream_gemini_audio(self.chat_session, wav_bytes):
                if token == "EVENT:LED_SEARCH":
                    log("🔍 [HalConsumer] Live Web Search active -> Sending LED:SEARCH")
                    await self.send(text_data="LED:SEARCH")
                    continue

                accumulated_text += token

                # If silence protocol triggered, halt audio immediately
                if "[SILENCE]" in accumulated_text.upper():
                    is_silent_response = True
                    log("🤫 [HalConsumer] [SILENCE] protocol triggered. Remaining silent.")
                    while not sentence_queue.empty():
                        try:
                            sentence_queue.get_nowait()
                            sentence_queue.task_done()
                        except Exception:
                            break
                    break

                # Extract and process complete sentences safely (respecting domains, decimals, abbreviations)
                while True:
                    sentence, remainder = split_first_sentence(accumulated_text)
                    if not sentence:
                        break

                    accumulated_text = remainder

                    if "[SILENCE]" in sentence.upper():
                        is_silent_response = True
                        log("🤫 [HalConsumer] [SILENCE] protocol triggered in sentence. Remaining silent.")
                        while not sentence_queue.empty():
                            try:
                                sentence_queue.get_nowait()
                                sentence_queue.task_done()
                            except Exception:
                                break
                        break

                    sentence = await self._process_hardware_directives(sentence)
                    if sentence:
                        full_response_text += sentence + " "
                        await sentence_queue.put(sentence)

                if is_silent_response:
                    break

            # Flush any remaining tail text
            if not is_silent_response and accumulated_text.strip():
                clean_tail = await self._process_hardware_directives(accumulated_text.strip())
                if clean_tail:
                    if "[SILENCE]" in clean_tail.upper():
                        is_silent_response = True
                        log("🤫 [HalConsumer] [SILENCE] protocol triggered in tail text. Remaining silent.")
                    else:
                        full_response_text += clean_tail
                        await sentence_queue.put(clean_tail)

            if not is_silent_response and not full_response_text.strip():
                if self._turn_should_sleep:
                    log("🌙 [HalConsumer] Silent sleep acknowledged.")
                else:
                    is_silent_response = True
                    log("🤫 [HalConsumer] Model produced empty vocal response. Treating as silent.")

            # Stop TTS worker and await completion of speech generation
            await sentence_queue.put(None)
            await tts_task

            # If Kokoro produced speech audio, estimate when playback on the client speaker will finish.
            # 24kHz 16-bit Mono PCM = 48,000 bytes per second.
            # This ensures the grace clock does not start until the end of HAL's answer, even before client confirmation.
            if total_tts_bytes > 0:
                est_playback_duration = total_tts_bytes / 48000.0
                self.last_speech_time = time.time() + est_playback_duration
                log(f"⏱️ [HalConsumer] Dispatched {total_tts_bytes} bytes of voice audio (~{est_playback_duration:.1f}s). Grace clock estimated to start at +{est_playback_duration:.1f}s.")

            # Send SLEEP before DONE so client registers pendingSleep before playback finishes
            if self._turn_should_sleep:
                self._turn_should_sleep = False
                log("🌙 [HalConsumer] Dispatched SLEEP signal to client.")
                await self.send(text_data="SLEEP")

            # CRITICAL MANDATE: Send DONE immediately when speech generation is complete!
            # Never block client playback or state transitions waiting for background CPU transcription.
            log("🏁 [HalConsumer] Sending DONE signal to client.")
            await self.send(text_data="DONE")
            log(f"⏱️ [HalConsumer] Audio turn processed in {time.time() - start_time:.2f}s.")

            if is_silent_response:
                # Cancel local transcription task immediately if still running
                if transcribe_task and not transcribe_task.done():
                    transcribe_task.cancel()
                # Restore history checkpoint to strictly discard this silent turn without touching prior memory
                hal_brain.restore_history_checkpoint(self.chat_session, history_checkpoint)
                log("🧹 [HalConsumer] Restored chat_session checkpoint: silent turn completely purged.")
            else:
                # Note: self.last_speech_time was stamped at audio end (estimated + confirmed via client playback_complete)
                # Asynchronous background persistence: process user transcript & save to SQLite without blocking client
                async def _save_turn_background(t_task, model_text):
                    u_transcript = ""
                    if t_task:
                        try:
                            u_transcript = await t_task
                        except Exception as e:
                            log(f"⚠️ [HalConsumer] Local transcription retrieval error: {e}")

                    if u_transcript and u_transcript.strip() and u_transcript.strip().upper() not in ("[SILENCE]", "SILENCE"):
                        hal_brain.update_chat_history_with_transcript(self.chat_session, u_transcript)

                    display_user_text = u_transcript if (u_transcript and u_transcript.upper() not in ("[SILENCE]", "SILENCE")) else "[Spoken Audio]"
                    display_model_text = model_text.strip() if model_text.strip() else ""
                    if display_model_text:
                        await asyncio.to_thread(hal_brain.save_turn, self.client_id, display_user_text, display_model_text)

                asyncio.create_task(_save_turn_background(transcribe_task, full_response_text))

        except asyncio.CancelledError:
            log("🛑 [HalConsumer] Turn cancelled by client disconnect.")
            if transcribe_task and not transcribe_task.done():
                transcribe_task.cancel()
        except Exception as e:
            log(f"❌ [HalConsumer] Error processing turn: {e}")
            import traceback
            traceback.print_exc()
