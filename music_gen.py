from transformers import pipeline
import scipy.io.wavfile
import base64
import io

_synthesizer = None

def _get_synthesizer():
    global _synthesizer
    if _synthesizer is None:
        _synthesizer = pipeline("text-to-audio", "facebook/musicgen-small")
    return _synthesizer

def generate_music_base64(prompt, duration=10):
    synthesizer = _get_synthesizer()
    music = synthesizer(prompt, forward_params={"do_sample": True, "max_new_tokens": duration * 50})

    buffer = io.BytesIO()
    scipy.io.wavfile.write(buffer, rate=music["sampling_rate"], data=music["audio"][0])
    audio_bytes = buffer.getvalue()

    b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
    return f"data:audio/wav;base64,{b64_audio}"