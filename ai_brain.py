import os
import base64
import requests

from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MODEL_NAME = "deepseek/deepseek-v3.2-exp"


def ask_leo(question, screen_text="", image_path=None):
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY set nahi hai.")

    prompt = f"""
Tum Leo ho. User ke personal private assistant ho.
User ke sawal ka simple Hindi me jawab do.

Agar screenshot ya screen context diya gaya ho, to uske basis par jawab do.
Agar screenshot na ho, to normal assistant ki tarah jawab do.

User question:
{question}

Screen text:
{screen_text}
""".strip()

    content = [{"type": "text", "text": prompt}]

    if image_path:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{image_b64}"
            }
        })

    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.4
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "Leo Assistant"
    }

    response = requests.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
        timeout=120
    )

    if not response.ok:
        raise ValueError(f"OpenRouter Error {response.status_code}: {response.text}")

    data = response.json()
    return data["choices"][0]["message"]["content"].strip()