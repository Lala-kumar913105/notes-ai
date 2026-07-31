import os
import requests
import json

from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ✅ Model priority list - automatic fallback

MODELS = [
    "meta-llama/llama-4-maverick",
    "deepseek/deepseek-v3.2-exp",
    "deepseek/deepseek-r1-0528",
]

# ✅ In codes pe next model try hoga
RATE_LIMIT_CODES = {429, 503, 529, 500}


def _build_messages(question=None, messages=None):
    """
    Normalizes input into an OpenAI/OpenRouter-style messages list.
    - Prefers `messages` (used for multi-turn chat + follow-up suggestions).
    - Falls back to wrapping a single `question` string (used by Notes/Blog
      generators which still call with a single prompt string).
    """
    if messages:
        return messages

    prompt = f"""
Tum StudyAI ho. User ke personal private assistant ho.
User ke sawal ka simple jawab do, usi language me jismein sawal poocha gaya hai.

User question:
{question}
""".strip()

    return [{"role": "user", "content": prompt}]


def _stream_chunks(messages):
    """Generator: yields text chunks from a streaming OpenRouter response,
    trying each model in MODELS until one works."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "StudyAI"
    }

    last_error = None

    for model in MODELS:
        try:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.4,
                "stream": True
            }

            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=120,
                stream=True
            )

            if response.status_code in RATE_LIMIT_CODES:
                last_error = f"Model {model} rate limited ({response.status_code})"
                continue

            if not response.ok:
                last_error = f"Model {model} error {response.status_code}"
                continue

            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data = line[6:]
                        if data != '[DONE]':
                            try:
                                json_data = json.loads(data)
                                if 'choices' in json_data and len(json_data['choices']) > 0:
                                    delta = json_data['choices'][0].get('delta', {})
                                    if 'content' in delta:
                                        yield delta['content']
                            except json.JSONDecodeError:
                                continue
            return  # success — stop trying other models

        except requests.exceptions.Timeout:
            last_error = f"Model {model} timeout"
            continue
        except Exception as e:
            last_error = f"Model {model} exception: {str(e)}"
            continue

    raise ValueError(f"Saare models fail ho gaye. Last error: {last_error}")


def _call_once(messages):
    """Plain (non-generator) function: returns the full response string.
    Kept separate from _stream_chunks so the return value is never lost
    inside a generator's StopIteration."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "StudyAI"
    }

    last_error = None

    for model in MODELS:
        try:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.4,
                "stream": False
            }

            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=120
            )

            if response.status_code in RATE_LIMIT_CODES:
                last_error = f"Model {model} rate limited ({response.status_code})"
                continue

            if not response.ok:
                last_error = f"Model {model} error {response.status_code}"
                continue

            data = response.json()
            return data["choices"][0]["message"]["content"].strip()

        except requests.exceptions.Timeout:
            last_error = f"Model {model} timeout"
            continue
        except Exception as e:
            last_error = f"Model {model} exception: {str(e)}"
            continue

    raise ValueError(f"Saare models fail ho gaye. Last error: {last_error}")


def ask_leo_stream(question=None, messages=None, stream=True):
    """
    Unified entry point used by app.py.

    - stream=True  -> returns a generator yielding text chunks (for SSE streaming).
    - stream=False -> returns a generator that yields exactly ONE full string
                       (so existing app.py code like `"".join(ask_leo_stream(...))`
                       keeps working without changes).

    Accepts either:
      - messages=[{"role": "...", "content": "..."}, ...]  (preferred, multi-turn)
      - question="..."   (backward-compatible single-prompt mode)
    """
    msgs = _build_messages(question=question, messages=messages)

    if stream:
        yield from _stream_chunks(msgs)
    else:
        yield _call_once(msgs)


def ask_leo(question):
    """Non-streaming convenience helper — returns a plain string."""
    return _call_once(_build_messages(question=question))