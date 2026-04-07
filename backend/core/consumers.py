import asyncio
import sys
from channels.generic.websocket import AsyncWebsocketConsumer
from . import llm
from . import tts

# How long to accumulate audio before processing (seconds).
CAPTURE_WINDOW = 2.0

def log(msg):
    """Print with immediate flush so systemd/journalctl shows output in real time."""
    print(msg, flush=True)

class HalConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        log("🔌 [HalConsumer] New connection request from iOS client on /ws/hal/ ...")
        await self.accept()
        log("✅ [HalConsumer] Connection accepted. WebSocket is now open.")
        
        # State variables
        self.audio_buffer = bytearray()
        self.is_recording = False
        self.processing_task = None
        self.chat_session = llm.create_chat_session()

    async def disconnect(self, close_code):
        log(f"🔴 [HalConsumer] Client disconnected. Code: {close_code}")
        if self.processing_task and not self.processing_task.done():
            self.processing_task.cancel()

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data:
            self.audio_buffer.extend(bytes_data)
            
            # Start the capture timer on first chunk only
            if not self.is_recording:
                self.is_recording = True
                log(f"⏺️ [HalConsumer] First audio chunk received. Starting {CAPTURE_WINDOW}s capture window...")
                self.processing_task = asyncio.create_task(self._process_pipeline())

    async def _process_pipeline(self):
        import time
        try:
            # Wait for the capture window to accumulate audio
            await asyncio.sleep(CAPTURE_WINDOW)
            
            buffer_size = len(self.audio_buffer)
            duration_s = buffer_size / (16000 * 2)  # 16kHz, 16-bit mono
            log(f"🤫 [HalConsumer] Capture window ended. Captured {buffer_size} bytes ({duration_s:.1f}s of audio).")
            
            start_time = time.time()
            pcm_bytes = bytes(self.audio_buffer)
            
            if not pcm_bytes:
                return
                
            log("📦 [HalConsumer] Packaging to WAV...")
            wav_bytes = llm.pcm_to_wav(pcm_bytes)
            
            log("🧠 [HalConsumer] Sending audio to Gemini (streaming)...")
            gemini_start = time.time()
            text_buffer = ""
            first_token = True
            sentence_count = 0
            
            async for chunk in llm.generate_chat_response(self.chat_session, wav_bytes):
                if first_token:
                    log(f"⚡ [HalConsumer] Gemini first token in {time.time() - gemini_start:.2f}s")
                    first_token = False
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
                            sentence_count += 1
                            tts_start = time.time()
                            log(f"🗣️ [HalConsumer] Synthesizing sentence #{sentence_count}: {sentence}")
                            tts_audio = await asyncio.to_thread(tts.text_to_speech, sentence)
                            tts_elapsed = time.time() - tts_start
                            if tts_audio:
                                log(f"📤 [HalConsumer] TTS #{sentence_count} took {tts_elapsed:.2f}s, sending {len(tts_audio)} bytes")
                                await self.send(bytes_data=tts_audio)
                    else:
                        break
            
            gemini_elapsed = time.time() - gemini_start
            log(f"⚡ [HalConsumer] Gemini streaming complete in {gemini_elapsed:.2f}s")
            
            # Process any remaining text in the buffer
            final_sentence = text_buffer.strip()
            if final_sentence:
                sentence_count += 1
                tts_start = time.time()
                log(f"🗣️ [HalConsumer] Synthesizing final sentence #{sentence_count}: {final_sentence}")
                tts_audio = await asyncio.to_thread(tts.text_to_speech, final_sentence)
                tts_elapsed = time.time() - tts_start
                if tts_audio:
                    log(f"📤 [HalConsumer] TTS #{sentence_count} took {tts_elapsed:.2f}s, sending {len(tts_audio)} bytes")
                    await self.send(bytes_data=tts_audio)
            
            log("🏁 [HalConsumer] Sending DONE signal to iOS...")
            await self.send(text_data="DONE")
            
            end_time = time.time()
            log(f"⏱️ [HalConsumer] Pipeline complete in {end_time - start_time:.2f}s ({sentence_count} sentences).")
            
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

