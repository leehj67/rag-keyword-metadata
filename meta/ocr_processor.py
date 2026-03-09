"""
OCR 처리 모듈 (EasyOCR 기반)
CPU 모드, 높은 정확도, 가벼운 사이즈 최적화
"""
from pathlib import Path
from typing import Optional, List, Dict
import json

# EasyOCR 선택적 import (설치되지 않은 경우 None)
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    easyocr = None
    EASYOCR_AVAILABLE = False


class OCRProcessor:
    """EasyOCR 기반 OCR 처리기 (CPU 최적화)"""
    
    def __init__(self, languages: List[str] = ['ko', 'en'], gpu: bool = False):
        """
        Args:
            languages: 인식할 언어 리스트 ['ko', 'en']
            gpu: GPU 사용 여부 (기본값: False, CPU 사용)
        """
        self.reader = None
        self.languages = languages
        self.gpu = gpu
        self._initialized = False
    
    def _ensure_initialized(self):
        """OCR Reader 초기화 (지연 로딩)"""
        if not EASYOCR_AVAILABLE:
            raise ImportError("EasyOCR이 설치되지 않았습니다. 'pip install easyocr'을 실행하세요.")
        if not self._initialized:
            # CPU 모드로 초기화 (gpu=False)
            self.reader = easyocr.Reader(self.languages, gpu=self.gpu)
            self._initialized = True
    
    def extract_text(self, image_path: str) -> Dict:
        """
        이미지에서 텍스트 추출
        
        Args:
            image_path: 이미지 파일 경로
            
        Returns:
            {
                "text": "전체 텍스트",
                "lines": [
                    {"text": "텍스트", "confidence": 0.95, "bbox": [x1, y1, x2, y2, x3, y3, x4, y4]},
                    ...
                ],
                "word_count": 10,
                "language": "ko",
                "success": True
            }
        """
        self._ensure_initialized()
        
        image_path = Path(image_path)
        if not image_path.exists():
            return {
                "error": f"이미지 파일이 없습니다: {image_path}",
                "success": False
            }
        
        try:
            results = self.reader.readtext(str(image_path))
            
            if not results:
                return {
                    "text": "",
                    "lines": [],
                    "word_count": 0,
                    "language": "unknown",
                    "success": True,
                    "empty": True
                }
            
            # 전체 텍스트 결합
            full_text = "\n".join([item[1] for item in results])
            
            # 라인별 정보
            lines = []
            total_confidence = 0.0
            for item in results:
                bbox, text, confidence = item
                # bbox를 평탄화: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]] -> [x1, y1, x2, y2, x3, y3, x4, y4]
                flat_bbox = [int(coord) for point in bbox for coord in point]
                lines.append({
                    "text": text,
                    "confidence": float(confidence),
                    "bbox": flat_bbox
                })
                total_confidence += float(confidence)
            
            avg_confidence = total_confidence / len(lines) if lines else 0.0
            
            return {
                "text": full_text,
                "lines": lines,
                "word_count": len(full_text.split()),
                "language": self._detect_language(full_text),
                "confidence": avg_confidence,
                "line_count": len(lines),
                "success": True
            }
        except Exception as e:
            return {
                "error": str(e),
                "success": False
            }
    
    def extract_text_simple(self, image_path: str) -> str:
        """
        간단한 텍스트만 추출 (전체 텍스트만)
        
        Args:
            image_path: 이미지 파일 경로
            
        Returns:
            추출된 텍스트 (실패 시 빈 문자열)
        """
        result = self.extract_text(image_path)
        return result.get("text", "") if result.get("success") else ""
    
    def _detect_language(self, text: str) -> str:
        """텍스트 언어 감지 (간단한 휴리스틱)"""
        if not text:
            return "unknown"
        
        # 한글 포함 여부
        if any('\uAC00' <= char <= '\uD7A3' for char in text):
            return "ko"
        
        # 영문 포함 여부
        if any(char.isalpha() and ord(char) < 128 for char in text):
            return "en"
        
        return "unknown"


# 전역 인스턴스 (지연 초기화)
_ocr_processor: Optional[OCRProcessor] = None

def get_ocr_processor(languages: List[str] = ['ko', 'en'], gpu: bool = False) -> OCRProcessor:
    """
    OCR Processor 싱글톤
    
    Args:
        languages: 인식할 언어 리스트
        gpu: GPU 사용 여부 (기본값: False)
        
    Returns:
        OCRProcessor 인스턴스
    """
    global _ocr_processor
    if _ocr_processor is None:
        _ocr_processor = OCRProcessor(languages=languages, gpu=gpu)
    return _ocr_processor
