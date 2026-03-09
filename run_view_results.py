#!/usr/bin/env python
"""벤치마크 결과 UI 생성 (프로젝트 루트에서 실행)

사용법:
  python run_view_results.py
  python run_view_results.py --no-open
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from meta.benchmark.view_results import main

if __name__ == "__main__":
    sys.exit(main())
