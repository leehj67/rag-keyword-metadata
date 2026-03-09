# 검색 모델 사양

## 1. 모델별 검색 경로

| 모델 | BM25 인덱스 | 키워드 표현 | 검색 방식 |
|------|-------------|-------------|-----------|
| **bm25** | (a) 원문 | - | 원문 BM25만 |
| **rake+bm25** | (a) 원문 | RAKE 키워드 | (c) 점수 fusion 50:50 |
| **bm25_topk+bm25** | (a) 원문 | BM25 TF-IDF 상위 k | (c) 점수 fusion 50:50 |
| **rake+bm25topk** | (a) 원문 | RAKE + BM25TopK | (c) 점수 fusion 50:50 |
| **yake+bm25topk** | (a) 원문 | YAKE + BM25TopK | (c) 점수 fusion 50:50 |
| **rake+yake+bm25topk** | (a) 원문 | RAKE + YAKE + BM25TopK | (c) 점수 fusion 50:50 |

- **(a) 원문 BM25**: BM25 인덱스는 항상 `title + text` 원문 토큰화 결과 사용
- **(b) 키워드 기반 표현**: 키워드로 문서를 인덱싱하지 않음. 키워드는 overlap 점수 계산에만 사용
- **(c) 점수 fusion**: 기본 max-normalization. 옵션: `FUSION_MODE=max|zscore|rrf`, `FUSION_DIAG_LOG=1`로 진단 로그

## 2. k-values와 retrieval

| 모델 | k 영향 | 비고 |
|------|--------|------|
| **bm25** | retrieval 무관, run_name="bm25" | BM25는 원문만 사용. k=30 고정, run_name에 k suffix 없음 |
| **rake+bm25, yake+bm25, bm25_topk+bm25** | k=30 고정 | doc_keywords가 retrieval의 kw_score에 사용됨 |
| **rake, yake, ensemble, weighted_*** | k에 따라 변경 | doc_keywords가 retrieval 전체를 구성 |

## 3. 토크나이저

- **통일 규칙**: `[a-z0-9]+` 2글자 이상, 소문자, stopwords 없음 (영문 데이터셋 기준)
- query와 doc 동일 정규식/필터 적용
