"""
K-means 기반 문서 카테고리 자동 분류
- ko-sbert 임베딩 사용
- 클러스터 → 카테고리 매핑 (수동 라벨 기반 다수결)
- 가중치: 수동 > 자동, 신뢰도 기반 선택 가능
"""
import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from collections import Counter

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

try:
    from sklearn.cluster import KMeans
    import numpy as np
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

from category_manager import (
    load_categories,
    load_manual_category,
    genre_to_category,
    save_auto_category,
)
from auto_tagging import load_auto_tags


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


def run_kmeans_classification(
    out_root: str,
    use_manual_as_seed: bool = True,
    min_docs: int = 2,
) -> Dict[str, Any]:
    """
    K-means로 문서 자동 카테고리 분류
    
    Args:
        out_root: 출력 폴더 경로
        use_manual_as_seed: 수동 카테고리가 있는 문서를 시드로 클러스터→카테고리 매핑에 사용
        min_docs: 최소 문서 수 미만이면 건너뜀
    
    Returns:
        {"success": bool, "updated_count": int, "error": str}
    """
    if not SENTENCE_TRANSFORMERS_AVAILABLE:
        return {"success": False, "updated_count": 0, "error": "sentence-transformers 미설치"}
    if not SKLEARN_AVAILABLE:
        return {"success": False, "updated_count": 0, "error": "sklearn 미설치"}

    out_path = Path(out_root)
    payload_path = out_path / "workspace_payload.jsonl"
    if not payload_path.exists():
        return {"success": False, "updated_count": 0, "error": "workspace_payload.jsonl 없음"}

    payloads = _read_jsonl(payload_path)
    if len(payloads) < min_docs:
        return {"success": False, "updated_count": 0, "error": f"문서 수 부족 (최소 {min_docs}개)"}

    categories = load_categories(out_root)
    k = min(len(categories), len(payloads))

    # (doc_id, text, manual_cat, genre) 수집
    docs = []
    for p in payloads:
        doc_id = p.get("doc_id")
        if not doc_id:
            continue
        text = (p.get("text") or "").strip()
        if not text:
            text = p.get("title", "")
        manual_cat = load_manual_category(out_root, doc_id)
        auto_tags = load_auto_tags(out_root, doc_id) or {}
        genre = auto_tags.get("genre")
        docs.append({
            "doc_id": doc_id,
            "text": text[:4000] if text else "",  # 임베딩 길이 제한
            "manual_category": manual_cat,
            "genre": genre,
            "title": p.get("title", ""),
        })

    if len(docs) < min_docs:
        return {"success": False, "updated_count": 0, "error": f"유효 문서 수 부족 (최소 {min_docs}개)"}

    # 임베딩
    try:
        model = SentenceTransformer("jhgan/ko-sbert-sts")
    except Exception as e:
        return {"success": False, "updated_count": 0, "error": f"임베딩 모델 로드 실패: {e}"}

    texts = [d["text"] or d["title"] or " " for d in docs]
    embeddings = model.encode(texts, show_progress_bar=False)
    embeddings = np.array(embeddings, dtype=np.float32)

    # K-means
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = kmeans.fit_predict(embeddings)

    # 클러스터 → 카테고리 매핑 (수동 라벨 다수결)
    cluster_to_category: Dict[int, str] = {}
    for cluster_id in range(k):
        cluster_docs = [d for d, l in zip(docs, labels) if l == cluster_id]
        votes = []
        for d in cluster_docs:
            if use_manual_as_seed and d["manual_category"] and d["manual_category"] in categories:
                votes.append(d["manual_category"])
            else:
                cat = genre_to_category(d["genre"])
                if cat in categories:
                    votes.append(cat)
        if votes:
            cluster_to_category[cluster_id] = Counter(votes).most_common(1)[0][0]
        else:
            cluster_to_category[cluster_id] = categories[0] if categories else "기타"

    # 센트로이드 거리 기반 신뢰도 (0~1, 가까울수록 높음)
    centroids = kmeans.cluster_centers_
    updated = 0
    for i, d in enumerate(docs):
        cluster_id = int(labels[i])
        cat = cluster_to_category.get(cluster_id, "기타")
        dist = np.linalg.norm(embeddings[i] - centroids[cluster_id])
        max_dist = max(np.linalg.norm(embeddings - centroids[cluster_id], axis=1))
        confidence = 1.0 - (dist / (max_dist + 1e-8)) * 0.5  # 대략 0.5~1.0

        # 수동 카테고리가 있으면 자동 분류 결과를 저장하지 않음 (덮어쓰지 않음)
        if d["manual_category"]:
            continue
        save_auto_category(out_root, d["doc_id"], cat, float(confidence))
        updated += 1

    return {"success": True, "updated_count": updated, "error": None}
