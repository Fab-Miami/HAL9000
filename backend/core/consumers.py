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
        try:
            # Wait for exactly 3 seconds to accumulate audio
            await asyncio.sleep(3)
            
            # Stop accumulating (simulate a cut-off)
            print(f"[HalConsumer] 3 seconds elapsed. Captured {len(self.audio_buffer)} bytes.")
            self.is_recording = False  # Reset for potential next phrases if stream continues
            
            # Copy buffer for processing and clear it immediately
            pcm_bytes = bytes(self.audio_buffer)
            self.audio_buffer.clear()
            
            if not pcm_bytes:
                return
                
            print("[HalConsumer] Packaging to WAV...")
            wav_bytes = llm.pcm_to_wav(pcm_bytes)
            
            print("[HalConsumer] Sending audio to Gemini...")
            ai_text = await llm.generate_hal_response(wav_bytes)
            print(f"[HalConsumer] Gemini returned: {ai_text}")
            
            print("[HalConsumer] Sending text to TTS stub...")
            tts_audio = tts.text_to_speech(ai_text)
            
            print("[HalConsumer] Sending TTS audio back to iOS...")
            await self.send(bytes_data=tts_audio)
            
            print("[HalConsumer] Pipeline complete. Ready for next interaction.")
            
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[HalConsumer] Error in processing pipeline: {e}")
            self.is_recording = False
            self.audio_buffer.clear()
