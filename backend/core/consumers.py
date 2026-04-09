import asyncio
import sys
import time
import numpy as np
from channels.generic.websocket import AsyncWebsocketConsumer
from . import llm
from . import tts

# How long to wait for silence before processing (seconds).
CAPTURE_WINDOW = 2.0
SILENCE_THRESHOLD = 500

def log(msg):
    """Print with immediate flush so systemd/journalctl shows output in real time."""
    print(msg, flush=True)

class HalConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.client_id = self.scope['url_route']['kwargs'].get('client_id', 'anonymous')
        log(f"🔌 [HalConsumer] New connection from client: {self.client_id}")
        await self.accept()
        log(f"✅ [HalConsumer] Connection accepted for {self.client_id}.")
        
        # State variables
        self.audio_buffer = bytearray()
        self.is_recording = False
        self.processing_task = None
        self.last_speech_time = 0
        
        # Load recent history and long-term summaries
        history, summaries = await asyncio.to_thread(llm.load_history, self.client_id)
        self.chat_session = llm.create_chat_session(history=history, summaries_text=summaries)
        
        # Trigger background summarization for any other old chats this client might have
        # This runs "when the time comes" in a separate thread, without blocking Dave.
        asyncio.create_task(asyncio.to_thread(llm.summarize_old_conversations, self.client_id))

    async def disconnect(self, close_code):
        log(f"🔴 [HalConsumer] Client disconnected. Code: {close_code}")
        if self.processing_task and not self.processing_task.done():
            self.processing_task.cancel()

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data:
            self.audio_buffer.extend(bytes_data)
            
            # Check for voice activity
            data = np.frombuffer(bytes_data, dtype=np.int16)
            if len(data) > 0:
                # Calculate root mean square (RMS)
                rms = np.sqrt(np.mean(np.square(data.astype(np.float32))))
                if rms > SILENCE_THRESHOLD:
                    self.last_speech_time = time.time()
            
            # Start the capture timer on first chunk only
            if not self.is_recording:
                self.is_recording = True
                self.last_speech_time = time.time()
                log(f"⏺️ [HalConsumer] First audio chunk received. Listening until {CAPTURE_WINDOW}s of silence...")
                self.processing_task = asyncio.create_task(self._process_pipeline())

    async def _process_pipeline(self):
        try:
            # Wait for the capture window of silence to accumulate audio
            while time.time() - self.last_speech_time < CAPTURE_WINDOW:
                await asyncio.sleep(0.1)
            
            buffer_size = len(self.audio_buffer)
            duration_s = buffer_size / (16000 * 2)  # 16kHz, 16-bit mono
            log(f"🤫 [HalConsumer] Silence detected. Captured {buffer_size} bytes ({duration_s:.1f}s of audio).")
            
            # Inform the client that we are now thinking
            await self.send(text_data="THINKING")
            
            start_time = time.time()
            pcm_bytes = bytes(self.audio_buffer)
            
            if not pcm_bytes:
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
                    if sentence is None:  # Sentinel value to terminate
                        sentence_queue.task_done()
                        break
                        
                    sentence_count += 1
                    tts_start = time.time()
                    log(f"🗣️ [HalConsumer] Synthesizing sentence #{sentence_count}: {sentence}")
                    tts_audio = await asyncio.to_thread(tts.text_to_speech, sentence)
                    tts_elapsed = time.time() - tts_start
                    if tts_audio:
                        log(f"📤 [HalConsumer] TTS #{sentence_count} took {tts_elapsed:.2f}s, sending {len(tts_audio)} bytes")
                        await self.send(bytes_data=tts_audio)
                    sentence_queue.task_done()
                    
            tts_task = asyncio.create_task(tts_worker())
            
            text_buffer = ""
            first_token = True
            
            # --- Transcription Interception Logic ---
            interceptor_buffer = ""
            is_stripping = True
            manual_transcript = ""

            async for chunk in llm.generate_chat_response(self.chat_session, wav_bytes):
                if first_token:
                    log(f"⚡ [HalConsumer] Gemini first token in {time.time() - gemini_start:.2f}s")
                    first_token = False
                
                if is_stripping:
                    interceptor_buffer += chunk
                    if "HALANSWER:" in interceptor_buffer:
                        # Split by the marker
                        parts = interceptor_buffer.split("HALANSWER:", 1)
                        # Extract the user transcript from before the marker
                        transcript_raw = parts[0].replace("USERTRANSCRIPT:", "").strip()
                        manual_transcript = transcript_raw
                        log(f"🧠 [HalConsumer] Internal Transcript Extracted: {manual_transcript}")
                        
                        # The rest is the actual response for Dave
                        text_buffer = parts[1]
                        is_stripping = False
                    continue # Keep buffering until we find the marker
                
                text_buffer += chunk
                
                # Check for sentence boundaries
                while True:
                    split_idx = -1
                    for punct in ['. ', '? ', '! ']:
                        idx = text_buffer.find(punct)
                        if idx != -1 and (split_idx == -1 or idx < split_idx):
                            split_idx = idx
                            
                    if split_idx != -1:
                        sentence = text_buffer[:split_idx + 1].strip()
                        text_buffer = text_buffer[split_idx + 1:].lstrip()
                        
                        if sentence:
                            await sentence_queue.put(sentence)
                    else:
                        break
            
            gemini_elapsed = time.time() - gemini_start
            
            # Process any remaining text in the buffer
            final_sentence = text_buffer.strip()
            if final_sentence:
                await sentence_queue.put(final_sentence)
            
            # Shut down queue cleanly
            await sentence_queue.put(None)
            
            # Await the TTS task to ensure everything finishes synthesizing and sending
            await tts_task
            
            log(f"⚡ [HalConsumer] Gemini streaming complete in {gemini_elapsed:.2f}s")
            
            # Save the updated history back to the database, swapping the audio for the text transcript
            history = self.chat_session.get_history()
            await asyncio.to_thread(llm.save_history, self.client_id, history, manual_transcript=manual_transcript)
            
            log("🏁 [HalConsumer] Sending DONE signal to iOS...")
            await self.send(text_data="DONE")
            
            end_time = time.time()
            log(f"⏱️ [HalConsumer] Pipeline complete in {end_time - start_time:.2f}s.")
            
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log(f"❌ [HalConsumer] Error in processing pipeline: {e}")
            import traceback
            traceback.print_exc()
        finally:
            log("♻️ [HalConsumer] Resetting state for next interaction.")
            self.is_recording = False
            self.audio_buffer.clear()

