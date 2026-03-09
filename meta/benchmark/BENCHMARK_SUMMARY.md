# 벤치마크 요약

## 1. 목표

**LLM 없이 키워드 추출 + Sparse 검색으로 RAG 검색 성능 개선**

- RAKE, YAKE, BM25, 앙상블 등 다양한 키워드 추출 방식의 품질·검색 성능을 정량 비교
- BEIR·RepliQA 벤치마크로 객관적 평가

---

## 2. 데이터셋

| 데이터셋 | 출처 | 문서 수 | 쿼리 수 | 용도 |
|----------|------|---------|---------|------|
| **scifact** | BEIR | ~5,183 | 300 | 과학 사실 검증 |
| **nfcorpus** | BEIR | ~3,633 | 323 | 의료/건강 |
| **fiqa** | BEIR | ~57,638 | 648 | 금융 QA |
| **arguana** | BEIR | (선택) | - | 논증 검색 |
| **trec-covid** | BEIR/TREC | (선택) | - | COVID 관련 |
| **repliqa** | HuggingFace | (선택) | - | 토픽 검색 |

**기본 실행 시**: scifact, nfcorpus, fiqa (3개)

---

## 3. 모델

### 3.1 개별 키워드 추출

| 모델 | 방식 |
|------|------|
| **rake** | RAKE (rake-nltk / multi-rake) |
| **yake** | YAKE 통계 기반 n-gram |
| **bm25** | TF-IDF 상위 term (키워드 품질 비교용) |
| **bm25_topk** | BM25 상위 term (KeyBERT Top-K 대체) |

### 3.2 앙상블

| 모델 | 구성 |
|------|------|
| **ensemble** | RAKE + YAKE 통합 |
| **rake+bm25topk** | RAKE + BM25TopK |
| **yake+bm25topk** | YAKE + BM25TopK |
| **rake+yake+bm25topk** | RAKE + YAKE + BM25TopK 3-way |

### 3.3 가중 투표 (RAKE vs YAKE 비율)

| 모델 | RAKE:YAKE |
|------|-----------|
| weighted_0_100 | 0:100 (YAKE만) |
| weighted_25_75 | 25:75 |
| weighted_50_50 | 50:50 |
| weighted_75_25 | 75:25 |
| weighted_100_0 | 100:0 (RAKE만) |

### 3.4 검색 (키워드 + BM25 50:50)

| 모델 | 키워드 | 검색 |
|------|--------|------|
| rake+bm25 | RAKE | BM25 |
| yake+bm25 | YAKE | BM25 |
| bm25_topk+bm25 | BM25TopK | BM25 |

### k 값

- **키워드 품질**: k = 10, 20, 30
- **검색 전용 모델**: k = 30 고정

---

## 4. 평가 메트릭

### 4.1 키워드 품질

| 메트릭 | 설명 |
|--------|------|
| **QKO** | Query-Keyword Overlap: 관련 (query, doc)에서 쿼리 토큰이 키워드에 얼마나 포함되는지 |
| **Coverage** | 문서 고유 토큰 중 키워드가 차지하는 비율 |
| **Diversity** | 키워드 내 중복 없음 비율 |
| **AvgKeywords** | 문서당 평균 키워드 수 |

### 4.2 검색 성능

| 메트릭 | 설명 |
|--------|------|
| **NDCG@10** | 정규화된 누적 이득 (랭킹 품질) |
| **MRR** | 첫 관련 문서 역순위 |

---

## 5. 실행 모드 요약

| 모드 | 데이터셋 | 모델 | k | 제한 |
|------|----------|------|---|------|
| **기본** | scifact, nfcorpus, fiqa | 전체 | 10,20,30 | 없음 |
| **--basic** | 위 3개 | rake, yake, bm25, ensemble | 10,20,30 | 없음 |
| **--verify** | 6개 (+arguana, trec-covid, repliqa) | 5개 핵심 | 10 | max_docs=1000, max_queries=150 |
| **--quick** | nfcorpus 1개 | 5개 | 10 | 없음 |
| **--fast** | scifact, nfcorpus | 전체 | 10,20,30 | max_docs=5000, max_queries=500 |
| **--smoke** | scifact | 5개 | 10 | max_docs=1000, max_queries=100 |
| **--presentation** | scifact, nfcorpus, arguana | bm25, rake+bm25, yake+bm25, ensemble | 30 | bench_present.json |

---

## 6. 출력

- `results/benchmark_summary.json`: 데이터셋별·모델별 메트릭
- `results/<dataset>_<model>_keywords.json`: 문서별 키워드 샘플
- `view_results`: HTML 표·그래프 생성
