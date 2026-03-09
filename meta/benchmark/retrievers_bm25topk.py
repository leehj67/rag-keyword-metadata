"""
검증용: BM25 기반 키워드 TopK (KeyBERT 없음)

검색 경로 (RETRIEVAL_MODEL_SPEC.md 참고):
- BM25TopKRetriever: (b) 키워드 기반. doc_keywords(TF*IDF 상위 K)를 join한 텍스트로 표현.
- rake+bm25topk, yake+bm25topk, rake+yake+bm25topk, bm25_topk+bm25: (c) 점수 fusion 50:50.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from .retrievers import (
    RAKERetriever,
    YAKERetriever,
    BM25Retriever,
    BaseRetriever,
    _kw_overlap_score,
    _simple_tokenize,
)

# query/doc 토크나이저 통일: retrievers._simple_tokenize와 동일 (stopwords 미제거, 2글자 이상)
# overlap 왜곡 방지를 위해 query·doc 동일 규칙 사용


class BM25TopKRetriever(BaseRetriever):
    """BM25(TF*IDF) 기반 문서별 상위 K 토큰 키워드 추출 (임베딩 없음)"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}
        self._doc_ids: List[str] = []
        self._tokenized_corpus: Optional[List[List[str]]] = None

    def index_corpus(
        self,
        corpus: Dict[str, Dict[str, str]],
        tokenized_corpus: Optional[List[List[str]]] = None,
    ) -> None:
        self._doc_ids = list(corpus.keys())
        if tokenized_corpus is not None:
            tokenized = tokenized_corpus
        else:
            tokenized = []
            for doc_id in self._doc_ids:
                doc = corpus[doc_id]
                text = (doc.get("title") or "") + " " + (doc.get("text") or "")
                tokenized.append(_simple_tokenize(text))
        self._tokenized_corpus = tokenized

        n_docs = len(tokenized)
        doc_freq: Dict[str, int] = {}
        for toks in tokenized:
            for t in set(toks):
                doc_freq[t] = doc_freq.get(t, 0) + 1

        self._doc_keywords = {}
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
        q_tokens = set(_simple_tokenize(query))
        if not q_tokens:
            return {doc_id: 0.0 for doc_id in corpus}
        return {
            did: _kw_overlap_score(q_tokens, kws)
            for did, kws in self._doc_keywords.items()
        }

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


class _BM25TopKPlusBM25Mixin:
    """점수 fusion: 키워드 overlap + 원문 BM25 50:50 (max-normalization)"""

    def search(self, query: str, corpus: Dict[str, Dict[str, str]]) -> Dict[str, float]:
        q_tokens = set(_simple_tokenize(query))
        kw_scores = {
            did: _kw_overlap_score(q_tokens, kws)
            for did, kws in self._doc_keywords.items()
        }
        bm25_scores = self._bm25_retriever.search(query, corpus)
        max_bm = max(bm25_scores.values()) or 1.0
        max_kw = max(kw_scores.values()) or 1.0
        return {
            did: 0.5 * (bm25_scores.get(did, 0) / max_bm)
            + 0.5 * (kw_scores.get(did, 0) / max_kw)
            for did in corpus
        }


class RAKEPlusBM25TopKRetriever(BaseRetriever, _BM25TopKPlusBM25Mixin):
    """RAKE + BM25TopK 앙상블 (KeyBERT 없음)"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}
        self._bm25_retriever: Optional[BM25Retriever] = None

    def index_corpus(
        self,
        corpus: Dict[str, Dict[str, str]],
        tokenized_corpus: Optional[List[List[str]]] = None,
    ) -> None:
        r1 = RAKERetriever(keyword_top_k=self.keyword_top_k)
        r2 = BM25TopKRetriever(keyword_top_k=self.keyword_top_k)
        r1.index_corpus(corpus)
        r2.index_corpus(corpus, tokenized_corpus=tokenized_corpus)
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
        self._bm25_retriever.index_corpus(corpus, tokenized_corpus=tokenized_corpus)

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


class YAKEPlusBM25TopKRetriever(BaseRetriever, _BM25TopKPlusBM25Mixin):
    """YAKE + BM25TopK 앙상블 (KeyBERT 없음)"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}
        self._bm25_retriever: Optional[BM25Retriever] = None

    def index_corpus(
        self,
        corpus: Dict[str, Dict[str, str]],
        tokenized_corpus: Optional[List[List[str]]] = None,
    ) -> None:
        r1 = YAKERetriever(keyword_top_k=self.keyword_top_k)
        r2 = BM25TopKRetriever(keyword_top_k=self.keyword_top_k)
        r1.index_corpus(corpus)
        r2.index_corpus(corpus, tokenized_corpus=tokenized_corpus)
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
        self._bm25_retriever.index_corpus(corpus, tokenized_corpus=tokenized_corpus)

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


class EnsembleRAKEYAKEBM25TopKRetriever(BaseRetriever, _BM25TopKPlusBM25Mixin):
    """RAKE + YAKE + BM25TopK 3-way 앙상블 (KeyBERT 없음)"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}
        self._bm25_retriever: Optional[BM25Retriever] = None

    def index_corpus(
        self,
        corpus: Dict[str, Dict[str, str]],
        tokenized_corpus: Optional[List[List[str]]] = None,
    ) -> None:
        r1 = RAKERetriever(keyword_top_k=self.keyword_top_k)
        r2 = YAKERetriever(keyword_top_k=self.keyword_top_k)
        r3 = BM25TopKRetriever(keyword_top_k=self.keyword_top_k)
        r1.index_corpus(corpus)
        r2.index_corpus(corpus)
        r3.index_corpus(corpus, tokenized_corpus=tokenized_corpus)
        kw1, kw2, kw3 = (
            r1.get_doc_keywords(),
            r2.get_doc_keywords(),
            r3.get_doc_keywords(),
        )
        self._doc_keywords = {}
        for doc_id in corpus:
            seen, unique = set(), []
            for kw in (
                kw1.get(doc_id, []) + kw2.get(doc_id, []) + kw3.get(doc_id, [])
            ):
                k = kw.strip().lower()
                if k and k not in seen:
                    seen.add(k)
                    unique.append(k)
            self._doc_keywords[doc_id] = unique[: self.keyword_top_k * 3]
        self._bm25_retriever = BM25Retriever(top_k=self.top_k)
        self._bm25_retriever.index_corpus(corpus, tokenized_corpus=tokenized_corpus)

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)


class BM25TopKPlusBM25Retriever(BaseRetriever, _BM25TopKPlusBM25Mixin):
    """BM25TopK 키워드 + BM25 검색"""

    def __init__(self, top_k: int = 1000, keyword_top_k: int = 30):
        super().__init__(top_k)
        self.keyword_top_k = keyword_top_k
        self._doc_keywords: Dict[str, List[str]] = {}
        self._bm25_retriever: Optional[BM25Retriever] = None

    def index_corpus(
        self,
        corpus: Dict[str, Dict[str, str]],
        tokenized_corpus: Optional[List[List[str]]] = None,
    ) -> None:
        r = BM25TopKRetriever(keyword_top_k=self.keyword_top_k)
        r.index_corpus(corpus, tokenized_corpus=tokenized_corpus)
        self._doc_keywords = r.get_doc_keywords()
        self._bm25_retriever = BM25Retriever(top_k=self.top_k)
        self._bm25_retriever.index_corpus(corpus, tokenized_corpus=tokenized_corpus)

    def get_doc_keywords(self) -> Dict[str, List[str]]:
        return dict(self._doc_keywords)
