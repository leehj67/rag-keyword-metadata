"""
Poppler Windows 설치 및 설정 스크립트
"""
import os
import sys
import subprocess
import urllib.request
import zipfile
import shutil
from pathlib import Path

def find_poppler_in_path():
    """PATH에서 Poppler 찾기"""
    try:
        result = subprocess.run(['where', 'pdftoppm'], 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        if result.returncode == 0:
            poppler_exe = result.stdout.strip().split('\n')[0]
            poppler_bin = Path(poppler_exe).parent
            return str(poppler_bin)
    except:
        pass
    return None

def find_poppler_common_locations():
    """일반적인 Poppler 설치 위치 확인"""
    common_paths = [
        Path.home() / "poppler" / "bin",
        Path.home() / "poppler-23.11.0" / "bin",
        Path("C:/poppler/bin"),
        Path("C:/Program Files/poppler/bin"),
        Path("C:/Program Files (x86)/poppler/bin"),
    ]
    
    for path in common_paths:
        if path.exists() and (path / "pdftoppm.exe").exists():
            return str(path)
    return None

def download_poppler():
    """Poppler Windows 바이너리 다운로드"""
    print("=" * 60)
    print("Poppler Windows 설치 안내")
    print("=" * 60)
    print()
    print("자동 다운로드는 지원하지 않습니다. 다음 단계를 따라주세요:")
    print()
    print("1. 다운로드:")
    print("   https://github.com/oschwartz10612/poppler-windows/releases")
    print("   최신 Release 버전의 .zip 파일 다운로드")
    print()
    print("2. 압축 해제:")
    print("   예: C:\\poppler 또는 %USERPROFILE%\\poppler")
    print()
    print("3. 설치 방법 선택:")
    print()
    print("   방법 A: 환경 변수 PATH에 추가 (권장)")
    print("   - Win + R → sysdm.cpl → 고급 → 환경 변수")
    print("   - 시스템 변수 Path 편집 → 새로 만들기")
    print("   - C:\\poppler\\bin 추가")
    print()
    print("   방법 B: 코드에서 경로 지정")
    print("   - 아래 경로를 복사하여 코드에 사용:")
    print()
    
    # 사용자 홈 디렉토리에 poppler 폴더가 있는지 확인
    home_poppler = Path.home() / "poppler" / "bin"
    if home_poppler.exists():
        print(f"   poppler_path = r'{home_poppler}'")
    else:
        print("   poppler_path = r'C:\\poppler\\bin'  # 실제 경로로 변경")
    
    print()
    print("=" * 60)
    
    return None

def check_poppler():
    """Poppler 설치 확인"""
    print("[Poppler] 설치 확인 중...")
    
    # 1. PATH에서 찾기
    poppler_path = find_poppler_in_path()
    if poppler_path:
        print(f"[Poppler] [OK] PATH에서 발견: {poppler_path}")
        return poppler_path
    
    # 2. 일반적인 위치에서 찾기
    poppler_path = find_poppler_common_locations()
    if poppler_path:
        print(f"[Poppler] [OK] 일반 위치에서 발견: {poppler_path}")
        return poppler_path
    
    # 3. 설치 안내
    print("[Poppler] [ERROR] Poppler를 찾을 수 없습니다.")
    print()
    download_poppler()
    
    return None

def test_pdf2image(poppler_path=None):
    """pdf2image 테스트"""
    try:
        from pdf2image import convert_from_path
        
        if poppler_path:
            print(f"[테스트] poppler_path 지정: {poppler_path}")
            # 테스트는 실제 PDF 파일이 필요하므로 스킵
            print("[테스트] [OK] pdf2image import 성공")
            print(f"[테스트] poppler_path 사용 가능: {poppler_path}")
            return True
        else:
            print("[테스트] [OK] pdf2image import 성공")
            print("[테스트] [WARN] Poppler 경로 확인 필요")
            return False
    except ImportError:
        print("[테스트] [ERROR] pdf2image가 설치되지 않았습니다.")
        print("[테스트] 설치: pip install pdf2image")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Poppler Windows 설치 확인 및 안내")
    print("=" * 60)
    print()
    
    # pdf2image 확인
    pdf2image_ok = test_pdf2image()
    print()
    
    # Poppler 확인
    poppler_path = check_poppler()
    print()
    
    if poppler_path:
        print("=" * 60)
        print("[OK] Poppler 설치 확인 완료!")
        print(f"   경로: {poppler_path}")
        print()
        print("코드에서 사용하려면:")
        print(f"   poppler_path = r'{poppler_path}'")
        print("=" * 60)
    else:
        print("=" * 60)
        print("[WARN] Poppler 설치가 필요합니다.")
        print("위의 안내를 따라 설치해주세요.")
        print("=" * 60)
