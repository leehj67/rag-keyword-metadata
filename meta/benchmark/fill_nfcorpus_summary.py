#!/usr/bin/env python
"""nfcorpus 메트릭을 계산하여 benchmark_summary.json에 병합"""
import json
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from meta.benchmark.datasets import load_beir_dataset
from meta.benchmark.evaluate import (
    _make_model,
    evaluate_keyword_quality,
    evaluate_retrieval,
    _load_or_create_tokenized,
    _load_or_create_bm25_retrieval,
    _load_or_create_doc_tokens,
    _compute_combined_retrieval,
    _cache_key,
    save_keywords_json,
    BM25_RETRIEVAL_REUSE_MODELS,
)

def main():
    output_dir = Path(__file__).parent / "results"
    cache_dir = output_dir / "cache"
    summary_path = output_dir / "benchmark_summary.json"

    # 기존 summary 로드
    all_results = {"keyword": {}, "retrieval": {}}
    if summary_path.exists():
        with open(summary_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        all_results["keyword"] = loaded.get("keyword", {})
        all_results["retrieval"] = loaded.get("retrieval", {})

    # nfcorpus 로드
    corpus, queries, qrels = load_beir_dataset("nfcorpus")
    if not corpus or not queries or not qrels:
        print("[오류] nfcorpus 로드 실패")
        return 1

    doc_ids = list(corpus.keys())
    ck = _cache_key("nfcorpus", None, None)
    tokenized_corpus, tokenized_queries = _load_or_create_tokenized(
        cache_dir, ck, corpus, queries, doc_ids
    )
    bm25_retrieval_cached = _load_or_create_bm25_retrieval(
        cache_dir, ck, tokenized_corpus, tokenized_queries, doc_ids, top_k=1000
    )
    doc_tokens_cached = _load_or_create_doc_tokens(
        cache_dir, ck, doc_ids, tokenized_corpus
    )

    models = ["rake", "yake", "bm25", "ensemble"]
    k_values = [10]
    retrieval_only = {"rake+bm25", "yake+bm25", "bm25_topk+bm25"}
    fusion_models = ["rake+bm25", "yake+bm25", "bm25_topk+bm25"]

    if "nfcorpus" not in all_results["keyword"]:
        all_results["keyword"]["nfcorpus"] = {}
    if "nfcorpus" not in all_results["retrieval"]:
        all_results["retrieval"]["nfcorpus"] = {}

    for model_name in models + fusion_models:
        k_list = [30] if model_name in fusion_models else k_values
        for k in k_list:
            run_name = model_name if model_name in retrieval_only else f"{model_name}_k{k}"
            if run_name in all_results["keyword"].get("nfcorpus", {}) and run_name in all_results["retrieval"].get("nfcorpus", {}):
                print(f"  [스킵] {run_name} (이미 있음)")
                continue

            r = _make_model(model_name, k)
            if r is None:
                continue

            tokenized_models = {"bm25", "bm25_topk", "rake+bm25topk", "yake+bm25topk", "rake+yake+bm25topk", "bm25_topk+bm25"}
            if model_name in tokenized_models:
                r.index_corpus(corpus, tokenized_corpus=tokenized_corpus)
            else:
                r.index_corpus(corpus)

            doc_keywords = r.get_doc_keywords()
            kw_metrics = evaluate_keyword_quality(
                corpus, queries, qrels, doc_keywords, tokenized_doc_tokens=doc_tokens_cached
            )
            all_results["keyword"]["nfcorpus"][run_name] = kw_metrics

            if model_name in BM25_RETRIEVAL_REUSE_MODELS:
                if model_name == "bm25":
                    results = bm25_retrieval_cached
                else:
                    results = _compute_combined_retrieval(
                        doc_keywords, bm25_retrieval_cached, queries, corpus
                    )
            else:
                results = r.retrieve(corpus, queries)

            ret_metrics = evaluate_retrieval(qrels, results)
            all_results["retrieval"]["nfcorpus"][run_name] = ret_metrics
            print(f"  [완료] {run_name} NDCG@10={ret_metrics['NDCG'].get('NDCG@10', 0):.4f} QKO={kw_metrics['QKO']:.4f}")

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {summary_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
