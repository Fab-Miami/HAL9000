import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from . import llm
from . import tts

class HalConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        print("[HalConsumer] New connection request from iOS client on /ws/hal/ ...")
        # Accept the incoming connection
        await self.accept()
        print("[HalConsumer] Connection accepted. WebSocket is now open.")
        
        # State variables to track incoming audio stream
        self.audio_buffer = bytearray()
        self.is_recording = False
        self.processing_task = None

    async def disconnect(self, close_code):
        print(f"[HalConsumer] Client disconnected. Code: {close_code}")
        if self.processing_task:
            self.processing_task.cancel()

    async def receive(self, text_data=None, bytes_data=None):
        # We only expect binary PCM audio from the iPhone right now
        if bytes_data:
            self.audio_buffer.extend(bytes_data)
            
            if not self.is_recording:
                self.is_recording = True
                print("[HalConsumer] First audio chunk received. Starting 3-second capture window...")
                # Start the 3-second timer
                self.processing_task = asyncio.create_task(self.process_audio_after_delay())

    async def process_audio_after_delay(self):
        import time
        try:
            # Wait for 2.0 seconds to accumulate audio (reduced from 3 to improve latency)
            await asyncio.sleep(2.0)
            
            # Stop accumulating (simulate a cut-off)
            print(f"[HalConsumer] 2.0 seconds elapsed. Captured {len(self.audio_buffer)} bytes.")
            self.is_recording = False  # Reset for potential next phrases if stream continues
            
            start_time = time.time()
            # Copy buffer for processing and clear it immediately
            pcm_bytes = bytes(self.audio_buffer)
            self.audio_buffer.clear()
            
            if not pcm_bytes:
                return
                
            print("[HalConsumer] Packaging to WAV...")
            wav_bytes = llm.pcm_to_wav(pcm_bytes)
            
            print("[HalConsumer] Sending audio to Gemini...")
            text_buffer = ""
            
            async for chunk in llm.generate_hal_response(wav_bytes):
                text_buffer += chunk
                
                # Check for sentence boundaries
                while True:
                    # Simple sentence splitters for HAL's formal speech
                    split_idx = -1
                    for punct in ['. ', '? ', '! ']:
                        idx = text_buffer.find(punct)
                        if idx != -1 and (split_idx == -1 or idx < split_idx):
                            split_idx = idx
                            
                    if split_idx != -1:
                        # Extract the full sentence including the punctuation
                        sentence = text_buffer[:split_idx + 1].strip()
                        text_buffer = text_buffer[split_idx + 1:].lstrip()
                        
                        if sentence:
                            print(f"[HalConsumer] Synthesizing sentence: {sentence}")
                            tts_audio = tts.text_to_speech(sentence)
                            if tts_audio:
                                await self.send(bytes_data=tts_audio)
                    else:
                        break
            
            # Process any remaining text in the buffer (e.g. final sentence lacking trailing space)
            final_sentence = text_buffer.strip()
            if final_sentence:
                print(f"[HalConsumer] Synthesizing final sentence: {final_sentence}")
                tts_audio = tts.text_to_speech(final_sentence)
                if tts_audio:
                    await self.send(bytes_data=tts_audio)
            
            print("[HalConsumer] Sending DONE signal to iOS...")
            await self.send(text_data="DONE")
            
            end_time = time.time()
            print(f"[HalConsumer] Pipeline complete in {end_time - start_time:.2f}s. Ready for next interaction.")
            
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[HalConsumer] Error in processing pipeline: {e}")
            self.is_recording = False
            self.audio_buffer.clear()
