"""
문서 분류 대시보드 UI
- 장르별 분류 통계
- 주제별 그룹핑
- 문서 종류별 시각화
"""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Optional, Any
from collections import Counter, defaultdict
from datetime import datetime

# 그래프 시각화를 위한 선택적 import
try:
    import matplotlib
    matplotlib.use('TkAgg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    
    # 한글 폰트 설정
    import platform
    system = platform.system()
    if system == 'Windows':
        font_name = 'Malgun Gothic'
    elif system == 'Darwin':
        font_name = 'AppleGothic'
    else:
        font_name = 'NanumGothic'
    
    plt.rcParams['font.family'] = font_name
    plt.rcParams['axes.unicode_minus'] = False
    
    try:
        font_prop = fm.FontProperties(family=font_name)
    except:
        font_prop = None
    
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
except Exception as e:
    print(f"[분류대시보드] matplotlib 설정 실패: {e}")
    MATPLOTLIB_AVAILABLE = True

from auto_tagging import load_auto_tags
from category_manager import (
    load_categories,
    add_category,
    save_manual_category,
    load_manual_category,
    genre_to_category,
)
try:
    from category_classifier import run_kmeans_classification
    KMEANS_AVAILABLE = True
except ImportError:
    KMEANS_AVAILABLE = False


# 장르 한글명 매핑
GENRE_NAMES = {
    "issue": "이슈/문제",
    "resolution": "해결책",
    "procedure": "절차/가이드",
    "report": "보고서",
    "policy": "정책",
    "communication": "의사소통",
    "plan": "계획",
    "contract": "계약/제안",
    "reference": "참고자료",
    "application": "신청서",
    "form": "양식",
    "maintenance": "유지보수",
    "guide": "가이드",
    "record": "기록",
    "unknown": "미분류"
}


def _read_json(path: Path) -> Optional[dict]:
    """JSON 파일 읽기"""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def _read_jsonl(path: Path) -> List[dict]:
    """JSONL 파일 읽기"""
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


class ClassificationDashboardWindow(tk.Toplevel):
    """문서 분류 대시보드 창"""
    
    def __init__(self, master, out_root: str):
        super().__init__(master)
        self.title("문서 분류 대시보드")
        self.geometry("1400x900")
        self.out_root = Path(out_root)
        self.all_docs = []
        self.genre_stats = {}
        self.topic_groups = defaultdict(list)
        
        self.transient(master)
        self._load_all_documents()
        self._build_ui()
        self._update_dashboard()
    
    def _load_all_documents(self):
        """모든 문서의 분류 정보 로드"""
        self.all_docs = []
        
        # workspace_payload.jsonl에서 모든 문서 정보 가져오기
        payload_path = self.out_root / "workspace_payload.jsonl"
        if not payload_path.exists():
            print(f"[분류대시보드] workspace_payload.jsonl 파일이 없습니다: {payload_path}")
            return
        
        payloads = _read_jsonl(payload_path)
        print(f"[분류대시보드] 로드된 문서 수: {len(payloads)}개")
        
        for payload in payloads:
            doc_id = payload.get("doc_id")
            if not doc_id:
                continue
            
            # auto_tags.json 로드
            auto_tags = load_auto_tags(str(self.out_root), doc_id) or {}
            
            genre = auto_tags.get("genre", "unknown")
            topic_sentence = auto_tags.get("topic_sentence")
            genre_confidence = auto_tags.get("genre_confidence", 0.0)
            
            manual_cat = load_manual_category(str(self.out_root), doc_id)
            try:
                from category_manager import load_auto_category
                auto_cat = load_auto_category(str(self.out_root), doc_id)
            except ImportError:
                auto_cat = None
            category = manual_cat or auto_cat or genre_to_category(genre)
            
            doc_info = {
                "doc_id": doc_id,
                "title": payload.get("title", ""),
                "genre": genre,
                "category": category,
                "manual_category": manual_cat,
                "genre_confidence": genre_confidence,
                "topic_sentence": topic_sentence,
                "language": auto_tags.get("language", "unknown"),
                "tags_count": len(auto_tags.get("tags_topk", [])),
                "source_path": payload.get("source_path", ""),
                "processed_at": auto_tags.get("generated_at", "")
            }
            
            self.all_docs.append(doc_info)
            
            # 주제별 그룹핑 (주제문장이 있는 경우)
            if topic_sentence and topic_sentence.strip():
                # 주제문장의 첫 50자를 키로 사용
                topic_key = topic_sentence.strip()[:50]
                self.topic_groups[topic_key].append(doc_info)
        
        # 장르별 통계 계산
        genre_counter = Counter([doc["genre"] for doc in self.all_docs])
        self.genre_stats = dict(genre_counter)
        
        print(f"[분류대시보드] 장르별 통계: {self.genre_stats}")
        print(f"[분류대시보드] 주제 그룹 수: {len(self.topic_groups)}개")
    
    def _build_ui(self):
        """UI 구성"""
        # 메인 프레임
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 상단: 요약 통계
        summary_frame = ttk.LabelFrame(main_frame, text="전체 통계", padding=10)
        summary_frame.pack(fill="x", pady=(0, 10))
        
        stats_row = ttk.Frame(summary_frame)
        stats_row.pack(fill="x")
        
        self.lbl_total = ttk.Label(stats_row, text="", font=("Malgun Gothic", 10))
        self.lbl_total.pack(side="left", padx=20)
        
        self.lbl_genres = ttk.Label(stats_row, text="", font=("Malgun Gothic", 10))
        self.lbl_genres.pack(side="left", padx=20)
        
        self.lbl_topics = ttk.Label(stats_row, text="", font=("Malgun Gothic", 10))
        self.lbl_topics.pack(side="left", padx=20)
        
        # 본문: 좌(차트) + 우(문서 목록)
        body_frame = ttk.Frame(main_frame)
        body_frame.pack(fill="both", expand=True)
        
        # 좌측: 차트 영역
        left_frame = ttk.Frame(body_frame, width=700)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        # 차트 탭
        chart_notebook = ttk.Notebook(left_frame)
        chart_notebook.pack(fill="both", expand=True)
        
        # 탭 1: 장르별 분포
        genre_frame = ttk.Frame(chart_notebook)
        chart_notebook.add(genre_frame, text="장르별 분포")
        self.genre_chart_frame = ttk.Frame(genre_frame)
        self.genre_chart_frame.pack(fill="both", expand=True)
        
        # 탭 2: 장르별 신뢰도
        confidence_frame = ttk.Frame(chart_notebook)
        chart_notebook.add(confidence_frame, text="장르별 신뢰도")
        self.confidence_chart_frame = ttk.Frame(confidence_frame)
        self.confidence_chart_frame.pack(fill="both", expand=True)
        
        # 탭 3: 주제별 그룹
        topic_frame = ttk.Frame(chart_notebook)
        chart_notebook.add(topic_frame, text="주제별 그룹")
        self.topic_chart_frame = ttk.Frame(topic_frame)
        self.topic_chart_frame.pack(fill="both", expand=True)
        
        # 우측: 문서 목록
        right_frame = ttk.LabelFrame(body_frame, text="문서 목록", padding=10, width=600)
        right_frame.pack(side="right", fill="both", expand=False)
        right_frame.pack_propagate(False)  # 고정 크기 유지
        
        # 카테고리 관리 버튼
        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(fill="x", pady=(0, 5))
        ttk.Button(btn_frame, text="카테고리 추가", command=self._add_category_dialog).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="인덱스 갱신", command=self._rebuild_index).pack(side="left", padx=2)
        if KMEANS_AVAILABLE:
            ttk.Button(btn_frame, text="K-means 자동 분류", command=self._run_kmeans).pack(side="left", padx=2)
        
        # 필터 영역
        filter_frame = ttk.Frame(right_frame)
        filter_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(filter_frame, text="장르 필터:", width=10).pack(side="left", padx=(0, 5))
        self.genre_filter_var = tk.StringVar(value="전체")
        genre_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.genre_filter_var,
            values=["전체"] + list(GENRE_NAMES.keys()),
            state="readonly",
            width=15
        )
        genre_combo.pack(side="left", padx=5)
        genre_combo.bind("<<ComboboxSelected>>", lambda e: self._filter_documents())
        
        ttk.Label(filter_frame, text="카테고리:", width=10).pack(side="left", padx=(10, 5))
        self.category_filter_var = tk.StringVar(value="전체")
        self.category_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.category_filter_var,
            values=["전체"] + load_categories(str(self.out_root)),
            state="readonly",
            width=15
        )
        self.category_combo.pack(side="left", padx=5)
        self.category_combo.bind("<<ComboboxSelected>>", lambda e: self._filter_documents())
        
        ttk.Label(filter_frame, text="주제 필터:", width=10).pack(side="left", padx=(10, 5))
        self.topic_filter_var = tk.StringVar()
        topic_entry = ttk.Entry(filter_frame, textvariable=self.topic_filter_var, width=20)
        topic_entry.pack(side="left", padx=5)
        topic_entry.bind("<KeyRelease>", lambda e: self._filter_documents())
        
        # 문서 목록 트리뷰
        list_frame = ttk.Frame(right_frame)
        list_frame.pack(fill="both", expand=True)
        
        columns = ("제목", "장르", "카테고리", "신뢰도", "주제", "태그수")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=25)
        
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=80)
        
        self.tree.column("제목", width=180)
        self.tree.column("장르", width=80)
        self.tree.column("카테고리", width=90)
        self.tree.column("신뢰도", width=60)
        self.tree.column("주제", width=120)
        self.tree.column("태그수", width=50)
        
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.tree.bind("<Double-1>", self._on_document_double_click)
        
        # 우클릭 메뉴: 카테고리 변경
        self.tree.bind("<Button-3>", self._on_tree_right_click)
    
    def _update_dashboard(self):
        """대시보드 업데이트"""
        # 통계 업데이트
        total = len(self.all_docs)
        genre_count = len(self.genre_stats)
        topic_count = len(self.topic_groups)
        
        self.lbl_total.config(text=f"전체 문서: {total}개")
        self.lbl_genres.config(text=f"장르 종류: {genre_count}개")
        self.lbl_topics.config(text=f"주제 그룹: {topic_count}개")
        
        # 차트 업데이트
        if MATPLOTLIB_AVAILABLE:
            self._render_genre_distribution()
            self._render_genre_confidence()
            self._render_topic_groups()
        
        # 문서 목록 업데이트
        self._filter_documents()
    
    def _render_genre_distribution(self):
        """장르별 분포 차트"""
        # 기존 차트 제거
        for widget in self.genre_chart_frame.winfo_children():
            widget.destroy()
        
        if not self.genre_stats:
            ttk.Label(self.genre_chart_frame, text="데이터가 없습니다.").pack()
            return
        
        # 데이터 준비
        genres = list(self.genre_stats.keys())
        counts = list(self.genre_stats.values())
        genre_names_ko = [GENRE_NAMES.get(g, g) for g in genres]
        
        # 차트 생성
        fig = Figure(figsize=(8, 6), dpi=100)
        ax = fig.add_subplot(111)
        
        # 막대 그래프
        bars = ax.bar(genre_names_ko, counts, color='steelblue', alpha=0.7)
        
        # 값 표시
        for bar, count in zip(bars, counts):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{count}',
                   ha='center', va='bottom', fontproperties=font_prop)
        
        ax.set_xlabel('장르', fontproperties=font_prop)
        ax.set_ylabel('문서 수', fontproperties=font_prop)
        ax.set_title('장르별 문서 분포', fontproperties=font_prop, fontsize=14, fontweight='bold')
        ax.set_xticklabels(genre_names_ko, fontproperties=font_prop, rotation=45, ha='right')
        
        fig.tight_layout()
        
        canvas = FigureCanvasTkAgg(fig, self.genre_chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
    
    def _render_genre_confidence(self):
        """장르별 평균 신뢰도 차트"""
        # 기존 차트 제거
        for widget in self.confidence_chart_frame.winfo_children():
            widget.destroy()
        
        if not self.all_docs:
            ttk.Label(self.confidence_chart_frame, text="데이터가 없습니다.").pack()
            return
        
        # 장르별 평균 신뢰도 계산
        genre_confidences = defaultdict(list)
        for doc in self.all_docs:
            genre = doc["genre"]
            confidence = doc["genre_confidence"]
            genre_confidences[genre].append(confidence)
        
        genres = list(genre_confidences.keys())
        avg_confidences = [sum(genre_confidences[g]) / len(genre_confidences[g]) for g in genres]
        genre_names_ko = [GENRE_NAMES.get(g, g) for g in genres]
        
        # 차트 생성
        fig = Figure(figsize=(8, 6), dpi=100)
        ax = fig.add_subplot(111)
        
        bars = ax.bar(genre_names_ko, avg_confidences, color='coral', alpha=0.7)
        
        # 값 표시
        for bar, conf in zip(bars, avg_confidences):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{conf:.2f}',
                   ha='center', va='bottom', fontproperties=font_prop)
        
        ax.set_xlabel('장르', fontproperties=font_prop)
        ax.set_ylabel('평균 신뢰도', fontproperties=font_prop)
        ax.set_title('장르별 평균 분류 신뢰도', fontproperties=font_prop, fontsize=14, fontweight='bold')
        ax.set_ylim(0, 1.0)
        ax.set_xticklabels(genre_names_ko, fontproperties=font_prop, rotation=45, ha='right')
        
        fig.tight_layout()
        
        canvas = FigureCanvasTkAgg(fig, self.confidence_chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
    
    def _render_topic_groups(self):
        """주제별 그룹 차트"""
        # 기존 차트 제거
        for widget in self.topic_chart_frame.winfo_children():
            widget.destroy()
        
        if not self.topic_groups:
            ttk.Label(self.topic_chart_frame, text="주제문장이 있는 문서가 없습니다.").pack()
            return
        
        # 주제별 문서 수 계산
        topic_counts = {topic: len(docs) for topic, docs in self.topic_groups.items()}
        
        # 상위 10개만 표시
        sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        topics = [t[:30] + "..." if len(t) > 30 else t for t, _ in sorted_topics]
        counts = [c for _, c in sorted_topics]
        
        # 차트 생성
        fig = Figure(figsize=(8, 6), dpi=100)
        ax = fig.add_subplot(111)
        
        bars = ax.barh(topics, counts, color='lightgreen', alpha=0.7)
        
        # 값 표시
        for bar, count in zip(bars, counts):
            width = bar.get_width()
            ax.text(width, bar.get_y() + bar.get_height()/2.,
                   f' {count}',
                   ha='left', va='center', fontproperties=font_prop)
        
        ax.set_xlabel('문서 수', fontproperties=font_prop)
        ax.set_ylabel('주제', fontproperties=font_prop)
        ax.set_title('주제별 문서 그룹 (상위 10개)', fontproperties=font_prop, fontsize=14, fontweight='bold')
        ax.set_yticklabels(topics, fontproperties=font_prop)
        
        fig.tight_layout()
        
        canvas = FigureCanvasTkAgg(fig, self.topic_chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
    
    def _update_category_combo(self):
        """카테고리 콤보박스 값 갱신"""
        try:
            if hasattr(self, "category_combo") and self.category_combo.winfo_exists():
                self.category_combo["values"] = ["전체"] + load_categories(str(self.out_root))
        except Exception:
            pass
    
    def _filter_documents(self):
        """문서 목록 필터링"""
        # 기존 항목 제거
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # 필터 적용
        genre_filter = self.genre_filter_var.get()
        category_filter = getattr(self, "category_filter_var", None)
        cat_val = category_filter.get() if category_filter else "전체"
        topic_filter = self.topic_filter_var.get().lower()
        
        filtered_docs = self.all_docs
        
        if genre_filter != "전체":
            filtered_docs = [doc for doc in filtered_docs if doc["genre"] == genre_filter]
        
        if cat_val != "전체":
            filtered_docs = [doc for doc in filtered_docs if doc.get("category") == cat_val]
        
        if topic_filter:
            filtered_docs = [
                doc for doc in filtered_docs
                if topic_filter in (doc.get("topic_sentence") or "").lower()
            ]
        
        # 정렬 (최신순)
        filtered_docs.sort(key=lambda x: x.get("processed_at", ""), reverse=True)
        
        # 트리뷰에 추가
        for doc in filtered_docs:
            genre_name = GENRE_NAMES.get(doc["genre"], doc["genre"])
            category = doc.get("category", "-")
            topic = doc.get("topic_sentence", "") or "-"
            if len(topic) > 30:
                topic = topic[:30] + "..."
            
            self.tree.insert(
                "",
                "end",
                values=(
                    doc["title"][:40] + "..." if len(doc["title"]) > 40 else doc["title"],
                    genre_name,
                    category,
                    f"{doc['genre_confidence']:.2f}",
                    topic,
                    doc["tags_count"]
                ),
                tags=(doc["doc_id"],)
            )
    
    def _on_document_double_click(self, event):
        """문서 더블클릭 시 카테고리 변경 대화상자"""
        self._show_change_category_dialog()
    
    def _on_tree_right_click(self, event):
        """우클릭 시 컨텍스트 메뉴"""
        selection = self.tree.selection()
        if not selection:
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="카테고리 변경", command=self._show_change_category_dialog)
        menu.add_command(label="문서 상세 보기", command=lambda: self._open_analysis(selection[0]))
        menu.post(event.x_root, event.y_root)
    
    def _open_analysis(self, item_id):
        """문서 상세 보기"""
        item = self.tree.item(item_id)
        doc_id = item["tags"][0] if item["tags"] else None
        if doc_id:
            try:
                from analysis_viewer import open_analysis_window
                open_analysis_window(self.master, str(self.out_root), doc_id)
            except Exception as e:
                messagebox.showerror("오류", f"문서 상세 정보를 열 수 없습니다:\n{e}")
    
    def _show_change_category_dialog(self):
        """선택 문서의 카테고리 변경 대화상자"""
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("안내", "문서를 선택하세요.")
            return
        item = self.tree.item(selection[0])
        doc_id = item["tags"][0] if item["tags"] else None
        if not doc_id:
            return
        doc = next((d for d in self.all_docs if d["doc_id"] == doc_id), None)
        if not doc:
            return
        
        categories = load_categories(str(self.out_root))
        current = doc.get("category", "기타")
        
        dialog = tk.Toplevel(self)
        dialog.title("카테고리 변경")
        dialog.transient(self)
        dialog.geometry("320x120")
        
        ttk.Label(dialog, text=f"문서: {doc['title'][:50]}...").pack(pady=(10, 5))
        ttk.Label(dialog, text="카테고리:").pack(anchor="w", padx=20)
        var = tk.StringVar(value=current)
        combo = ttk.Combobox(dialog, textvariable=var, values=categories, state="readonly", width=35)
        combo.pack(padx=20, pady=5)
        
        def ok():
            new_cat = var.get().strip()
            if new_cat and new_cat in categories:
                try:
                    save_manual_category(str(self.out_root), doc_id, new_cat)
                    doc["manual_category"] = new_cat
                    doc["category"] = new_cat
                    messagebox.showinfo("완료", "카테고리가 저장되었습니다.\n인덱스 갱신 버튼을 눌러 검색에 반영하세요.")
                    self._filter_documents()
                except Exception as e:
                    messagebox.showerror("오류", str(e))
            dialog.destroy()
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="저장", command=ok).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="취소", command=dialog.destroy).pack(side="left", padx=5)
    
    def _add_category_dialog(self):
        """새 카테고리 추가 대화상자"""
        dialog = tk.Toplevel(self)
        dialog.title("카테고리 추가")
        dialog.transient(self)
        dialog.geometry("320x100")
        
        ttk.Label(dialog, text="새 카테고리 이름:").pack(anchor="w", padx=20, pady=(10, 5))
        entry = ttk.Entry(dialog, width=35)
        entry.pack(padx=20, pady=5)
        entry.focus()
        
        def ok():
            name = entry.get().strip()
            if not name:
                messagebox.showwarning("경고", "카테고리 이름을 입력하세요.")
                return
            try:
                if add_category(str(self.out_root), name):
                    messagebox.showinfo("완료", f"카테고리 '{name}'가 추가되었습니다.")
                    self._update_category_combo()
                    self._filter_documents()
                else:
                    messagebox.showwarning("경고", f"'{name}'는 이미 존재하거나 유효하지 않습니다.")
            except Exception as e:
                messagebox.showerror("오류", str(e))
            dialog.destroy()
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="추가", command=ok).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="취소", command=dialog.destroy).pack(side="left", padx=5)
        entry.bind("<Return>", lambda e: ok())
    
    def _rebuild_index(self):
        """검색 인덱스 강제 재구축 (카테고리 반영)"""
        try:
            from document_search import build_tag_index
            build_tag_index(str(self.out_root), force_rebuild=True)
            messagebox.showinfo("완료", "인덱스가 갱신되었습니다.")
            self._load_all_documents()
            self._update_dashboard()
        except Exception as e:
            messagebox.showerror("오류", f"인덱스 갱신 실패:\n{e}")
    
    def _run_kmeans(self):
        """K-means 자동 분류 실행"""
        if not KMEANS_AVAILABLE:
            messagebox.showwarning("경고", "category_classifier 모듈을 사용할 수 없습니다.\nsklearn, sentence-transformers를 설치하세요.")
            return
        try:
            result = run_kmeans_classification(str(self.out_root), use_manual_as_seed=True)
            if result["success"]:
                msg = f"K-means 자동 분류 완료.\n{result['updated_count']}개 문서에 auto_category가 설정되었습니다.\n인덱스 갱신 버튼을 눌러 검색에 반영하세요."
                messagebox.showinfo("완료", msg)
                self._load_all_documents()
                self._update_dashboard()
            else:
                messagebox.showerror("오류", result.get("error", "알 수 없는 오류"))
        except Exception as e:
            messagebox.showerror("오류", f"K-means 분류 실패:\n{e}")


def open_classification_dashboard(master, out_root: str):
    """분류 대시보드 창 열기"""
    try:
        ClassificationDashboardWindow(master, out_root)
    except Exception as e:
        messagebox.showerror("오류", f"분류 대시보드를 열 수 없습니다:\n{e}")
