#!/usr/bin/env python
"""기존 benchmark_summary.json에 검색 성능만 보완"""
from __future__ import annotations

import os
import json

if "TQDM_DISABLE" not in os.environ:
    os.environ["TQDM_DISABLE"] = "1"
from pathlib import Path

from .evaluate import load_beir_dataset, load_repliqa_dataset, _make_model, evaluate_retrieval

RESULTS_DIR = Path(__file__).parent / "results"
SUMMARY_PATH = RESULTS_DIR / "benchmark_summary.json"


def main():
    if not SUMMARY_PATH.exists():
        print(f"[오류] {SUMMARY_PATH} 없음")
        return 1
    with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    kw = data.get("keyword", {})
    ret = data.get("retrieval", {})
    models = ["rake", "yake", "bm25", "ensemble"]
    k_values = [10]
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
        if dataset not in ret:
            ret[dataset] = {}
        for model_name in models:
            for k in k_values:
                run_name = f"{model_name}_k{k}"
                if run_name not in kw.get(dataset, {}):
                    continue
                if run_name in ret.get(dataset, {}):
                    print(f"  {run_name} 건너뜀")
                    continue
                print(f"  {run_name} 계산 중...")
                r = _make_model(model_name, k)
                r.index_corpus(corpus)
                results = r.retrieve(corpus, queries)
                ret[dataset][run_name] = evaluate_retrieval(qrels, results)
                print(f"    NDCG@10: {ret[dataset][run_name]['NDCG'].get('NDCG@10', 0):.4f}")
    data["retrieval"] = ret
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[완료] {SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
