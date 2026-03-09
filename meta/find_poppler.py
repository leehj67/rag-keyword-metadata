"""
Poppler 경로 찾기 스크립트
"""
from pathlib import Path
import subprocess

def find_poppler():
    """Poppler 경로 찾기"""
    print("=" * 60)
    print("Poppler 경로 검색 중...")
    print("=" * 60)
    print()
    
    # 1. PATH에서 찾기
    print("[1] PATH 환경 변수에서 검색...")
    try:
        result = subprocess.run(['where', 'pdftoppm'], 
                              capture_output=True, 
                              text=True, 
                              timeout=2)
        if result.returncode == 0:
            poppler_exe = result.stdout.strip().split('\n')[0]
            poppler_path = Path(poppler_exe).parent
            print(f"  [OK] 발견: {poppler_path}")
            print(f"  파일: {poppler_exe}")
            return str(poppler_path)
        else:
            print("  [없음] PATH에 없습니다.")
    except Exception as e:
        print(f"  [오류] {e}")
    
    print()
    
    # 2. 일반적인 위치에서 찾기
    print("[2] 일반적인 설치 위치 검색...")
    common_paths = [
        Path("C:/poppler/bin"),
        Path("C:/poppler/Library/bin"),
        Path.home() / "poppler" / "bin",
        Path("C:/Program Files/poppler/bin"),
    ]
    
    for path in common_paths:
        print(f"  확인 중: {path}")
        if path.exists():
            print(f"    폴더 존재: 예")
            exe_file = path / "pdftoppm.exe"
            if exe_file.exists():
                print(f"    pdftoppm.exe 존재: 예")
                print(f"  [OK] 발견: {path}")
                return str(path)
            else:
                print(f"    pdftoppm.exe 존재: 아니오")
        else:
            print(f"    폴더 존재: 아니오")
    
    print()
    
    # 3. C:\poppler 안에서 재귀적으로 찾기
    print("[3] C:\\poppler 안에서 재귀 검색...")
    poppler_root = Path("C:/poppler")
    if poppler_root.exists():
        print(f"  C:\\poppler 폴더 존재: 예")
        print(f"  내용물:")
        try:
            items = list(poppler_root.iterdir())
            for item in items[:10]:  # 처음 10개만 표시
                print(f"    - {item.name} ({'폴더' if item.is_dir() else '파일'})")
            if len(items) > 10:
                print(f"    ... 외 {len(items) - 10}개")
        except Exception as e:
            print(f"    읽기 오류: {e}")
        
        print(f"  pdftoppm.exe 검색 중...")
        try:
            for exe_file in poppler_root.rglob("pdftoppm.exe"):
                poppler_path = exe_file.parent
                print(f"  [OK] 발견: {poppler_path}")
                print(f"  전체 경로: {exe_file}")
                return str(poppler_path)
        except Exception as e:
            print(f"  검색 오류: {e}")
    else:
        print(f"  C:\\poppler 폴더 존재: 아니오")
    
    print()
    print("=" * 60)
    print("[결과] Poppler를 찾을 수 없습니다.")
    print("=" * 60)
    print()
    print("설치 확인:")
    print("1. C:\\poppler 폴더가 존재하는지 확인")
    print("2. 압축 해제가 완료되었는지 확인")
    print("3. bin 폴더 안에 pdftoppm.exe가 있는지 확인")
    print()
    print("올바른 구조:")
    print("  C:\\poppler\\")
    print("    bin\\")
    print("      pdftoppm.exe")
    print("      pdfinfo.exe")
    print("      ...")
    
    return None

if __name__ == "__main__":
    result = find_poppler()
    if result:
        print()
        print("=" * 60)
        print(f"사용할 경로: {result}")
        print("=" * 60)
