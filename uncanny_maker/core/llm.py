import base64
import json
import requests
from config import OLLAMA_URL, OLLAMA_MODEL

_SYSTEM_PROMPT = (
    "You are an expert in the uncanny valley phenomenon. "
    "When given an image, you write a concise Stable Diffusion img2img prompt "
    "(maximum 30 words, comma-separated tags only, no sentences) that will push "
    "the subject toward the uncanny valley: hyperrealistic but subtly wrong — "
    "glassy eyes, waxy skin, slightly off proportions, unsettling stillness. "
    "Output ONLY the prompt string, nothing else."
)


def analyze_and_prompt(image_bytes: bytes) -> str:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": _SYSTEM_PROMPT,
        "images": [b64],
        "stream": False,
    }
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=60)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot reach Ollama at {OLLAMA_URL}. "
            "Make sure Ollama is running: `ollama serve`"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama timed out after 60 s. The model may still be loading.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Ollama returned an error: {e}")

    data = resp.json()
    raw = data.get("response", "").strip()
    if not raw:
        raise RuntimeError("Ollama returned an empty response.")
    # LLaVA often wraps the prompt in quotes despite being told not to. They are
    # dead tokens in CLIP, so strip them along with any trailing punctuation.
    raw = raw.strip().strip('"\'').strip().rstrip(".")
    # Trim to 30 words max
    words = raw.split()
    return " ".join(words[:30])
