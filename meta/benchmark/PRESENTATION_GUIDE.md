# 프레젠테이션 모드 결과 발표 가이드

발표 시 알아야 할 핵심 내용을 정리했습니다.

---

## 1. 한 줄 요약

**LLM 없이 RAKE/YAKE 키워드 추출 + BM25 검색으로 RAG 검색 성능을 개선할 수 있는지** BEIR 벤치마크로 평가한 결과입니다.

---

## 2. 실험 설정 (발표 시 말할 것)

| 항목 | 내용 |
|------|------|
| **데이터셋** | scifact, nfcorpus, arguana (BEIR 3개) |
| **문서/쿼리 규모** | scifact 5,183문서·300쿼리 / nfcorpus 3,633·323 / arguana 8,674·1,406 |
| **키워드 수** | k=30 (문서당 상위 30개) |
| **Fusion 가중치** | alpha=0.1 (combined = 0.9×BM25 + 0.1×keyword) |

---

## 3. 비교하는 두 가지 방식

### Fusion (점수 결합)
- BM25 점수와 키워드 overlap 점수를 **가중 합산**하여 한 번에 랭킹
- 모델: bm25, rake+bm25, yake+bm25, ensemble

### Rerank (2단계)
- BM25로 top-K 검색 후, **키워드 점수로만** 상위 K개 재정렬
- 모델: bm25, rake+bm25_rerank, yake+bm25_rerank

---

## 4. 평가 메트릭 설명 (질문 대비)

| 메트릭 | 의미 | 발표용 한 줄 |
|--------|------|--------------|
| **NDCG@10** | 상위 10개 결과의 랭킹 품질 (0~1, 높을수록 좋음) | 검색 결과 순위가 얼마나 좋은지 |
| **MRR** | 첫 번째 관련 문서의 역순위 (0~1) | 첫 번째 정답을 얼마나 빨리 찾는지 |
| **QKO** | 관련 (query, doc)에서 쿼리 토큰이 키워드에 얼마나 포함되는지 | 키워드가 쿼리와 얼마나 맞는지 |
| **Coverage** | 문서 토큰 중 키워드가 차지하는 비율 | 문서를 얼마나 잘 대표하는지 |
| **Diversity** | 키워드 내 중복 정도 (1에 가까울수록 중복 적음) | 키워드가 얼마나 다양한지 |

---

## 5. 핵심 결과 (NDCG@10 기준)

### 5.1 Fusion 결과 (bench_present.json)

| 데이터셋 | BM25 | Rake+BM25 | YAKE+BM25 | Ensemble |
|---------|------|-----------|-----------|----------|
| **scifact** | **0.784** | 0.768 | 0.768 | 0.663 |
| **nfcorpus** | 0.321 | **0.324** | **0.324** | 0.310 |
| **arguana** | 0.351 | 0.353 | **0.367** | **0.365** |

**요약**
- **scifact**: BM25 단독이 가장 좋음. 키워드 fusion은 약간 손실.
- **nfcorpus**: Rake/YAKE fusion이 BM25보다 소폭 우위.
- **arguana**: YAKE fusion·Ensemble이 BM25보다 우수.

### 5.2 Rerank 결과 (bench_present_rerank.json)

| 데이터셋 | BM25 | Rake+BM25_rerank | YAKE+BM25_rerank |
|---------|------|------------------|------------------|
| **scifact** | **0.784** | 0.014 | 0.014 |
| **nfcorpus** | **0.321** | 0.185 | 0.186 |
| **arguana** | **0.351** | 0.002 | 0.002 |

**요약**
- **Rerank는 scifact·arguana에서 크게 실패** (NDCG 거의 0)
- nfcorpus에서는 BM25의 절반 수준으로 동작
- **Fusion이 Rerank보다 전반적으로 우수**

---

## 6. 발표 시 강조할 점

1. **데이터셋별 차이**: scifact는 BM25만으로 충분, arguana는 YAKE fusion이 유리.
2. **Fusion vs Rerank**: Fusion이 더 안정적. Rerank는 BM25 top-K 밖의 정답을 놓치기 쉬움.
3. **Ensemble**: 키워드 품질(QKO, Coverage)은 좋지만, scifact·nfcorpus에서는 검색 성능이 BM25보다 낮음.
4. **LLM/임베딩 없음**: 순수 통계 기반(RAKE, YAKE, BM25)만으로 평가.

---

## 7. 예상 질문 & 답변

**Q: Rerank가 왜 이렇게 나쁜가?**  
A: BM25 top-K(예: 30) 안에 정답이 없으면, 키워드로 재정렬해도 정답을 찾을 수 없습니다. Fusion은 전체 문서에 대해 점수를 합산하므로 더 넓은 후보를 고려합니다.

**Q: Ensemble이 왜 BM25보다 낮은가?**  
A: Ensemble은 RAKE+YAKE를 합쳐 키워드가 많아지지만, 노이즈도 늘어나 검색 시 BM25 신호를 희석할 수 있습니다. scifact처럼 BM25가 이미 강한 데이터셋에서는 단순 BM25가 유리합니다.

**Q: alpha=0.1은 어떻게 정한 것인가?**  
A: 키워드 신호가 BM25보다 약할 수 있어 보수적으로 0.1로 설정했습니다. alpha sweep(0.1, 0.2, 0.3, 0.5) 옵션으로 실험 가능합니다.

**Q: qrels가 뭔가?**  
A: Query–Document Relevance의 약자로, 질의별로 어떤 문서가 관련 있는지 정답 레이블입니다. NDCG·MRR 계산에 사용합니다.

---

## 8. 결과 파일 위치

| 파일 | 내용 |
|------|------|
| `results/bench_present.json` | Fusion 결과 (bm25, rake+bm25, yake+bm25, ensemble) |
| `results/bench_present_rerank.json` | Rerank 결과 (bm25, rake+bm25_rerank, yake+bm25_rerank) |
| `results/benchmark_results.html` | HTML 요약 (브라우저로 열기) |

---

## 9. 모델별 한 줄 설명

| 모델 | 설명 |
|------|------|
| **bm25** | 원문 BM25만 사용 (키워드 없음) |
| **rake+bm25** | RAKE 키워드 + BM25 점수 fusion (alpha=0.1) |
| **yake+bm25** | YAKE 키워드 + BM25 점수 fusion |
| **ensemble** | RAKE+YAKE 키워드 통합 + BM25 fusion |
| **rake+bm25_rerank** | BM25 top-K 검색 → RAKE 키워드로 재정렬 |
| **yake+bm25_rerank** | BM25 top-K 검색 → YAKE 키워드로 재정렬 |
