#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAKE 설정 확인 스크립트
RAKE가 정상 동작하기 위한 필수 패키지 및 설정을 확인합니다.
"""

import sys

def check_imports():
    """필수 패키지 import 확인"""
    print("=" * 60)
    print("RAKE 설정 확인 시작")
    print("=" * 60)
    
    # 1. rake-nltk 확인
    print("\n1. rake-nltk 패키지 확인...")
    try:
        import rake_nltk
        print("   ✓ rake-nltk 설치됨")
        print(f"   버전: {getattr(rake_nltk, '__version__', 'unknown')}")
    except ImportError as e:
        print(f"   ✗ rake-nltk 설치되지 않음: {e}")
        print("   해결: pip install rake-nltk")
        return False
    
    # 2. nltk 확인
    print("\n2. nltk 패키지 확인...")
    try:
        import nltk
        print("   [OK] nltk 설치됨")
        print(f"   버전: {nltk.__version__}")
    except ImportError as e:
        print(f"   [ERROR] nltk 설치되지 않음: {e}")
        print("   해결: pip install nltk")
        return False
    
    # 3. NLTK 리소스 확인
    print("\n3. NLTK 리소스 확인...")
    resources_needed = [
        'corpora/stopwords',
        'tokenizers/punkt',
        'tokenizers/punkt_tab'
    ]
    
    all_ok = True
    for resource in resources_needed:
        try:
            nltk.data.find(resource)
            print(f"   [OK] {resource} 존재함")
        except LookupError:
            print(f"   [ERROR] {resource} 없음")
            all_ok = False
    
    if not all_ok:
        print("\n   리소스 다운로드 시도...")
        try:
            for resource in resources_needed:
                try:
                    nltk.data.find(resource)
                except LookupError:
                    resource_name = resource.split('/')[-1]
                    print(f"   다운로드 중: {resource_name}...")
                    nltk.download(resource_name, quiet=True)
                    print(f"   [OK] {resource_name} 다운로드 완료")
        except Exception as e:
            print(f"   [ERROR] 리소스 다운로드 실패: {e}")
            print("   해결: Python 인터프리터에서 수동으로 다운로드")
            print("   >>> import nltk")
            print("   >>> nltk.download('stopwords')")
            print("   >>> nltk.download('punkt')")
            print("   >>> nltk.download('punkt_tab')")
            return False
    
    # 4. RAKE 초기화 테스트
    print("\n4. RAKE 초기화 테스트...")
    try:
        r = rake_nltk.Rake(max_length=3)
        print("   [OK] RAKE 객체 생성 성공")
    except Exception as e:
        print(f"   [ERROR] RAKE 객체 생성 실패: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 5. RAKE 기본 기능 테스트
    print("\n5. RAKE 기본 기능 테스트...")
    try:
        test_text = "This is a test document for keyword extraction using RAKE algorithm."
        r = rake_nltk.Rake(max_length=3)
        r.extract_keywords_from_text(test_text)
        keywords = r.get_ranked_phrases_with_scores()
        print(f"   [OK] RAKE 추출 성공: {len(keywords)}개 키워드 발견")
        if keywords:
            print(f"   예시: {keywords[0]}")
    except Exception as e:
        print(f"   [ERROR] RAKE 추출 실패: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 6. KoNLPy 확인 (선택사항)
    print("\n6. KoNLPy 확인 (한국어 형태소 분석, 선택사항)...")
    try:
        from konlpy.tag import Okt
        print("   [OK] konlpy 설치됨")
        
        # Okt 초기화 테스트
        try:
            tagger = Okt()
            print("   [OK] Okt 초기화 성공")
        except Exception as e:
            print(f"   [ERROR] Okt 초기화 실패: {e}")
            print("   참고: JPype1 및 Java가 필요할 수 있습니다")
    except ImportError:
        print("   [-] konlpy 설치되지 않음 (선택사항)")
        print("   한국어 문서의 경우 형태소 분석 없이 기본 토큰화 사용")
    
    print("\n" + "=" * 60)
    print("RAKE 설정 확인 완료")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = check_imports()
    sys.exit(0 if success else 1)
