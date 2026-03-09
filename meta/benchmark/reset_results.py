#!/usr/bin/env python
"""
벤치마크 결과 초기화 스크립트

사용법:
  python -m benchmark.reset_results          # results만 삭제
  python -m benchmark.reset_results --all    # results + data 삭제 (재다운로드 필요)
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCHMARK_DIR / "results"
DATA_DIR = BENCHMARK_DIR / "data"


def main():
    parser = argparse.ArgumentParser(description="벤치마크 결과 초기화")
    parser.add_argument(
        "--all",
        action="store_true",
        help="results + data 모두 삭제 (다음 실행 시 데이터셋 재다운로드)",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="실제 삭제 없이 삭제 대상만 출력",
    )
    args = parser.parse_args()

    to_remove = [RESULTS_DIR]
    if args.all:
        to_remove.append(DATA_DIR)

    for path in to_remove:
        if not path.exists():
            print(f"[건너뜀] 없음: {path}")
            continue
        if args.dry_run:
            print(f"[dry-run] 삭제 예정: {path}")
        else:
            shutil.rmtree(path)
            print(f"[삭제] {path}")

    if not args.dry_run and to_remove:
        print("\n초기화 완료. python -m benchmark.run_benchmark 로 다시 실행하세요.")


if __name__ == "__main__":
    main()
