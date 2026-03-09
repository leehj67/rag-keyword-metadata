# config.py

from pathlib import Path

# Inzent AI 웹 UI
PORTAL_URL = "https://drive.inzent.com/xedrm/app#/AI-layout/AI-search"

INPUT_SELECTOR = "#AI-search .input-question textarea"
ANSWER_SELECTOR = "#AI-search .answer-area > div"

# Playwright 브라우저 설정
HEADLESS = False  # True로 하면 창 안 뜨게 실행

# Ollama (로컬 LLM) 설정
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2:7b"

# 로그/문서 저장 경로
BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
DOC_DIR = LOG_DIR / "docs"
QNA_LOG_PATH = LOG_DIR / "qna_log.jsonl"
EXTRA_DB_PATH = LOG_DIR / "extra_questions.db"
