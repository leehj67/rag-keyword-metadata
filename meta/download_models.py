#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
의미 기반 신뢰도 보정 모델 사전 다운로드 스크립트

이 스크립트를 실행하면 필요한 모델들을 미리 다운로드하여 캐시에 저장합니다.
앱 실행 시 모델이 이미 있으면 즉시 사용할 수 있습니다.
"""

import sys
import os

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
        print("[1/2] ✓ 한국어 SBERT 모델 다운로드 완료!")
        
        # 간단한 테스트
        print("\n[2/2] 모델 테스트 중...")
        test_text = "카프카 클러스터 설정"
        embedding = model.encode(test_text)
        print(f"[2/2] ✓ 모델 테스트 성공 (임베딩 차원: {len(embedding)})")
        
        return True
    except ImportError:
        print("\n❌ sentence-transformers가 설치되지 않았습니다.")
        print("설치 방법: pip install sentence-transformers")
        return False
    except Exception as e:
        print(f"\n❌ 모델 다운로드 실패: {e}")
        return False


def download_sentence_bart():
    """영어 Sentence-BART 모델 다운로드 (선택적)"""
    print("\n" + "=" * 60)
    print("영어 Sentence-BART 모델 다운로드 시작")
    print("모델: facebook/bart-large")
    print("크기: 약 1.6GB (큼)")
    print("=" * 60)
    
    try:
        from transformers import pipeline
        print("\n[1/2] 모델 다운로드 중... (시간이 오래 걸릴 수 있습니다)")
        model = pipeline('feature-extraction', model='facebook/bart-large')
        print("[1/2] ✓ 영어 Sentence-BART 모델 다운로드 완료!")
        
        # 간단한 테스트
        print("\n[2/2] 모델 테스트 중...")
        test_text = "Kafka cluster configuration"
        features = model(test_text)
        print(f"[2/2] ✓ 모델 테스트 성공")
        
        return True
    except ImportError:
        print("\n❌ transformers가 설치되지 않았습니다.")
        print("설치 방법: pip install transformers")
        return False
    except Exception as e:
        print(f"\n❌ 모델 다운로드 실패: {e}")
        return False


def main():
    """메인 함수"""
    print("\n" + "=" * 60)
    print("의미 기반 신뢰도 보정 모델 사전 다운로드")
    print("=" * 60)
    print("\n이 스크립트는 다음 모델들을 다운로드합니다:")
    print("1. 한국어 SBERT (ko-sbert) - 필수")
    print("2. 영어 Sentence-BART - 선택적 (영어 문서 처리 시 필요)")
    print("\n모델은 Hugging Face 캐시에 저장되며,")
    print("앱 실행 시 자동으로 사용됩니다.")
    print("=" * 60)
    
    # 명령줄 인자 확인
    import sys
    choice = None
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ['1', 'ko', 'korean']:
            choice = "1"
        elif arg in ['2', 'all', 'both']:
            choice = "2"
        elif arg in ['3', 'cancel', 'skip']:
            choice = "3"
    
    # 사용자 확인 (인자가 없으면)
    if choice is None:
        print("\n다운로드할 모델을 선택하세요:")
        print("1. 한국어 SBERT만 다운로드 (권장)")
        print("2. 한국어 SBERT + 영어 Sentence-BART 모두 다운로드")
        print("3. 취소")
        
        try:
            choice = input("\n선택 (1-3): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n다운로드를 취소했습니다.")
            sys.exit(0)
    
    if choice == "1":
        success = download_ko_sbert()
        if success:
            print("\n" + "=" * 60)
            print("✓ 한국어 SBERT 모델 다운로드 완료!")
            print("이제 앱을 실행하면 모델이 즉시 사용됩니다.")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("❌ 모델 다운로드 실패")
            print("=" * 60)
            sys.exit(1)
            
    elif choice == "2":
        success_ko = download_ko_sbert()
        if not success_ko:
            print("\n한국어 모델 다운로드 실패로 영어 모델 다운로드를 건너뜁니다.")
            sys.exit(1)
        
        print("\n영어 모델도 다운로드하시겠습니까? (y/n): ", end="")
        confirm = input().strip().lower()
        if confirm == 'y':
            success_en = download_sentence_bart()
            if success_en:
                print("\n" + "=" * 60)
                print("✓ 모든 모델 다운로드 완료!")
                print("이제 앱을 실행하면 모델이 즉시 사용됩니다.")
                print("=" * 60)
            else:
                print("\n영어 모델 다운로드 실패 (한국어 모델은 정상 작동)")
        else:
            print("\n영어 모델 다운로드를 건너뜁니다.")
            
    elif choice == "3":
        print("\n다운로드를 취소했습니다.")
        sys.exit(0)
    else:
        print("\n잘못된 선택입니다.")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n다운로드가 중단되었습니다.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
