import os
import requests
import base64
from dotenv import load_dotenv

load_dotenv()

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "").strip()

# Fallback models — pehla fail ho to dusra try hoga
IMAGE_MODELS = [
    "black-forest-labs/FLUX.1-schnell",
    "stabilityai/stable-diffusion-xl-base-1.0",
]

HF_API_URL = "https://router.huggingface.co/hf-inference/models/{}"

def generate_image(prompt: str) -> bytes:
    """Returns raw PNG/JPEG image bytes."""
    if not HF_API_KEY:
        raise ValueError("HUGGINGFACE_API_KEY set nahi hai.")

    if not prompt or not prompt.strip():
        raise ValueError("Prompt khaali hai.")

    headers = {
        "Authorization": f"Bearer {HF_API_KEY}",
        "Content-Type": "application/json",
    }

    last_error = None

    for model in IMAGE_MODELS:
        try:
            url = HF_API_URL.format(model)
            response = requests.post(
                url,
                headers=headers,
                json={"inputs": prompt},
                timeout=90,
            )

            # Model cold-start hone par HF 503 deta hai with estimated_time
            if response.status_code == 503:
                last_error = f"Model {model} load ho raha hai, thodi der baad try karo."
                continue

            if response.status_code == 429:
                last_error = f"Model {model} rate limited."
                continue

            if not response.ok:
                # HF errors kabhi-kabhi JSON body mein aate hain
                try:
                    err_json = response.json()
                    last_error = f"Model {model} error: {err_json.get('error', response.status_code)}"
                except Exception:
                    last_error = f"Model {model} error {response.status_code}"
                continue

            content_type = response.headers.get("content-type", "")
            if "image" not in content_type:
                last_error = f"Model {model} ne image nahi bheji: {response.text[:200]}"
                continue

            return response.content  # raw image bytes

        except requests.exceptions.Timeout:
            last_error = f"Model {model} timeout"
            continue
        except Exception as e:
            last_error = f"Model {model} exception: {str(e)}"
            continue

    raise ValueError(f"Saare image models fail ho gaye. Last error: {last_error}")


def generate_image_base64(prompt: str) -> str:
    """Returns base64 string prefixed with data URI, ready for <img src>."""
    image_bytes = generate_image(prompt)
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/png;base64,{b64}"