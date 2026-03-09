#!/usr/bin/env python
"""가중 투표·다양성 보정 데이터 보완 (프로젝트 루트에서 실행)"""
import sys
from pathlib import Path

# 프로젝트 루트
sys.path.insert(0, str(Path(__file__).resolve().parent))

from meta.benchmark.fill_weighted_diversity import main

if __name__ == "__main__":
    sys.exit(main())
