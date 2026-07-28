import os
import uuid
from huggingface_hub import InferenceClient

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

# Text-to-video model + provider jo HF ke official docs mein confirmed working example hai.
# Alternatives: "tencent/HunyuanVideo-1.5", "Lightricks/LTX-Video", "THUDM/CogVideoX-5b"
VIDEO_MODEL = "Wan-AI/Wan2.2-TI2V-5B"
VIDEO_PROVIDER = "fal-ai"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GENERATED_DIR = os.path.join(BASE_DIR, "static", "generated")


def generate_video_file(prompt: str) -> str:
    """Generates video via HF Inference Providers, saves it to static/generated/,
    returns the public URL path."""
    if not HF_API_KEY:
        raise ValueError("Hugging Face API key set nahi hai (.env mein HUGGINGFACE_API_KEY daalo).")

    os.makedirs(GENERATED_DIR, exist_ok=True)

    try:
        client = InferenceClient(
            provider=VIDEO_PROVIDER,   # "auto" kabhi kabhi galat provider choose kar leta hai
            api_key=HF_API_KEY,
        )
        video_bytes = client.text_to_video(
            prompt,
            model=VIDEO_MODEL,
        )
    except Exception as e:
        msg = str(e)
        if "503" in msg or "loading" in msg.lower():
            raise ValueError("Model load ho raha hai, thodi der baad try karo (cold start).")
        if "429" in msg or "rate limit" in msg.lower() or "exceeded" in msg.lower():
            raise ValueError("Free quota/rate limit khatam ho gaya hai, thodi der baad try karo.")
        raise ValueError(f"HF Inference error: {msg[:300]}")

    filename = f"video_{uuid.uuid4().hex}.mp4"
    filepath = os.path.join(GENERATED_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(video_bytes)

    return f"/static/generated/{filename}"