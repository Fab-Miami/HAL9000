import asyncio
import json
import re
import time
import datetime
from channels.generic.websocket import AsyncWebsocketConsumer
from . import hal_brain

def log(msg):
    """Print with immediate flush so journalctl shows output in real time."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] {msg}", flush=True)

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

def is_hal_wake_word(text: str) -> bool:
    """
    Strict validation of wake phrases from standby.
    Only wakes on intentional, unambiguous addresses to HAL:
    1. Direct wake-up phrases: 'wake up hal', 'hal wake up', 'wake up'
    2. Explicit multi-word greetings: 'hey hal', 'hello hal', 'hi hal', 'ok hal', 'good evening/morning/afternoon hal'
    STRICTLY FORBIDDEN:
    - Single word "HAL" (causes false positives from room noise)
    - Starting with bare "HAL, ..." (e.g. "HAL, what time is it")
    """
    if not text:
        return False
    clean = re.sub(r'[.,!?;:\"\'\-]', '', text.strip().lower())
    clean = re.sub(r'\s+', ' ', clean).strip()

    # 1. Direct wake up commands: "wake up hal", "hal wake up", "wake up"
    if re.search(r'\b(?:wake\s*up\s*hal|hal\s*wake\s*up|wake\s*up)\b', clean, re.IGNORECASE):
        words = clean.split()
        if len(words) <= 8:
            return True

    # 2. Explicit multi-word greeting directed to HAL:
    # Requires a greeting word BEFORE "hal" (never bare "hal" or "hal, ...")
    # Supports common Whisper phonetic transcriptions of HAL (hal, how, al, pal, cal, hell, owl)
    hal_phonetic = r"(?:hal|how|al|pal|cal|hell|owl)"
    greeting_prefix = r"(?:hey|ok|okay|hi|hello|good\s+(?:morning|evening|afternoon))"
    if re.search(rf"\b{greeting_prefix}\s+{hal_phonetic}\b", clean, re.IGNORECASE):
        return True

    return False

class HalConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.client_id = self.scope['url_route']['kwargs'].get('client_id', 'anonymous')
        log(f"🔌 [HalConsumer] Connection from client: {self.client_id}")
        await self.accept()
        log(f"✅ [HalConsumer] Accepted connection for {self.client_id}.")

        self.processing_task = None
        self.current_volume = 5
        self.is_client_sleeping = False

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
                        if client_ver != 'v17':
                            log(f"🔄 [HalConsumer] Legacy client detected (version: {client_ver} != v17). Triggering remote reload...")
                            await self.send(text_data="RELOAD")
                            return
                        log("✅ [HalConsumer] Verified v17 client architecture connected.")
                        if 'sleeping' in msg:
                            self.is_client_sleeping = bool(msg.get('sleeping'))
                            log(f"🌙 [HalConsumer] Initial client sleep state synced: {self.is_client_sleeping}")

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

        # 2. Sleep tags: [SLEEP]
        if "[SLEEP]" in text.upper():
            log("🌙 [HalConsumer] Sleep command parsed.")
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
                local_transcript = await asyncio.to_thread(hal_brain.transcribe_local_pcm, wav_bytes)
                if not is_hal_wake_word(local_transcript):
                    log(f"💤 [Standby] Ignored non-wake audio: \"{local_transcript or '[No Speech]'}\" ($0.00 cost). Remaining asleep.")
                    await self.send(text_data="DONE")
                    return

                log(f"☀️ [Standby] Verified wake phrase: \"{local_transcript}\"! Waking HAL from standby.")
                self.is_client_sleeping = False
                await self.send(text_data="WAKE")
                await self.send(text_data="THINKING")
                user_transcript = local_transcript
            else:
                await self.send(text_data="THINKING")
                # In active conversation: transcribe in the background with Gemini 3.5 Flash-Lite
                # STRICT MANDATE: Whisper is NEVER invoked during active conversation (0% CPU on Hetzner)!
                transcribe_task = asyncio.create_task(hal_brain.transcribe_audio_gemini(wav_bytes))

            sentence_queue = asyncio.Queue()

            # Dedicated TTS Streaming Worker Task
            async def tts_worker():
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

                    sentence_count += 1
                    if sentence_count == 1 and self.is_client_sleeping:
                        self.is_client_sleeping = False
                        await self.send(text_data="WAKE")

                    log(f"🗣️ [HalConsumer] Synthesizing sentence #{sentence_count}: {speech_text}")
                    async for audio_chunk in hal_brain.synthesize_tts_stream(speech_text):
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

            # CRITICAL MANDATE: Send DONE immediately when speech generation is complete!
            # Never block client playback or state transitions waiting for background CPU transcription.
            log("🏁 [HalConsumer] Sending DONE signal to client.")
            await self.send(text_data="DONE")
            if self._turn_should_sleep:
                self._turn_should_sleep = False
                await self.send(text_data="SLEEP")
            log(f"⏱️ [HalConsumer] Audio turn processed in {time.time() - start_time:.2f}s.")

            if is_silent_response:
                # Cancel local transcription task immediately if still running
                if transcribe_task and not transcribe_task.done():
                    transcribe_task.cancel()
                # Restore history checkpoint to strictly discard this silent turn without touching prior memory
                hal_brain.restore_history_checkpoint(self.chat_session, history_checkpoint)
                log("🧹 [HalConsumer] Restored chat_session checkpoint: silent turn completely purged.")
            else:
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
