# extra_worker.py

from typing import Optional

from analyzer import build_doc_for_missing  # 문서 생성만 재사용
from storage import save_doc_markdown
from extra_db import ExtraQuestionRepository


def make_extra_docs(limit: int = 10) -> None:
    """
    extra_questions DB에 저장된 'PENDING' 상태의 추가 질문들에 대해
    자동으로 문서(자료)를 생성하고 저장하는 배치 함수.

    - 포털을 다시 호출하지 않고, 순수하게 LLM으로 설명 문서만 생성.
    - 성공하면 status = 'DONE', doc_path 업데이트.
    - 실패하면 status = 'FAILED'.
    """
    repo = ExtraQuestionRepository()
    pending = repo.get_pending(limit=limit)

    if not pending:
        print("[EXTRA] 처리할 PENDING 추가 질문이 없습니다.")
        return

    print(f"[EXTRA] PENDING 추가 질문 {len(pending)}개를 처리합니다. (limit={limit})")

    for row in pending:
        id_ = row["id"]
        q = row["extra_question"]
        print(f"\n[EXTRA] ID={id_} 추가 질문 문서 생성: {q}")

        try:
            md = build_doc_for_missing(q)
            if not md:
                print("[EXTRA] 문서 생성 실패 (빈 응답). FAILED로 표시합니다.")
                repo.update_status(id_, status="FAILED", doc_path=None)
                continue

            doc_path = save_doc_markdown(q, md)
            print(f"[EXTRA] 문서를 생성했습니다: {doc_path}")
            repo.update_status(id_, status="DONE", doc_path=doc_path)

        except Exception as e:
            print(f"[EXTRA] 문서 생성 중 예외 발생: {e}")
            repo.update_status(id_, status="FAILED", doc_path=None)
