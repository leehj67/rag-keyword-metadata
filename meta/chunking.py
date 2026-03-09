# chunking.py
from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

# core_store의 stable_artifact_id를 그대로 사용(일관성 확보)
from core_store import stable_artifact_id


def _sha256_hex(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8", errors="ignore")).hexdigest()


def normalize_text(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def build_version_key(file_sha256: str) -> str:
    sh = (file_sha256 or "").strip().lower()
    return "vk_" + (sh[:24] if len(sh) >= 24 else _sha256_hex(sh)[:24])


def build_record_key(title: str, canonical_text: str) -> str:
    # 경로/시간 등 변동 요소 배제: title + canonical_text 기반
    blob = f"{(title or '').strip().lower()}|{normalize_text(canonical_text).lower()}"
    return "rk_" + _sha256_hex(blob)[:24]


@dataclass
class Chunk:
    chunk_index: int
    start_offset: int
    end_offset: int
    text: str
    section_path: str = "unknown"


def _split_sentences_with_spans(text: str) -> List[Tuple[int, int, str]]:
    """
    문장 경계 인식 분리 (. ! ? 。 후 공백/줄바꿈)
    """
    spans: List[Tuple[int, int, str]] = []
    if not text or not text.strip():
        return spans
    # 문장 종결 패턴: . ! ? 。 후 공백 또는 줄바꿈
    pattern = re.compile(r"(?<=[.!?。])\s+(?=[^\s])|\n+")
    last = 0
    for m in pattern.finditer(text):
        start = last
        end = m.start()
        sent = text[start:end].strip()
        if sent:
            spans.append((start, end, sent))
        last = m.end()
    if last < len(text):
        sent = text[last:].strip()
        if sent:
            spans.append((last, len(text), sent))
    return spans


def _split_paragraphs_with_spans(text: str) -> List[Tuple[int, int, str]]:
    """
    빈 줄 기준 단락 분리 + 원문 오프셋 span 유지
    문장 경계를 우선 인식하여 의미 단위 유지
    """
    t = text
    spans: List[Tuple[int, int, str]] = []
    if not t:
        return spans

    # 단락: \n\n 이상을 경계로 분리
    pattern = re.compile(r"\n\s*\n+")
    last = 0
    for m in pattern.finditer(t):
        start = last
        end = m.start()
        para = t[start:end].strip("\n")
        if para.strip():
            spans.append((start, end, para))
        last = m.end()
    # tail
    start = last
    end = len(t)
    para = t[start:end].strip("\n")
    if para.strip():
        spans.append((start, end, para))
    return spans


def _split_by_steps(text: str) -> List[Tuple[int, int, str]]:
    """
    절차 문서: 단계 번호/마커 기반 분리
    예: "1.", "2)", "Step 1", "단계 1" 등
    """
    spans: List[Tuple[int, int, str]] = []
    if not text:
        return spans
    
    # 단계 패턴: 숫자 + 점/괄호, "Step", "단계" 등
    step_patterns = [
        re.compile(r"\n\s*(\d+)[\.\)]\s+"),  # "1.", "2)"
        re.compile(r"\n\s*(Step|STEP|step)\s+(\d+)[\.\)]?\s+", re.IGNORECASE),  # "Step 1"
        re.compile(r"\n\s*단계\s*(\d+)[\.\)]?\s+"),  # "단계 1"
        re.compile(r"\n\s*[가-힣]\.\s+"),  # "가.", "나."
    ]
    
    # 첫 번째 패턴으로 시도
    pattern = step_patterns[0]
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            # 이전 단계까지의 텍스트
            start = last
            end = m.start()
            para = text[start:end].strip("\n")
            if para.strip():
                spans.append((start, end, para))
        last = m.start()
    
    # 마지막 부분
    if last < len(text):
        para = text[last:].strip("\n")
        if para.strip():
            spans.append((last, len(text), para))
    
    # 단계로 분리되지 않으면 단락 기반으로 fallback
    if len(spans) <= 1:
        return _split_paragraphs_with_spans(text)
    
    return spans


def _split_by_sections(text: str) -> List[Tuple[int, int, str]]:
    """
    보고서 문서: 섹션 제목 기반 분리
    예: "##", "제1장", "Chapter 1" 등
    """
    spans: List[Tuple[int, int, str]] = []
    if not text:
        return spans
    
    # 섹션 패턴: 제목, 장, 챕터 등
    section_patterns = [
        re.compile(r"\n\s*(#{1,3})\s+"),  # Markdown 스타일 "## 제목"
        re.compile(r"\n\s*제\s*(\d+)\s*장\s*"),  # "제1장"
        re.compile(r"\n\s*(Chapter|CHAPTER|chapter)\s+(\d+)", re.IGNORECASE),  # "Chapter 1"
        re.compile(r"\n\s*(\d+)\s*\.\s*[A-Z가-힣]"),  # "1. 제목"
    ]
    
    # 첫 번째 패턴으로 시도
    pattern = section_patterns[0]
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            start = last
            end = m.start()
            para = text[start:end].strip("\n")
            if para.strip():
                spans.append((start, end, para))
        last = m.start()
    
    # 마지막 부분
    if last < len(text):
        para = text[last:].strip("\n")
        if para.strip():
            spans.append((last, len(text), para))
    
    # 섹션으로 분리되지 않으면 단락 기반으로 fallback
    if len(spans) <= 1:
        return _split_paragraphs_with_spans(text)
    
    return spans


def _split_by_issue_structure(text: str) -> List[Tuple[int, int, str]]:
    """
    이슈 문서: 문제-원인-해결 구조 기반 분리
    """
    spans: List[Tuple[int, int, str]] = []
    if not text:
        return spans
    
    # 이슈 구조 패턴
    issue_patterns = [
        re.compile(r"\n\s*(문제|현상|증상|오류|장애)[:：]\s*", re.IGNORECASE),
        re.compile(r"\n\s*(원인|원인분석|원인 분석)[:：]\s*", re.IGNORECASE),
        re.compile(r"\n\s*(해결|조치|대응|수정)[:：]\s*", re.IGNORECASE),
        re.compile(r"\n\s*(Problem|Issue|Error)[:：]\s*", re.IGNORECASE),
        re.compile(r"\n\s*(Cause|Root Cause)[:：]\s*", re.IGNORECASE),
        re.compile(r"\n\s*(Solution|Resolution|Fix)[:：]\s*", re.IGNORECASE),
    ]
    
    # 모든 패턴 통합
    all_matches = []
    for pattern in issue_patterns:
        for m in pattern.finditer(text):
            all_matches.append((m.start(), m.group()))
    
    # 위치 순으로 정렬
    all_matches.sort(key=lambda x: x[0])
    
    if not all_matches:
        return _split_paragraphs_with_spans(text)
    
    last = 0
    for pos, label in all_matches:
        if pos > last:
            start = last
            end = pos
            para = text[start:end].strip("\n")
            if para.strip():
                spans.append((start, end, para))
        last = pos
    
    # 마지막 부분
    if last < len(text):
        para = text[last:].strip("\n")
        if para.strip():
            spans.append((last, len(text), para))
    
    if len(spans) <= 1:
        return _split_paragraphs_with_spans(text)
    
    return spans


def make_chunks(
    canonical_text: str,
    target_chars: int = 1000,
    min_chars: int = 250,
    overlap_chars: int = 120,
    genre: Optional[str] = None,
    topic_sentence: Optional[str] = None
) -> List[Chunk]:
    """
    장르별 청킹 전략 적용:
    - procedure: 단계 기반 청킹 (작은 청크, 단계 경계 고려)
    - report: 섹션 기반 청킹 (큰 청크, 섹션 경계 고려)
    - issue: 문제-원인-해결 구조 기반 청킹
    - 기타: 기본 단락 기반 청킹
    
    Args:
        canonical_text: 정규화된 텍스트
        target_chars: 목표 청크 크기
        min_chars: 최소 청크 크기
        overlap_chars: 청크 간 겹침
        genre: 문서 장르
        topic_sentence: 주제문장 (우선순위 선점용)
    """
    text = canonical_text or ""
    if not text.strip():
        return []

    # 장르별 청킹 전략 선택
    if genre == "procedure":
        paras = _split_by_steps(text)
        effective_target = int(target_chars * 0.7)
        effective_min = int(min_chars * 0.8)
    elif genre == "report":
        paras = _split_by_sections(text)
        effective_target = int(target_chars * 1.3)
        effective_min = int(min_chars * 1.2)
    elif genre == "issue":
        paras = _split_by_issue_structure(text)
        effective_target = target_chars
        effective_min = min_chars
    else:
        paras = _split_paragraphs_with_spans(text)
        effective_target = target_chars
        effective_min = min_chars

    # 의미 단위 청킹: 긴 단락을 문장 경계로 세분화
    expanded: List[Tuple[int, int, str]] = []
    for (p_start, p_end, para) in paras:
        if len(para) > effective_target * 1.5:
            sent_spans = _split_sentences_with_spans(para)
            for (s_start, s_end, sent_text) in sent_spans:
                if sent_text.strip():
                    g_start = p_start + s_start
                    g_end = p_start + s_end
                    expanded.append((g_start, g_end, sent_text))
        else:
            expanded.append((p_start, p_end, para))
    paras = expanded

    chunks: List[Chunk] = []

    buf_parts: List[str] = []
    buf_start: int | None = None
    buf_end: int | None = None

    def flush():
        nonlocal buf_parts, buf_start, buf_end
        if buf_start is None or buf_end is None:
            buf_parts = []
            return
        chunk_text = "\n\n".join(buf_parts).strip()
        if chunk_text:
            chunks.append(
                Chunk(
                    chunk_index=len(chunks),
                    start_offset=buf_start,
                    end_offset=buf_end,
                    text=chunk_text,
                    section_path=genre or "unknown",
                )
            )
        buf_parts = []
        buf_start = None
        buf_end = None

    # 주제문장 토큰 추출 (우선순위 선점용)
    topic_keywords: set[str] = set()
    if topic_sentence:
        from auto_tagging import tokenize
        topic_keywords = set(tokenize(topic_sentence))

    for (p_start, p_end, para) in paras:
        # 주제문장 키워드가 포함된 단락에 우선순위 부여 (청크 시작점으로 활용)
        para_lower = para.lower()
        has_topic_keyword = any(kw in para_lower for kw in topic_keywords) if topic_keywords else False
        
        if buf_start is None:
            buf_start = p_start
            buf_end = p_end
            buf_parts = [para]
        else:
            # 주제문장 키워드가 있는 단락은 새 청크 시작 고려
            if has_topic_keyword and len("\n\n".join(buf_parts)) >= effective_min:
                flush()
                buf_start = p_start
                buf_end = p_end
                buf_parts = [para]
                continue
            
            # 다음 단락을 붙였을 때 길이 평가
            next_len = len("\n\n".join(buf_parts)) + 2 + len(para)
            # 최대 크기 제한: 1024 토큰 (문자 수 기준)
            max_chars = 1024
            if next_len <= effective_target and next_len <= max_chars:
                buf_parts.append(para)
                buf_end = p_end
            else:
                # 현재 버퍼가 너무 짧으면(=min 미만) 강제로 붙여서 flush
                # 단, 최대 크기를 초과하지 않는 경우에만
                current_len = len("\n\n".join(buf_parts))
                if current_len < effective_min and next_len <= max_chars:
                    buf_parts.append(para)
                    buf_end = p_end
                    flush()
                else:
                    # 최대 크기 초과 시 강제로 flush
                    if current_len >= max_chars:
                        flush()
                    buf_start = p_start
                    buf_end = p_end
                    buf_parts = [para]

    flush()

    # overlap 적용(뒤에서 overlap_chars 만큼 앞 chunk의 끝 일부를 다음 chunk 앞에 덧붙임)
    if overlap_chars > 0 and len(chunks) > 1:
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            cur = chunks[i]
            # overlap 텍스트는 prev.text의 tail 일부
            tail = prev.text[-overlap_chars:]
            # cur.text 앞에 붙이되 중복/공백 과다 방지
            cur.text = (tail + "\n\n" + cur.text).strip()
            # 오프셋은 "표시/하이라이트" 기준이므로 start_offset은 그대로 유지(안전)

    return chunks


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def _append_jsonl(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _find_evidence_hits(chunk_text: str, evidence_quotes: List[str]) -> List[dict]:
    hits = []
    if not chunk_text or not evidence_quotes:
        return hits
    low = chunk_text.lower()
    for q in evidence_quotes:
        if not q:
            continue
        qn = q.strip()
        if not qn:
            continue
        # 단순 포함 매칭(증명 가능한 1차 구현)
        if qn.lower() in low:
            hits.append({"quote": qn, "score": 1.0})
    return hits


def build_chunks_and_reports(out_root: str, doc_id: str, facts: dict, text: str, target_chars: int = 1000, min_chars: int = 250, overlap_chars: int = 120) -> None:
    """
    - output/core/chunks.jsonl append
    - output/<doc_id>/chunks.json 생성
    - output/<doc_id>/analysis_report.json 생성
    기존 산출물/로직에는 관여하지 않음(추가만).
    
    Args:
        target_chars: 목표 청크 크기 (기본값: 1000)
        min_chars: 최소 청크 크기 (기본값: 250)
        overlap_chars: 청크 간 겹침 (기본값: 120)
    """
    out = Path(out_root)
    doc_dir = out / doc_id
    core_dir = out / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    doc_dir.mkdir(parents=True, exist_ok=True)

    auto_tags = _load_json(doc_dir / "auto_tags.json") or {}
    canonical_text = text or ""
    title = (facts.get("title") or "").strip()
    source_path = facts.get("source_path") or ""
    file_sha256 = facts.get("sha256") or ""
    inference_scope = facts.get("inference_scope") or ""
    language = facts.get("language") or "unknown"
    modified_at = facts.get("modified_at")
    processed_at = facts.get("processed_at")

    artifact_id = stable_artifact_id(source_path, file_sha256)
    record_key = build_record_key(title, canonical_text)
    version_key = build_version_key(file_sha256)

    # 문서 메타(자동태깅 결과)
    genre = auto_tags.get("genre")
    genre_conf = auto_tags.get("genre_confidence")
    tags_topk = auto_tags.get("tags_topk") or []
    evidence_quotes = []
    for ev in (auto_tags.get("genre_evidence") or []):
        q = ev.get("quote")
        if q:
            evidence_quotes.append(q)

    # 주제문장 추출 (우선순위 선점용)
    topic_sentence = auto_tags.get("topic_sentence")
    
    # 1) chunk 생성 (장르별 전략 적용)
    chunks = make_chunks(
        canonical_text=normalize_text(canonical_text),
        target_chars=target_chars,
        min_chars=min_chars,
        overlap_chars=overlap_chars,
        genre=genre,
        topic_sentence=topic_sentence
    )

    # 2) chunk 레코드 작성 + evidence 매핑
    chunk_rows: List[dict] = []
    evidence_mapped = 0

    for ch in chunks:
        hits = _find_evidence_hits(ch.text, evidence_quotes)
        if hits:
            evidence_mapped += len(hits)

        chunk_id = "c_" + _sha256_hex(f"{artifact_id}|{ch.start_offset}|{ch.end_offset}")[:16]

        row = {
            "schema_version": 1,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "doc_id": doc_id,
            "chunk_id": chunk_id,
            "chunk_index": ch.chunk_index,
            "artifact_id": artifact_id,
            "record_key": record_key,
            "version_key": version_key,
            "source_path": source_path,
            "title": title,
            "inference_scope": inference_scope,
            "language": language,
            "modified_at": modified_at,
            "ingested_at": processed_at,
            "section_path": ch.section_path,
            "start_offset": ch.start_offset,
            "end_offset": ch.end_offset,
            "text": ch.text,
            "genre": genre,
            "genre_confidence": genre_conf,
            "tags_topk": tags_topk,
            "evidence_hits": hits,
        }
        chunk_rows.append(row)

    # 3) core/chunks.jsonl append (매번 output 지워도 재생성됨)
    chunks_jsonl = core_dir / "chunks.jsonl"
    for row in chunk_rows:
        _append_jsonl(chunks_jsonl, row)

    # 4) 문서별 chunks.json 저장(디버그/시각화)
    (doc_dir / "chunks.json").write_text(
        json.dumps({"doc_id": doc_id, "record_key": record_key, "version_key": version_key, "chunks": chunk_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 5) 증명용 리포트 생성
    total_evidence = len(evidence_quotes)
    mapped_unique_quotes = 0
    if total_evidence > 0:
        # quote 기준으로 “하나라도 매핑됐는지” 측정
        q_hit = set()
        for row in chunk_rows:
            for h in row.get("evidence_hits", []):
                q_hit.add(h["quote"])
        mapped_unique_quotes = len(q_hit)

    report = {
        "doc_id": doc_id,
        "title": title,
        "artifact_id": artifact_id,
        "record_key": record_key,
        "version_key": version_key,
        "chunk_count": len(chunk_rows),
        "avg_chunk_chars": (sum(len(r["text"]) for r in chunk_rows) / len(chunk_rows)) if chunk_rows else 0,
        "evidence_quote_count": total_evidence,
        "evidence_quote_mapped_unique": mapped_unique_quotes,
        "evidence_quote_mapping_rate": (mapped_unique_quotes / total_evidence) if total_evidence else None,
        "chunking_params": {
            "target_chars": target_chars,
            "min_chars": min_chars,
            "overlap_chars": overlap_chars
        },
        # metadata filter 효과를 "예시"로 기록(genre 기준)
        "metadata_filter_demo": {
            "genre": genre,
            "candidate_chunks_before": len(chunk_rows),
            "candidate_chunks_after_genre_filter": len(chunk_rows) if genre else len(chunk_rows),
        },
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (doc_dir / "analysis_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
