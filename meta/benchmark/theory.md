# 키워드 기반 Sparse 검색을 통한 RAG 성능 개선

## 1. 연구 주제

**LLM을 사용하지 않는 문서 전처리 기반 RAG 검색 성능 개선**

대규모 언어 모델(LLM)에 의존하지 않고, 키워드 추출과 sparse retrieval(BM25)을 결합한 문서 전처리 파이프라인을 통해 Retrieval-Augmented Generation(RAG)의 검색 단계 성능을 개선한다. RAKE, YAKE, Top-K(임베딩 기반) 등 다양한 키워드 추출 알고리즘과 이들의 앙상블이 문서 표현 품질 및 검색 성능에 미치는 영향을 BEIR·RepliQA 벤치마크로 정량화한다.

---

## 2. 평가 체계

### 2.1 데이터셋

| 데이터셋 | 출처 | 용도 |
|----------|------|------|
| **BEIR** | SciFact, NFCorpus, FiQA 등 | 공개 검색 벤치마크 |
| **RepliQA** | HuggingFace ServiceNow/repliqa | 토픽 검색 |

### 2.2 이중 평가

| 평가 유형 | 메트릭 | 설명 |
|-----------|--------|------|
| **키워드 품질** | QKO, Coverage, Diversity, AvgKeywords | 추출된 키워드의 품질 |
| **검색 성능** | NDCG@k, Recall@k, MRR | 검색 랭킹 품질 |

---

## 3. 키워드 모델

### 3.1 개별 모델

| 모델 | 방식 |
|------|------|
| **RAKE** | 통계 기반 구문 추출 (rake-nltk / multi-rake) |
| **YAKE** | 통계 기반 n-gram 추출 (yake) |
| **Top-K** | 임베딩 기반 상위 k개 추출 (KeyBERT 등) |

### 3.2 키워드 품질 평가 대상

| 유형 | 구성 | k 값 |
|------|------|------|
| **개별** | RAKE, YAKE, Top-K | 10, 20, 30 |
| **2-way 앙상블** | RAKE+Top-K, YAKE+Top-K | 10, 20, 30 |
| **3-way 앙상블** | RAKE+YAKE+Top-K | 10, 20, 30 |
| **가중 투표** | w₁·RAKE + w₂·YAKE (w₁=w₂, 0.3/0.7, 0.7/0.3) | 10, 20, 30 |
| **다양성 보정 앙상블** | MMR 기반 중복 억제 | 10, 20, 30 |

### 3.3 검색 성능 평가 대상

| 조합 | 키워드 추출 | 검색 점수 |
|------|-------------|-----------|
| 1 | RAKE | BM25 |
| 2 | YAKE | BM25 |
| 3 | Top-K | BM25 |
| 4 | RAKE+YAKE+Top-K | BM25 |

검색 점수 = α × (키워드 오버랩 점수) + (1 − α) × (BM25 점수), α = 0.5

---

## 4. 앙상블 정의

### 4.1 단순 결합 (RAKE+Top-K, YAKE+Top-K, RAKE+YAKE+Top-K)

각 모델의 키워드 후보를 합친 뒤 중복 제거. 순서는 출현 빈도 또는 원본 점수 유지.

### 4.2 가중 투표 앙상블 (Weighted Voting)

RAKE와 YAKE만 사용 (Top-K 제외, 가중치 해석 용이):

$$
\text{score}(kw) = w_1 \cdot s_{\text{RAKE}}(kw) + w_2 \cdot s_{\text{YAKE}}(kw)
$$

- $w_1 + w_2 = 1$
- 설정: 선형 구간 (0:100), (25:75), (50:50), (75:25), (100:0) — RAKE 가중치 0%~100% 5구간

각 모델별 점수는 0~1 정규화 후 가중 합산.

### 4.3 다양성 보정 앙상블 (Diversity-Corrected Ensemble)

MMR(Maximal Marginal Relevance) 기반 선택:

$$
\text{MMR}(kw) = \lambda \cdot \text{Rel}(kw) - (1-\lambda) \cdot \max_{kw' \in S} \text{Sim}(kw, kw')
$$

- $\text{Rel}(kw)$: RAKE+YAKE+Top-K 통합 점수  
- $\text{Sim}(kw, kw')$: 키워드 간 Jaccard 유사도 (토큰 집합)  
- $S$: 이미 선택된 키워드 집합  
- $\lambda$: 관련성 vs 다양성 균형 (기본 0.7)

순차적으로 MMR이 가장 높은 키워드를 선택하여 최종 상위 k개 구성. k=10, 20, 30으로 측정.

---

## 5. 메트릭 정의

### 5.1 키워드 품질

| 메트릭 | 수식 |
|--------|------|
| **QKO** | $\frac{1}{N}\sum \frac{\|Q \cap K\|}{\|Q\|}$ |
| **Coverage** | $\frac{1}{M}\sum \frac{\|T \cap K\|}{\|T\|}$ |
| **Diversity** | $\frac{1}{M}\sum \min(\frac{\|\text{unique}(K)\|}{\sum \|\text{tokenize}(kw)\|}, 1)$ |
| **AvgKeywords** | $\frac{1}{M}\sum \|\text{keywords}(d)\|$ |

### 5.2 검색 성능

| 메트릭 | 설명 |
|--------|------|
| **NDCG@k** | 정규화된 누적 이득 |
| **Recall@k** | 관련 문서 회상율 |
| **MRR** | 첫 관련 문서 역순위 |

---

## 6. 실험 구성 요약

| 구분 | 항목 |
|------|------|
| **키워드 품질** | RAKE, YAKE, Top-K, RAKE+Top-K, YAKE+Top-K, RAKE+YAKE+Top-K, 가중투표(선형 5구간), 다양성보정(k=10,20,30) |
| **k 값** | 10, 20, 30 |
| **검색 성능** | RAKE+BM25, YAKE+BM25, Top-K+BM25, (RAKE+YAKE+Top-K)+BM25 |
| **데이터셋** | BEIR (scifact, nfcorpus, fiqa), RepliQA |
