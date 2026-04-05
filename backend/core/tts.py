def text_to_speech(text: str) -> bytes:
    """
    Stub for future voice engine.
    Prints the given text and returns a dummy payload (1024 bytes of 0s).
    """
    print(f"TTS Engine received: {text}")
    return b'\x00' * 1024
