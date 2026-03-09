# analyzer.py

from dataclasses import dataclass
from typing import Optional, List
import textwrap
import re

from llm_client import call_llm


@dataclass
class AnalysisResult:
    has_meaningful_answer: bool
    analysis_summary: str
    doc_markdown: Optional[str] = None          # 생성된 문서 내용
    extra_questions: Optional[List[str]] = None  # 추가 학습용 질문 리스트


def is_meaningful_answer(text: str) -> bool:
    """
    포털 답변이 '나름대로 쓸만한 답변'인지 대략 판단.
    너무 짧거나, '찾을 수 없습니다'류 문구가 있으면 False.
    """
    if not text:
        return False

    t = text.strip()
    if len(t) < 20:
        return False

    deny_phrases = [
        "찾을 수 없습니다",
        "정보를 찾을 수 없습니다",
        "검색 결과가 없습니다",
        "해당 내용을 찾지 못했습니다",
        "다시 질문해 주시겠어요",
        "질문을 다시 확인해 주세요",
        "관련 정보를 찾지 못했습니다",
    ]
    return not any(p in t for p in deny_phrases)


def build_doc_for_missing(question: str) -> str:
    """
    포털에서 의미 있는 답변을 못 줬을 때,
    로컬 LLM을 통해 '자료(문서)'를 생성 (마크다운 형식).
    - 주제 제한 없음 (일반형)
    - 문서 안에 '문서 헤더 가이드' 섹션도 포함하게 지시
    """
    prompt = textwrap.dedent(f"""
    당신은 '기술 문서/지식 문서 작성자'입니다.

    아래 질문에 대해 사내 AI 검색으로는 관련 문서를 찾지 못했습니다.
    이 질문에 대해 사용자가 참고할 수 있는 '설명 문서'를 작성해 주세요.

    [질문]
    {question}

    [문서 작성 요구사항]
    1. 문서 제목을 한 줄로 제안해 주세요.
    2. "개념/정의, 필요성/배경, 상세 설명, 예시, 주의사항" 정도로 3~6개 섹션 목차를 만들고,
       각 섹션에 대해 충분한 분량으로 설명을 작성해주세요.
    3. 가능하다면 실제 사용/운영/장애 대응, 실무 상황에서의 예시를 1~2개 포함해 주세요.
    4. 마지막에 '정리 및 추가로 알아볼 것' 섹션을 추가해, 사용자가 더 공부하면 좋은 키워드나
       확인해야 할 포인트를 bullet 형식으로 정리해 주세요.
    5. 전체 문서는 마크다운 형식으로 작성해 주세요.
    6. 문서 상단 부근에 "**문서 헤더 가이드**" 섹션을 추가하여,
       - 이 문서를 RAG/검색 시스템에서 잘 찾기 위해,
       - 어떤 헤더/키워드/태그(예: 시스템명, 제품명, 모듈명, 주요 에러코드, 주요 로그 파일 경로 등)를
         문서 메타데이터에 넣어야 하는지 bullet 형식으로 정리해 주세요.
       (이 헤더 가이드는 문서에 포함되는 설명용 텍스트입니다. 실제 YAML 헤더는 외부 시스템에서 붙일 예정입니다.)

    출력 형식 예시:
    # 문서 제목

    ## 문서 헤더 가이드
    - 키워드: ...
    - 시스템: ...
    - ...

    ## 1. 개념/정의
    ...

    ## 2. 필요성/배경
    ...

    ## 3. 상세 설명
    ...

    ## 4. 예시
    ...

    ## 5. 주의사항
    ...

    ## 6. 정리 및 추가로 알아볼 것
    - ...
    - ...
    """)

    print(f"[LLM] '{question}' 에 대한 설명 문서 생성 중...")
    md = call_llm(prompt)
    print(f"[LLM] '{question}' 문서 생성 완료.")
    return md or ""


def build_extra_questions(question: str) -> List[str]:
    """
    추가 학습을 위해, 해당 질문과 관련된 후속 질문 리스트를 생성.
    - 어떤 주제든 일반적으로 더 파고들 수 있는 질문 5~10개.
    - 각 줄에 질문 하나씩, 번호/불릿 없이 문장만.
    """
    prompt = textwrap.dedent(f"""
    당신은 '추가 학습을 위한 질문 설계자'입니다.

    아래 질문을 더 깊이 이해하고, 사내 지식베이스를 확장하기 위해
    관련된 후속 질문 5~10개를 한국어로 작성해 주세요.

    [질문]
    {question}

    [요구사항]
    - 각 줄마다 하나의 질문만 작성합니다.
    - 번호, 불릿(-, 1., 2.) 등은 쓰지 말고, 순수한 질문 문장만 작성합니다.
    - 서로 다른 관점/상세/환경/예외 케이스 등을 다루도록 다양하게 만들어 주세요.

    출력 예시:
    이런 식으로 출력해야 합니다 (예시는 실제 출력에 포함하지 마세요):

    A 관련 설정 파일 경로와 주요 옵션은 무엇인가요?
    A가 에러를 발생시킬 때 자주 나타나는 로그 패턴은 무엇인가요?
    ...
    """)

    print(f"[LLM] '{question}' 에 대한 추가 학습용 질문 리스트 생성 중...")
    text = call_llm(prompt)
    print(f"[LLM] '{question}' 추가 질문 생성 완료.")

    extra_qs: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 번호/불릿이 들어가 있으면 제거
        line = re.sub(r"^[\-\d\.\)\(]+\s*", "", line).strip()
        if line:
            extra_qs.append(line)

    # 중복 제거
    deduped = []
    seen = set()
    for q in extra_qs:
        if q not in seen:
            seen.add(q)
            deduped.append(q)

    print(f"[LLM] 추가 질문 {len(deduped)}개 추출: {deduped}")
    return deduped


def analyze(question: str, portal_answer: str) -> AnalysisResult:
    """
    - 포털 답변이 유의미하면: has_meaningful_answer=True, doc_markdown=None, extra_questions=None
    - 유의미하지 않으면:
        - doc_markdown = LLM이 생성한 문서
        - extra_questions = LLM이 생성한 추가 질문 리스트
    """
    meaningful = is_meaningful_answer(portal_answer)

    if meaningful:
        summary = "포털에서 의미 있는 답변을 반환했습니다. 별도의 자료/추가 질문 생성은 수행하지 않습니다."
        return AnalysisResult(
            has_meaningful_answer=True,
            analysis_summary=summary,
            doc_markdown=None,
            extra_questions=None,
        )

    # 의미 있는 답변이 없으므로 문서 + 추가 질문 생성
    doc_md = build_doc_for_missing(question)
    extra_qs = build_extra_questions(question)

    summary = (
        "포털에서 의미 있는 답변을 얻지 못해, "
        "로컬 LLM으로 설명 문서와 추가 학습용 질문 리스트를 생성했습니다."
    )

    return AnalysisResult(
        has_meaningful_answer=False,
        analysis_summary=summary,
        doc_markdown=doc_md or None,
        extra_questions=extra_qs or None,
    )
