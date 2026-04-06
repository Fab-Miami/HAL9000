import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from . import llm
from . import tts

# Silence timeout: if no audio chunk arrives for this many seconds, consider speech done.
SILENCE_TIMEOUT = 1.5

class HalConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        print("[HalConsumer] New connection request from iOS client on /ws/hal/ ...")
        await self.accept()
        print("[HalConsumer] Connection accepted. WebSocket is now open.")
        
        # State variables
        self.audio_buffer = bytearray()
        self.is_processing = False
        self.silence_task = None
        self.audio_ready = asyncio.Event()

    async def disconnect(self, close_code):
        print(f"[HalConsumer] Client disconnected. Code: {close_code}")
        # If we're waiting for audio, unblock and let the pipeline handle the partial buffer
        self.audio_ready.set()
        if self.silence_task and not self.silence_task.done():
            self.silence_task.cancel()

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data:
            self.audio_buffer.extend(bytes_data)
            
            # Cancel existing silence timer and restart it
            if self.silence_task and not self.silence_task.done():
                self.silence_task.cancel()
            
            self.silence_task = asyncio.create_task(self._silence_timer())
            
            # Kick off the processing pipeline (only once per interaction)
            if not self.is_processing:
                self.is_processing = True
                print("[HalConsumer] First audio chunk received. Waiting for speech to end...")
                asyncio.create_task(self._process_pipeline())

    async def _silence_timer(self):
        """Fires after SILENCE_TIMEOUT seconds of no new audio chunks."""
        try:
            await asyncio.sleep(SILENCE_TIMEOUT)
            buffer_size = len(self.audio_buffer)
            duration_s = buffer_size / (16000 * 2)  # 16kHz, 16-bit mono
            print(f"[HalConsumer] Silence detected. Captured {buffer_size} bytes ({duration_s:.1f}s of audio).")
            self.audio_ready.set()
        except asyncio.CancelledError:
            pass  # Timer was reset by a new audio chunk

    async def _process_pipeline(self):
        import time
        try:
            # Wait until the silence timer fires (meaning the user stopped talking)
            await self.audio_ready.wait()
            
            start_time = time.time()
            pcm_bytes = bytes(self.audio_buffer)
            
            if not pcm_bytes:
                return
                
            print("[HalConsumer] Packaging to WAV...")
            wav_bytes = llm.pcm_to_wav(pcm_bytes)
            
            print("[HalConsumer] Sending audio to Gemini (streaming)...")
            text_buffer = ""
            
            async for chunk in llm.generate_hal_response(wav_bytes):
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
                            print(f"[HalConsumer] Synthesizing sentence: {sentence}")
                            tts_audio = await asyncio.to_thread(tts.text_to_speech, sentence)
                            if tts_audio:
                                await self.send(bytes_data=tts_audio)
                    else:
                        break
            
            # Process any remaining text in the buffer
            final_sentence = text_buffer.strip()
            if final_sentence:
                print(f"[HalConsumer] Synthesizing final sentence: {final_sentence}")
                tts_audio = await asyncio.to_thread(tts.text_to_speech, final_sentence)
                if tts_audio:
                    await self.send(bytes_data=tts_audio)
            
            print("[HalConsumer] Sending DONE signal to iOS...")
            await self.send(text_data="DONE")
            
            end_time = time.time()
            print(f"[HalConsumer] Pipeline complete in {end_time - start_time:.2f}s.")
            
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[HalConsumer] Error in processing pipeline: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print("[HalConsumer] Resetting state for next interaction.")
            self.is_processing = False
            self.audio_buffer.clear()
            self.audio_ready.clear()
