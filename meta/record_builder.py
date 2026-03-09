
import os
import re
import json
import hashlib
import shutil
from pathlib import Path
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

from auto_tagging import auto_tag_document

# 기존 문서 ingest(app.py)와 동일한 코어 산출물을 만들기 위해 사용
from core_store import CoreStore, build_core_artifact_from_doc, build_event_from_artifact, extract_entities_light


def _slug(s: str, max_len: int = 40) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^0-9A-Za-z가-힣_\-]+", "", s)
    return s[:max_len] if s else "untitled"


def _hash8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()[:8]


def _read_text(t: tk.Text) -> str:
    return t.get("1.0", "end").strip()


def _safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _copy_attachment(src: Path, dst_dir: Path) -> str:
    _safe_mkdir(dst_dir)
    # keep extension, avoid overwrite
    ext = src.suffix.lower() or ".bin"
    base = _slug(src.stem, 60)
    name = f"{base}{ext}"
    out = dst_dir / name
    if out.exists():
        name = f"{base}_{_hash8(str(src)+str(datetime.now().timestamp()))}{ext}"
        out = dst_dir / name
    shutil.copy2(src, out)
    return name


def build_report_markdown(record: dict) -> str:
    h = record["header"]
    ctx = record["context"]
    find = record["findings"]
    act = record["actions"]
    res = record["result"]
    blocks = record["blocks"]

    lines = []
    lines.append(f"# {h.get('title','(제목 없음)')}")
    lines.append("")
    lines.append("## 요약")
    lines.append(h.get("summary","").strip() or "-")
    lines.append("")
    lines.append("## 메타")
    lines.append(f"- 고객사: {h.get('customer','-')}")
    lines.append(f"- 시스템: {h.get('system','-')}")
    lines.append(f"- 분류: {h.get('category','-')}")
    lines.append(f"- 기간: {h.get('date_start','-')} ~ {h.get('date_end','-')}")
    lines.append(f"- 작성자: {h.get('owner','-')}")
    lines.append("")

    def sec(title, txt):
        lines.append(f"## {title}")
        lines.append(txt.strip() or "-")
        lines.append("")

    sec("배경", ctx.get("background",""))
    sec("범위/대상", ctx.get("scope",""))
    sec("제약", ctx.get("constraints",""))
    sec("관계자", ctx.get("stakeholders",""))

    sec("증상", find.get("symptom",""))
    sec("원인 가설", find.get("hypothesis",""))
    sec("근거(텍스트)", find.get("evidence",""))
    sec("결정/확정 사항", find.get("decision",""))

    sec("조치 단계", act.get("steps",""))
    sec("명령/SQL/스니펫", act.get("snippets",""))
    sec("롤백", act.get("rollback",""))
    sec("검증", act.get("validation",""))

    sec("결과", res.get("outcome",""))
    sec("잔여 리스크", res.get("remaining_risks",""))
    sec("후속 작업", res.get("next_actions",""))

    lines.append("## 타임라인/근거 블록")
    if not blocks:
        lines.append("- (없음)")
    else:
        for i,b in enumerate(blocks, start=1):
            ts = b.get("timestamp","").strip()
            if b.get("type") == "text":
                lines.append(f"### [{i}] TEXT {ts}".strip())
                lines.append(b.get("text","").strip() or "-")
                lines.append("")
            elif b.get("type") == "image":
                cap = b.get("text","").strip()
                img = b.get("image_file","").strip()
                lines.append(f"### [{i}] IMAGE {ts}".strip())
                if img:
                    # attachments are stored alongside record.json (datasets/records/.../attachments)
                    lines.append(f"![evidence]({record.get('_md_image_prefix','attachments')}/{img})")
                if cap:
                    lines.append(cap)
                lines.append("")
    # RAG hints
    hints = record.get("rag_hints", {})
    lines.append("## RAG 힌트")
    tags = hints.get("tags", [])
    if tags:
        lines.append(f"- tags: {', '.join(tags)}")
    qs = hints.get("questions", [])
    if qs:
        lines.append("- 이 기록이 답할 수 있는 질문")
        for q in qs:
            lines.append(f"  - {q}")
    dna = hints.get("do_not_answer","").strip()
    if dna:
        lines.append(f"- 답변 금지/주의: {dna}")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def chunk_markdown_for_rag(md: str) -> list[str]:
    # simple paragraph-based chunking (keeps headings + content together)
    paras = [p.strip() for p in re.split(r"\n{2,}", md) if p.strip()]
    chunks = []
    buf = ""
    max_chars = 1400
    for p in paras:
        if not buf:
            buf = p
            continue
        if len(buf) + 2 + len(p) <= max_chars:
            buf = buf + "\n\n" + p
        else:
            chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)
    # merge tiny chunks
    merged = []
    for c in chunks:
        if merged and len(c) < 180:
            merged[-1] = merged[-1] + "\n\n" + c
        else:
            merged.append(c)
    return merged


class RecordBuilderWindow(tk.Toplevel):
    """
    수기 입력 기반 레코드(업무 1건) 생성기.
    - 템플릿을 직관적으로 보여주고(섹션별)
    - 블록(텍스트 / 사진+텍스트)을 근거로 추가
    - 저장(record.json + attachments) + 생성(report.md + rag_export chunks.jsonl)
    """
    def __init__(self, master, base_dir: Path, out_dir: Path):
        super().__init__(master)
        self.title("업무 레코드/보고서 생성 (수동 입력)")
        # 하단 액션 버튼이 항상 보이도록 기본 크기/최소 크기 확보
        self.geometry("1280x900")
        self.minsize(1120, 780)
        self.base_dir = Path(base_dir)
        self.out_dir = Path(out_dir)

        self.dataset_root = self.base_dir / "datasets" / "records"
        self.blocks: list[dict] = []

        today = datetime.now().strftime("%Y-%m-%d")

        # header vars
        self.v_customer = tk.StringVar(value="범용")
        self.v_system = tk.StringVar(value="범용")
        self.v_category = tk.StringVar(value="오류/장애")
        self.v_date_start = tk.StringVar(value=today)
        self.v_date_end = tk.StringVar(value=today)
        self.v_owner = tk.StringVar(value=os.environ.get("USERNAME") or "Hyungjoo")
        self.v_title = tk.StringVar(value="")
        self.v_summary = tk.StringVar(value="")

        # rag hints
        self.v_tags = tk.StringVar(value="")
        self.v_questions = tk.StringVar(value="")
        self.v_dna = tk.StringVar(value="")

        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 8}

        # Top: purpose banner
        banner = ttk.Frame(self)
        banner.pack(fill="x", **pad)
        ttk.Label(
            banner,
            text="업무 자료(텍스트/이미지)를 '표준 보고서 + RAG 투입 가능한 데이터셋'으로 변환합니다.  (수기 입력 기반)",
            font=("맑은 고딕", 11, "bold"),
        ).pack(anchor="w")

        # Header form
        frm = ttk.LabelFrame(self, text="1) 기본 정보(헤더)  —  이 영역은 보고서/인덱싱의 기준이 됩니다")
        frm.pack(fill="x", **pad)

        # 헤더 영역 우측에 '저장/생성' 고정 액션 바(스크롤/레이아웃 영향 최소화)
        action_bar = ttk.Frame(frm)
        action_bar.pack(fill="x", padx=10, pady=(8, 0))
        ttk.Label(
            action_bar,
            text="※ 아래 버튼으로 원본 저장 / 보고서+RAG 출력까지 한 번에 생성합니다.",
            foreground="#444",
        ).pack(side="left")
        ttk.Button(action_bar, text="저장(초안)", command=self.save_only).pack(side="right", padx=6)
        ttk.Button(action_bar, text="저장 + 출력(보고서+RAG+태깅)", command=self.save_and_generate).pack(side="right", padx=6)

        def row(parent):
            r = ttk.Frame(parent); r.pack(fill="x", padx=10, pady=4); return r

        r = row(frm)
        ttk.Label(r, text="고객사", width=10).pack(side="left")
        ttk.Entry(r, textvariable=self.v_customer, width=20).pack(side="left", padx=6)
        ttk.Label(r, text="시스템", width=10).pack(side="left")
        ttk.Entry(r, textvariable=self.v_system, width=20).pack(side="left", padx=6)
        ttk.Label(r, text="분류", width=10).pack(side="left")
        ttk.Combobox(r, textvariable=self.v_category, values=["오류/장애","설정/구성","절차/가이드","업무공유","회의/결정","기타"], width=18, state="readonly").pack(side="left", padx=6)

        r = row(frm)
        ttk.Label(r, text="기간", width=10).pack(side="left")
        ttk.Entry(r, textvariable=self.v_date_start, width=12).pack(side="left", padx=6)
        ttk.Label(r, text="~").pack(side="left")
        ttk.Entry(r, textvariable=self.v_date_end, width=12).pack(side="left", padx=6)
        ttk.Label(r, text="작성자", width=10).pack(side="left")
        ttk.Entry(r, textvariable=self.v_owner, width=20).pack(side="left", padx=6)

        r = row(frm)
        ttk.Label(r, text="제목", width=10).pack(side="left")
        ttk.Entry(r, textvariable=self.v_title, width=90).pack(side="left", padx=6)

        r = row(frm)
        ttk.Label(r, text="요약(3~7줄)", width=10).pack(side="left", anchor="n")
        self.t_summary = tk.Text(r, height=3)
        self.t_summary.pack(side="left", fill="x", expand=True, padx=6)

        # ✅ 상단 액션 바(항상 보이게): 저장/출력 버튼
        act = ttk.Frame(frm)
        act.pack(fill="x", padx=10, pady=(6, 10))
        ttk.Label(
            act,
            text="저장 = datasets/records 에 원본 저장 / 출력(생성) = output/records 에 보고서 + RAG 데이터셋 + 오토태깅 + core 산출물",
            foreground="#444",
        ).pack(side="left")
        ttk.Button(act, text="저장(초안)", command=self.save_only).pack(side="right", padx=6)
        ttk.Button(act, text="출력(보고서+RAG+태깅)", command=self.save_and_generate).pack(side="right", padx=6)

        # Middle: sections + blocks + preview
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, **pad)

        left = ttk.Frame(mid)
        left.pack(side="left", fill="both", expand=True)

        note = ttk.Notebook(left)
        note.pack(fill="both", expand=True)

        # Section text widgets
        self.t_background = tk.Text(note, height=8)
        self.t_scope = tk.Text(note, height=6)
        self.t_constraints = tk.Text(note, height=6)
        self.t_stakeholders = tk.Text(note, height=4)

        self.t_symptom = tk.Text(note, height=6)
        self.t_hypothesis = tk.Text(note, height=6)
        self.t_evidence = tk.Text(note, height=6)
        self.t_decision = tk.Text(note, height=6)

        self.t_steps = tk.Text(note, height=8)
        self.t_snippets = tk.Text(note, height=6)
        self.t_rollback = tk.Text(note, height=6)
        self.t_validation = tk.Text(note, height=6)

        self.t_outcome = tk.Text(note, height=6)
        self.t_remaining = tk.Text(note, height=6)
        self.t_next = tk.Text(note, height=6)

        def tab(title, items):
            f = ttk.Frame(note)
            f.pack(fill="both", expand=True)
            # a short guide
            ttk.Label(f, text="아래 항목은 보고서 섹션으로 그대로 들어갑니다.", foreground="#333").pack(anchor="w", padx=10, pady=(10,2))
            for label, widget, hint in items:
                ttk.Label(f, text=label, font=("맑은 고딕", 10, "bold")).pack(anchor="w", padx=10, pady=(10,2))
                if hint:
                    ttk.Label(f, text=hint, foreground="#555").pack(anchor="w", padx=10, pady=(0,2))
                widget.pack(fill="x", padx=10)
            note.add(f, text=title)

        tab("컨텍스트", [
            ("배경", self.t_background, "왜 이 일이 발생했는지(업무 맥락)"),
            ("범위/대상", self.t_scope, "대상 시스템/버전/서버/경로 등"),
            ("제약", self.t_constraints, "운영/권한/시간/보안 등의 제약"),
            ("관계자", self.t_stakeholders, "관련 팀/담당자/승인자 등"),
        ])
        tab("발견/판단", [
            ("증상", self.t_symptom, "관측된 현상/로그/에러 메시지 요약"),
            ("원인 가설", self.t_hypothesis, "추정 원인(여러 개 가능)"),
            ("근거(텍스트)", self.t_evidence, "스크린샷/문서/대화에서 확인된 근거를 텍스트로"),
            ("결정/확정 사항", self.t_decision, "결정된 원인/방향/확정된 사실"),
        ])
        tab("조치/절차", [
            ("조치 단계", self.t_steps, "Step-by-step 조치(번호로 작성 추천)"),
            ("명령/SQL/스니펫", self.t_snippets, "실행한 커맨드/SQL/설정값"),
            ("롤백", self.t_rollback, "문제 발생 시 되돌리는 방법"),
            ("검증", self.t_validation, "정상 여부 확인 방법(로그/명령/체크리스트)"),
        ])
        tab("결과/후속", [
            ("결과", self.t_outcome, "해결 여부 / 최종 상태"),
            ("잔여 리스크", self.t_remaining, "남은 위험 요소/불확실성"),
            ("후속 작업", self.t_next, "해야 할 일(담당/기한 포함 추천)"),
        ])

        # Right: blocks + preview + rag hints
        right = ttk.Frame(mid)
        right.pack(side="left", fill="both", padx=(10,0))

        blf = ttk.LabelFrame(right, text="2) 근거 블록(타임라인)  —  텍스트만 / 사진+텍스트로 추가")
        blf.pack(fill="both", expand=True, padx=0, pady=(0,10))

        ttk.Label(blf, text="아래 리스트가 보고서 '타임라인/근거' 섹션으로 들어갑니다. (일렬 이미지 몰아넣기 X)", foreground="#444").pack(anchor="w", padx=10, pady=(8,4))

        self.tree = ttk.Treeview(blf, columns=("type","ts","preview","img"), show="headings", height=12)
        self.tree.heading("type", text="타입")
        self.tree.heading("ts", text="시간")
        self.tree.heading("preview", text="내용 미리보기")
        self.tree.heading("img", text="이미지")
        self.tree.column("type", width=70, anchor="center")
        self.tree.column("ts", width=120)
        self.tree.column("preview", width=360)
        self.tree.column("img", width=180)
        self.tree.pack(fill="x", padx=10, pady=(0,6))
        self.tree.bind("<<TreeviewSelect>>", self._on_select_block)

        btnr = ttk.Frame(blf); btnr.pack(fill="x", padx=10, pady=(0,10))
        ttk.Button(btnr, text="텍스트 블록 추가", command=self.add_text_block).pack(side="left")
        ttk.Button(btnr, text="사진+텍스트 블록 추가", command=self.add_image_blocks).pack(side="left", padx=8)
        ttk.Button(btnr, text="선택 블록 삭제", command=self.delete_selected_block).pack(side="left", padx=8)

        # Preview area
        pv = ttk.LabelFrame(right, text="선택 블록 미리보기")
        pv.pack(fill="both", expand=True, padx=0, pady=(0,10))

        self.lbl_preview = ttk.Label(pv, text="(블록을 선택하면 여기에 표시됩니다)", foreground="#555")
        self.lbl_preview.pack(anchor="w", padx=10, pady=(10,4))

        self.txt_preview = tk.Text(pv, height=8)
        self.txt_preview.pack(fill="x", padx=10, pady=(0,8))

        self.img_canvas = tk.Canvas(pv, width=520, height=260, bg="#f6f6f6", highlightthickness=1, highlightbackground="#ddd")
        self.img_canvas.pack(fill="both", expand=True, padx=10, pady=(0,10))
        self._preview_imgtk = None

        # RAG hints
        hf = ttk.LabelFrame(right, text="3) RAG 힌트(선택)  —  검색/질의가 잘 되게 하는 메타")
        hf.pack(fill="x", padx=0, pady=(0,0))

        rr = ttk.Frame(hf); rr.pack(fill="x", padx=10, pady=6)
        ttk.Label(rr, text="태그(쉼표)", width=12).pack(side="left")
        ttk.Entry(rr, textvariable=self.v_tags, width=60).pack(side="left", padx=6)

        rr = ttk.Frame(hf); rr.pack(fill="x", padx=10, pady=6)
        ttk.Label(rr, text="질문 예시(줄)", width=12).pack(side="left", anchor="n")
        self.t_questions = tk.Text(rr, height=4)
        self.t_questions.pack(side="left", fill="x", expand=True, padx=6)

        rr = ttk.Frame(hf); rr.pack(fill="x", padx=10, pady=(6,10))
        ttk.Label(rr, text="답변 주의", width=12).pack(side="left")
        ttk.Entry(rr, textvariable=self.v_dna, width=60).pack(side="left", padx=6)

        # (중요) 기존에는 하단에 버튼을 뒀는데 화면 크기에 따라 안 보일 수 있어
        # 헤더의 action_bar로 이동. (기능은 동일)

    # ---------- blocks ----------
    def _refresh_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for idx, b in enumerate(self.blocks):
            t = "TEXT" if b["type"]=="text" else "IMAGE"
            ts = b.get("timestamp","")
            prev = (b.get("text","") or "").strip().replace("\n"," ")
            if len(prev) > 60:
                prev = prev[:60] + "…"
            img = b.get("image_path","") if b["type"]=="image" else ""
            self.tree.insert("", "end", iid=str(idx), values=(t, ts, prev, os.path.basename(img) if img else ""))

    def add_text_block(self):
        dlg = tk.Toplevel(self); dlg.title("텍스트 블록 추가"); dlg.geometry("560x420")
        ts = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d %H:%M"))
        ttk.Label(dlg, text="시간(선택)").pack(anchor="w", padx=10, pady=(10,2))
        ttk.Entry(dlg, textvariable=ts).pack(fill="x", padx=10)
        ttk.Label(dlg, text="내용").pack(anchor="w", padx=10, pady=(10,2))
        txt = tk.Text(dlg, height=14); txt.pack(fill="both", expand=True, padx=10)
        def ok():
            self.blocks.append({"type":"text","timestamp":ts.get().strip(),"text":txt.get("1.0","end").strip()})
            dlg.destroy()
            self._refresh_tree()
        ttk.Button(dlg, text="추가", command=ok).pack(pady=10)

    def add_image_blocks(self):
        paths = filedialog.askopenfilenames(title="이미지 선택", filetypes=[("Images","*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.webp"),("All","*.*")])
        if not paths:
            return
        dlg = tk.Toplevel(self); dlg.title("사진+텍스트 블록 추가"); dlg.geometry("560x420")
        ts = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d %H:%M"))
        ttk.Label(dlg, text="시간(선택)").pack(anchor="w", padx=10, pady=(10,2))
        ttk.Entry(dlg, textvariable=ts).pack(fill="x", padx=10)
        ttk.Label(dlg, text="설명(캡션) — 선택한 사진들 각각에 동일하게 적용됩니다").pack(anchor="w", padx=10, pady=(10,2))
        txt = tk.Text(dlg, height=12); txt.pack(fill="both", expand=True, padx=10)
        def ok():
            cap = txt.get("1.0","end").strip()
            for p in paths:
                self.blocks.append({"type":"image","timestamp":ts.get().strip(),"text":cap,"image_path":p})
            dlg.destroy()
            self._refresh_tree()
        ttk.Button(dlg, text=f"{len(paths)}개 추가", command=ok).pack(pady=10)

    def delete_selected_block(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        del self.blocks[idx]
        self._refresh_tree()
        self.txt_preview.delete("1.0","end")
        self.img_canvas.delete("all")

    def _on_select_block(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        b = self.blocks[idx]
        self.txt_preview.delete("1.0","end")
        self.img_canvas.delete("all")
        if b["type"] == "text":
            self.lbl_preview.config(text=f"[TEXT] {b.get('timestamp','')}".strip())
            self.txt_preview.insert("end", b.get("text",""))
            return

        self.lbl_preview.config(text=f"[IMAGE] {b.get('timestamp','')}".strip())
        self.txt_preview.insert("end", b.get("text",""))

        img_path = b.get("image_path","")
        if Image is None or not img_path or not Path(img_path).exists():
            self.img_canvas.create_text(260,130, text="이미지 미리보기를 사용할 수 없습니다.", fill="#666")
            return
        try:
            im = Image.open(img_path)
            im.thumbnail((520,260))
            self._preview_imgtk = ImageTk.PhotoImage(im)
            self.img_canvas.create_image(260,130, image=self._preview_imgtk)
        except Exception:
            self.img_canvas.create_text(260,130, text="이미지 로드 실패", fill="#666")

    # ---------- build/save ----------
    def _build_record_dict(self) -> dict:
        title = self.v_title.get().strip()
        summary = _read_text(self.t_summary)
        tags = [t.strip() for t in (self.v_tags.get() or "").split(",") if t.strip()]
        qs = [q.strip() for q in _read_text(self.t_questions).splitlines() if q.strip()]
        record = {
            "schema_version": 1,
            "header": {
                "customer": self.v_customer.get().strip(),
                "system": self.v_system.get().strip(),
                "category": self.v_category.get().strip(),
                "date_start": self.v_date_start.get().strip(),
                "date_end": self.v_date_end.get().strip(),
                "owner": self.v_owner.get().strip(),
                "title": title,
                "summary": summary,
            },
            "context": {
                "background": _read_text(self.t_background),
                "scope": _read_text(self.t_scope),
                "constraints": _read_text(self.t_constraints),
                "stakeholders": _read_text(self.t_stakeholders),
            },
            "findings": {
                "symptom": _read_text(self.t_symptom),
                "hypothesis": _read_text(self.t_hypothesis),
                "evidence": _read_text(self.t_evidence),
                "decision": _read_text(self.t_decision),
            },
            "actions": {
                "steps": _read_text(self.t_steps),
                "snippets": _read_text(self.t_snippets),
                "rollback": _read_text(self.t_rollback),
                "validation": _read_text(self.t_validation),
            },
            "result": {
                "outcome": _read_text(self.t_outcome),
                "remaining_risks": _read_text(self.t_remaining),
                "next_actions": _read_text(self.t_next),
            },
            "blocks": [],
            "rag_hints": {
                "tags": tags,
                "questions": qs,
                "do_not_answer": (self.v_dna.get() or "").strip(),
            },
        }

        # blocks are stored with copied file names later
        for b in self.blocks:
            record["blocks"].append({
                "type": b["type"],
                "timestamp": b.get("timestamp",""),
                "text": b.get("text",""),
                "image_path": b.get("image_path","") if b["type"]=="image" else "",
            })
        return record

    def _make_record_id(self, record: dict) -> str:
        h = record["header"]
        ymd = (h.get("date_start") or datetime.now().strftime("%Y-%m-%d")).replace("-","")
        base = f"{ymd}_{_slug(h.get('customer',''))}_{_slug(h.get('system',''))}_{_slug(h.get('title',''))}"
        stable = json.dumps(record, ensure_ascii=False, sort_keys=True)
        return f"{base}_{_hash8(stable)}"

    def save_only(self):
        try:
            record = self._build_record_dict()
            if not record["header"]["title"]:
                messagebox.showwarning("필수", "제목은 필수입니다.")
                return
            record_id = self._make_record_id(record)
            rec_dir = self.dataset_root / record_id
            att_dir = rec_dir / "attachments"
            _safe_mkdir(att_dir)

            # copy attachments, rewrite blocks to reference copied filenames
            new_blocks = []
            for b in record["blocks"]:
                if b["type"] == "image":
                    src = Path(b.get("image_path",""))
                    if src.exists():
                        fname = _copy_attachment(src, att_dir)
                        new_blocks.append({"type":"image","timestamp":b.get("timestamp",""),"text":b.get("text",""),"image_file":fname})
                    else:
                        new_blocks.append({"type":"image","timestamp":b.get("timestamp",""),"text":b.get("text",""),"image_file":""})
                else:
                    new_blocks.append({"type":"text","timestamp":b.get("timestamp",""),"text":b.get("text","")})
            record["blocks"] = new_blocks

            # for markdown image prefix
            record["_md_image_prefix"] = "attachments"

            _safe_mkdir(rec_dir)
            (rec_dir / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

            messagebox.showinfo("저장 완료", f"레코드 저장 완료:\n- datasets/records/{record_id}/record.json")
        except Exception as e:
            messagebox.showerror("오류", f"저장 실패: {e}")

    def save_and_generate(self):
        try:
            record = self._build_record_dict()
            if not record["header"]["title"]:
                messagebox.showwarning("필수", "제목은 필수입니다.")
                return
            record_id = self._make_record_id(record)

            # 1) save datasets
            rec_dir = self.dataset_root / record_id
            att_dir = rec_dir / "attachments"
            _safe_mkdir(att_dir)

            new_blocks = []
            for b in record["blocks"]:
                if b["type"] == "image":
                    src = Path(b.get("image_path",""))
                    if src.exists():
                        fname = _copy_attachment(src, att_dir)
                        new_blocks.append({"type":"image","timestamp":b.get("timestamp",""),"text":b.get("text",""),"image_file":fname})
                    else:
                        new_blocks.append({"type":"image","timestamp":b.get("timestamp",""),"text":b.get("text",""),"image_file":""})
                else:
                    new_blocks.append({"type":"text","timestamp":b.get("timestamp",""),"text":b.get("text","")})
            record["blocks"] = new_blocks
            record["_md_image_prefix"] = "attachments"

            _safe_mkdir(rec_dir)
            (rec_dir / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

            # 2) build report.md
            out_record_dir = self.out_dir / "records" / record_id
            _safe_mkdir(out_record_dir)
            report_md = build_report_markdown(record)
            report_path = out_record_dir / "report.md"
            report_path.write_text(report_md, encoding="utf-8")

            # 3) ✅ 오토 태깅: 기존 문서 파이프라인과 동일한 auto_tagging.py 사용
            # - output/records/<record_id>/auto_tags.json 으로 저장됨
            tag_res = auto_tag_document(
                out_root=str(self.out_dir / "records"),
                doc_id=record_id,
                title=record["header"].get("title", ""),
                text=report_md or "",
                language="ko",
                top_k=12,
            )
            tags_topk = tag_res.get("tags_topk", []) if isinstance(tag_res, dict) else []

            # 4) RAG export chunks.jsonl (self-describing chunks)
            rag_dir = out_record_dir / "rag_export"
            _safe_mkdir(rag_dir)

            meta_header = record["header"]
            # tags_topk는 [{tag, score, ...}] 형태이므로 문자열 태그만 뽑아 붙임
            tags_topk_text = []
            for t in (tags_topk or []):
                if isinstance(t, dict) and t.get("tag"):
                    tags_topk_text.append(t["tag"])
            tags_text = ", ".join(tags_topk_text or record.get("rag_hints", {}).get("tags", []))
            prefix = (
                f"[SOURCE] manual_record\n"
                f"[DOC_ID] {record_id}\n"
                f"[CUSTOMER] {meta_header.get('customer','-')}\n"
                f"[SYSTEM] {meta_header.get('system','-')}\n"
                f"[CATEGORY] {meta_header.get('category','-')}\n"
                f"[DATE] {meta_header.get('date_start','-')}~{meta_header.get('date_end','-')}\n"
                f"[TAGS] {tags_text}\n"
                f"---\n"
            )
            chunks = chunk_markdown_for_rag(report_md)
            out_rows = []
            for idx, ch in enumerate(chunks):
                out_rows.append({
                    "doc_id": record_id,
                    "chunk_id": f"{record_id}__c{idx:04d}",
                    "chunk_index": idx,
                    "text": prefix + ch,
                    "tags_topk": tags_topk,
                    "genre": "report",
                })
            chunks_path = rag_dir / "chunks.jsonl"
            with open(chunks_path, "w", encoding="utf-8") as f:
                for r in out_rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")

            # 5) ✅ workspace_payload.jsonl 추가(기존 문서 ingest와 같은 레벨)
            payload = {
                "doc_id": record_id,
                "title": record["header"].get("title", ""),
                "source_path": str((rec_dir / "record.json").resolve()),
                "doc_type": "manual_record",
                "language": "ko",
                "inference_scope": "manual_record",
                "modified_at": datetime.now().isoformat(timespec="seconds"),
                "text": report_md,
                "stats": {"size_bytes": len(report_md.encode("utf-8")), "text_length": len(report_md)},
                "assets": {"extracted_images": []},
                "record_meta": record.get("header", {}),
            }
            ws_path = self.out_dir / "workspace_payload.jsonl"
            ws_path.parent.mkdir(parents=True, exist_ok=True)
            with open(ws_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")

            # 6) ✅ core schema 산출물(artifacts/entities/events/records)도 같이 업데이트
            try:
                core = CoreStore(str(self.out_dir))

                # record 첨부 이미지들은 attachments 폴더에 저장되어 있으므로 file:// URI로 연결
                attachments = []
                for b in record.get("blocks", []) or []:
                    if b.get("type") == "image" and b.get("image_file"):
                        img_abs = (att_dir / b["image_file"]).resolve()
                        attachments.append({"kind": "image", "ref": img_abs.as_uri(), "note": b.get("text", "")})

                # source_path는 "출력(report.md)" 기준으로 잡아도 되고, 원본(record.json) 기준으로 잡아도 됨.
                # 여기서는 RAG/보고서와 일치시키기 위해 report.md 기준으로 설정.
                artifact = build_core_artifact_from_doc(
                    source_path=str(report_path.resolve()),
                    sha256=hashlib.sha256(report_md.encode("utf-8", errors="ignore")).hexdigest(),
                    size_bytes=len(report_md.encode("utf-8")),
                    modified_at=datetime.now().isoformat(timespec="seconds"),
                    ingested_at=datetime.now().isoformat(timespec="seconds"),
                    inference_scope="manual_record",
                    title=record["header"].get("title", ""),
                    language="ko",
                    text=report_md,
                    attachments=attachments,
                )
                artifact_id = core.append_artifact(artifact)

                ents = extract_entities_light(text=report_md, title=record["header"].get("title", ""))
                entity_refs = []
                for e in ents:
                    er = core.upsert_entity(e.get("type", "other"), e.get("name", ""), artifact_id)
                    if er and er.get("entity_id"):
                        entity_refs.append({"entity_id": er["entity_id"], "role": "related"})

                genre = (artifact.get("classification") or {}).get("genre", "report")
                ev_summary = f"[manual_record] {record['header'].get('title','')} ({genre})"
                ev = build_event_from_artifact(
                    artifact_id=artifact_id,
                    event_time=datetime.now().isoformat(timespec="seconds"),
                    summary=ev_summary,
                    entities=entity_refs,
                    genre=genre,
                    evidence=[{"artifact_id": artifact_id, "quote": (report_md.strip().splitlines()[0][:180] if report_md.strip() else "(empty)"), "locator": "line1"}],
                )
                event_id = core.append_event(ev)

                for r in entity_refs:
                    eid = r.get("entity_id")
                    if not eid:
                        continue
                    core.apply_event_to_record(
                        entity_id=eid,
                        event_id=event_id,
                        event_time=datetime.now().isoformat(timespec="seconds"),
                        summary=ev_summary,
                        artifact_id=artifact_id,
                        artifact_title=record["header"].get("title", ""),
                        genre=genre,
                    )
            except Exception:
                # core 출력은 실패해도 레코드/보고서 생성은 깨지지 않게
                pass

            messagebox.showinfo(
                "완료",
                "생성 완료!\n\n"
                f"- 원본 저장: datasets/records/{record_id}/record.json\n"
                f"- 보고서: output/records/{record_id}/report.md\n"
                f"- 오토태그: output/records/{record_id}/auto_tags.json\n"
                f"- RAG Export: output/records/{record_id}/rag_export/chunks.jsonl\n"
                f"- workspace_payload: output/workspace_payload.jsonl\n"
                f"- core: output/core/*"
            )
        except Exception as e:
            messagebox.showerror("오류", f"생성 실패: {e}")
