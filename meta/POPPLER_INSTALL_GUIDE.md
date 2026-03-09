# Poppler Windows 설치 가이드

## 개요

PDF를 이미지로 변환하기 위해 `pdf2image` 라이브러리는 Poppler를 필요로 합니다.
Windows에서는 Poppler를 별도로 설치해야 합니다.

## 설치 방법

### 1단계: Poppler 다운로드

1. 다음 링크에서 최신 Release 버전을 다운로드하세요:
   - https://github.com/oschwartz10612/poppler-windows/releases
   - 예: `Release-23.11.0-0.zip`

### 2단계: 압축 해제

다운로드한 ZIP 파일을 압축 해제하세요:
- 권장 위치: `C:\poppler` 또는 `%USERPROFILE%\poppler`
- 압축 해제 후 `bin` 폴더가 있는지 확인하세요

### 3단계: 설치 방법 선택

#### 방법 A: 환경 변수 PATH에 추가 (권장)

1. `Win + R` 키를 눌러 실행 창 열기
2. `sysdm.cpl` 입력 후 Enter
3. **고급** 탭 선택 → **환경 변수** 버튼 클릭
4. **시스템 변수** 섹션에서 **Path** 선택 → **편집** 클릭
5. **새로 만들기** 클릭
6. Poppler의 `bin` 폴더 경로 입력:
   - 예: `C:\poppler\bin`
7. **확인** 클릭하여 모든 창 닫기
8. **새 터미널/프로그램 재시작** (환경 변수 적용)

#### 방법 B: 코드에서 경로 지정

코드가 자동으로 다음 위치에서 Poppler를 찾습니다:
- `%USERPROFILE%\poppler\bin`
- `%USERPROFILE%\poppler-23.11.0\bin`
- `C:\poppler\bin`
- `C:\Program Files\poppler\bin`

위 위치 중 하나에 설치하면 자동으로 인식됩니다.

## 설치 확인

다음 명령어로 설치를 확인할 수 있습니다:

```bash
python meta/install_poppler.py
```

또는 직접 확인:

```bash
where pdftoppm
```

`pdftoppm.exe`의 경로가 출력되면 설치가 완료된 것입니다.

## 문제 해결

### "Unable to get page count. Is poppler installed and in PATH?" 오류

1. Poppler가 설치되었는지 확인
2. 환경 변수 PATH에 `bin` 폴더가 추가되었는지 확인
3. 터미널/프로그램을 재시작했는지 확인

### 코드에서 경로를 찾지 못하는 경우

`app.py`와 `donut_processor.py`에서 자동으로 다음 위치를 확인합니다:
- PATH 환경 변수
- 일반적인 설치 위치

수동으로 경로를 지정하려면 코드를 수정하세요:

```python
from pdf2image import convert_from_path

images = convert_from_path(
    pdf_path,
    poppler_path=r'C:\poppler\bin'  # 실제 경로로 변경
)
```

## 참고

- Poppler는 PDF를 이미지로 변환하는 데 사용됩니다
- `pdf2image` 라이브러리는 내부적으로 Poppler를 호출합니다
- Windows에서는 Poppler를 별도로 설치해야 합니다
- Linux/Mac에서는 패키지 매니저로 설치 가능합니다
