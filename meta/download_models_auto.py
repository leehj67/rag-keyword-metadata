#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
의미 기반 신뢰도 보정 모델 자동 다운로드 스크립트

한국어 SBERT 모델만 자동으로 다운로드합니다.
"""

import sys

def download_ko_sbert():
    """한국어 SBERT 모델 다운로드"""
    print("=" * 60)
    print("한국어 SBERT 모델 다운로드 시작")
    print("모델: jhgan/ko-sbert-multitask")
    print("크기: 약 442MB")
    print("=" * 60)
    
    try:
        from sentence_transformers import SentenceTransformer
        print("\n[1/2] 모델 다운로드 중...")
        model = SentenceTransformer('jhgan/ko-sbert-multitask')
        print("[1/2] [OK] 한국어 SBERT 모델 다운로드 완료!")
        
        # 간단한 테스트
        print("\n[2/2] 모델 테스트 중...")
        test_text = "카프카 클러스터 설정"
        embedding = model.encode(test_text)
        print(f"[2/2] [OK] 모델 테스트 성공 (임베딩 차원: {len(embedding)})")
        
        return True
    except ImportError:
        print("\n[ERROR] sentence-transformers가 설치되지 않았습니다.")
        print("설치 방법: pip install sentence-transformers")
        return False
    except Exception as e:
        print(f"\n[ERROR] 모델 다운로드 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    try:
        success = download_ko_sbert()
        if success:
            print("\n" + "=" * 60)
            print("[SUCCESS] 한국어 SBERT 모델 다운로드 완료!")
            print("이제 앱을 실행하면 모델이 즉시 사용됩니다.")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("[FAILED] 모델 다운로드 실패")
            print("=" * 60)
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n다운로드가 중단되었습니다.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
