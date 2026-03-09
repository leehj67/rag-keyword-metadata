#!/usr/bin/env python
"""기존 benchmark_summary.json에 가중 투표·다양성 보정 키워드 품질 데이터 보완

실행 (프로젝트 루트 ai_orchestrator에서):
  python run_fill_weighted_diversity.py
  또는 python -m meta.benchmark.fill_weighted_diversity
"""
from __future__ import annotations

import os
import sys
import json

if "TQDM_DISABLE" not in os.environ:
    os.environ["TQDM_DISABLE"] = "1"
from pathlib import Path

_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from meta.benchmark.evaluate import (
    load_beir_dataset,
    load_repliqa_dataset,
    _make_model,
    evaluate_keyword_quality,
    save_keywords_json,
)

RESULTS_DIR = Path(__file__).parent / "results"
SUMMARY_PATH = RESULTS_DIR / "benchmark_summary.json"

WEIGHTED_MODELS = ["weighted_0_100", "weighted_25_75", "weighted_50_50", "weighted_75_25", "weighted_100_0"]
DIVERSITY_MODELS = ["diversity"]
K_VALUES = [10, 20, 30]


def main():
    if not SUMMARY_PATH.exists():
        print(f"[오류] {SUMMARY_PATH} 없음")
        return 1
    with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    kw = data.get("keyword", {})
    for dataset in list(kw.keys()):
        print(f"[{dataset}] 로드 중...")
        try:
            if dataset == "repliqa":
                corpus, queries, qrels = load_repliqa_dataset()
            else:
                corpus, queries, qrels = load_beir_dataset(dataset)
        except Exception as e:
            print(f"  로드 실패: {e}")
            continue
        if not corpus or not queries or not qrels:
            print(f"  데이터 없음, 건너뜀")
            continue
        for model_name in WEIGHTED_MODELS + DIVERSITY_MODELS:
            for k in K_VALUES:
                run_name = f"{model_name}_k{k}"
                if run_name in kw.get(dataset, {}):
                    print(f"  {run_name} 건너뜀")
                    continue
                print(f"  {run_name} 계산 중...")
                r = _make_model(model_name, k)
                if r is None:
                    print(f"    모델 생성 실패")
                    continue
                r.index_corpus(corpus)
                doc_keywords = r.get_doc_keywords()
                kw_metrics = evaluate_keyword_quality(corpus, queries, qrels, doc_keywords)
                kw[dataset][run_name] = kw_metrics
                save_keywords_json(RESULTS_DIR / f"{dataset}_{run_name}_keywords.json", doc_keywords)
                print(f"    QKO: {kw_metrics['QKO']:.4f}")
    data["keyword"] = kw
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[완료] {SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
