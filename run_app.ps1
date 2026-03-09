# AI Orchestrator 앱 실행 스크립트
# PowerShell에서 실행: .\run_app.ps1

# 가상환경 활성화
if (Test-Path ".venv\Scripts\Activate.ps1") {
    Write-Host "가상환경 활성화 중..." -ForegroundColor Cyan
    & .\.venv\Scripts\Activate.ps1
} else {
    Write-Host "⚠️ 가상환경이 없습니다. 먼저 .\setup_env.ps1를 실행하세요." -ForegroundColor Yellow
    exit 1
}

# 앱 실행
Write-Host "앱 실행 중..." -ForegroundColor Cyan
python meta\app.py
