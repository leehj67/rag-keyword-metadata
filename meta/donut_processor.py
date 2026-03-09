"""
Donut 기반 OCR-free 문서 인식 모듈
PDF 이미지를 직접 처리하여 텍스트 추출
"""
from pathlib import Path
from typing import Optional, Dict, List
import warnings

# PyTorch pin_memory 경고 필터링
warnings.filterwarnings('ignore', message='.*pin_memory.*', category=UserWarning)

# transformers 선택적 import
try:
    from transformers import DonutProcessor, VisionEncoderDecoderModel
    import torch
    from PIL import Image
    TRANSFORMERS_AVAILABLE = True
    DONUT_AVAILABLE = True
    _DonutProcessor = DonutProcessor  # 원본 클래스 저장
    _VisionEncoderDecoderModel = VisionEncoderDecoderModel
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    DONUT_AVAILABLE = False
    _DonutProcessor = None
    _VisionEncoderDecoderModel = None
    torch = None

# pdf2image 선택적 import (PDF → 이미지 변환)
try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    convert_from_path = None


class DonutDocumentProcessor:
    """Donut 기반 OCR-free 문서 인식 처리기"""
    
    def __init__(self, model_name: str = "naver-clova-ix/donut-base-finetuned-cord-v2"):
        """
        Args:
            model_name: Hugging Face 모델 이름
                        - "naver-clova-ix/donut-base-finetuned-cord-v2": 문서 인식용
                        - "naver-clova-ix/donut-base": 기본 모델
        """
        self.model_name = model_name
        self.processor = None
        self.model = None
        self._initialized = False
        if torch is not None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = "cpu"
    
    def _ensure_initialized(self):
        """Donut 모델 초기화 (지연 로딩)"""
        if not DONUT_AVAILABLE:
            raise ImportError(
                "Donut 모델을 사용하려면 transformers와 torch가 필요합니다.\n"
                "pip install transformers torch pillow"
            )
        
        if not self._initialized:
            try:
                print(f"[Donut] 모델 로딩 시작: {self.model_name}")
                print(f"[Donut] 디바이스: {self.device}")
                
                self.processor = _DonutProcessor.from_pretrained(self.model_name)
                self.model = _VisionEncoderDecoderModel.from_pretrained(self.model_name)
                self.model.to(self.device)
                self.model.eval()
                
                self._initialized = True
                print(f"[Donut] 모델 로딩 완료")
            except Exception as e:
                print(f"[Donut] 모델 로딩 실패: {e}")
                raise
    
    def extract_text_from_image(self, image_path: str, task: str = "text") -> Dict:
        """
        이미지에서 텍스트 추출
        
        Args:
            image_path: 이미지 파일 경로
            task: 작업 유형 ("text", "document_classification" 등)
        
        Returns:
            {
                "text": "추출된 텍스트",
                "success": True,
                "model": "donut",
                "device": "cpu/cuda"
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
            # 이미지 로드
            image = Image.open(image_path).convert("RGB")
            
            # 전처리
            pixel_values = self.processor(image, return_tensors="pt").pixel_values
            pixel_values = pixel_values.to(self.device)
            
            # 추론
            with torch.no_grad():
                decoder_input_ids = self.processor.tokenizer(
                    f"<s_{task}>",
                    add_special_tokens=False,
                    return_tensors="pt"
                ).input_ids
                decoder_input_ids = decoder_input_ids.to(self.device)
                
                outputs = self.model.generate(
                    pixel_values,
                    decoder_input_ids=decoder_input_ids,
                    max_length=self.model.decoder.config.max_position_embeddings,
                    early_stopping=True,
                    pad_token_id=self.processor.tokenizer.pad_token_id,
                    eos_token_id=self.processor.tokenizer.eos_token_id,
                    use_cache=True,
                    num_beams=1,
                    bad_words_ids=[[self.processor.tokenizer.unk_token_id]],
                    return_dict_in_generate=True,
                )
            
            # 후처리
            sequence = self.processor.batch_decode(outputs.sequences)[0]
            sequence = sequence.replace(self.processor.tokenizer.eos_token, "").replace(
                self.processor.tokenizer.pad_token, ""
            )
            sequence = sequence.replace(f"<s_{task}>", "").replace("</s>", "").strip()
            
            return {
                "text": sequence,
                "success": True,
                "model": "donut",
                "device": self.device,
                "task": task
            }
        except Exception as e:
            return {
                "error": str(e),
                "success": False,
                "model": "donut"
            }
    
    def extract_text_from_pdf(self, pdf_path: str, max_pages: int = 5) -> Dict:
        """
        PDF에서 텍스트 추출 (이미지 변환 후 Donut 적용)
        
        Args:
            pdf_path: PDF 파일 경로
            max_pages: 최대 처리할 페이지 수 (메모리 절약)
        
        Returns:
            {
                "text": "추출된 텍스트",
                "pages_processed": 3,
                "success": True,
                "model": "donut"
            }
        """
        if not PDF2IMAGE_AVAILABLE:
            return {
                "error": "PDF를 이미지로 변환하려면 pdf2image가 필요합니다.\npip install pdf2image",
                "success": False
            }
        
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            return {
                "error": f"PDF 파일이 없습니다: {pdf_path}",
                "success": False
            }
        
        try:
            print(f"[Donut] PDF 이미지 변환 시작: {pdf_path.name}")
            
            # Poppler 경로 자동 찾기
            poppler_path = None
            try:
                import subprocess
                
                # 1. PATH에서 찾기
                try:
                    result = subprocess.run(['where', 'pdftoppm'], 
                                          capture_output=True, 
                                          text=True, 
                                          timeout=2)
                    if result.returncode == 0:
                        poppler_exe = result.stdout.strip().split('\n')[0]
                        poppler_path = str(Path(poppler_exe).parent)
                except:
                    pass
                
                # 2. 일반적인 위치에서 찾기
                if not poppler_path:
                    common_paths = [
                        Path("C:/poppler/bin"),
                        Path("C:/poppler/Library/bin"),  # 일부 버전은 Library/bin에 있음
                        Path.home() / "poppler" / "bin",
                        Path.home() / "poppler-23.11.0" / "bin",
                        Path("C:/Program Files/poppler/bin"),
                    ]
                    for path in common_paths:
                        if path.exists() and (path / "pdftoppm.exe").exists():
                            poppler_path = str(path)
                            print(f"[Donut] Poppler 경로 발견: {poppler_path}")
                            break
                    
                    # 3. C:\poppler 안에서 재귀적으로 찾기
                    if not poppler_path:
                        poppler_root = Path("C:/poppler")
                        if poppler_root.exists():
                            for exe_file in poppler_root.rglob("pdftoppm.exe"):
                                poppler_path = str(exe_file.parent)
                                print(f"[Donut] Poppler 경로 발견 (재귀 검색): {poppler_path}")
                                break
            except:
                pass
            
            # PDF를 이미지로 변환
            if poppler_path:
                images = convert_from_path(
                    str(pdf_path),
                    dpi=200,
                    first_page=1,
                    last_page=max_pages,
                    poppler_path=poppler_path
                )
            else:
                # poppler_path 없이 시도 (PATH에 있으면 작동)
                images = convert_from_path(
                    str(pdf_path),
                    dpi=200,
                    first_page=1,
                    last_page=max_pages
                )
            
            print(f"[Donut] 변환된 이미지 수: {len(images)}개")
            
            # 각 페이지에서 텍스트 추출
            all_texts = []
            for idx, image in enumerate(images, start=1):
                print(f"[Donut] 페이지 {idx}/{len(images)} 처리 중...")
                
                # 임시 이미지 파일로 저장
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                    tmp_path = tmp_file.name
                    image.save(tmp_path, "PNG")
                
                try:
                    result = self.extract_text_from_image(tmp_path)
                    if result.get("success"):
                        page_text = result.get("text", "")
                        if page_text.strip():
                            all_texts.append(f"=== 페이지 {idx} ===\n{page_text}")
                finally:
                    # 임시 파일 삭제
                    Path(tmp_path).unlink(missing_ok=True)
            
            combined_text = "\n\n".join(all_texts)
            
            return {
                "text": combined_text,
                "pages_processed": len(images),
                "success": True,
                "model": "donut",
                "device": self.device
            }
        except Exception as e:
            import traceback
            print(f"[Donut] PDF 처리 실패: {e}")
            traceback.print_exc()
            return {
                "error": str(e),
                "success": False,
                "model": "donut"
            }


# 전역 Donut 프로세서 인스턴스 (지연 초기화)
_donut_processor: Optional[DonutDocumentProcessor] = None


def get_donut_processor(model_name: str = "naver-clova-ix/donut-base-finetuned-cord-v2") -> Optional[DonutDocumentProcessor]:
    """
    Donut 프로세서 인스턴스 가져오기 (싱글톤 패턴)
    
    Args:
        model_name: Hugging Face 모델 이름
    
    Returns:
        DonutDocumentProcessor 인스턴스 또는 None (사용 불가능한 경우)
    """
    global _donut_processor
    
    if not DONUT_AVAILABLE:
        return None
    
    if _donut_processor is None:
        try:
            _donut_processor = DonutDocumentProcessor(model_name)
        except Exception as e:
            print(f"[Donut] 프로세서 초기화 실패: {e}")
            return None
    
    return _donut_processor


def extract_text_with_donut(pdf_path: str, max_pages: int = 5) -> Dict:
    """
    Donut을 사용하여 PDF에서 텍스트 추출 (편의 함수)
    
    Args:
        pdf_path: PDF 파일 경로
        max_pages: 최대 처리할 페이지 수
    
    Returns:
        추출 결과 딕셔너리
    """
    processor = get_donut_processor()
    if processor is None:
        return {
            "error": "Donut 모델을 사용할 수 없습니다.",
            "success": False
        }
    
    return processor.extract_text_from_pdf(pdf_path, max_pages=max_pages)
