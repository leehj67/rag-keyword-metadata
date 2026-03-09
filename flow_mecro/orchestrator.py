# orchestrator.py

from typing import Optional, Dict, Any

from portal_client import PortalClient
from analyzer import analyze
from storage import save_doc_markdown, log_interaction
from extra_db import ExtraQuestionRepository


def process_question(question: str) -> Dict[str, Any]:
    """
    하나의 질문을 전체 파이프라인에 태움:
    1) 웹 UI에 질문 → 포털 답변 수신
    2) 답변 분석 → 부족 시 LLM으로 문서 + 추가 질문 생성
    3) 문서 저장 (있다면)
    4) 추가 질문 리스트를 extra_questions DB에 저장
    5) Q/A 로그 저장
    6) 결과 dict 반환
    """
    portal_client = PortalClient()
    extra_repo = ExtraQuestionRepository()

    print(f"\n=== 질문 ===\n{question}\n")

    # 1) 포털에 질문 던지기
    portal_answer = portal_client.ask(question)
    print(f"[PORTAL] 답변 일부:\n{(portal_answer[:200] + ' ...') if len(portal_answer) > 200 else portal_answer}\n")

    # 2) 답변 분석 / 문서 + 추가 질문 생성 여부 판단
    analysis_result = analyze(question, portal_answer)

    # 3) 문서 저장 (필요한 경우)
    doc_path: Optional[str] = None
    if analysis_result.doc_markdown:
        doc_path = save_doc_markdown(question, analysis_result.doc_markdown)
        print(f"[DOC] 문서를 생성하고 저장했습니다: {doc_path}")
    else:
        print("[DOC] 별도 문서를 생성하지 않았습니다.")

    # 4) 추가 질문 리스트를 extra_questions 큐에 저장
    if analysis_result.extra_questions:
        extra_repo.insert_many(
            original_question=question,
            extra_questions=analysis_result.extra_questions,
        )
    else:
        print("[EXTRA] 추가 학습용 질문 리스트가 없습니다.")

    # 5) 로그 저장
    log_interaction(
        question=question,
        portal_answer=portal_answer,
        has_answer=analysis_result.has_meaningful_answer,
        doc_created=bool(doc_path),
        doc_path=doc_path,
        analysis_summary=analysis_result.analysis_summary,
    )

    # 6) 호출자에게 결과 반환
    return {
        "question": question,
        "portal_answer": portal_answer,
        "has_answer": analysis_result.has_meaningful_answer,
        "doc_created": bool(doc_path),
        "doc_path": doc_path,
        "analysis_summary": analysis_result.analysis_summary,
        "extra_questions": analysis_result.extra_questions or [],
    }
