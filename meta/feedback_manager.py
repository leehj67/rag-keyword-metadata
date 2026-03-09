"""
검색 결과 피드백 관리 모듈
- 좋아요/좋아요 안함 피드백 저장
- 피드백 기반 검색 점수 가중치 계산
- 메타데이터 업데이트
"""
import json
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime


def load_feedback_data(out_root: str) -> Dict[str, Dict]:
    """피드백 데이터 로드"""
    feedback_path = Path(out_root) / "document_feedback.json"
    
    if not feedback_path.exists():
        return {}
    
    try:
        return json.loads(feedback_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[피드백] 로드 실패: {e}")
        return {}


def save_feedback(
    out_root: str,
    doc_id: str,
    query: str,
    feedback: str,  # "like" or "dislike"
    session_id: str,
    user: str = "user"
) -> None:
    """피드백 저장"""
    feedback_path = Path(out_root) / "document_feedback.json"
    
    # 기존 데이터 로드
    feedback_data = load_feedback_data(out_root)
    
    # 문서 정보 가져오기
    doc_title = get_document_title(out_root, doc_id)
    
    # 문서 피드백 초기화 (없으면)
    if doc_id not in feedback_data:
        feedback_data[doc_id] = {
            "doc_id": doc_id,
            "title": doc_title,
            "feedback_history": [],
            "feedback_summary": {
                "total_likes": 0,
                "total_dislikes": 0,
                "like_ratio": 0.0,
                "last_feedback": None,
                "last_feedback_type": None
            },
            "search_boost": 1.0
        }
    
    # 피드백 이력 추가
    feedback_entry = {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "feedback": feedback,
        "user": user,
        "session_id": session_id
    }
    
    feedback_data[doc_id]["feedback_history"].append(feedback_entry)
    
    # 요약 정보 업데이트
    summary = feedback_data[doc_id]["feedback_summary"]
    
    if feedback == "like":
        summary["total_likes"] = summary.get("total_likes", 0) + 1
    else:
        summary["total_dislikes"] = summary.get("total_dislikes", 0) + 1
    
    total = summary["total_likes"] + summary["total_dislikes"]
    summary["like_ratio"] = summary["total_likes"] / total if total > 0 else 0.0
    summary["last_feedback"] = feedback_entry["timestamp"]
    summary["last_feedback_type"] = feedback
    
    # 검색 가중치 계산
    feedback_data[doc_id]["search_boost"] = calculate_feedback_boost(summary)
    
    # 저장
    feedback_path.write_text(
        json.dumps(feedback_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def calculate_feedback_boost(feedback_summary: Dict) -> float:
    """피드백 기반 검색 점수 가중치 계산"""
    total_likes = feedback_summary.get("total_likes", 0)
    total_dislikes = feedback_summary.get("total_dislikes", 0)
    total_feedback = total_likes + total_dislikes
    
    if total_feedback == 0:
        return 1.0
    
    like_ratio = total_likes / total_feedback
    
    # 가중치 계산: 0.5 ~ 2.0
    boost = 0.5 + (like_ratio * 1.5)
    
    # 최근 피드백 보너스 (7일 이내)
    last_feedback = feedback_summary.get("last_feedback")
    if last_feedback:
        try:
            last_date = datetime.fromisoformat(last_feedback)
            days_ago = (datetime.now() - last_date).days
            
            if days_ago <= 7:
                recent_bonus = 0.2 * (1 - days_ago / 7)
                boost = min(2.0, boost + recent_bonus)
        except:
            pass
    
    return round(boost, 2)


def update_metadata_with_feedback(out_root: str, doc_id: str) -> None:
    """메타데이터에 피드백 정보 업데이트"""
    feedback_data = load_feedback_data(out_root)
    doc_feedback = feedback_data.get(doc_id)
    
    if not doc_feedback:
        return
    
    summary = doc_feedback.get("feedback_summary", {})
    
    # 1. auto_tags.json 업데이트
    doc_dir = Path(out_root) / doc_id
    auto_tags_path = doc_dir / "auto_tags.json"
    
    if auto_tags_path.exists():
        try:
            auto_tags = json.loads(auto_tags_path.read_text(encoding="utf-8"))
            
            auto_tags["search_feedback"] = {
                "total_likes": summary.get("total_likes", 0),
                "total_dislikes": summary.get("total_dislikes", 0),
                "like_ratio": summary.get("like_ratio", 0.0),
                "search_boost": doc_feedback.get("search_boost", 1.0),
                "last_feedback": summary.get("last_feedback"),
                "last_feedback_type": summary.get("last_feedback_type")
            }
            
            auto_tags_path.write_text(
                json.dumps(auto_tags, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"[피드백] auto_tags.json 업데이트 실패: {e}")
    
    # 2. workspace_payload.jsonl 업데이트
    payload_path = Path(out_root) / "workspace_payload.jsonl"
    
    if payload_path.exists():
        try:
            updated_payloads = []
            
            with payload_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                        
                        if payload.get("doc_id") == doc_id:
                            payload["search_feedback"] = {
                                "total_likes": summary.get("total_likes", 0),
                                "total_dislikes": summary.get("total_dislikes", 0),
                                "like_ratio": summary.get("like_ratio", 0.0),
                                "search_boost": doc_feedback.get("search_boost", 1.0)
                            }
                        
                        updated_payloads.append(payload)
                    except:
                        pass
            
            # 파일 재작성
            with payload_path.open("w", encoding="utf-8") as f:
                for payload in updated_payloads:
                    f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[피드백] workspace_payload.jsonl 업데이트 실패: {e}")


def get_document_title(out_root: str, doc_id: str) -> str:
    """문서 제목 가져오기"""
    payload_path = Path(out_root) / "workspace_payload.jsonl"
    
    if not payload_path.exists():
        return "제목 없음"
    
    try:
        with payload_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    doc = json.loads(line)
                    if doc.get("doc_id") == doc_id:
                        return doc.get("title", "제목 없음")
                except:
                    pass
    except:
        pass
    
    return "제목 없음"


def get_feedback_status(doc_id: str, feedback_data: Dict) -> str:
    """문서의 피드백 상태 확인"""
    doc_feedback = feedback_data.get(doc_id, {})
    summary = doc_feedback.get("feedback_summary", {})
    
    total_likes = summary.get("total_likes", 0)
    total_dislikes = summary.get("total_dislikes", 0)
    
    if total_likes > total_dislikes:
        return "liked"
    elif total_dislikes > total_likes:
        return "disliked"
    else:
        return "none"


def get_feedback_info(doc_id: str, feedback_data: Dict) -> Dict:
    """피드백 정보 가져오기"""
    feedback_summary = feedback_data.get(doc_id, {}).get("feedback_summary", {})
    
    total_likes = feedback_summary.get("total_likes", 0)
    total_dislikes = feedback_summary.get("total_dislikes", 0)
    
    if total_likes == 0 and total_dislikes == 0:
        return {
            "display": "-",
            "boost": 1.0,
            "status": "none"
        }
    
    # 표시 형식
    if total_likes > 0 and total_dislikes == 0:
        display = f"👍 {total_likes}"
    elif total_dislikes > 0 and total_likes == 0:
        display = f"👎 {total_dislikes}"
    else:
        display = f"👍 {total_likes} 👎 {total_dislikes}"
    
    # 가중치 계산
    boost = calculate_feedback_boost(feedback_summary)
    
    return {
        "display": display,
        "boost": boost,
        "status": "liked" if total_likes > total_dislikes else ("disliked" if total_dislikes > total_likes else "neutral")
    }
