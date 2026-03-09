# BEIR + TREC + RepliQA 벤치마크 (키워드 품질 평가)

RAKE, YAKE, BM25, Ensemble 모델의 **키워드 품질**을 BEIR, TREC, RepliQA 데이터셋으로 검증·비교합니다.

## 설치 (필수)

```bash
pip install rank-bm25 datasets beir rake-nltk yake
```

- **rank-bm25**: BM25 및 TF-IDF 키워드 추출
- **datasets**: RepliQA 및 BEIR HuggingFace fallback
- **beir**: BEIR 데이터셋
- **rake-nltk**: RAKE (multi-rake 대안, pycld2 불필요)
- **yake**: YAKE 키워드 추출

**선택 (Top-K 앙상블용)**:
```bash
pip install keybert
```

`[RAKE] fallback 사용` / `[YAKE] fallback 사용` 로그가 나오면:
```bash
python -m benchmark.check_keyword_deps   # 의존성 확인
pip install multi-rake yake              # 설치
```

## 실행

```bash
# 방법 1: 프로젝트 루트(ai_orchestrator)에서
python -m meta.benchmark.run_benchmark

# 방법 2: meta 디렉터리에서
cd meta
python -m benchmark.run_benchmark
```

### 옵션

- `--datasets`: BEIR 데이터셋 (기본: scifact, nfcorpus, fiqa)
- `--models`: 모델 (기본: 전체). `--basic` 시 rake, yake, bm25, ensemble만
- `--k-values`: 키워드 k 값 (기본: 10 20 30)
- `--basic`: 기본 4개 모델만 실행
- `--output-dir`: 결과 저장 경로
- `--no-repliqa`: RepliQA 제외

### 검색 경로 (RETRIEVAL_MODEL_SPEC.md 참고)

- **bm25**: 원문 BM25만. run_name=`bm25` (k suffix 없음)
- **rake+bm25, yake+bm25, bm25_topk+bm25**: 원문 BM25 + 키워드 overlap 점수 fusion 50:50
- **점수 fusion 옵션**: `FUSION_MODE=max|zscore|rrf`, `FUSION_DIAG_LOG=1`로 kw_score 진단 로그

### 모델 (theory.md 참고)

| 유형 | 모델 |
|------|------|
| 개별 | rake, yake, bm25, topk |
| 앙상블 | ensemble, rake+topk, yake+topk, rake+yake+topk |
| 가중 투표 | weighted_50_50, weighted_30_70, weighted_70_30 |
| 다양성 보정 | diversity |
| 검색 (키워드+BM25) | rake+bm25, yake+bm25, topk+bm25, ensemble3way+bm25 |

### 발표/검증용 (빠른 그래프용)

```bash
python -m benchmark.run_benchmark --verify
```

- **데이터셋**: scifact, nfcorpus, fiqa, arguana, trec-covid, repliqa (6개)
- **모델**: rake, yake, bm25, ensemble (핵심 4개)
- **k**: 10만
- **제한**: max_docs=3000, max_queries=300
- **목적**: 대회 발표·검증용 최소 수치만 빠르게 계산 → `view_results`로 그래프 표시

### 전체 데이터 조회 (제한 없음)

```bash
python -m benchmark.run_benchmark --full
python -m benchmark.run_benchmark --verify --full   # 검증 모델로 전체 데이터
```

- **--full**: max_docs, max_queries 제한 없음 (기존 전체 데이터 기준)
- **--verify --full**: 6개 데이터셋 + 4모델 + k=10, 제한 없음

### 병목 (5% 근처에서 멈춤)

- **원인**: KeyBERT(TopK) 모델이 `sentence-transformers` 로딩 (워커당 1~2분, ~1GB)
- **대상 모델**: topk, rake+topk, yake+topk, rake+yake+topk, diversity, topk+bm25, ensemble3way+bm25
- **해결**: `--no-topk`로 KeyBERT 모델 제외 → rake/yake/bm25/ensemble/weighted만 실행

```bash
python run_benchmark.py --fast --no-topk   # 빠르게 완료
```

### 예시

```bash
# meta 디렉터리에서 실행 시
python -m benchmark.run_benchmark --verify              # 발표용 검증 (가장 빠름)
python -m benchmark.run_benchmark --datasets scifact --models bm25 ensemble
python -m benchmark.run_benchmark --datasets scifact nfcorpus fiqa --models rake yake bm25 ensemble
python run_benchmark.py --fast --no-topk               # 병목 회피
```

## 출력

- `results/benchmark_summary.json`: 데이터셋별·모델별 키워드 품질 메트릭
- `results/<dataset>_<model>_keywords.json`: 문서별 추출 키워드 샘플 (상위 100개)

## 결과 표시 (표 + 그래프 UI)

```bash
python -m benchmark.view_results
```

`benchmark_summary.json`을 읽어 **표**와 **그래프**(QKO, Coverage, Diversity, AvgKeywords)를 브라우저에 표시합니다.

```bash
python -m benchmark.view_results --results-dir path/to/results  # 경로 지정
python -m benchmark.view_results --no-open                     # HTML만 생성, 브라우저 미실행
```

## 키워드 품질 메트릭

| 메트릭 | 설명 |
|--------|------|
| **QKO** | Query-Keyword Overlap: 관련 (query, doc) 쌍에서 쿼리 토큰이 키워드에 얼마나 포함되는지 (높을수록 좋음) |
| **Coverage** | 문서 고유 토큰 중 키워드가 차지하는 비율 (높을수록 문서를 잘 대표) |
| **Diversity** | 키워드 내 중복 없음 비율 (1에 가까울수록 중복 적음) |
| **AvgKeywords** | 문서당 평균 키워드 수 |

## 모델 설명

| 모델 | 키워드 추출 방식 |
|------|------------------|
| **RAKE** | RAKE 알고리즘 (multi-rake) |
| **YAKE** | YAKE 알고리즘 (yake) |
| **BM25** | TF-IDF 상위 N개 term (키워드 품질 비교용) |
| **Ensemble** | RAKE + YAKE 키워드 통합 |

## 데이터셋

- **BEIR**: SciFact, NFCorpus 등 (beir 패키지로 자동 다운로드)
- **TREC**: trec-covid 등 BEIR에 포함
- **RepliQA**: HuggingFace ServiceNow/repliqa (Topic Retrieval)

## 다시 시작할 때

| 목적 | 지울 것 |
|------|---------|
| **결과만 새로 만들기** | `meta/benchmark/results/` 폴더 삭제 |
| **완전 초기화** | `meta/benchmark/results/` + `meta/benchmark/data/` 삭제 (data 삭제 시 다음 실행 시 데이터셋 재다운로드) |

```bash
# 초기화 스크립트 (meta 디렉터리에서)
python -m benchmark.reset_results          # results만 삭제
python -m benchmark.reset_results --all   # results + data 삭제
python -m benchmark.reset_results -n     # dry-run (삭제 대상만 출력)
```

```powershell
# PowerShell로 직접 삭제
Remove-Item -Recurse -Force meta\benchmark\results
Remove-Item -Recurse -Force meta\benchmark\results, meta\benchmark\data
```
