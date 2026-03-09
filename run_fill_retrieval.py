#!/usr/bin/env python
"""검색 성능 데이터 보완 (프로젝트 루트에서 실행)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from meta.benchmark.fill_retrieval import main

if __name__ == "__main__":
    sys.exit(main())
