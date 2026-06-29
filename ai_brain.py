import os
import requests
import json

from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_NAME = "deepseek/deepseek-v3.2-exp"    # 1rd choice: DeepSeek
"qwen/qwen3-235b-a22b-instruct:free",        # 2st choice: Qwen
"meta-llama/llama-4-maverick:free",          # 3nd choice: Llama

# ✅ 429 ya rate limit pe yeh codes check honge
RATE_LIMIT_CODES = {429, 503, 529, 500}

def _build_payload(model: str, content: list, stream: bool) -> dict:
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.4,
        "stream": stream,
    }


def ask_leo_stream(question, stream=False):
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY set nahi hai.")

    prompt = f"""
Tum StudyAI ho. User ke personal private assistant ho.
User ke sawal ka simple Hindi me jawab do.

User question:
{question}
""".strip()

    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "stream": stream
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "StudyAI"
    }

    if stream:
        response = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=120,
            stream=True
        )

        if not response.ok:
            raise ValueError(f"OpenRouter Error {response.status_code}: {response.text}")

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
    else:
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


def ask_leo(question):
    """Non-streaming version"""
    result = ask_leo_stream(question, stream=False)
    if isinstance(result, str):
        return result
    return "".join(result)
