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
            if text_data == "INTERRUPT":
                log("🛑 [HalConsumer] Voice Barge-In signal received. Cancelling response generation.")
                if self.processing_task and not self.processing_task.done():
                    self.processing_task.cancel()
                return

            try:
                msg = json.loads(text_data)
                if isinstance(msg, dict):
                    if msg.get('type') == 'init':
                        client_ver = msg.get('version')
                        if client_ver != 'v4':
                            log(f"🔄 [HalConsumer] Legacy client detected (version: {client_ver} != v4). Triggering remote reload...")
                            await self.send(text_data="RELOAD")
                            return
                        log("✅ [HalConsumer] Verified v4 client architecture connected.")

                    if msg.get('type') == 'telemetry':
                        log(f"📱 [Client Telemetry] {msg.get('message')}")
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
            # Incoming finalized user audio turn (16kHz Mono WAV container)
            duration_s = len(bytes_data) / (16000 * 2)
            log(f"🎙️ [HalConsumer] Received audio turn payload: {len(bytes_data)} bytes (~{duration_s:.1f}s). Dispatching to Gemini...")

            if self.processing_task and not self.processing_task.done():
                self.processing_task.cancel()

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
            await self.send(text_data="SLEEP")
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
        try:
            await self.send(text_data="THINKING")
            start_time = time.time()
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
            sentence_pattern = re.compile(r'(.*?[.!?\n]+)')
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

                # Extract and process complete sentences
                while True:
                    match = sentence_pattern.search(accumulated_text)
                    if not match:
                        break

                    sentence = match.group(1).strip()
                    accumulated_text = accumulated_text[match.end():]

                    if sentence:
                        if "[SILENCE]" in sentence.upper():
                            is_silent_response = True
                            break

                        sentence = await self._process_hardware_directives(sentence)
                        if sentence:
                            full_response_text += sentence + " "
                            await sentence_queue.put(sentence)

            # Flush any remaining tail text
            if not is_silent_response and accumulated_text.strip():
                clean_tail = await self._process_hardware_directives(accumulated_text.strip())
                if clean_tail and "[SILENCE]" not in clean_tail.upper():
                    full_response_text += clean_tail
                    await sentence_queue.put(clean_tail)

            # Stop TTS worker and await completion
            await sentence_queue.put(None)
            await tts_task

            # Asynchronously persist updated chat history to SQLite
            try:
                history_data = getattr(self.chat_session, 'get_history', lambda: getattr(self.chat_session, '_history', []))()
                await asyncio.to_thread(hal_brain.save_turn, self.client_id, history_data)
            except Exception as e:
                log(f"⚠️ [HalConsumer] Memory persistence note: {e}")

            # Notify client that voice playback generation has finished
            log("🏁 [HalConsumer] Sending DONE signal to client.")
            await self.send(text_data="DONE")
            log(f"⏱️ [HalConsumer] Audio turn processed in {time.time() - start_time:.2f}s.")

        except asyncio.CancelledError:
            log("🛑 [HalConsumer] Turn cancelled by user barge-in or disconnect.")
        except Exception as e:
            log(f"❌ [HalConsumer] Error processing turn: {e}")
            import traceback
            traceback.print_exc()
