import os
import re
import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional


# =========================
# Core Schema v1
# =========================
SCHEMA_VERSION = 1

DEFAULT_GENRES = [
    "procedure", "issue", "resolution", "policy", "report",
    "request", "communication", "plan", "contract", "reference", "unknown"
]


def _now_iso_local() -> str:
    # local timezone-aware ISO
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_jsonl_append(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _safe_jsonl_read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _hash16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()[:16]


def stable_artifact_id(source_path: str, sha256: str) -> str:
    # source_path+sha256 기반: 파일 변경 시 sha256이 달라지므로 신규 artifact로 들어감
    return "a_" + _hash16(f"{source_path}|{sha256}")


def stable_entity_id(entity_type: str, name: str) -> str:
    return "e_" + _hash16(f"{entity_type}|{name}".lower().strip())


def new_event_id(source_artifact_id: str, event_time: str, summary: str) -> str:
    # deterministic-ish: 같은 artifact/time/summary면 동일 event_id가 나올 수 있음(중복 방지에 도움)
    return "ev_" + _hash16(f"{source_artifact_id}|{event_time}|{summary}")


def normalize_tag(tag: str) -> str:
    t = (tag or "").strip()
    if not t:
        return ""
    if t.startswith("#"):
        t = t[1:]
    t = re.sub(r"\s+", "_", t)
    return t.lower()


def topk_tags_from_text(text: str, k: int = 12) -> list[dict]:
    """
    매우 가벼운 기본 태깅(v1):
    - 알파/한글 토큰 추출
    - 길이 2 이상
    - 빈도 상위 k
    점수는 상대빈도(정규화)
    ※ 이후 TF-IDF/RAKE/TextRank로 교체 가능(플러그인화 대상)
    """
    if not text:
        return []
    tokens = re.findall(r"[A-Za-z0-9_]+|[가-힣]{2,}", text)
    freq: dict[str, int] = {}
    for tok in tokens:
        tok = normalize_tag(tok)
        if not tok:
            continue
        if len(tok) < 2:
            continue
        # 숫자만은 제거
        if re.fullmatch(r"\d+", tok):
            continue
        freq[tok] = freq.get(tok, 0) + 1

    if not freq:
        return []
    items = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:k]
    maxv = items[0][1]
    out = [{"tag": t, "score": round(v / maxv, 4)} for t, v in items]
    return out


def classify_genre_light(text: str, title: str = "") -> dict:
    """
    초경량 장르 분류(v1) — 제품 데모용 / 이후 교체 가능
    결과:
      {genre, confidence, evidence:[{quote, locator}]}
    """
    blob = f"{title}\n{text}".lower()

    rules = [
        ("issue",      [r"error", r"exception", r"장애", r"오류", r"fail", r"실패", r"cannot", r"no route", r"timeout"]),
        ("resolution", [r"조치", r"해결", r"완료", r"수정", r"재기동", r"rollback", r"롤백"]),
        ("procedure",  [r"절차", r"가이드", r"매뉴얼", r"방법", r"how to", r"설정 방법", r"체크리스트"]),
        ("policy",     [r"정책", r"규정", r"표준", r"준수", r"보안", r"권한"]),
        ("report",     [r"보고", r"결과", r"분석", r"리포트", r"요약", r"현황"]),
        ("communication",[r"회의", r"통화", r"메일", r"요청", r"문의", r"답변"]),
        ("plan",       [r"계획", r"일정", r"roadmap", r"todo", r"task"]),
        ("contract",   [r"계약", r"제안", r"견적", r"사업", r"발주"]),
        ("reference",  [r"개념", r"참고", r"링크", r"용어", r"정리"]),
        ("application", [r"application", r"apply", r"request", r"신청", r"신청서", r"제출", r"지원"]),
        ("form",       [r"form", r"template", r"양식", r"서식", r"템플릿", r"format"]),
        ("maintenance", [r"maintenance", r"유지보수", r"점검", r"정기", r"check", r"점검서", r"유지", r"보수"]),
        ("guide",      [r"guide", r"manual", r"설명서", r"가이드북", r"사용법", r"tutorial"]),
        ("record",     [r"record", r"기록", r"일지", r"로그", r"이력", r"history", r"기록서"]),
    ]

    matched: list[tuple[str, int]] = []
    for g, pats in rules:
        score = 0
        for p in pats:
            if re.search(p, blob):
                score += 1
        if score:
            matched.append((g, score))

    if not matched:
        return {"genre": "unknown", "confidence": 0.2, "evidence": []}

    matched.sort(key=lambda x: x[1], reverse=True)
    genre, score = matched[0]
    confidence = min(0.95, 0.35 + 0.12 * score)

    # evidence: 텍스트에서 매칭된 한 줄 정도만
    ev = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    locator = "line?"
    for ln in lines[:80]:
        low = ln.lower()
        for p in sum([pats for g, pats in rules if g == genre], []):
            if re.search(p, low):
                ev.append({"quote": ln[:180], "locator": locator})
                break
        if len(ev) >= 3:
            break

    return {"genre": genre, "confidence": float(round(confidence, 3)), "evidence": ev}


def extract_entities_light(text: str, title: str = "") -> list[dict]:
    """
    초경량 엔티티 추출(v1):
    - 고객사: "K사", "(주)OO", "OO 고객사" 류
    - 제품/시스템: JEUS/WebtoB/Tomcat/PostgreSQL/XEDRM 등 키워드
    - 버전: 1.2 / 6.7 / 5.8 형태
    - 이슈: error code / exception class 일부
    ※ 이후 NER/사전/사용자 검증 루프로 강화
    """
    blob = f"{title}\n{text}"
    out: list[dict] = []

    # customer heuristic
    # 예: "K사", "A사", "OO고객사"
    for m in re.finditer(r"([A-Za-z가-힣0-9]{1,8})\s*사\b", blob):
        name = m.group(0).strip()
        if len(name) <= 1:
            continue
        out.append({"type": "customer", "name": name})

    # product/system keywords
    products = [
        ("product", "JEUS"),
        ("product", "WebtoB"),
        ("product", "Tomcat"),
        ("product", "PostgreSQL"),
        ("product", "Oracle"),
        ("product", "Tibero"),
        ("product", "XEDRM"),
        ("product", "XEDM"),
    ]
    low = blob.lower()
    for et, kw in products:
        if kw.lower() in low:
            out.append({"type": et, "name": kw})

    # version pattern (e.g. 6.7, 5.8.1)
    for m in re.finditer(r"\b\d+\.\d+(?:\.\d+)?\b", blob):
        v = m.group(0)
        out.append({"type": "version", "name": v})

    # exception patterns
    for m in re.finditer(r"\b[A-Za-z_]+Exception\b", blob):
        out.append({"type": "issue", "name": m.group(0)})

    # error codes like ORA-00936
    for m in re.finditer(r"\b[A-Z]{2,5}-\d{3,5}\b", blob):
        out.append({"type": "issue", "name": m.group(0)})

    # dedupe by (type,name)
    seen = set()
    dedup = []
    for e in out:
        key = (e["type"], e["name"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(e)

    return dedup


@dataclass
class CoreStore:
    out_root: str

    def __post_init__(self):
        self.out_root_p = Path(self.out_root)
        self.core_dir = self.out_root_p / "core"
        self.records_dir = self.core_dir / "records"
        self.core_dir.mkdir(parents=True, exist_ok=True)
        self.records_dir.mkdir(parents=True, exist_ok=True)

        self.artifacts_path = self.core_dir / "artifacts.jsonl"
        self.entities_path = self.core_dir / "entities.jsonl"
        self.events_path = self.core_dir / "events.jsonl"
        self.edges_path = self.core_dir / "edges.jsonl"  # optional

    # ---------- upsert helpers ----------
    def _load_entities_index(self) -> dict[tuple[str, str], dict]:
        idx: dict[tuple[str, str], dict] = {}
        for r in _safe_jsonl_read(self.entities_path):
            et = (r.get("type") or "").strip()
            nm = (r.get("name") or "").strip()
            if not et or not nm:
                continue
            idx[(et, nm)] = r
        return idx

    def upsert_entity(self, entity_type: str, name: str, first_seen_artifact_id: str) -> dict:
        entity_type = (entity_type or "other").strip()
        name = (name or "").strip()
        if not name:
            # skip empty
            return {}

        existing = None
        idx = self._load_entities_index()
        existing = idx.get((entity_type, name))

        now = _now_iso_local()
        eid = stable_entity_id(entity_type, name)

        if existing:
            # "update" by appending a new line (jsonl append) is messy.
            # v1 approach: append a new entity record with updated_at; consumers take latest by entity_id.
            updated = dict(existing)
            updated["schema_version"] = SCHEMA_VERSION
            updated["entity_id"] = existing.get("entity_id", eid)
            updated["updated_at"] = now
            updated.setdefault("provenance", {})
            updated["provenance"]["last_seen_artifact_id"] = first_seen_artifact_id
            _safe_jsonl_append(self.entities_path, updated)
            return updated

        rec = {
            "schema_version": SCHEMA_VERSION,
            "entity_id": eid,
            "type": entity_type,
            "name": name,
            "aliases": [],
            "keys": {},
            "created_at": now,
            "updated_at": now,
            "provenance": {
                "first_seen_artifact_id": first_seen_artifact_id,
                "last_seen_artifact_id": first_seen_artifact_id
            }
        }
        _safe_jsonl_append(self.entities_path, rec)
        return rec

    # ---------- artifact ----------
    def append_artifact(self, artifact: dict) -> str:
        artifact = dict(artifact)
        artifact["schema_version"] = SCHEMA_VERSION
        if "artifact_id" not in artifact or not artifact["artifact_id"]:
            # try build from source
            sp = artifact.get("source", {}).get("path", "")
            sh = artifact.get("source", {}).get("sha256", "")
            artifact["artifact_id"] = stable_artifact_id(sp, sh) if sp and sh else "a_" + _hash16(json.dumps(artifact, ensure_ascii=False))

        _safe_jsonl_append(self.artifacts_path, artifact)
        return artifact["artifact_id"]

    # ---------- event ----------
    def append_event(self, event: dict) -> str:
        event = dict(event)
        event["schema_version"] = SCHEMA_VERSION

        if "event_id" not in event or not event["event_id"]:
            src_aid = (event.get("source") or {}).get("artifact_id", "") or event.get("source_artifact_id", "")
            et = event.get("event_time", "") or _now_iso_local()
            sm = event.get("summary", "") or "event"
            event["event_id"] = new_event_id(src_aid, et, sm)

        _safe_jsonl_append(self.events_path, event)
        return event["event_id"]

    # ---------- record ----------
    def load_record(self, entity_id: str) -> dict:
        p = self.records_dir / f"{entity_id}.json"
        if not p.exists():
            return {
                "schema_version": SCHEMA_VERSION,
                "entity_id": entity_id,
                "snapshot": {"status": "unknown", "fields": {}},
                "timeline": [],
                "linked_artifacts": [],
                "updated_at": _now_iso_local()
            }
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {
                "schema_version": SCHEMA_VERSION,
                "entity_id": entity_id,
                "snapshot": {"status": "unknown", "fields": {}},
                "timeline": [],
                "linked_artifacts": [],
                "updated_at": _now_iso_local()
            }

    def save_record(self, record: dict):
        record = dict(record)
        record["schema_version"] = SCHEMA_VERSION
        record["updated_at"] = _now_iso_local()
        p = self.records_dir / f"{record['entity_id']}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def apply_event_to_record(self, entity_id: str, event_id: str, event_time: str, summary: str,
                              artifact_id: str, artifact_title: str, genre: str):
        rec = self.load_record(entity_id)

        # timeline append (keep recent 200)
        rec.setdefault("timeline", [])
        rec["timeline"].append({"event_id": event_id, "event_time": event_time, "summary": summary})
        rec["timeline"] = sorted(rec["timeline"], key=lambda x: x.get("event_time", ""))[-200:]

        # linked artifacts append (dedupe by artifact_id)
        rec.setdefault("linked_artifacts", [])
        exists = {x.get("artifact_id") for x in rec["linked_artifacts"]}
        if artifact_id not in exists:
            rec["linked_artifacts"].append({"artifact_id": artifact_id, "title": artifact_title, "genre": genre})

        # status heuristic
        snap = rec.setdefault("snapshot", {"status": "unknown", "fields": {}})
        if genre in ("issue",):
            snap["status"] = "active"
        elif genre in ("resolution",):
            # resolution 문서가 들어오면 active->unknown으로 내리는 정도(도메인 플러그인에서 더 정확히)
            if snap.get("status") == "active":
                snap["status"] = "unknown"

        self.save_record(rec)


def build_core_artifact_from_doc(
    *,
    source_path: str,
    sha256: str,
    size_bytes: int,
    modified_at: str,
    ingested_at: str,
    inference_scope: str,
    title: str,
    language: str,
    text: str,
    attachments: Optional[list[dict]] = None
) -> dict:
    genre_info = classify_genre_light(text=text, title=title)
    tags_topk = topk_tags_from_text(text=text, k=12)

    artifact = {
        "artifact_id": stable_artifact_id(source_path, sha256),
        "type": "document",
        "title": title,
        "source": {
            "source_type": "file",
            "path": source_path,
            "origin_app": "app.py",
            "sha256": sha256,
            "size_bytes": size_bytes,
            "modified_at": modified_at,
            "ingested_at": ingested_at,
        },
        "content": {
            "language": language,
            "text": text,
            "text_length": len(text or ""),
            "attachments": attachments or [],
        },
        "classification": {
            "genre": genre_info["genre"],
            "confidence": genre_info["confidence"],
            "evidence": genre_info.get("evidence", []),
        },
        "tags": {
            "topk": tags_topk
        },
        "entities_hint": [],
        "meta": {
            "inference_scope": inference_scope,
            "notes": ""
        }
    }
    return artifact


def build_event_from_artifact(
    *,
    artifact_id: str,
    event_time: str,
    summary: str,
    entities: list[dict],
    genre: str,
    evidence: Optional[list[dict]] = None
) -> dict:
    """
    v1: 문서가 들어왔다는 사실(ingest)을 Event로 남김
    """
    ev = {
        "event_id": new_event_id(artifact_id, event_time, summary),
        "event_time": event_time,
        "event_type": "info_added",
        "summary": summary,
        "entities": entities,
        "claims": [
            {
                "field": "artifact.genre",
                "op": "set",
                "value": genre,
                "confidence": 0.6,
                "evidence": (evidence or [])
            }
        ],
        "source": {"artifact_id": artifact_id}
    }
    return ev
