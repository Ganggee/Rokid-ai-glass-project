# Open-source evaluation — food segmentation / recognition

조사일 2026-11-04. 라이선스는 각 저장소 `LICENSE` 파일을 직접 받아 확인(얕은 clone). 모델 가중치·데이터셋 조건은 README 기재 기준이며 **법률 검토가 아님**.

| 후보 | 코드 라이선스 | 가중치/데이터 | 실행 요건 | 역할 | PoC 판단 |
|---|---|---|---|---|---|
| **OpenCV** (opencv-python-headless) | Apache-2.0 | 없음 | CPU, pip | QR/바코드 디코딩, SIFT/ORB/ECC 정렬, 색·텍스처 마스크, 면적 | **기본 채택 (Baseline 0/1)** |
| **facebookresearch/sam2** | Apache-2.0 (+ `LICENSE_cctorch` BSD-3) | 체크포인트 별도 다운로드(README: SAM 2.1 suite) | python≥3.10, torch≥2.5.1, torchvision≥0.20.1, CUDA 커널 빌드 권장 | 클래스 무관 마스크 — **음식 종류는 모름** | 선택 플러그인(`FOOD_MODEL_PLUGIN=sam2`, `SAM2_CHECKPOINT`). 이 세션에서 torch 미설치 → **NOT VERIFIED**, 자동 폴백 확인 |
| **jamesjg/FoodSAM** | Apache-2.0 | SAM + FoodSeg103 semantic 체크포인트 + 객체검출기 별도 | 별도 `installation.md`, 구형 mmcv/torch 스택 | 음식 클래스 + 마스크 | API 프로세스에 포함하지 않음. **별도 실험 환경(WSL2/GPU/Docker)** 권장 |
| **LARC-CMU-SMU/FoodSeg103-Benchmark-v1** | Apache-2.0 (MMSegmentation 기반) | 데이터셋 zip은 연구 다운로드(비밀번호 공개), 학습 모델은 SharePoint 링크 | mmseg/torch, 다중 GPU 학습 스크립트 | 104개 식재료 클래스 벤치마크 | 데이터셋/가중치의 **상업적 사용 조건 미명시 → 사내 사용 전 확인 필요** |
| **ultralytics/ultralytics** (YOLO) | **AGPL-3.0** (또는 Enterprise) | 사전학습 가중치 동일 조건 | pip | 검출/분할 | 회사 Private PoC에 **포함하지 않음**. AGPL 네트워크 조항 때문에 서버 배포 시 소스 공개 의무 가능 |
| 한국 음식 인식 모델/데이터 | 미조사(출처·라이선스 명확한 후보 미확보) | AI Hub 등은 이용 약관 확인 필요 | — | 한식 분류 | `docs/required-inputs.md`에 후속 과제로 기록. 출처 불명 모델은 사용하지 않음 |
| Tesseract OCR (+pytesseract) | Apache-2.0 | 언어 데이터(eng 등) | 서버에 바이너리 설치 | 제품 라벨 텍스트 → 후보 | 선택 기능(`OCR_ENABLED`), 이 세션에서 동작 확인 |

## 구조 결정
- 분할(어디에 음식이 있는가)과 분류(무슨 음식인가)를 분리: `backend/app/vision/interfaces.py`.
- 모델이 없거나 실패하면 `analysis_method`가 OpenCV baseline으로 바뀌고 `warnings`에 사유가 기록됨(테스트 `test_model_method_falls_back_with_warning`).
- 음식명은 현재 **사용자 라벨(HUD 선택/PC 입력)** 이 정본. 자동 분류는 후속 과제.
