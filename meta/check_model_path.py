#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""모델 경로 확인 스크립트"""

import os
from pathlib import Path

print("=" * 60)
print("모델 경로 확인")
print("=" * 60)

# Hugging Face 캐시 경로
cache_dir = Path.home() / '.cache' / 'huggingface' / 'hub'
print(f"\n1. Hugging Face 캐시 경로: {cache_dir}")
print(f"   존재 여부: {cache_dir.exists()}")

if cache_dir.exists():
    # ko-sbert 모델 찾기
    model_dirs = list(cache_dir.glob('models--jhgan--ko-sbert-multitask*'))
    print(f"\n2. ko-sbert 모델 디렉토리:")
    for model_dir in model_dirs:
        print(f"   {model_dir}")
        if model_dir.exists():
            # 모델 파일 확인
            model_files = list(model_dir.rglob('*.bin')) + list(model_dir.rglob('*.safetensors'))
            print(f"   모델 파일 수: {len(model_files)}")
            if model_files:
                print(f"   예시 파일: {model_files[0]}")

# sentence-transformers가 모델을 찾는 경로 확인
try:
    from sentence_transformers import SentenceTransformer
    import sentence_transformers
    
    print(f"\n3. sentence-transformers 모듈 경로:")
    print(f"   {sentence_transformers.__file__}")
    
    # 모델 로드 시도 (캐시 확인)
    print(f"\n4. 모델 로드 테스트:")
    print("   모델 로드 중...")
    model = SentenceTransformer('jhgan/ko-sbert-multitask')
    
    # 모델 경로 확인
    if hasattr(model, '_model_card_vars'):
        print(f"   모델 카드 변수: {model._model_card_vars}")
    
    # 모델의 실제 경로 확인
    if hasattr(model, '_modules'):
        for name, module in model._modules.items():
            if hasattr(module, 'auto_model'):
                if hasattr(module.auto_model, 'config'):
                    print(f"   모델 이름: {module.auto_model.config.name_or_path}")
    
    print("   [OK] 모델 로드 성공!")
    
except Exception as e:
    print(f"   [ERROR] 모델 로드 실패: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
