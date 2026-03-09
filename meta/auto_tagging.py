import json
import math
import re
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Any, Optional, Dict, List, Set, Tuple

# PyTorch pin_memory 경고 필터링 (CPU 환경에서 불필요한 경고)
warnings.filterwarnings('ignore', message='.*pin_memory.*', category=UserWarning)

# 다중 알고리즘 태깅을 위한 선택적 import
# MULTI_RAKE: 언어 독립적인 RAKE 구현 (형태소 분석 불필요)
try:
    from multi_rake import Rake
    MULTI_RAKE_AVAILABLE = True
except ImportError:
    MULTI_RAKE_AVAILABLE = False
    # 하위 호환성: rake-nltk도 확인
    try:
        import rake_nltk
        RAKE_NLTK_AVAILABLE = True
    except ImportError:
        RAKE_NLTK_AVAILABLE = False
else:
    RAKE_NLTK_AVAILABLE = False  # MULTI_RAKE 사용 시 rake-nltk 불필요

# 한국어 형태소 분석 (Kiwipiepy - 빠르고 가벼움)
try:
    from kiwipiepy import Kiwi
    KIWIPIEPY_AVAILABLE = True
    KIWI_TAGGER = None  # 지연 초기화
except ImportError:
    KIWIPIEPY_AVAILABLE = False
    KIWI_TAGGER = None

# 한국어 형태소 분석 (KoNLPy - 하위 호환성)
try:
    from konlpy.tag import Okt, Kkma
    KONLPY_AVAILABLE = True
    KONLPY_TAGGER = None  # 지연 초기화
    _KONLPY_INIT_FAILED = False  # 초기화 실패 플래그
except ImportError:
    KONLPY_AVAILABLE = False
    KONLPY_TAGGER = None
    _KONLPY_INIT_FAILED = True  # 패키지가 없으면 실패로 간주

try:
    import yake
    YAKE_AVAILABLE = True
except ImportError:
    YAKE_AVAILABLE = False

# 의미 기반 신뢰도 보정을 위한 선택적 import
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

try:
    from transformers import pipeline
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False

# RAKE 사용 가능 여부 (MULTI_RAKE 우선, 없으면 rake-nltk)
RAKE_AVAILABLE = MULTI_RAKE_AVAILABLE or RAKE_NLTK_AVAILABLE

# 의미 기반 보정 모델 (지연 초기화)
_SEMANTIC_MODEL_KO = None  # ko-sbert
_SEMANTIC_MODEL_EN = None  # sentence-bart


# =========================
# Config
# =========================
DEFAULT_STOPWORDS_KO = {
    "그리고","하지만","또한","그러나","따라서","때문","관련","대해서","위해","하여","하는","한다","함",
    "입니다","있습니다","없습니다","가능","불가","확인","조치","방법","절차","가이드","매뉴얼",
    "서버","시스템","환경","설정","구성","적용","변경","필요","권장","주의","리스크",
    "오류","장애","현상","원인","해결","대응",
}

DEFAULT_STOPWORDS_EN = {
    "the","a","an","and","or","but","if","then","else","for","to","of","in","on","at","by","with",
    "is","are","was","were","be","been","being",
    "this","that","these","those",
    "check","confirm","apply","change","need","required","recommended","note","risk",
    "error","issue","failure","failed","timeout","exception",
    "server","system","config","configuration","setting","guide","manual","procedure",
}

# 아주 가벼운 동의어/표기 통일(필요하면 계속 늘리기)
SYNONYM_MAP = {
    # products
    "jeus": ["제우스"],
    "webtob": ["웹투비","web to b","web-to-b"],
    "tomcat": ["톰캣"],
    "postgresql": ["postgres","포스트그레스","포스트그레","포스트그레sql","pg"],
    "oracle": ["오라클"],
    "tibero": ["티베로"],
    "xedrm": ["xe drm","xedrm5","xedrm6"],
    "xedm": ["xe dm","xedm5","xedm6"],

    # infra
    "port": ["포트"],
    "pid": ["프로세스id","프로세스 id"],
    "netstat": ["넷스탯"],
    "kill": ["강제종료","종료"],
    "rollback": ["롤백"],
    "restart": ["재기동","재시작","리스타트"],

    # categories
    "issue": ["오류","장애","에러","실패","현상"],
    "resolution": ["해결","조치","완료","대응"],
    "procedure": ["가이드","매뉴얼","절차","방법","설정"],
    "report": ["보고","리포트","분석","요약","현황"],
}

# 장르(문서종류) 분류 규칙(경량)
GENRE_RULES = [
    ("issue", [
        r"\berror\b", r"\bexception\b", r"\bfail(ed|ure)?\b", r"\btimeout\b",
        r"오류", r"장애", r"실패", r"예외", r"타임아웃", r"NoRouteToHost", r"ORA-\d+",
    ]),
    ("resolution", [
        r"\bfix\b", r"\bresolve(d)?\b", r"\bworkaround\b", r"\brollback\b", r"\brestart\b",
        r"해결", r"조치", r"완료", r"수정", r"롤백", r"재기동", r"재시작",
    ]),
    ("procedure", [
        r"\bhow to\b", r"\bprocedure\b", r"\bguide\b", r"\bchecklist\b", r"\bconfiguration\b",
        r"가이드", r"매뉴얼", r"절차", r"체크리스트", r"설정", r"구성",
    ]),
    ("report", [
        r"\breport\b", r"\banalysis\b", r"\bsummary\b", r"\bresult\b",
        r"보고", r"분석", r"요약", r"결과", r"현황",
    ]),
    ("application", [
        r"\bapplication\b", r"\bapply\b", r"\brequest\b", r"\b신청\b", r"\b신청서\b",
        r"\b제출\b", r"\b지원\b", r"\bapplication form\b", r"\b신청 양식\b",
    ]),
    ("form", [
        r"\bform\b", r"\btemplate\b", r"\b양식\b", r"\b서식\b", r"\b템플릿\b",
        r"\bformat\b", r"\b서식 파일\b", r"\b양식 파일\b",
    ]),
    ("maintenance", [
        r"\bmaintenance\b", r"\b유지보수\b", r"\b점검\b", r"\b정기\b", r"\bcheck\b",
        r"\b점검서\b", r"\b유지\b", r"\b보수\b", r"\bmaintain\b",
    ]),
    ("guide", [
        r"\bguide\b", r"\bmanual\b", r"\b설명서\b", r"\b가이드북\b", r"\b매뉴얼\b",
        r"\b사용법\b", r"\b사용 가이드\b", r"\btutorial\b",
    ]),
    ("record", [
        r"\brecord\b", r"\b기록\b", r"\b일지\b", r"\b로그\b", r"\b이력\b",
        r"\bhistory\b", r"\b기록서\b", r"\b일지\b",
    ]),
]

# 토큰 추출: 한글(2자+) / 영문숫자 underscore
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[가-힣]{2,}")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_token(tok: str) -> str:
    t = (tok or "").strip()
    if not t:
        return ""
    t = t.lower()
    t = t.strip("#")
    t = re.sub(r"\s+", "_", t)
    # 특수문자 정리(태그로 쓰기 좋게)
    t = re.sub(r"[^0-9a-z_가-힣\-\.]+", "", t)
    return t


def apply_synonyms(t: str) -> str:
    """
    SYNONYM_MAP 기반으로 표기 통일.
    - alias -> canonical 로 매핑
    """
    if not t:
        return ""
    for canon, aliases in SYNONYM_MAP.items():
        if t == canon:
            return canon
        if t in [normalize_token(a) for a in aliases]:
            return canon
    return t


def guess_language(text: str) -> str:
    if re.search(r"[가-힣]", text or ""):
        return "ko"
    if re.search(r"[A-Za-z]", text or ""):
        return "en"
    return "unknown"


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    toks = TOKEN_RE.findall(text)
    out = []
    for x in toks:
        t = normalize_token(x)
        if not t:
            continue
        # 숫자만 제거
        if re.fullmatch(r"\d+", t):
            continue
        if len(t) < 2:
            continue
        t = apply_synonyms(t)
        out.append(t)
    return out


def classify_genre(text: str, title: str = "") -> dict:
    blob = f"{title}\n{text}".lower()
    best = ("unknown", 0)
    for genre, pats in GENRE_RULES:
        score = 0
        for p in pats:
            if re.search(p, blob):
                score += 1
        if score > best[1]:
            best = (genre, score)

    if best[0] == "unknown":
        return {"genre": "unknown", "confidence": 0.2, "evidence": []}

    confidence = min(0.95, 0.35 + 0.12 * best[1])

    # evidence: 매칭되는 문장 1~3개
    ev = []
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for ln in lines[:120]:
        low = ln.lower()
        for p in dict(GENRE_RULES).get(best[0], []):
            if re.search(p, low):
                ev.append({"quote": ln[:180], "locator": "line?"})
                break
        if len(ev) >= 3:
            break

    return {"genre": best[0], "confidence": round(confidence, 3), "evidence": ev}


@dataclass
class TaggingState:
    """
    간이 DF(Document Frequency) 누적 상태:
    - corpus_docs: 문서 개수
    - df: token -> 포함된 문서 수
    - total_doc_length: BM25용 문서 길이 합계 (토큰 수)
    """
    corpus_docs: int
    df: dict[str, int]
    total_doc_length: int = 0

    @staticmethod
    def load(path: Path) -> "TaggingState":
        if not path.exists():
            return TaggingState(corpus_docs=0, df={})
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            return TaggingState(
                corpus_docs=int(obj.get("corpus_docs", 0)),
                df=dict(obj.get("df", {})),
                total_doc_length=int(obj.get("total_doc_length", 0)),
            )
        except Exception:
            return TaggingState(corpus_docs=0, df={})

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        obj = {"corpus_docs": self.corpus_docs, "df": self.df, "total_doc_length": self.total_doc_length, "updated_at": now_iso()}
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def avg_doc_length(self) -> float:
        """BM25 문서 길이 정규화용 평균 문서 길이"""
        if self.corpus_docs <= 0:
            return 1.0
        return self.total_doc_length / self.corpus_docs


def compute_tfidf_topk(tokens: list[str], state: TaggingState, lang: str, k: int = 12, genre: Optional[str] = None, topic_sentence: Optional[str] = None) -> list[dict]:
    """
    TF-IDF 기반 태그 추출 (장르별 가중치 적용)
    
    Args:
        tokens: 토큰 리스트
        state: TaggingState
        lang: 언어 ("ko" 또는 "en")
        k: 상위 k개 태그 반환
        genre: 문서 장르 (가중치 적용용)
        topic_sentence: 주제문장 (우선순위 선점용)
    """
    if not tokens:
        return []

    stop = DEFAULT_STOPWORDS_KO if lang == "ko" else DEFAULT_STOPWORDS_EN
    tf: dict[str, int] = {}
    for t in tokens:
        if t in stop:
            continue
        tf[t] = tf.get(t, 0) + 1

    if not tf:
        return []

    # 장르별 가중치 키워드 정의
    genre_weights: dict[str, dict[str, float]] = {
        "procedure": {
            # 절차/가이드 문서: 동사, 명령형, 단계 관련 단어에 가중치
            "설정": 1.5, "실행": 1.5, "확인": 1.4, "적용": 1.4, "구성": 1.4,
            "configure": 1.5, "execute": 1.5, "check": 1.4, "apply": 1.4,
            "step": 1.3, "단계": 1.3, "절차": 1.3, "procedure": 1.3,
        },
        "report": {
            # 보고서: 숫자, 통계, 결과 관련 단어에 가중치
            "결과": 1.5, "분석": 1.4, "현황": 1.4, "통계": 1.4, "데이터": 1.3,
            "result": 1.5, "analysis": 1.4, "summary": 1.4, "statistics": 1.4,
            "report": 1.3, "data": 1.3,
        },
        "issue": {
            # 이슈/문제: 문제, 원인, 증상 관련 단어에 가중치
            "오류": 1.6, "장애": 1.6, "문제": 1.5, "원인": 1.5, "증상": 1.4,
            "error": 1.6, "issue": 1.6, "failure": 1.5, "cause": 1.5, "symptom": 1.4,
            "exception": 1.5, "timeout": 1.4,
        },
        "resolution": {
            # 해결책: 해결, 조치, 수정 관련 단어에 가중치
            "해결": 1.6, "조치": 1.5, "수정": 1.5, "완료": 1.4, "대응": 1.4,
            "fix": 1.6, "resolve": 1.6, "solution": 1.5, "workaround": 1.4,
            "rollback": 1.4, "restart": 1.3,
        },
        "application": {
            # 신청서: 신청, 제출, 지원 관련 단어에 가중치
            "신청": 1.5, "제출": 1.4, "지원": 1.4, "신청서": 1.5,
            "application": 1.5, "apply": 1.4, "submit": 1.4, "request": 1.3,
        },
        "form": {
            # 양식: 양식, 템플릿 관련 단어에 가중치
            "양식": 1.5, "서식": 1.5, "템플릿": 1.4, "format": 1.4,
            "form": 1.5, "template": 1.4,
        },
        "maintenance": {
            # 유지보수: 점검, 유지보수 관련 단어에 가중치
            "점검": 1.5, "유지보수": 1.5, "정기": 1.4, "점검서": 1.5,
            "maintenance": 1.5, "check": 1.4, "inspection": 1.4,
        },
        "guide": {
            # 가이드: 가이드, 매뉴얼 관련 단어에 가중치
            "가이드": 1.5, "매뉴얼": 1.5, "설명서": 1.4, "사용법": 1.4,
            "guide": 1.5, "manual": 1.5, "tutorial": 1.4,
        },
        "record": {
            # 기록: 기록, 일지, 로그 관련 단어에 가중치
            "기록": 1.5, "일지": 1.5, "로그": 1.4, "이력": 1.4,
            "record": 1.5, "log": 1.4, "history": 1.4,
        },
    }

    # 주제문장 토큰 추출 (우선순위 선점용)
    topic_tokens: set[str] = set()
    if topic_sentence:
        topic_tokens = set(tokenize(topic_sentence))

    N = max(1, state.corpus_docs)
    scored = []
    genre_weight_map = genre_weights.get(genre or "", {})
    
    for term, f in tf.items():
        df = max(0, int(state.df.get(term, 0)))
        # idf: log((N+1)/(df+1)) + 1
        idf = math.log((N + 1) / (df + 1)) + 1.0
        base_score = f * idf
        
        # 장르별 가중치 적용
        weight = genre_weight_map.get(term, 1.0)
        if weight > 1.0:
            base_score *= weight
        
        # 주제문장 토큰 우선순위 선점 (추가 가중치)
        if term in topic_tokens:
            base_score *= 1.3  # 주제문장 토큰은 30% 추가 가중치
        
        scored.append((term, base_score, f, df, weight, term in topic_tokens))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:k]
    max_score = top[0][1] if top else 1.0

    out = []
    for term, score, f, df, weight, from_topic in top:
        tag_item = {
            "tag": term,
            "score": round(score / max_score, 4),
            "tf": f,
            "df": df
        }
        # 가중치가 적용된 경우 메타데이터 추가
        if weight > 1.0:
            tag_item["genre_weight"] = round(weight, 2)
        if from_topic:
            tag_item["from_topic"] = True
        else:
            tag_item["from_topic"] = False
        out.append(tag_item)
    return out


def compute_bm25_topk(
    tokens: list[str],
    state: TaggingState,
    lang: str,
    k: int = 12,
    genre: Optional[str] = None,
    topic_sentence: Optional[str] = None,
    k1: float = 1.5,
    b: float = 0.75
) -> list[dict]:
    """
    BM25 기반 태그 추출 (장르별 가중치 적용, fallback용)
    compute_tfidf_topk와 동일한 인터페이스
    """
    if not tokens:
        return []

    stop = DEFAULT_STOPWORDS_KO if lang == "ko" else DEFAULT_STOPWORDS_EN
    tf: dict[str, int] = {}
    for t in tokens:
        if t in stop:
            continue
        tf[t] = tf.get(t, 0) + 1

    if not tf:
        return []

    genre_weights: dict[str, dict[str, float]] = {
        "procedure": {"설정": 1.5, "실행": 1.5, "확인": 1.4, "configure": 1.5, "execute": 1.5, "step": 1.3, "단계": 1.3},
        "report": {"결과": 1.5, "분석": 1.4, "현황": 1.4, "result": 1.5, "analysis": 1.4, "summary": 1.4},
        "issue": {"오류": 1.6, "장애": 1.6, "문제": 1.5, "error": 1.6, "issue": 1.6, "failure": 1.5},
        "resolution": {"해결": 1.6, "조치": 1.5, "수정": 1.5, "fix": 1.6, "resolve": 1.6, "solution": 1.5},
        "application": {"신청": 1.5, "제출": 1.4, "application": 1.5, "apply": 1.4},
        "form": {"양식": 1.5, "서식": 1.5, "form": 1.5, "template": 1.4},
        "maintenance": {"점검": 1.5, "유지보수": 1.5, "maintenance": 1.5, "check": 1.4},
        "guide": {"가이드": 1.5, "매뉴얼": 1.5, "guide": 1.5, "manual": 1.5},
        "record": {"기록": 1.5, "일지": 1.5, "record": 1.5, "log": 1.4},
    }

    topic_tokens: set[str] = set()
    if topic_sentence:
        topic_tokens = set(tokenize(topic_sentence))

    N = max(1, state.corpus_docs)
    doc_len = len(tokens)
    avg_doc_len = max(1.0, state.avg_doc_length)
    length_norm = 1.0 - b + b * (doc_len / avg_doc_len)
    genre_weight_map = genre_weights.get(genre or "", {})

    scored = []
    for term, f in tf.items():
        df = max(0, int(state.df.get(term, 0)))
        idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
        bm25 = idf * (f * (k1 + 1)) / (f + k1 * length_norm)

        weight = genre_weight_map.get(term, 1.0)
        if weight > 1.0:
            bm25 *= weight
        if term in topic_tokens:
            bm25 *= 1.3

        scored.append((term, bm25, f, df, weight, term in topic_tokens))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:k]
    max_score = top[0][1] if top else 1.0

    out = []
    for term, score, f, df, weight, from_topic in top:
        tag_item = {
            "tag": term,
            "score": round(score / max_score, 4),
            "tf": f,
            "df": df
        }
        if weight > 1.0:
            tag_item["genre_weight"] = round(weight, 2)
        tag_item["from_topic"] = from_topic
        out.append(tag_item)
    return out


def extract_topic_keywords(topic_sentence: str, lang: str) -> set[str]:
    """주제문장에서 핵심 키워드 추출 (불용어 제거)"""
    if not topic_sentence:
        return set()
    
    tokens = tokenize(topic_sentence)
    stop = DEFAULT_STOPWORDS_KO if lang == "ko" else DEFAULT_STOPWORDS_EN
    
    # 불용어 제거하고 2글자 이상만
    keywords = {t for t in tokens if t not in stop and len(t) >= 2}
    return keywords


def calculate_topic_relevance(
    tag: str,
    topic_keywords: set[str],
    text: str = "",
    tokens: list[str] = None
) -> float:
    """
    태그의 주제 관련성 점수 계산 (0.0~1.0)
    
    Args:
        tag: 태그 단어
        topic_keywords: 주제 키워드 집합
        text: 원본 텍스트 (문맥 분석용)
        tokens: 토큰 리스트 (위치 점수 계산용)
    
    Returns:
        관련성 점수 (0.0~1.0)
    """
    if not topic_keywords:
        return 0.0
    
    score = 0.0
    
    # 1. 직접 매칭
    if tag in topic_keywords:
        score = 1.0
        return score
    
    # 2. 부분 매칭 (예: "카프카_설정"과 "카프카")
    for keyword in topic_keywords:
        # 태그에 키워드가 포함되거나, 키워드에 태그가 포함
        if keyword in tag or tag in keyword:
            score = max(score, 0.5)
        # 유사도 (공통 부분이 많으면)
        common_chars = set(tag) & set(keyword)
        if len(common_chars) >= min(len(tag), len(keyword)) * 0.6:
            score = max(score, 0.3)
    
    # 3. 문맥 점수 (텍스트에서 주제 키워드와 태그가 같은 문장/구에 출현)
    if text and score < 0.5:
        context_score = _calculate_context_score(tag, topic_keywords, text)
        score = max(score, context_score * 0.4)
    
    # 4. 위치 점수 (태그가 문서 앞부분에 자주 출현하면 보너스)
    # 주제문장이 있으면 앞부분 태그에 약간의 보너스
    if tokens and score > 0:
        # 태그가 토큰 리스트 앞 30%에 출현하면 보너스
        tag_positions = [i for i, t in enumerate(tokens) if t == tag]
        if tag_positions:
            first_pos = min(tag_positions)
            if first_pos < len(tokens) * 0.3:
                score = min(1.0, score + 0.1)
    
    return min(1.0, score)


def _calculate_context_score(tag: str, topic_keywords: set[str], text: str) -> float:
    """태그가 주제 키워드와 가까이 출현하는지 확인"""
    if not text:
        return 0.0
    
    # 문장 단위로 확인
    sentences = re.split(r'[.!?。！？]\s+', text)
    max_score = 0.0
    tag_lower = tag.lower()
    
    for sentence in sentences[:100]:  # 상위 100개 문장만 확인 (성능)
        sentence_lower = sentence.lower()
        has_tag = tag_lower in sentence_lower
        has_keyword = any(kw.lower() in sentence_lower for kw in topic_keywords)
        
        if has_tag and has_keyword:
            # 같은 문장에 있으면 높은 점수
            max_score = max(max_score, 0.6)
        
        # 같은 문단(인접 문장)에 있으면 중간 점수
        # (간단히 이전/다음 문장 확인)
        if has_tag:
            # 주제 키워드가 주변에 있는지 확인
            for kw in topic_keywords:
                kw_lower = kw.lower()
                # 태그 주변 50자 내에 키워드가 있으면
                tag_idx = sentence_lower.find(tag_lower)
                if tag_idx >= 0:
                    context = sentence[max(0, tag_idx-50):tag_idx+len(tag)+50].lower()
                    if kw_lower in context:
                        max_score = max(max_score, 0.3)
    
    return max_score


def compute_bm25_topk_with_topic_boost(
    tokens: list[str],
    state: TaggingState,
    lang: str,
    k: int = 12,
    genre: Optional[str] = None,
    topic_sentence: Optional[str] = None,
    original_text: Optional[str] = None,
    topic_boost_factor: float = 2.0
) -> list[dict]:
    """
    주제 기반 태깅 개선 버전 (BM25 기반)
    """
    if not topic_sentence:
        return compute_bm25_topk(tokens, state, lang, k, genre, None)

    # 1단계: 기본 BM25로 후보 태그 추출 (더 많이 추출)
    candidates = compute_bm25_topk(tokens, state, lang, k=k*2, genre=genre, topic_sentence=None)
    
    if not candidates:
        return []
    
    # 2단계: 주제 키워드 추출
    topic_keywords = extract_topic_keywords(topic_sentence, lang)
    
    if not topic_keywords:
        # 주제 키워드 없으면 기존 방식
        return candidates[:k]
    
    # 3단계: 각 후보 태그에 주제 관련성 점수 부여
    scored_candidates = []
    for tag_item in candidates:
        tag = tag_item["tag"]
        
        # 관련성 점수 계산
        relevance = calculate_topic_relevance(
            tag=tag,
            topic_keywords=topic_keywords,
            text=original_text or "",
            tokens=tokens
        )
        
        # 최종 점수 = BM25 점수 * (1 + 관련성 * 부스트 계수)
        original_score = tag_item["score"]
        boosted_score = original_score * (1.0 + relevance * topic_boost_factor)
        
        # 메타데이터 추가
        tag_item["score"] = round(boosted_score, 4)
        tag_item["topic_relevance"] = round(relevance, 3)
        tag_item["from_topic"] = relevance > 0.2  # 관련성 20% 이상이면 주제 관련으로 표시
        
        scored_candidates.append(tag_item)
    
    # 4단계: 재정렬
    # 1순위: 주제 관련성 높은 순
    # 2순위: 최종 점수 높은 순
    scored_candidates.sort(
        key=lambda x: (
            x.get("topic_relevance", 0),  # 관련성 우선
            x["score"]  # 그 다음 점수
        ),
        reverse=True
    )
    
    # 5단계: 정규화 (최고 점수를 1.0으로)
    if scored_candidates:
        max_score = scored_candidates[0]["score"]
        if max_score > 0:
            for item in scored_candidates:
                item["score"] = round(item["score"] / max_score, 4)
    
    return scored_candidates[:k]


def update_df_state(state: TaggingState, unique_terms: set[str], doc_length: int = 0):
    """DF 상태 업데이트. doc_length는 BM25용 평균 문서 길이 계산에 사용."""
    state.corpus_docs += 1
    state.total_doc_length += doc_length
    for t in unique_terms:
        state.df[t] = int(state.df.get(t, 0)) + 1


# =========================
# 다중 알고리즘 태깅 파이프라인
# =========================

def extract_candidates_with_rake(
    text: str, 
    lang: str, 
    max_phrase_length: int = 3,
    top_k: int = 50
) -> List[Dict[str, Any]]:
    """
    RAKE로 구문 단위 키프레이즈 후보 추출
    - MULTI_RAKE 우선 사용 (언어 독립적, 형태소 분석 불필요)
    - 없으면 rake-nltk 사용 (하위 호환성)
    - 점수는 문서 단위로 0~1 정규화
    
    Args:
        text: 문서 텍스트
        lang: 언어 ("ko" 또는 "en")
        max_phrase_length: 최대 키프레이즈 길이 (단어 수)
        top_k: 상위 k개 후보 반환
    
    Returns:
        [
            {
                "phrase": "카프카 클러스터",
                "score": 0.85,  # 0~1 정규화된 점수
                "spans": [(start_pos, end_pos), ...]  # 텍스트 내 위치
            },
            ...
        ]
    """
    if not RAKE_AVAILABLE or not text:
        return []
    
    # 텍스트가 너무 길면 처리 시간이 오래 걸릴 수 있으므로 제한
    if len(text) > 50000:  # 5만자 이상이면 RAKE 건너뛰기
        print(f"[RAKE] 텍스트가 너무 깁니다 ({len(text)}자). RAKE 추출을 건너뜁니다.")
        return []
    
    try:
        # 타임아웃 설정을 위한 스레드 사용
        import threading
        import queue
        
        result_queue = queue.Queue()
        
        def extract_with_timeout():
            try:
                # 한국어: MULTI_RAKE + Kiwipiepy 독립적으로 실행 (하나가 실패해도 다른 하나는 실행)
                if lang == "ko":
                    results = []
                    
                    # MULTI_RAKE 사용 (독립적으로 실행, 실패해도 계속)
                    if MULTI_RAKE_AVAILABLE:
                        try:
                            multi_result = _extract_rake_multi(text, max_phrase_length, top_k, lang)
                            if multi_result:
                                results.extend(multi_result)
                                print(f"[RAKE] MULTI_RAKE 후보: {len(multi_result)}개")
                        except Exception as multi_err:
                            print(f"[RAKE] MULTI_RAKE 실패 (계속 진행): {multi_err}")
                    
                    # Kiwipiepy 사용 (독립적으로 실행, 실패해도 계속)
                    if KIWIPIEPY_AVAILABLE:
                        try:
                            kiwi_result = _extract_keywords_with_kiwi(text, max_phrase_length, top_k)
                            if kiwi_result:
                                results.extend(kiwi_result)
                                print(f"[RAKE] Kiwipiepy 후보: {len(kiwi_result)}개")
                        except Exception as kiwi_err:
                            print(f"[RAKE] Kiwipiepy 실패 (계속 진행): {kiwi_err}")
                    
                    # 결과가 없으면 하위 호환성: rake-nltk 사용
                    if not results and RAKE_NLTK_AVAILABLE:
                        try:
                            results = _extract_rake_korean(text, max_phrase_length, top_k)
                            if results:
                                print(f"[RAKE] rake-nltk 후보: {len(results)}개")
                        except Exception as nltk_err:
                            print(f"[RAKE] rake-nltk 실패: {nltk_err}")
                    
                    result = results
                # 영어: MULTI_RAKE 우선 사용
                elif MULTI_RAKE_AVAILABLE:
                    result = _extract_rake_multi(text, max_phrase_length, top_k, lang)
                # 하위 호환성: rake-nltk 사용
                elif RAKE_NLTK_AVAILABLE:
                    result = _extract_rake_english(text, max_phrase_length, top_k)
                else:
                    result = []
                result_queue.put(("success", result))
            except Exception as e:
                # 예외를 문자열로 변환하여 안전하게 전달
                error_msg = str(e)
                import traceback
                error_trace = traceback.format_exc()
                print(f"[RAKE] 스레드 내 오류 발생: {error_msg}")
                print(f"[RAKE] 상세 오류:\n{error_trace}")
                result_queue.put(("error", error_msg))
        
        thread = threading.Thread(target=extract_with_timeout, daemon=True)
        thread.start()
        thread.join(timeout=30)  # 30초 타임아웃
        
        if thread.is_alive():
            print(f"[RAKE] 타임아웃 (30초 초과). RAKE 추출을 건너뜁니다.")
            return []
        
        try:
            status, value = result_queue.get_nowait()
            if status == "success":
                candidates = value
                # 점수 정규화 (문서 단위로 0~1)
                if candidates:
                    try:
                        scores = [c.get("score", 0.0) for c in candidates]
                        if scores:
                            normalized_scores = _normalize_scores_to_0_1(scores)
                            if normalized_scores and len(normalized_scores) == len(candidates):
                                for i, cand in enumerate(candidates):
                                    cand["score"] = normalized_scores[i]
                    except Exception as norm_err:
                        print(f"[RAKE] 점수 정규화 실패 (원본 점수 사용): {norm_err}")
                        import traceback
                        traceback.print_exc()
                        # 정규화 실패 시 원본 점수 사용
                return candidates
            else:
                # 에러가 발생했지만 프로그램을 계속 진행
                print(f"[RAKE] 추출 중 오류 발생 (계속 진행): {value}")
                import traceback
                traceback.print_exc()
                return []
        except queue.Empty:
            print(f"[RAKE] 결과를 받지 못했습니다. RAKE 추출을 건너뜁니다.")
            return []
            
    except Exception as e:
        print(f"[RAKE] 오류: {e}")
        import traceback
        traceback.print_exc()
        return []


def _get_korean_tagger():
    """KoNLPy 형태소 분석기 초기화 (지연 로딩)"""
    global KONLPY_TAGGER, _KONLPY_INIT_FAILED
    if not KONLPY_AVAILABLE or _KONLPY_INIT_FAILED:
        return None
    
    if KONLPY_TAGGER is None:
        # JPype1 설치 확인
        try:
            import jpype
            if not jpype.isJVMStarted():
                # Java 경로 확인
                import subprocess
                try:
                    result = subprocess.run(['java', '-version'], 
                                          capture_output=True, 
                                          text=True, 
                                          timeout=3)
                    if result.returncode != 0:
                        print("[KoNLPy] Java가 설치되어 있지 않거나 PATH에 없습니다.")
                        print("[KoNLPy] 해결 방법:")
                        print("  1. Java 설치: https://www.oracle.com/java/technologies/downloads/")
                        print("  2. 또는 JPype1 재설치: pip install --upgrade JPype1")
                        print("[KoNLPy] KoNLPy 없이 기본 토큰화로 진행합니다.")
                        _KONLPY_INIT_FAILED = True
                        return None
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    print("[KoNLPy] Java 실행 파일을 찾을 수 없습니다.")
                    print("[KoNLPy] 해결 방법:")
                    print("  1. Java 설치: https://www.oracle.com/java/technologies/downloads/")
                    print("  2. 또는 JPype1 재설치: pip install --upgrade JPype1")
                    print("[KoNLPy] KoNLPy 없이 기본 토큰화로 진행합니다.")
                    _KONLPY_INIT_FAILED = True
                    return None
        except ImportError:
            print("[KoNLPy] JPype1이 설치되어 있지 않습니다.")
            print("[KoNLPy] 해결 방법: pip install JPype1")
            print("[KoNLPy] KoNLPy 없이 기본 토큰화로 진행합니다.")
            _KONLPY_INIT_FAILED = True
            return None
        except Exception as e:
            print(f"[KoNLPy] JPype1 확인 중 오류: {e}")
            print("[KoNLPy] KoNLPy 없이 기본 토큰화로 진행합니다.")
            _KONLPY_INIT_FAILED = True
            return None
        
        try:
            # Okt는 빠르고 가볍고, Kkma는 더 정확하지만 느림
            KONLPY_TAGGER = Okt()
            print("[KoNLPy] Okt 초기화 성공")
        except Exception as e:
            error_msg = str(e)
            print(f"[KoNLPy] Okt 초기화 실패: {error_msg}")
            
            # JPype1 관련 오류인지 확인
            if "jpype" in error_msg.lower() or "java" in error_msg.lower() or "jar" in error_msg.lower():
                print("[KoNLPy] JPype1/Java 관련 오류입니다.")
                print("[KoNLPy] 해결 방법:")
                print("  1. Java 설치 확인: java -version")
                print("  2. JPype1 재설치: pip install --upgrade --force-reinstall JPype1")
                print("  3. 환경 변수 JAVA_HOME 설정 확인")
                print("[KoNLPy] JPype1 오류로 인해 Kkma도 동일한 문제가 발생할 수 있어 건너뜁니다.")
                print("[KoNLPy] KoNLPy 없이 기본 토큰화로 진행합니다.")
                print("[KoNLPy] 태깅 품질은 다소 저하될 수 있지만, 기본 기능은 정상 작동합니다.")
                _KONLPY_INIT_FAILED = True
                return None
            
            # JPype1 오류가 아닌 경우에만 Kkma 시도 (하지만 타임아웃 설정)
            print("[KoNLPy] Kkma 시도 중... (최대 10초)")
            try:
                import threading
                import queue
                
                # 타임아웃을 위한 큐
                result_queue = queue.Queue()
                
                def init_kkmma():
                    try:
                        tagger = Kkma()
                        result_queue.put(("success", tagger))
                    except Exception as e:
                        result_queue.put(("error", e))
                
                # 별도 스레드에서 초기화 시도
                thread = threading.Thread(target=init_kkmma, daemon=True)
                thread.start()
                thread.join(timeout=10.0)  # 10초 타임아웃
                
                if thread.is_alive():
                    print("[KoNLPy] Kkma 초기화 타임아웃 (10초 초과)")
                    print("[KoNLPy] KoNLPy 없이 기본 토큰화로 진행합니다.")
                    _KONLPY_INIT_FAILED = True
                    return None
                
                # 결과 확인
                try:
                    status, value = result_queue.get_nowait()
                    if status == "success":
                        KONLPY_TAGGER = value
                        print("[KoNLPy] Kkma 초기화 성공")
                    else:
                        raise value
                except queue.Empty:
                    print("[KoNLPy] Kkma 초기화 결과를 받지 못했습니다.")
                    print("[KoNLPy] KoNLPy 없이 기본 토큰화로 진행합니다.")
                    _KONLPY_INIT_FAILED = True
                    return None
                except Exception:
                    _KONLPY_INIT_FAILED = True
                    raise
                    
            except Exception as e2:
                print(f"[KoNLPy] Kkma 초기화도 실패: {e2}")
                print("[KoNLPy] KoNLPy 없이 기본 토큰화로 진행합니다.")
                print("[KoNLPy] 태깅 품질은 다소 저하될 수 있지만, 기본 기능은 정상 작동합니다.")
                _KONLPY_INIT_FAILED = True
                return None
    
    return KONLPY_TAGGER


def _morphological_analyze_korean(text: str) -> str:
    """
    한국어 형태소 분석 후 품사 태깅
    명사, 동사, 형용사만 추출하여 공백으로 연결
    
    Returns:
        형태소 분석 후 공백으로 연결된 텍스트
        예: "카프카 클러스터 설정" → "카프카 클러스터 설정"
    """
    tagger = _get_korean_tagger()
    if not tagger:
        # KoNLPy 없으면 기존 토큰화 사용
        tokens = tokenize(text)
        return " ".join(tokens)
    
    try:
        # 형태소 분석
        pos_tags = tagger.pos(text, norm=True, stem=True)
        
        # 명사, 동사, 형용사만 추출
        # 명사: NNG(일반명사), NNP(고유명사), NNBC(단위명사), NR(수사)
        # 동사: VV(동사), VA(형용사)
        # 형용사: VA
        extracted_words = []
        for word, pos in pos_tags:
            # 명사, 동사, 형용사, 영어/숫자 포함
            if pos.startswith('N') or pos.startswith('V') or \
               (pos.startswith('SL') and re.match(r'[A-Za-z0-9]+', word)) or \
               pos.startswith('SN'):  # SN: 숫자
                if len(word) >= 2:  # 2글자 이상만
                    extracted_words.append(word)
        
        return " ".join(extracted_words)
    except Exception as e:
        print(f"[형태소 분석] 오류: {e}")
        # 실패 시 기존 토큰화 사용
        tokens = tokenize(text)
        return " ".join(tokens)


def _get_kiwi_tagger():
    """Kiwipiepy 형태소 분석기 초기화 (지연 로딩)"""
    global KIWI_TAGGER
    if not KIWIPIEPY_AVAILABLE:
        return None
    
    if KIWI_TAGGER is None:
        try:
            KIWI_TAGGER = Kiwi()
            print("[Kiwipiepy] 초기화 성공")
        except Exception as e:
            print(f"[Kiwipiepy] 초기화 실패: {e}")
            return None
    
    return KIWI_TAGGER


def _extract_keywords_with_kiwi(
    text: str,
    max_phrase_length: int,
    top_k: int
) -> List[Dict[str, Any]]:
    """
    Kiwipiepy를 사용한 한국어 키워드 추출
    - 형태소 분석 후 명사/키워드 추출
    - 한국어 처리에 최적화
    
    Args:
        text: 문서 텍스트
        max_phrase_length: 최대 키프레이즈 길이 (단어 수)
        top_k: 상위 k개 후보 반환
    
    Returns:
        후보 리스트
    """
    if not KIWIPIEPY_AVAILABLE:
        return []
    
    try:
        kiwi = _get_kiwi_tagger()
        if not kiwi:
            return []
        
        # 형태소 분석
        # analyze 메서드로 형태소 분석 수행
        # 반환 형식: 문장 리스트, 각 문장은 (형태소, 품사, 시작위치, 끝위치) 튜플의 리스트
        analyzed = kiwi.analyze(text)
        
        # 명사 추출 및 빈도 계산
        noun_freq = {}
        noun_positions = {}  # 첫 번째 등장 위치
        
        for sentence in analyzed:
            # sentence는 형태소 분석 결과 리스트
            # 각 결과는 (형태소, 품사, 시작위치, 끝위치) 튜플 또는 리스트
            for morpheme_info in sentence:
                try:
                    # Kiwipiepy 반환 형식: (형태소, 품사, 시작위치, 끝위치) 튜플
                    if isinstance(morpheme_info, (list, tuple)) and len(morpheme_info) >= 4:
                        word = str(morpheme_info[0])
                        pos = str(morpheme_info[1])
                        start = int(morpheme_info[2])
                        end = int(morpheme_info[3])
                    else:
                        continue
                    
                    # 명사만 추출 (NNG: 일반명사, NNP: 고유명사, NNBC: 단위명사, NR: 수사)
                    if pos.startswith('N') and len(word) >= 2:
                        if word not in noun_freq:
                            noun_freq[word] = 0
                            noun_positions[word] = (start, end)
                        noun_freq[word] += 1
                except (ValueError, TypeError, IndexError) as e:
                    # 형태소 정보 파싱 실패 시 무시하고 계속
                    continue
        
        # 빈도 기반 점수 계산 (TF-like score)
        if not noun_freq:
            return []
        
        max_freq = max(noun_freq.values())
        candidates = []
        
        for word, freq in noun_freq.items():
            # TF-like 점수 (빈도 기반, 0~1 정규화)
            score = freq / max_freq if max_freq > 0 else 0.0
            
            # 위치 정보
            start, end = noun_positions[word]
            spans = [(start, end)]
            
            candidates.append({
                "phrase": word,
                "score": score,
                "spans": spans,
                "algorithm": "kiwipiepy"
            })
        
        # 점수 순으로 정렬하고 상위 k개 반환
        candidates.sort(key=lambda x: x["score"], reverse=True)
        
        # 다중 단어 구문 추출 (인접한 명사 조합)
        # 문장 단위로 인접한 명사들을 조합
        phrases = []
        for sentence in analyzed:
            nouns_in_sentence = []
            for morpheme_info in sentence:
                try:
                    # Kiwipiepy 반환 형식: (형태소, 품사, 시작위치, 끝위치) 튜플
                    if isinstance(morpheme_info, (list, tuple)) and len(morpheme_info) >= 4:
                        word = str(morpheme_info[0])
                        pos = str(morpheme_info[1])
                        start = int(morpheme_info[2])
                        end = int(morpheme_info[3])
                    else:
                        continue
                    
                    if pos.startswith('N') and len(word) >= 2:
                        nouns_in_sentence.append((word, start, end))
                except (ValueError, TypeError, IndexError) as e:
                    # 형태소 정보 파싱 실패 시 무시하고 계속
                    continue
            
            # 인접한 명사들을 max_phrase_length까지 조합
            for i in range(len(nouns_in_sentence)):
                for length in range(1, min(max_phrase_length + 1, len(nouns_in_sentence) - i + 1)):
                    phrase_words = [nouns_in_sentence[j][0] for j in range(i, i + length)]
                    phrase = " ".join(phrase_words)
                    
                    # 이미 단일 단어로 추가된 경우 제외
                    if length == 1:
                        continue
                    
                    # 구문 점수: 구성 단어들의 평균 점수
                    phrase_score = sum(noun_freq.get(word, 0) for word in phrase_words) / (len(phrase_words) * max_freq) if max_freq > 0 else 0.0
                    
                    # 위치 정보
                    phrase_start = nouns_in_sentence[i][1]
                    phrase_end = nouns_in_sentence[i + length - 1][2]
                    
                    phrases.append({
                        "phrase": phrase,
                        "score": phrase_score,
                        "spans": [(phrase_start, phrase_end)],
                        "algorithm": "kiwipiepy"
                    })
        
        # 구문도 추가
        candidates.extend(phrases)
        
        # 점수 순으로 정렬하고 상위 k개 반환
        candidates.sort(key=lambda x: x["score"], reverse=True)
        
        return candidates[:top_k]
        
    except Exception as e:
        print(f"[Kiwipiepy] 오류: {e}")
        import traceback
        traceback.print_exc()
        return []


def _extract_rake_multi(
    text: str,
    max_phrase_length: int,
    top_k: int,
    lang: str
) -> List[Dict[str, Any]]:
    """
    MULTI_RAKE를 사용한 언어 독립적 키프레이즈 추출
    - 형태소 분석 불필요
    - 한국어, 영어 등 여러 언어 지원
    
    Args:
        text: 문서 텍스트
        max_phrase_length: 최대 키프레이즈 길이 (단어 수)
        top_k: 상위 k개 후보 반환
        lang: 언어 코드 ("ko", "en" 등)
    
    Returns:
        후보 리스트
    """
    if not MULTI_RAKE_AVAILABLE:
        return []
    
    try:
        from multi_rake import Rake
        
        # 텍스트 UTF-8 정리 (강화된 버전 - pycld2 호환)
        try:
            # 1단계: bytes인 경우 UTF-8 디코딩
            if isinstance(text, bytes):
                text_clean = text.decode('utf-8', errors='replace')
            else:
                text_clean = str(text)
            
            # 2단계: 잘못된 UTF-8 바이트 제거 (pycld2 호환)
            # 문자열을 bytes로 변환 후 다시 UTF-8로 디코딩하여 잘못된 바이트 제거
            text_bytes = text_clean.encode('utf-8', errors='replace')
            text_clean = text_bytes.decode('utf-8', errors='replace')
            
            # 3단계: 제어 문자 및 잘못된 유니코드 문자 제거
            import unicodedata
            # 제어 문자 제거 (단, 줄바꿈/탭은 유지)
            text_clean = ''.join(
                char if unicodedata.category(char)[0] != 'C' or char in '\n\r\t' 
                else ' ' 
                for char in text_clean
            )
            
            # 4단계: 연속된 공백 정리
            import re
            text_clean = re.sub(r'\s+', ' ', text_clean)
            text_clean = text_clean.strip()
            
            # 5단계: 최종 UTF-8 검증 (pycld2가 처리할 수 있도록)
            # 마지막으로 한 번 더 인코딩/디코딩하여 확실히 정리
            text_clean = text_clean.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
            
            # 텍스트가 너무 짧으면 의미 없음
            if len(text_clean) < 10:
                print(f"[RAKE-Multi] 텍스트가 너무 짧습니다 ({len(text_clean)}자). 건너뜁니다.")
                return []
                
        except Exception as clean_err:
            print(f"[RAKE-Multi] UTF-8 정리 실패: {clean_err}")
            # 정리 실패 시 빈 리스트 반환 (오류 전파 방지)
            return []
        
        # MULTI_RAKE 초기화
        # 한국어는 내장 stopwords가 없으므로 커스텀 stopwords 제공 또는 None 사용
        if lang == "ko":
            # 한국어: language_code와 stopwords를 None으로 설정하면 텍스트에서 자동 생성
            try:
                rake = Rake(
                    min_chars=2,
                    max_words=max_phrase_length,
                    min_freq=1,
                    language_code=None,  # None으로 설정하면 텍스트에서 자동 생성
                    stopwords=None  # None으로 설정하면 텍스트에서 자동 생성
                )
            except Exception as e1:
                # 첫 번째 방법 실패 시 커스텀 stopwords 사용
                print(f"[RAKE-Multi] 자동 stopwords 생성 실패, 커스텀 stopwords 사용: {e1}")
                rake = Rake(
                    min_chars=2,
                    max_words=max_phrase_length,
                    min_freq=1,
                    language_code=None,
                    stopwords=list(DEFAULT_STOPWORDS_KO)  # 커스텀 stopwords 제공
                )
        else:
            # 다른 언어는 기존 방식 사용
            supported_langs = ['en', 'de', 'fr', 'es', 'it', 'pt', 'ru', 'ar', 'zh', 'ja']
            language_code = lang if lang in supported_langs else None
            
            rake = Rake(
                min_chars=2,
                max_words=max_phrase_length,
                min_freq=1,
                language_code=language_code
            )
        
        # 키워드 추출 (정리된 텍스트 사용)
        keywords = rake.apply(text_clean)
        
        if not keywords:
            return []
        
        candidates = []
        for item in keywords[:top_k]:
            try:
                # MULTI_RAKE 반환 형식: (phrase, score) 튜플
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                
                phrase = str(item[0]).strip()
                score = float(item[1])
                
                if not phrase or len(phrase.strip()) < 2:
                    continue
                
                # 텍스트에서 위치 찾기
                spans = _find_phrase_spans(text, phrase)
                
                candidates.append({
                    "phrase": phrase,
                    "score": score,
                    "spans": spans,
                    "algorithm": "multi_rake"
                })
            except Exception as item_err:
                # 개별 항목 처리 실패는 무시하고 계속 진행
                print(f"[RAKE-Multi] 키워드 항목 처리 실패: {item}, 오류: {item_err}")
                continue
        
        return candidates
    except Exception as e:
        print(f"[RAKE-Multi] 오류: {e}")
        import traceback
        traceback.print_exc()
        return []


def _extract_rake_korean(
    text: str,
    max_phrase_length: int,
    top_k: int
) -> List[Dict[str, Any]]:
    """
    한국어 형태소 분석 + RAKE를 사용한 키프레이즈 추출
    
    1. KoNLPy로 형태소 분석
    2. 명사/동사만 추출하여 공백으로 연결
    3. rake-nltk에 입력하여 키프레이즈 추출
    
    주의: KoNLPy가 사용 불가능하면 RAKE를 건너뜀 (RAKE는 형태소 분석 결과가 필요)
    """
    if not RAKE_NLTK_AVAILABLE:
        return []
    
    # KoNLPy 확인: RAKE는 형태소 분석이 필수
    tagger = _get_korean_tagger()
    if not tagger:
        print("[RAKE-Korean] KoNLPy가 사용 불가능합니다. RAKE를 건너뜁니다.")
        print("[RAKE-Korean] YAKE는 언어 독립적이므로 계속 진행됩니다.")
        return []
    
    try:
        # 1단계: 형태소 분석하여 품사 태깅
        analyzed_text = _morphological_analyze_korean(text)
        
        if not analyzed_text or len(analyzed_text.strip()) < 2:
            return []
        
        # 2단계: rake-nltk로 키프레이즈 추출
        # NLTK stopwords 확인 및 다운로드
        try:
            import nltk
            try:
                nltk.data.find('corpora/stopwords')
            except LookupError:
                nltk.download('stopwords', quiet=True)
            # punkt, punkt_tab 추가 확인 (런타임에서 누락될 경우 대비)
            try:
                nltk.data.find('tokenizers/punkt')
            except LookupError:
                nltk.download('punkt', quiet=True)
            try:
                nltk.data.find('tokenizers/punkt_tab')
            except LookupError:
                nltk.download('punkt_tab', quiet=True)
        except ImportError:
            pass
        
        r = rake_nltk.Rake(max_length=max_phrase_length)
        try:
            r.extract_keywords_from_text(analyzed_text)
        except LookupError as e:
            # punkt 계열 리소스가 여전히 없는 경우 대비
            print(f"[RAKE-Korean] NLTK 리소스(punkt/punkt_tab) 누락: {e}")
            print("[RAKE-Korean] nltk.download('punkt'); nltk.download('punkt_tab') 실행 필요")
            return []
        
        # 키워드와 점수 추출
        keywords_with_scores = r.get_ranked_phrases_with_scores()
        
        if not keywords_with_scores:
            return []
        
        candidates = []
        for item in keywords_with_scores[:top_k]:
            try:
                # RAKE 반환 형식: (score, phrase) 튜플
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                
                score = float(item[0])
                phrase = str(item[1])
                
                if not phrase or len(phrase.strip()) < 2:
                    continue
                
                phrase = phrase.strip()
                
                # 원본 텍스트에서 위치 찾기 (형태소 분석된 텍스트가 아닌 원본)
                # phrase는 형태소 분석된 결과이므로 원본에서 유사한 패턴 찾기
                spans = _find_phrase_spans_in_korean(text, phrase)
                
                candidates.append({
                    "phrase": phrase,
                    "score": score,
                    "spans": spans,
                    "algorithm": "rake_kor_konlpy"
                })
            except Exception as item_err:
                # 개별 항목 처리 실패는 무시하고 계속 진행
                print(f"[RAKE-Korean] 키워드 항목 처리 실패: {item}, 오류: {item_err}")
                continue
        
        return candidates
    except Exception as e:
        print(f"[RAKE-Korean] 오류: {e}")
        import traceback
        traceback.print_exc()
        return []


def _find_phrase_spans_in_korean(original_text: str, phrase: str) -> List[Tuple[int, int]]:
    """
    형태소 분석된 구문을 원본 텍스트에서 찾기
    형태소 분석 과정에서 단어가 분리되거나 변형될 수 있으므로 유연하게 매칭
    """
    spans = []
    
    # phrase의 각 단어를 추출
    phrase_words = phrase.split()
    if not phrase_words:
        return spans
    
    # 원본 텍스트를 문장 단위로 분리
    sentences = re.split(r'[.!?。！？\n]+', original_text)
    
    for sentence in sentences:
        sentence_lower = sentence.lower()
        # phrase의 모든 단어가 문장에 포함되는지 확인
        all_words_found = all(
            any(word.lower() in word_candidate for word_candidate in sentence_lower.split())
            for word in phrase_words
        )
        
        if all_words_found:
            # 첫 번째 단어의 위치 찾기
            first_word = phrase_words[0].lower()
            pos = sentence_lower.find(first_word)
            if pos >= 0:
                # 문장의 시작 위치를 원본 텍스트 기준으로 변환
                sentence_start = original_text.find(sentence)
                if sentence_start >= 0:
                    start_pos = sentence_start + pos
                    # 대략적인 끝 위치 (구문 길이 기반)
                    end_pos = start_pos + len(phrase) + 20  # 여유 공간
                    spans.append((start_pos, min(end_pos, len(original_text))))
    
    # 간단한 방법: phrase의 키워드들이 포함된 부분 찾기
    if not spans:
        # phrase의 주요 키워드로 원본 텍스트 검색
        for word in phrase_words[:2]:  # 첫 2개 단어만
            word_lower = word.lower()
            start = 0
            while True:
                pos = original_text.lower().find(word_lower, start)
                if pos < 0:
                    break
                spans.append((pos, pos + len(word)))
                start = pos + 1
    
    # 중복 제거 및 정렬
    spans = sorted(list(set(spans)))
    
    return spans[:3]  # 최대 3개만 반환


def _extract_rake_english(
    text: str,
    max_phrase_length: int,
    top_k: int
) -> List[Dict[str, Any]]:
    """rake-nltk를 사용한 영어 키프레이즈 추출"""
    try:
        # NLTK stopwords 확인 및 다운로드
        try:
            import nltk
            try:
                nltk.data.find('corpora/stopwords')
            except LookupError:
                nltk.download('stopwords', quiet=True)
        except ImportError:
            pass
        
        # RAKE 초기화
        r = rake_nltk.Rake(max_length=max_phrase_length)
        r.extract_keywords_from_text(text)
        
        # 키워드와 점수 추출
        keywords_with_scores = r.get_ranked_phrases_with_scores()
        
        if not keywords_with_scores:
            return []
        
        candidates = []
        for item in keywords_with_scores[:top_k]:
            try:
                # RAKE 반환 형식: (score, phrase) 튜플
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                
                score = float(item[0])
                phrase = str(item[1])
                
                if not phrase or len(phrase.strip()) < 2:
                    continue
                
                phrase = phrase.strip()
                
                # 텍스트에서 위치 찾기
                spans = _find_phrase_spans(text, phrase)
                
                candidates.append({
                    "phrase": phrase,
                    "score": score,
                    "spans": spans,
                    "algorithm": "rake_nltk"
                })
            except Exception as item_err:
                # 개별 항목 처리 실패는 무시하고 계속 진행
                print(f"[RAKE-NLTK] 키워드 항목 처리 실패: {item}, 오류: {item_err}")
                continue
        
        return candidates
    except Exception as e:
        print(f"[RAKE-NLTK] 오류: {e}")
        import traceback
        traceback.print_exc()
        return []


def extract_candidates_with_yake(
    text: str,
    lang: str,
    max_ngram_size: int = 3,
    top_k: int = 50
) -> List[Dict[str, Any]]:
    """
    YAKE로 문서 내부 통계 기반 키워드/키프레이즈 후보 추출
    
    Args:
        text: 문서 텍스트
        lang: 언어 ("ko" 또는 "en")
        max_ngram_size: 최대 n-gram 크기
        top_k: 상위 k개 후보 반환
    
    Returns:
        [
            {
                "phrase": "데이터베이스",
                "score": 0.82,
                "spans": [(start_pos, end_pos)]
            },
            ...
        ]
    """
    if not YAKE_AVAILABLE or not text:
        return []
    
    try:
        # YAKE 초기화
        # lang: "ko" 또는 "en", n=max_ngram_size
        language_code = "ko" if lang == "ko" else "en"
        kw_extractor = yake.KeywordExtractor(
            lan=language_code,
            n=max_ngram_size,
            dedupLim=0.7,
            top=top_k
        )
        
        # 키워드 추출
        keywords = kw_extractor.extract_keywords(text)
        
        candidates = []
        for item in keywords:
            # YAKE 반환 형식: (score, phrase) 또는 (phrase, score)일 수 있음
            # 타입 체크로 안전하게 처리
            try:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    # 첫 번째가 숫자면 (score, phrase), 두 번째가 숫자면 (phrase, score)
                    if isinstance(item[0], (int, float)) or (hasattr(item[0], '__float__') and not isinstance(item[0], str)):
                        score = float(item[0])
                        phrase = str(item[1])
                    elif isinstance(item[1], (int, float)) or (hasattr(item[1], '__float__') and not isinstance(item[1], str)):
                        phrase = str(item[0])
                        score = float(item[1])
                    else:
                        # 둘 다 문자열이면 첫 번째를 phrase로, 점수는 기본값
                        phrase = str(item[0])
                        score = 1.0
                else:
                    # 단일 항목이면 phrase로 처리
                    phrase = str(item)
                    score = 1.0
                
                # phrase가 유효한 문자열인지 확인
                if not phrase or not isinstance(phrase, str):
                    continue
                
                phrase = phrase.strip()
                if len(phrase) < 2:
                    continue
                
                # YAKE 점수는 낮을수록 좋음 (일단 원본 점수 저장, 나중에 정규화)
                # 정규화는 문서 단위로 수행하므로 여기서는 원본 점수 저장
                raw_score = float(score)
                
                # 텍스트에서 위치 찾기
                spans = _find_phrase_spans(text, phrase)
                
                candidates.append({
                    "phrase": phrase,
                    "score": raw_score,  # 원본 점수 (나중에 정규화)
                    "spans": spans,
                    "algorithm": "yake"
                })
            except Exception as e:
                # 개별 항목 처리 실패는 무시하고 계속 진행
                print(f"[YAKE] 키워드 항목 처리 실패: {item}, 오류: {e}")
                continue
        
        # YAKE 점수 정규화 (문서 단위로 0~1, 방향 통일: 낮을수록 좋음 → 높을수록 좋게)
        if candidates:
            # YAKE 점수는 낮을수록 좋으므로 역변환 후 정규화
            raw_scores = [c["score"] for c in candidates]
            # 역변환: 낮은 점수 → 높은 점수
            inverted_scores = [1.0 / (1.0 + s) for s in raw_scores]
            # 정규화
            normalized_scores = _normalize_scores_to_0_1(inverted_scores)
            for i, cand in enumerate(candidates):
                cand["score"] = normalized_scores[i]
        
        return candidates
    except Exception as e:
        print(f"[YAKE] 오류: {e}")
        return []


def _find_phrase_spans(text: str, phrase: str) -> List[Tuple[int, int]]:
    """텍스트에서 구문의 모든 위치 찾기"""
    spans = []
    phrase_lower = phrase.lower()
    text_lower = text.lower()
    
    start = 0
    while True:
        pos = text_lower.find(phrase_lower, start)
        if pos < 0:
            break
        spans.append((pos, pos + len(phrase)))
        start = pos + 1
    
    return spans


def normalize_candidates(
    rake_candidates: List[Dict[str, Any]],
    yake_candidates: List[Dict[str, Any]],
    lang: str
) -> Dict[str, Dict[str, Any]]:
    """
    후보 키프레이즈 정규화 및 통합 (normalize_key 기반 중복 제거)
    
    Args:
        rake_candidates: RAKE 후보 리스트
        yake_candidates: YAKE 후보 리스트
        lang: 언어
    
    Returns:
        {
            "정규화된_태그": {
                "normalized": "정규화된_태그",
                "normalize_key": "normalize_key",
                "original_phrases": ["원본 구문1", "원본 구문2"],
                "sources": ["rake", "yake"],
                "spans": [(pos1, pos2), ...],
                "scores": {"rake": 0.85, "yake": 0.82}  # 0~1 정규화된 점수
            },
            ...
        }
    """
    # normalize_key 기준으로 그룹화 (중복 제거)
    by_normalize_key = {}
    
    # RAKE 후보 정규화
    for cand in rake_candidates:
        phrase = cand["phrase"]
        normalized_tag = _normalize_phrase(phrase, lang)
        normalize_key = _create_normalize_key(phrase)
        
        if not normalized_tag or not normalize_key:
            continue
        
        if normalize_key not in by_normalize_key:
            by_normalize_key[normalize_key] = {
                "normalized": normalized_tag,
                "normalize_key": normalize_key,
                "original_phrases": [],
                "sources": [],
                "spans": [],
                "scores": {},
                "best_score": 0.0  # best score 추적
            }
        
        entry = by_normalize_key[normalize_key]
        entry["original_phrases"].append(phrase)
        if "rake" not in entry["sources"]:
            entry["sources"].append("rake")
        entry["spans"].extend(cand["spans"])
        # best score 기준으로 업데이트
        if cand["score"] > entry["best_score"]:
            entry["best_score"] = cand["score"]
            entry["scores"]["rake"] = cand["score"]
    
    # YAKE 후보 정규화
    for cand in yake_candidates:
        phrase = cand["phrase"]
        normalized_tag = _normalize_phrase(phrase, lang)
        normalize_key = _create_normalize_key(phrase)
        
        if not normalized_tag or not normalize_key:
            continue
        
        if normalize_key not in by_normalize_key:
            by_normalize_key[normalize_key] = {
                "normalized": normalized_tag,
                "normalize_key": normalize_key,
                "original_phrases": [],
                "sources": [],
                "spans": [],
                "scores": {},
                "best_score": 0.0
            }
        
        entry = by_normalize_key[normalize_key]
        entry["original_phrases"].append(phrase)
        if "yake" not in entry["sources"]:
            entry["sources"].append("yake")
        entry["spans"].extend(cand["spans"])
        # best score 기준으로 업데이트
        if cand["score"] > entry["best_score"]:
            entry["best_score"] = cand["score"]
            entry["scores"]["yake"] = cand["score"]
    
    # normalized_tag를 키로 하는 딕셔너리로 변환 (기존 형식 유지)
    normalized = {}
    for normalize_key, entry in by_normalize_key.items():
        normalized_tag = entry["normalized"]
        # normalize_key가 같은 경우 best score를 가진 normalized_tag 사용
        if normalized_tag not in normalized or entry["best_score"] > normalized[normalized_tag].get("best_score", 0.0):
            normalized[normalized_tag] = {
                "normalized": normalized_tag,
                "normalize_key": normalize_key,
                "original_phrases": entry["original_phrases"],
                "sources": entry["sources"],
                "spans": sorted(list(set(entry["spans"]))),
                "scores": entry["scores"],
                "best_score": entry["best_score"]
            }
    
    return normalized


def _normalize_phrase(phrase: str, lang: str) -> str:
    """
    구문을 정규화된 태그 형식으로 변환
    - 토큰화
    - 동의어 적용
    - 언더스코어로 연결
    """
    # 토큰화
    tokens = tokenize(phrase)
    
    if not tokens:
        return ""
    
    # 동의어 적용
    normalized_tokens = [apply_synonyms(t) for t in tokens if t]
    
    # 언더스코어로 연결
    normalized = "_".join(normalized_tokens)
    
    return normalized if len(normalized) >= 2 else ""


def _create_normalize_key(phrase: str) -> str:
    """
    중복 제거를 위한 normalize_key 생성
    - 띄어쓰기 차이 등을 동일한 키로 매핑
    - trim, 다중 공백 1칸, 특수문자 양끝 제거
    """
    if not phrase:
        return ""
    
    # trim, 다중 공백 1칸 처리
    normalized = re.sub(r'\s+', ' ', phrase.strip())
    
    # 특수문자 양끝 제거 (언더스코어 제외)
    normalized = normalized.strip('.,;:!?()[]{}"\'-')
    
    # 소문자 변환 및 언더스코어를 공백으로 변환 (통일)
    normalized = normalized.lower().replace('_', ' ')
    
    # 다시 다중 공백 제거
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    return normalized


def _normalize_scores_to_0_1(scores: List[float]) -> List[float]:
    """
    점수 리스트를 0~1 범위로 정규화
    """
    if not scores:
        return []
    
    max_score = max(scores)
    if max_score <= 0:
        return scores  # 정규화 불가
    
    return [score / max_score for score in scores]


def _matches_domain_pattern(phrase: str) -> bool:
    """
    도메인 중요 패턴 매칭
    - 에러코드: ORA-\\d+, SQLSTATE, ERROR\\s*\\d+, NullPointerException
    - 제품/모듈명: 영문대문자+숫자 혼합 또는 '_' 포함 (예: XEDRM5, WAS_PATCH, JEUS8)
    """
    if not phrase:
        return False
    
    # 에러코드 패턴
    error_patterns = [
        r'ORA-\d+',
        r'SQLSTATE',
        r'ERROR\s*\d+',
        r'NullPointerException',
        r'OutOfMemoryError',
        r'StackOverflowError',
    ]
    
    for pattern in error_patterns:
        if re.search(pattern, phrase, re.IGNORECASE):
            return True
    
    # 제품/모듈명 패턴: 영문대문자+숫자 혼합 또는 '_' 포함
    # 예: XEDRM5, WAS_PATCH, JEUS8, APACHE_KAFKA
    product_pattern = r'^[A-Z][A-Z0-9_]*[A-Z0-9]$'
    if re.match(product_pattern, phrase):
        return True
    
    # 언더스코어 포함 및 영문대문자+숫자 혼합
    if '_' in phrase:
        parts = phrase.split('_')
        if len(parts) >= 2:
            # 모든 부분이 영문대문자+숫자로 시작
            if all(re.match(r'^[A-Z][A-Z0-9]*', part) for part in parts if part):
                return True
    
    return False


def compute_tfidf_for_candidates(
    normalized_candidates: Dict[str, Dict[str, Any]],
    tokens: List[str],
    state: TaggingState,
    lang: str,
    top_k: int = 50
) -> Tuple[Dict[str, float], List[str]]:
    """
    정규화된 후보들에 대해 TF-IDF 점수 계산 및 Top-K 반환
    
    Returns:
        (tfidf_scores, tfidf_topk_tags)
        - tfidf_scores: {"정규화된_태그": tfidf_score, ...}
        - tfidf_topk_tags: Top-K 태그 리스트
    """
    if not tokens:
        return {}, []
    
    # 각 정규화된 태그의 토큰들을 추출
    tag_token_sets = {}
    for tag, data in normalized_candidates.items():
        tag_tokens = tokenize(tag.replace("_", " "))
        tag_token_sets[tag] = set(tag_tokens)
    
    # 문서 내 TF 계산
    doc_tf = {}
    for token in tokens:
        doc_tf[token] = doc_tf.get(token, 0) + 1
    
    # 각 태그의 TF-IDF 점수 계산
    N = max(1, state.corpus_docs)
    tfidf_scores = {}
    
    for tag, tag_tokens in tag_token_sets.items():
        if not tag_tokens:
            continue
        
        # 태그를 구성하는 토큰들의 평균 TF-IDF
        token_scores = []
        for token in tag_tokens:
            if token in doc_tf:
                tf = doc_tf[token]
                df = max(0, int(state.df.get(token, 0)))
                idf = math.log((N + 1) / (df + 1)) + 1.0
                token_scores.append(tf * idf)
        
        if token_scores:
            # 평균 또는 합계 (평균 사용)
            tfidf_scores[tag] = sum(token_scores) / len(token_scores)
        else:
            tfidf_scores[tag] = 0.0
    
    # 정규화 (0.0~1.0)
    if tfidf_scores:
        max_score = max(tfidf_scores.values())
        if max_score > 0:
            tfidf_scores = {tag: score / max_score for tag, score in tfidf_scores.items()}
    
    # Top-K 태그 추출
    sorted_tags = sorted(tfidf_scores.items(), key=lambda x: x[1], reverse=True)
    tfidf_topk_tags = [tag for tag, score in sorted_tags[:top_k]]
    
    return tfidf_scores, tfidf_topk_tags


def compute_bm25_for_candidates(
    normalized_candidates: Dict[str, Dict[str, Any]],
    tokens: List[str],
    state: TaggingState,
    lang: str,
    top_k: int = 50,
    k1: float = 1.5,
    b: float = 0.75
) -> Tuple[Dict[str, float], List[str]]:
    """
    정규화된 후보들에 대해 BM25 점수 계산 및 Top-K 반환
    
    BM25 공식: IDF(t) * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_doc_len))
    IDF: log((N - df + 0.5) / (df + 0.5) + 1)
    
    Returns:
        (bm25_scores, bm25_topk_tags)
    """
    if not tokens:
        return {}, []
    
    tag_token_sets = {}
    for tag, data in normalized_candidates.items():
        tag_tokens = tokenize(tag.replace("_", " "))
        tag_token_sets[tag] = set(tag_tokens)
    
    doc_tf = {}
    for token in tokens:
        doc_tf[token] = doc_tf.get(token, 0) + 1
    
    doc_len = len(tokens)
    N = max(1, state.corpus_docs)
    avg_doc_len = max(1.0, state.avg_doc_length)
    
    bm25_scores = {}
    for tag, tag_tokens in tag_token_sets.items():
        if not tag_tokens:
            continue
        token_scores = []
        for token in tag_tokens:
            if token in doc_tf:
                tf = doc_tf[token]
                df = max(0, int(state.df.get(token, 0)))
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
                length_norm = 1.0 - b + b * (doc_len / avg_doc_len)
                bm25 = idf * (tf * (k1 + 1)) / (tf + k1 * length_norm)
                token_scores.append(bm25)
        if token_scores:
            bm25_scores[tag] = sum(token_scores) / len(token_scores)
        else:
            bm25_scores[tag] = 0.0
    
    if bm25_scores:
        max_score = max(bm25_scores.values())
        if max_score > 0:
            bm25_scores = {tag: score / max_score for tag, score in bm25_scores.items()}
    
    sorted_tags = sorted(bm25_scores.items(), key=lambda x: x[1], reverse=True)
    bm25_topk_tags = [tag for tag, score in sorted_tags[:top_k]]
    
    return bm25_scores, bm25_topk_tags


def extract_evidence_spans(
    tag: str,
    spans: List[Tuple[int, int]],
    text: str,
    max_spans: int = 3
) -> List[Dict[str, Any]]:
    """
    태그의 증거 구문(evidence spans) 추출
    
    Returns:
        [
            {
                "text": "카프카 클러스터 설정",
                "position": 120,
                "algorithm": "rake"
            },
            ...
        ]
    """
    evidence = []
    
    # spans를 위치 순으로 정렬하고 상위 N개만 선택
    sorted_spans = sorted(spans, key=lambda x: x[0])[:max_spans]
    
    for start, end in sorted_spans:
        # 주변 컨텍스트 포함하여 추출 (각 20자)
        context_start = max(0, start - 20)
        context_end = min(len(text), end + 20)
        
        span_text = text[context_start:context_end].strip()
        if span_text:
            evidence.append({
                "text": span_text,
                "position": start,
                "algorithm": "multi"  # 여러 알고리즘 통합 결과
            })
    
    return evidence


def _get_semantic_model(lang: str):
    """의미 기반 보정 모델 초기화 (지연 로딩)"""
    global _SEMANTIC_MODEL_KO, _SEMANTIC_MODEL_EN
    
    if lang == "ko":
        if _SEMANTIC_MODEL_KO is None and SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                # 모델이 이미 캐시에 있는지 확인
                import os
                from pathlib import Path
                cache_dir = Path.home() / '.cache' / 'huggingface' / 'hub'
                model_cache_exists = False
                if cache_dir.exists():
                    model_dirs = list(cache_dir.glob('models--jhgan--ko-sbert-multitask*'))
                    if model_dirs:
                        # 모델 파일이 있는지 확인
                        for model_dir in model_dirs:
                            model_files = list(model_dir.rglob('*.bin')) + list(model_dir.rglob('*.safetensors'))
                            if model_files:
                                model_cache_exists = True
                                break
                
                if model_cache_exists:
                    print("[의미보정] ko-sbert 모델 로드 중... (캐시에서)")
                else:
                    print("[의미보정] ko-sbert 모델 다운로드 중... (약 442MB, 시간이 걸릴 수 있습니다)")
                
                # 타임아웃 설정을 위한 스레드 사용
                import threading
                import queue
                
                result_queue = queue.Queue()
                
                def load_model():
                    try:
                        # SentenceTransformer는 자동으로 캐시를 확인하고 사용함
                        model = SentenceTransformer('jhgan/ko-sbert-multitask')
                        result_queue.put(("success", model))
                    except Exception as e:
                        result_queue.put(("error", e))
                
                thread = threading.Thread(target=load_model, daemon=True)
                thread.start()
                thread.join(timeout=300)  # 5분 타임아웃
                
                if thread.is_alive():
                    print("[의미보정] ko-sbert 모델 로드 타임아웃 (5분 초과)")
                    print("[의미보정] 네트워크 문제일 수 있습니다. 나중에 다시 시도하거나 의미 보정을 비활성화하세요.")
                    return None
                
                try:
                    status, value = result_queue.get_nowait()
                    if status == "success":
                        _SEMANTIC_MODEL_KO = value
                        if model_cache_exists:
                            print("[의미보정] ko-sbert 모델 로드 완료 (캐시에서)")
                        else:
                            print("[의미보정] ko-sbert 모델 다운로드 및 로드 완료")
                    else:
                        raise value
                except queue.Empty:
                    print("[의미보정] ko-sbert 모델 로드 결과를 받지 못했습니다.")
                    return None
                    
            except Exception as e:
                import traceback
                print(f"[의미보정] ko-sbert 로드 실패: {e}")
                print("[의미보정] 상세 오류:")
                traceback.print_exc()
                print("[의미보정] 의미 보정 없이 계속 진행합니다.")
                return None
        return _SEMANTIC_MODEL_KO
    else:
        if _SEMANTIC_MODEL_EN is None and TRANSFORMERS_AVAILABLE:
            try:
                print("[의미보정] sentence-bart 모델 다운로드 중... (시간이 걸릴 수 있습니다)")
                # 영어 모델은 더 크므로 타임아웃 더 길게
                import threading
                import queue
                
                result_queue = queue.Queue()
                
                def load_model():
                    try:
                        model = pipeline('feature-extraction', model='facebook/bart-large')
                        result_queue.put(("success", model))
                    except Exception as e:
                        result_queue.put(("error", e))
                
                thread = threading.Thread(target=load_model, daemon=True)
                thread.start()
                thread.join(timeout=600)  # 10분 타임아웃
                
                if thread.is_alive():
                    print("[의미보정] sentence-bart 모델 다운로드 타임아웃 (10분 초과)")
                    print("[의미보정] 네트워크 문제일 수 있습니다. 나중에 다시 시도하거나 의미 보정을 비활성화하세요.")
                    return None
                
                try:
                    status, value = result_queue.get_nowait()
                    if status == "success":
                        _SEMANTIC_MODEL_EN = value
                        print("[의미보정] sentence-bart 모델 로드 완료")
                    else:
                        raise value
                except queue.Empty:
                    print("[의미보정] sentence-bart 모델 로드 결과를 받지 못했습니다.")
                    return None
                    
            except Exception as e:
                print(f"[의미보정] sentence-bart 로드 실패: {e}")
                print("[의미보정] 의미 보정 없이 계속 진행합니다.")
                return None
        return _SEMANTIC_MODEL_EN


def compute_semantic_similarity(
    tag: str,
    text: str,
    lang: str,
    evidence_spans: List[Dict[str, Any]] = None
) -> float:
    """
    태그와 문서 텍스트 간 의미적 유사도 계산
    
    Args:
        tag: 태그 (예: "카프카_클러스터")
        text: 문서 텍스트
        lang: 언어 ("ko" 또는 "en")
        evidence_spans: 증거 구문 리스트 (있는 경우 사용)
    
    Returns:
        의미적 유사도 점수 (0.0~1.0)
    """
    if not text or not tag:
        return 0.0
    
    model = _get_semantic_model(lang)
    if not model:
        return 0.0
    
    try:
        # 태그를 자연어로 변환 (언더스코어를 공백으로)
        tag_text = tag.replace("_", " ")
        
        # 증거 구문이 있으면 그것을 사용, 없으면 전체 텍스트 샘플
        if evidence_spans and len(evidence_spans) > 0:
            # 증거 구문들을 결합
            evidence_texts = [ev.get("text", "") for ev in evidence_spans[:3] if ev.get("text")]
            if evidence_texts:
                doc_sample = " ".join(evidence_texts)
            else:
                # 전체 텍스트에서 샘플 추출
                doc_sample = text[:500] if len(text) > 500 else text
        else:
            # 전체 텍스트에서 샘플 추출
            doc_sample = text[:500] if len(text) > 500 else text
        
        if lang == "ko" and SENTENCE_TRANSFORMERS_AVAILABLE:
            # ko-sbert 사용
            try:
                embeddings = model.encode([tag_text, doc_sample])
                # 코사인 유사도 계산
                try:
                    import numpy as np
                    similarity = np.dot(embeddings[0], embeddings[1]) / (np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1]))
                    return float(max(0.0, min(1.0, similarity)))
                except ImportError:
                    # numpy 없으면 간단한 유클리드 거리 기반 근사치
                    diff = embeddings[0] - embeddings[1]
                    distance = sum(diff ** 2) ** 0.5
                    similarity = 1.0 / (1.0 + distance)
                    return float(max(0.0, min(1.0, similarity)))
            except Exception as e:
                print(f"[의미보정] ko-sbert 인코딩 실패: {e}")
                return 0.0
        
        elif lang != "ko" and TRANSFORMERS_AVAILABLE:
            # sentence-bart 사용 (간단한 구현)
            # 실제로는 더 정교한 구현 필요
            # 여기서는 간단히 키워드 매칭 기반으로 근사치 계산
            tag_words = set(tag_text.lower().split())
            doc_words = set(doc_sample.lower().split())
            if not tag_words or not doc_words:
                return 0.0
            # Jaccard 유사도
            intersection = len(tag_words & doc_words)
            union = len(tag_words | doc_words)
            return intersection / union if union > 0 else 0.0
        
    except Exception as e:
        print(f"[의미보정] 유사도 계산 실패: {e}")
        return 0.0
    
    return 0.0


def apply_semantic_confidence_adjustment(
    tags: List[Dict[str, Any]],
    text: str,
    lang: str,
    adjustment_weight: float = 0.3
) -> List[Dict[str, Any]]:
    """
    의미 기반 신뢰도 보정 적용
    
    Args:
        tags: 태그 리스트 (confidence 포함)
        text: 문서 텍스트
        lang: 언어
        adjustment_weight: 의미 보정 가중치 (0.0~1.0, 기본 0.3)
    
    Returns:
        보정된 태그 리스트
    """
    if not tags or not text:
        return tags
    
    adjusted_tags = []
    for tag_item in tags:
        tag = tag_item.get("tag", "")
        original_confidence = tag_item.get("confidence", tag_item.get("score", 0.0))
        
        # 의미적 유사도 계산
        evidence_spans = tag_item.get("evidence_spans", [])
        semantic_score = compute_semantic_similarity(tag, text, lang, evidence_spans)
        
        # 보정된 신뢰도 = 원본 신뢰도 * (1 - weight) + 의미 점수 * weight
        adjusted_confidence = original_confidence * (1.0 - adjustment_weight) + semantic_score * adjustment_weight
        
        # 메타데이터 추가
        tag_item = tag_item.copy()
        tag_item["confidence_original"] = original_confidence
        tag_item["confidence_adjusted"] = round(adjusted_confidence, 4)
        tag_item["semantic_score"] = round(semantic_score, 4)
        tag_item["confidence"] = round(adjusted_confidence, 4)  # 최종 신뢰도 업데이트
        
        adjusted_tags.append(tag_item)
    
    # 보정된 신뢰도 순으로 재정렬
    adjusted_tags.sort(key=lambda x: x.get("confidence", 0.0), reverse=True)
    
    return adjusted_tags


def build_consensus_tags(
    normalized_candidates: Dict[str, Dict[str, Any]],
    tfidf_scores: Dict[str, float],
    tfidf_topk_tags: List[str],
    rake_topk_tags: List[str] = None,
    yake_topk_tags: List[str] = None,
    min_support: int = 2,
    top_k: int = 12,
    text: str = "",
    lang: str = "ko",
    use_semantic_adjustment: bool = True,
    # 가중치 파라미터
    wr: float = 0.3,  # RAKE 가중치
    wy: float = 0.3,  # YAKE 가중치
    wt: float = 0.4,  # TF-IDF/BM25 가중치
    alpha: float = 0.2,  # 보너스 계수
    exception_tfidf_rank: int = 3,  # 예외 규칙 상위 순위
    stat_name: str = "tfidf"  # "tfidf" 또는 "bm25" (support_algorithms/scores 키)
) -> List[Dict[str, Any]]:
    """
    새로운 합의 기반 태그 생성 (G(c) × A(c) × B(c) 방식)
    
    Args:
        normalized_candidates: 정규화된 후보 딕셔너리
        tfidf_scores: TF-IDF 점수 딕셔너리
        tfidf_topk_tags: TF-IDF Top-K 태그 리스트
        rake_topk_tags: RAKE Top-K 태그 리스트 (normalized_tag 기준)
        yake_topk_tags: YAKE Top-K 태그 리스트 (normalized_tag 기준)
        min_support: 최소 지지 알고리즘 수 (기본 2, 사용 안함)
        top_k: 상위 k개 태그 반환
        text: 문서 텍스트 (증거 추출용)
        lang: 언어
        use_semantic_adjustment: 의미 기반 보정 사용 여부
        wr, wy, wt: 가중치 (기본값: 0.3, 0.3, 0.4)
        alpha: 보너스 계수 (기본값: 0.2)
        exception_tfidf_rank: 예외 규칙 TF-IDF 상위 순위 (기본값: 3)
    
    Returns:
        [
            {
                "tag": "카프카_클러스터",
                "confidence": 0.92,
                "support_algorithms": ["rake", "yake", "tfidf"],
                "evidence_spans": [...],
                "scores": {...},
                "votes": 3,
                "gate": 1,
                "weighted_avg": 0.70,
                "bonus": 1.2
            },
            ...
        ]
    """
    if not normalized_candidates or not tfidf_scores:
        return []
    
    # Top-K 태그 집합 (votes 계산용)
    rake_topk_set = set(rake_topk_tags) if rake_topk_tags else set()
    yake_topk_set = set(yake_topk_tags) if yake_topk_tags else set()
    tfidf_topk_set = set(tfidf_topk_tags) if tfidf_topk_tags else set()
    
    # TF-IDF rank 계산 (예외 규칙용)
    sorted_tfidf = sorted(tfidf_scores.items(), key=lambda x: x[1], reverse=True)
    tfidf_rank_map = {tag: rank + 1 for rank, (tag, _) in enumerate(sorted_tfidf)}
    
    consensus_tags = []
    
    for tag, data in normalized_candidates.items():
        # 1. Votes 계산: I(c in RAKE Top-K) + I(c in YAKE Top-K) + I(c in TF-IDF Top-K)
        votes = 0
        if tag in rake_topk_set:
            votes += 1
        if tag in yake_topk_set:
            votes += 1
        if tag in tfidf_topk_set:
            votes += 1
        
        # 2. Gate 계산: G(c) = 1 if votes(c) >= 2 else 0
        gate = 1 if votes >= 2 else 0
        
        # 예외 규칙: votes==1이더라도 TF-IDF 상위 + 도메인 패턴이면 Gate=1
        if votes == 1 and gate == 0:
            tfidf_rank = tfidf_rank_map.get(tag, 999)
            if tfidf_rank <= exception_tfidf_rank:
                # 도메인 패턴 확인
                original_phrases = data.get("original_phrases", [])
                if original_phrases and any(_matches_domain_pattern(phrase) for phrase in original_phrases):
                    gate = 1
        
        # Gate=0이면 제외
        if gate == 0:
            continue
        
        # 3. 가중 평균 계산: A(c) = wr × r(c) + wy × y(c) + wt × t(c)
        r_score = data["scores"].get("rake", 0.0)  # 0~1 정규화됨
        y_score = data["scores"].get("yake", 0.0)  # 0~1 정규화됨
        t_score = tfidf_scores.get(tag, 0.0)  # 0~1 정규화됨
        
        # 가중치 합계 계산 (있는 알고리즘만)
        total_weight = 0.0
        weighted_sum = 0.0
        
        if "rake" in data["sources"]:
            total_weight += wr
            weighted_sum += wr * r_score
        if "yake" in data["sources"]:
            total_weight += wy
            weighted_sum += wy * y_score
        if tag in tfidf_topk_set:
            total_weight += wt
            weighted_sum += wt * t_score
        
        # 가중 평균 (0으로 나누기 방지)
        if total_weight > 0:
            weighted_avg = weighted_sum / total_weight
        else:
            weighted_avg = 0.0
        
        # 4. 보너스 계산: B(c) = 1 + alpha × (votes(c) - 2)
        if votes >= 2:
            bonus = 1.0 + alpha * (votes - 2)
        else:
            bonus = 1.0  # votes < 2인 경우 (예외 규칙으로 통과한 경우)
        
        # 5. 최종 점수 계산: Score(c) = G(c) × A(c) × B(c)
        final_score = gate * weighted_avg * bonus
        
        # 증거 구문 추출
        evidence_spans = []
        if text and data.get("spans"):
            evidence_spans = extract_evidence_spans(
                tag,
                data["spans"],
                text,
                max_spans=3
            )
        
        # 지지 알고리즘 리스트
        support_algorithms = []
        if tag in rake_topk_set:
            support_algorithms.append("rake")
        if tag in yake_topk_set:
            support_algorithms.append("yake")
        if tag in tfidf_topk_set:
            support_algorithms.append(stat_name)
        
        # 점수 딕셔너리
        scores = data["scores"].copy()
        scores[stat_name] = t_score
        
        consensus_tags.append({
            "tag": tag,
            "confidence": round(final_score, 4),
            "support_algorithms": support_algorithms,
            "evidence_spans": evidence_spans,
            "scores": scores,
            "support_count": len(support_algorithms),
            "votes": votes,
            "gate": gate,
            "weighted_avg": round(weighted_avg, 4),
            "bonus": round(bonus, 4)
        })
    
    # 최종 점수 순으로 정렬
    consensus_tags.sort(key=lambda x: x["confidence"], reverse=True)
    
    # 의미 기반 신뢰도 보정 적용 (선택적)
    if use_semantic_adjustment and text:
        consensus_tags = apply_semantic_confidence_adjustment(
            consensus_tags,
            text,
            lang,
            adjustment_weight=0.3
        )
    
    # 최소 태그 수 보장: top_k 미만이면 조건 완화하여 추가 태그 생성
    if len(consensus_tags) < top_k and len(normalized_candidates) > len(consensus_tags):
        existing_tags = {t["tag"] for t in consensus_tags}
        fallback_tags = []
        
        for tag, data in normalized_candidates.items():
            if tag in existing_tags:
                continue
            
            t_score = tfidf_scores.get(tag, 0.0)
            # 완화된 조건: TF-IDF 점수가 0.3 이상이면 포함
            if t_score >= 0.3:
                # 간단한 점수 계산 (fallback)
                votes = 0
                if tag in rake_topk_set:
                    votes += 1
                if tag in yake_topk_set:
                    votes += 1
                if tag in tfidf_topk_set:
                    votes += 1
                
                gate = 1 if votes >= 1 else 0  # 완화된 조건
                if gate == 0:
                    continue
                
                r_score = data["scores"].get("rake", 0.0)
                y_score = data["scores"].get("yake", 0.0)
                
                # 간단한 가중 평균
                total_weight = 0.0
                weighted_sum = 0.0
                if "rake" in data["sources"]:
                    total_weight += wr
                    weighted_sum += wr * r_score
                if "yake" in data["sources"]:
                    total_weight += wy
                    weighted_sum += wy * y_score
                if tag in tfidf_topk_set:
                    total_weight += wt
                    weighted_sum += wt * t_score
                
                if total_weight > 0:
                    weighted_avg = weighted_sum / total_weight
                else:
                    weighted_avg = t_score  # fallback
                
                bonus = 1.0 + alpha * max(0, votes - 1)  # 완화된 보너스
                final_score = gate * weighted_avg * bonus * 0.8  # 완화된 점수 (0.8 배율)
                
                support_algorithms = []
                if tag in rake_topk_set:
                    support_algorithms.append("rake")
                if tag in yake_topk_set:
                    support_algorithms.append("yake")
                if tag in tfidf_topk_set:
                    support_algorithms.append(stat_name)
                
                scores = data["scores"].copy()
                scores[stat_name] = t_score
                
                fallback_tags.append({
                    "tag": tag,
                    "confidence": round(final_score, 4),
                    "support_algorithms": support_algorithms,
                    "evidence_spans": [],
                    "scores": scores,
                    "support_count": len(support_algorithms),
                    "votes": votes,
                    "gate": gate,
                    "weighted_avg": round(weighted_avg, 4),
                    "bonus": round(bonus, 4)
                })
        
        # Fallback 태그도 점수 순으로 정렬
        fallback_tags.sort(key=lambda x: x["confidence"], reverse=True)
        
        # 필요한 만큼만 추가
        needed = top_k - len(consensus_tags)
        consensus_tags.extend(fallback_tags[:needed])
        
        # 다시 정렬
        consensus_tags.sort(key=lambda x: x["confidence"], reverse=True)
    
    return consensus_tags[:top_k]


def evaluate_tagging_quality(
    tags: List[Dict[str, Any]],
    text: str,
    genre: Optional[str] = None
) -> Dict[str, Any]:
    """
    태깅 품질 평가: Coverage, Diversity, Genre consistency 등 지표
    
    Args:
        tags: tags_topk 형식 리스트
        text: 문서 텍스트
        genre: 문서 장르
    
    Returns:
        quality_metrics, overall_score, recommendation
    """
    if not tags:
        return {
            "overall_score": 0.0,
            "metrics": {
                "coverage": 0.0,
                "diversity": 0.0,
                "genre_consistency": 0.0,
                "confidence_avg": 0.0,
                "support_avg": 0.0,
            },
            "recommendation": "needs_improvement",
        }
    text_lower = (text or "").lower()
    tag_phrases = [t.get("tag", "").strip() for t in tags if t.get("tag")]
    # Coverage: 태그가 텍스트에 얼마나 등장하는지
    coverage = 0.0
    if text_lower and tag_phrases:
        hits = sum(1 for t in tag_phrases if t and t.lower() in text_lower)
        coverage = hits / len(tag_phrases) if tag_phrases else 0.0
    # Diversity: 태그 간 고유 단어 비율 (중복 단어 적을수록 높음)
    all_words = set()
    for t in tag_phrases:
        all_words.update(t.split())
    total_words = sum(len(t.split()) for t in tag_phrases)
    diversity = len(all_words) / total_words if total_words > 0 else 0.0
    diversity = min(1.0, diversity)  # 1.0 상한
    # Genre consistency: 장르별 가중치 (procedure/report/issue/resolution)
    genre_keywords = {
        "procedure": ["단계", "절차", "step", "procedure", "방법"],
        "report": ["결과", "분석", "통계", "result", "analysis"],
        "issue": ["문제", "오류", "원인", "issue", "error"],
        "resolution": ["해결", "조치", "solution", "fix"],
    }
    genre_consistency = 0.5  # 기본값
    if genre and genre in genre_keywords:
        kw = genre_keywords[genre]
        tag_str = " ".join(tag_phrases).lower()
        matches = sum(1 for k in kw if k in tag_str)
        genre_consistency = 0.5 + 0.1 * min(matches, 5)  # 0.5~1.0
    # Confidence / Support
    confs = [t.get("confidence", t.get("score", 0.0)) for t in tags]
    confidence_avg = sum(confs) / len(confs) if confs else 0.0
    supports = [t.get("support_count", len(t.get("support_algorithms", []))) for t in tags]
    support_avg = sum(supports) / len(supports) if supports else 0.0
    # Overall score
    overall = (
        coverage * 0.3 + diversity * 0.2 + genre_consistency * 0.2 +
        min(1.0, confidence_avg) * 0.2 + min(1.0, support_avg / 3.0) * 0.1
    )
    overall = min(1.0, overall)
    return {
        "overall_score": round(overall, 4),
        "metrics": {
            "coverage": round(coverage, 4),
            "diversity": round(diversity, 4),
            "genre_consistency": round(genre_consistency, 4),
            "confidence_avg": round(confidence_avg, 4),
            "support_avg": round(support_avg, 4),
        },
        "recommendation": "good" if overall > 0.7 else "needs_improvement",
    }


def auto_tag_document_chunked(
    *,
    out_root: str,
    doc_id: str,
    title: str,
    text: str,
    chunk_size: int = 50000,
    language: Optional[str] = None,
    top_k: int = 12,
    topic_sentence: Optional[str] = None,
    use_multi_algorithm: bool = True,
    min_algorithm_support: int = 2,
    use_semantic_adjustment: bool = False,
) -> dict:
    """
    대용량 문서(10만자 이상) 청크 단위 태깅 후 병합
    """
    if not text or len(text) <= chunk_size:
        return auto_tag_document(
            out_root=out_root,
            doc_id=doc_id,
            title=title,
            text=text,
            language=language,
            top_k=top_k,
            topic_sentence=topic_sentence,
            use_multi_algorithm=use_multi_algorithm,
            min_algorithm_support=min_algorithm_support,
            use_semantic_adjustment=use_semantic_adjustment,
        )
    chunks_list: List[str] = []
    for i in range(0, len(text), chunk_size):
        chunks_list.append(text[i : i + chunk_size])
    chunk_tags: List[Dict] = []
    last_result: Optional[dict] = None
    for i, chunk in enumerate(chunks_list):
        try:
            result = auto_tag_document(
                out_root=out_root,
                doc_id=doc_id,
                title=title,
                text=chunk,
                language=language,
                top_k=top_k,
                topic_sentence=topic_sentence,
                use_multi_algorithm=use_multi_algorithm,
                min_algorithm_support=min_algorithm_support,
                use_semantic_adjustment=use_semantic_adjustment,
            )
            last_result = result
            chunk_tags.extend(result.get("tags_topk", []))
        except Exception as e:
            print(f"[태깅-청크] 청크 {i + 1}/{len(chunks_list)} 태깅 실패: {e}")
    if not last_result:
        raise RuntimeError("대용량 문서 청크 태깅 실패")
    seen: Dict[str, Dict] = {}
    for t in chunk_tags:
        tag = (t.get("tag") or "").strip()
        if not tag:
            continue
        key = tag.lower()
        conf = t.get("confidence", t.get("score", 0.0))
        if key not in seen or conf > seen[key].get("confidence", 0.0):
            seen[key] = t
    merged = sorted(seen.values(), key=lambda x: x.get("confidence", 0.0), reverse=True)[:top_k]
    last_result["tags_topk"] = merged
    last_result["chunked_tagging"] = True
    last_result["chunk_count"] = len(chunks_list)
    out_root_p = Path(out_root)
    (out_root_p / doc_id / "auto_tags.json").write_text(
        json.dumps(last_result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return last_result


def auto_tag_document_multi_algorithm(
    *,
    out_root: str,
    doc_id: str,
    title: str,
    text: str,
    language: Optional[str] = None,
    top_k: int = 12,
    topic_sentence: Optional[str] = None,
    min_support: int = 2,
    text_for_evidence: Optional[str] = None,
    use_semantic_adjustment: bool = False  # 메모리 절약을 위해 기본값 False
) -> dict:
    """
    다중 알고리즘 합의 기반 태깅 파이프라인
    
    Returns:
        기존 auto_tag_document와 동일한 형식 (schema_version=2)
    """
    out_root_p = Path(out_root)
    doc_dir = out_root_p / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    
    lang = language or guess_language(text)
    
    # 주제문장 처리
    text_for_tagging = text or ""
    if topic_sentence and topic_sentence.strip():
        text_for_tagging = f"{topic_sentence.strip()}\n\n{text_for_tagging}"
    
    # 증거 추출용 원본 텍스트
    evidence_text = text_for_evidence or text_for_tagging
    
    # 장르 분류 (기존 로직 유지)
    title_for_genre = title or ""
    if topic_sentence and topic_sentence.strip():
        title_for_genre = f"{title_for_genre} {topic_sentence.strip()}"
    genre_info = classify_genre(text=text_for_tagging or "", title=title_for_genre)
    
    # 1~2단계: RAKE와 YAKE 병렬 실행
    print(f"[태깅-다중알고리즘] 1~2단계: RAKE/YAKE 병렬 후보 추출 시작")
    rake_candidates: List[Dict] = []
    yake_candidates: List[Dict] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {}
        if RAKE_AVAILABLE:
            futures[executor.submit(extract_candidates_with_rake, text_for_tagging, lang, top_k=50)] = "rake"
        if YAKE_AVAILABLE:
            futures[executor.submit(extract_candidates_with_yake, text_for_tagging, lang, top_k=50)] = "yake"
        for future in as_completed(futures, timeout=60):
            name = futures[future]
            try:
                result = future.result(timeout=30)
                if name == "rake":
                    rake_candidates = result or []
                    print(f"[태깅-다중알고리즘] RAKE 후보: {len(rake_candidates)}개")
                else:
                    yake_candidates = result or []
                    print(f"[태깅-다중알고리즘] YAKE 후보: {len(yake_candidates)}개")
            except Exception as e:
                print(f"[태깅-다중알고리즘] {name.upper()} 추출 실패 (계속 진행): {e}")
    
    # 3단계: 후보 정규화
    print(f"[태깅-다중알고리즘] 3단계: 후보 정규화 시작")
    try:
        normalized_candidates = normalize_candidates(rake_candidates, yake_candidates, lang)
        print(f"[태깅-다중알고리즘] 정규화된 후보: {len(normalized_candidates)}개")
    except Exception as e:
        print(f"[태깅-다중알고리즘] 후보 정규화 실패 (계속 진행): {e}")
        normalized_candidates = {}
    
    # 4단계: BM25 점수 계산 및 Top-K 추출
    print(f"[태깅-다중알고리즘] 4단계: BM25 점수 계산 시작")
    try:
        tokens = tokenize(text_for_tagging)
        unique_terms = set(tokens)
        
        state_path = out_root_p / "auto_tagging_state.json"
        state = TaggingState.load(state_path)
        
        bm25_scores, bm25_topk_tags = compute_bm25_for_candidates(
            normalized_candidates, tokens, state, lang, top_k=50
        )
        print(f"[태깅-다중알고리즘] BM25 점수 계산 완료: {len(bm25_scores)}개, Top-K: {len(bm25_topk_tags)}개")
    except Exception as e:
        print(f"[태깅-다중알고리즘] BM25 계산 실패: {e}")
        import traceback
        traceback.print_exc()
        raise  # BM25는 필수이므로 실패 시 예외 발생
    
    # RAKE/YAKE Top-K 태그 추출 (normalized_tag 기준)
    rake_topk_tags = []
    yake_topk_tags = []
    if rake_candidates:
        # RAKE 후보를 점수 순으로 정렬하고 normalized_tag 추출
        sorted_rake = sorted(rake_candidates, key=lambda x: x["score"], reverse=True)
        for cand in sorted_rake[:50]:  # Top-50
            normalized_tag = _normalize_phrase(cand["phrase"], lang)
            if normalized_tag and normalized_tag not in rake_topk_tags:
                rake_topk_tags.append(normalized_tag)
    
    if yake_candidates:
        # YAKE 후보를 점수 순으로 정렬하고 normalized_tag 추출
        sorted_yake = sorted(yake_candidates, key=lambda x: x["score"], reverse=True)
        for cand in sorted_yake[:50]:  # Top-50
            normalized_tag = _normalize_phrase(cand["phrase"], lang)
            if normalized_tag and normalized_tag not in yake_topk_tags:
                yake_topk_tags.append(normalized_tag)
    
    # 5단계: 합의 기반 태그 생성 (BM25 앙상블)
    print(f"[태깅-다중알고리즘] 5단계: BM25 앙상블 합의 태그 생성 시작")
    try:
        consensus_tags = build_consensus_tags(
            normalized_candidates,
            bm25_scores,
            bm25_topk_tags,
            rake_topk_tags=rake_topk_tags,
            yake_topk_tags=yake_topk_tags,
            min_support=min_support,
            top_k=top_k,
            text=text_for_tagging,
            lang=lang,
            use_semantic_adjustment=use_semantic_adjustment,
            stat_name="bm25"
        )
        print(f"[태깅-다중알고리즘] BM25 앙상블 합의 태그 생성 완료: {len(consensus_tags)}개")
    except Exception as e:
        print(f"[태깅-다중알고리즘] 합의 태그 생성 실패: {e}")
        import traceback
        traceback.print_exc()
        raise  # 태그 생성 실패는 치명적 오류
    
    # 6단계: 증거 구문 추가
    for tag_item in consensus_tags:
        tag = tag_item["tag"]
        if tag in normalized_candidates:
            spans = normalized_candidates[tag]["spans"]
            tag_item["evidence_spans"] = extract_evidence_spans(tag, spans, evidence_text)
    
    # 상태 업데이트
    update_df_state(state, unique_terms, doc_length=len(tokens))
    state.save(state_path)
    
    # 태깅 품질 평가
    quality = evaluate_tagging_quality(
        consensus_tags,
        text_for_tagging or "",
        genre_info.get("genre")
    )
    # 결과 반환 (기존 형식과 호환)
    result = {
        "doc_id": doc_id,
        "schema_version": 2,  # 새 버전 표시
        "generated_at": now_iso(),
        "language": lang,
        "topic_sentence": topic_sentence.strip() if topic_sentence else None,
        "genre": genre_info["genre"],
        "genre_confidence": genre_info["confidence"],
        "genre_evidence": genre_info.get("evidence", []),
        "tags_topk": consensus_tags,  # BM25 앙상블
        "tagging_quality": quality,
        "algorithm_info": {
            "rake_available": RAKE_AVAILABLE,
            "multi_rake_available": MULTI_RAKE_AVAILABLE,
            "kiwipiepy_available": KIWIPIEPY_AVAILABLE,
            "rake_nltk_available": RAKE_NLTK_AVAILABLE,
            "konlpy_available": KONLPY_AVAILABLE,
            "yake_available": YAKE_AVAILABLE,
            "semantic_adjustment_available": SENTENCE_TRANSFORMERS_AVAILABLE or TRANSFORMERS_AVAILABLE,
            "semantic_model_ko": "ko-sbert" if (lang == "ko" and SENTENCE_TRANSFORMERS_AVAILABLE) else None,
            "semantic_model_en": "sentence-bart" if (lang != "ko" and TRANSFORMERS_AVAILABLE) else None,
            "language": lang,
            "min_support": min_support
        }
    }
    
    (doc_dir / "auto_tags.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return result


def auto_tag_document(
    *,
    out_root: str,
    doc_id: str,
    title: str,
    text: str,
    language: Optional[str] = None,
    top_k: int = 12,
    topic_sentence: Optional[str] = None,
    use_multi_algorithm: bool = True,
    min_algorithm_support: int = 2,
    use_semantic_adjustment: bool = False  # 메모리 절약을 위해 기본값 False
) -> dict:
    """
    자동 태깅 (다중 알고리즘 합의 기반 또는 BM25)
    
    결과는 output/<doc_id>/auto_tags.json 으로 저장.
    - genre(문서종류) + confidence + evidence
    - tags_topk: 태그 리스트 (schema_version에 따라 형식 다름)
    - topic_sentence: 주제문장이 있으면 태그 우선순위 조정 및 장르 분류에 활용
    
    Args:
        use_multi_algorithm: True면 다중 알고리즘 파이프라인 사용, False면 BM25
        min_algorithm_support: 최소 지지 알고리즘 수 (기본 2)
    
    Returns:
        dict: 태깅 결과 (schema_version으로 구분)
    """
    # 다중 알고리즘 파이프라인 사용 시도
    if use_multi_algorithm and (RAKE_AVAILABLE or YAKE_AVAILABLE):
        try:
            print(f"[태깅] 다중 알고리즘 파이프라인 시작 (RAKE: {RAKE_AVAILABLE}, YAKE: {YAKE_AVAILABLE})")
            result = auto_tag_document_multi_algorithm(
                out_root=out_root,
                doc_id=doc_id,
                title=title,
                text=text,
                language=language,
                top_k=top_k,
                topic_sentence=topic_sentence,
                min_support=min_algorithm_support,
                use_semantic_adjustment=use_semantic_adjustment
            )
            print(f"[태깅] 다중 알고리즘 파이프라인 완료")
            return result
        except Exception as e:
            # 다중 알고리즘 실패 시 기존 방식으로 fallback
            print(f"[태깅] ⚠️ 다중 알고리즘 파이프라인 실패, BM25 fallback 방식으로 진행")
            print(f"[태깅] 오류: {e}")
            import traceback
            traceback.print_exc()
    
    # BM25 방식 (fallback 또는 use_multi_algorithm=False)
    out_root_p = Path(out_root)
    doc_dir = out_root_p / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)

    lang = language or guess_language(text)
    
    # 주제문장이 있으면 텍스트에 포함하여 처리
    text_for_tagging = text or ""
    if topic_sentence and topic_sentence.strip():
        # 주제문장을 앞에 추가하여 우선순위 부여
        text_for_tagging = f"{topic_sentence.strip()}\n\n{text_for_tagging}"
    
    tokens = tokenize(text_for_tagging)
    unique_terms = set(tokens)

    state_path = out_root_p / "auto_tagging_state.json"
    state = TaggingState.load(state_path)

    # 장르 분류: 주제문장이 있으면 주제문장도 고려
    title_for_genre = title or ""
    if topic_sentence and topic_sentence.strip():
        title_for_genre = f"{title_for_genre} {topic_sentence.strip()}"
    genre_info = classify_genre(text=text_for_tagging or "", title=title_for_genre)

    # 주제 기반 태그 추출 (주제문장이 있으면 개선된 버전 사용)
    if topic_sentence and topic_sentence.strip():
        tags = compute_bm25_topk_with_topic_boost(
            tokens=tokens,
            state=state,
            lang=lang,
            k=top_k,
            genre=genre_info.get("genre"),
            topic_sentence=topic_sentence,
            original_text=text_for_tagging,
            topic_boost_factor=2.0  # 주제 관련성 부스트 계수
        )
    else:
        tags = compute_bm25_topk(
            tokens=tokens,
            state=state,
            lang=lang,
            k=top_k,
            genre=genre_info.get("genre"),
            topic_sentence=None
        )
    # 점수 기준으로 재정렬 (이미 정렬되어 있지만 확실히)
    tags.sort(key=lambda x: x["score"], reverse=True)

    # 상태 업데이트(문서 ingest 단위로 DF 누적)
    try:
        update_df_state(state, unique_terms, doc_length=len(tokens))
        state.save(state_path)
    except Exception as e:
        print(f"[태깅] 상태 저장 실패 (계속 진행): {e}")
        # 상태 저장 실패해도 태깅 결과는 저장

    result = {
        "doc_id": doc_id,
        "schema_version": 1,
        "generated_at": now_iso(),
        "language": lang,
        "topic_sentence": topic_sentence.strip() if topic_sentence else None,
        "genre": genre_info["genre"],
        "genre_confidence": genre_info["confidence"],
        "genre_evidence": genre_info.get("evidence", []),
        "tags_topk": tags,
    }

    (doc_dir / "auto_tags.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return result


def load_auto_tags(out_root: str, doc_id: str) -> Optional[dict]:
    p = Path(out_root) / doc_id / "auto_tags.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
