# analysis_viewer.py
from __future__ import annotations

import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from collections import Counter
from typing import Dict, List, Any

# 그래프 시각화를 위한 선택적 import
try:
    import matplotlib
    matplotlib.use('TkAgg')  # tkinter와 호환
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def _read_jsonl(path: Path):
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


class AnalysisWindow(tk.Toplevel):
    def __init__(self, master, out_root: str, doc_id: str):
        super().__init__(master)
        self.title(f"문서 해석 보기 - {doc_id}")
        self.geometry("1400x900")  # 그래프를 위해 크기 확대
        self.out_root = out_root
        self.doc_id = doc_id
        self._tags_data = []

        self._load_data()
        self._build_ui()
        self._render_header()
        self._render_tags()
        self._render_chunks()
        if MATPLOTLIB_AVAILABLE:
            self._render_graphs()

    def _load_data(self):
        out = Path(self.out_root)
        self.doc_dir = out / self.doc_id
        self.auto_tags = _read_json(self.doc_dir / "auto_tags.json") or {}
        self.report = _read_json(self.doc_dir / "analysis_report.json") or {}
        # chunks는 core/chunks.jsonl에서 doc_id로 필터(항상 최신)
        all_chunks = _read_jsonl(out / "core" / "chunks.jsonl")
        self.chunks = [r for r in all_chunks if r.get("doc_id") == self.doc_id]
        # fallback: doc_dir/chunks.json
        if not self.chunks:
            cj = _read_json(self.doc_dir / "chunks.json") or {}
            self.chunks = cj.get("chunks") or []

    def _build_ui(self):
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True, padx=10, pady=10)

        # 상단: 요약
        top = ttk.Frame(root)
        top.pack(fill="x")

        self.lbl_title = ttk.Label(top, text="", font=("Malgun Gothic", 12, "bold"))
        self.lbl_title.pack(anchor="w")

        self.lbl_meta = ttk.Label(top, text="", wraplength=1050, justify="left")
        self.lbl_meta.pack(anchor="w", pady=(4, 8))

        sep = ttk.Separator(root, orient="horizontal")
        sep.pack(fill="x", pady=6)

        # 본문: 좌(태그/근거) + 우(그래프/청크)
        body = ttk.Frame(root)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, width=340)
        left.pack(side="left", fill="y", padx=(0, 10))

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)

        # left: genre / tags / evidence / report
        ttk.Label(left, text="분류(Genre)", font=("Malgun Gothic", 10, "bold")).pack(anchor="w")
        self.txt_genre = tk.Text(left, height=4, wrap="word")
        self.txt_genre.pack(fill="x", pady=(4, 10))

        ttk.Label(left, text="태그 Top-K", font=("Malgun Gothic", 10, "bold")).pack(anchor="w")
        self.lst_tags = tk.Listbox(left, height=10)
        self.lst_tags.pack(fill="x", pady=(4, 10))
        self.lst_tags.bind("<<ListboxSelect>>", self._on_select_tag)

        ttk.Label(left, text="태그 상세(계산식/점수)", font=("Malgun Gothic", 10, "bold")).pack(anchor="w")
        self.txt_tag_detail = tk.Text(left, height=10, wrap="word")
        self.txt_tag_detail.pack(fill="both", expand=False, pady=(4, 10))

        ttk.Label(left, text="근거(Evidence)", font=("Malgun Gothic", 10, "bold")).pack(anchor="w")
        self.lst_evd = tk.Listbox(left, height=10)
        self.lst_evd.pack(fill="x", pady=(4, 10))
        self.lst_evd.bind("<<ListboxSelect>>", self._on_select_evidence)

        ttk.Label(left, text="지표(Report)", font=("Malgun Gothic", 10, "bold")).pack(anchor="w")
        self.txt_report = tk.Text(left, height=8, wrap="word")
        self.txt_report.pack(fill="x", pady=(4, 0))

        # right: 상단 그래프 영역 + 하단 청크 영역
        right_top = ttk.Frame(right)
        right_top.pack(fill="both", expand=True, pady=(0, 10))
        
        # 그래프 탭 (Notebook)
        if MATPLOTLIB_AVAILABLE:
            self.graph_notebook = ttk.Notebook(right_top)
            self.graph_notebook.pack(fill="both", expand=True)
            
            # 탭 1: 문서 분류 분포
            self.tab_genre = ttk.Frame(self.graph_notebook)
            self.graph_notebook.add(self.tab_genre, text="분류 분포")
            
            # 탭 2: 태그 분포
            self.tab_tags = ttk.Frame(self.graph_notebook)
            self.graph_notebook.add(self.tab_tags, text="태그 분포")
            
            # 탭 3: 신뢰도 보정 전후
            self.tab_confidence = ttk.Frame(self.graph_notebook)
            self.graph_notebook.add(self.tab_confidence, text="신뢰도 보정")
        else:
            # matplotlib 없으면 텍스트로 표시
            self.graph_notebook = None
            ttk.Label(right_top, text="그래프 시각화를 위해 matplotlib 설치 필요:\npip install matplotlib", 
                     foreground="gray", justify="left", font=("Malgun Gothic", 9)).pack(fill="both", expand=True, padx=10, pady=10)
        
        # 하단: 청크 목록 + 본문
        right_bottom = ttk.Frame(right)
        right_bottom.pack(fill="both", expand=False)
        
        ttk.Label(right_bottom, text="청크 목록", font=("Malgun Gothic", 10, "bold")).pack(anchor="w")
        self.lst_chunks = tk.Listbox(right_bottom, height=8)
        self.lst_chunks.pack(fill="x", pady=(4, 10))
        self.lst_chunks.bind("<<ListboxSelect>>", self._on_select_chunk)

        ttk.Label(right_bottom, text="청크 본문", font=("Malgun Gothic", 10, "bold")).pack(anchor="w")
        self.txt_chunk = tk.Text(right_bottom, height=12, wrap="word")
        self.txt_chunk.pack(fill="both", expand=True, pady=(4, 0))

        # highlight tag
        self.txt_chunk.tag_configure("hl", background="#fff2a8")

    def _render_header(self):
        title = self.report.get("title") or self.auto_tags.get("title") or ""
        genre = self.auto_tags.get("genre")
        conf = self.auto_tags.get("genre_confidence")
        rk = self.report.get("record_key")
        vk = self.report.get("version_key")
        schema_v = self.auto_tags.get("schema_version")
        algo_info = self.auto_tags.get("algorithm_info") or {}

        self.lbl_title.config(text=title or f"(제목없음) {self.doc_id}")

        meta = []
        if genre:
            meta.append(f"Genre: {genre} (conf={conf})")
        if rk:
            meta.append(f"record_key: {rk}")
        if vk:
            meta.append(f"version_key: {vk}")
        if schema_v is not None:
            meta.append(f"auto_tags.schema_version: {schema_v}")
        if algo_info:
            # 알고리즘 사용 가능 여부 간단 표시
            parts = []
            if "rake_available" in algo_info:
                parts.append(f"RAKE={algo_info.get('rake_available')}")
            if "yake_available" in algo_info:
                parts.append(f"YAKE={algo_info.get('yake_available')}")
            if "konlpy_available" in algo_info:
                parts.append(f"KoNLPy={algo_info.get('konlpy_available')}")
            if parts:
                meta.append("tagger: " + ",".join([str(p) for p in parts]))
        if self.report.get("chunk_count") is not None:
            meta.append(f"chunks: {self.report.get('chunk_count')}  avg_chars={self.report.get('avg_chunk_chars'):.1f}")
        if self.report.get("evidence_quote_mapping_rate") is not None:
            meta.append(f"evidence_mapping_rate: {self.report.get('evidence_quote_mapping_rate'):.2%}")
        self.lbl_meta.config(text=" | ".join(meta))

        # genre box
        self.txt_genre.delete("1.0", "end")
        evs = self.auto_tags.get("genre_evidence") or []
        lines = [f"- {genre} (conf={conf})"]
        for e in evs[:3]:
            q = e.get("quote")
            if q:
                lines.append(f"  근거: {q[:160]}")
        self.txt_genre.insert("1.0", "\n".join(lines))

        # report box
        self.txt_report.delete("1.0", "end")
        rep_lines = []
        for k in ["chunk_count", "avg_chunk_chars", "evidence_quote_count", "evidence_quote_mapped_unique", "evidence_quote_mapping_rate"]:
            if k in self.report:
                rep_lines.append(f"{k}: {self.report.get(k)}")
        self.txt_report.insert("1.0", "\n".join(rep_lines) if rep_lines else "(report 없음)")

        # evidence list
        self.lst_evd.delete(0, "end")
        for e in (self.auto_tags.get("genre_evidence") or []):
            q = (e.get("quote") or "").strip()
            if q:
                self.lst_evd.insert("end", q[:220])

    def _render_tags(self):
        self.lst_tags.delete(0, "end")
        self.txt_tag_detail.delete("1.0", "end")
        self._tags_data = []
        tags = self.auto_tags.get("tags_topk") or []
        for t in tags:
            if not isinstance(t, dict):
                continue
            tag = t.get("tag")
            if not tag:
                continue
            # schema_version=2: confidence 기반, schema_version=1: score 기반
            conf = t.get("confidence")
            score = t.get("score")
            if conf is not None:
                label = f"{tag}  (confidence={conf})"
            else:
                label = f"{tag}  (score={score})"
            self.lst_tags.insert("end", label)
            self._tags_data.append(t)

        if self._tags_data:
            self.lst_tags.selection_set(0)
            self._show_tag_detail(0)

    def _render_chunks(self):
        self.lst_chunks.delete(0, "end")
        # chunk_index 순으로 정렬
        self.chunks.sort(key=lambda r: r.get("chunk_index", 0))
        for r in self.chunks:
            idx = r.get("chunk_index")
            st = r.get("start_offset")
            ed = r.get("end_offset")
            preview = (r.get("text") or "").replace("\n", " ")[:80]
            self.lst_chunks.insert("end", f"[{idx}] ({st}-{ed}) {preview}")

        if self.chunks:
            self.lst_chunks.selection_set(0)
            self._show_chunk(0)

    def _on_select_chunk(self, _evt):
        sel = self.lst_chunks.curselection()
        if not sel:
            return
        self._show_chunk(sel[0])

    def _show_chunk(self, index: int):
        if index < 0 or index >= len(self.chunks):
            return
        r = self.chunks[index]
        text = r.get("text") or ""
        self.txt_chunk.delete("1.0", "end")
        self.txt_chunk.insert("1.0", text)
        # 기본: evidence_hits가 있으면 하이라이트
        self._highlight_quotes([h.get("quote") for h in (r.get("evidence_hits") or []) if h.get("quote")])

    def _on_select_evidence(self, _evt):
        sel = self.lst_evd.curselection()
        if not sel:
            return
        q = self.lst_evd.get(sel[0]).strip()
        if not q:
            return
        # 현재 표시 중인 chunk에 q 하이라이트
        self._highlight_quotes([q])

    def _on_select_tag(self, _evt):
        sel = self.lst_tags.curselection()
        if not sel:
            return
        self._show_tag_detail(sel[0])

    def _show_tag_detail(self, index: int):
        if index < 0 or index >= len(self._tags_data):
            return
        t = self._tags_data[index]
        self.txt_tag_detail.delete("1.0", "end")
        self.txt_tag_detail.insert("1.0", self._format_tag_detail(t))

    def _format_tag_detail(self, t: dict) -> str:
        """
        태그별 계산 결과를 사람이 읽기 좋은 형태로 출력.
        - schema v1: BM25 기반 score/tf/df/genre_weight/from_topic/topic_relevance(있으면)
        - schema v2: 합의 기반 confidence + support_algorithms + scores(bm25/rake/yake) + evidence_spans
        """
        tag = t.get("tag", "")
        lines = [f"tag: {tag}"]

        # schema v2
        if "confidence" in t or "support_algorithms" in t:
            confidence = t.get("confidence")
            support_algs = t.get("support_algorithms") or []
            scores = t.get("scores") or {}
            support_count = t.get("support_count")

            if confidence is not None:
                lines.append(f"confidence: {confidence}")
            if support_count is not None:
                lines.append(f"support_count: {support_count}")
            if support_algs:
                lines.append(f"support_algorithms: {', '.join([str(a) for a in support_algs])}")

            # 개별 점수
            if scores:
                lines.append("")
                lines.append("[scores]")
                for k in ["bm25", "tfidf", "rake", "yake"]:
                    if k in scores:
                        lines.append(f"- {k}: {scores.get(k)}")
                # 그 외 점수도 표시
                for k, v in scores.items():
                    if k in ("bm25", "tfidf", "rake", "yake"):
                        continue
                    lines.append(f"- {k}: {v}")

            # 계산식(설명용): 현재 구현의 기본 합의식 가시화
            stat_score = scores.get("bm25") or scores.get("tfidf")
            if stat_score is not None:
                bonus = 0.0
                if "rake" in support_algs:
                    bonus += 0.3
                if "yake" in support_algs:
                    bonus += 0.3
                consensus_score = min(1.0, float(stat_score) + bonus)
                lines.append("")
                lines.append("[consensus formula (explain)]")
                lines.append(f"- bm25_score = {stat_score}")
                lines.append(f"- bonus = {bonus}  (rake:+0.3, yake:+0.3)")
                lines.append(f"- consensus_score = min(1.0, bm25_score + bonus) = {round(consensus_score, 4)}")
                if support_count is not None:
                    support_factor = {3: 1.0, 2: 0.85, 1: 0.6}.get(int(support_count), 0.6)
                    lines.append(f"- support_factor = {support_factor} (by support_count)")
                    lines.append(f"- confidence = consensus_score * support_factor = {round(consensus_score * support_factor, 4)}")

            # evidence_spans
            evs = t.get("evidence_spans") or []
            if evs:
                lines.append("")
                lines.append("[evidence_spans]")
                for ev in evs[:5]:
                    if isinstance(ev, dict):
                        ev_text = (ev.get("text") or "").strip().replace("\n", " ")
                        pos = ev.get("position")
                        alg = ev.get("algorithm")
                        lines.append(f"- pos={pos} alg={alg} text={ev_text[:160]}")
            return "\n".join(lines)

        # schema v1 (기존 BM25)
        score = t.get("score")
        tf = t.get("tf")
        df = t.get("df")
        genre_weight = t.get("genre_weight")
        from_topic = t.get("from_topic")
        topic_rel = t.get("topic_relevance")

        if score is not None:
            lines.append(f"score: {score}")
        if tf is not None:
            lines.append(f"tf: {tf}")
        if df is not None:
            lines.append(f"df: {df}")
        if genre_weight is not None:
            lines.append(f"genre_weight: {genre_weight}")
        if from_topic is not None:
            lines.append(f"from_topic: {from_topic}")
        if topic_rel is not None:
            lines.append(f"topic_relevance: {topic_rel}")

        lines.append("")
        lines.append("[tf-idf formula (explain)]")
        lines.append("- base_score = tf * (log((N+1)/(df+1)) + 1.0)")
        lines.append("- then apply genre/topic weights (if any)")
        lines.append("- finally normalized by max score to 0~1 (stored as score)")
        return "\n".join(lines)

    def _highlight_quotes(self, quotes):
        self.txt_chunk.tag_remove("hl", "1.0", "end")
        if not quotes:
            return
        content = self.txt_chunk.get("1.0", "end")
        low = content.lower()
        for q in quotes:
            if not q:
                continue
            qn = q.strip()
            if not qn:
                continue
            qlow = qn.lower()
            start = 0
            while True:
                pos = low.find(qlow, start)
                if pos < 0:
                    break
                # tkinter text index 계산
                idx_start = f"1.0+{pos}c"
                idx_end = f"1.0+{pos+len(qn)}c"
                self.txt_chunk.tag_add("hl", idx_start, idx_end)
                start = pos + len(qn)

    def _render_graphs(self):
        """그래프 시각화 렌더링"""
        if not MATPLOTLIB_AVAILABLE:
            return
        
        # 1. 문서 분류 분포
        self._render_genre_distribution()
        
        # 2. 태그 분포
        self._render_tag_distribution()
        
        # 3. 신뢰도 보정 전후 비교
        self._render_confidence_adjustment()

    def _render_genre_distribution(self):
        """문서 분류(장르) 분포 그래프"""
        # 기존 그래프 제거
        for widget in self.tab_genre.winfo_children():
            widget.destroy()
        
        # 장르별 청크 수 집계
        genre_counts = Counter()
        for chunk in self.chunks:
            genre = chunk.get("genre") or "unknown"
            genre_counts[genre] += 1
        
        if not genre_counts:
            ttk.Label(self.tab_genre, text="장르 데이터 없음", foreground="gray").pack()
            return
        
        # 막대 그래프 생성
        fig = Figure(figsize=(6, 4), dpi=100)
        ax = fig.add_subplot(111)
        
        genres = list(genre_counts.keys())
        counts = list(genre_counts.values())
        
        bars = ax.bar(genres, counts, color='steelblue', alpha=0.7)
        ax.set_xlabel('장르 (Genre)', fontsize=10)
        ax.set_ylabel('청크 수', fontsize=10)
        ax.set_title('문서 분류 분포', fontsize=12, fontweight='bold')
        ax.tick_params(axis='x', rotation=45)
        
        # 값 표시
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{int(height)}', ha='center', va='bottom', fontsize=9)
        
        fig.tight_layout()
        
        canvas = FigureCanvasTkAgg(fig, self.tab_genre)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def _render_tag_distribution(self):
        """태그 분포 그래프"""
        # 기존 그래프 제거
        for widget in self.tab_tags.winfo_children():
            widget.destroy()
        
        tags = self.auto_tags.get("tags_topk") or []
        if not tags:
            ttk.Label(self.tab_tags, text="태그 데이터 없음", foreground="gray").pack()
            return
        
        # 태그별 신뢰도/점수 추출
        tag_names = []
        tag_scores = []
        
        for tag_item in tags[:15]:  # 상위 15개만
            if isinstance(tag_item, dict):
                tag = tag_item.get("tag", "")
                # confidence 또는 score 사용
                score = tag_item.get("confidence") or tag_item.get("score", 0.0)
                if tag:
                    tag_names.append(tag.replace("_", "\n"))  # 줄바꿈으로 가독성 향상
                    tag_scores.append(float(score))
        
        if not tag_names:
            ttk.Label(self.tab_tags, text="태그 데이터 없음", foreground="gray").pack()
            return
        
        # 막대 그래프 생성
        fig = Figure(figsize=(8, 5), dpi=100)
        ax = fig.add_subplot(111)
        
        bars = ax.barh(range(len(tag_names)), tag_scores, color='coral', alpha=0.7)
        ax.set_yticks(range(len(tag_names)))
        ax.set_yticklabels(tag_names, fontsize=9)
        ax.set_xlabel('신뢰도/점수', fontsize=10)
        ax.set_title('태그 분포 (상위 15개)', fontsize=12, fontweight='bold')
        ax.set_xlim(0, 1.0)
        
        # 값 표시
        for i, (bar, score) in enumerate(zip(bars, tag_scores)):
            width = bar.get_width()
            ax.text(width, bar.get_y() + bar.get_height()/2.,
                   f'{score:.3f}', ha='left', va='center', fontsize=8)
        
        fig.tight_layout()
        
        canvas = FigureCanvasTkAgg(fig, self.tab_tags)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def _render_confidence_adjustment(self):
        """신뢰도 보정 전후 비교 그래프"""
        # 기존 그래프 제거
        for widget in self.tab_confidence.winfo_children():
            widget.destroy()
        
        tags = self.auto_tags.get("tags_topk") or []
        if not tags:
            ttk.Label(self.tab_confidence, text="태그 데이터 없음", foreground="gray").pack()
            return
        
        # 보정 전후 데이터 추출
        original_scores = []
        adjusted_scores = []
        semantic_scores = []
        tag_names = []
        
        for tag_item in tags[:12]:  # 상위 12개만
            if isinstance(tag_item, dict):
                tag = tag_item.get("tag", "")
                if not tag:
                    continue
                
                # 보정 전 신뢰도
                orig = tag_item.get("confidence_original") or tag_item.get("confidence") or tag_item.get("score", 0.0)
                # 보정 후 신뢰도
                adj = tag_item.get("confidence_adjusted") or tag_item.get("confidence", 0.0)
                # 의미 점수
                sem = tag_item.get("semantic_score", 0.0)
                
                tag_names.append(tag.replace("_", "\n"))
                original_scores.append(float(orig))
                adjusted_scores.append(float(adj))
                semantic_scores.append(float(sem))
        
        if not tag_names:
            ttk.Label(self.tab_confidence, text="보정 데이터 없음 (의미 기반 보정 미적용)", foreground="gray").pack()
            return
        
        # 비교 그래프 생성
        fig = Figure(figsize=(8, 6), dpi=100)
        ax = fig.add_subplot(111)
        
        x = range(len(tag_names))
        width = 0.25
        
        # 막대 그래프
        bars1 = ax.bar([i - width for i in x], original_scores, width, 
                       label='보정 전', color='lightblue', alpha=0.7)
        bars2 = ax.bar(x, adjusted_scores, width, 
                       label='보정 후', color='steelblue', alpha=0.7)
        bars3 = ax.bar([i + width for i in x], semantic_scores, width, 
                       label='의미 점수', color='coral', alpha=0.7)
        
        ax.set_xlabel('태그', fontsize=10)
        ax.set_ylabel('점수', fontsize=10)
        ax.set_title('신뢰도 보정 전후 비교', fontsize=12, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(tag_names, fontsize=8, rotation=45, ha='right')
        ax.set_ylim(0, 1.0)
        ax.legend(fontsize=9)
        ax.grid(axis='y', alpha=0.3)
        
        fig.tight_layout()
        
        canvas = FigureCanvasTkAgg(fig, self.tab_confidence)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)


def open_analysis_window(master, out_root: str, doc_id: str):
    out = Path(out_root)
    doc_dir = out / doc_id
    if not doc_dir.exists():
        messagebox.showwarning("없음", "해당 doc_id 디렉터리가 없습니다.")
        return

    # report/chunks 없으면 안내
    rep = doc_dir / "analysis_report.json"
    if not rep.exists():
        messagebox.showwarning("분석 결과 없음", "analysis_report.json이 없습니다. 문서를 한 번 처리(인제스트)해주세요.")
        # 그래도 창은 열어줌(사용자가 상황 확인 가능)
    AnalysisWindow(master, out_root, doc_id)
