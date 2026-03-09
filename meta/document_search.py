"""
문서 검색 기능
- 주제문장 기반 우선순위 검색
- 태그 기반 검색
- 장르 기반 필터링
- 2단계 검색 최적화 (태그 기반 선별 + 상세 검색)
- 피드백 기반 가중치 적용
- 증분 인덱싱 (신규/변경 문서만 인덱싱, 삭제 문서 제거)
- 검색 쿼리 LRU 캐싱
"""
import json
from collections import OrderedDict
from hashlib import md5
from pathlib import Path
from typing import List, Dict, Optional, Any, Set, Tuple
from auto_tagging import load_auto_tags

try:
    from category_manager import (
        load_manual_category,
        load_auto_category,
        genre_to_category,
    )
except ImportError:
    def load_manual_category(out_root: str, doc_id: str) -> Optional[str]:
        return None
    def load_auto_category(out_root: str, doc_id: str) -> Optional[str]:
        return None
    def genre_to_category(genre: Optional[str]) -> str:
        return "기타" if not genre else "기타"

# 피드백 관리 모듈 (선택적 import)
try:
    from feedback_manager import load_feedback_data, calculate_feedback_boost, get_feedback_status
    FEEDBACK_AVAILABLE = True
except ImportError:
    FEEDBACK_AVAILABLE = False
    def load_feedback_data(out_root: str) -> Dict:
        return {}
    def calculate_feedback_boost(feedback_summary: Dict) -> float:
        return 1.0
    def get_feedback_status(doc_id: str, feedback_data: Dict) -> str:
        return "none"


# 전역 인덱스 캐시
_tag_index_cache: Optional[Dict[str, Any]] = None
_document_index_cache: Optional[Dict[str, Any]] = None
_index_last_modified: Optional[float] = None


def build_tag_index(out_root: str, force_rebuild: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    태그 역인덱스 및 문서 메타데이터 인덱스 구축
    
    Args:
        out_root: 출력 폴더 경로
        force_rebuild: 강제 재구축 여부
    
    Returns:
        (tag_index, document_index) 튜플
    """
    global _tag_index_cache, _document_index_cache, _index_last_modified
    
    out_path = Path(out_root)
    tag_index_path = out_path / "tag_index.json"
    document_index_path = out_path / "document_index.json"
    payload_path = out_path / "workspace_payload.jsonl"
    
    # 캐시 확인 (파일 수정 시간 기반)
    if not force_rebuild and _tag_index_cache is not None and _document_index_cache is not None:
        if tag_index_path.exists() and document_index_path.exists():
            try:
                tag_index_mtime = tag_index_path.stat().st_mtime
                doc_index_mtime = document_index_path.stat().st_mtime
                payload_mtime = payload_path.stat().st_mtime if payload_path.exists() else 0
                
                # 인덱스가 payload보다 최신이면 캐시 사용
                if (tag_index_mtime >= payload_mtime and 
                    doc_index_mtime >= payload_mtime and
                    _index_last_modified == max(tag_index_mtime, doc_index_mtime)):
                    return _tag_index_cache, _document_index_cache
            except Exception:
                pass
    
    # 증분 인덱싱: 기존 인덱스가 있으면 로드 후 신규/변경만 반영, 삭제 문서 제거
    tag_index: Dict[str, Any] = {}
    document_index: Dict[str, Any] = {}
    if tag_index_path.exists() and document_index_path.exists() and payload_path.exists() and not force_rebuild:
        try:
            tag_index_mtime = tag_index_path.stat().st_mtime
            payload_mtime = payload_path.stat().st_mtime
            if tag_index_mtime >= payload_mtime:
                tag_index = json.loads(tag_index_path.read_text(encoding="utf-8"))
                document_index = json.loads(document_index_path.read_text(encoding="utf-8"))
                _tag_index_cache = tag_index
                _document_index_cache = document_index
                _index_last_modified = max(tag_index_path.stat().st_mtime, document_index_path.stat().st_mtime)
                return tag_index, document_index
        except Exception:
            pass
        try:
            tag_index = json.loads(tag_index_path.read_text(encoding="utf-8"))
            document_index = json.loads(document_index_path.read_text(encoding="utf-8"))
        except Exception:
            tag_index = {}
            document_index = {}
    
    if not payload_path.exists():
        # 빈 인덱스 저장
        tag_index_path.write_text("{}", encoding="utf-8")
        document_index_path.write_text("{}", encoding="utf-8")
        return {}, {}
    
    # 증분 인덱싱: payload에 없는 doc_id는 인덱스에서 제거 (삭제된 문서)
    payload_doc_ids: Set[str] = set()
    payload_docs: List[Dict] = []
    with open(payload_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
                doc_id = doc.get("doc_id")
                if doc_id:
                    payload_doc_ids.add(doc_id)
                    payload_docs.append(doc)
            except Exception:
                continue
    
    deleted_ids = set(document_index.keys()) - payload_doc_ids
    for doc_id in deleted_ids:
        document_index.pop(doc_id, None)
        for tag_lower, tag_data in list(tag_index.items()):
            if doc_id in tag_data.get("doc_ids", []):
                tag_data["doc_ids"] = [d for d in tag_data["doc_ids"] if d != doc_id]
                tag_data.get("doc_metadata", {}).pop(doc_id, None)
            if not tag_data.get("doc_ids"):
                del tag_index[tag_lower]
    
    # workspace_payload.jsonl 기반 인덱스 (신규/변경 문서 반영)
    for doc in payload_docs:
        try:
            doc_id = doc.get("doc_id")
            if not doc_id:
                continue
            # 변경 문서: 기존 태그 역인덱스에서 제거 후 재추가
            for tag_data in tag_index.values():
                if doc_id in tag_data.get("doc_ids", []):
                    tag_data["doc_ids"] = [d for d in tag_data["doc_ids"] if d != doc_id]
                    tag_data.get("doc_metadata", {}).pop(doc_id, None)
            for tag_lower in list(tag_index.keys()):
                if not tag_index[tag_lower].get("doc_ids"):
                    del tag_index[tag_lower]
            # auto_tags.json 로드
            auto_tags = load_auto_tags(out_root, doc_id) or {}
            tags_topk = auto_tags.get("tags_topk", [])
            # 카테고리: 수동 > K-means 자동 > 장르 매핑
            manual_cat = load_manual_category(out_root, doc_id)
            auto_cat = load_auto_category(out_root, doc_id)
            genre = auto_tags.get("genre")
            category = manual_cat or auto_cat or genre_to_category(genre)
            # 문서 메타데이터 인덱스 구축
            document_index[doc_id] = {
                "title": doc.get("title", ""),
                "document_title": doc.get("document_title"),
                "document_created_at": doc.get("document_created_at"),
                "source_path": doc.get("source_path", ""),
                "ingested_at": doc.get("ingested_at"),
                "genre": genre,
                "category": category,
                "topic_sentence": auto_tags.get("topic_sentence"),
                "tags": [t.get("tag", "") for t in tags_topk if t.get("tag")],
                "tag_count": len(tags_topk),
                "has_topic": bool(auto_tags.get("topic_sentence")),
            }
            # 태그 역인덱스 구축 (기존 doc_id 항목은 덮어쓰기)
            for tag_item in tags_topk:
                tag = tag_item.get("tag", "").strip()
                if not tag:
                    continue
                tag_lower = tag.lower()
                if tag_lower not in tag_index:
                    tag_index[tag_lower] = {"doc_ids": [], "doc_metadata": {}}
                if doc_id not in tag_index[tag_lower]["doc_ids"]:
                    tag_index[tag_lower]["doc_ids"].append(doc_id)
                tag_index[tag_lower]["doc_metadata"][doc_id] = {
                    "tag_score": tag_item.get("score", 0.0),
                    "confidence": tag_item.get("confidence", tag_item.get("score", 0.0)),
                    "from_topic": tag_item.get("from_topic", False),
                    "genre": auto_tags.get("genre"),
                    "original_tag": tag
                }
        except Exception:
            continue
    
    # 인덱스 저장
    tag_index_path.write_text(
        json.dumps(tag_index, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    document_index_path.write_text(
        json.dumps(document_index, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    # 캐시 저장
    _tag_index_cache = tag_index
    _document_index_cache = document_index
    _index_last_modified = max(tag_index_path.stat().st_mtime, document_index_path.stat().st_mtime)
    
    return tag_index, document_index


def stage1_filter(
    query: str,
    tag_index: Dict[str, Any],
    document_index: Dict[str, Any],
    genre_filter: Optional[str] = None,
    tag_filter: Optional[List[str]] = None,
    top_k: int = 100
) -> List[str]:
    """
    1단계: 태그 기반 빠른 필터링
    
    Args:
        query: 검색 쿼리
        tag_index: 태그 역인덱스
        document_index: 문서 메타데이터 인덱스
        genre_filter: 장르 필터
        tag_filter: 태그 필터 리스트
        top_k: 선별할 최대 문서 수
    
    Returns:
        선별된 문서 ID 리스트
    """
    query_lower = query.lower()
    query_tokens = set(query_lower.split())
    candidate_scores: Dict[str, float] = {}
    
    # 1. 태그 매칭으로 후보 문서 찾기
    matched_tags: Set[str] = set()
    
    # 정확한 태그 매칭
    if query_lower in tag_index:
        matched_tags.add(query_lower)
    
    # 부분 태그 매칭 (토큰 기반)
    for tag in tag_index.keys():
        tag_tokens = set(tag.split())
        # 검색어 토큰이 태그에 포함되거나, 태그 토큰이 검색어에 포함
        if query_tokens & tag_tokens or any(token in tag for token in query_tokens) or any(tag_token in query_lower for tag_token in tag_tokens):
            matched_tags.add(tag)
    
    # 매칭된 태그로 문서 점수 계산
    for tag in matched_tags:
        tag_data = tag_index[tag]
        for doc_id in tag_data["doc_ids"]:
            if doc_id not in candidate_scores:
                candidate_scores[doc_id] = 0.0
            
            tag_meta = tag_data["doc_metadata"][doc_id]
            tag_score = tag_meta.get("tag_score", 0.0) or tag_meta.get("confidence", 0.0)
            multiplier = 1.5 if tag_meta.get("from_topic", False) else 1.0
            
            # 정확한 매칭은 더 높은 점수
            if query_lower == tag:
                candidate_scores[doc_id] += tag_score * multiplier * 2.0
            elif query_lower in tag or tag in query_lower:
                candidate_scores[doc_id] += tag_score * multiplier * 1.5
            else:
                candidate_scores[doc_id] += tag_score * multiplier
    
    # 2. 장르 필터 적용
    if genre_filter:
        candidate_scores = {
            doc_id: score
            for doc_id, score in candidate_scores.items()
            if doc_id in document_index and document_index[doc_id].get("genre") == genre_filter
        }
    
    # 3. 태그 필터 적용
    if tag_filter:
        tag_filter_lower = [t.lower() for t in tag_filter]
        candidate_scores = {
            doc_id: score
            for doc_id, score in candidate_scores.items()
            if doc_id in document_index and any(
                tag.lower() in [t.lower() for t in document_index[doc_id].get("tags", [])]
                for tag in tag_filter_lower
            )
        }
    
    # 4. 점수 순으로 정렬하고 상위 N개 반환
    sorted_candidates = sorted(
        candidate_scores.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    return [doc_id for doc_id, score in sorted_candidates[:top_k]]


def load_document_text(out_root: str, doc_id: str) -> str:
    """
    문서 본문 텍스트 로드 (지연 로드)
    
    Args:
        out_root: 출력 폴더 경로
        doc_id: 문서 ID
    
    Returns:
        문서 본문 텍스트
    """
    payload_path = Path(out_root) / "workspace_payload.jsonl"
    if not payload_path.exists():
        return ""
    
    with open(payload_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
                if doc.get("doc_id") == doc_id:
                    return doc.get("text", "")
            except Exception:
                continue
    
    return ""


def stage2_detailed_search(
    query: str,
    candidate_doc_ids: List[str],
    document_index: Dict[str, Any],
    out_root: str,
    limit: int = 20
) -> List[Dict]:
    """
    2단계: 선별된 문서에 대한 상세 검색
    
    Args:
        query: 검색 쿼리
        candidate_doc_ids: 선별된 문서 ID 리스트
        document_index: 문서 메타데이터 인덱스
        out_root: 출력 폴더 경로
        limit: 최대 결과 수
    
    Returns:
        검색 결과 리스트 (점수 순)
    """
    results = []
    query_lower = query.lower()
    query_tokens = set(query_lower.split())
    
    # 장르별 검색 가중치
    genre_search_weights = {
        "procedure": {"단계": 1.3, "step": 1.3, "절차": 1.2, "procedure": 1.2},
        "report": {"결과": 1.3, "result": 1.3, "분석": 1.2, "analysis": 1.2, "통계": 1.2},
        "issue": {"문제": 1.4, "issue": 1.4, "오류": 1.3, "error": 1.3, "원인": 1.2},
        "resolution": {"해결": 1.4, "solution": 1.4, "조치": 1.3, "fix": 1.3},
    }
    
    # 선별된 문서만 순회
    for doc_id in candidate_doc_ids:
        if doc_id not in document_index:
            continue
        
        doc_meta = document_index[doc_id]
        
        # 상세 점수 계산
        score = 0.0
        match_reasons = []
        
        # 장르 가중치 계산
        doc_genre = doc_meta.get("genre")
        genre_weight = 1.0
        if doc_genre and doc_genre in genre_search_weights:
            for keyword, weight in genre_search_weights[doc_genre].items():
                if keyword in query_lower:
                    genre_weight = max(genre_weight, weight)
                    break
        
        # 1. 주제문장 매칭 (최고 우선순위)
        topic_sentence = doc_meta.get("topic_sentence")
        if topic_sentence:
            topic_lower = topic_sentence.lower()
            if query_lower in topic_lower:
                score += 100.0 * genre_weight
                match_reasons.append("주제문장 일치")
            elif any(token in topic_lower for token in query_tokens):
                score += 50.0 * genre_weight
                match_reasons.append("주제문장 부분 일치")
        
        # 2. 제목 매칭
        title = doc_meta.get("title", "").lower()
        if query_lower in title:
            score += 30.0 * genre_weight
            match_reasons.append("제목 일치")
        elif any(token in title for token in query_tokens):
            score += 15.0 * genre_weight
            match_reasons.append("제목 부분 일치")
        
        # 3. 태그 매칭 (이미 1단계에서 계산했지만, 더 정확한 점수 계산)
        tags = doc_meta.get("tags", [])
        for tag in tags:
            tag_lower = tag.lower()
            if query_lower == tag_lower:
                score += 20.0 * genre_weight
                match_reasons.append(f"태그 일치: {tag}")
            elif query_lower in tag_lower or tag_lower in query_lower:
                score += 10.0 * genre_weight
                match_reasons.append(f"태그 부분 일치: {tag}")
            elif any(token in tag_lower for token in query_tokens):
                score += 5.0 * genre_weight
        
        # 4. 본문 매칭 (점수가 있을 때만 로드하여 토큰 효율화)
        if score > 0:
            text = load_document_text(out_root, doc_id).lower()
            if text:
                if query_lower in text:
                    score += 5.0 * genre_weight
                    match_reasons.append("본문 일치")
                elif any(token in text for token in query_tokens):
                    score += 1.0 * genre_weight
        
        # 5. 피드백 가중치 적용
        base_score = score
        feedback_boost = 1.0
        feedback_status = "none"
        
        if FEEDBACK_AVAILABLE and score > 0:
            feedback_data = load_feedback_data(out_root)
            doc_feedback = feedback_data.get(doc_id, {})
            feedback_summary = doc_feedback.get("feedback_summary", {})
            feedback_boost = calculate_feedback_boost(feedback_summary)
            feedback_status = get_feedback_status(doc_id, feedback_data)
            
            # 최종 점수에 가중치 적용
            score = score * feedback_boost
        
        if base_score > 0:
            results.append({
                "doc_id": doc_id,
                "title": doc_meta.get("title", ""),
                "score": round(score, 2),  # 가중치 적용된 점수
                "base_score": round(base_score, 2),  # 원본 점수
                "feedback_boost": feedback_boost,  # 가중치
                "match_reasons": match_reasons,
                "genre": doc_genre,
                "topic_sentence": topic_sentence,
                "tags": tags[:5],  # 상위 5개 태그만
                "source_path": doc_meta.get("source_path", ""),
                "feedback_status": feedback_status
            })
    
    # 점수 순으로 정렬
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


# 검색 쿼리 LRU 캐시 (동일 쿼리 즉시 반환)
_SEARCH_CACHE: OrderedDict = OrderedDict()
_SEARCH_CACHE_MAX = 100
_INDEX_MTIME_BY_OUT_ROOT: Dict[str, float] = {}


def _search_cache_key(out_root: str, query: str, genre_filter: Optional[str],
                      tag_filter: Optional[List[str]], limit: int, stage1_topk: int) -> str:
    tag_str = ",".join(sorted(tag_filter)) if tag_filter else ""
    blob = f"{out_root}|{query}|{genre_filter or ''}|{tag_str}|{limit}|{stage1_topk}"
    return md5(blob.encode("utf-8")).hexdigest()


def _is_search_cache_valid(cache_key: str, out_root: str) -> bool:
    """캐시가 인덱스 수정 시간보다 최신인지 확인"""
    tag_index_path = Path(out_root) / "tag_index.json"
    payload_path = Path(out_root) / "workspace_payload.jsonl"
    if not tag_index_path.exists():
        return False
    index_mtime = tag_index_path.stat().st_mtime
    payload_mtime = payload_path.stat().st_mtime if payload_path.exists() else 0
    source_mtime = max(index_mtime, payload_mtime)
    cached = _SEARCH_CACHE.get(cache_key)
    if not cached:
        return False
    cached_source_mtime = cached[1]  # 캐시 생성 시점의 인덱스/payload mtime
    return cached_source_mtime >= source_mtime


def search_documents_optimized(
    out_root: str,
    query: str,
    genre_filter: Optional[str] = None,
    tag_filter: Optional[List[str]] = None,
    limit: int = 20,
    stage1_topk: int = 100,
    use_optimized: bool = True,
    use_cache: bool = True
) -> List[Dict]:
    """
    2단계 검색: 빠른 필터링 + 상세 검색 (LRU 캐시 지원)
    
    Args:
        out_root: 출력 폴더 경로
        query: 검색 쿼리 (키워드)
        genre_filter: 장르 필터 (선택적)
        tag_filter: 태그 필터 리스트 (선택적)
        limit: 최대 결과 수
        stage1_topk: 1단계에서 선별할 문서 수
        use_optimized: 최적화 검색 사용 여부 (False면 기존 방식)
        use_cache: 검색 결과 캐싱 사용 여부
    
    Returns:
        검색 결과 리스트 (우선순위 순서)
    """
    if not use_optimized:
        return search_documents(out_root, query, genre_filter, tag_filter, limit)
    
    cache_key = _search_cache_key(out_root, query, genre_filter, tag_filter, limit, stage1_topk)
    if use_cache and _is_search_cache_valid(cache_key, out_root):
        result = _SEARCH_CACHE[cache_key][0]
        _SEARCH_CACHE.move_to_end(cache_key)  # LRU: 최근 사용으로 이동
        return result
    
    # 인덱스 로드 또는 구축
    tag_index, document_index = build_tag_index(out_root)
    
    if not tag_index or not document_index:
        # 인덱스가 없으면 기존 방식으로 폴백
        return search_documents(out_root, query, genre_filter, tag_filter, limit)
    
    # 1단계: 빠른 필터링
    candidate_doc_ids = stage1_filter(
        query,
        tag_index,
        document_index,
        genre_filter,
        tag_filter,
        top_k=stage1_topk
    )
    
    if not candidate_doc_ids:
        return []
    
    # 2단계: 상세 검색
    results = stage2_detailed_search(
        query,
        candidate_doc_ids,
        document_index,
        out_root,
        limit=limit
    )
    
    # LRU 캐시 저장 (인덱스 mtime 기준 무효화)
    if use_cache:
        tag_index_path = Path(out_root) / "tag_index.json"
        payload_path = Path(out_root) / "workspace_payload.jsonl"
        index_mtime = tag_index_path.stat().st_mtime if tag_index_path.exists() else 0
        payload_mtime = payload_path.stat().st_mtime if payload_path.exists() else 0
        source_mtime = max(index_mtime, payload_mtime)
        _SEARCH_CACHE[cache_key] = (results, source_mtime)
        _SEARCH_CACHE.move_to_end(cache_key)
        while len(_SEARCH_CACHE) > _SEARCH_CACHE_MAX:
            _SEARCH_CACHE.popitem(last=False)
    
    return results


def search_documents(
    out_root: str,
    query: str,
    genre_filter: Optional[str] = None,
    tag_filter: Optional[List[str]] = None,
    limit: int = 20
) -> List[Dict]:
    """
    문서 검색 (주제문장 기반 우선순위 적용) - 기존 방식
    
    Args:
        out_root: 출력 폴더 경로
        query: 검색 쿼리 (키워드)
        genre_filter: 장르 필터 (선택적)
        tag_filter: 태그 필터 리스트 (선택적)
        limit: 최대 결과 수
    
    Returns:
        검색 결과 리스트 (우선순위 순서)
    """
    out_path = Path(out_root)
    payload_path = out_path / "workspace_payload.jsonl"
    
    if not payload_path.exists():
        return []
    
    # 모든 문서 로드
    documents = []
    with open(payload_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    doc = json.loads(line)
                    documents.append(doc)
                except Exception:
                    continue
    
    # 검색 결과 계산
    results = []
    query_lower = query.lower()
    query_tokens = set(query_lower.split())
    
    for doc in documents:
        doc_id = doc.get("doc_id")
        if not doc_id:
            continue
        
        # auto_tags.json 로드
        auto_tags = load_auto_tags(out_root, doc_id) or {}
        
        # 장르 필터링
        if genre_filter:
            doc_genre = auto_tags.get("genre")
            if doc_genre != genre_filter:
                continue
        
        # 태그 필터링
        if tag_filter:
            doc_tags = [t.get("tag", "") for t in auto_tags.get("tags_topk", [])]
            if not any(tag in doc_tags for tag in tag_filter):
                continue
        
        # 점수 계산
        score = 0.0
        match_reasons = []
        
        # 장르와 주제 기반 우선순위 선점
        doc_genre = auto_tags.get("genre")
        topic_sentence = auto_tags.get("topic_sentence")
        
        # 장르별 검색 가중치
        genre_search_weights = {
            "procedure": {"단계": 1.3, "step": 1.3, "절차": 1.2, "procedure": 1.2},
            "report": {"결과": 1.3, "result": 1.3, "분석": 1.2, "analysis": 1.2, "통계": 1.2},
            "issue": {"문제": 1.4, "issue": 1.4, "오류": 1.3, "error": 1.3, "원인": 1.2},
            "resolution": {"해결": 1.4, "solution": 1.4, "조치": 1.3, "fix": 1.3},
        }
        
        genre_weight = 1.0
        if doc_genre and doc_genre in genre_search_weights:
            for keyword, weight in genre_search_weights[doc_genre].items():
                if keyword in query_lower:
                    genre_weight = max(genre_weight, weight)
                    break
        
        # 1. 주제문장 매칭 (최고 우선순위)
        if topic_sentence:
            topic_lower = topic_sentence.lower()
            if query_lower in topic_lower:
                score += 100.0 * genre_weight  # 장르 가중치 적용
                match_reasons.append("주제문장 일치")
            elif any(token in topic_lower for token in query_tokens):
                score += 50.0 * genre_weight
                match_reasons.append("주제문장 부분 일치")
        
        # 2. 제목 매칭
        title = doc.get("title", "").lower()
        if query_lower in title:
            score += 30.0 * genre_weight
            match_reasons.append("제목 일치")
        elif any(token in title for token in query_tokens):
            score += 15.0 * genre_weight
            match_reasons.append("제목 부분 일치")
        
        # 3. 태그 매칭 (장르별 가중치 적용)
        tags_topk = auto_tags.get("tags_topk", [])
        for tag_item in tags_topk:
            tag = tag_item.get("tag", "").lower()
            tag_score = tag_item.get("score", 0.0)
            from_topic = tag_item.get("from_topic", False)
            genre_weight_applied = tag_item.get("genre_weight", 1.0)  # 태그에 적용된 장르 가중치
            
            base_multiplier = (1.5 if from_topic else 1.0) * genre_weight_applied * genre_weight
            
            if query_lower == tag:
                score += 20.0 * tag_score * base_multiplier
                match_reasons.append(f"태그 일치: {tag_item.get('tag')}")
            elif query_lower in tag or tag in query_lower:
                score += 10.0 * tag_score * base_multiplier
                match_reasons.append(f"태그 부분 일치: {tag_item.get('tag')}")
            elif any(token in tag for token in query_tokens):
                score += 5.0 * tag_score * base_multiplier
        
        # 4. 본문 텍스트 매칭 (장르별 가중치 적용)
        text = doc.get("text", "").lower()
        if query_lower in text:
            score += 5.0 * genre_weight
            match_reasons.append("본문 일치")
        elif any(token in text for token in query_tokens):
            score += 1.0 * genre_weight
        
        # 5. 피드백 가중치 적용
        base_score = score
        feedback_boost = 1.0
        feedback_status = "none"
        
        if FEEDBACK_AVAILABLE and score > 0:
            feedback_data = load_feedback_data(out_root)
            doc_feedback = feedback_data.get(doc_id, {})
            feedback_summary = doc_feedback.get("feedback_summary", {})
            feedback_boost = calculate_feedback_boost(feedback_summary)
            feedback_status = get_feedback_status(doc_id, feedback_data)
            
            # 최종 점수에 가중치 적용
            score = score * feedback_boost
        
        # 점수가 0보다 크면 결과에 추가
        if base_score > 0:
            results.append({
                "doc_id": doc_id,
                "title": doc.get("title", ""),
                "score": round(score, 2),  # 가중치 적용된 점수
                "base_score": round(base_score, 2),  # 원본 점수
                "feedback_boost": feedback_boost,  # 가중치
                "match_reasons": match_reasons,
                "genre": auto_tags.get("genre"),
                "topic_sentence": topic_sentence,
                "tags": [t.get("tag") for t in tags_topk[:5]],  # 상위 5개 태그만
                "source_path": doc.get("source_path", ""),
                "feedback_status": feedback_status
            })
    
    # 점수 기준으로 정렬 (내림차순)
    results.sort(key=lambda x: x["score"], reverse=True)
    
    return results[:limit]


def search_by_topic_sentence(
    out_root: str,
    topic_query: str,
    limit: int = 10
) -> List[Dict]:
    """
    주제문장으로 문서 검색 (주제문장이 있는 문서만)
    
    Args:
        out_root: 출력 폴더 경로
        topic_query: 주제문장 검색 쿼리
        limit: 최대 결과 수
    
    Returns:
        검색 결과 리스트
    """
    out_path = Path(out_root)
    payload_path = out_path / "workspace_payload.jsonl"
    
    if not payload_path.exists():
        return []
    
    documents = []
    with open(payload_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    doc = json.loads(line)
                    documents.append(doc)
                except Exception:
                    continue
    
    results = []
    topic_query_lower = topic_query.lower()
    topic_query_tokens = set(topic_query_lower.split())
    
    for doc in documents:
        doc_id = doc.get("doc_id")
        if not doc_id:
            continue
        
        auto_tags = load_auto_tags(out_root, doc_id) or {}
        topic_sentence = auto_tags.get("topic_sentence")
        
        # 주제문장이 없는 문서는 제외
        if not topic_sentence:
            continue
        
        score = 0.0
        topic_lower = topic_sentence.lower()
        
        # 정확한 일치
        if topic_query_lower in topic_lower:
            score = 100.0
        # 토큰 기반 일치
        elif any(token in topic_lower for token in topic_query_tokens):
            matched_tokens = sum(1 for token in topic_query_tokens if token in topic_lower)
            score = (matched_tokens / len(topic_query_tokens)) * 50.0
        
        if score > 0:
            results.append({
                "doc_id": doc_id,
                "title": doc.get("title", ""),
                "score": round(score, 2),
                "topic_sentence": topic_sentence,
                "genre": auto_tags.get("genre"),
                "tags": [t.get("tag") for t in auto_tags.get("tags_topk", [])[:5]],
                "source_path": doc.get("source_path", ""),
            })
    
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
