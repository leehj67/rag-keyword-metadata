# extra_db.py

import sqlite3
from datetime import datetime
from typing import List, Dict, Any

from config import EXTRA_DB_PATH, LOG_DIR
from pathlib import Path


class ExtraQuestionRepository:
    """
    추가 학습용 질문 리스트를 관리하는 SQLite 기반 저장소.
    - 여러 사용자가 동시에 질문을 넣어도 충돌을 줄일 수 있음.
    """

    def __init__(self, db_path: str = str(EXTRA_DB_PATH)):
        self.db_path = db_path
        Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS extra_questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    original_question TEXT NOT NULL,
                    extra_question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    doc_path TEXT
                )
                """
            )
            conn.commit()

    def insert_many(self, original_question: str, extra_questions: List[str]) -> None:
        if not extra_questions:
            return
        now = datetime.now().isoformat(timespec="seconds")
        rows = [
            (now, original_question, q, "PENDING", None) for q in extra_questions
        ]
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.executemany(
                """
                INSERT INTO extra_questions (
                    created_at, original_question, extra_question, status, doc_path
                ) VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        print(f"[EXTRA] 추가 질문 {len(extra_questions)}개를 큐에 저장했습니다.")

    def get_pending(self, limit: int = 20) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, created_at, original_question, extra_question, status, doc_path
                FROM extra_questions
                WHERE status = 'PENDING'
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    def update_status(self, id_: int, status: str, doc_path: str | None = None) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE extra_questions
                SET status = ?, doc_path = ?
                WHERE id = ?
                """,
                (status, doc_path, id_),
            )
            conn.commit()
