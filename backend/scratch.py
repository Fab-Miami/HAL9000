import kokoro_onnx, asyncio

async def main():
    kokoro = kokoro_onnx.Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
    stream = kokoro.create_stream("Hello world. This is a very interesting demonstration.", voice="hal9000", speed=0.9, lang="en-us")
    async for chunk in stream:
        print("chunk tuple length:", len(chunk))
        print("chunk tuple types:", [type(x) for x in chunk])
        break

asyncio.run(main())
