# AI Orchestrator 환경 설정 가이드

## 빠른 시작

### 1. 환경 설정 (최초 1회)

PowerShell에서 실행:

```powershell
.\setup_env.ps1
```

이 스크립트는 다음을 수행합니다:
- 가상환경(`.venv`) 생성 (없는 경우)
- 가상환경 활성화
- pip 업그레이드
- 필수 패키지 설치 (`meta/requirements.txt` 또는 기본 패키지)

### 2. 앱 실행

#### 방법 1: 실행 스크립트 사용 (권장)

```powershell
.\run_app.ps1
```

#### 방법 2: 수동 실행

```powershell
# 가상환경 활성화
.\.venv\Scripts\Activate.ps1

# 앱 실행
python meta\app.py
```

## 필수 패키지

### 기본 라이브러리
- `Pillow` - 이미지 처리
- `python-docx` - DOCX 파일 처리
- `python-pptx` - PPTX 파일 처리
- `pypdf` - PDF 파일 처리
- `openpyxl` - XLSX 파일 처리
- `lxml` - XML 처리
- `matplotlib` - 그래프 시각화
- `numpy` - 수치 계산

### 선택적 라이브러리 (태깅)
- `multi-rake` - RAKE 키워드 추출
- `yake` - YAKE 키워드 추출
- `kiwipiepy` - 한국어 형태소 분석

### 선택적 라이브러리 (고급 기능)
- `sentence-transformers` - 의미 기반 보정
- `transformers` - LLM 모델
- `easyocr` - OCR 처리
- `pdf2image` - PDF to Image 변환 (Poppler 필요)

## 문제 해결

### PIL 모듈을 찾을 수 없음

가상환경이 활성화되지 않았을 수 있습니다:

```powershell
# 가상환경 활성화 확인
$env:VIRTUAL_ENV

# 가상환경 활성화
.\.venv\Scripts\Activate.ps1

# PIL 재설치
pip install Pillow
```

### 가상환경 재생성

문제가 계속되면 가상환경을 재생성:

```powershell
# 기존 가상환경 삭제
Remove-Item -Recurse -Force .venv

# 환경 재설정
.\setup_env.ps1
```

### Poppler 설치 필요 (PDF 처리)

PDF to Image 변환이 필요하면 Poppler 설치 필요:
- Windows: [Poppler 설치 가이드](meta/POPPLER_INSTALL_GUIDE.md)
- `C:\poppler` 경로에 설치 권장

## 시스템 요구사항

- Python 3.12+
- Windows 10/11 (권장)
- 가상환경 지원 (venv)

## 참고

- 가상환경 활성화 후 프롬프트에 `(.venv)`가 표시됩니다
- 매번 앱 실행 전에 가상환경을 활성화해야 합니다
- `setup_env.ps1`는 한 번만 실행하면 됩니다
