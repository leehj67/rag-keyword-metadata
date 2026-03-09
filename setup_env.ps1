# AI Orchestrator 환경 설정 스크립트
# PowerShell에서 실행: .\setup_env.ps1

Write-Host "=== AI Orchestrator 환경 설정 ===" -ForegroundColor Cyan

# 1. 가상환경 확인 및 생성
if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Host "가상환경이 없습니다. 생성 중..." -ForegroundColor Yellow
    python -m venv .venv
    Write-Host "✅ 가상환경 생성 완료" -ForegroundColor Green
} else {
    Write-Host "✅ 가상환경 이미 존재" -ForegroundColor Green
}

# 2. 가상환경 활성화
Write-Host "가상환경 활성화 중..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

# 3. pip 업그레이드
Write-Host "pip 업그레이드 중..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet

# 4. requirements.txt 확인
if (Test-Path "meta\requirements.txt") {
    Write-Host "필수 패키지 설치 중..." -ForegroundColor Yellow
    python -m pip install -r meta\requirements.txt
    Write-Host "✅ 패키지 설치 완료" -ForegroundColor Green
} else {
    Write-Host "⚠️ requirements.txt를 찾을 수 없습니다. 기본 패키지 설치 중..." -ForegroundColor Yellow
    python -m pip install Pillow python-docx python-pptx pypdf openpyxl lxml matplotlib numpy multi-rake yake kiwipiepy
    Write-Host "✅ 기본 패키지 설치 완료" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== 환경 설정 완료 ===" -ForegroundColor Cyan
Write-Host "이제 다음 명령으로 앱을 실행할 수 있습니다:" -ForegroundColor White
Write-Host "  python meta\app.py" -ForegroundColor Yellow
Write-Host ""
