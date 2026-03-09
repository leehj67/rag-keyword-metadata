#!/usr/bin/env python
"""
BEIR + TREC + RepliQA 키워드 품질 벤치마크 실행 스크립트

사용법:
  pip install rank-bm25 datasets beir
  python -m meta.benchmark.run_benchmark

실행 예시:
  # fusion (기존 발표 모드):
  python -m meta.benchmark.run_benchmark --presentation --force-reset

  # rerank (2-stage: BM25 topK → keyword 재정렬):
  python -m meta.benchmark.run_benchmark --presentation_rerank --force-reset

  # compare (fusion + rerank 둘 다 실행, 각각 별도 파일 저장):
  python -m meta.benchmark.run_benchmark --presentation_compare --force-reset

  # alpha sweep (fusion 모델만, alpha=[0,0.05,0.1,0.2,0.3] → CSV+PNG):
  python -m meta.benchmark.run_benchmark --alpha-sweep-fusion
"""
from __future__ import annotations

import os
# tqdm 진행 표시가 PowerShell stderr로 인해 오류로 인식되는 문제 방지 (최상단에서 설정)
os.environ["TQDM_DISABLE"] = "1"

import argparse
import sys
from pathlib import Path

# 프로젝트 루트(meta 상위) 경로 추가
_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def _check_deps():
    """필수 패키지 확인"""
    missing = []
    try:
        import rank_bm25
    except ImportError:
        missing.append("rank-bm25")
    try:
        import datasets
    except ImportError:
        missing.append("datasets")
    try:
        import beir
    except ImportError:
        missing.append("beir")
    if missing:
        print("[오류] 다음 패키지를 먼저 설치하세요:")
        print("  pip install " + " ".join(missing))
        sys.exit(1)


def main():
    _check_deps()
    from meta.benchmark.evaluate import run_benchmark, run_alpha_sweep_fusion

    parser = argparse.ArgumentParser(description="RAKE/YAKE/BM25/Ensemble 키워드 품질 벤치마크")
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=["scifact", "nfcorpus", "fiqa"],
        help="BEIR 데이터셋 (scifact, nfcorpus, fiqa, arguana, trec-covid 등)",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=None,
        help="모델 (기본: 전체). --basic 시 rake,yake,bm25,ensemble만",
    )
    parser.add_argument(
        "--k-values",
        nargs="+",
        type=int,
        default=[10, 20, 30],
        help="키워드 k 값 (기본: 10 20 30)",
    )
    parser.add_argument(
        "--basic",
        action="store_true",
        help="기본 4개 모델만 실행",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "results",
        help="결과 저장 경로",
    )
    parser.add_argument(
        "--no-repliqa",
        action="store_true",
        help="RepliQA 제외",
    )
    parser.add_argument(
        "--force-reset",
        action="store_true",
        help="기존 결과 삭제 후 처음부터 재계산",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="빠른 실행: nfcorpus 1개, 기본 4모델, k=10만, RepliQA 제외",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="병렬 워커 수 (기본: 1, 순차 실행. --workers N 으로 병렬 지정)",
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=None,
        help="문서 수 제한 (예: 5000 → fiqa 57K→5K로 10배 이상 빠름)",
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=None,
        help="검색 평가 쿼리 수 제한 (예: 1000 → repliqa 18K→1K로 18배 빠름)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="빠른 실행: nfcorpus+scifact만, max-docs 5000, max-queries 500, RepliQA 제외",
    )
    parser.add_argument(
        "--no-topk",
        action="store_true",
        help="(기본) KeyBERT 모델 제외, bm25_topk로 대체. 노트북 권장.",
    )
    parser.add_argument(
        "--use-topk",
        action="store_true",
        help="KeyBERT(TopK) 모델 포함 (로딩 1~2분/워커, 병목 가능)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="발표/검증용: 6개 데이터셋, 핵심 4모델, k=10, max_docs=1000, max_queries=150 (--max-docs/--max-queries로 override)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="전체 데이터 조회 (max_docs, max_queries 제한 없음). --verify와 함께 사용 시 검증 모델로 전체 데이터 평가",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="smoke test: scifact만, max_docs=1000, max_queries=100, workers=1",
    )
    parser.add_argument(
        "--presentation",
        action="store_true",
        help="발표용(fusion): scifact+nfcorpus+arguana, bm25/rake+bm25/yake+bm25/ensemble → bench_present.json",
    )
    parser.add_argument(
        "--presentation_rerank",
        action="store_true",
        help="발표용(rerank): scifact+nfcorpus+arguana, bm25/rake+bm25_rerank/yake+bm25_rerank → bench_present_rerank.json",
    )
    parser.add_argument(
        "--presentation_compare",
        action="store_true",
        help="fusion과 rerank 둘 다 실행, bench_present.json + bench_present_rerank.json 각각 저장",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.1,
        help="Fusion 가중치 (keyword weight). combined=(1-alpha)*bm25+alpha*kw (기본 0.1)",
    )
    parser.add_argument(
        "--alpha-sweep",
        action="store_true",
        help="alpha sweep: 0.1, 0.2, 0.3, 0.5로 fusion 모델 각각 실행 (발표/검증용)",
    )
    parser.add_argument(
        "--alpha-sweep-fusion",
        action="store_true",
        help="fusion 모델만 alpha sweep: scifact+nfcorpus+arguana, alpha=[0,0.05,0.1,0.2,0.3] → CSV+PNG",
    )
    args = parser.parse_args()

    if args.full:
        args.max_docs = None
        args.max_queries = None
        print("[전체 데이터] max_docs, max_queries 제한 없음")
    if args.presentation:
        args.datasets = ["scifact", "nfcorpus", "arguana"]
        args.models = ["bm25", "rake+bm25", "yake+bm25", "ensemble"]
        args.k_values = [30]
        args.no_repliqa = True
        args.summary_filename = "bench_present.json"
        if not args.full:
            args.max_docs = args.max_docs or 1000
            args.max_queries = args.max_queries or 150
        args.alpha = getattr(args, "alpha", 0.1)
        print("[발표 모드 - FUSION] scifact+nfcorpus+arguana, bm25/rake+bm25/yake+bm25/ensemble, k=30 → bench_present.json")
    elif args.presentation_rerank:
        args.datasets = ["scifact", "nfcorpus", "arguana"]
        args.models = ["bm25", "rake+bm25_rerank", "yake+bm25_rerank"]
        args.k_values = [30]
        args.no_repliqa = True
        args.summary_filename = "bench_present_rerank.json"
        if not args.full:
            args.max_docs = args.max_docs or 1000
            args.max_queries = args.max_queries or 150
        print("[발표 모드 - RERANK] scifact+nfcorpus+arguana, bm25/rake+bm25_rerank/yake+bm25_rerank, k=30 → bench_present_rerank.json")
    elif args.presentation_compare:
        args.datasets = ["scifact", "nfcorpus", "arguana"]
        args.k_values = [30]
        args.no_repliqa = True
        if not args.full:
            args.max_docs = args.max_docs or 1000
            args.max_queries = args.max_queries or 150
        args.alpha = getattr(args, "alpha", 0.1)
        args._compare_mode = True
        print("[발표 모드 - COMPARE] fusion + rerank 둘 다 실행 → bench_present.json + bench_present_rerank.json")
    elif args.smoke:
        args.datasets = ["scifact"]
        args.models = ["rake", "yake", "bm25", "bm25_topk", "ensemble"]
        args.k_values = [10]
        args.max_docs = args.max_docs or 1000
        args.max_queries = args.max_queries or 100
        args.workers = 1
        args.no_repliqa = True
        print("[smoke test] scifact, max_docs=1000, max_queries=100, workers=1")
    elif args.verify:
        args.datasets = ["scifact", "nfcorpus", "fiqa", "arguana", "trec-covid"]
        args.models = ["rake", "yake", "bm25", "bm25_topk", "ensemble"]
        args.k_values = [10]
        if not args.full:
            args.max_docs = args.max_docs or 1000
            args.max_queries = args.max_queries or 150
        args.no_repliqa = False
        limit_str = "제한 없음" if args.full else "max_docs=1000, max_queries=150"
        print(f"[검증 모드] scifact+nfcorpus+fiqa+arguana+trec-covid+repliqa, rake/yake/bm25/bm25_topk/ensemble, k=10, {limit_str}")
    elif args.quick:
        args.datasets = ["nfcorpus"]
        args.models = ["rake", "yake", "bm25", "bm25_topk", "ensemble"]
        args.k_values = [10]
        args.no_repliqa = True
        print("[빠른 실행] 데이터셋 1개, 모델 4개, k=10")
    if args.fast and not args.verify:
        args.datasets = args.datasets or ["nfcorpus", "scifact"]
        args.max_docs = args.max_docs or 5000
        args.max_queries = args.max_queries or 500
        args.no_repliqa = True
        print("[빠른 실행] nfcorpus+scifact, max_docs=5000, max_queries=500, RepliQA 제외")

    if args.workers is None:
        args.workers = 1
        print("[워커] 1 (기본, 노트북 권장). --workers N 으로 병렬 지정")
    elif args.workers > 2:
        print(f"[경고] workers={args.workers} > 2 → 노트북에서는 1 권장")

    models = args.models
    if args.basic:
        models = ["rake", "yake", "bm25", "ensemble"]
    alpha_sweep_list = [0.1, 0.2, 0.3, 0.5] if getattr(args, "alpha_sweep", False) else None

    if getattr(args, "alpha_sweep_fusion", False):
        run_alpha_sweep_fusion(
            datasets=["scifact", "nfcorpus", "arguana"],
            output_dir=args.output_dir,
            max_docs=args.max_docs,
            max_queries=args.max_queries,
        )
        return

    if getattr(args, "_compare_mode", False):
        # fusion 먼저 실행 (force_reset 적용)
        print("\n--- [1/2] FUSION 실행 ---")
        run_benchmark(
            datasets=args.datasets,
            models=["bm25", "rake+bm25", "yake+bm25", "ensemble"],
            k_values=args.k_values,
            output_dir=args.output_dir,
            summary_filename="bench_present.json",
            use_repliqa=not args.no_repliqa,
            force_reset=args.force_reset,
            workers=args.workers,
            max_docs=args.max_docs,
            max_queries=args.max_queries,
            skip_topk_models=not args.use_topk,
            alpha=getattr(args, "alpha", 0.1),
            alpha_sweep=alpha_sweep_list,
        )
        # rerank 실행 (캐시 재사용, force_reset=False)
        print("\n--- [2/2] RERANK 실행 ---")
        run_benchmark(
            datasets=args.datasets,
            models=["bm25", "rake+bm25_rerank", "yake+bm25_rerank"],
            k_values=args.k_values,
            output_dir=args.output_dir,
            summary_filename="bench_present_rerank.json",
            use_repliqa=not args.no_repliqa,
            force_reset=False,
            workers=args.workers,
            max_docs=args.max_docs,
            max_queries=args.max_queries,
            skip_topk_models=not args.use_topk,
            alpha=getattr(args, "alpha", 0.1),
            alpha_sweep=None,
        )
        summary_path = args.output_dir / "bench_present_rerank.json"
    else:
        run_benchmark(
            datasets=args.datasets,
            models=models,
            k_values=args.k_values,
            output_dir=args.output_dir,
            summary_filename=getattr(args, "summary_filename", None),
            use_repliqa=not args.no_repliqa,
            force_reset=args.force_reset,
            workers=args.workers,
            max_docs=args.max_docs,
            max_queries=args.max_queries,
            skip_topk_models=not args.use_topk,
            alpha=getattr(args, "alpha", 0.1),
            alpha_sweep=alpha_sweep_list,
        )
        summary_path = args.output_dir / (getattr(args, "summary_filename", None) or "benchmark_summary.json")

    # 벤치마크 완료 후 HTML summary 자동 생성
    if getattr(args, "_compare_mode", False):
        for fn in ("bench_present.json", "bench_present_rerank.json"):
            if (args.output_dir / fn).exists():
                try:
                    from meta.benchmark.view_results import generate_html
                    print(f"\n[HTML summary 생성] {fn}")
                    generate_html(args.output_dir, no_open=True, summary_filename=fn)
                except Exception as e:
                    print(f"[경고] HTML summary 생성 실패 ({fn}): {e}")
    elif summary_path.exists():
        try:
            from meta.benchmark.view_results import generate_html
            print("\n[HTML summary 생성]")
            generate_html(args.output_dir, no_open=True, summary_filename=getattr(args, "summary_filename", None))
        except Exception as e:
            print(f"[경고] HTML summary 생성 실패: {e}")


if __name__ == "__main__":
    main()
