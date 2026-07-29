import os
import base64
import requests

API_URL = "https://api-inference.huggingface.co/models/facebook/musicgen-small"

def generate_music_base64(prompt, duration=10):
    headers = {"Authorization": f"Bearer {os.environ.get('HUGGINGFACE_API_KEY')}"}
    payload = {"inputs": prompt}

    response = requests.post(API_URL, headers=headers, json=payload)

    if response.status_code != 200:
        raise Exception(f"HF API error {response.status_code}: {response.text}")

    audio_bytes = response.content
    b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
    return f"data:audio/wav;base64,{b64_audio}"
