import os
import base64
import requests
import json

from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ✅ Fallback chain: Qwen → Llama → DeepSeek
MODELS = [
    "qwen/qwen3-235b-a22b-instruct:free",        # 1st choice: Qwen
    "meta-llama/llama-4-maverick:free",            # 2nd choice: Llama
    "deepseek/deepseek-v3.2-exp",              # 3rd choice: DeepSeek
]

# ✅ 429 ya rate limit pe yeh codes check honge
RATE_LIMIT_CODES = {429, 503, 529, 500}


def _build_payload(model: str, content: list, stream: bool) -> dict:
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.4,
        "stream": stream,
    }


def _build_headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "Leo Assistant",
    }


def _build_content(question: str, screen_text: str, image_path: str | None) -> list:
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

    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
        })

    return content


# =========================================================
# STREAMING VERSION  (generator — yields string chunks)
# =========================================================

def ask_leo_stream(question: str, screen_text: str = "", image_path: str | None = None, stream: bool = True):
    """
    Streaming mode: yields text chunks one by one.
    Non-streaming mode (stream=False): returns full string.
    Tries Qwen → Llama → DeepSeek automatically on rate-limit errors.
    """
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY set nahi hai.")

    content = _build_content(question, screen_text, image_path)
    headers = _build_headers()
    last_error = None

    for model in MODELS:
        payload = _build_payload(model, content, stream)

        try:
            if stream:
                # ── Streaming path ──────────────────────────────────────
                response = requests.post(
                    OPENROUTER_URL,
                    headers=headers,
                    json=payload,
                    timeout=120,
                    stream=True,
                )

                # Rate-limit → try next model
                if response.status_code in RATE_LIMIT_CODES:
                    last_error = f"{model} busy ({response.status_code}). Trying next model..."
                    continue

                if not response.ok:
                    last_error = f"{model} error {response.status_code}: {response.text}"
                    continue

                # ✅ Stream started successfully — yield chunks
                for line in response.iter_lines():
                    if line:
                        line = line.decode("utf-8")
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                return
                            try:
                                json_data = json.loads(data)
                                delta = json_data.get("choices", [{}])[0].get("delta", {})
                                if "content" in delta and delta["content"]:
                                    yield delta["content"]
                            except json.JSONDecodeError:
                                continue
                return  # stream finished cleanly

            else:
                # ── Non-streaming path ──────────────────────────────────
                response = requests.post(
                    OPENROUTER_URL,
                    headers=headers,
                    json=payload,
                    timeout=120,
                )

                if response.status_code in RATE_LIMIT_CODES:
                    last_error = f"{model} busy ({response.status_code}). Trying next model..."
                    continue

                if not response.ok:
                    last_error = f"{model} error {response.status_code}: {response.text}"
                    continue

                data = response.json()
                return data["choices"][0]["message"]["content"].strip()

        except requests.exceptions.Timeout:
            last_error = f"{model} timeout. Trying next model..."
            continue
        except requests.exceptions.ConnectionError:
            last_error = f"{model} connection error. Trying next model..."
            continue

    # Agar saare models fail ho jayein
    raise ValueError(
        f"Saare AI models busy hain. Last error: {last_error or 'Unknown error'}"
    )


# =========================================================
# NON-STREAMING WRAPPER  (backward compatibility)
# =========================================================

def ask_leo(question: str, screen_text: str = "", image_path: str | None = None) -> str:
    """Non-streaming version — returns complete string."""
    result = ask_leo_stream(question, screen_text, image_path, stream=False)

    # Non-streaming returns a plain string directly (not a generator)
    if isinstance(result, str):
        return result

    # Fallback: join generator output (should not reach here normally)
    return "".join(result)


def ask_leo_old(question: str, screen_text: str = "", image_path: str | None = None) -> str:
    """Legacy alias."""
    return ask_leo(question, screen_text, image_path)
