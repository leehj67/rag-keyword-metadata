"""
키워드 품질 평가 + 검색 성능 평가
"""
from __future__ import annotations

import os
import json
import math
import pickle
import re
import shutil
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

# tqdm 진행 표시가 PowerShell stderr로 인해 오류로 인식되는 문제 방지
if "TQDM_DISABLE" not in os.environ:
    os.environ["TQDM_DISABLE"] = "1"

from .retrievers import (
    RAKERetriever, YAKERetriever, BM25Retriever, EnsembleRetriever,
    TopKRetriever, EnsembleRAKEPlusTopK, EnsembleYAKEPlusTopK, EnsembleRAKEYAKETopK,
    WeightedVotingRetriever, DiversityCorrectedRetriever,
    RAKEPlusBM25Retriever, YAKEPlusBM25Retriever, TopKPlusBM25Retriever,
    _kw_overlap_score,
)
from .retrievers_bm25topk import (
    BM25TopKRetriever,
    RAKEPlusBM25TopKRetriever,
    YAKEPlusBM25TopKRetriever,
    EnsembleRAKEYAKEBM25TopKRetriever,
    BM25TopKPlusBM25Retriever,
)
from .datasets import load_beir_dataset, load_repliqa_dataset

# 검증용: topk -> bm25_topk 자동 치환 (KeyBERT 제거)
REPLACE_TOPK_WITH_BM25_TOPK = True

K_VALUES = [1, 3, 5, 10, 100]

# KeyBERT(sentence-transformers) 사용 모델 - 로딩 1~2분/워커, 메모리 ~1GB/워커
# skip_topk_models=True이면 무조건 스킵
TOPK_MODELS = {"topk", "rake+topk", "yake+topk", "rake+yake+topk", "diversity", "topk+bm25", "ensemble3way+bm25"}

# BM25 retrieval 캐시 재사용 가능 모델 (키워드+BM25 결합)
BM25_RETRIEVAL_REUSE_MODELS = {
    "bm25", "rake+bm25", "yake+bm25", "topk+bm25", "ensemble3way+bm25",
    "bm25_topk+bm25", "rake+bm25topk", "yake+bm25topk", "rake+yake+bm25topk",
}
# Two-stage rerank 모델 (BM25 topK → keyword 재정렬)
FUSION_RERANK_MODELS = {"rake+bm25_rerank", "yake+bm25_rerank"}


def _check_rake_yake(models: List[str]) -> None:
    """RAKE/YAKE 실제 추출 동작 확인, 실패 시 안내 출력"""
    if "rake" not in models and "yake" not in models and "ensemble" not in models:
        return
    import sys
    from pathlib import Path
    _meta = Path(__file__).resolve().parent.parent
    if str(_meta) not in sys.path:
        sys.path.insert(0, str(_meta))
    from auto_tagging import (
        extract_candidates_with_rake,
        extract_candidates_with_yake,
        RAKE_AVAILABLE,
        YAKE_AVAILABLE,
    )
    sample = "Machine learning is a subset of artificial intelligence."
    rake_ok = False
    yake_ok = False
    if RAKE_AVAILABLE:
        try:
            r = extract_candidates_with_rake(sample, "en", top_k=5)
            rake_ok = len(r) > 0
        except Exception:
            pass
    if YAKE_AVAILABLE:
        try:
            y = extract_candidates_with_yake(sample, "en", top_k=5)
            yake_ok = len(y) > 0
        except Exception:
            pass
    if not rake_ok and ("rake" in models or "ensemble" in models):
        print("[안내] RAKE 추출 실패. pip install multi-rake 후 재실행하세요.")
    if not yake_ok and ("yake" in models or "ensemble" in models):
        print("[안내] YAKE 추출 실패. pip install yake 후 재실행하세요.")


def _tokenize(text: str) -> Set[str]:
    """영문/숫자 토큰화 (2글자 이상)"""
    text = (text or "").lower()
    tokens = re.findall(r"\b[a-z0-9]+\b", text)
    return set(t for t in tokens if len(t) > 1)


def evaluate_keyword_quality(
    corpus: Dict[str, Dict[str, str]],
    queries: Dict[str, str],
    qrels: Dict[str, Dict[str, int]],
    doc_keywords: Dict[str, List[str]],
    tokenized_doc_tokens: Optional[Dict[str, Set[str]]] = None,
) -> Dict[str, float]:
    """
    키워드 품질 메트릭 계산

    - QKO (Query-Keyword Overlap): 관련 (query, doc) 쌍에서 쿼리 토큰이 키워드에 얼마나 포함되는지
    - Coverage: 문서 고유 토큰 중 키워드가 차지하는 비율
    - Diversity: 키워드 내 중복 없음 비율 (unique_terms / total_terms)
    - AvgKeywords: 문서당 평균 키워드 수
    """
    qko_scores = []
    coverage_scores = []
    diversity_scores = []
    kw_counts = []

    for doc_id, keywords in doc_keywords.items():
        if not keywords:
            continue
        if tokenized_doc_tokens and doc_id in tokenized_doc_tokens:
            doc_tokens = tokenized_doc_tokens[doc_id]
        else:
            doc = corpus.get(doc_id, {})
            text = (doc.get("title") or "") + " " + (doc.get("text") or "")
            doc_tokens = _tokenize(text)
        if not doc_tokens:
            continue

        kw_tokens = set()
        for kw in keywords:
            kw_tokens.update(_tokenize(kw))
        total_kw_terms = sum(len(_tokenize(kw)) for kw in keywords)

        # Coverage: 문서 토큰 중 키워드가 커버하는 비율
        if doc_tokens:
            cov = len(doc_tokens & kw_tokens) / len(doc_tokens)
            coverage_scores.append(cov)

        # Diversity: unique / total (1에 가까울수록 중복 없음)
        if total_kw_terms > 0:
            div = len(kw_tokens) / total_kw_terms
            diversity_scores.append(min(div, 1.0))
        kw_counts.append(len(keywords))

    # QKO: 관련 (qid, doc_id) 쌍에 대해 쿼리-키워드 오버랩
    for qid, qrel in qrels.items():
        qtext = queries.get(qid, "")
        q_tokens = _tokenize(qtext)
        if not q_tokens:
            continue
        for doc_id, rel in qrel.items():
            if rel <= 0:
                continue
            keywords = doc_keywords.get(doc_id, [])
            if not keywords:
                qko_scores.append(0.0)
                continue
            kw_tokens = set()
            for kw in keywords:
                kw_tokens.update(_tokenize(kw))
            overlap = len(q_tokens & kw_tokens) / len(q_tokens)
            qko_scores.append(overlap)

    def avg(lst: List[float]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    return {
        "QKO": avg(qko_scores),
        "Coverage": avg(coverage_scores),
        "Diversity": avg(diversity_scores),
        "AvgKeywords": avg([float(c) for c in kw_counts]),
    }


def _dcg_at_k(relevances: List[int], k: int) -> float:
    relevances = relevances[:k]
    if not relevances:
        return 0.0
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))


def _ndcg_at_k(qrels: Dict[str, int], results: Dict[str, float], k: int) -> float:
    sorted_docs = sorted(results.keys(), key=lambda x: results[x], reverse=True)[:k]
    relevances = [qrels.get(d, 0) for d in sorted_docs]
    dcg = _dcg_at_k(relevances, k)
    ideal = sorted(qrels.values(), reverse=True)[:k]
    idcg = _dcg_at_k(ideal, k)
    return dcg / idcg if idcg > 0 else 0.0


def _recall_at_k(qrels: Dict[str, int], results: Dict[str, float], k: int) -> float:
    rel_docs = set(d for d, r in qrels.items() if r > 0)
    if not rel_docs:
        return 0.0
    retrieved = set(d for d in sorted(results.keys(), key=lambda x: results[x], reverse=True)[:k])
    return len(rel_docs & retrieved) / len(rel_docs)


def _mrr(qrels: Dict[str, int], results: Dict[str, float]) -> float:
    rel_docs = set(d for d, r in qrels.items() if r > 0)
    if not rel_docs:
        return 0.0
    sorted_docs = sorted(results.keys(), key=lambda x: results[x], reverse=True)
    for i, doc in enumerate(sorted_docs):
        if doc in rel_docs:
            return 1.0 / (i + 1)
    return 0.0


def evaluate_retrieval(
    qrels: Dict[str, Dict[str, int]],
    results: Dict[str, Dict[str, float]],
    k_values: List[int] = K_VALUES,
) -> Dict[str, Dict[str, float]]:
    """검색 성능: NDCG@k, Recall@k, MRR"""
    ndcg = {k: [] for k in k_values}
    recall = {k: [] for k in k_values}
    mrr_list = []
    for qid, qrel in qrels.items():
        if qid not in results:
            continue
        res = results[qid]
        for k in k_values:
            ndcg[k].append(_ndcg_at_k(qrel, res, k))
            recall[k].append(_recall_at_k(qrel, res, k))
        mrr_list.append(_mrr(qrel, res))
    def avg(lst): return sum(lst) / len(lst) if lst else 0.0
    return {
        "NDCG": {f"NDCG@{k}": avg(ndcg[k]) for k in k_values},
        "Recall": {f"Recall@{k}": avg(recall[k]) for k in k_values},
        "MRR": avg(mrr_list),
    }


def save_keywords_json(path: Path, doc_keywords: Dict[str, List[str]]) -> None:
    """문서별 키워드 JSON 저장 (샘플, 상위 100개 문서만)"""
    path.parent.mkdir(parents=True, exist_ok=True)
    sample = dict(list(doc_keywords.items())[:100])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sample, f, ensure_ascii=False, indent=2)


def _make_model(name: str, k: int):
    """모델명과 k로 Retriever 인스턴스 생성"""
    kw = {"keyword_top_k": k}
    if name == "rake":
        return RAKERetriever(**kw)
    if name == "yake":
        return YAKERetriever(**kw)
    if name == "bm25":
        return BM25Retriever(**kw)
    if name == "bm25_topk":
        return BM25TopKRetriever(**kw)
    if name == "topk":
        return TopKRetriever(**kw)
    if name == "ensemble":
        return EnsembleRetriever(**kw)
    if name == "rake+topk":
        return EnsembleRAKEPlusTopK(**kw)
    if name == "yake+topk":
        return EnsembleYAKEPlusTopK(**kw)
    if name == "rake+yake+topk":
        return EnsembleRAKEYAKETopK(**kw)
    if name == "rake+bm25topk":
        return RAKEPlusBM25TopKRetriever(**kw)
    if name == "yake+bm25topk":
        return YAKEPlusBM25TopKRetriever(**kw)
    if name == "rake+yake+bm25topk":
        return EnsembleRAKEYAKEBM25TopKRetriever(**kw)
    if name == "bm25_topk+bm25":
        return BM25TopKPlusBM25Retriever(**kw)
    if name.startswith("weighted_"):
        parts = name.replace("weighted_", "").split("_")
        if len(parts) == 2:
            try:
                w1, w2 = int(parts[0]) / 100.0, int(parts[1]) / 100.0
                if 0 <= w1 <= 1 and 0 <= w2 <= 1 and abs(w1 + w2 - 1.0) < 0.01:
                    return WeightedVotingRetriever(**kw, w_rake=w1, w_yake=w2)
            except (ValueError, IndexError):
                pass
    if name == "diversity":
        return DiversityCorrectedRetriever(**kw)
    if name == "rake+bm25":
        return RAKEPlusBM25Retriever(**kw)
    if name == "yake+bm25":
        return YAKEPlusBM25Retriever(**kw)
    if name == "rake+bm25_rerank":
        return RAKERetriever(**kw)
    if name == "yake+bm25_rerank":
        return YAKERetriever(**kw)
    if name == "topk+bm25":
        return TopKPlusBM25Retriever(**kw)
    if name == "ensemble3way+bm25":
        return EnsembleRAKEYAKETopK(**kw)
    return None


def _worker_init() -> None:
    """워커 프로세스 초기화: 모델 로딩 경고 억제, 스레드 폭주 방지"""
    import warnings
    warnings.filterwarnings("ignore")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    try:
        import transformers
        transformers.logging.set_verbosity_error()
    except Exception:
        pass
    try:
        import logging
        for name in ("transformers", "sentence_transformers", "httpx"):
            logging.getLogger(name).setLevel(logging.ERROR)
    except Exception:
        pass


def _compute_combined_retrieval(
    doc_keywords: Dict[str, List[str]],
    bm25_retrieval_cached: Dict[str, Dict[str, float]],
    queries: Dict[str, str],
    corpus: Dict[str, Dict[str, str]],
    fusion_mode: Optional[str] = None,
    alpha: float = 0.1,
    quiet: bool = False,
) -> Dict[str, Dict[str, float]]:
    """
    키워드 점수 + 캐시된 BM25 결합. combined = (1-alpha)*bm25_norm + alpha*kw_norm
    alpha: 키워드 가중치 (기본 0.1). alpha=0.5 시 50:50.
    fusion_mode: "max"(기본), "zscore", "rrf" (환경변수 FUSION_MODE로 지정 가능)
    candidate fusion: BM25 상위 candidate_k 후보에만 kw 계산 (O(Q*D)→O(Q*K), FUSION_CANDIDATE_K)
    """
    if fusion_mode is None:
        fusion_mode = os.environ.get("FUSION_MODE", "max").lower()
    results = {}
    doc_ids = list(corpus.keys())
    diag = os.environ.get("FUSION_DIAG_LOG", "").lower() in ("1", "true", "yes")
    sample_qids = list(queries.keys())[:5] if diag else []
    kw_weight = max(0.0, min(1.0, alpha))
    bm_weight = 1.0 - kw_weight
    # BM25 상위 후보에만 kw 계산 → keyword가 ranking을 흔들 수 있는 구간에 집중, recall 손실 최소화
    candidate_k = int(os.environ.get("FUSION_CANDIDATE_K", "1000"))

    for qid, qtext in queries.items():
        q_tokens = _tokenize(qtext)
        bm25_scores = bm25_retrieval_cached.get(qid, {})
        if not q_tokens:
            results[qid] = {did: 0.0 for did in doc_ids}
            continue

        bm_sorted = sorted(bm25_scores.keys(), key=lambda d: bm25_scores.get(d, 0), reverse=True)
        candidates = bm_sorted[:candidate_k] if candidate_k > 0 else bm_sorted
        kw_scores = {
            did: _kw_overlap_score(q_tokens, doc_keywords.get(did, []))
            for did in candidates
        }

        # 진단: 첫 10개 쿼리에 대해 query_tokens, keyword_tokens, intersection 출력
        if diag and qid in sample_qids and candidates:
            first_did = candidates[0]
            kws = doc_keywords.get(first_did, [])
            kw_set = set()
            for kw in kws:
                kw_set.update(_simple_tokenize(kw))
            inter = len(q_tokens & kw_set)
            print(f"    [kw_diag] qid={qid} query_tokens={len(q_tokens)} keyword_tokens={len(kw_set)} intersection={inter}")

        vals = list(kw_scores.values())
        zero_count = sum(1 for v in vals if v == 0)
        max_kw = max(vals) if vals else 0.0
        top10_avg = sum(sorted(vals, reverse=True)[:10]) / 10.0 if len(vals) >= 10 else (sum(vals) / len(vals) if vals else 0)
        if diag and qid in sample_qids:
            print(f"    [kw_score] qid={qid} zero_count={zero_count}/{len(vals)}={100*zero_count/max(1,len(vals)):.1f}% max={max_kw:.4f} 상위10평균={top10_avg:.4f}")
        if not quiet and zero_count >= len(vals) * 0.9 and len(vals) > 10:
            print(f"    [경고] kw_score 대부분 0 (zero_count={zero_count}/{len(vals)}) → 키워드 매칭 부족, alpha 낮게 유지 권장")

        if fusion_mode == "rrf":
            rrf_k = 60
            bm_rank = {did: i for i, (did, _) in enumerate(
                sorted(bm25_scores.keys(), key=lambda d: bm25_scores.get(d, 0), reverse=True)
            )}
            kw_rank = {did: i for i, (did, _) in enumerate(
                sorted(kw_scores.keys(), key=lambda d: kw_scores.get(d, 0), reverse=True)
            )}
            combined = {}
            for did in bm_sorted:
                rrf_bm = 1.0 / (rrf_k + bm_rank.get(did, len(bm_sorted)) + 1)
                rrf_kw = 1.0 / (rrf_k + kw_rank.get(did, len(bm_sorted)) + 1)
                combined[did] = bm_weight * rrf_bm + kw_weight * rrf_kw
        elif fusion_mode == "zscore":
            bm_vals = [bm25_scores.get(d, 0) for d in candidates]
            kw_vals = [kw_scores.get(d, 0) for d in candidates]
            bm_mean = sum(bm_vals) / len(bm_vals) if bm_vals else 0
            kw_mean = sum(kw_vals) / len(kw_vals) if kw_vals else 0
            bm_std = (sum((v - bm_mean) ** 2 for v in bm_vals) / len(bm_vals)) ** 0.5 if bm_vals else 1.0
            kw_std = (sum((v - kw_mean) ** 2 for v in kw_vals) / len(kw_vals)) ** 0.5 if kw_vals else 1.0
            combined = {}
            for did in bm_sorted:
                z_bm = (bm25_scores.get(did, 0) - bm_mean) / bm_std if bm_std else 0
                z_kw = (kw_scores.get(did, 0) - kw_mean) / kw_std if kw_std else 0
                combined[did] = bm_weight * max(0, z_bm) + kw_weight * max(0, z_kw)
        else:
            max_bm = max(bm25_scores.get(d, 0) for d in candidates) or 1.0
            max_kw = max(kw_scores.values()) or 1.0
            combined = {}
            for did in candidates:
                bm = bm25_scores.get(did, 0) / max_bm if max_bm else 0
                kw = kw_scores.get(did, 0) / max_kw if max_kw else 0
                combined[did] = bm_weight * bm + kw_weight * kw
            for did in bm_sorted:
                if did not in combined:
                    bm = bm25_scores.get(did, 0) / max_bm if max_bm else 0
                    combined[did] = bm_weight * bm

        results[qid] = dict(
            sorted(combined.items(), key=lambda x: x[1], reverse=True)[: 1000]
        )
    return results


def _compute_rerank_retrieval(
    doc_keywords: Dict[str, List[str]],
    bm25_retrieval_cached: Dict[str, Dict[str, float]],
    queries: Dict[str, str],
    corpus: Dict[str, Dict[str, str]],
    top_k: int = 100,
) -> Dict[str, Dict[str, float]]:
    """
    Two-stage: BM25 topK 후보 → 키워드 점수로 재정렬 (0.9*BM25 + 0.1*kw).
    BM25 강점 보존, keyword는 보조 신호.
    """
    results = {}
    for qid, qtext in queries.items():
        q_tokens = _tokenize(qtext)
        bm25_scores = bm25_retrieval_cached.get(qid, {})
        if not bm25_scores:
            results[qid] = {}
            continue
        bm_sorted = sorted(bm25_scores.keys(), key=lambda d: bm25_scores.get(d, 0), reverse=True)
        candidates = bm_sorted[:top_k]
        rest = bm_sorted[top_k:]
        if not q_tokens:
            results[qid] = {did: float(bm25_scores.get(did, 0)) for did in bm_sorted[:1000]}
        else:
            kw_scores = {did: _kw_overlap_score(q_tokens, doc_keywords.get(did, [])) for did in candidates}
            max_kw = max(kw_scores.values()) or 1.0
            max_bm = max(bm25_scores.get(d, 0) for d in candidates) or 1.0
            combined = {}
            for did in candidates:
                bm = bm25_scores.get(did, 0) / max_bm if max_bm else 0
                kw = kw_scores.get(did, 0) / max_kw if max_kw else 0
                combined[did] = 0.9 * bm + 0.1 * kw
            reranked = sorted(candidates, key=lambda d: combined[d], reverse=True)
            rest_scores = {did: bm25_scores.get(did, 0) for did in rest}
            final_order = reranked + rest
            results[qid] = {did: combined.get(did, bm25_scores.get(did, 0)) for did in final_order[:1000]}
    return results


def _simple_tokenize(text: str) -> List[str]:
    """영문/숫자 토큰화 (retrievers와 동일)"""
    text = (text or "").lower()
    tokens = re.findall(r"\b[a-z0-9]+\b", text)
    return [t for t in tokens if len(t) > 1]


def _cache_key(dataset: str, max_docs: Optional[int], max_queries: Optional[int]) -> str:
    return f"{dataset}_{max_docs or 'full'}_{max_queries or 'full'}"


def _ensure_cache_dir(cache_dir: Path, force_reset: bool) -> None:
    if force_reset and cache_dir.exists():
        shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)


def _load_or_create_tokenized(
    cache_dir: Path,
    cache_key: str,
    corpus: Dict[str, Dict[str, str]],
    queries: Dict[str, str],
    doc_ids: List[str],
) -> Tuple[List[List[str]], Dict[str, List[str]]]:
    path = cache_dir / f"{cache_key}_tokenized.pkl"
    if path.exists():
        with open(path, "rb") as f:
            return pickle.load(f)
    tokenized_corpus = [
        _simple_tokenize((corpus[d].get("title") or "") + " " + (corpus[d].get("text") or ""))
        for d in doc_ids
    ]
    tokenized_queries = {qid: _simple_tokenize(queries.get(qid, "")) for qid in queries}
    with open(path, "wb") as f:
        pickle.dump((tokenized_corpus, tokenized_queries), f)
    return tokenized_corpus, tokenized_queries


def _load_or_create_doc_tokens(
    cache_dir: Path,
    cache_key: str,
    doc_ids: List[str],
    tokenized_corpus: List[List[str]],
) -> Dict[str, Set[str]]:
    """doc_id -> set(tokens) 캐시 (evaluate_keyword_quality용)"""
    path = cache_dir / f"{cache_key}_doc_tokens.pkl"
    if path.exists():
        with open(path, "rb") as f:
            return pickle.load(f)
    doc_tokens = {doc_ids[i]: set(tokenized_corpus[i]) for i in range(len(doc_ids))}
    with open(path, "wb") as f:
        pickle.dump(doc_tokens, f)
    return doc_tokens


def _load_or_create_bm25_retrieval(
    cache_dir: Path,
    cache_key: str,
    tokenized_corpus: List[List[str]],
    tokenized_queries: Dict[str, List[str]],
    doc_ids: List[str],
    top_k: int = 1000,
) -> Dict[str, Dict[str, float]]:
    """BM25 retrieval 결과 캐시 (dataset당 1회, k_values 루프에서 재사용)"""
    path = cache_dir / f"{cache_key}_bm25_retrieval.pkl"
    if path.exists():
        with open(path, "rb") as f:
            return pickle.load(f)
    try:
        from rank_bm25 import BM25Okapi
        import numpy as np
    except ImportError:
        return {}
    bm25 = BM25Okapi(tokenized_corpus)
    results = {}
    n = len(doc_ids)
    for qid, q_tokens in tokenized_queries.items():
        if not q_tokens:
            results[qid] = {}
            continue
        scores_arr = bm25.get_scores(q_tokens)
        k = min(top_k, n)
        if k >= n:
            idx = np.argsort(scores_arr)[::-1]
        else:
            idx = np.argpartition(scores_arr, -k)[-k:]
            idx = idx[np.argsort(-scores_arr[idx])]
        results[qid] = {doc_ids[i]: float(scores_arr[i]) for i in idx}
    with open(path, "wb") as f:
        pickle.dump(results, f)
    return results


def _ascii_ratio(text: str) -> float:
    """텍스트 비율 (0~1). 영어 전용 실험 시 참고용"""
    if not text:
        return 1.0
    ascii_count = sum(1 for c in text if ord(c) < 128)
    return ascii_count / len(text)


def _log_ascii_stats(corpus: Dict, queries: Dict, dataset: str) -> None:
    """비영문/비ASCII 비율 로그 (영어 전용 실험 참고)"""
    low_docs = 0
    for doc in corpus.values():
        text = (doc.get("title") or "") + " " + (doc.get("text") or "")
        if text and _ascii_ratio(text) < 0.8:
            low_docs += 1
    low_queries = 0
    for qid, qtext in queries.items():
        if qtext and _ascii_ratio(qtext) < 0.8:
            low_queries += 1
    if low_docs > 0 or low_queries > 0:
        print(f"  [영어전용] 비ASCII 문서: {low_docs}/{len(corpus)}, 쿼리: {low_queries}/{len(queries)}")


def _truncate_data(corpus: Dict, queries: Dict, qrels: Dict, max_docs: Optional[int], max_queries: Optional[int]) -> Tuple[Dict, Dict, Dict]:
    """corpus/queries/qrels를 max_docs, max_queries로 제한 (속도 개선용)"""
    if max_docs and len(corpus) > max_docs:
        corpus = dict(list(corpus.items())[:max_docs])
    qrels = {qid: {did: r for did, r in docs.items() if did in corpus} for qid, docs in qrels.items()}
    qrels = {qid: docs for qid, docs in qrels.items() if docs}
    queries = {qid: queries[qid] for qid in qrels if qid in queries}
    if max_queries and len(qrels) > max_queries:
        qrels = dict(list(qrels.items())[:max_queries])
        queries = {qid: queries[qid] for qid in qrels if qid in queries}
    return corpus, queries, qrels


def _run_single_task(args: Tuple) -> Optional[Dict[str, Any]]:
    """병렬 워커: (dataset, model_name, k, ..., cache_dir, alpha?, progress_dict?) -> 결과 dict"""
    dataset, model_name, k, eval_kw, eval_ret, output_dir, retrieval_only = args[:7]
    max_docs = args[7] if len(args) > 7 else None
    max_queries = args[8] if len(args) > 8 else None
    cache_dir = Path(args[9]) if len(args) > 9 else None
    alpha = args[10] if len(args) > 10 and isinstance(args[10], (int, float)) else 0.1
    progress_dict = args[11] if len(args) > 11 else None
    output_dir = Path(output_dir)
    if model_name in BM25_RETRIEVAL_REUSE_MODELS and model_name != "bm25":
        run_name = f"{model_name}_a{alpha}"
    elif model_name not in retrieval_only:
        run_name = f"{model_name}_k{k}"
    else:
        run_name = model_name
    pid = os.getpid()
    if progress_dict is not None:
        try:
            progress_dict[pid] = f"{dataset} {run_name}"
        except Exception:
            pass
    try:
        if dataset == "repliqa":
            corpus, queries, qrels = load_repliqa_dataset()
        else:
            corpus, queries, qrels = load_beir_dataset(dataset)
        if not corpus or not queries or not qrels:
            return None
        corpus, queries, qrels = _truncate_data(corpus, queries, qrels, max_docs, max_queries)
        doc_ids = list(corpus.keys())
        ck = _cache_key(dataset, max_docs, max_queries) if cache_dir else None

        tokenized_corpus = tokenized_queries = None
        bm25_retrieval_cached = None
        doc_tokens_cached = None
        if cache_dir:
            tokenized_corpus, tokenized_queries = _load_or_create_tokenized(
                cache_dir, ck, corpus, queries, doc_ids
            )
            if eval_ret and (model_name in BM25_RETRIEVAL_REUSE_MODELS or model_name in FUSION_RERANK_MODELS):
                bm25_retrieval_cached = _load_or_create_bm25_retrieval(
                    cache_dir, ck, tokenized_corpus, tokenized_queries, doc_ids, top_k=1000
                )
            if tokenized_corpus is not None:
                doc_tokens_cached = _load_or_create_doc_tokens(
                    cache_dir, ck, doc_ids, tokenized_corpus
                )

        r = _make_model(model_name, k)
        if r is None:
            return None
        tokenized_models = {"bm25", "bm25_topk", "rake+bm25topk", "yake+bm25topk", "rake+yake+bm25topk", "bm25_topk+bm25"}
        if tokenized_corpus is not None and model_name in tokenized_models:
            try:
                r.index_corpus(corpus, tokenized_corpus=tokenized_corpus)
            except TypeError:
                r.index_corpus(corpus)
        else:
            r.index_corpus(corpus)
        kw_metrics = None
        ret_metrics = None
        if eval_kw:
            doc_keywords = r.get_doc_keywords()
            empty_count = sum(1 for v in doc_keywords.values() if not v)
            if empty_count > 0:
                print(f"    [키워드] 빈 리스트 비율: {empty_count}/{len(doc_keywords)} ({100*empty_count/max(1,len(doc_keywords)):.1f}%)")
            tok_doc = doc_tokens_cached if doc_tokens_cached else (
                {doc_ids[i]: set(tokenized_corpus[i]) for i in range(len(doc_ids))} if tokenized_corpus else None
            )
            kw_metrics = evaluate_keyword_quality(corpus, queries, qrels, doc_keywords, tokenized_doc_tokens=tok_doc)
            kw_path = output_dir / f"{dataset}_{run_name}_keywords.json"
            save_keywords_json(kw_path, doc_keywords)
        if eval_ret:
            if bm25_retrieval_cached is not None and model_name in FUSION_RERANK_MODELS:
                results = _compute_rerank_retrieval(
                    r.get_doc_keywords(), bm25_retrieval_cached, queries, corpus, top_k=100
                )
            elif bm25_retrieval_cached is not None and model_name in BM25_RETRIEVAL_REUSE_MODELS:
                if model_name == "bm25":
                    results = bm25_retrieval_cached
                else:
                    results = _compute_combined_retrieval(
                        r.get_doc_keywords(), bm25_retrieval_cached, queries, corpus, alpha=alpha
                    )
            else:
                results = r.retrieve(corpus, queries)
            ret_metrics = evaluate_retrieval(qrels, results)
        return {"dataset": dataset, "run_name": run_name, "kw": kw_metrics, "ret": ret_metrics}
    except Exception as e:
        err_msg = (str(e) or "").strip() or repr(e) or type(e).__name__
        return {"dataset": dataset, "run_name": run_name, "error": err_msg}
    finally:
        if progress_dict is not None:
            try:
                progress_dict.pop(pid, None)
            except Exception:
                pass


def run_benchmark(
    datasets: Optional[List[str]] = None,
    models: Optional[List[str]] = None,
    k_values: Optional[List[int]] = None,
    output_dir: Optional[Path] = None,
    summary_filename: Optional[str] = None,
    use_repliqa: bool = True,
    eval_keyword: bool = True,
    eval_retrieval: bool = True,
    force_reset: bool = False,
    workers: int = 1,
    max_docs: Optional[int] = None,
    max_queries: Optional[int] = None,
    skip_topk_models: bool = True,
    alpha: float = 0.1,
    alpha_sweep: Optional[List[float]] = None,
) -> Dict:
    """
    벤치마크 실행 (키워드 품질 + 검색 성능)

    Args:
        datasets: BEIR 데이터셋
        models: 모델 리스트
        k_values: 키워드 수 (기본 [10,20,30])
        output_dir: 결과 경로
        use_repliqa: RepliQA 포함
        eval_keyword: 키워드 품질 평가
        eval_retrieval: 검색 성능 평가
    """
    if datasets is None:
        datasets = ["scifact", "nfcorpus", "fiqa"]
    if models is None:
        models = ["rake", "yake", "bm25", "ensemble", "topk", "rake+topk", "yake+topk", "rake+yake+topk",
                  "weighted_0_100", "weighted_25_75", "weighted_50_50", "weighted_75_25", "weighted_100_0",
                  "diversity",
                  "rake+bm25", "yake+bm25", "topk+bm25", "ensemble3way+bm25"]
    if k_values is None:
        k_values = [10, 20, 30]
    if output_dir is None:
        output_dir = Path(__file__).parent / "results"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = output_dir / "cache"
    _ensure_cache_dir(cache_dir, force_reset)
    if force_reset:
        print("[초기화] 캐시 제거")
    summary_path = output_dir / (summary_filename or "benchmark_summary.json")
    all_results = {"keyword": {}, "retrieval": {}}
    if force_reset and summary_path.exists():
        summary_path.unlink()
        print("[초기화] 기존 결과 삭제")
    elif not force_reset and summary_path.exists():
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            all_results["keyword"] = loaded.get("keyword", {})
            all_results["retrieval"] = loaded.get("retrieval", {})
            print("[기존 결과 로드] 검색 성능만 보완 모드")
        except Exception:
            pass

    _check_rake_yake(models)

    # topk -> bm25_topk 치환 (KeyBERT 제거)
    if REPLACE_TOPK_WITH_BM25_TOPK:
        models = [
            "bm25_topk" if m == "topk" else
            "rake+bm25topk" if m == "rake+topk" else
            "yake+bm25topk" if m == "yake+topk" else
            "rake+yake+bm25topk" if m == "rake+yake+topk" else
            "bm25_topk+bm25" if m == "topk+bm25" else
            "rake+yake+bm25topk" if m == "ensemble3way+bm25" else
            m
            for m in models
        ]
        models = list(dict.fromkeys(models))

    # KeyBERT 모델이 리스트에 있으면 경고
    keybert_in_list = [m for m in models if m in TOPK_MODELS]
    if keybert_in_list:
        print(f"[경고] KeyBERT 의존 모델 포함: {keybert_in_list} → skip_topk_models=True이면 스킵됨")

    retrieval_only = {
        "bm25",  # k suffix 제거: retrieval은 원문 BM25만, k는 키워드 품질용
        "rake+bm25", "yake+bm25", "topk+bm25", "ensemble3way+bm25",
        "bm25_topk+bm25", "rake+bm25topk", "yake+bm25topk", "rake+yake+bm25topk",
    } | FUSION_RERANK_MODELS
    all_datasets = list(datasets) + (["repliqa"] if use_repliqa else [])

    # 병렬 실행: 미완료 태스크 수집
    if workers > 1:
        tasks = []
        for dataset in all_datasets:
            if dataset == "repliqa":
                try:
                    c, q, r = load_repliqa_dataset()
                    if not c or not q or not r:
                        continue
                except Exception:
                    continue
            else:
                try:
                    c, q, r = load_beir_dataset(dataset)
                    if not c or not q or not r:
                        continue
                except Exception:
                    continue
            if dataset not in all_results["keyword"]:
                all_results["keyword"][dataset] = {}
            if dataset not in all_results["retrieval"]:
                all_results["retrieval"][dataset] = {}
            for model_name in models:
                if _make_model(model_name, 30) is None:
                    continue
                k_list = [30] if model_name in retrieval_only else k_values
                fusion_with_alpha = model_name in BM25_RETRIEVAL_REUSE_MODELS and model_name != "bm25"
                alphas = alpha_sweep if (alpha_sweep and fusion_with_alpha) else [alpha]
                for k in k_list:
                    run_name_kw = f"{model_name}_k{k}" if model_name not in retrieval_only else model_name
                    has_kw = run_name_kw in all_results["keyword"].get(dataset, {})
                    if has_kw and not eval_retrieval:
                        continue
                    for a in alphas:
                        run_name_ret = f"{model_name}_a{a}" if fusion_with_alpha else run_name_kw
                        has_ret = run_name_ret in all_results["retrieval"].get(dataset, {})
                        if has_kw and has_ret:
                            continue
                        tasks.append((dataset, model_name, k, eval_keyword, eval_retrieval, str(output_dir), retrieval_only, max_docs, max_queries, str(cache_dir), a))

        # 병목 완화: KeyBERT 미사용 모델(rake,yake,bm25,ensemble 등)을 먼저 실행 → 진행률이 빨리 올라감
        tasks.sort(key=lambda t: (t[1] in TOPK_MODELS, t[0], t[1], t[2]))

        if tasks:
            import sys
            speed_note = ""
            if max_docs or max_queries:
                speed_note = f" (속도개선: max_docs={max_docs or '∞'}, max_queries={max_queries or '∞'})"
            topk_count = sum(1 for t in tasks if t[1] in TOPK_MODELS)
            print(f"[병렬] {len(tasks)}개 태스크, {workers} 워커{speed_note}", flush=True)
            if topk_count > 0:
                print(f"  [병목] KeyBERT 모델 {topk_count}개 → 워커당 1~2분 로딩, 5% 근처에서 지연 가능. --no-topk로 건너뛰기", flush=True)
            print("  (빠른 모델 우선 실행, 15초마다 진행 표시)", flush=True)
            done_count: List[int] = [0]
            try:
                from multiprocessing import Manager
                _mgr = Manager()
                progress_dict = _mgr.dict()
            except Exception:
                progress_dict = None
            task_tuples = [
                t + (progress_dict,) if progress_dict is not None else t
                for t in tasks
            ]

            def _progress_reporter() -> None:
                while done_count[0] < len(tasks):
                    time.sleep(15)
                    if done_count[0] < len(tasks):
                        pct = 100 * done_count[0] // len(tasks)
                        msg = f"  [{done_count[0]}/{len(tasks)}] {pct}% 진행 중..."
                        if progress_dict is not None:
                            current = list(progress_dict.values())
                            if current:
                                msg += f" | 현재: {', '.join(current[:4])}{'...' if len(current) > 4 else ''}"
                        print(msg, flush=True)

            reporter = threading.Thread(target=_progress_reporter, daemon=True)
            reporter.start()
            with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init) as ex:
                futures = {ex.submit(_run_single_task, tt): tt for tt in task_tuples}
                done = 0
                for fut in as_completed(futures):
                    done += 1
                    done_count[0] = done
                    res = fut.result()
                    ds = res.get("dataset", "?") if res else "?"
                    rn = res.get("run_name", "?") if res else "?"
                    pct = 100 * done // len(tasks)
                    print(f"  [{done}/{len(tasks)}] {pct}% | {ds} {rn}", flush=True)
                    if res is None:
                        continue
                    if "error" in res:
                        err = res["error"]
                        print(f"    [오류] {err}", flush=True)
                        if not err or err in ("Exception", "Exception()"):
                            print(f"    (상세 확인: --workers 1 로 재실행)", flush=True)
                        continue
                    ds, rn = res["dataset"], res["run_name"]
                    if res.get("kw") is not None:
                        all_results["keyword"][ds][rn] = res["kw"]
                    if res.get("ret") is not None:
                        all_results["retrieval"][ds][rn] = res["ret"]
        # 병렬로 모두 처리됨 → 아래 순차 루프 스킵
        datasets = []  # 빈 리스트로 순차 루프 스킵
        use_repliqa = False

    for dataset in datasets:
        print(f"\n{'='*60}")
        print(f"[벤치마크] 데이터셋: {dataset}")
        print("=" * 60)
        try:
            corpus, queries, qrels = load_beir_dataset(dataset)
        except Exception as e:
            print(f"[오류] {dataset} 로드 실패: {e}")
            continue
        if not corpus or not queries or not qrels:
            print(f"[경고] {dataset} 데이터 없음")
            continue
        print(f"  문서: {len(corpus)}, 쿼리: {len(queries)}, qrels: {len(qrels)}")
        _log_ascii_stats(corpus, queries, dataset)

        corpus, queries, qrels = _truncate_data(corpus, queries, qrels, max_docs, max_queries)
        doc_ids = list(corpus.keys())
        ck = _cache_key(dataset, max_docs, max_queries)
        tokenized_corpus, tokenized_queries = _load_or_create_tokenized(
            cache_dir, ck, corpus, queries, doc_ids
        )
        bm25_retrieval_cached = _load_or_create_bm25_retrieval(
            cache_dir, ck, tokenized_corpus, tokenized_queries, doc_ids, top_k=1000
        )
        doc_tokens_cached = _load_or_create_doc_tokens(
            cache_dir, ck, doc_ids, tokenized_corpus
        )

        if dataset not in all_results["keyword"]:
            all_results["keyword"][dataset] = {}
        if dataset not in all_results["retrieval"]:
            all_results["retrieval"][dataset] = {}

        retrieval_only = {
            "rake+bm25", "yake+bm25", "topk+bm25", "ensemble3way+bm25",
            "bm25_topk+bm25", "rake+bm25topk", "yake+bm25topk", "rake+yake+bm25topk",
        } | FUSION_RERANK_MODELS

        for model_name in models:
            if skip_topk_models and model_name in TOPK_MODELS:
                continue
            r = _make_model(model_name, 30)
            if r is None:
                continue
            k_list = [30] if model_name in retrieval_only else k_values
            fusion_with_alpha = model_name in BM25_RETRIEVAL_REUSE_MODELS and model_name != "bm25"
            alphas_to_run = alpha_sweep if (alpha_sweep and fusion_with_alpha) else [alpha]
            for k in k_list:
                run_name_kw = f"{model_name}_k{k}" if model_name not in retrieval_only else model_name
                has_kw = run_name_kw in all_results["keyword"].get(dataset, {})
                if has_kw and not eval_retrieval:
                    continue
                for a in alphas_to_run:
                    run_name_ret = f"{model_name}_a{a}" if fusion_with_alpha else run_name_kw
                    has_ret = run_name_ret in all_results["retrieval"].get(dataset, {})
                    if has_kw and has_ret:
                        continue
                    run_name = run_name_ret
                    print(f"\n  [모델] {run_name}")
                    try:
                        r = _make_model(model_name, k)
                        tokenized_models = {"bm25", "bm25_topk", "rake+bm25topk", "yake+bm25topk", "rake+yake+bm25topk", "bm25_topk+bm25"}
                        if model_name in tokenized_models:
                            try:
                                r.index_corpus(corpus, tokenized_corpus=tokenized_corpus)
                            except TypeError:
                                r.index_corpus(corpus)
                        else:
                            r.index_corpus(corpus)
                        do_kw = eval_keyword and not has_kw and (a == alphas_to_run[0] or not fusion_with_alpha)
                        if do_kw:
                            doc_keywords = r.get_doc_keywords()
                            empty_count = sum(1 for v in doc_keywords.values() if not v)
                            if empty_count > 0:
                                print(f"    [키워드] 빈 리스트 비율: {empty_count}/{len(doc_keywords)} ({100*empty_count/max(1,len(doc_keywords)):.1f}%)")
                            tok_doc = doc_tokens_cached
                            kw_metrics = evaluate_keyword_quality(corpus, queries, qrels, doc_keywords, tokenized_doc_tokens=tok_doc)
                            all_results["keyword"][dataset][run_name_kw] = kw_metrics
                            print(f"    QKO: {kw_metrics['QKO']:.4f} Coverage: {kw_metrics['Coverage']:.4f}")
                            save_keywords_json(output_dir / f"{dataset}_{run_name_kw}_keywords.json", doc_keywords)
                        if eval_retrieval and not has_ret:
                            if bm25_retrieval_cached and model_name in FUSION_RERANK_MODELS:
                                results = _compute_rerank_retrieval(
                                    r.get_doc_keywords(), bm25_retrieval_cached, queries, corpus, top_k=100
                                )
                            elif bm25_retrieval_cached and model_name in BM25_RETRIEVAL_REUSE_MODELS:
                                if model_name == "bm25":
                                    results = bm25_retrieval_cached
                                else:
                                    results = _compute_combined_retrieval(
                                        r.get_doc_keywords(), bm25_retrieval_cached, queries, corpus, alpha=a
                                    )
                            else:
                                results = r.retrieve(corpus, queries)
                            ret_metrics = evaluate_retrieval(qrels, results)
                            all_results["retrieval"][dataset][run_name_ret] = ret_metrics
                            print(f"    NDCG@10: {ret_metrics['NDCG'].get('NDCG@10', 0):.4f} MRR: {ret_metrics['MRR']:.4f}")
                    except Exception as e:
                        print(f"    [오류] {e}")
                        import traceback
                        traceback.print_exc()

    if use_repliqa:
        print(f"\n{'='*60}")
        print("[벤치마크] RepliQA")
        print("=" * 60)
        try:
            corpus, queries, qrels = load_repliqa_dataset()
            if corpus and queries and qrels:
                corpus, queries, qrels = _truncate_data(corpus, queries, qrels, max_docs, max_queries)
                doc_ids = list(corpus.keys())
                ck = _cache_key("repliqa", max_docs, max_queries)
                tokenized_corpus, tokenized_queries = _load_or_create_tokenized(
                    cache_dir, ck, corpus, queries, doc_ids
                )
                bm25_retrieval_cached = _load_or_create_bm25_retrieval(
                    cache_dir, ck, tokenized_corpus, tokenized_queries, doc_ids, top_k=1000
                )
                doc_tokens_cached = _load_or_create_doc_tokens(
                    cache_dir, ck, doc_ids, tokenized_corpus
                )
                if "repliqa" not in all_results["keyword"]:
                    all_results["keyword"]["repliqa"] = {}
                if "repliqa" not in all_results["retrieval"]:
                    all_results["retrieval"]["repliqa"] = {}
                retrieval_only = {
                    "bm25",
                    "rake+bm25", "yake+bm25", "topk+bm25", "ensemble3way+bm25",
                    "bm25_topk+bm25", "rake+bm25topk", "yake+bm25topk", "rake+yake+bm25topk",
                } | FUSION_RERANK_MODELS
                for model_name in models:
                    if skip_topk_models and model_name in TOPK_MODELS:
                        continue
                    r = _make_model(model_name, 30)
                    if r is None:
                        continue
                    k_list = [30] if model_name in retrieval_only else k_values
                    fusion_with_alpha = model_name in BM25_RETRIEVAL_REUSE_MODELS and model_name != "bm25"
                    alphas_to_run = alpha_sweep if (alpha_sweep and fusion_with_alpha) else [alpha]
                    for k in k_list:
                        run_name_kw = f"{model_name}_k{k}" if model_name not in retrieval_only else model_name
                        has_kw = run_name_kw in all_results["keyword"].get("repliqa", {})
                        if has_kw and not eval_retrieval:
                            continue
                        for a in alphas_to_run:
                            run_name_ret = f"{model_name}_a{a}" if fusion_with_alpha else run_name_kw
                            has_ret = run_name_ret in all_results["retrieval"].get("repliqa", {})
                            if has_kw and has_ret:
                                continue
                            run_name = run_name_ret
                            print(f"\n  [모델] {run_name}")
                            try:
                                r = _make_model(model_name, k)
                                tokenized_models = {"bm25", "bm25_topk", "rake+bm25topk", "yake+bm25topk", "rake+yake+bm25topk", "bm25_topk+bm25"}
                                if model_name in tokenized_models:
                                    try:
                                        r.index_corpus(corpus, tokenized_corpus=tokenized_corpus)
                                    except TypeError:
                                        r.index_corpus(corpus)
                                else:
                                    r.index_corpus(corpus)
                                do_kw = eval_keyword and not has_kw and (a == alphas_to_run[0] or not fusion_with_alpha)
                                if do_kw:
                                    doc_keywords = r.get_doc_keywords()
                                    empty_count = sum(1 for v in doc_keywords.values() if not v)
                                    if empty_count > 0:
                                        print(f"    [키워드] 빈 리스트 비율: {empty_count}/{len(doc_keywords)} ({100*empty_count/max(1,len(doc_keywords)):.1f}%)")
                                    kw_metrics = evaluate_keyword_quality(corpus, queries, qrels, doc_keywords, tokenized_doc_tokens=doc_tokens_cached)
                                    all_results["keyword"]["repliqa"][run_name_kw] = kw_metrics
                                    print(f"    QKO: {kw_metrics['QKO']:.4f} Coverage: {kw_metrics['Coverage']:.4f}")
                                    save_keywords_json(output_dir / f"repliqa_{run_name_kw}_keywords.json", doc_keywords)
                                if eval_retrieval and not has_ret:
                                    if bm25_retrieval_cached and model_name in FUSION_RERANK_MODELS:
                                        results = _compute_rerank_retrieval(
                                            r.get_doc_keywords(), bm25_retrieval_cached, queries, corpus, top_k=100
                                        )
                                    elif bm25_retrieval_cached and model_name in BM25_RETRIEVAL_REUSE_MODELS:
                                        if model_name == "bm25":
                                            results = bm25_retrieval_cached
                                        else:
                                            results = _compute_combined_retrieval(
                                                r.get_doc_keywords(), bm25_retrieval_cached, queries, corpus, alpha=a
                                            )
                                    else:
                                        results = r.retrieve(corpus, queries)
                                    ret_metrics = evaluate_retrieval(qrels, results)
                                    all_results["retrieval"]["repliqa"][run_name_ret] = ret_metrics
                                    print(f"    NDCG@10: {ret_metrics['NDCG'].get('NDCG@10', 0):.4f}")
                            except Exception as e:
                                print(f"    [오류] {e}")
        except ImportError:
            print("[경고] RepliQA: pip install datasets")
        except Exception as e:
            print(f"[오류] RepliQA 로드 실패: {e}")

    _summary_path = output_dir / (summary_filename or "benchmark_summary.json")
    with open(_summary_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n[완료] 결과 저장: {_summary_path}")
    return all_results


# Alpha sweep용 fusion 모델 (BM25 + keyword fusion만)
ALPHA_SWEEP_FUSION_MODELS = ["rake+bm25", "yake+bm25", "ensemble"]
ALPHA_SWEEP_VALUES = [0.0, 0.05, 0.1, 0.2, 0.3]


def run_alpha_sweep_fusion(
    datasets: Optional[List[str]] = None,
    output_dir: Optional[Path] = None,
    max_docs: Optional[int] = None,
    max_queries: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    BM25 + keyword fusion 모델에 대해 alpha sweep만 수행.
    기존 단일 모델(bm25, rake, yake, ensemble-only)은 실행하지 않음.
    캐시된 BM25 retrieval과 doc_keywords만 사용하여 fusion 계산만 반복.

    Returns:
        결과 리스트 (dataset, alpha, ndcg@10, mrr, recall@10)
    """
    if datasets is None:
        datasets = ["scifact", "nfcorpus", "arguana"]
    if output_dir is None:
        output_dir = Path(__file__).parent / "results"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir / "cache"

    alpha_list = ALPHA_SWEEP_VALUES
    fusion_models = ALPHA_SWEEP_FUSION_MODELS

    print(f"[Alpha Sweep Fusion] datasets={datasets}, alpha={alpha_list}, models={fusion_models}")
    print("  (캐시 재사용, fusion 계산만 수행)")

    all_rows: List[Dict[str, Any]] = []

    for dataset in datasets:
        try:
            corpus, queries, qrels = load_beir_dataset(dataset)
        except Exception as e:
            print(f"  [오류] {dataset} 로드 실패: {e}")
            continue
        if not corpus or not queries or not qrels:
            continue

        corpus, queries, qrels = _truncate_data(corpus, queries, qrels, max_docs, max_queries)
        doc_ids = list(corpus.keys())
        ck = _cache_key(dataset, max_docs, max_queries)

        tokenized_corpus, tokenized_queries = _load_or_create_tokenized(
            cache_dir, ck, corpus, queries, doc_ids
        )
        bm25_retrieval_cached = _load_or_create_bm25_retrieval(
            cache_dir, ck, tokenized_corpus, tokenized_queries, doc_ids, top_k=1000
        )
        if not bm25_retrieval_cached:
            print(f"  [오류] {dataset} BM25 캐시 생성 실패")
            continue

        # fusion 모델별 doc_keywords 수집 (index_corpus만 실행)
        model_keywords: Dict[str, Dict[str, List[str]]] = {}
        for model_name in fusion_models:
            r = _make_model(model_name, 30)
            if r is None:
                continue
            r.index_corpus(corpus)
            model_keywords[model_name] = r.get_doc_keywords()

        if not model_keywords:
            print(f"  [오류] {dataset} doc_keywords 수집 실패")
            continue

        # alpha별로 fusion 실행 및 평가 (모델별 평균)
        for alpha in alpha_list:
            ndcg_list, mrr_list, recall_list = [], [], []

            for model_name, doc_keywords in model_keywords.items():
                if alpha == 0.0:
                    results = bm25_retrieval_cached
                else:
                    results = _compute_combined_retrieval(
                        doc_keywords, bm25_retrieval_cached, queries, corpus, alpha=alpha, quiet=True
                    )

                ret_metrics = evaluate_retrieval(qrels, results, k_values=[10])
                ndcg_list.append(ret_metrics["NDCG"].get("NDCG@10", 0.0))
                mrr_list.append(ret_metrics["MRR"])
                recall_list.append(ret_metrics["Recall"].get("Recall@10", 0.0))

            n = len(ndcg_list)
            row = {
                "dataset": dataset,
                "alpha": alpha,
                "ndcg@10": sum(ndcg_list) / n if n else 0.0,
                "mrr": sum(mrr_list) / n if n else 0.0,
                "recall@10": sum(recall_list) / n if n else 0.0,
            }
            all_rows.append(row)
            print(f"  {dataset} alpha={alpha:.2f} NDCG@10={row['ndcg@10']:.4f} MRR={row['mrr']:.4f} Recall@10={row['recall@10']:.4f}")

    # CSV 저장
    csv_path = output_dir / "alpha_fusion_results.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        import csv
        w = csv.DictWriter(f, fieldnames=["dataset", "alpha", "ndcg@10", "mrr", "recall@10"])
        w.writeheader()
        w.writerows(all_rows)
    print(f"\n[CSV 저장] {csv_path}")

    # matplotlib 그래프: alpha vs NDCG@10, dataset별 선
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        by_dataset: Dict[str, List[Tuple[float, float]]] = {}
        for row in all_rows:
            ds = row["dataset"]
            if ds not in by_dataset:
                by_dataset[ds] = []
            by_dataset[ds].append((row["alpha"], row["ndcg@10"]))

        plt.figure(figsize=(8, 5))
        for ds, points in sorted(by_dataset.items()):
            alphas = [p[0] for p in points]
            ndcgs = [p[1] for p in points]
            plt.plot(alphas, ndcgs, marker="o", label=ds)

        plt.xlabel("alpha")
        plt.ylabel("NDCG@10")
        plt.title("Alpha vs NDCG@10 (BM25 + Keyword Fusion)")
        plt.legend()
        plt.grid(True, alpha=0.3)
        png_path = output_dir / "alpha_vs_ndcg_fusion.png"
        plt.savefig(png_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"[그래프 저장] {png_path}")
    except ImportError as e:
        print(f"[경고] matplotlib 없음, 그래프 생성 스킵: {e}")

    return all_rows
