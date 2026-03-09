"""
태깅 결과 시각화 UI
문서별 자동 태깅 결과를 표로 보여주는 뷰어
"""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Optional, Any
from datetime import datetime
from collections import Counter

# 그래프 시각화를 위한 선택적 import
try:
    import matplotlib
    matplotlib.use('TkAgg')  # tkinter와 호환
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    
    # 한글 폰트 설정
    # Windows: Malgun Gothic, macOS: AppleGothic, Linux: NanumGothic
    import platform
    system = platform.system()
    if system == 'Windows':
        font_name = 'Malgun Gothic'
    elif system == 'Darwin':  # macOS
        font_name = 'AppleGothic'
    else:  # Linux
        font_name = 'NanumGothic'
    
    # 폰트 설정
    plt.rcParams['font.family'] = font_name
    plt.rcParams['axes.unicode_minus'] = False  # 마이너스 기호 깨짐 방지
    
    # 폰트 속성 저장 (ax.text()에서 사용)
    try:
        font_prop = fm.FontProperties(family=font_name)
    except:
        font_prop = None
    
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
except Exception as e:
    print(f"[태깅뷰어] matplotlib 폰트 설정 실패: {e}")
    MATPLOTLIB_AVAILABLE = True  # matplotlib은 있지만 폰트 설정 실패

from auto_tagging import load_auto_tags


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


class TaggingViewerWindow(tk.Toplevel):
    """태깅 결과 뷰어 메인 창"""
    
    def __init__(self, master, out_root: str):
        super().__init__(master)
        self.title("태깅 결과 보기")
        self.geometry("1200x700")
        self.out_root = Path(out_root)
        self.all_docs = []
        self.filtered_docs = []
        
        self.transient(master)
        self._load_all_documents()
        self._build_ui()
        self._refresh_table()
    
    def _load_all_documents(self):
        """모든 문서의 태깅 정보 로드"""
        self.all_docs = []
        
        # workspace_payload.jsonl에서 모든 문서 정보 가져오기
        payload_path = self.out_root / "workspace_payload.jsonl"
        if not payload_path.exists():
            print(f"[태깅뷰어] workspace_payload.jsonl 파일이 없습니다: {payload_path}")
            return
        
        payloads = _read_jsonl(payload_path)
        print(f"[태깅뷰어] 로드된 문서 수: {len(payloads)}개")
        
        no_tagging_count = 0
        for payload in payloads:
            doc_id = payload.get("doc_id")
            if not doc_id:
                continue
            
            # auto_tags.json 로드
            auto_tags = load_auto_tags(str(self.out_root), doc_id) or {}
            
            if not auto_tags:
                no_tagging_count += 1
                # 태깅 정보가 없어도 문서는 표시 (태깅 실패 표시용)
                doc_info = {
                    "doc_id": doc_id,
                    "title": payload.get("title", doc_id[:16]),
                    "language": "unknown",
                    "genre": "unknown",
                    "genre_confidence": 0.0,
                    "topic_sentence": None,
                    "tags_count": 0,
                    "generated_at": "",
                    "schema_version": 1,
                    "auto_tags": {},
                    "payload": payload,
                    "tagging_failed": True
                }
                self.all_docs.append(doc_info)
                continue
            
            doc_info = {
                "doc_id": doc_id,
                "title": payload.get("title", doc_id[:16]),
                "language": auto_tags.get("language", "unknown"),
                "genre": auto_tags.get("genre", "unknown"),
                "genre_confidence": auto_tags.get("genre_confidence", 0.0),
                "topic_sentence": auto_tags.get("topic_sentence"),
                "tags_count": len(auto_tags.get("tags_topk", [])),
                "generated_at": auto_tags.get("generated_at", ""),
                "schema_version": auto_tags.get("schema_version", 1),
                "auto_tags": auto_tags,
                "payload": payload,
                "tagging_failed": False
            }
            self.all_docs.append(doc_info)
        
        if no_tagging_count > 0:
            print(f"[태깅뷰어] 태깅 정보가 없는 문서: {no_tagging_count}개")
        
        print(f"[태깅뷰어] 총 로드된 문서: {len(self.all_docs)}개")
        
        # 처리 시간 기준 정렬 (최신순)
        self.all_docs.sort(key=lambda x: x.get("generated_at", ""), reverse=True)
        self.filtered_docs = self.all_docs.copy()
    
    def _build_ui(self):
        """UI 구성"""
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 필터 영역
        filter_frame = ttk.LabelFrame(root, text="필터", padding=10)
        filter_frame.pack(fill="x", pady=(0, 10))
        
        filter_row1 = ttk.Frame(filter_frame)
        filter_row1.pack(fill="x", pady=4)
        
        ttk.Label(filter_row1, text="장르:", width=8, anchor="w").pack(side="left")
        self.genre_var = tk.StringVar(value="")
        genre_combo = ttk.Combobox(
            filter_row1,
            textvariable=self.genre_var,
            values=[""] + sorted(set(d.get("genre", "unknown") for d in self.all_docs)),
            width=20,
            state="readonly",
            font=("Malgun Gothic", 9)
        )
        genre_combo.pack(side="left", padx=5)
        genre_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filters())
        
        ttk.Label(filter_row1, text="언어:", width=8, anchor="w").pack(side="left", padx=(20, 0))
        self.language_var = tk.StringVar(value="")
        language_combo = ttk.Combobox(
            filter_row1,
            textvariable=self.language_var,
            values=[""] + sorted(set(d.get("language", "unknown") for d in self.all_docs)),
            width=15,
            state="readonly",
            font=("Malgun Gothic", 9)
        )
        language_combo.pack(side="left", padx=5)
        language_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filters())
        
        ttk.Label(filter_row1, text="주제문장:", width=10, anchor="w").pack(side="left", padx=(20, 0))
        self.topic_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filter_row1,
            text="주제문장이 있는 문서만",
            variable=self.topic_only_var,
            command=self._apply_filters
        ).pack(side="left", padx=5)
        
        filter_row2 = ttk.Frame(filter_frame)
        filter_row2.pack(fill="x", pady=4)
        
        ttk.Label(filter_row2, text="태그 검색:", width=10, anchor="w").pack(side="left")
        self.tag_search_var = tk.StringVar()
        self.tag_search_var.trace("w", lambda *args: self._apply_filters())
        tag_search_entry = ttk.Entry(filter_row2, textvariable=self.tag_search_var, width=30, font=("Malgun Gothic", 9))
        tag_search_entry.pack(side="left", padx=5)
        
        ttk.Label(filter_row2, text="정렬:", width=6, anchor="w").pack(side="left", padx=(20, 0))
        self.sort_var = tk.StringVar(value="시간_최신순")
        sort_combo = ttk.Combobox(
            filter_row2,
            textvariable=self.sort_var,
            values=["시간_최신순", "시간_오래된순", "태그수_많은순", "태그수_적은순", "신뢰도_높은순", "신뢰도_낮은순", "제목_가나다순"],
            width=15,
            state="readonly",
            font=("Malgun Gothic", 9)
        )
        sort_combo.pack(side="left", padx=5)
        sort_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_sort())
        
        filter_row3 = ttk.Frame(filter_frame)
        filter_row3.pack(fill="x", pady=4)
        
        ttk.Label(filter_row3, text="문서 수:", width=8, anchor="w").pack(side="left")
        self.status_label = ttk.Label(filter_row3, text=f"전체 {len(self.all_docs)}개", font=("Malgun Gothic", 9))
        self.status_label.pack(side="left", padx=5)
        
        ttk.Button(filter_row3, text="새로고침", command=self._refresh_data, width=10).pack(side="right")
        
        # 문서 목록 테이블
        list_frame = ttk.LabelFrame(root, text="문서 목록", padding=10)
        list_frame.pack(fill="both", expand=True)
        
        # Treeview 생성
        columns = ("제목", "장르", "신뢰도", "태그수", "언어", "시간", "주제문장")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=20)
        
        # 컬럼 설정
        self.tree.heading("제목", text="문서 제목")
        self.tree.heading("장르", text="장르")
        self.tree.heading("신뢰도", text="장르 신뢰도")
        self.tree.heading("태그수", text="태그 수")
        self.tree.heading("언어", text="언어")
        self.tree.heading("시간", text="처리 시간")
        self.tree.heading("주제문장", text="주제문장")
        
        self.tree.column("제목", width=250)
        self.tree.column("장르", width=100, anchor="center")
        self.tree.column("신뢰도", width=80, anchor="center")
        self.tree.column("태그수", width=70, anchor="center")
        self.tree.column("언어", width=60, anchor="center")
        self.tree.column("시간", width=150)
        self.tree.column("주제문장", width=200)
        
        # 스크롤바
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 더블클릭 시 상세 보기
        self.tree.bind("<Double-1>", lambda e: self._open_detail())
        
        # 버튼 영역
        btn_frame = ttk.Frame(root)
        btn_frame.pack(fill="x", pady=(10, 0))
        
        ttk.Button(btn_frame, text="상세 보기", command=self._open_detail, width=12).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="닫기", command=self.destroy, width=12).pack(side="right", padx=5)
    
    def _apply_filters(self):
        """필터 적용"""
        genre_filter = self.genre_var.get()
        language_filter = self.language_var.get()
        topic_only = self.topic_only_var.get()
        tag_search = self.tag_search_var.get().strip().lower()
        
        self.filtered_docs = []
        for doc in self.all_docs:
            # 장르 필터
            if genre_filter and doc.get("genre") != genre_filter:
                continue
            
            # 언어 필터
            if language_filter and doc.get("language") != language_filter:
                continue
            
            # 주제문장 필터
            if topic_only and not doc.get("topic_sentence"):
                continue
            
            # 태그 검색 필터
            if tag_search:
                tags = doc.get("auto_tags", {}).get("tags_topk", [])
                tag_names = [t.get("tag", "").lower() for t in tags]
                if not any(tag_search in tag_name for tag_name in tag_names):
                    continue
            
            self.filtered_docs.append(doc)
        
        self.status_label.config(text=f"전체 {len(self.all_docs)}개 / 필터링 {len(self.filtered_docs)}개")
        self._apply_sort()
    
    def _apply_sort(self):
        """정렬 적용"""
        sort_option = self.sort_var.get()
        
        if sort_option == "시간_최신순":
            self.filtered_docs.sort(key=lambda x: x.get("generated_at", ""), reverse=True)
        elif sort_option == "시간_오래된순":
            self.filtered_docs.sort(key=lambda x: x.get("generated_at", ""), reverse=False)
        elif sort_option == "태그수_많은순":
            self.filtered_docs.sort(key=lambda x: x.get("tags_count", 0), reverse=True)
        elif sort_option == "태그수_적은순":
            self.filtered_docs.sort(key=lambda x: x.get("tags_count", 0), reverse=False)
        elif sort_option == "신뢰도_높은순":
            self.filtered_docs.sort(key=lambda x: x.get("genre_confidence", 0.0), reverse=True)
        elif sort_option == "신뢰도_낮은순":
            self.filtered_docs.sort(key=lambda x: x.get("genre_confidence", 0.0), reverse=False)
        elif sort_option == "제목_가나다순":
            self.filtered_docs.sort(key=lambda x: x.get("title", "").lower())
        
        self._refresh_table()
    
    def _refresh_data(self):
        """데이터 새로고침"""
        self._load_all_documents()
        self._apply_filters()
    
    def _refresh_table(self):
        """테이블 새로고침"""
        # 기존 항목 삭제
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # 장르별 색상 매핑
        genre_colors = {
            "guide": "#E3F2FD",      # 파랑
            "procedure": "#E8F5E9",  # 초록
            "report": "#FFF3E0",     # 주황
            "issue": "#FFEBEE",      # 빨강
            "resolution": "#F3E5F5", # 보라
            "policy": "#E0F2F1",     # 청록
            "maintenance": "#FFF9C4", # 노랑
        }
        
        # 필터링된 문서 추가
        for doc in self.filtered_docs:
            genre = doc.get("genre", "unknown")
            confidence = doc.get("genre_confidence", 0.0)
            tags_count = doc.get("tags_count", 0)
            language = doc.get("language", "unknown")
            generated_at = doc.get("generated_at", "")
            topic_sentence = doc.get("topic_sentence")
            
            # 시간 포맷팅
            time_str = ""
            if generated_at:
                try:
                    dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                    time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    time_str = generated_at[:19] if len(generated_at) >= 19 else generated_at
            
            # 주제문장 표시
            topic_display = "📝 있음" if topic_sentence else ""
            if topic_sentence and len(topic_sentence) > 30:
                topic_display = f"📝 {topic_sentence[:30]}..."
            
            # 신뢰도 포맷팅 및 색상 태그
            confidence_str = f"{confidence:.2f}" if confidence else "0.00"
            
            # 신뢰도별 색상 태그
            if confidence >= 0.8:
                conf_tag = "high_conf"
            elif confidence >= 0.5:
                conf_tag = "mid_conf"
            else:
                conf_tag = "low_conf"
            
            # 장르별 색상 태그
            genre_tag = f"genre_{genre}"
            
            # 태깅 실패 표시
            title_display = doc.get("title", "")
            if doc.get("tagging_failed", False):
                title_display = f"⚠️ {title_display} (태깅 실패)"
            
            item_id = self.tree.insert("", "end", values=(
                title_display,
                genre,
                confidence_str,
                tags_count,
                language,
                time_str,
                topic_display
            ), tags=(doc["doc_id"], genre_tag, conf_tag))
            
            # 태깅 실패 시 빨간색 표시
            if doc.get("tagging_failed", False):
                self.tree.tag_configure(doc["doc_id"], foreground="red")
            
            # 색상 적용
            genre_color = genre_colors.get(genre)
            if genre_color:
                self.tree.set(item_id, "장르", genre)
        
        # 색상 태그 설정
        self.tree.tag_configure("high_conf", foreground="#2E7D32")  # 녹색
        self.tree.tag_configure("mid_conf", foreground="#F57C00")  # 주황색
        self.tree.tag_configure("low_conf", foreground="#C62828")  # 빨간색
        
        # 장르별 배경색 (선택적, 너무 많으면 시각적 혼란 가능)
        for genre, color in genre_colors.items():
            self.tree.tag_configure(f"genre_{genre}", background=color)
    
    def _open_detail(self):
        """상세 보기 창 열기"""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("선택 필요", "문서를 선택하세요.")
            return
        
        item = self.tree.item(selection[0])
        doc_id = item["tags"][0] if item["tags"] else None
        
        if not doc_id:
            return
        
        # 해당 문서 찾기
        doc_info = None
        for doc in self.filtered_docs:
            if doc["doc_id"] == doc_id:
                doc_info = doc
                break
        
        if not doc_info:
            return
        
        TaggingDetailWindow(self, self.out_root, doc_info)
    
    def _show_global_stats(self):
        """전체 문서 통계 대시보드"""
        if not MATPLOTLIB_AVAILABLE:
            messagebox.showinfo("알림", "그래프 시각화를 위해 matplotlib 설치 필요:\npip install matplotlib")
            return
        
        stats_window = tk.Toplevel(self)
        stats_window.title("전체 통계 대시보드")
        stats_window.geometry("1200x800")
        
        # 통계 데이터 수집
        genres = Counter()
        languages = Counter()
        total_tags = 0
        avg_confidence = 0.0
        schema_versions = Counter()
        algorithm_usage = Counter()
        
        for doc in self.all_docs:
            genre = doc.get("genre", "unknown")
            language = doc.get("language", "unknown")
            tags_count = doc.get("tags_count", 0)
            genre_conf = doc.get("genre_confidence", 0.0)
            schema_ver = doc.get("schema_version", 1)
            
            genres[genre] += 1
            languages[language] += 1
            total_tags += tags_count
            avg_confidence += genre_conf
            schema_versions[schema_ver] += 1
            
            # 알고리즘 정보
            auto_tags = doc.get("auto_tags", {})
            algo_info = auto_tags.get("algorithm_info", {})
            if algo_info.get("rake_available"):
                algorithm_usage["RAKE"] += 1
            if algo_info.get("yake_available"):
                algorithm_usage["YAKE"] += 1
            if algo_info.get("semantic_adjustment_available"):
                algorithm_usage["의미보정"] += 1
        
        total_docs = len(self.all_docs)
        if total_docs > 0:
            avg_confidence /= total_docs
        
        # 그래프 생성
        fig = Figure(figsize=(12, 8), dpi=100)
        
        # 1. 장르 분포
        ax1 = fig.add_subplot(2, 3, 1)
        if genres:
            genre_names = list(genres.keys())
            genre_counts = list(genres.values())
            ax1.barh(genre_names, genre_counts, color='steelblue', alpha=0.7)
            ax1.set_xlabel('문서 수', fontsize=9)
            ax1.set_title('장르별 문서 수', fontsize=10, fontweight='bold')
            ax1.grid(axis='x', alpha=0.3)
        else:
            ax1.text(0.5, 0.5, '데이터 없음', ha='center', va='center', transform=ax1.transAxes)
            ax1.set_title('장르별 문서 수', fontsize=10, fontweight='bold')
        
        # 2. 언어 분포
        ax2 = fig.add_subplot(2, 3, 2)
        if languages:
            lang_names = list(languages.keys())
            lang_counts = list(languages.values())
            ax2.pie(lang_counts, labels=lang_names, autopct='%1.1f%%', startangle=90)
            ax2.set_title('언어 분포', fontsize=10, fontweight='bold')
        else:
            ax2.text(0.5, 0.5, '데이터 없음', ha='center', va='center', transform=ax2.transAxes)
            ax2.set_title('언어 분포', fontsize=10, fontweight='bold')
        
        # 3. 스키마 버전 분포
        ax3 = fig.add_subplot(2, 3, 3)
        if schema_versions:
            ver_names = [f"v{k}" for k in schema_versions.keys()]
            ver_counts = list(schema_versions.values())
            ax3.bar(ver_names, ver_counts, color='coral', alpha=0.7)
            ax3.set_ylabel('문서 수', fontsize=9)
            ax3.set_title('스키마 버전 분포', fontsize=10, fontweight='bold')
            ax3.grid(axis='y', alpha=0.3)
        else:
            ax3.text(0.5, 0.5, '데이터 없음', ha='center', va='center', transform=ax3.transAxes)
            ax3.set_title('스키마 버전 분포', fontsize=10, fontweight='bold')
        
        # 4. 알고리즘 사용률
        ax4 = fig.add_subplot(2, 3, 4)
        if algorithm_usage:
            algo_names = list(algorithm_usage.keys())
            algo_counts = list(algorithm_usage.values())
            bars = ax4.barh(algo_names, algo_counts, color='lightgreen', alpha=0.7)
            ax4.set_xlabel('사용 문서 수', fontsize=9)
            ax4.set_title('알고리즘 사용률', fontsize=10, fontweight='bold')
            ax4.grid(axis='x', alpha=0.3)
            
            # y축 레이블 폰트 설정 (알고리즘 이름)
            try:
                import platform
                system = platform.system()
                if system == 'Windows':
                    font_prop = fm.FontProperties(family='Malgun Gothic', size=9)
                elif system == 'Darwin':
                    font_prop = fm.FontProperties(family='AppleGothic', size=9)
                else:
                    font_prop = fm.FontProperties(family='NanumGothic', size=9)
                
                # y축 틱 레이블에 폰트 적용
                ax4.set_yticklabels(algo_names, fontproperties=font_prop)
            except:
                # 폰트 설정 실패 시 기본 설정 사용
                ax4.tick_params(axis='y', labelsize=9)
            
            # 값 표시 (숫자만 표시하므로 폰트 문제 없음)
            for bar, count in zip(bars, algo_counts):
                width = bar.get_width()
                ax4.text(width, bar.get_y() + bar.get_height()/2.,
                        str(count), ha='left', va='center', fontsize=9)
        else:
            ax4.text(0.5, 0.5, '데이터 없음', ha='center', va='center', transform=ax4.transAxes)
            ax4.set_title('알고리즘 사용률', fontsize=10, fontweight='bold')
        
        # 5. 통계 요약 텍스트
        ax5 = fig.add_subplot(2, 3, 5)
        ax5.axis('off')
        stats_text = [
            "📊 전체 통계 요약",
            "",
            f"총 문서 수: {total_docs}개",
            f"총 태그 수: {total_tags}개",
            f"평균 태그 수: {total_tags/total_docs:.1f}개" if total_docs > 0 else "평균 태그 수: 0개",
            f"평균 장르 신뢰도: {avg_confidence:.3f}",
            "",
            "📈 분포:",
            f"  • 장르 종류: {len(genres)}개",
            f"  • 언어 종류: {len(languages)}개",
            f"  • 스키마 버전: {len(schema_versions)}개"
        ]
        
        # 한글 폰트 설정
        try:
            import platform
            system = platform.system()
            if system == 'Windows':
                font_prop = fm.FontProperties(family='Malgun Gothic', size=10)
            elif system == 'Darwin':
                font_prop = fm.FontProperties(family='AppleGothic', size=10)
            else:
                font_prop = fm.FontProperties(family='NanumGothic', size=10)
            
            ax5.text(0.1, 0.9, '\n'.join(stats_text), transform=ax5.transAxes,
                    fontsize=10, verticalalignment='top', fontproperties=font_prop)
        except:
            # 폰트 설정 실패 시 기본 설정 사용 (monospace 제거)
            ax5.text(0.1, 0.9, '\n'.join(stats_text), transform=ax5.transAxes,
                    fontsize=10, verticalalignment='top')
        
        # 6. 태그 수 분포 히스토그램
        ax6 = fig.add_subplot(2, 3, 6)
        tag_counts = [doc.get("tags_count", 0) for doc in self.all_docs]
        if tag_counts:
            ax6.hist(tag_counts, bins=min(20, max(5, len(set(tag_counts)))), 
                    color='purple', alpha=0.7, edgecolor='black')
            ax6.set_xlabel('태그 수', fontsize=9)
            ax6.set_ylabel('문서 수', fontsize=9)
            ax6.set_title('문서별 태그 수 분포', fontsize=10, fontweight='bold')
            ax6.grid(axis='y', alpha=0.3)
        else:
            ax6.text(0.5, 0.5, '데이터 없음', ha='center', va='center', transform=ax6.transAxes)
            ax6.set_title('문서별 태그 수 분포', fontsize=10, fontweight='bold')
        
        fig.tight_layout()
        
        canvas = FigureCanvasTkAgg(fig, stats_window)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        
        ttk.Button(stats_window, text="닫기", command=stats_window.destroy).pack(pady=10)


class TaggingDetailWindow(tk.Toplevel):
    """태깅 상세 보기 창"""
    
    def __init__(self, master, out_root: Path, doc_info: Dict[str, Any]):
        super().__init__(master)
        self.title(f"태깅 상세 - {doc_info.get('title', '')}")
        self.geometry("1600x1000")  # 그래프와 태그 목록을 모두 보이도록 크기 확대
        self.out_root = out_root
        self.doc_info = doc_info
        self.auto_tags = doc_info.get("auto_tags", {})
        
        self.transient(master)
        self._build_ui()
        self._render_info()
        self._render_algorithm_info()
        self._render_tags()
        # 그래프 렌더링 (matplotlib 사용 가능 시)
        if MATPLOTLIB_AVAILABLE and self.graph_notebook:
            self._render_confidence_graphs()
            self._render_statistics_dashboard()
    
    def _build_ui(self):
        """UI 구성"""
        # 메인 컨테이너 (스크롤 가능)
        main_container = ttk.Frame(self)
        main_container.pack(fill="both", expand=True)
        
        # 캔버스와 스크롤바 추가
        canvas = tk.Canvas(main_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        root = scrollable_frame
        
        # 상단: 기본 정보 + 알고리즘 정보
        top_frame = ttk.Frame(root)
        top_frame.pack(fill="x", pady=(10, 10), padx=10)
        
        # 기본 정보 영역
        info_frame = ttk.LabelFrame(top_frame, text="기본 정보", padding=10)
        info_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
        
        self.info_text = tk.Text(info_frame, height=6, wrap="word", font=("Malgun Gothic", 9))
        self.info_text.pack(fill="x")
        
        # 알고리즘 정보 영역
        algo_frame = ttk.LabelFrame(top_frame, text="알고리즘 정보", padding=10)
        algo_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))
        
        self.algo_text = tk.Text(algo_frame, height=6, wrap="word", font=("Malgun Gothic", 9))
        self.algo_text.pack(fill="x")
        
        # 중간: 그래프 영역 (탭) - 높이 제한
        if MATPLOTLIB_AVAILABLE:
            graph_frame = ttk.LabelFrame(root, text="시각화", padding=10)
            graph_frame.pack(fill="x", pady=(0, 10), padx=10)  # expand 제거, fill="x"만 사용
            
            self.graph_notebook = ttk.Notebook(graph_frame)
            self.graph_notebook.pack(fill="x", pady=5)  # expand 제거
            
            # 탭 1: 신뢰도 비교
            self.tab_confidence = ttk.Frame(self.graph_notebook)
            self.graph_notebook.add(self.tab_confidence, text="신뢰도 비교")
            
            # 탭 2: 통계 대시보드
            self.tab_stats = ttk.Frame(self.graph_notebook)
            self.graph_notebook.add(self.tab_stats, text="통계 대시보드")
            
            # 탭 3: 원본 문서 (실제 문서 전체, 스크롤 가능)
            self.tab_original = ttk.Frame(self.graph_notebook)
            self.graph_notebook.add(self.tab_original, text="원본 표시")
            self._build_original_doc_tab()
        else:
            self.graph_notebook = None
            no_graph_label = ttk.Label(root, text="그래프 시각화를 위해 matplotlib 설치 필요:\npip install matplotlib", 
                                     foreground="gray", justify="left", font=("Malgun Gothic", 9))
            no_graph_label.pack(fill="x", pady=(0, 10), padx=10)
            # 원본 표시는 별도 프레임으로 제공
            orig_frame = ttk.LabelFrame(root, text="원본 표시", padding=10)
            orig_frame.pack(fill="both", expand=True, pady=(0, 10), padx=10)
            self._build_original_doc_in_frame(orig_frame)
        
        # 하단: 태그 목록 영역
        tags_frame = ttk.LabelFrame(root, text="태그 목록", padding=10)
        tags_frame.pack(fill="both", expand=True, pady=(0, 10), padx=10)
        
        # 태그 테이블
        columns = ("태그", "신뢰도", "원본", "의미점수", "알고리즘", "증거")
        self.tags_tree = ttk.Treeview(tags_frame, columns=columns, show="headings", height=15)
        
        self.tags_tree.heading("태그", text="태그명")
        self.tags_tree.heading("신뢰도", text="최종 신뢰도")
        self.tags_tree.heading("원본", text="원본 신뢰도")
        self.tags_tree.heading("의미점수", text="의미 점수")
        self.tags_tree.heading("알고리즘", text="지지 알고리즘")
        self.tags_tree.heading("증거", text="증거 구문")
        
        self.tags_tree.column("태그", width=150)
        self.tags_tree.column("신뢰도", width=80, anchor="center")
        self.tags_tree.column("원본", width=80, anchor="center")
        self.tags_tree.column("의미점수", width=80, anchor="center")
        self.tags_tree.column("알고리즘", width=120, anchor="center")
        self.tags_tree.column("증거", width=80, anchor="center")
        
        scrollbar_tags = ttk.Scrollbar(tags_frame, orient="vertical", command=self.tags_tree.yview)
        self.tags_tree.configure(yscrollcommand=scrollbar_tags.set)
        
        self.tags_tree.pack(side="left", fill="both", expand=True)
        scrollbar_tags.pack(side="right", fill="y")
        
        # 증거 구문 보기 (더블클릭)
        self.tags_tree.bind("<Double-1>", lambda e: self._show_evidence())
        
        # 버튼
        btn_frame = ttk.Frame(root)
        btn_frame.pack(fill="x", pady=(10, 10), padx=10)
        
        ttk.Button(btn_frame, text="닫기", command=self.destroy, width=12).pack(side="right", padx=5)
        
        # 캔버스와 스크롤바 배치
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 마우스 휠 스크롤 바인딩
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
    
    def _build_original_doc_tab(self):
        """원본 표시 탭: 실제 문서 전체 텍스트 (스크롤 가능)"""
        self._build_original_doc_in_frame(self.tab_original)
    
    def _build_original_doc_in_frame(self, parent):
        """parent 프레임 안에 원본 문서 텍스트 뷰어 (스크롤 가능) 구성"""
        doc_id = self.doc_info.get("doc_id", "")
        doc_dir = self.out_root / doc_id
        extracted_json = _read_json(doc_dir / "extracted.json")
        original_text = extracted_json.get("text", "") if extracted_json else "(원본 텍스트 없음)"
        
        text_frame = ttk.Frame(parent)
        text_frame.pack(fill="both", expand=True)
        
        orig_text = tk.Text(text_frame, wrap="word", font=("Malgun Gothic", 9), state="disabled", bg="white")
        orig_text.pack(side="left", fill="both", expand=True)
        
        scrollbar_orig = ttk.Scrollbar(text_frame, orient="vertical", command=orig_text.yview)
        scrollbar_orig.pack(side="right", fill="y")
        orig_text.config(yscrollcommand=scrollbar_orig.set)
        
        orig_text.config(state="normal")
        orig_text.delete("1.0", "end")
        orig_text.insert("1.0", original_text)
        orig_text.config(state="disabled")
        
        def _on_mousewheel_orig(event):
            orig_text.yview_scroll(int(-1 * (event.delta / 120)), "units")
        orig_text.bind("<MouseWheel>", _on_mousewheel_orig)
    
    def _render_info(self):
        """기본 정보 표시"""
        doc_id = self.doc_info.get("doc_id", "")
        title = self.doc_info.get("title", "")
        genre = self.doc_info.get("genre", "unknown")
        genre_confidence = self.doc_info.get("genre_confidence", 0.0)
        language = self.doc_info.get("language", "unknown")
        topic_sentence = self.doc_info.get("topic_sentence")
        generated_at = self.doc_info.get("generated_at", "")
        schema_version = self.auto_tags.get("schema_version", 1)
        
        # 시간 포맷팅
        time_str = ""
        if generated_at:
            try:
                dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                time_str = generated_at[:19] if len(generated_at) >= 19 else generated_at
        
        info_lines = [
            f"문서 ID: {doc_id}",
            f"제목: {title}",
            f"장르: {genre} (신뢰도: {genre_confidence:.3f})",
            f"언어: {language}",
            f"스키마 버전: v{schema_version}",
            f"처리 시간: {time_str}"
        ]
        
        if topic_sentence:
            info_lines.append(f"주제문장: {topic_sentence}")
        
        # 장르 증거
        genre_evidence = self.auto_tags.get("genre_evidence", [])
        if genre_evidence:
            info_lines.append("\n장르 증거:")
            for ev in genre_evidence[:3]:
                quote = ev.get("quote", "")
                if quote:
                    info_lines.append(f"  - {quote[:100]}")
        
        self.info_text.delete("1.0", "end")
        self.info_text.insert("1.0", "\n".join(info_lines))
        self.info_text.config(state="disabled")
    
    def _render_tags(self):
        """태그 목록 표시"""
        tags = self.auto_tags.get("tags_topk", [])
        schema_version = self.auto_tags.get("schema_version", 1)
        
        for tag_item in tags:
            tag = tag_item.get("tag", "")
            
            if schema_version == 2:
                # v2: 다중 알고리즘
                confidence = tag_item.get("confidence_adjusted") or tag_item.get("confidence", 0.0)
                confidence_original = tag_item.get("confidence_original", confidence)
                semantic_score = tag_item.get("semantic_score")
                support_algorithms = tag_item.get("support_algorithms", [])
                evidence_spans = tag_item.get("evidence_spans", [])
                
                # 알고리즘 표시
                algo_display = "+".join(support_algorithms) if support_algorithms else "BM25"
                
                # 의미 점수 표시
                semantic_display = f"{semantic_score:.3f}" if semantic_score is not None else "-"
                
                # 증거 구문 개수
                evidence_count = len(evidence_spans) if evidence_spans else 0
                evidence_display = f"{evidence_count}개" if evidence_count > 0 else "-"
                
                self.tags_tree.insert("", "end", values=(
                    tag,
                    f"{confidence:.3f}",
                    f"{confidence_original:.3f}",
                    semantic_display,
                    algo_display,
                    evidence_display
                ), tags=(json.dumps(tag_item),))
            else:
                # v1: 기존 BM25 (fallback)
                score = tag_item.get("score", 0.0)
                tf = tag_item.get("tf", 0)
                df = tag_item.get("df", 0)
                from_topic = tag_item.get("from_topic", False)
                
                algo_display = "BM25"
                if from_topic:
                    algo_display += "+주제"
                
                self.tags_tree.insert("", "end", values=(
                    tag,
                    f"{score:.3f}",
                    "-",
                    "-",
                    algo_display,
                    f"TF:{tf}, DF:{df}"
                ), tags=(json.dumps(tag_item),))
    
    def _show_evidence(self):
        """증거 구문 보기 (원문 하이라이트 포함)"""
        selection = self.tags_tree.selection()
        if not selection:
            return
        
        item = self.tags_tree.item(selection[0])
        tag_data_str = item["tags"][0] if item["tags"] else None
        
        if not tag_data_str:
            return
        
        try:
            tag_data = json.loads(tag_data_str)
        except:
            return
        
        evidence_spans = tag_data.get("evidence_spans", [])
        if not evidence_spans:
            messagebox.showinfo("증거 구문", "증거 구문이 없습니다.")
            return
        
        # 원본 텍스트 가져오기
        doc_id = self.doc_info.get("doc_id")
        doc_dir = self.out_root / doc_id
        extracted_json = _read_json(doc_dir / "extracted.json")
        original_text = extracted_json.get("text", "") if extracted_json else ""
        
        # 증거 구문 창
        evidence_window = tk.Toplevel(self)
        evidence_window.title(f"증거 구문 - {tag_data.get('tag', '')}")
        evidence_window.geometry("800x600")
        
        header_frame = ttk.Frame(evidence_window)
        header_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Label(header_frame, text=f"태그: {tag_data.get('tag', '')}", font=("Malgun Gothic", 11, "bold")).pack(anchor="w")
        ttk.Label(header_frame, text=f"신뢰도: {tag_data.get('confidence', 0.0):.3f}", font=("Malgun Gothic", 9)).pack(anchor="w", pady=(2, 0))
        
        # 탭 노트북
        notebook = ttk.Notebook(evidence_window)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 탭 1: 증거 구문 목록
        tab1 = ttk.Frame(notebook)
        notebook.add(tab1, text="증거 구문 목록")
        
        list_frame = ttk.Frame(tab1)
        list_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        evidence_list = tk.Listbox(list_frame, font=("Malgun Gothic", 9))
        evidence_list.pack(fill="both", expand=True)
        
        for i, span in enumerate(evidence_spans, 1):
            text = span.get("text", "")
            position = span.get("position", 0)
            algorithm = span.get("algorithm", "")
            preview = text[:80] + "..." if len(text) > 80 else text
            evidence_list.insert("end", f"[{i}] 위치:{position} | {algorithm} | {preview}")
        
        # 탭 2: 원문 하이라이트 (스크롤 가능)
        tab2 = ttk.Frame(notebook)
        notebook.add(tab2, text="원문 하이라이트")
        
        text_frame = ttk.Frame(tab2)
        text_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        original_text_widget = tk.Text(text_frame, wrap="word", font=("Malgun Gothic", 9))
        original_text_widget.pack(side="left", fill="both", expand=True)
        
        scrollbar_orig = ttk.Scrollbar(text_frame, orient="vertical", command=original_text_widget.yview)
        scrollbar_orig.pack(side="right", fill="y")
        original_text_widget.config(yscrollcommand=scrollbar_orig.set)
        
        def _on_mousewheel_orig(event):
            original_text_widget.yview_scroll(int(-1 * (event.delta / 120)), "units")
        original_text_widget.bind("<MouseWheel>", _on_mousewheel_orig)
        
        if original_text:
            original_text_widget.insert("1.0", original_text)
            
            # 증거 구문 하이라이트
            for span in evidence_spans:
                text = span.get("text", "")
                position = span.get("position", 0)
                
                # 텍스트에서 위치 찾기
                start_pos = f"1.0 + {position} chars"
                end_pos = f"1.0 + {position + len(text)} chars"
                
                try:
                    original_text_widget.tag_add("highlight", start_pos, end_pos)
                except:
                    # 위치 계산 실패 시 텍스트 검색으로 대체
                    start_idx = original_text.find(text, max(0, position - 50))
                    if start_idx >= 0:
                        start_line = original_text[:start_idx].count('\n') + 1
                        start_col = start_idx - (original_text.rfind('\n', 0, start_idx) + 1)
                        end_idx = start_idx + len(text)
                        end_line = original_text[:end_idx].count('\n') + 1
                        end_col = end_idx - (original_text.rfind('\n', 0, end_idx) + 1)
                        
                        try:
                            original_text_widget.tag_add("highlight", f"{start_line}.{start_col}", f"{end_line}.{end_col}")
                        except:
                            pass
            
            # 하이라이트 스타일 설정
            original_text_widget.tag_config("highlight", background="#FFEB3B", foreground="#000")
        
        original_text_widget.config(state="disabled")
        
        # 리스트 선택 시 원문으로 이동
        def on_list_select(event):
            selection = evidence_list.curselection()
            if selection and original_text:
                idx = selection[0]
                if idx < len(evidence_spans):
                    span = evidence_spans[idx]
                    position = span.get("position", 0)
                    # 원문 탭으로 전환
                    notebook.select(1)
                    # 해당 위치로 스크롤
                    try:
                        start_pos = f"1.0 + {position} chars"
                        original_text_widget.see(start_pos)
                        original_text_widget.mark_set("insert", start_pos)
                    except:
                        pass
        
        evidence_list.bind("<<ListboxSelect>>", on_list_select)
        
        ttk.Button(evidence_window, text="닫기", command=evidence_window.destroy).pack(pady=10)
    
    def _render_algorithm_info(self):
        """알고리즘 정보 표시"""
        algorithm_info = self.auto_tags.get("algorithm_info", {})
        schema_version = self.auto_tags.get("schema_version", 1)
        
        if schema_version == 1:
            # v1: 기본 BM25 (fallback)
            info_lines = [
                "스키마 버전: v1 (BM25 기반)",
                "알고리즘: BM25",
                "의미 보정: 미적용"
            ]
        else:
            # v2: 다중 알고리즘
            info_lines = [
                "스키마 버전: v2 (다중 알고리즘 합의 기반)",
                "",
                "사용 가능한 알고리즘:",
                f"  • MULTI_RAKE: {'✓' if algorithm_info.get('multi_rake_available', False) else '✗'}",
                f"  • Kiwipiepy: {'✓' if algorithm_info.get('kiwipiepy_available', False) else '✗'}",
                f"  • RAKE: {'✓' if algorithm_info.get('rake_available', False) else '✗'}",
                f"  • RAKE-NLTK: {'✓' if algorithm_info.get('rake_nltk_available', False) else '✗'}",
                f"  • YAKE: {'✓' if algorithm_info.get('yake_available', False) else '✗'}",
                f"  • KoNLPy: {'✓' if algorithm_info.get('konlpy_available', False) else '✗'}",
                f"  • BM25: ✓ (항상 사용)",
                "",
                "의미 기반 보정:",
                f"  • 사용 가능: {'✓' if algorithm_info.get('semantic_adjustment_available', False) else '✗'}",
                f"  • 한국어 모델: {algorithm_info.get('semantic_model_ko', 'N/A')}",
                f"  • 영어 모델: {algorithm_info.get('semantic_model_en', 'N/A')}",
                "",
                f"최소 지지 수: {algorithm_info.get('min_support', 2)}",
                f"언어: {algorithm_info.get('language', 'unknown')}"
            ]
        
        self.algo_text.delete("1.0", "end")
        self.algo_text.insert("1.0", "\n".join(info_lines))
        self.algo_text.config(state="disabled")
    
    def _render_confidence_graphs(self):
        """신뢰도 비교 그래프"""
        if not MATPLOTLIB_AVAILABLE or not self.graph_notebook:
            return
        
        # 기존 그래프 제거
        for widget in self.tab_confidence.winfo_children():
            widget.destroy()
        
        tags = self.auto_tags.get("tags_topk", [])
        if not tags:
            ttk.Label(self.tab_confidence, text="태그 데이터 없음", foreground="gray").pack()
            return
        
        # 의미 보정이 실제로 적용되었는지 확인
        # confidence_original 필드가 있는 태그가 하나라도 있으면 보정이 적용된 것으로 간주
        has_semantic_adjustment = any(
            tag_item.get("confidence_original") is not None 
            for tag_item in tags 
            if isinstance(tag_item, dict)
        )
        
        if not has_semantic_adjustment:
            # 의미 보정이 적용되지 않은 경우: 신뢰도 분포만 표시
            confidences = []
            tag_names = []
            
            for tag_item in tags[:15]:  # 상위 15개
                if isinstance(tag_item, dict):
                    tag = tag_item.get("tag", "")
                    if not tag:
                        continue
                    
                    conf = tag_item.get("confidence") or tag_item.get("score", 0.0)
                    tag_names.append(tag.replace("_", "\n"))
                    confidences.append(float(conf))
            
            if not tag_names:
                ttk.Label(self.tab_confidence, text="태그 데이터 없음", foreground="gray").pack()
                return
            
            # 신뢰도 분포 그래프
            fig = Figure(figsize=(10, 5), dpi=100)
            ax = fig.add_subplot(111)
            
            x = range(len(tag_names))
            bars = ax.bar(x, confidences, color='steelblue', alpha=0.7)
            
            ax.set_xlabel('태그', fontsize=10)
            ax.set_ylabel('신뢰도', fontsize=10)
            ax.set_title('태그별 신뢰도 분포 (상위 15개)\n※ 의미 보정 미적용', fontsize=12, fontweight='bold')
            ax.set_xticks(x)
            ax.set_xticklabels(tag_names, fontsize=8, rotation=45, ha='right')
            ax.set_ylim(0, max(1.0, max(confidences) * 1.1))
            ax.grid(axis='y', alpha=0.3)
            
            # 값 표시 (폰트 명시적 지정)
            try:
                from matplotlib import font_manager as fm
                import platform
                system = platform.system()
                if system == 'Windows':
                    font_prop = fm.FontProperties(family='Malgun Gothic', size=7)
                elif system == 'Darwin':
                    font_prop = fm.FontProperties(family='AppleGothic', size=7)
                else:
                    font_prop = fm.FontProperties(family='NanumGothic', size=7)
            except:
                font_prop = None
            
            for bar, conf in zip(bars, confidences):
                height = bar.get_height()
                # 숫자만 표시하므로 폰트 문제는 없지만, 명시적으로 지정
                text_str = f'{conf:.3f}'
                if font_prop:
                    ax.text(bar.get_x() + bar.get_width()/2., height,
                           text_str, ha='center', va='bottom', fontproperties=font_prop)
                else:
                    ax.text(bar.get_x() + bar.get_width()/2., height,
                           text_str, ha='center', va='bottom', fontsize=7)
            
            fig.tight_layout()
            
            canvas = FigureCanvasTkAgg(fig, self.tab_confidence)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="x", pady=5)
            return
        
        # 의미 보정이 적용된 경우: 보정 전후 비교 그래프
        original_scores = []
        adjusted_scores = []
        semantic_scores = []
        tag_names = []
        
        for tag_item in tags[:15]:  # 상위 15개
            if isinstance(tag_item, dict):
                tag = tag_item.get("tag", "")
                if not tag:
                    continue
                
                # 보정 전 신뢰도 (의미 보정이 적용된 경우에만 존재)
                orig = tag_item.get("confidence_original")
                if orig is None:
                    continue  # 보정이 적용되지 않은 태그는 제외
                
                # 보정 후 신뢰도
                adj = tag_item.get("confidence_adjusted") or tag_item.get("confidence", 0.0)
                # 의미 점수
                sem = tag_item.get("semantic_score", 0.0)
                
                tag_names.append(tag.replace("_", "\n"))
                original_scores.append(float(orig))
                adjusted_scores.append(float(adj))
                semantic_scores.append(float(sem) if sem else 0.0)
        
        if not tag_names:
            ttk.Label(self.tab_confidence, text="보정 데이터 없음", foreground="gray").pack()
            return
        
        # 비교 그래프 생성 (크기 제한)
        fig = Figure(figsize=(10, 5), dpi=100)
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
        ax.set_title('신뢰도 보정 전후 비교 (상위 15개)', fontsize=12, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(tag_names, fontsize=8, rotation=45, ha='right')
        ax.set_ylim(0, max(1.0, max(adjusted_scores + original_scores + semantic_scores) * 1.1))
        ax.legend(fontsize=9)
        ax.grid(axis='y', alpha=0.3)
        
        fig.tight_layout()
        
        canvas = FigureCanvasTkAgg(fig, self.tab_confidence)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="x", pady=5)
    
    def _render_statistics_dashboard(self):
        """통계 대시보드 (BM25 앙상블)"""
        if not MATPLOTLIB_AVAILABLE or not self.graph_notebook:
            return
        
        # 기존 그래프 제거
        for widget in self.tab_stats.winfo_children():
            widget.destroy()
        
        tags = self.auto_tags.get("tags_topk", [])
        algorithm_info = self.auto_tags.get("algorithm_info", {})
        
        # 통계 데이터 수집
        total_tags = len(tags)
        avg_confidence = 0.0
        avg_semantic = 0.0
        algorithm_counts = Counter()
        confidence_ranges = {"높음(≥0.8)": 0, "중간(0.5-0.8)": 0, "낮음(<0.5)": 0}
        semantic_count = 0
        
        for tag_item in tags:
            if isinstance(tag_item, dict):
                conf = tag_item.get("confidence_adjusted") or tag_item.get("confidence") or tag_item.get("score", 0.0)
                avg_confidence += float(conf)
                sem = tag_item.get("semantic_score")
                if sem is not None:
                    avg_semantic += float(sem)
                    semantic_count += 1
                if conf >= 0.8:
                    confidence_ranges["높음(≥0.8)"] += 1
                elif conf >= 0.5:
                    confidence_ranges["중간(0.5-0.8)"] += 1
                else:
                    confidence_ranges["낮음(<0.5)"] += 1
                support_algos = tag_item.get("support_algorithms", [])
                if support_algos:
                    for algo in support_algos:
                        algorithm_counts[algo] += 1
                else:
                    algorithm_counts["bm25"] += 1
        
        if total_tags > 0:
            avg_confidence /= total_tags
            if semantic_count > 0:
                avg_semantic /= semantic_count
        
        # 대시보드 그래프 생성 (2x2)
        fig = Figure(figsize=(12, 6), dpi=100)
        
        # 1. 신뢰도 분포 (파이)
        ax1 = fig.add_subplot(2, 2, 1)
        if sum(confidence_ranges.values()) > 0:
            labels = list(confidence_ranges.keys())
            sizes = list(confidence_ranges.values())
            colors = ['#2E7D32', '#F57C00', '#C62828']
            ax1.pie(sizes, labels=labels, autopct='%1.1f%%', colors=colors, startangle=90)
        else:
            ax1.text(0.5, 0.5, '데이터 없음', ha='center', va='center', transform=ax1.transAxes)
        ax1.set_title('신뢰도 분포', fontsize=11, fontweight='bold')
        
        # 2. 알고리즘 사용 분포 (막대)
        ax2 = fig.add_subplot(2, 2, 2)
        if algorithm_counts:
            algo_names = list(algorithm_counts.keys())
            algo_counts = list(algorithm_counts.values())
            bars = ax2.barh(algo_names, algo_counts, color='steelblue', alpha=0.7)
            ax2.set_xlabel('태그 수', fontsize=9)
            ax2.set_title('알고리즘별 태그 수', fontsize=11, fontweight='bold')
            ax2.grid(axis='x', alpha=0.3)
            for bar, count in zip(bars, algo_counts):
                width = bar.get_width()
                ax2.text(width, bar.get_y() + bar.get_height()/2., str(count), ha='left', va='center', fontsize=9)
        else:
            ax2.text(0.5, 0.5, '데이터 없음', ha='center', va='center', transform=ax2.transAxes)
            ax2.set_title('알고리즘별 태그 수', fontsize=11, fontweight='bold')
        
        # 3. 통계 요약 (텍스트)
        ax3 = fig.add_subplot(2, 2, 3)
        ax3.axis('off')
        stats_text = [
            "📊 통계 요약",
            "",
            f"총 태그 수: {total_tags}개",
            f"평균 신뢰도: {avg_confidence:.3f}",
            f"평균 의미 점수: {avg_semantic:.3f}" if semantic_count > 0 else "평균 의미 점수: N/A",
            "",
            "📈 신뢰도 분포:",
            f"  • 높음 (≥0.8): {confidence_ranges['높음(≥0.8)']}개",
            f"  • 중간 (0.5-0.8): {confidence_ranges['중간(0.5-0.8)']}개",
            f"  • 낮음 (<0.5): {confidence_ranges['낮음(<0.5)']}개",
            "",
            "🔧 알고리즘 정보:",
            f"  • RAKE: {'사용' if algorithm_info.get('rake_available') else '미사용'}",
            f"  • YAKE: {'사용' if algorithm_info.get('yake_available') else '미사용'}",
            f"  • BM25: 사용 (앙상블)",
            f"  • 의미 보정: {'사용' if algorithm_info.get('semantic_adjustment_available') else '미사용'}"
        ]
        try:
            import platform
            system = platform.system()
            font_name = 'Malgun Gothic' if system == 'Windows' else ('AppleGothic' if system == 'Darwin' else 'NanumGothic')
            font_prop = fm.FontProperties(family=font_name, size=10)
            ax3.text(0.1, 0.9, '\n'.join(stats_text), transform=ax3.transAxes,
                     fontsize=10, verticalalignment='top', fontproperties=font_prop)
        except:
            ax3.text(0.1, 0.9, '\n'.join(stats_text), transform=ax3.transAxes,
                     fontsize=10, verticalalignment='top')
        
        # 4. 태그 신뢰도 분포 (히스토그램)
        ax4 = fig.add_subplot(2, 2, 4)
        if tags:
            confidences = []
            for tag_item in tags:
                conf = tag_item.get("confidence_adjusted") or tag_item.get("confidence") or tag_item.get("score", 0.0)
                confidences.append(float(conf))
            if confidences:
                ax4.hist(confidences, bins=20, color='coral', alpha=0.7, edgecolor='black')
                ax4.set_xlabel('신뢰도', fontsize=9)
                ax4.set_ylabel('태그 수', fontsize=9)
                ax4.set_title('신뢰도 분포 히스토그램', fontsize=11, fontweight='bold')
                ax4.grid(axis='y', alpha=0.3)
        else:
            ax4.text(0.5, 0.5, '데이터 없음', ha='center', va='center', transform=ax4.transAxes)
            ax4.set_title('신뢰도 분포 히스토그램', fontsize=11, fontweight='bold')
        
        fig.tight_layout()
        
        canvas = FigureCanvasTkAgg(fig, self.tab_stats)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="x", pady=5)


def open_tagging_viewer(master, out_root: str):
    """태깅 뷰어 열기"""
    try:
        TaggingViewerWindow(master, out_root)
    except Exception as e:
        messagebox.showerror("오류", f"태깅 뷰어를 열 수 없습니다:\n{e}")
