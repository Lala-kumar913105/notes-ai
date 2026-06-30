import os
import requests
import json

from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ✅ Model priority list - automatic fallback
MODELS = [
    "meta-llama/llama-4-maverick",   # 1st choice - fastest, best Hindi
    "deepseek/deepseek-v3.2-exp",           # 2nd choice - smart reasoning
    "deepseek/deepseek-r1-0528",    # 3rd fallback
]

# ✅ In codes pe next model try hoga
RATE_LIMIT_CODES = {429, 503, 529, 500}


def ask_leo_stream(question, stream=False):
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY set nahi hai.")

    prompt = f"""
Tum StudyAI ho. User ke personal private assistant ho.
User ke sawal ka simple Hindi me jawab do.

User question:
{question}
""".strip()

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
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
                "stream": stream
            }

            if stream:
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
                return

            else:
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


def ask_leo(question):
    """Non-streaming version"""
    result = ask_leo_stream(question, stream=False)
    if isinstance(result, str):
        return result
    return "".join(result)
