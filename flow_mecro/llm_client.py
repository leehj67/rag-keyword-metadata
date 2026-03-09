# llm_client.py

import requests
from config import OLLAMA_URL, OLLAMA_MODEL


def call_llm(prompt: str) -> str:
    """
    로컬 Ollama(qwen2:7b)에 프롬프트를 보내 텍스트 생성.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "").strip()
    except requests.exceptions.Timeout:
        print("[LLM] 요청 타임아웃 (180초 초과). 응답을 받지 못했습니다.")
        return ""
    except requests.exceptions.ConnectionError:
        print("[LLM] Ollama 서버에 연결할 수 없습니다. (localhost:11434 확인 필요)")
        return ""
    except Exception as e:
        print(f"[LLM] 예기치 못한 에러: {e}")
        return ""
