# storage.py

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from config import LOG_DIR, DOC_DIR, QNA_LOG_PATH


def ensure_dirs():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DOC_DIR.mkdir(parents=True, exist_ok=True)


def save_doc_markdown(question: str, markdown: str) -> str:
    """
    생성된 문서(markdown)를 파일로 저장하고, 경로를 반환.
    - 파일명: YYYYMMDD_HHMMSS_문서.md (질문 일부 포함)
    - 파일 맨 위에는 YAML 헤더(front matter)를 자동으로 추가
      (원본 질문, 생성 시각, 소스 등)
    """
    ensure_dirs()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    iso_ts = datetime.now().isoformat(timespec="seconds")

    safe_q = "".join(c for c in question[:20] if c.isalnum() or c in (" ", "_", "-"))
    safe_q = safe_q.strip().replace(" ", "_") or "doc"
    filename = f"{ts}_{safe_q}.md"
    path = DOC_DIR / filename

    header = (
        "---\n"
        f"source: auto_missing\n"
        f"original_question: \"{question.replace('\"', '\\\"')}\"\n"
        f"created_at: {iso_ts}\n"
        "tags: []\n"
        "---\n\n"
    )

    path.write_text(header + markdown, encoding="utf-8")
    return str(path)


def append_qna_log(entry: Dict[str, Any]) -> None:
    """
    qna_log.jsonl 파일에 로그 한 줄 추가.
    """
    ensure_dirs()
    with QNA_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_interaction(
    question: str,
    portal_answer: str,
    has_answer: bool,
    doc_created: bool,
    doc_path: Optional[str],
    analysis_summary: str,
) -> None:
    """
    하나의 질문에 대한 전체 결과를 로그에 기록.
    """
    snippet = portal_answer.strip()
    if len(snippet) > 200:
        snippet = snippet[:200] + " ..."

    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "portal_answer_snippet": snippet,
        "has_answer": has_answer,
        "doc_created": doc_created,
        "doc_path": doc_path,
        "analysis_summary": analysis_summary,
    }
    append_qna_log(entry)
    print(f"[LOG] 로그 기록 완료: has_answer={has_answer}, doc_created={doc_created}, doc_path={doc_path}")










