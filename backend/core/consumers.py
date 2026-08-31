import asyncio
import json
import re
import sys
import time
import numpy as np
from channels.generic.websocket import AsyncWebsocketConsumer
from . import llm
from . import tts

# How long to wait for silence before processing (seconds).
CAPTURE_WINDOW = 3.0
SILENCE_THRESHOLD = 1000  # Lowered threshold to accommodate the physical enclosure damping sound

import datetime
def log(msg):
    """Print with immediate flush so systemd/journalctl shows output in real time."""
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
    # Remove markdown link syntax [text](url) -> text
    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)
    # Remove code blocks and inline backticks
    t = re.sub(r'```.*?```', '', t, flags=re.DOTALL)
    t = re.sub(r'`([^`]+)`', r'\1', t)
    # Remove markdown headers (# Header)
    t = re.sub(r'#+\s*', '', t)
    # Remove bullet markers like * or - or + or •
    t = re.sub(r'(?:^|\n|\s)[\*\-\+•]\s+', ' ', t)
    # Remove all asterisks, underscores, tildes, backticks, hashes, carets, slashes, backslashes, @, |, <, >
    t = re.sub(r'[\*\_~`#^|><\\@]', '', t)
    # Convert & to 'and', % to 'percent', + to 'plus'
    t = re.sub(r'\s*&\s*', ' and ', t)
    t = re.sub(r'(\d+)\s*%', r'\1 percent', t)
    t = re.sub(r'\s*\+\s*', ' plus ', t)
    # Remove parentheses and brackets around words (e.g. (such as X) -> such as X)
    t = re.sub(r'[\(\)\[\]\{\}]', ' ', t)
    # Collapse multiple whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def is_stop_command(text: str) -> bool:
    """
    Returns True if user explicitly said 'stop', 'halt', 'quiet', 'shut up',
    or if speech contains repeated/consecutive 'stop' words (e.g. 'stop stop', 'stop stop stop').
    """
    if not text:
        return False
    t = text.strip()
    # 1. Consecutive stops: "stop stop", "stop, stop", "no stop stop", "HAL stop stop"
    if re.search(r'\bstop\b(?:[,\s\.\-]+)\bstop\b', t, re.IGNORECASE):
        return True
    # 2. Standalone stop: "stop", "HAL stop", "quiet", "shut up", "halt", "be quiet"
    if re.search(r'^\s*(?:(?:hey\s+|ok\s+)?hal\s*,?\s*)?(?:stop|halt|quiet|shut\s*up|be\s*quiet|silence)[.!?]?\s*$', t, re.IGNORECASE):
        return True
    # 3. Explicit stop speaking: "stop talking", "stop speaking", "shut up", "be quiet"
    if re.search(r'\b(?:stop\s+talking|stop\s+speaking|shut\s+up|be\s+quiet|be\s+silent)\b', t, re.IGNORECASE):
        return True
    return False

class HalConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.client_id = self.scope['url_route']['kwargs'].get('client_id', 'anonymous')
        log(f"🔌 [HalConsumer] New connection from client: {self.client_id}")
        await self.accept()
        log(f"✅ [HalConsumer] Connection accepted for {self.client_id}.")
        
        # State variables
        self.audio_buffer = bytearray()
        self.pre_roll_buffer = bytearray()
        self.last_speech_time = time.time()
        self.is_recording = False
        self.speech_detected = False
        self.processing_task = None
        self.current_volume = 5
        
        # Load recent history and long-term summaries
        self.history, self.summaries = await asyncio.to_thread(llm.load_history, self.client_id)
        self.chat_session = llm.create_chat_session(
            history=self.history, 
            summaries_text=self.summaries, 
            current_volume=self.current_volume
        )
        
        # Trigger background summarization for any other old chats this client might have
        asyncio.create_task(asyncio.to_thread(llm.summarize_old_conversations, self.client_id))

    async def disconnect(self, close_code):
        log(f"🔴 [HalConsumer] Client disconnected. Code: {close_code}")
        if self.processing_task and not self.processing_task.done():
            self.processing_task.cancel()

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            if text_data == "INTERRUPT":
                log("🛑 [HalConsumer] Voice Barge-In signal received. Terminating response generation...")
                if self.processing_task and not self.processing_task.done():
                    self.processing_task.cancel()
                self.audio_buffer = bytearray()
                self.pre_roll_buffer = bytearray()
                self.is_recording = False
                self.speech_detected = False
                return

            try:
                msg = json.loads(text_data)
                if isinstance(msg, dict) and 'volume' in msg:
                    self.current_volume = max(1, min(10, int(msg['volume'])))
                    log(f"🎛️ [HalConsumer] Client synced hardware volume: {self.current_volume}/10")
                    self.chat_session = llm.create_chat_session(
                        history=self.history, 
                        summaries_text=self.summaries, 
                        current_volume=self.current_volume
                    )
            except Exception as e:
                log(f"⚠️ [HalConsumer] JSON message parse error: {e}")

        if bytes_data:
            # Check for voice activity in this chunk
            data = np.frombuffer(bytes_data, dtype=np.int16)
            rms = 0.0
            if len(data) > 0:
                rms = float(np.sqrt(np.mean(np.square(data.astype(np.float32)))))

            if rms > SILENCE_THRESHOLD:
                self.last_speech_time = time.time()
                if not self.is_recording:
                    self.is_recording = True
                    self.speech_detected = True
                    # Prepend pre-roll buffer (0.5s) so speech onset isn't lost
                    self.audio_buffer = bytearray(self.pre_roll_buffer)
                    self.audio_buffer.extend(bytes_data)
                    log(f"🎙️ [HalConsumer] Speech detected (RMS: {rms:.0f}). Capturing until {CAPTURE_WINDOW}s of silence...")
                    self.processing_task = asyncio.create_task(self._process_pipeline())
                else:
                    self.audio_buffer.extend(bytes_data)
            else:
                if self.is_recording:
                    # User spoke previously, now accumulating silence window
                    self.audio_buffer.extend(bytes_data)
                else:
                    # Ambient silence: maintain 0.5s rolling pre-roll buffer (16000 bytes)
                    self.pre_roll_buffer.extend(bytes_data)
                    if len(self.pre_roll_buffer) > 16000:
                        self.pre_roll_buffer = self.pre_roll_buffer[-16000:]

    async def _process_pipeline(self):
        try:
            # Wait for the capture window of silence to accumulate audio
            while time.time() - self.last_speech_time < CAPTURE_WINDOW:
                await asyncio.sleep(0.05)
            
            buffer_size = len(self.audio_buffer)
            duration_s = buffer_size / (16000 * 2)  # 16kHz, 16-bit mono
            log(f"🤫 [HalConsumer] Silence detected. Captured {buffer_size} bytes ({duration_s:.1f}s of audio).")
            
            # If no speech was detected or buffer is too short, reset silently without inference
            if not self.speech_detected or buffer_size < 19200:
                log("⚠️ [HalConsumer] Insufficient speech energy. Resetting silently.")
                self.audio_buffer = bytearray()
                self.pre_roll_buffer = bytearray()
                self.is_recording = False
                self.speech_detected = False
                await self.send(text_data="DONE")
                return

            # Trim trailing dead silence from buffer, leaving a clean 0.15s cushion
            trailing_silence_s = time.time() - self.last_speech_time
            trim_duration_s = max(0.0, trailing_silence_s - 0.15)
            trim_bytes = int(trim_duration_s * 16000) * 2  # Strictly even number of bytes
            
            if trim_bytes > 0 and len(self.audio_buffer) > trim_bytes + 6400:
                pcm_bytes = bytes(self.audio_buffer[:-trim_bytes])
                log(f"✂️ [HalConsumer] Trimmed {trim_bytes} bytes ({trim_duration_s:.2f}s) of dead trailing silence.")
            else:
                pcm_bytes = bytes(self.audio_buffer)
            
            # Ensure strict 16-bit PCM word alignment (must be multiple of 2 bytes)
            if len(pcm_bytes) % 2 != 0:
                pcm_bytes = pcm_bytes[:-1]

            # Strict validation: verify trimmed audio payload duration and RMS volume
            speech_duration_s = len(pcm_bytes) / (16000 * 2)
            audio_arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
            peak_rms = 0.0
            if len(audio_arr) > 0:
                peak_rms = float(np.sqrt(np.mean(np.square(audio_arr))))

            if speech_duration_s < 0.40 or peak_rms < (SILENCE_THRESHOLD * 0.70):
                log(f"🤫 [HalConsumer] Filtered out ambient noise/phantom trigger (Duration: {speech_duration_s:.2f}s, RMS: {peak_rms:.0f}). Resetting.")
                self.audio_buffer = bytearray()
                self.pre_roll_buffer = bytearray()
                self.is_recording = False
                self.speech_detected = False
                await self.send(text_data="DONE")
                return

            # Inform the client that we are now thinking
            await self.send(text_data="THINKING")
            start_time = time.time()
            
            if not pcm_bytes:
                self.is_recording = False
                self.speech_detected = False
                return
                
            log("📦 [HalConsumer] Packaging to WAV...")
            wav_bytes = llm.pcm_to_wav(pcm_bytes)
            
            log("🧠 [HalConsumer] Sending audio to Gemini (streaming)...")
            gemini_start = time.time()
            
            # Set up the Queue for TTS
            sentence_queue = asyncio.Queue()
            
            # Dedicated TTS Worker Task
            async def tts_worker():
                sentence_count = 0
                while True:
                    sentence = await sentence_queue.get()
                    if sentence is None:
                        break # Poison pill received
                    
                    speech_text = clean_speech_text(sentence)
                    if not speech_text:
                        sentence_queue.task_done()
                        continue

                    sentence_count += 1
                    tts_start = time.time()
                    log(f"🗣️ [HalConsumer] Synthesizing sentence #{sentence_count}: {speech_text}")
                    
                    # Stream Kokoro TTS audio chunks back to iOS
                    async for audio_chunk in tts.text_to_speech_stream(speech_text):
                        await self.send(bytes_data=audio_chunk)
                    
                    log(f"📤 [HalConsumer] TTS #{sentence_count} streaming completed in {time.time() - tts_start:.2f}s")
                    sentence_queue.task_done()
            
            tts_task = asyncio.create_task(tts_worker())

            # Text accumulation and sentence boundary detection
            accumulated_text = ""
            full_response_text = ""
            manual_transcript = ""
            first_token_time = None
            is_transcript_mode = False
            is_silent_response = False
            
            # Sentence terminators: period, exclamation, question mark, newline
            sentence_pattern = re.compile(r'([^.!?\n]+[.!?\n]+)')

            # Iterate over the live Gemini stream
            async for token in llm.stream_gemini_response(self.chat_session, wav_bytes):
                if first_token_time is None:
                    first_token_time = time.time()
                    log(f"⚡ [HalConsumer] Gemini first token in {first_token_time - gemini_start:.2f}s")
                
                accumulated_text += token

                # If model responded with [SILENCE], abort speech generation immediately
                if "[SILENCE]" in accumulated_text.upper():
                    is_silent_response = True
                    log("🤫 [HalConsumer] Non-speech/ambient audio detected ([SILENCE]). HAL remaining silent.")
                    break

                # Check if we have crossed into the USERTRANSCRIPT section
                if not is_transcript_mode:
                    if "USERTRANSCRIPT:" in accumulated_text:
                        is_transcript_mode = True
                        parts = accumulated_text.split("USERTRANSCRIPT:")
                        hal_part = parts[0]
                        manual_transcript = parts[1] if len(parts) > 1 else ""
                        
                        # Stop command check: if user said "stop" or consecutive stops, remain completely silent
                        if is_stop_command(manual_transcript):
                            is_silent_response = True
                            log(f"🛑 [HalConsumer] Stop command detected in transcript (\"{manual_transcript.strip()}\"). Halting and remaining silent.")
                            while not sentence_queue.empty():
                                try:
                                    sentence_queue.get_nowait()
                                    sentence_queue.task_done()
                                except Exception:
                                    break
                            break

                        # Process any remaining sentences in the HAL part
                        clean_hal = re.sub(r'(?i)\*?\*?HALANSWER\*?\*?\s*:', '', hal_part).strip()
                        if clean_hal and not clean_hal.upper().startswith("[SILENCE]"):
                            full_response_text += clean_hal + " "
                            await sentence_queue.put(clean_hal)
                        accumulated_text = ""
                    else:
                        # Extract complete sentences from HAL's answer
                        while True:
                            # Strip "HALANSWER: " prefix if present at start of stream
                            accumulated_text = re.sub(r'(?i)^\s*\*?\*?HALANSWER\*?\*?\s*:\s*', '', accumulated_text)
                                
                            match = sentence_pattern.search(accumulated_text)
                            if not match:
                                break
                                
                            complete_sentence = match.group(1).strip()
                            accumulated_text = accumulated_text[match.end():]
                            
                            # Clean up and push to TTS queue
                            if complete_sentence:
                                if complete_sentence.upper().startswith("[SILENCE]"):
                                    is_silent_response = True
                                    break

                                # Intercept and process any embedded volume tag
                                vol_match = re.search(r'\[?volume:\s*(\d+)\]?', complete_sentence, re.IGNORECASE)
                                if vol_match:
                                    new_vol = max(1, min(10, int(vol_match.group(1))))
                                    self.current_volume = new_vol
                                    log(f"🔊 [HalConsumer] Volume command parsed from HAL text: {new_vol}/10")
                                    await self.send(text_data=f"VOLUME:{new_vol}")
                                    complete_sentence = re.sub(r'\[?volume:\s*\d+\]?', '', complete_sentence, flags=re.IGNORECASE).strip()

                                if complete_sentence:
                                    full_response_text += complete_sentence + " "
                                    await sentence_queue.put(complete_sentence)
                else:
                    manual_transcript += token

            # If the stream finished without encountering USERTRANSCRIPT:, flush remaining text
            if not is_silent_response and not is_transcript_mode and accumulated_text.strip():
                clean_tail = re.sub(r'(?i)\*?\*?HALANSWER\*?\*?\s*:', '', accumulated_text).strip()
                if not clean_tail.upper().startswith("[SILENCE]"):
                    vol_match = re.search(r'\[?volume:\s*(\d+)\]?', clean_tail, re.IGNORECASE)
                    if vol_match:
                        new_vol = max(1, min(10, int(vol_match.group(1))))
                        self.current_volume = new_vol
                        log(f"🔊 [HalConsumer] Volume command parsed from HAL text: {new_vol}/10")
                        await self.send(text_data=f"VOLUME:{new_vol}")
                        clean_tail = re.sub(r'\[?volume:\s*\d+\]?', '', clean_tail, flags=re.IGNORECASE).strip()

                    if clean_tail:
                        full_response_text += clean_tail
                        await sentence_queue.put(clean_tail)

            log(f"⚡ [HalConsumer] Gemini streaming complete in {time.time() - gemini_start:.2f}s")
            
            # Extract and log transcript
            manual_transcript = manual_transcript.strip()
            if manual_transcript:
                log(f"🧠 [HalConsumer] Internal Transcript Extracted: {manual_transcript}")
                if is_stop_command(manual_transcript):
                    is_silent_response = True
                    log(f"🛑 [HalConsumer] Stop command confirmed (\"{manual_transcript}\"). Suppressing any remaining audio.")
                    while not sentence_queue.empty():
                        try:
                            sentence_queue.get_nowait()
                            sentence_queue.task_done()
                        except Exception:
                            break

            # Send poison pill to stop TTS worker and wait for synthesis completion
            await sentence_queue.put(None)
            await tts_task

            # Asynchronously persist updated chat history safely
            try:
                history_data = getattr(self.chat_session, 'get_history', lambda: getattr(self.chat_session, '_history', []))()
                await asyncio.to_thread(llm.save_history, self.client_id, history_data, manual_transcript)
            except Exception as hist_err:
                log(f"⚠️ [HalConsumer] History persistence note: {hist_err}")

            # Signal iOS client that audio generation is complete
            log("🏁 [HalConsumer] Sending DONE signal to iOS...")
            await self.send(text_data="DONE")
            log(f"⏱️ [HalConsumer] Pipeline complete in {time.time() - start_time:.2f}s.")

        except asyncio.CancelledError:
            log("🛑 [HalConsumer] Pipeline task cancelled (User barge-in or disconnect).")
        except Exception as e:
            log(f"❌ [HalConsumer] Error in processing pipeline: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Always reset state so HAL is ready for next speech turn
            log("♻️ [HalConsumer] Resetting state for next interaction.")
            self.audio_buffer = bytearray()
            self.pre_roll_buffer = bytearray()
            self.is_recording = False
            self.speech_detected = False
