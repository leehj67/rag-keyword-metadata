#!/usr/bin/env python
"""
RAKE/YAKE 키워드 추출 의존성 확인 스크립트

fallback 로그가 나오면 이 스크립트로 원인 확인:
  python -m benchmark.check_keyword_deps
"""
from __future__ import annotations

import sys
from pathlib import Path

# meta 경로 추가
_meta = Path(__file__).resolve().parent.parent
if str(_meta) not in sys.path:
    sys.path.insert(0, str(_meta))


def main():
    print("=== RAKE/YAKE 의존성 확인 ===\n")

    # 1. 패키지 설치 여부
    rake_avail = False
    yake_avail = False
    try:
        from auto_tagging import RAKE_AVAILABLE, YAKE_AVAILABLE
        rake_avail = RAKE_AVAILABLE
        yake_avail = YAKE_AVAILABLE
        print(f"RAKE_AVAILABLE: {rake_avail}")
        print(f"YAKE_AVAILABLE: {yake_avail}")
    except Exception as e:
        print(f"auto_tagging 로드 실패: {e}")
        return

    # 2. 실제 추출 테스트
    sample = "Machine learning is a subset of artificial intelligence. Deep learning uses neural networks."
    print(f"\n샘플: {sample[:50]}...")
    print()

    if rake_avail:
        try:
            from auto_tagging import extract_candidates_with_rake
            r = extract_candidates_with_rake(sample, "en", top_k=5)
            if r:
                print(f"RAKE OK: {[c['phrase'] for c in r[:3]]}")
            else:
                print("RAKE: 빈 결과 (fallback 사용됨) -> pip install multi-rake")
        except Exception as e:
            print(f"RAKE 실패: {e}")
            print("  -> pip install multi-rake")
    else:
        print("RAKE 미설치 -> pip install multi-rake")

    if yake_avail:
        try:
            from auto_tagging import extract_candidates_with_yake
            y = extract_candidates_with_yake(sample, "en", top_k=5)
            if y:
                print(f"YAKE OK: {[c['phrase'] for c in y[:3]]}")
            else:
                print("YAKE: 빈 결과 (fallback 사용됨) -> pip install yake")
        except Exception as e:
            print(f"YAKE 실패: {e}")
            print("  -> pip install yake")
    else:
        print("YAKE 미설치 -> pip install yake")

    print("\n=== 권장 설치 ===")
    print("  pip install multi-rake yake")


if __name__ == "__main__":
    main()
