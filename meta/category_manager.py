"""
카테고리 관리 모듈
- 카테고리 로드/저장/추가 (categories.json)
- 문서별 수동 카테고리 저장/로드 (document_facts.json)
- 장르→카테고리 매핑
"""
import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional

# 기본 카테고리 (categories.json 없을 때 사용)
DEFAULT_CATEGORIES = ["오류/장애", "설정/구성", "절차/가이드", "결과/완료", "참고/개념", "기타"]

# 장르(genre) → 카테고리 매핑 (auto_tags.genre → CATEGORIES)
GENRE_TO_CATEGORY = {
    "issue": "오류/장애",
    "resolution": "결과/완료",
    "procedure": "절차/가이드",
    "report": "결과/완료",
    "policy": "설정/구성",
    "communication": "기타",
    "plan": "결과/완료",
    "contract": "참고/개념",
    "reference": "참고/개념",
    "application": "설정/구성",
    "form": "설정/구성",
    "maintenance": "설정/구성",
    "guide": "절차/가이드",
    "record": "참고/개념",
    "unknown": "기타",
}


def _read_json(path: Path) -> Optional[dict]:
    """JSON 파일 읽기"""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def _write_json(path: Path, obj: dict) -> None:
    """JSON 파일 쓰기"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# =========================
# 카테고리 관리
# =========================


def load_categories(out_root: str) -> List[str]:
    """
    카테고리 목록 로드
    categories.json이 없으면 DEFAULT_CATEGORIES 반환
    """
    path = Path(out_root) / "categories.json"
    if not path.exists():
        return list(DEFAULT_CATEGORIES)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cats = data.get("categories", data) if isinstance(data, dict) else data
        if isinstance(cats, list) and cats:
            return [str(c) for c in cats]
    except Exception:
        pass
    return list(DEFAULT_CATEGORIES)


def save_categories(out_root: str, categories: List[str]) -> None:
    """카테고리 목록 저장"""
    path = Path(out_root) / "categories.json"
    data = {"categories": categories, "updated_at": datetime.now().isoformat(timespec="seconds")}
    _write_json(path, data)


def add_category(out_root: str, name: str) -> bool:
    """새 카테고리 추가 (중복 시 False)"""
    cats = load_categories(out_root)
    name = str(name).strip()
    if not name or name in cats:
        return False
    cats.append(name)
    save_categories(out_root, cats)
    return True


def remove_category(out_root: str, name: str) -> bool:
    """카테고리 제거 (기본 카테고리 '기타'는 제거 불가)"""
    if name == "기타":
        return False
    cats = load_categories(out_root)
    if name not in cats:
        return False
    cats.remove(name)
    save_categories(out_root, cats)
    return True


# =========================
# 문서별 수동 카테고리
# =========================


def load_manual_category(out_root: str, doc_id: str) -> Optional[str]:
    """
    문서의 수동 설정 카테고리 로드
    document_facts.json의 manual_category 반환, 없으면 None
    """
    path = Path(out_root) / doc_id / "document_facts.json"
    data = _read_json(path)
    if not data:
        return None
    return data.get("manual_category")


def load_auto_category(out_root: str, doc_id: str) -> Optional[str]:
    """문서의 K-means 자동 분류 카테고리 로드"""
    path = Path(out_root) / doc_id / "document_facts.json"
    data = _read_json(path)
    if not data:
        return None
    return data.get("auto_category")


def save_auto_category(out_root: str, doc_id: str, category: str, confidence: float = 1.0) -> bool:
    """K-means 자동 분류 결과 저장"""
    path = Path(out_root) / doc_id / "document_facts.json"
    data = _read_json(path)
    if not data:
        return False
    data["auto_category"] = category
    data["auto_category_confidence"] = confidence
    data["auto_category_updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(path, data)
    return True


def save_manual_category(out_root: str, doc_id: str, category: str) -> bool:
    """
    문서의 수동 카테고리 저장
    document_facts.json 업데이트
    """
    path = Path(out_root) / doc_id / "document_facts.json"
    data = _read_json(path)
    if not data:
        return False
    data["manual_category"] = category
    data["manual_category_updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(path, data)
    return True


def get_effective_category(
    out_root: str,
    doc_id: str,
    genre: Optional[str] = None,
    manual_category: Optional[str] = None,
    auto_category: Optional[str] = None,
) -> str:
    """
    문서의 유효 카테고리 결정
    수동 카테고리 > K-means 자동 > 장르 매핑 > 기타
    """
    if manual_category:
        return manual_category
    if auto_category:
        return auto_category
    if genre and genre in GENRE_TO_CATEGORY:
        return GENRE_TO_CATEGORY[genre]
    return "기타"


def genre_to_category(genre: Optional[str]) -> str:
    """장르를 카테고리로 변환"""
    if genre and genre in GENRE_TO_CATEGORY:
        return GENRE_TO_CATEGORY[genre]
    return "기타"
