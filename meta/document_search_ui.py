"""
문서 검색 UI
"""
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import json
from document_search import search_documents, search_by_topic_sentence, search_documents_optimized, build_tag_index

# 피드백 관리 모듈 (선택적 import)
try:
    from feedback_manager import (
        load_feedback_data, save_feedback, update_metadata_with_feedback,
        get_feedback_info, get_feedback_status
    )
    FEEDBACK_AVAILABLE = True
except ImportError:
    FEEDBACK_AVAILABLE = False
    def load_feedback_data(out_root: str) -> Dict:
        return {}
    def save_feedback(*args, **kwargs):
        pass
    def update_metadata_with_feedback(*args, **kwargs):
        pass
    def get_feedback_info(*args, **kwargs):
        return {"display": "-", "boost": 1.0, "status": "none"}
    def get_feedback_status(*args, **kwargs):
        return "none"


class DocumentSearchWindow(tk.Toplevel):
    """문서 검색 창"""
    def __init__(self, master, out_root: str):
        super().__init__(master)
        self.title("문서 검색")
        self.geometry("1400x800")  # 본문 표시를 위해 크기 확대
        self.out_root = out_root
        self.current_session_id = None
        self.feedback_data = load_feedback_data(out_root) if FEEDBACK_AVAILABLE else {}
        
        self._build_ui()
        self.transient(master)
        
    def _build_ui(self):
        # 검색 영역
        search_frame = ttk.LabelFrame(self, text="검색", padding=10)
        search_frame.pack(fill="x", padx=10, pady=10)
        
        # 검색어 입력
        row1 = ttk.Frame(search_frame)
        row1.pack(fill="x", pady=5)
        ttk.Label(row1, text="검색어:", width=12, anchor="w").pack(side="left")
        self.search_entry = ttk.Entry(row1, width=60, font=("Malgun Gothic", 10))
        self.search_entry.pack(side="left", padx=5, fill="x", expand=True)
        self.search_entry.bind("<Return>", lambda e: self._do_search())
        ttk.Button(row1, text="검색", command=self._do_search, width=10).pack(side="left", padx=5)
        
        # 필터 옵션
        row2 = ttk.Frame(search_frame)
        row2.pack(fill="x", pady=5)
        ttk.Label(row2, text="장르 필터:", width=12, anchor="w").pack(side="left")
        self.genre_var = tk.StringVar(value="")
        genre_combo = ttk.Combobox(
            row2,
            textvariable=self.genre_var,
            values=["", "issue", "resolution", "procedure", "report", "policy", "communication", 
                   "plan", "contract", "reference", "application", "form", "maintenance", "guide", "record"],
            width=20,
            state="readonly",
            font=("Malgun Gothic", 9)
        )
        genre_combo.pack(side="left", padx=5)
        
        ttk.Label(row2, text="태그 필터:", width=12, anchor="w").pack(side="left", padx=(20, 0))
        self.tag_entry = ttk.Entry(row2, width=30, font=("Malgun Gothic", 9))
        self.tag_entry.pack(side="left", padx=5, fill="x", expand=True)
        ttk.Label(row2, text="(쉼표로 구분)", font=("Malgun Gothic", 8), foreground="gray").pack(side="left", padx=2)
        
        # 주제문장 검색 옵션 및 최적화 옵션
        row3 = ttk.Frame(search_frame)
        row3.pack(fill="x", pady=5)
        self.topic_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row3,
            text="주제문장이 있는 문서만 검색",
            variable=self.topic_only_var
        ).pack(side="left")
        
        self.use_optimized_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row3,
            text="최적화 검색 사용 (2단계 검색)",
            variable=self.use_optimized_var
        ).pack(side="left", padx=(20, 0))
        
        ttk.Button(
            row3,
            text="인덱스 재구축",
            command=self._rebuild_index,
            width=12
        ).pack(side="right", padx=5)
        
        # 결과 영역 (좌우 분할)
        result_container = ttk.Frame(self)
        result_container.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 왼쪽: 검색 결과 리스트
        left_frame = ttk.LabelFrame(result_container, text="검색 결과", padding=10)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
        
        # 결과 리스트
        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill="both", expand=True)
        
        # 트리뷰 생성 (피드백 컬럼 추가)
        columns = ("순위", "문서명", "점수", "가중치", "장르", "주제문장", "태그", "매칭 이유", "피드백", "작업")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=20)
        
        # 컬럼 설정
        self.tree.heading("순위", text="순위")
        self.tree.heading("문서명", text="문서명")
        self.tree.heading("점수", text="점수")
        self.tree.heading("가중치", text="가중치")
        self.tree.heading("장르", text="장르")
        self.tree.heading("주제문장", text="주제문장")
        self.tree.heading("태그", text="태그")
        self.tree.heading("매칭 이유", text="매칭 이유")
        self.tree.heading("피드백", text="피드백")
        self.tree.heading("작업", text="작업")
        
        self.tree.column("순위", width=50, anchor="center")
        self.tree.column("문서명", width=180)
        self.tree.column("점수", width=60, anchor="center")
        self.tree.column("가중치", width=60, anchor="center")
        self.tree.column("장르", width=80)
        self.tree.column("주제문장", width=150)
        self.tree.column("태그", width=120)
        self.tree.column("매칭 이유", width=150)
        self.tree.column("피드백", width=80)
        self.tree.column("작업", width=120)
        
        # 스크롤바
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 선택 이벤트 (본문 표시용)
        self.tree.bind("<<TreeviewSelect>>", self._on_select_document)
        self.tree.bind("<Double-1>", self._on_item_double_click)
        
        # 오른쪽: 원본 표시 (실제 문서, 스크롤 가능)
        right_frame = ttk.LabelFrame(result_container, text="원본 표시", padding=10)
        right_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))
        
        # 문서 제목 표시
        self.doc_title_label = ttk.Label(
            right_frame,
            text="문서를 선택하세요",
            font=("Malgun Gothic", 10, "bold"),
            wraplength=450
        )
        self.doc_title_label.pack(anchor="w", pady=(0, 5))
        
        # 본문 텍스트 위젯 (실제 문서, 스크롤 가능)
        text_frame = ttk.Frame(right_frame)
        text_frame.pack(fill="both", expand=True)
        
        self.text_widget = tk.Text(
            text_frame,
            wrap="word",
            font=("Malgun Gothic", 9),
            state="disabled",
            bg="white"
        )
        self.text_widget.pack(side="left", fill="both", expand=True)
        
        # 세로 스크롤바
        text_scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.text_widget.yview)
        text_scrollbar.pack(side="right", fill="y")
        self.text_widget.config(yscrollcommand=text_scrollbar.set)
        
        # 마우스 휠로 스크롤
        def _on_mousewheel(event):
            self.text_widget.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.text_widget.bind("<MouseWheel>", _on_mousewheel)
        
        # 검색어 하이라이트 태그 설정
        self.text_widget.tag_config("highlight", background="yellow", foreground="black")
        self.text_widget.tag_config("search_match", background="#ffeb3b", foreground="black")
        
        # 상태 표시
        self.status_label = ttk.Label(left_frame, text="검색어를 입력하고 검색 버튼을 클릭하세요.", font=("Malgun Gothic", 9))
        self.status_label.pack(pady=5)
        
    def _do_search(self):
        query = self.search_entry.get().strip()
        if not query:
            messagebox.showwarning("경고", "검색어를 입력하세요.")
            return
        
        # 세션 ID 생성
        self.current_session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 피드백 데이터 새로고침
        if FEEDBACK_AVAILABLE:
            self.feedback_data = load_feedback_data(self.out_root)
        
        # 기존 결과 삭제
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # 필터 파싱
        genre_filter = self.genre_var.get().strip() or None
        tag_filter_str = self.tag_entry.get().strip()
        tag_filter = [t.strip() for t in tag_filter_str.split(",") if t.strip()] if tag_filter_str else None
        
        try:
            # 검색 실행
            if self.topic_only_var.get():
                results = search_by_topic_sentence(self.out_root, query, limit=50)
            else:
                if self.use_optimized_var.get():
                    # 최적화된 검색 사용
                    results = search_documents_optimized(
                        self.out_root,
                        query,
                        genre_filter=genre_filter,
                        tag_filter=tag_filter,
                        limit=50,
                        stage1_topk=100,
                        use_optimized=True
                    )
                else:
                    # 기존 검색 방식
                    results = search_documents(
                        self.out_root,
                        query,
                        genre_filter=genre_filter,
                        tag_filter=tag_filter,
                        limit=50
                    )
            
            # 결과 표시
            if not results:
                self.status_label.config(text="검색 결과가 없습니다.")
                return
            
            for idx, result in enumerate(results, start=1):
                doc_id = result.get("doc_id")
                topic = result.get("topic_sentence", "") or "-"
                if len(topic) > 20:
                    topic = topic[:20] + "..."
                
                tags_str = ", ".join(result.get("tags", [])[:2])
                if len(tags_str) > 15:
                    tags_str = tags_str[:15] + "..."
                
                reasons_str = ", ".join(result.get("match_reasons", [])[:1])
                if len(reasons_str) > 20:
                    reasons_str = reasons_str[:20] + "..."
                
                # 피드백 정보 가져오기
                feedback_info = get_feedback_info(doc_id, self.feedback_data) if FEEDBACK_AVAILABLE else {"display": "-", "boost": 1.0}
                feedback_display = feedback_info.get("display", "-")
                feedback_boost = result.get("feedback_boost", feedback_info.get("boost", 1.0))
                
                # 점수 표시 (가중치 적용된 점수)
                final_score = result.get("score", 0)
                
                # 트리뷰에 삽입
                item_id = self.tree.insert(
                    "",
                    "end",
                    values=(
                        idx,
                        result.get("title", ""),
                        f"{final_score:.1f}",
                        f"{feedback_boost:.2f}",
                        result.get("genre", "unknown"),
                        topic,
                        tags_str,
                        reasons_str,
                        feedback_display,
                        ""  # 작업 컬럼은 별도 처리
                    ),
                    tags=(doc_id,)
                )
                
                # 작업 버튼 프레임 (임베드 불가하므로 별도 처리)
                # 실제로는 버튼을 트리뷰에 직접 넣을 수 없으므로
                # 더블클릭이나 컨텍스트 메뉴로 처리
            
            search_mode = "최적화" if self.use_optimized_var.get() and not self.topic_only_var.get() else "일반"
            self.status_label.config(text=f"검색 완료 ({search_mode}): {len(results)}개 문서 발견")
            
        except Exception as e:
            messagebox.showerror("오류", f"검색 중 오류 발생:\n{e}")
            self.status_label.config(text=f"검색 실패: {e}")
    
    def _rebuild_index(self):
        """인덱스 재구축"""
        try:
            self.status_label.config(text="인덱스 구축 중...")
            self.update()
            
            build_tag_index(self.out_root, force_rebuild=True)
            
            messagebox.showinfo("완료", "인덱스 재구축이 완료되었습니다.")
            self.status_label.config(text="인덱스 재구축 완료")
        except Exception as e:
            messagebox.showerror("오류", f"인덱스 재구축 중 오류 발생:\n{e}")
            self.status_label.config(text=f"인덱스 재구축 실패: {e}")
    
    def _on_select_document(self, event):
        """문서 선택 시 본문 표시"""
        selection = self.tree.selection()
        if not selection:
            return
        
        item = self.tree.item(selection[0])
        doc_id = item["tags"][0] if item["tags"] else None
        
        if doc_id:
            self._display_document_text(doc_id)
    
    def _get_document_info(self, doc_id: str) -> Optional[Dict]:
        """문서 정보 가져오기"""
        payload_path = Path(self.out_root) / "workspace_payload.jsonl"
        
        if not payload_path.exists():
            return None
        
        try:
            with payload_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        doc = json.loads(line)
                        if doc.get("doc_id") == doc_id:
                            return doc
                    except:
                        continue
        except:
            pass
        
        return None
    
    def _display_document_text(self, doc_id: str):
        """문서 본문 표시 (검색어 하이라이트)"""
        doc_info = self._get_document_info(doc_id)
        if not doc_info:
            self.doc_title_label.config(text="문서 정보를 불러올 수 없습니다")
            self.text_widget.config(state="normal")
            self.text_widget.delete("1.0", "end")
            self.text_widget.insert("1.0", "문서 정보를 불러올 수 없습니다.")
            self.text_widget.config(state="disabled")
            return
        
        # 제목 표시
        title = doc_info.get("title", "제목 없음")
        self.doc_title_label.config(text=title)
        
        # 본문 가져오기
        text = doc_info.get("text", "")
        if not text:
            text = "본문이 없습니다."
        
        # 텍스트 위젯 활성화
        self.text_widget.config(state="normal")
        self.text_widget.delete("1.0", "end")
        
        # 본문 삽입
        self.text_widget.insert("1.0", text)
        
        # 검색어 하이라이트
        query = self.search_entry.get().strip().lower()
        if query:
            self._highlight_search_terms(query, text)
        
        # 텍스트 위젯 비활성화 (읽기 전용)
        self.text_widget.config(state="disabled")
    
    def _highlight_search_terms(self, query: str, text: str):
        """검색어 하이라이트"""
        import re
        
        query_lower = query.lower()
        text_lower = text.lower()
        
        # 검색어 토큰화
        query_tokens = query.split()
        
        # 각 토큰에 대해 하이라이트
        for token in query_tokens:
            if not token:
                continue
            
            # 대소문자 구분 없이 검색
            pattern = re.compile(re.escape(token), re.IGNORECASE)
            
            # 모든 매칭 위치 찾기
            for match in pattern.finditer(text):
                start_idx = f"1.0 + {match.start()} chars"
                end_idx = f"1.0 + {match.end()} chars"
                
                # 하이라이트 태그 적용
                self.text_widget.tag_add("highlight", start_idx, end_idx)
        
        # 전체 검색어도 하이라이트 (더 강한 색상)
        if len(query_tokens) > 1:
            full_pattern = re.compile(re.escape(query), re.IGNORECASE)
            for match in full_pattern.finditer(text):
                start_idx = f"1.0 + {match.start()} chars"
                end_idx = f"1.0 + {match.end()} chars"
                self.text_widget.tag_add("search_match", start_idx, end_idx)
        
        # 첫 번째 하이라이트로 스크롤
        if query_tokens:
            first_token = query_tokens[0]
            first_pos = text_lower.find(first_token.lower())
            if first_pos >= 0:
                line_num = text[:first_pos].count('\n') + 1
                self.text_widget.see(f"{line_num}.0")
    
    def _on_item_double_click(self, event):
        """더블클릭 시 피드백 다이얼로그 또는 상세 정보 표시"""
        selection = self.tree.selection()
        if not selection:
            return
        
        item = self.tree.item(selection[0])
        doc_id = item["tags"][0] if item["tags"] else None
        
        if doc_id:
            # 피드백 다이얼로그 표시
            self._show_feedback_dialog(doc_id)
    
    def _show_feedback_dialog(self, doc_id: str):
        """피드백 다이얼로그"""
        if not FEEDBACK_AVAILABLE:
            # 피드백 기능이 없으면 기존 상세 정보 표시
            try:
                from analysis_viewer import open_analysis_window
                open_analysis_window(self.master, self.out_root, doc_id)
            except Exception as e:
                messagebox.showerror("오류", f"문서 상세 정보를 열 수 없습니다:\n{e}")
            return
        
        # 피드백 창 생성
        feedback_window = tk.Toplevel(self)
        feedback_window.title("피드백")
        feedback_window.geometry("400x200")
        feedback_window.transient(self)
        feedback_window.grab_set()
        
        # 문서 정보 표시
        doc_info = self._get_document_info(doc_id)
        title = doc_info.get("title", "제목 없음") if doc_info else "제목 없음"
        
        ttk.Label(
            feedback_window,
            text=f"문서: {title}",
            font=("Malgun Gothic", 10, "bold"),
            wraplength=350
        ).pack(pady=10)
        
        ttk.Label(
            feedback_window,
            text="이 검색 결과에 대한 피드백을 선택하세요:",
            font=("Malgun Gothic", 9)
        ).pack(pady=5)
        
        # 피드백 버튼
        btn_frame = ttk.Frame(feedback_window)
        btn_frame.pack(pady=20)
        
        def on_like():
            query = self.search_entry.get().strip()
            save_feedback(
                out_root=self.out_root,
                doc_id=doc_id,
                query=query,
                feedback="like",
                session_id=self.current_session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
            )
            update_metadata_with_feedback(self.out_root, doc_id)
            feedback_window.destroy()
            messagebox.showinfo("피드백 저장", "좋아요가 저장되었습니다.\n검색을 다시 실행하여 점수에 반영됩니다.")
            if query:
                self._do_search()
        
        def on_dislike():
            query = self.search_entry.get().strip()
            save_feedback(
                out_root=self.out_root,
                doc_id=doc_id,
                query=query,
                feedback="dislike",
                session_id=self.current_session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
            )
            update_metadata_with_feedback(self.out_root, doc_id)
            feedback_window.destroy()
            messagebox.showinfo("피드백 저장", "좋아요 안함이 저장되었습니다.\n검색을 다시 실행하여 점수에 반영됩니다.")
            if query:
                self._do_search()
        
        def on_detail():
            feedback_window.destroy()
            try:
                from analysis_viewer import open_analysis_window
                open_analysis_window(self.master, self.out_root, doc_id)
            except Exception as e:
                messagebox.showerror("오류", f"문서 상세 정보를 열 수 없습니다:\n{e}")
        
        ttk.Button(btn_frame, text="👍 좋아요", command=on_like, width=12).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="👎 좋아요 안함", command=on_dislike, width=12).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="상세 보기", command=on_detail, width=12).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="취소", command=feedback_window.destroy, width=12).pack(side="left", padx=5)
    
    def _update_feedback_display(self, doc_id: str):
        """피드백 표시 업데이트"""
        if not FEEDBACK_AVAILABLE:
            return
        
        feedback_info = get_feedback_info(doc_id, self.feedback_data)
        
        # 트리뷰에서 해당 항목 찾기
        for item in self.tree.get_children():
            item_tags = self.tree.item(item, "tags")
            if item_tags and item_tags[0] == doc_id:
                values = list(self.tree.item(item, "values"))
                values[8] = feedback_info["display"]  # 피드백 컬럼
                values[3] = f"{feedback_info['boost']:.2f}"  # 가중치 컬럼
                
                # 점수도 재계산 필요 (검색 재실행 권장)
                # 여기서는 UI만 업데이트
                self.tree.item(item, values=values)
                break