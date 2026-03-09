"""
BEIR/TREC/RepliQA 호환 검색기: RAKE, YAKE, Top-K, BM25, Ensemble 변형

검색 경로 (RETRIEVAL_MODEL_SPEC.md 참고):
- bm25: (a) 원문 BM25만. k는 TF-IDF top-k(키워드 품질용)에만 영향, retrieval에는 무관.
- rake+bm25, yake+bm25, bm25_topk+bm25: (a) 원문 BM25 + (c) 키워드 overlap 점수 fusion 50:50.
- rake+bm25topk, yake+bm25topk, rake+yake+bm25topk: 동일.
"""
from __future__ import annotations

import math
import os
import re
from typing import Dict, List, Any, Optional, Tuple

# 상대 import for meta package
import sys
from pathlib import Path
_meta = Path(__file__).resolve().parent.parent
if str(_meta) not in sys.path:
    sys.path.insert(0, str(_meta))

from auto_tagging import (
    extract_candidates_with_rake,
    extract_candidates_with_yake,
    tokenize,
    guess_language,
    RAKE_AVAILABLE,
    YAKE_AVAILABLE,
)

try:
    from keybert import KeyBERT
    KEYBERT_AVAILABLE = True
except ImportError:
    KEYBERT_AVAILABLE = False
    KeyBERT = None

def _simple_tokenize(text: str) -> List[str]:
    """영문/숫자 기반 간단 토큰화 (BEIR 데이터는 주로 영문)"""
    text = (text or "").lower()
    tokens = re.findall(r"\b[a-z0-9]+\b", text)
    return [t for t in tokens if len(t) > 1]


class BaseRetriever:
    """검색기 베이스"""

    def __init__(self, top_k: int = 1000):
        self.top_k = top_k

    def index_corpus(self, corpus: Dict[str, Dict[str, str]]) -> None:
        """코퍼스 인덱싱"""
        raise NotImplementedError

    def search(self, query: str, corpus: Dict[str, Dict[str, str]]) -> Dict[str, float]:
        """쿼리로 문서 검색, {doc_id: score} 반환"""
        raise NotImplementedError

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        """문서별 추출 키워드 {doc_id: [keyword, ...]} (키워드 품질 평가용)"""
        raise NotImplementedError

    def retrieve(
        self, corpus: Dict[str, Dict[str, str]], queries: Dict[str, str]
    ) -> Dict[str, Dict[str, float]]:
        """BEIR 형식: {query_id: {doc_id: score}}"""
        self.index_corpus(corpus)
        results = {}
        for qid, qtext in queries.items():
            scores = self.search(qtext, corpus)
            sorted_scores = dict(
                sorted(scores.items(), key=lambda x: x[1], reverse=True)[: self.top_k]
            )
            results[qid] = sorted_scores
        return results


class RAKERetriever(BaseRetriever):
    """RAKE 키워드 기반 검색"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}
        self._used_fallback = False

    def index_corpus(self, corpus: Dict[str, Dict[str, str]]) -> None:
        self._doc_keywords = {}
        fallback_count = 0
        for doc_id, doc in corpus.items():
            text = (doc.get("title") or "") + " " + (doc.get("text") or "")
            if not text.strip():
                self._doc_keywords[doc_id] = []
                continue
            lang = guess_language(text)
            try:
                candidates = extract_candidates_with_rake(
                    text, lang, top_k=self.keyword_top_k
                )
                keywords = [c["phrase"].lower() for c in candidates if c.get("phrase")]
                if not keywords:
                    keywords = list(set(_simple_tokenize(text)))[:100]
                    fallback_count += 1
                self._doc_keywords[doc_id] = keywords
            except Exception:
                self._doc_keywords[doc_id] = list(set(_simple_tokenize(text)))[:100]
                fallback_count += 1
        self._used_fallback = fallback_count > len(corpus) * 0.5
        if self._used_fallback:
            print(f"    [RAKE] fallback 사용 ({fallback_count}/{len(corpus)} 문서, RAKE 미설치 또는 추출 실패)")

    def search(self, query: str, corpus: Dict[str, Dict[str, str]]) -> Dict[str, float]:
        q_tokens = set(_simple_tokenize(query))
        if not q_tokens:
            return {doc_id: 0.0 for doc_id in corpus}
        scores = {}
        for doc_id, keywords in self._doc_keywords.items():
            kw_set = set()
            for kw in keywords:
                kw_set.update(_simple_tokenize(kw))
            overlap = len(q_tokens & kw_set) / len(q_tokens) if q_tokens else 0
            jaccard = (
                len(q_tokens & kw_set) / len(q_tokens | kw_set)
                if (q_tokens | kw_set)
                else 0
            )
            scores[doc_id] = 0.7 * overlap + 0.3 * jaccard
        return scores

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


# YAKE는 긴 문서에서 O(n²) 경향 → scifact 등에서 멈춘 것처럼 보임. truncate로 완화
MAX_TEXT_LEN_FOR_YAKE = 4000


def _extract_yake_safe(text: str, lang: str, top_k: int) -> List[Dict[str, Any]]:
    """긴 텍스트 truncate 후 YAKE 추출 (O(n²) 방지)"""
    if not text or not YAKE_AVAILABLE:
        return []
    text_trunc = text[:MAX_TEXT_LEN_FOR_YAKE] if len(text) > MAX_TEXT_LEN_FOR_YAKE else text
    return extract_candidates_with_yake(text_trunc, lang, top_k=top_k)


class YAKERetriever(BaseRetriever):
    """YAKE 키워드 기반 검색"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}

    def index_corpus(self, corpus: Dict[str, Dict[str, str]]) -> None:
        self._doc_keywords = {}
        fallback_count = 0
        for doc_id, doc in corpus.items():
            text = (doc.get("title") or "") + " " + (doc.get("text") or "")
            if not text.strip():
                self._doc_keywords[doc_id] = []
                continue
            lang = guess_language(text)
            try:
                candidates = _extract_yake_safe(text, lang, self.keyword_top_k)
                keywords = [c["phrase"].lower() for c in candidates if c.get("phrase")]
                if not keywords:
                    keywords = list(set(_simple_tokenize(text)))[:100]
                    fallback_count += 1
                self._doc_keywords[doc_id] = keywords
            except Exception:
                self._doc_keywords[doc_id] = list(set(_simple_tokenize(text)))[:100]
                fallback_count += 1
        if fallback_count > len(corpus) * 0.5:
            print(f"    [YAKE] fallback 사용 ({fallback_count}/{len(corpus)} 문서, YAKE 미설치 또는 추출 실패)")

    def search(self, query: str, corpus: Dict[str, Dict[str, str]]) -> Dict[str, float]:
        q_tokens = set(_simple_tokenize(query))
        if not q_tokens:
            return {doc_id: 0.0 for doc_id in corpus}
        scores = {}
        for doc_id, keywords in self._doc_keywords.items():
            kw_set = set()
            for kw in keywords:
                kw_set.update(_simple_tokenize(kw))
            overlap = len(q_tokens & kw_set) / len(q_tokens) if q_tokens else 0
            jaccard = (
                len(q_tokens & kw_set) / len(q_tokens | kw_set)
                if (q_tokens | kw_set)
                else 0
            )
            scores[doc_id] = 0.7 * overlap + 0.3 * jaccard
        return scores

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


class BM25Retriever(BaseRetriever):
    """원문 BM25 검색 (rank_bm25). 인덱스=원문(title+text) 토큰화. keyword_top_k는 TF-IDF 상위 k(키워드 품질 메트릭용)에만 사용, retrieval에는 무관."""

    def __init__(self, top_k: int = 1000, k1: float = 1.5, b: float = 0.75, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.k1 = k1
        self.b = b
        self.keyword_top_k = keyword_top_k
        self._bm25 = None
        self._doc_ids: List[str] = []
        self._doc_keywords: Dict[str, List[str]] = {}

    def index_corpus(self, corpus: Dict[str, Dict[str, str]], tokenized_corpus: Optional[List[List[str]]] = None) -> None:
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            raise ImportError("rank_bm25 필요: pip install rank-bm25")
        self._doc_ids = list(corpus.keys())
        if tokenized_corpus is not None:
            tokenized = tokenized_corpus
        else:
            tokenized = []
            for doc_id in self._doc_ids:
                doc = corpus[doc_id]
                text = (doc.get("title") or "") + " " + (doc.get("text") or "")
                tokenized.append(_simple_tokenize(text))
        self._bm25 = BM25Okapi(tokenized)
        # TF-IDF 상위 term을 키워드로 사용 (키워드 품질 평가용)
        import math
        self._doc_keywords = {}
        n_docs = len(tokenized)
        doc_freq: Dict[str, int] = {}
        for toks in tokenized:
            for t in set(toks):
                doc_freq[t] = doc_freq.get(t, 0) + 1
        for i, doc_id in enumerate(self._doc_ids):
            toks = tokenized[i]
            if not toks:
                self._doc_keywords[doc_id] = []
                continue
            tf: Dict[str, float] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            scores = []
            for t, cnt in tf.items():
                idf = math.log((n_docs + 1) / (doc_freq.get(t, 0) + 1)) + 1
                scores.append((t, cnt * idf))
            scores.sort(key=lambda x: x[1], reverse=True)
            self._doc_keywords[doc_id] = [t for t, _ in scores[: self.keyword_top_k]]

    def search(self, query: str, corpus: Dict[str, Dict[str, str]]) -> Dict[str, float]:
        if self._bm25 is None:
            return {doc_id: 0.0 for doc_id in corpus}
        import numpy as np
        q_tokens = _simple_tokenize(query)
        scores_arr = self._bm25.get_scores(q_tokens)
        n = len(self._doc_ids)
        k = min(self.top_k, n)
        if k >= n:
            idx = np.argsort(scores_arr)[::-1]
        else:
            idx = np.argpartition(scores_arr, -k)[-k:]
            idx = idx[np.argsort(-scores_arr[idx])]
        return {self._doc_ids[i]: float(scores_arr[i]) for i in idx}

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


class EnsembleRetriever(BaseRetriever):
    """RAKE + YAKE + BM25 앙상블 검색"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}
        self._bm25_retriever: Optional[BM25Retriever] = None

    def index_corpus(self, corpus: Dict[str, Dict[str, str]]) -> None:
        self._doc_keywords = {}
        for doc_id, doc in corpus.items():
            text = (doc.get("title") or "") + " " + (doc.get("text") or "")
            if not text.strip():
                self._doc_keywords[doc_id] = []
                continue
            lang = guess_language(text)
            all_keywords = []
            if RAKE_AVAILABLE:
                try:
                    rake_cands = extract_candidates_with_rake(
                        text, lang, top_k=self.keyword_top_k
                    )
                    all_keywords.extend(
                        c["phrase"].lower() for c in rake_cands if c.get("phrase")
                    )
                except Exception:
                    pass
            if YAKE_AVAILABLE:
                try:
                    yake_cands = _extract_yake_safe(text, lang, self.keyword_top_k)
                    all_keywords.extend(
                        c["phrase"].lower() for c in yake_cands if c.get("phrase")
                    )
                except Exception:
                    pass
            seen = set()
            unique = []
            for kw in all_keywords:
                k = kw.strip()
                if k and k not in seen:
                    seen.add(k)
                    unique.append(k)
            if not unique:
                unique = list(set(_simple_tokenize(text)))[:100]
            self._doc_keywords[doc_id] = unique
        self._bm25_retriever = BM25Retriever(top_k=self.top_k)
        self._bm25_retriever.index_corpus(corpus)

    def search(self, query: str, corpus: Dict[str, Dict[str, str]]) -> Dict[str, float]:
        # 후보군 제한: kw sparsity + O(Q*D) 비용. BM25 topK에만 kw(overlap+jaccard) 계산.
        q_tokens = set(_simple_tokenize(query))
        if not q_tokens:
            return {doc_id: 0.0 for doc_id in corpus}
        bm25_scores = self._bm25_retriever.search(query, corpus)
        if not bm25_scores:
            return {doc_id: 0.0 for doc_id in corpus}
        candidate_k = int(os.environ.get("FUSION_CANDIDATE_K", "1000"))
        bm_sorted = sorted(bm25_scores.keys(), key=lambda d: bm25_scores[d], reverse=True)
        candidates = bm_sorted[:candidate_k] if candidate_k > 0 else bm_sorted
        kw_scores = {}
        for doc_id in candidates:
            keywords = self._doc_keywords.get(doc_id, [])
            kw_set = set()
            for kw in keywords:
                kw_set.update(_simple_tokenize(kw))
            overlap = len(q_tokens & kw_set) / len(q_tokens) if q_tokens else 0
            jaccard = (
                len(q_tokens & kw_set) / len(q_tokens | kw_set)
                if (q_tokens | kw_set)
                else 0
            )
            kw_scores[doc_id] = 0.7 * overlap + 0.3 * jaccard
        return _fusion_combined_scores(
            bm25_scores, kw_scores, corpus.keys(), candidate_k, 0.5, 0.5
        )

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


def _kw_overlap_score(q_tokens: set, keywords: List[str]) -> float:
    kw_set = set()
    for kw in keywords:
        kw_set.update(_simple_tokenize(kw))
    if not q_tokens:
        return 0.0
    overlap = len(q_tokens & kw_set) / len(q_tokens)
    jaccard = len(q_tokens & kw_set) / len(q_tokens | kw_set) if (q_tokens | kw_set) else 0
    return 0.7 * overlap + 0.3 * jaccard


def _fusion_combined_scores(
    bm25_scores: Dict[str, float],
    kw_scores: Dict[str, float],
    corpus_keys: Any,
    candidate_k: int,
    bm_weight: float,
    kw_weight: float,
) -> Dict[str, float]:
    """
    후보군 기반 fusion: kw sparsity로 전 코퍼스 계산 시 ranking에 반영 못함 + O(Q*D) 비용.
    BM25 topK 후보에만 kw 계산 후 max-norm fusion, 나머지는 BM25만 유지.
    """
    bm_sorted = sorted(bm25_scores.keys(), key=lambda d: bm25_scores.get(d, 0), reverse=True)
    candidates = bm_sorted[:candidate_k] if candidate_k > 0 else bm_sorted
    max_bm = max((bm25_scores.get(d, 0) for d in candidates), default=0) or 1.0
    max_kw = max((kw_scores.get(d, 0) for d in candidates), default=0) or 1.0
    combined = {}
    for did in candidates:
        bm = bm25_scores.get(did, 0) / max_bm if max_bm else 0
        kw = kw_scores.get(did, 0) / max_kw if max_kw else 0
        combined[did] = bm_weight * bm + kw_weight * kw
    for did in bm_sorted:
        if did not in combined:
            bm = bm25_scores.get(did, 0) / max_bm if max_bm else 0
            combined[did] = bm_weight * bm
    for did in corpus_keys:
        if did not in combined:
            combined[did] = 0.0
    return combined


def _jaccard_tokens(a: str, b: str) -> float:
    sa = set(_simple_tokenize(a))
    sb = set(_simple_tokenize(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _mmr_select(candidates: List[Tuple[str, float]], k: int, lambda_: float = 0.7) -> List[str]:
    if len(candidates) <= k:
        return [c[0] for c in candidates]
    selected, remaining = [], list(candidates)
    for _ in range(k):
        best_score, best_idx = -1e9, 0
        for i, (phrase, rel) in enumerate(remaining):
            max_sim = max((_jaccard_tokens(phrase, sel) for sel in selected), default=0.0)
            mmr = lambda_ * rel - (1 - lambda_) * max_sim
            if mmr > best_score:
                best_score, best_idx = mmr, i
        selected.append(remaining.pop(best_idx)[0])
    return selected


class _KeywordPlusBM25Mixin:
    """점수 fusion: 0.5*(키워드 overlap) + 0.5*(원문 BM25). BM25는 원문만 사용, 키워드는 overlap 점수에만 사용."""

    def search(self, query: str, corpus: Dict[str, Dict[str, str]]) -> Dict[str, float]:
        # 후보군 제한: kw sparsity로 전 코퍼스 계산 시 ranking에 반영 못함. BM25 topK에만 kw 계산.
        q_tokens = set(_simple_tokenize(query))
        if not q_tokens:
            return {doc_id: 0.0 for doc_id in corpus}
        bm25_scores = self._bm25_retriever.search(query, corpus)
        if not bm25_scores:
            return {doc_id: 0.0 for doc_id in corpus}
        candidate_k = int(os.environ.get("FUSION_CANDIDATE_K", "1000"))
        bm_sorted = sorted(bm25_scores.keys(), key=lambda d: bm25_scores[d], reverse=True)
        candidates = bm_sorted[:candidate_k] if candidate_k > 0 else bm_sorted
        kw_scores = {
            did: _kw_overlap_score(q_tokens, self._doc_keywords.get(did, []))
            for did in candidates
        }
        return _fusion_combined_scores(
            bm25_scores, kw_scores, corpus.keys(), candidate_k, 0.5, 0.5
        )


class RAKEPlusBM25Retriever(_KeywordPlusBM25Mixin, BaseRetriever):
    """RAKE 키워드 + BM25 검색"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}
        self._bm25_retriever: Optional[BM25Retriever] = None

    def index_corpus(self, corpus: Dict[str, Dict[str, str]]) -> None:
        r = RAKERetriever(keyword_top_k=self.keyword_top_k)
        r.index_corpus(corpus)
        self._doc_keywords = r.get_doc_keywords()
        self._bm25_retriever = BM25Retriever(top_k=self.top_k)
        self._bm25_retriever.index_corpus(corpus)

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


class YAKEPlusBM25Retriever(BaseRetriever, _KeywordPlusBM25Mixin):
    """점수 fusion: YAKE 키워드 overlap + 원문 BM25 50:50"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}
        self._bm25_retriever: Optional[BM25Retriever] = None

    def index_corpus(self, corpus: Dict[str, Dict[str, str]]) -> None:
        r = YAKERetriever(keyword_top_k=self.keyword_top_k)
        r.index_corpus(corpus)
        self._doc_keywords = r.get_doc_keywords()
        self._bm25_retriever = BM25Retriever(top_k=self.top_k)
        self._bm25_retriever.index_corpus(corpus)

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


class TopKPlusBM25Retriever(_KeywordPlusBM25Mixin, BaseRetriever):
    """점수 fusion: Top-K 키워드 overlap + 원문 BM25 50:50"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}
        self._bm25_retriever: Optional[BM25Retriever] = None

    def index_corpus(self, corpus: Dict[str, Dict[str, str]]) -> None:
        r = TopKRetriever(keyword_top_k=self.keyword_top_k)
        r.index_corpus(corpus)
        self._doc_keywords = r.get_doc_keywords()
        self._bm25_retriever = BM25Retriever(top_k=self.top_k)
        self._bm25_retriever.index_corpus(corpus)

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


class TopKRetriever(BaseRetriever):
    """KeyBERT 기반 Top-K 키워드 추출"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}
        self._kw_model = None

    def index_corpus(self, corpus: Dict[str, Dict[str, str]]) -> None:
        self._doc_keywords = {}
        if not KEYBERT_AVAILABLE:
            for doc_id, doc in corpus.items():
                text = (doc.get("title") or "") + " " + (doc.get("text") or "")
                self._doc_keywords[doc_id] = list(set(_simple_tokenize(text)))[: self.keyword_top_k]
            return
        if self._kw_model is None:
            self._kw_model = KeyBERT()
        for doc_id, doc in corpus.items():
            text = (doc.get("title") or "") + " " + (doc.get("text") or "")
            if not text.strip():
                self._doc_keywords[doc_id] = []
                continue
            try:
                kws = self._kw_model.extract_keywords(text, keyphrase_ngram_range=(1, 3), top_n=self.keyword_top_k)
                self._doc_keywords[doc_id] = [kw for kw, _ in kws if kw]
            except Exception:
                self._doc_keywords[doc_id] = list(set(_simple_tokenize(text)))[: self.keyword_top_k]

    def search(self, query: str, corpus: Dict[str, Dict[str, str]]) -> Dict[str, float]:
        q_tokens = set(_simple_tokenize(query))
        if not q_tokens:
            return {doc_id: 0.0 for doc_id in corpus}
        return {did: _kw_overlap_score(q_tokens, kws) for did, kws in self._doc_keywords.items()}

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


class EnsembleRAKEPlusTopK(BaseRetriever):
    """RAKE + Top-K 앙상블"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}
        self._bm25_retriever: Optional[BM25Retriever] = None

    def index_corpus(self, corpus: Dict[str, Dict[str, str]]) -> None:
        r1, r2 = RAKERetriever(keyword_top_k=self.keyword_top_k), TopKRetriever(keyword_top_k=self.keyword_top_k)
        r1.index_corpus(corpus)
        r2.index_corpus(corpus)
        kw1, kw2 = r1.get_doc_keywords(), r2.get_doc_keywords()
        self._doc_keywords = {}
        for doc_id in corpus:
            seen, unique = set(), []
            for kw in kw1.get(doc_id, []) + kw2.get(doc_id, []):
                k = kw.strip().lower()
                if k and k not in seen:
                    seen.add(k)
                    unique.append(k)
            self._doc_keywords[doc_id] = unique[: self.keyword_top_k * 2]
        self._bm25_retriever = BM25Retriever(top_k=self.top_k)
        self._bm25_retriever.index_corpus(corpus)

    def search(self, query: str, corpus: Dict[str, Dict[str, str]]) -> Dict[str, float]:
        q_tokens = set(_simple_tokenize(query))
        kw_scores = {did: _kw_overlap_score(q_tokens, kws) for did, kws in self._doc_keywords.items()}
        bm25_scores = self._bm25_retriever.search(query, corpus)
        max_bm = max(bm25_scores.values()) or 1.0
        max_kw = max(kw_scores.values()) or 1.0
        return {did: 0.5 * (bm25_scores.get(did, 0) / max_bm) + 0.5 * (kw_scores.get(did, 0) / max_kw) for did in corpus}

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


class EnsembleYAKEPlusTopK(BaseRetriever):
    """YAKE + Top-K 앙상블"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}
        self._bm25_retriever: Optional[BM25Retriever] = None

    def index_corpus(self, corpus: Dict[str, Dict[str, str]]) -> None:
        r1, r2 = YAKERetriever(keyword_top_k=self.keyword_top_k), TopKRetriever(keyword_top_k=self.keyword_top_k)
        r1.index_corpus(corpus)
        r2.index_corpus(corpus)
        kw1, kw2 = r1.get_doc_keywords(), r2.get_doc_keywords()
        self._doc_keywords = {}
        for doc_id in corpus:
            seen, unique = set(), []
            for kw in kw1.get(doc_id, []) + kw2.get(doc_id, []):
                k = kw.strip().lower()
                if k and k not in seen:
                    seen.add(k)
                    unique.append(k)
            self._doc_keywords[doc_id] = unique[: self.keyword_top_k * 2]
        self._bm25_retriever = BM25Retriever(top_k=self.top_k)
        self._bm25_retriever.index_corpus(corpus)

    def search(self, query: str, corpus: Dict[str, Dict[str, str]]) -> Dict[str, float]:
        q_tokens = set(_simple_tokenize(query))
        kw_scores = {did: _kw_overlap_score(q_tokens, kws) for did, kws in self._doc_keywords.items()}
        bm25_scores = self._bm25_retriever.search(query, corpus)
        max_bm = max(bm25_scores.values()) or 1.0
        max_kw = max(kw_scores.values()) or 1.0
        return {did: 0.5 * (bm25_scores.get(did, 0) / max_bm) + 0.5 * (kw_scores.get(did, 0) / max_kw) for did in corpus}

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


class EnsembleRAKEYAKETopK(BaseRetriever):
    """RAKE + YAKE + Top-K 3-way 앙상블"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}
        self._bm25_retriever: Optional[BM25Retriever] = None

    def index_corpus(self, corpus: Dict[str, Dict[str, str]]) -> None:
        r1, r2, r3 = RAKERetriever(keyword_top_k=self.keyword_top_k), YAKERetriever(keyword_top_k=self.keyword_top_k), TopKRetriever(keyword_top_k=self.keyword_top_k)
        r1.index_corpus(corpus)
        r2.index_corpus(corpus)
        r3.index_corpus(corpus)
        kw1, kw2, kw3 = r1.get_doc_keywords(), r2.get_doc_keywords(), r3.get_doc_keywords()
        self._doc_keywords = {}
        for doc_id in corpus:
            seen, unique = set(), []
            for kw in kw1.get(doc_id, []) + kw2.get(doc_id, []) + kw3.get(doc_id, []):
                k = kw.strip().lower()
                if k and k not in seen:
                    seen.add(k)
                    unique.append(k)
            self._doc_keywords[doc_id] = unique[: self.keyword_top_k * 3]
        self._bm25_retriever = BM25Retriever(top_k=self.top_k)
        self._bm25_retriever.index_corpus(corpus)

    def search(self, query: str, corpus: Dict[str, Dict[str, str]]) -> Dict[str, float]:
        q_tokens = set(_simple_tokenize(query))
        kw_scores = {did: _kw_overlap_score(q_tokens, kws) for did, kws in self._doc_keywords.items()}
        bm25_scores = self._bm25_retriever.search(query, corpus)
        max_bm = max(bm25_scores.values()) or 1.0
        max_kw = max(kw_scores.values()) or 1.0
        return {did: 0.5 * (bm25_scores.get(did, 0) / max_bm) + 0.5 * (kw_scores.get(did, 0) / max_kw) for did in corpus}

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


class WeightedVotingRetriever(BaseRetriever):
    """가중 투표: w1*RAKE + w2*YAKE"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30, w_rake: float = 0.5, w_yake: float = 0.5):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self.w_rake = w_rake
        self.w_yake = w_yake
        self._doc_keywords: Dict[str, List[str]] = {}
        self._bm25_retriever: Optional[BM25Retriever] = None

    def index_corpus(self, corpus: Dict[str, Dict[str, str]]) -> None:
        r_rake = RAKERetriever(keyword_top_k=self.keyword_top_k * 2)
        r_yake = YAKERetriever(keyword_top_k=self.keyword_top_k * 2)
        r_rake.index_corpus(corpus)
        r_yake.index_corpus(corpus)
        kw_rake, kw_yake = r_rake.get_doc_keywords(), r_yake.get_doc_keywords()
        self._doc_keywords = {}
        for doc_id in corpus:
            scores = {}
            for i, kw in enumerate(kw_rake.get(doc_id, [])):
                k = kw.strip().lower()
                if k:
                    scores[k] = scores.get(k, 0) + self.w_rake * (1.0 - i / (self.keyword_top_k * 2 + 1))
            for i, kw in enumerate(kw_yake.get(doc_id, [])):
                k = kw.strip().lower()
                if k:
                    scores[k] = scores.get(k, 0) + self.w_yake * (1.0 - i / (self.keyword_top_k * 2 + 1))
            sorted_kw = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            self._doc_keywords[doc_id] = [k for k, _ in sorted_kw[: self.keyword_top_k]]
        self._bm25_retriever = BM25Retriever(top_k=self.top_k)
        self._bm25_retriever.index_corpus(corpus)

    def search(self, query: str, corpus: Dict[str, Dict[str, str]]) -> Dict[str, float]:
        q_tokens = set(_simple_tokenize(query))
        kw_scores = {did: _kw_overlap_score(q_tokens, kws) for did, kws in self._doc_keywords.items()}
        bm25_scores = self._bm25_retriever.search(query, corpus)
        max_bm = max(bm25_scores.values()) or 1.0
        max_kw = max(kw_scores.values()) or 1.0
        return {did: 0.5 * (bm25_scores.get(did, 0) / max_bm) + 0.5 * (kw_scores.get(did, 0) / max_kw) for did in corpus}

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


class DiversityCorrectedRetriever(BaseRetriever):
    """MMR 기반 다양성 보정 앙상블"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30, mmr_lambda: float = 0.7):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self.mmr_lambda = mmr_lambda
        self._doc_keywords: Dict[str, List[str]] = {}
        self._bm25_retriever: Optional[BM25Retriever] = None

    def index_corpus(self, corpus: Dict[str, Dict[str, str]]) -> None:
        r1, r2, r3 = RAKERetriever(keyword_top_k=self.keyword_top_k * 2), YAKERetriever(keyword_top_k=self.keyword_top_k * 2), TopKRetriever(keyword_top_k=self.keyword_top_k * 2)
        r1.index_corpus(corpus)
        r2.index_corpus(corpus)
        r3.index_corpus(corpus)
        kw1, kw2, kw3 = r1.get_doc_keywords(), r2.get_doc_keywords(), r3.get_doc_keywords()
        self._doc_keywords = {}
        for doc_id in corpus:
            scores = {}
            for i, kw in enumerate(kw1.get(doc_id, []) + kw2.get(doc_id, []) + kw3.get(doc_id, [])):
                k = kw.strip().lower()
                if k:
                    scores[k] = scores.get(k, 0) + (1.0 - i / (self.keyword_top_k * 6 + 1))
            max_s = max(scores.values()) if scores else 1.0
            candidates = [(k, s / max_s) for k, s in scores.items()]
            self._doc_keywords[doc_id] = _mmr_select(candidates, min(self.keyword_top_k, len(candidates)), self.mmr_lambda)
        self._bm25_retriever = BM25Retriever(top_k=self.top_k)
        self._bm25_retriever.index_corpus(corpus)

    def search(self, query: str, corpus: Dict[str, Dict[str, str]]) -> Dict[str, float]:
        q_tokens = set(_simple_tokenize(query))
        kw_scores = {did: _kw_overlap_score(q_tokens, kws) for did, kws in self._doc_keywords.items()}
        bm25_scores = self._bm25_retriever.search(query, corpus)
        max_bm = max(bm25_scores.values()) or 1.0
        max_kw = max(kw_scores.values()) or 1.0
        return {did: 0.5 * (bm25_scores.get(did, 0) / max_bm) + 0.5 * (kw_scores.get(did, 0) / max_kw) for did in corpus}

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)
