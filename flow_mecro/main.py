# main.py

import sys
from orchestrator import process_question
from extra_worker import make_extra_docs


def interactive_mode():
    print("=== HJ 오케스트레이터 (웹 UI + LLM 문서/추가질문 생성) ===")
    print("질문을 입력하면 포털에 던지고,")
    print("- 답이 없으면: 문서를 생성 + 추가 학습용 질문 리스트를 저장합니다.")
    print("- 답이 있으면: 로그만 남기고 문서를 만들지 않을 수 있습니다.")
    print("종료하려면 빈 줄에서 Enter 또는 Ctrl+C.\n")

    while True:
        try:
            q = input("질문 > ").strip()
            if not q:
                print("종료합니다.")
                break

            result = process_question(q)

            print("\n=== 처리 결과 요약 ===")
            print(f"- has_answer      : {result['has_answer']}")
            print(f"- doc_created     : {result['doc_created']}")
            print(f"- doc_path        : {result['doc_path']}")
            print(f"- extra_questions : {len(result['extra_questions'])}개 저장됨")
            print(f"- analysis        : {result['analysis_summary']}")
            print("====================================\n")

        except KeyboardInterrupt:
            print("\n사용자 중단. 종료합니다.")
            break


def extra_mode():
    """
    추가 질문 큐에 대해 자동 문서 생성 실행.
    """
    print("=== EXTRA MODE: 추가 질문에 대한 자동 문서 생성 ===")
    make_extra_docs(limit=20)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "extra":
        extra_mode()
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
