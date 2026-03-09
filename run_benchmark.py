#!/usr/bin/env python
"""벤치마크 실행 (프로젝트 루트에서 실행)

사용법:
  python run_benchmark.py
  python run_benchmark.py --datasets nfcorpus --basic
  python run_benchmark.py --no-repliqa
"""
import os
os.environ["TQDM_DISABLE"] = "1"

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from meta.benchmark.run_benchmark import main

if __name__ == "__main__":
    sys.exit(main())
