#!/usr/bin/env python
"""
벤치마크 결과 표시 UI

사용법:
  python -m benchmark.view_results
  python -m benchmark.view_results --results-dir path/to/results
"""
from __future__ import annotations

import argparse
import json
import webbrowser
from pathlib import Path
from typing import Optional


def _round_val(v: float) -> str:
    if isinstance(v, float):
        return f"{v:.4f}" if v < 10 else f"{v:.1f}"
    return str(v)


def _model_display_name(model: str) -> str:
    """앙상블 모델에 사용된 구성요소를 괄호로 표시"""
    if model.startswith("ensemble_") and "3way" not in model:
        return f"{model} (RAKE+YAKE+BM25)"
    if "ensemble3way+bm25" in model:
        return f"{model} (RAKE+YAKE+Top-K+BM25)"
    if "weighted_" in model:
        parts = model.replace("weighted_", "").split("_")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return f"{model} (RAKE:YAKE {parts[0]}:{parts[1]})"
        return f"{model} (RAKE+YAKE 가중투표)"
    if model.startswith("diversity"):
        return f"{model} (RAKE+YAKE+Top-K, MMR)"
    return model


METRIC_DESCRIPTIONS = {
    "QKO": "Query-Keyword Overlap. 관련 (쿼리, 문서) 쌍에서 쿼리 토큰이 추출된 키워드에 얼마나 포함되는지 비율. 높을수록 쿼리와 키워드가 잘 맞음.",
    "Coverage": "문서 고유 토큰 중 키워드가 차지하는 비율. 문서 전체를 키워드가 얼마나 잘 대표하는지 나타냄.",
    "Diversity": "키워드 내 중복 없음 비율 (unique_terms / total_terms). 1에 가까울수록 서로 다른 용어로 구성됨.",
    "AvgKeywords": "문서당 평균 키워드 수. 설정한 k 값과 비교해 실제 추출량을 확인.",
    "NDCG@10": "정규화된 누적 이득. 상위 10개 검색 결과의 랭킹 품질을 0~1로 평가.",
    "Recall@10": "상위 10개 결과에서 관련 문서를 얼마나 회상했는지 비율.",
    "MRR": "Mean Reciprocal Rank. 첫 번째 관련 문서의 역순위. 첫 번째에 나오면 1, 두 번째면 0.5 등.",
}


def _compute_summary(kw_data: dict, ret_data: dict) -> str:
    """데이터셋별 최고 모델 요약 (유의미한 결과 한눈에)"""
    ret_data = ret_data or {}
    datasets = list(kw_data.keys())
    lines = []
    # 키워드 품질: QKO 기준 (높을수록 좋음)
    for ds in datasets:
        best_qko = ("", -1.0)
        for model, m in kw_data.get(ds, {}).items():
            v = m.get("QKO", 0) or 0
            if v > best_qko[1]:
                best_qko = (model, v)
        if best_qko[0]:
            lines.append(f"<strong>{ds}</strong> QKO 최고: {_model_display_name(best_qko[0])} ({_round_val(best_qko[1])})")
    # 검색 성능: NDCG@10 기준
    for ds in datasets:
        best_ndcg = ("", -1.0)
        for model, m in ret_data.get(ds, {}).items():
            ndcg = (m.get("NDCG") or {}).get("NDCG@10", 0) or 0
            if ndcg > best_ndcg[1]:
                best_ndcg = (model, ndcg)
        if best_ndcg[0]:
            lines.append(f"<strong>{ds}</strong> NDCG@10 최고: {_model_display_name(best_ndcg[0])} ({_round_val(best_ndcg[1])})")
    if not lines:
        return ""
    return "<br>".join(lines)


def _build_html(kw_data: dict, ret_data: dict = None) -> str:
    ret_data = ret_data or {}
    datasets = list(kw_data.keys())
    all_models = set()
    for ds in datasets:
        all_models.update(kw_data[ds].keys())
    models = sorted(all_models)
    kw_metrics = ["QKO", "Coverage", "Diversity", "AvgKeywords"]
    ret_metrics = ["NDCG@10", "Recall@10", "MRR"]

    def _make_kw_table_rows(ds_list, model_list):
        out = []
        for ds in ds_list:
            out.append(f'<tr class="dataset-row"><td colspan="{len(kw_metrics)+1}" class="dataset-name">{ds}</td></tr>')
            for model in model_list:
                m = kw_data[ds].get(model, {})
                cells = "".join(f'<td>{_round_val(m.get(met, 0))}</td>' for met in kw_metrics)
                out.append(f'<tr><td class="model-name">{_model_display_name(model)}</td>{cells}</tr>')
        return "\n".join(out)

    core_kw = sorted([m for m in models if any(m.startswith(p) for p in ("rake_", "yake_", "bm25_", "ensemble_"))])
    weighted_kw = sorted([m for m in models if "weighted_" in m], key=lambda x: int((x.split("_")[1] or 0)))
    diversity_kw = sorted([m for m in models if m.startswith("diversity")])
    other_kw = sorted([m for m in models if m not in set(core_kw) and m not in set(weighted_kw) and m not in set(diversity_kw)])

    _empty_kw = "<tr><td colspan='5'>데이터 없음</td></tr>"
    table_core_kw = _make_kw_table_rows(datasets, core_kw) if core_kw else _empty_kw
    table_weighted_kw = _make_kw_table_rows(datasets, weighted_kw) if weighted_kw else _empty_kw
    table_diversity_kw = _make_kw_table_rows(datasets, diversity_kw) if diversity_kw else _empty_kw
    table_other_kw = _make_kw_table_rows(datasets, other_kw) if other_kw else _empty_kw

    ret_models = sorted(set(m for ds in ret_data for m in ret_data[ds].keys()))
    ret_core = [m for m in ret_models if not ("weighted" in m or m.startswith("diversity"))]
    ret_weighted = [m for m in ret_models if "weighted_" in m]
    ret_diversity = [m for m in ret_models if m.startswith("diversity")]

    ndcg_k_list = ["NDCG@1", "NDCG@3", "NDCG@5", "NDCG@10", "NDCG@100"]
    recall_k_list = ["Recall@1", "Recall@3", "Recall@5", "Recall@10", "Recall@100"]

    def _make_ret_rows(model_list, full_k: bool = False):
        if not model_list:
            col_count = len(ndcg_k_list) + len(recall_k_list) + 2 if full_k else 4
            return f"<tr><td colspan='{col_count}'>데이터 없음</td></tr>"
        out = []
        for ds in ret_data:
            if full_k:
                col_count = len(ndcg_k_list) + len(recall_k_list) + 2
                out.append(f'<tr class="dataset-row"><td colspan="{col_count}" class="dataset-name">{ds}</td></tr>')
            else:
                out.append(f'<tr class="dataset-row"><td colspan="{len(ret_metrics)+1}" class="dataset-name">{ds}</td></tr>')
            for model in model_list:
                if model not in ret_data.get(ds, {}):
                    continue
                m = ret_data[ds][model]
                ndcg = m.get("NDCG", {}) or {}
                recall = m.get("Recall", {}) or {}
                if full_k:
                    ndcg_cells = "".join(f'<td>{_round_val(ndcg.get(k, 0))}</td>' for k in ndcg_k_list)
                    recall_cells = "".join(f'<td>{_round_val(recall.get(k, 0))}</td>' for k in recall_k_list)
                    cells = ndcg_cells + recall_cells + f'<td>{_round_val(m.get("MRR", 0))}</td>'
                else:
                    cells = f'<td>{_round_val(ndcg.get("NDCG@10", 0))}</td><td>{_round_val(recall.get("Recall@10", 0))}</td><td>{_round_val(m.get("MRR", 0))}</td>'
                out.append(f'<tr><td class="model-name">{_model_display_name(model)}</td>{cells}</tr>')
        col_count = len(ndcg_k_list) + len(recall_k_list) + 2 if full_k else 4
        return "\n".join(out) if out else f"<tr><td colspan='{col_count}'>데이터 없음</td></tr>"

    _empty_ret = "<tr><td colspan='4'>데이터 없음</td></tr>"
    ret_table_core = _make_ret_rows(ret_core) if ret_core else _empty_ret
    ret_table_weighted = _make_ret_rows(ret_weighted) if ret_weighted else _empty_ret
    ret_table_diversity = _make_ret_rows(ret_diversity) if ret_diversity else _empty_ret
    ret_table_core_full = _make_ret_rows(ret_core, full_k=True) if ret_core else "<tr><td colspan='13'>데이터 없음</td></tr>"

    # 메트릭 설명 패널 (우측): QKO, Coverage, Diversity, AvgKeywords, NDCG@10, Recall@10, MRR
    metric_order = ["QKO", "Coverage", "Diversity", "AvgKeywords", "NDCG@10", "Recall@10", "MRR"]
    desc_items = [
        f'<div class="metric-desc-item"><strong>{m}</strong><p>{METRIC_DESCRIPTIONS[m]}</p></div>'
        for m in metric_order if m in METRIC_DESCRIPTIONS
    ]
    metric_desc_html = "\n".join(desc_items)

    # 메인 그래프: k=10 핵심 모델만 (rake, yake, bm25, ensemble)
    core_models = [m for m in models if m in ("rake_k10", "yake_k10", "bm25_k10", "ensemble_k10")]
    if not core_models:
        core_models = [m for m in models if m.endswith("_k10") and not ("weighted" in m or m.startswith("diversity"))][:4]
    main_chart_data = {ds: {m: kw_data[ds].get(m, {}) for m in core_models} for ds in datasets}
    chart_data = json.dumps(main_chart_data)

    # 가중 투표·다양성 보정 전용 데이터
    weighted_models = sorted([m for m in models if "weighted_" in m])
    diversity_models = sorted([m for m in models if m.startswith("diversity")])
    weighted_data = {}
    diversity_data = {}
    for ds in datasets:
        if weighted_models:
            weighted_data[ds] = {m: kw_data[ds].get(m, {}) for m in weighted_models}
        if diversity_models:
            diversity_data[ds] = {m: kw_data[ds].get(m, {}) for m in diversity_models}
    weighted_chart_data = json.dumps(weighted_data) if weighted_data else "{}"
    diversity_chart_data = json.dumps(diversity_data) if diversity_data else "{}"

    palette = [
        "rgba(233, 69, 96, 0.8)", "rgba(162, 210, 255, 0.8)", "rgba(46, 213, 115, 0.8)",
        "rgba(255, 211, 42, 0.8)", "rgba(155, 89, 182, 0.8)", "rgba(26, 188, 156, 0.8)",
    ]
    model_colors = {m: palette[i % len(palette)] for i, m in enumerate(core_models)}
    border_colors = {m: c.replace(", 0.8)", ", 1)") for m, c in model_colors.items()}
    short_labels = {m: m.replace("_k10", "").upper() if m.endswith("_k10") else m for m in core_models}

    summary_html = _compute_summary(kw_data, ret_data)

    chart_js = f"""
  const chartData = {chart_data};
  const datasets = Object.keys(chartData);
  const models = datasets.length ? Object.keys(chartData[datasets[0]]) : [];
  const colors = {json.dumps(model_colors)};
  const borders = {json.dumps(border_colors)};
  const shortLabels = {json.dumps(short_labels)};

  function createChart(canvasId, metric) {{
    const ctx = document.getElementById(canvasId);
    if (!ctx || !models.length) return;
    const dsLabels = Object.keys(chartData);
    const modelDatasets = models.map((model) => ({{
      label: shortLabels[model] || model,
      data: dsLabels.map(d => chartData[d][model]?.[metric] ?? 0),
      backgroundColor: colors[model] || 'rgba(128,128,128,0.8)',
      borderColor: borders[model] || 'rgb(128,128,128)',
      borderWidth: 1
    }}));
    new Chart(ctx.getContext('2d'), {{
      type: 'bar',
      data: {{ labels: dsLabels, datasets: modelDatasets }},
      options: {{
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 1.4,
        plugins: {{
          legend: {{ position: 'top' }},
          title: {{ display: true, text: metric, color: '#eee' }}
        }},
        scales: {{
          x: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#0f3460' }} }},
          y: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#0f3460' }} }}
        }}
      }}
    }});
  }}

  ['QKO','Coverage','Diversity','AvgKeywords'].forEach((m, i) => {{
    if (document.getElementById('chart-' + m)) createChart('chart-' + m, m);
  }});

  // 가중 투표·다양성 보정 데이터
  const weightedData = {weighted_chart_data};
  const diversityData = {diversity_chart_data};
  const _weightedModels = Object.keys(weightedData).length ? Object.keys(weightedData[Object.keys(weightedData)[0]]) : [];
  const weightedModels = _weightedModels.sort((a,b) => {{
    const ra = parseInt((a.match(/weighted_(\\d+)_/)?.[1] ?? 0)); const rb = parseInt((b.match(/weighted_(\\d+)_/)?.[1] ?? 0));
    return ra - rb;
  }});
  const diversityModels = Object.keys(diversityData).length ? Object.keys(diversityData[Object.keys(diversityData)[0]]) : [];
  const weightedPalette = ["rgba(100, 180, 255, 0.8)", "rgba(46, 213, 115, 0.8)", "rgba(255, 211, 42, 0.8)", "rgba(255, 140, 100, 0.8)", "rgba(155, 89, 182, 0.8)"];
  const weightedColors = {{}};
  weightedModels.forEach((m, i) => {{ weightedColors[m] = weightedPalette[i % 3]; }});
  const weightedNoData = document.getElementById('weighted-no-data');
  const diversityNoData = document.getElementById('diversity-no-data');
  if (weightedNoData) weightedNoData.style.display = weightedModels.length ? 'none' : 'block';
  if (diversityNoData) diversityNoData.style.display = diversityModels.length ? 'none' : 'block';

  // 가중 투표: 선 그래프 (RAKE 비율에 따른 QKO)
  const weightedCtx = document.getElementById('chart-weighted-QKO');
  if (weightedCtx && weightedModels.length) {{
    const ds = Object.keys(weightedData)[0] || 'nfcorpus';
    const labels = weightedModels.map(m => {{
      const ra = parseInt((m.match(/weighted_(\\d+)_/)?.[1] ?? 0));
      return ra + '% RAKE';
    }});
    const values = weightedModels.map(m => weightedData[ds]?.[m]?.QKO ?? 0);
    new Chart(weightedCtx.getContext('2d'), {{
      type: 'line',
      data: {{
        labels: labels,
        datasets: [{{ label: 'QKO', data: values, borderColor: 'rgba(46, 213, 115, 1)', backgroundColor: 'rgba(46, 213, 115, 0.2)', fill: true, tension: 0.3 }}]
      }},
      options: {{
        responsive: true, maintainAspectRatio: true, aspectRatio: 2,
        plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: '가중치에 따른 QKO', color: '#eee' }} }},
        scales: {{ x: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#0f3460' }} }}, y: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#0f3460' }} }} }}
      }}
    }});
  }}

  // 다양성 보정: 막대 그래프 (k별 QKO)
  const diversityCtx = document.getElementById('chart-diversity-QKO');
  if (diversityCtx && diversityModels.length) {{
    const ds = Object.keys(diversityData)[0] || 'nfcorpus';
    const labels = diversityModels.map(m => m.replace('diversity_k', 'k='));
    const values = diversityModels.map(m => diversityData[ds]?.[m]?.QKO ?? 0);
    new Chart(diversityCtx.getContext('2d'), {{
      type: 'bar',
      data: {{
        labels: labels,
        datasets: [{{ label: 'QKO', data: values, backgroundColor: 'rgba(26, 188, 156, 0.8)', borderColor: 'rgba(26, 188, 156, 1)', borderWidth: 1 }}]
      }},
      options: {{
        responsive: true, maintainAspectRatio: true, aspectRatio: 2,
        plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: 'k에 따른 QKO', color: '#eee' }} }},
        scales: {{ x: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#0f3460' }} }}, y: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#0f3460' }} }} }}
      }}
    }});
  }}
"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>벤치마크 결과</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ width: 100%; margin: 0; padding: 0; }}
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; padding: 24px 32px; background: #1a1a2e; color: #eee; }}
    h1 {{ color: #fff; margin-bottom: 24px; }}
    h2 {{ color: #e94560; margin: 32px 0 16px; font-size: 1.2em; }}
    .section-desc {{ color: #aaa; font-size: 0.9em; margin: -8px 0 20px; }}
    .table-section {{ color: #a2d2ff; font-size: 1em; margin: 20px 0 8px; font-weight: 500; }}
    .result-table {{ margin-bottom: 24px; }}
    .no-data-msg {{ background: #16213e; padding: 16px; border-radius: 8px; color: #888; margin-bottom: 20px; }}
    .no-data-msg code {{ font-size: 0.85em; color: #a2d2ff; }}
    .container {{ width: 100%; max-width: 100%; }}
    .layout {{ display: flex; gap: 32px; align-items: flex-start; max-width: 100%; }}
    .main {{ flex: 1; min-width: 0; max-width: 100%; }}
    .charts {{ display: grid; grid-template-columns: repeat(2, minmax(280px, 1fr)); gap: 28px; margin-bottom: 32px; }}
    .charts-single {{ grid-template-columns: 1fr; max-width: 600px; }}
    .chart-wrap {{ background: #16213e; border-radius: 8px; padding: 20px; height: 340px; min-height: 300px; }}
    @media (max-width: 900px) {{ .charts {{ grid-template-columns: 1fr; }} .chart-wrap {{ height: 320px; }} }}
    .table-scroll {{ overflow-x: auto; margin-bottom: 24px; }}
    table {{ border-collapse: collapse; width: 100%; background: #16213e; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #0f3460; }}
    th {{ background: #0f3460; color: #e94560; font-weight: 600; }}
    tr:hover {{ background: #1f4068; }}
    .dataset-row td {{ background: #0f3460; font-weight: 600; padding: 12px 16px; }}
    .dataset-name {{ color: #e94560; font-size: 1.1em; }}
    .model-name {{ font-weight: 500; color: #a2d2ff; }}
    td {{ font-family: 'Consolas', monospace; }}
    .sidebar {{ width: 340px; min-width: 280px; flex-shrink: 0; background: #16213e; border-radius: 8px; padding: 20px; position: sticky; top: 24px; }}
    .sidebar h3 {{ color: #e94560; margin: 0 0 16px; font-size: 1em; }}
    .metric-desc-item {{ margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid #0f3460; }}
    .metric-desc-item:last-child {{ margin-bottom: 0; padding-bottom: 0; border-bottom: none; }}
    .metric-desc-item strong {{ color: #a2d2ff; display: block; margin-bottom: 6px; }}
    .metric-desc-item p {{ margin: 0; font-size: 0.9em; line-height: 1.5; color: #ccc; }}
    @media (max-width: 1000px) {{ .layout {{ flex-direction: column; }} .sidebar {{ width: 100%; min-width: auto; position: static; }} }}
    .summary-box {{ background: linear-gradient(135deg, #16213e 0%%, #0f3460 100%%); border: 1px solid #e94560; border-radius: 12px; padding: 20px; margin-bottom: 28px; }}
    .summary-box h3 {{ color: #e94560; margin: 0 0 12px; font-size: 1em; }}
    .summary-box p {{ margin: 0; color: #ccc; font-size: 0.95em; line-height: 1.8; }}
  </style>
</head>
<body>
  <div class="container">
    <p class="section-desc"><a href="benchmark_results.html" style="color:#a2d2ff">← 데이터셋별 보기</a></p>
    <h1>키워드 품질 벤치마크 결과 (전체)</h1>

    <div class="summary-box">
      <h3>📌 데이터셋별 최고 모델 요약</h3>
      <p>{summary_html if summary_html else "데이터 없음"}</p>
      <p style="margin-top:12px; color:#888; font-size:0.85em">QKO: 쿼리-키워드 일치도 (높을수록 검색 적합) · NDCG@10: 검색 랭킹 품질 (높을수록 우수)</p>
    </div>

    <div class="layout">
      <div class="main">
        <h2>📊 핵심 모델 비교 (k=10)</h2>
        <p class="section-desc">RAKE, YAKE, BM25, Ensemble 4가지 메트릭</p>
        <div class="charts">
          <div class="chart-wrap"><canvas id="chart-QKO"></canvas></div>
          <div class="chart-wrap"><canvas id="chart-Coverage"></canvas></div>
          <div class="chart-wrap"><canvas id="chart-Diversity"></canvas></div>
          <div class="chart-wrap"><canvas id="chart-AvgKeywords"></canvas></div>
        </div>

        <h2>📋 키워드 품질 표</h2>
        <h3 class="table-section">핵심 모델 (RAKE, YAKE, BM25, Ensemble)</h3>
        <table class="result-table">
          <thead>
            <tr>
              <th>모델</th>
              <th>QKO</th>
              <th>Coverage</th>
              <th>Diversity</th>
              <th>AvgKeywords</th>
            </tr>
          </thead>
          <tbody>
            {table_core_kw}
          </tbody>
        </table>

        <h3 class="table-section">가중 투표</h3>
        <table class="result-table">
          <thead>
            <tr>
              <th>모델</th>
              <th>QKO</th>
              <th>Coverage</th>
              <th>Diversity</th>
              <th>AvgKeywords</th>
            </tr>
          </thead>
          <tbody>
            {table_weighted_kw}
          </tbody>
        </table>

        <h3 class="table-section">다양성 보정 앙상블</h3>
        <table class="result-table">
          <thead>
            <tr>
              <th>모델</th>
              <th>QKO</th>
              <th>Coverage</th>
              <th>Diversity</th>
              <th>AvgKeywords</th>
            </tr>
          </thead>
          <tbody>
            {table_diversity_kw}
          </tbody>
        </table>

        <h3 class="table-section">기타 모델 (Top-K, 앙상블+BM25 등)</h3>
        <table class="result-table">
          <thead>
            <tr>
              <th>모델</th>
              <th>QKO</th>
              <th>Coverage</th>
              <th>Diversity</th>
              <th>AvgKeywords</th>
            </tr>
          </thead>
          <tbody>
            {table_other_kw}
          </tbody>
        </table>

        <h2>🔍 검색 성능 표</h2>
        <h3 class="table-section">핵심 모델</h3>
        <table class="result-table">
          <thead>
            <tr>
              <th>모델</th>
              <th>NDCG@10</th>
              <th>Recall@10</th>
              <th>MRR</th>
            </tr>
          </thead>
          <tbody>
            {ret_table_core}
          </tbody>
        </table>
        <h3 class="table-section">가중 투표</h3>
        <table class="result-table">
          <thead>
            <tr>
              <th>모델</th>
              <th>NDCG@10</th>
              <th>Recall@10</th>
              <th>MRR</th>
            </tr>
          </thead>
          <tbody>
            {ret_table_weighted}
          </tbody>
        </table>
        <h3 class="table-section">다양성 보정</h3>
        <table class="result-table">
          <thead>
            <tr>
              <th>모델</th>
              <th>NDCG@10</th>
              <th>Recall@10</th>
              <th>MRR</th>
            </tr>
          </thead>
          <tbody>
            {ret_table_diversity}
          </tbody>
        </table>

        <h3 class="table-section">검색 성능 상세 (전체 k)</h3>
        <p class="section-desc">NDCG@1,3,5,10,100 · Recall@1,3,5,10,100</p>
        <div class="table-scroll">
        <table class="result-table">
          <thead>
            <tr>
              <th>모델</th>
              <th>NDCG@1</th>
              <th>NDCG@3</th>
              <th>NDCG@5</th>
              <th>NDCG@10</th>
              <th>NDCG@100</th>
              <th>Recall@1</th>
              <th>Recall@3</th>
              <th>Recall@5</th>
              <th>Recall@10</th>
              <th>Recall@100</th>
              <th>MRR</th>
            </tr>
          </thead>
          <tbody>
            {ret_table_core_full}
          </tbody>
        </table>
        </div>

        <h2>⚖️ 가중 투표 (RAKE vs YAKE 비율)</h2>
        <p class="section-desc">가중치에 따른 QKO 변화 (0:100 → 100:0)</p>
        <div class="no-data-msg" id="weighted-no-data" style="display:none">데이터가 없습니다. <code>python run_fill_weighted_diversity.py</code> 실행 후 확인하세요.</div>
        <div class="charts charts-weighted charts-single">
          <div class="chart-wrap"><canvas id="chart-weighted-QKO"></canvas></div>
        </div>

        <h2>🌐 다양성 보정 앙상블 (MMR)</h2>
        <p class="section-desc">k에 따른 QKO (k=10, 20, 30)</p>
        <div class="no-data-msg" id="diversity-no-data" style="display:none">데이터가 없습니다. <code>python run_fill_weighted_diversity.py</code> 실행 후 확인하세요.</div>
        <div class="charts charts-diversity charts-single">
          <div class="chart-wrap"><canvas id="chart-diversity-QKO"></canvas></div>
        </div>
      </div>

      <aside class="sidebar">
        <h3>📖 메트릭 설명</h3>
        {metric_desc_html}
      </aside>
    </div>
  </div>
  <script>{chart_js}</script>
</body>
</html>"""


def _summary_single(dataset_name: str, kw_data_ds: dict, ret_data_ds: dict) -> str:
    """단일 데이터셋 요약"""
    ret_data_ds = ret_data_ds or {}
    kw_data_ds = kw_data_ds or {}
    parts = []
    qko_items = [(m, (d.get("QKO") or 0)) for m, d in kw_data_ds.items()]
    best_qko = max(qko_items, key=lambda x: x[1]) if qko_items else (None, 0)
    if best_qko[0]:
        parts.append(f"QKO 최고: {_model_display_name(best_qko[0])} ({_round_val(best_qko[1])})")
    ndcg_items = [(m, ((d.get("NDCG") or {}).get("NDCG@10") or 0)) for m, d in ret_data_ds.items()]
    best_ndcg = max(ndcg_items, key=lambda x: x[1]) if ndcg_items else (None, 0)
    if best_ndcg[0]:
        parts.append(f"NDCG@10 최고: {_model_display_name(best_ndcg[0])} ({_round_val(best_ndcg[1])})")
    return " · ".join(parts) if parts else ""


def _build_html_single(dataset_name: str, kw_data_ds: dict, ret_data_ds: dict) -> str:
    """데이터셋별 개별 UI 생성 (단일 데이터셋 전용)"""
    ret_data_ds = ret_data_ds or {}
    models = sorted(kw_data_ds.keys())
    kw_metrics = ["QKO", "Coverage", "Diversity", "AvgKeywords"]
    ret_metrics = ["NDCG@10", "Recall@10", "MRR"]

    def _make_kw_rows(model_list):
        return "\n".join(
            f'<tr><td class="model-name">{_model_display_name(m)}</td>'
            + "".join(f'<td>{_round_val(kw_data_ds.get(m, {}).get(met, 0))}</td>' for met in kw_metrics)
            + "</tr>"
            for m in model_list
        )

    core_kw = sorted([m for m in models if any(m.startswith(p) for p in ("rake_", "yake_", "bm25_", "ensemble_"))])
    weighted_kw = sorted([m for m in models if "weighted_" in m], key=lambda x: int((x.split("_")[1] or 0)))
    diversity_kw = sorted([m for m in models if m.startswith("diversity")])
    other_kw = sorted([m for m in models if m not in set(core_kw) and m not in set(weighted_kw) and m not in set(diversity_kw)])

    table_core_kw = _make_kw_rows(core_kw) if core_kw else "<tr><td colspan='5'>데이터 없음</td></tr>"
    table_weighted_kw = _make_kw_rows(weighted_kw) if weighted_kw else "<tr><td colspan='5'>데이터 없음</td></tr>"
    table_diversity_kw = _make_kw_rows(diversity_kw) if diversity_kw else "<tr><td colspan='5'>데이터 없음</td></tr>"
    table_other_kw = _make_kw_rows(other_kw) if other_kw else "<tr><td colspan='5'>데이터 없음</td></tr>"

    ret_models = sorted(ret_data_ds.keys())
    ret_core = [m for m in ret_models if not ("weighted" in m or m.startswith("diversity"))]
    ret_weighted = [m for m in ret_models if "weighted_" in m]
    ret_diversity = [m for m in ret_models if m.startswith("diversity")]

    ndcg_k_list = ["NDCG@1", "NDCG@3", "NDCG@5", "NDCG@10", "NDCG@100"]
    recall_k_list = ["Recall@1", "Recall@3", "Recall@5", "Recall@10", "Recall@100"]

    def _make_ret_rows(model_list, full_k: bool = False):
        if not model_list:
            return "<tr><td colspan='4'>데이터 없음</td></tr>" if not full_k else "<tr><td colspan='13'>데이터 없음</td></tr>"
        out = []
        for m in model_list:
            data = ret_data_ds.get(m, {})
            ndcg = data.get("NDCG", {}) or {}
            recall = data.get("Recall", {}) or {}
            if full_k:
                ndcg_cells = "".join(f'<td>{_round_val(ndcg.get(k, 0))}</td>' for k in ndcg_k_list)
                recall_cells = "".join(f'<td>{_round_val(recall.get(k, 0))}</td>' for k in recall_k_list)
                cells = ndcg_cells + recall_cells + f'<td>{_round_val(data.get("MRR", 0))}</td>'
            else:
                cells = f'<td>{_round_val(ndcg.get("NDCG@10", 0))}</td><td>{_round_val(recall.get("Recall@10", 0))}</td><td>{_round_val(data.get("MRR", 0))}</td>'
            out.append(f'<tr><td class="model-name">{_model_display_name(m)}</td>{cells}</tr>')
        return "\n".join(out)

    ret_table_core = _make_ret_rows(ret_core)
    ret_table_weighted = _make_ret_rows(ret_weighted)
    ret_table_diversity = _make_ret_rows(ret_diversity)
    ret_table_core_full = _make_ret_rows(ret_core, full_k=True)

    metric_order = ["QKO", "Coverage", "Diversity", "AvgKeywords", "NDCG@10", "Recall@10", "MRR"]
    metric_desc_html = "\n".join(
        f'<div class="metric-desc-item"><strong>{m}</strong><p>{METRIC_DESCRIPTIONS[m]}</p></div>'
        for m in metric_order if m in METRIC_DESCRIPTIONS
    )

    core_models = [m for m in models if m in ("rake_k10", "yake_k10", "bm25_k10", "ensemble_k10")]
    if not core_models:
        core_models = [m for m in models if m.endswith("_k10") and not ("weighted" in m or m.startswith("diversity"))][:4]
    chart_data = {m: kw_data_ds.get(m, {}) for m in core_models}
    chart_data_js = json.dumps(chart_data)

    weighted_models = sorted([m for m in models if "weighted_" in m])
    diversity_models = sorted([m for m in models if m.startswith("diversity")])
    weighted_data_ds = {m: kw_data_ds.get(m, {}) for m in weighted_models}
    diversity_data_ds = {m: kw_data_ds.get(m, {}) for m in diversity_models}
    weighted_chart_js = json.dumps(weighted_data_ds)
    diversity_chart_js = json.dumps(diversity_data_ds)

    palette = ["rgba(233, 69, 96, 0.8)", "rgba(162, 210, 255, 0.8)", "rgba(46, 213, 115, 0.8)", "rgba(255, 211, 42, 0.8)"]
    model_colors = {m: palette[i % len(palette)] for i, m in enumerate(core_models)}
    short_labels = {m: m.replace("_k10", "").upper() if m.endswith("_k10") else m for m in core_models}

    short_labels_js = json.dumps(short_labels)
    chart_js = f"""
  const chartData = {chart_data_js};
  const models = Object.keys(chartData);
  const colors = {json.dumps(model_colors)};
  const shortLabels = {short_labels_js};

  function createChart(canvasId, metric) {{
    const ctx = document.getElementById(canvasId);
    if (!ctx || !models.length) return;
    const labels = models.map(m => shortLabels[m] || m.replace('_k10','').toUpperCase());
    const values = models.map(m => chartData[m]?.[metric] ?? 0);
    new Chart(ctx.getContext('2d'), {{
      type: 'bar',
      data: {{
        labels: labels,
        datasets: [{{ label: metric, data: values, backgroundColor: models.map((m,i) => colors[m] || 'rgba(128,128,128,0.8)'), borderWidth: 1 }}
      }},
      options: {{
        responsive: true, maintainAspectRatio: true, aspectRatio: 1.4,
        plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: metric, color: '#eee' }} }},
        scales: {{ x: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#0f3460' }} }}, y: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#0f3460' }} }} }}
      }}
    }});
  }}

  ['QKO','Coverage','Diversity','AvgKeywords'].forEach(m => {{
    if (document.getElementById('chart-' + m)) createChart('chart-' + m, m);
  }});

  const weightedData = {weighted_chart_js};
  const diversityData = {diversity_chart_js};
  const weightedModels = Object.keys(weightedData).sort((a,b) => parseInt((a.match(/weighted_(\\d+)_/)?.[1] ?? 0)) - parseInt((b.match(/weighted_(\\d+)_/)?.[1] ?? 0)));
  const diversityModels = Object.keys(diversityData);

  const wNoData = document.getElementById('weighted-no-data');
  const dNoData = document.getElementById('diversity-no-data');
  if (wNoData) wNoData.style.display = weightedModels.length ? 'none' : 'block';
  if (dNoData) dNoData.style.display = diversityModels.length ? 'none' : 'block';

  const weightedCtx = document.getElementById('chart-weighted-QKO');
  if (weightedCtx && weightedModels.length) {{
    const labels = weightedModels.map(m => (parseInt((m.match(/weighted_(\\d+)_/)?.[1] ?? 0))) + '% RAKE');
    const values = weightedModels.map(m => weightedData[m]?.QKO ?? 0);
    new Chart(weightedCtx.getContext('2d'), {{
      type: 'line',
      data: {{ labels: labels, datasets: [{{ label: 'QKO', data: values, borderColor: 'rgba(46, 213, 115, 1)', backgroundColor: 'rgba(46, 213, 115, 0.2)', fill: true, tension: 0.3 }}] }},
      options: {{ responsive: true, maintainAspectRatio: true, aspectRatio: 2, plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: '가중치에 따른 QKO', color: '#eee' }} }}, scales: {{ x: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#0f3460' }} }}, y: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#0f3460' }} }} }} }}
    }});
  }}

  const diversityCtx = document.getElementById('chart-diversity-QKO');
  if (diversityCtx && diversityModels.length) {{
    const labels = diversityModels.map(m => m.replace('diversity_k', 'k='));
    const values = diversityModels.map(m => diversityData[m]?.QKO ?? 0);
    new Chart(diversityCtx.getContext('2d'), {{
      type: 'bar',
      data: {{ labels: labels, datasets: [{{ label: 'QKO', data: values, backgroundColor: 'rgba(26, 188, 156, 0.8)', borderColor: 'rgba(26, 188, 156, 1)', borderWidth: 1 }}] }},
      options: {{ responsive: true, maintainAspectRatio: true, aspectRatio: 2, plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: 'k에 따른 QKO', color: '#eee' }} }}, scales: {{ x: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#0f3460' }} }}, y: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#0f3460' }} }} }} }}
    }});
  }}
"""

    back_link = '<p class="section-desc"><a href="benchmark_results_all.html" style="color:#a2d2ff">← 전체 한눈에 보기</a> · <a href="benchmark_results.html" style="color:#a2d2ff">데이터셋 목록</a></p>'
    summary_single = _summary_single(dataset_name, kw_data_ds, ret_data_ds)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>벤치마크 - {dataset_name}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ width: 100%; margin: 0; padding: 0; }}
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; padding: 24px 32px; background: #1a1a2e; color: #eee; }}
    h1 {{ color: #fff; margin-bottom: 24px; }}
    h2 {{ color: #e94560; margin: 32px 0 16px; font-size: 1.2em; }}
    .section-desc {{ color: #aaa; font-size: 0.9em; margin: -8px 0 20px; }}
    .table-section {{ color: #a2d2ff; font-size: 1em; margin: 20px 0 8px; font-weight: 500; }}
    .result-table {{ margin-bottom: 24px; }}
    .no-data-msg {{ background: #16213e; padding: 16px; border-radius: 8px; color: #888; margin-bottom: 20px; }}
    .no-data-msg code {{ font-size: 0.85em; color: #a2d2ff; }}
    .container {{ width: 100%; max-width: 100%; }}
    .layout {{ display: flex; gap: 32px; align-items: flex-start; max-width: 100%; }}
    .main {{ flex: 1; min-width: 0; max-width: 100%; }}
    .charts {{ display: grid; grid-template-columns: repeat(2, minmax(280px, 1fr)); gap: 28px; margin-bottom: 32px; }}
    .charts-single {{ grid-template-columns: 1fr; max-width: 600px; }}
    .chart-wrap {{ background: #16213e; border-radius: 8px; padding: 20px; height: 340px; min-height: 300px; }}
    @media (max-width: 900px) {{ .charts {{ grid-template-columns: 1fr; }} .chart-wrap {{ height: 320px; }} }}
    .table-scroll {{ overflow-x: auto; margin-bottom: 24px; }}
    table {{ border-collapse: collapse; width: 100%; background: #16213e; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #0f3460; }}
    th {{ background: #0f3460; color: #e94560; font-weight: 600; }}
    tr:hover {{ background: #1f4068; }}
    .model-name {{ font-weight: 500; color: #a2d2ff; }}
    td {{ font-family: 'Consolas', monospace; }}
    .sidebar {{ width: 340px; min-width: 280px; flex-shrink: 0; background: #16213e; border-radius: 8px; padding: 20px; position: sticky; top: 24px; }}
    .sidebar h3 {{ color: #e94560; margin: 0 0 16px; font-size: 1em; }}
    .metric-desc-item {{ margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid #0f3460; }}
    .metric-desc-item:last-child {{ margin-bottom: 0; padding-bottom: 0; border-bottom: none; }}
    .metric-desc-item strong {{ color: #a2d2ff; display: block; margin-bottom: 6px; }}
    .metric-desc-item p {{ margin: 0; font-size: 0.9em; line-height: 1.5; color: #ccc; }}
    @media (max-width: 1000px) {{ .layout {{ flex-direction: column; }} .sidebar {{ width: 100%; min-width: auto; position: static; }} }}
    .ds-link {{ display: block; padding: 12px 16px; margin: 8px 0; background: #16213e; border-radius: 8px; color: #a2d2ff; text-decoration: none; }}
    .ds-link:hover {{ background: #1f4068; }} .ds-link.active {{ background: #0f3460; color: #e94560; }}
    .summary-box {{ background: linear-gradient(135deg, #16213e 0%%, #0f3460 100%%); border: 1px solid #e94560; border-radius: 12px; padding: 20px; margin-bottom: 28px; }}
    .summary-box h3 {{ color: #e94560; margin: 0 0 12px; font-size: 1em; }}
    .summary-box p {{ margin: 0; color: #ccc; font-size: 0.95em; line-height: 1.8; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>키워드 품질 벤치마크 결과 — {dataset_name}</h1>
    {back_link}
    {f'<div class="summary-box"><h3>📌 이 데이터셋 최고 모델</h3><p>{summary_single}</p></div>' if summary_single else ''}

    <div class="layout">
      <div class="main">
        <h2>📊 핵심 모델 비교 (k=10)</h2>
        <p class="section-desc">RAKE, YAKE, BM25, Ensemble 4가지 메트릭</p>
        <div class="charts">
          <div class="chart-wrap"><canvas id="chart-QKO"></canvas></div>
          <div class="chart-wrap"><canvas id="chart-Coverage"></canvas></div>
          <div class="chart-wrap"><canvas id="chart-Diversity"></canvas></div>
          <div class="chart-wrap"><canvas id="chart-AvgKeywords"></canvas></div>
        </div>

        <h2>📋 키워드 품질 표</h2>
        <h3 class="table-section">핵심 모델</h3>
        <table class="result-table"><thead><tr><th>모델</th><th>QKO</th><th>Coverage</th><th>Diversity</th><th>AvgKeywords</th></tr></thead><tbody>{table_core_kw}</tbody></table>
        <h3 class="table-section">가중 투표</h3>
        <table class="result-table"><thead><tr><th>모델</th><th>QKO</th><th>Coverage</th><th>Diversity</th><th>AvgKeywords</th></tr></thead><tbody>{table_weighted_kw}</tbody></table>
        <h3 class="table-section">다양성 보정 앙상블</h3>
        <table class="result-table"><thead><tr><th>모델</th><th>QKO</th><th>Coverage</th><th>Diversity</th><th>AvgKeywords</th></tr></thead><tbody>{table_diversity_kw}</tbody></table>
        <h3 class="table-section">기타 모델 (Top-K, 앙상블+BM25 등)</h3>
        <table class="result-table"><thead><tr><th>모델</th><th>QKO</th><th>Coverage</th><th>Diversity</th><th>AvgKeywords</th></tr></thead><tbody>{table_other_kw}</tbody></table>

        <h2>🔍 검색 성능 표</h2>
        <h3 class="table-section">핵심 모델</h3>
        <table class="result-table"><thead><tr><th>모델</th><th>NDCG@10</th><th>Recall@10</th><th>MRR</th></tr></thead><tbody>{ret_table_core}</tbody></table>
        <h3 class="table-section">가중 투표</h3>
        <table class="result-table"><thead><tr><th>모델</th><th>NDCG@10</th><th>Recall@10</th><th>MRR</th></tr></thead><tbody>{ret_table_weighted}</tbody></table>
        <h3 class="table-section">다양성 보정</h3>
        <table class="result-table"><thead><tr><th>모델</th><th>NDCG@10</th><th>Recall@10</th><th>MRR</th></tr></thead><tbody>{ret_table_diversity}</tbody></table>
        <h3 class="table-section">검색 성능 상세 (전체 k)</h3>
        <p class="section-desc">NDCG@1,3,5,10,100 · Recall@1,3,5,10,100</p>
        <div class="table-scroll">
        <table class="result-table"><thead><tr><th>모델</th><th>NDCG@1</th><th>NDCG@3</th><th>NDCG@5</th><th>NDCG@10</th><th>NDCG@100</th><th>Recall@1</th><th>Recall@3</th><th>Recall@5</th><th>Recall@10</th><th>Recall@100</th><th>MRR</th></tr></thead><tbody>{ret_table_core_full}</tbody></table>
        </div>

        <h2>⚖️ 가중 투표 (RAKE vs YAKE 비율)</h2>
        <p class="section-desc">가중치에 따른 QKO 변화</p>
        <div class="no-data-msg" id="weighted-no-data" style="display:none">데이터 없음</div>
        <div class="charts charts-weighted charts-single"><div class="chart-wrap"><canvas id="chart-weighted-QKO"></canvas></div></div>

        <h2>🌐 다양성 보정 앙상블 (MMR)</h2>
        <p class="section-desc">k에 따른 QKO</p>
        <div class="no-data-msg" id="diversity-no-data" style="display:none">데이터 없음</div>
        <div class="charts charts-diversity charts-single"><div class="chart-wrap"><canvas id="chart-diversity-QKO"></canvas></div></div>
      </div>

      <aside class="sidebar"> <h3>📖 메트릭 설명</h3> {metric_desc_html} </aside>
    </div>
  </div>
  <script>{chart_js}</script>
</body>
</html>"""


def _build_index_html(datasets: list) -> str:
    """데이터셋별 링크가 있는 인덱스 페이지"""
    all_link = '<a class="ds-link ds-link-all" href="benchmark_results_all.html">📊 전체 데이터셋 한눈에 보기</a>'
    links = "\n".join(
        f'<a class="ds-link" href="benchmark_results_{ds}.html">{ds}</a>'
        for ds in datasets
    )
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>벤치마크 결과 - 데이터셋 선택</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; padding: 24px 32px; background: #1a1a2e; color: #eee; margin: 0; }}
    h1 {{ color: #fff; margin-bottom: 24px; }}
    .section-desc {{ color: #aaa; font-size: 0.9em; margin: -8px 0 20px; }}
    .ds-link {{ display: block; padding: 12px 16px; margin: 8px 0; background: #16213e; border-radius: 8px; color: #a2d2ff; text-decoration: none; max-width: 400px; }}
    .ds-link:hover {{ background: #1f4068; }}
    .ds-link-all {{ background: #0f3460; color: #e94560; font-weight: 600; margin-bottom: 20px; }}
    .ds-link-all:hover {{ background: #1a4a7a; }}
    .summary-box {{ background: linear-gradient(135deg, #16213e 0%%, #0f3460 100%%); border: 1px solid #e94560; border-radius: 12px; padding: 20px; margin-bottom: 28px; }}
    .summary-box h3 {{ color: #e94560; margin: 0 0 12px; font-size: 1em; }}
    .summary-box p {{ margin: 0; color: #ccc; font-size: 0.95em; line-height: 1.8; }}
  </style>
</head>
<body>
  <h1>키워드 품질 벤치마크 결과</h1>
  <p class="section-desc">BEIR + RepliQA 데이터셋별 결과를 선택하세요.</p>
  {all_link}
  <p class="section-desc">데이터셋별 상세</p>
  {links}
</body>
</html>"""


def generate_html(results_dir: Path, no_open: bool = True, summary_filename: Optional[str] = None) -> int:
    """benchmark_summary.json 기반 HTML 생성 (run_benchmark에서 호출 가능)"""
    summary_path = results_dir / (summary_filename or "benchmark_summary.json")
    if not summary_path.exists():
        print(f"[오류] 결과 파일 없음: {summary_path}")
        print("  먼저 python -m meta.benchmark.run_benchmark 를 실행하세요.")
        return 1

    with open(summary_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if "keyword" in raw:
        kw_data = raw["keyword"]
        ret_data = raw.get("retrieval", {})
    else:
        kw_data = raw
        ret_data = {}

    datasets = list(kw_data.keys())
    if not datasets:
        print("[오류] 데이터셋 없음")
        return 1

    # 전체 통합 HTML 생성 (모든 데이터셋 한 페이지)
    combined_html = _build_html(kw_data, ret_data)
    combined_path = results_dir / "benchmark_results_all.html"
    with open(combined_path, "w", encoding="utf-8") as f:
        f.write(combined_html)
    print(f"  [전체] benchmark_results_all.html ({len(datasets)}개 데이터셋 통합)")

    # 데이터셋별 개별 HTML 생성
    for ds in datasets:
        kw_ds = kw_data.get(ds, {})
        ret_ds = ret_data.get(ds, {})
        html = _build_html_single(ds, kw_ds, ret_ds)
        out = results_dir / f"benchmark_results_{ds}.html"
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  {ds}: benchmark_results_{ds}.html")

    # 인덱스 페이지 생성
    index_html = _build_index_html(datasets)
    index_path = results_dir / "benchmark_results.html"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_html)

    total_models = sum(len(kw_data.get(ds, {})) for ds in datasets)
    print(f"결과 저장: {index_path} (인덱스) + 전체 통합 + 데이터셋별 {len(datasets)}개 | 총 {total_models}개 모델 결과 반영")
    if not no_open:
        webbrowser.open(str(combined_path.absolute()))
    return 0


def main():
    parser = argparse.ArgumentParser(description="벤치마크 결과 표시")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path(__file__).parent / "results",
        help="결과 디렉터리",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="브라우저 자동 열기 안 함",
    )
    args = parser.parse_args()
    return generate_html(args.results_dir, no_open=args.no_open)


if __name__ == "__main__":
    import sys
    sys.exit(main())
