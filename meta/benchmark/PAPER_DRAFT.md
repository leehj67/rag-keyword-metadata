# BEIR·RepliQA 기반 키워드 추출 알고리즘 품질 비교 연구

## 초록

본 연구는 비지도 키워드 추출 알고리즘(RAKE, YAKE)과 통계 기반 방법(BM25/TF-IDF), 이들의 앙상블이 문서에서 추출하는 키워드의 품질을 정량적으로 비교한다. BEIR(SciFact, NFCorpus, FiQA) 및 RepliQA 데이터셋을 사용하여 QKO(Query-Keyword Overlap), Coverage, Diversity, AvgKeywords 네 가지 메트릭으로 평가하였다. 실험 결과, QKO와 Coverage에서는 앙상블 및 BM25가 우수하였고, Diversity에서는 BM25와 RAKE가 높은 값을 보였다. 데이터셋별 특성에 따라 최적 모델이 달라짐을 확인하였다.

**키워드**: 키워드 추출, RAKE, YAKE, BM25, 앙상블, BEIR, RepliQA, 키워드 품질 평가

---

## 1. 서론

### 1.1 연구 배경

키워드 추출(Keyword Extraction)은 문서의 핵심 개념을 요약하고 검색·분류·요약 등 다운스트림 태스크의 기반이 된다. 비지도 방식인 RAKE(Rapid Automatic Keyword Extraction)와 YAKE(Yet Another Keyword Extractor)는 별도의 학습 데이터 없이 문서 내부 통계만으로 키워드를 추출한다. 한편 TF-IDF나 BM25와 같은 통계 기반 방법은 빈도와 역문서빈도를 이용해 중요 용어를 선별한다.

### 1.2 연구 목적

본 연구의 목적은 다음과 같다.

1. RAKE, YAKE, BM25(TF-IDF 상위 term), RAKE+YAKE 앙상블의 키워드 품질을 공정하게 비교한다.
2. BEIR 및 RepliQA 등 공개 벤치마크 데이터셋에서의 성능을 정량화한다.
3. 쿼리-문서 연관성(qrels)을 활용한 키워드 품질 메트릭(QKO 등)을 제안하고 검증한다.

---

## 2. 관련 연구

### 2.1 RAKE

RAKE(Rapid Automatic Keyword Extraction)는 단어 공동 출현(co-occurrence)과 빈도를 이용해 키워드를 추출한다. Stopword를 제거한 후 구(phrase) 단위로 점수를 매기며, 형태소 분석이 필요 없어 다국어에 적용 가능하다.

### 2.2 YAKE

YAKE는 문서 내부 통계(텍스트 통계, 위치, 대소문자 등)만을 사용하는 비지도 키워드 추출기이다. n-gram 기반으로 키워드를 추출하며, 점수가 낮을수록 중요도가 높다.

### 2.3 BM25 / TF-IDF

BM25는 검색에서 널리 쓰이는 랭킹 함수이다. 본 실험에서는 BM25 자체가 아닌, 문서별 TF-IDF 상위 N개 term을 "키워드"로 간주하여 다른 추출 알고리즘과 품질을 비교한다.

---

## 3. 방법론

### 3.1 비교 대상 모델

| 모델 | 설명 |
|------|------|
| **RAKE** | rake-nltk 또는 multi-rake 기반, 구문 단위 키워드 추출 |
| **YAKE** | yake 패키지, n-gram 및 문서 내부 통계 기반 |
| **BM25** | TF-IDF 상위 30개 term을 키워드로 사용 (비교용) |
| **Ensemble** | RAKE + YAKE 키워드 통합 (중복 제거) |

### 3.2 평가 메트릭

#### 3.2.1 QKO (Query-Keyword Overlap)

관련 (query, doc) 쌍에서 쿼리 토큰이 추출된 키워드에 얼마나 포함되는지 측정한다.

$$
\text{QKO} = \frac{1}{N} \sum_{(q,d) \in \text{rel}} \frac{|Q(q) \cap K(d)|}{|Q(q)|}
$$

- $Q(q)$: 쿼리 $q$의 토큰 집합  
- $K(d)$: 문서 $d$의 키워드에서 추출한 토큰 집합  
- $N$: 관련 쌍 개수

#### 3.2.2 Coverage

문서의 고유 토큰 중 키워드가 차지하는 비율이다.

$$
\text{Coverage} = \frac{1}{M} \sum_{d} \frac{|T(d) \cap K(d)|}{|T(d)|}
$$

- $T(d)$: 문서 $d$의 고유 토큰 집합  
- $M$: 문서 개수

#### 3.2.3 Diversity

키워드 내 중복 정도를 나타낸다. 1에 가까울수록 중복이 적다.

$$
\text{Diversity} = \frac{1}{M} \sum_{d} \min\left( \frac{|\text{unique}(K(d))|}{\sum_{\text{kw}} |\text{tokenize}(\text{kw})|}, 1 \right)
$$

#### 3.2.4 AvgKeywords

문서당 평균 키워드 개수이다.

$$
\text{AvgKeywords} = \frac{1}{M} \sum_{d} |\text{keywords}(d)|
$$

#### 3.2.5 토큰화

모든 메트릭에서 영문/숫자 기반 토큰화를 사용한다: `\b[a-z0-9]+\b`, 2글자 이상만 포함.

---

## 4. 실험 설정

### 4.1 데이터셋

| 데이터셋 | 출처 | 용도 |
|----------|------|------|
| **SciFact** | BEIR | 과학 사실 검증 |
| **NFCorpus** | BEIR | 의료/생명과학 |
| **FiQA** | BEIR | 금융 QA |
| **RepliQA** | HuggingFace (ServiceNow) | 토픽 검색 |

### 4.2 실험 환경

- **구현**: Python, rank-bm25, datasets, beir
- **RAKE**: rake-nltk (multi-rake 대안, pycld2 의존성 회피)
- **YAKE**: yake
- **키워드 수**: 문서당 상위 30개 (BM25/Ensemble 포함)

---

## 5. 실험 결과

### 5.1 전체 결과

| 데이터셋 | 모델 | QKO | Coverage | Diversity | AvgKeywords |
|----------|------|-----|----------|-----------|-------------|
| **scifact** | rake | 0.2453 | 0.4188 | 0.7314 | 29.8 |
| | yake | 0.2562 | 0.2296 | 0.4223 | 30.0 |
| | bm25 | **0.3200** | 0.2762 | **1.0000** | 30.0 |
| | ensemble | **0.3408** | **0.5062** | 0.5350 | 51.4 |
| **nfcorpus** | rake | 0.0823 | 0.3861 | 0.7205 | 29.8 |
| | yake | 0.0903 | 0.2163 | 0.4487 | 30.0 |
| | bm25 | **0.0962** | 0.2594 | **1.0000** | 30.0 |
| | ensemble | **0.1145** | **0.4707** | 0.5581 | 50.7 |
| **fiqa** | rake | 0.1874 | 0.4672 | 0.8532 | 24.5 |
| | yake | 0.2178 | 0.3769 | 0.5405 | 28.1 |
| | bm25 | **0.2468** | 0.4964 | **1.0000** | 29.7 |
| | ensemble | **0.2564** | **0.5709** | 0.5808 | 42.0 |
| **repliqa** | rake | 0.1661 | 0.1587 | 0.8689 | 30.0 |
| | yake | 0.2118 | 0.0592 | 0.4699 | 30.0 |
| | bm25 | **0.3339** | 0.0635 | **1.0000** | 30.0 |
| | ensemble | **0.2729** | **0.1968** | 0.6724 | 57.3 |

### 5.2 메트릭별 분석

#### QKO (Query-Keyword Overlap)

- **BM25**와 **Ensemble**이 전 데이터셋에서 가장 높은 QKO를 기록하였다.
- BM25는 쿼리와 유사한 고빈도 term을 선별하므로 QKO에 유리하다.
- Ensemble은 RAKE+YAKE를 결합해 다양한 키워드를 포함하므로 쿼리 토큰과의 오버랩이 증가한다.

#### Coverage

- **Ensemble**이 scifact, nfcorpus, fiqa에서 최고 Coverage를 보였다.
- RAKE도 fiqa에서 0.4672로 높은 Coverage를 기록하였다.
- RepliQA에서는 문서 특성상 전체 Coverage가 낮게 나타났다.

#### Diversity

- **BM25**는 단일 term만 사용하므로 Diversity가 항상 1.0이다.
- **RAKE**가 phrase 기반임에도 0.72~0.87로 높은 Diversity를 유지하였다.
- **YAKE**는 n-gram 중복으로 인해 Diversity가 상대적으로 낮았다(0.42~0.54).

#### AvgKeywords

- **Ensemble**은 RAKE+YAKE 통합으로 문서당 42~57개로 가장 많은 키워드를 추출하였다.
- BM25, RAKE, YAKE는 설정된 상한(30개) 근처에서 수렴하였다.

### 5.3 데이터셋별 특성

- **SciFact**: 앙상블이 QKO·Coverage 모두에서 우수.
- **NFCorpus**: QKO가 전반적으로 낮아(0.08~0.11) 도메인 특화 쿼리와의 정합성이 상대적으로 낮음.
- **FiQA**: RAKE의 Diversity(0.85)와 Ensemble의 Coverage(0.57)가 돋보임.
- **RepliQA**: BM25의 QKO(0.33)가 가장 높으나 Coverage는 전 모델에서 낮음.

---

## 6. 논의

### 6.1 메트릭의 해석

- **QKO**는 검색·연관성 태스크에 직접적으로 기여하는 지표이다. BM25와 Ensemble이 유리한 구조를 가진다.
- **Coverage**는 문서 요약·대표성 관점에서 중요하다. Ensemble이 RAKE·YAKE를 통합해 더 넓은 문서 영역을 커버한다.
- **Diversity**는 중복 없는 다양한 키워드 추출을 요구할 때 유용하다. BM25(단일 term)와 RAKE(phrase 중복 적음)가 유리하다.

### 6.2 제한점

- 토큰화가 영문 중심으로 설계되어 다국어 문서에는 추가 검증이 필요하다.
- qrels 기반 QKO는 관련성 판정 품질에 의존한다.
- BM25는 "키워드 추출"이 아닌 TF-IDF 상위 term을 사용하므로, 다른 모델과 직접 비교 시 해석에 주의가 필요하다.

---

## 7. 결론

본 연구는 RAKE, YAKE, BM25(TF-IDF), RAKE+YAKE 앙상블의 키워드 품질을 BEIR·RepliQA 데이터셋으로 비교하였다. QKO와 Coverage에서는 앙상블과 BM25가, Diversity에서는 BM25와 RAKE가 우수하였다. 데이터셋과 태스크(검색 vs 요약 vs 다양성)에 따라 최적 모델이 달라지므로, 활용 목적에 맞는 메트릭과 모델 선택이 필요하다.

향후 연구로는 다국어 확장, 딥러닝 기반 추출기와의 비교, 태스크별 최적 가중치 탐색 등이 고려될 수 있다.

---

## 참고문헌

1. Rose, S., Engel, D., Cramer, N., & Cowley, W. (2010). Automatic keyword extraction from individual documents. *Text Mining*, 1-20.
2. Campos, R., Mangaravite, V., Pasquali, A., et al. (2020). YAKE! Keyword extraction from single documents using multiple local features. *Information Sciences*, 509, 257-289.
3. Robertson, S., & Zaragoza, H. (2009). The probabilistic relevance framework: BM25 and beyond. *Foundations and Trends in Information Retrieval*, 3(4), 333-389.
4. Thakur, N., Reimers, N., Rücklé, A., et al. (2021). BEIR: A heterogeneous benchmark for zero-shot evaluation of information retrieval models. *arXiv:2104.08663*.
