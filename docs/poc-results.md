# PoC results (2026-11-04, development sandbox)

## 실행 환경 점검 (§3-A)
| 도구 | 결과 |
|---|---|
| git | 2.43.0 |
| gh | 2.89.0 — **인증 실패** (토큰 무효, "No linked GitHub account") → 원격 저장소 생성/push 불가 |
| node / npm | v22.23.4 / 10.9.9 |
| python / pip | 3.13.18 / 26.2.1 |
| Docker | 29.9.2 (사용 안 함) |
| 패키지 레지스트리 | PyPI·npm **정책 차단(403)** → `aix-cli`, `npx skills add`, `npm create @yodaos-pkg/aiui-agent` 실행 불가. GitHub clone은 가능 |
| 테스트용 FastAPI | GitHub 태그 소스(fastapi 0.162.0, httpx 0.28.1, httpcore 1.0.9, annotated-doc)를 **샌드박스에서만** import 경로에 추가. 저장소에는 포함하지 않음 |
| 기타 | opencv 5.0.0, numpy 2.5.3, Pillow 12.3.0, openpyxl 3.1.5, Tesseract 5.3.4 |
| AIUI 공식 자료 | yodaos-project/AIUI, jsar-project/AIUI clone (`skills/aiui-dev`, `packages/create-aiui-agent/template`, `samples/scanner`, `bench/`) |

공식 scaffold는 `npm create` 대신 저장소의 `packages/create-aiui-agent/template`(v2.1.3)과 동일한 구조(AGENTS.md, app.js, app.json, pages/index/index.ink)로 만들었습니다.

## 기능별 결과
| 기능 | UNIT | API E2E | AIUI 로직 하네스 | AIUI SIM | RV101 | 판정 |
|---|---|---|---|---|---|---|
| 재고 조회(3개 DEMO 품목, 한글 별칭·코드 검색) | PASS | PASS | PASS | NOT VERIFIED | NOT VERIFIED | 가능 |
| 차감 20→19, 이력 1건 | PASS | PASS | PASS | NOT VERIFIED | NOT VERIFIED | 가능 |
| **페이지 재진입 후 19 유지 (보고된 버그)** | — | — | **PASS** (LOCAL·SERVER) | NOT VERIFIED | NOT VERIFIED | 가능(실기기 확인 필요) |
| 서버 재기동 후 19 유지 | — | **PASS** (실제 uvicorn 종료/재시작) | **PASS** | — | — | 가능 |
| 멱등키 2회 → 1회 차감, 동시 8요청 → 1회 | PASS | PASS | PASS | — | — | 가능 |
| 동시 25요청(재고 15) → 15 성공/10 거절, 음수 없음 | PASS | — | — | — | — | 가능 |
| 확인 전 쓰기 금지 / 취소 시 불변 | PASS | PASS | PASS | NOT VERIFIED | NOT VERIFIED | 가능 |
| 응답 유실 → 재진입 시 상태확인, 이중 차감 없음 | PASS | — | **PASS** | NOT VERIFIED | NOT VERIFIED | 가능 |
| 저장소 쓰기 실패 → 실패 표시 | — | — | PASS | — | — | 가능 |
| Excel/CSV import 미리보기·적용·재수입 보호 | PASS | PASS | — | — | — | 가능 |
| QR(서버 OpenCV) 정상/잘못된 값 | PASS | PASS | PASS (카메라 mock) | NOT VERIFIED | NOT VERIFIED | 조건부(실카메라 화질) |
| 온디바이스 BarcodeDetector | — | — | 미사용 경로(폴백 시험) | NOT VERIFIED | NOT VERIFIED | 미확인 |
| OCR 후보(Tesseract) | PASS (렌더링된 라벨) | PASS | — | — | NOT VERIFIED | 조건부 |
| 음성 명령 → 확인 화면 (파서) | PASS | PASS | PASS (SpeechRecognition mock) | NOT VERIFIED | NOT VERIFIED | 한국어 STT **미확인** |
| 식사 세션·사진 2장·결과 조회 | PASS | PASS | PASS | NOT VERIFIED | NOT VERIFIED | 가능 |
| Baseline 0 수동 영역 (10000→4000px, 200g → 120g) | PASS | PASS | — | — | — | 가능 |
| Baseline 1 자동(영역 내 마스크 + 정렬) | PASS (합성) | PASS (합성) | PASS | — | NOT VERIFIED | 조건부 |
| g/kcal은 제공량 있을 때만, 없으면 null | PASS | PASS | PASS | — | — | 가능 |
| 정렬 실패·사진 불일치 경고 | PASS | PASS | — | — | — | 가능 |
| 모델 플러그인(SAM2/FoodSAM) | 폴백 PASS | — | — | — | — | **설치 안 됨 (torch 없음)** |
| MFDS OpenAPI | — | 비활성 경로 PASS | — | — | — | **NOT VERIFIED** (키 없음, 접속 불가) |
| AIX 패키징 / 리소스 업데이트 | — | — | — | — | — | **NOT VERIFIED** (Studio 미접속, aix-cli 설치 불가) |
| HUD 레이아웃(겹침) | — | — | — | NOT VERIFIED | NOT VERIFIED | 미확인 |

## 실행 증거
- `python -m pytest -q` → **40 passed** (backend/tests: inventory 15, import 4, recognition 6, meal math 6, meal API 9).
- `node aiui-agent/tests/run-aiui-checks.mjs --with-server` → **18/18 passed**
  (공식 validator issues 0, LOCAL 4, SERVER 7, MEAL 4, 정적 3).
- `python scripts/smoke_test.py --base-url http://127.0.0.1:8765` → `RESULT PASS`
  (센서 20→19, 중복 전송 replayed, 식사: 밥 추정 57.7%(정답 60.2%) 115.5 g 173.2 kcal DEMO, 김치 49.0%(정답 50.2%) g/kcal null).
- `python scripts/eval_synthetic_meals.py --n 20` (**합성 이미지만**, 회전 ±4°, 이동 ±35px, 노출 0.92–1.10):
  정렬 20/20 성공; 섭취비율 절대오차 평균/최대 — 밥 0.047/0.131 (19/20 ≤0.10), 김치 0.013/0.017, 계란 0.000/0.000, 샐러드 0.007/0.010.
  흰 접시 위 흰 밥 + 노출 증가 조합에서 오차가 커짐(1건 0.131). 실제 음식 사진 성능을 의미하지 않음.

## 핵심 한계
1. 실기기·Simulator·AIX 단계는 이 세션에서 실행하지 못했습니다(접근 수단 없음).
2. 2D 면적 비율 ≠ 섭취 중량. 높이/부피, 국물, 겹침, 음식 이동, 시점 변화는 보정하지 않습니다.
3. 후보 영역 검출은 색/텍스처 기반이라 흰 음식(밥 등)을 놓치기 쉽습니다 → HUD 라벨링 또는 PC 관리자 화면 수동 박스.
4. 영양값은 DEMO_MOCK. MFDS 연동 코드는 필드명이 미확인입니다.
5. 한국어 글리프 렌더링, 한국어 STT, RV101 키 매핑은 미확인입니다.

## 다음 단계
1. Simulator에서 §2 체크리스트 → 실기기 D1–D15.
2. HTTPS 엔드포인트 확보 후 SERVER 모드 실기기 시험.
3. 실제 식사 사진(동의) 10–20세트로 Baseline 오차 측정, 필요 시 SAM 2 플러그인 실험.
4. 실제 Excel·QR 내용으로 매핑 확정.

# Iteration 2 results (2026-11-06, development sandbox)

역할 분담: 지도교수(계획·합격 기준) → 코더(구현) → 토의자(독립 검증) → 지도교수(최종 승인). 아래는 코더 단계의 실측입니다.

| 기능 | UNIT | API E2E | AIUI 로직 하네스 | AIUI SIM | RV101 | 판정 |
|---|---|---|---|---|---|---|
| 공개 영양 DB 165행(출처·검증 등급) + 검증기 | PASS | — | — | — | — | 가능 |
| 공식 파일/API 임포터, 빈 기준량 버그 수정 | PASS(픽스처) | — | — | — | — | 코드 완료, 공식 파일 실데이터 **NOT VERIFIED** |
| 음성 식사 기록: 파싱 → 확인 → 저장(멱등) | PASS(파서 32케이스) | PASS | PASS | NOT VERIFIED | NOT VERIFIED | 가능(한국어 STT 미확인) |
| 날짜로 조회 / 읽어 주기(TTS) | PASS | PASS | PASS(speak 1회, 미지원 폴백) | NOT VERIFIED | NOT VERIFIED | 화면 가능, 한국어 음성 **미확인** |
| 분석 결과 → 일지 기록(분석당 1건) | PASS | PASS | PASS | — | — | 가능 |
| 재고 ↔ Excel 내보내기/병합/잠금/충돌 | PASS(17) | PASS(API) | — | — | — | 가능(실제 OneDrive/Drive 클라이언트 **NOT VERIFIED**) |
| 장기 사용 soak | PASS | — | — | — | — | 아래 수치 |

실행 증거
- `python -m pytest -q` → **107 passed** (iteration 1의 40 포함).
- `node aiui-agent/tests/run-aiui-checks.mjs --with-server` → **23/23** (공식 validator issues 0).
- `python scripts/smoke_test.py` (실제 uvicorn) → `RESULT PASS`; diary `speech_text` 예: "11월 5일 저녁 기록입니다. 총 약 360킬로칼로리, 추정입니다. 김밥, 배추김치."
- `python scripts/validate_nutrition_csv.py …public.csv …demo.csv` → 165 rows 0 failing / 6 rows 0 failing.
- `python -I scripts/build_nutrition_reference.py --mirrors /tmp/nutri-mirrors` → curated 175, 없음 1, 미러 간 불일치로 제외 9, `mirror_cross_checked` 142, `single_mirror` 23, 기준량 100 mL(값 비움) 65 → **번들 165행(값 있음 100행)**. 상세: `sample-data/nutrition_reference_public.report.json`.
- `python scripts/soak_inventory_excel.py --seed 2026 --uses 2000 --edits 60 --restarts 6` → PASS, 34 s, 잠금 실패 주입 38회, 내보내기 593회, 외부 수정 반영 59건, 충돌 기록 53건. `--seed 7` → PASS(잠금 42, 반영 55, 충돌 43). 재기동은 프로세스 내 연결·상태 재생성이며 OS 프로세스 재시작은 `test_crash_after_commit_before_export_is_recovered`와 API 시작 시 동기화 테스트로 별도 확인.

한계
1. 영양값은 공식 사이트가 아니라 **공개 미러의 교차검증본**입니다. 공식 파일로 덮어쓰기 전까지 `verification`이 `mirror_cross_checked`/`single_mirror`로 표시됩니다.
2. 음식 DB의 상당수(65/165)가 100 mL 기준이라 kcal을 계산하지 않습니다(mL→g 환산 금지 원칙).
3. 1회 제공량(1인분)은 집단 참고량입니다. '공기', '개' 같은 단위는 원자료에 없어 g을 추정하지 않습니다.
4. Excel 내보내기는 통합문서를 새로 쓰므로 사용자 서식·추가 시트·수식은 보존되지 않습니다.
5. 실제 OneDrive/Google Drive 동기화 클라이언트와 Windows 파일 잠금은 시뮬레이션(PermissionError 주입, `~$` 잠금 파일, 잘린 zip)으로만 시험했습니다.
