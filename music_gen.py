import os
import base64
from huggingface_hub import InferenceClient

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = InferenceClient(
            model="facebook/musicgen-small",
            token=os.environ.get("HUGGINGFACE_API_KEY")
        )
    return _client

def generate_music_base64(prompt, duration=10):
    client = _get_client()
    audio_bytes = client.text_to_speech(prompt)
    b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
    return f"data:audio/wav;base64,{b64_audio}"
