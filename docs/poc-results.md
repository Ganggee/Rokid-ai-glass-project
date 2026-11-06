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

# Iteration 2 results (2026-11-06, development sandbox — after review 02 fixes)

역할 분담: 지도교수(계획·합격 기준) → 코더(구현) → 토의자(독립 검증, `docs/review/02-reviewer-findings.md`: 조건부 불합격) → 코더 수정(`docs/review/03-coder-response.md`) → 지도교수 최종 판단. 아래 수치는 수정 후 다시 실측한 값입니다.

| 기능 | UNIT | API E2E | AIUI 로직 하네스 | AIUI SIM | RV101 | 판정 |
|---|---|---|---|---|---|---|
| 공개 영양 DB 124행(대표 행 선정 규칙·검증 등급) + 검증기 | PASS | — | — | — | — | 가능(미러 기반, 아래 한계 1) |
| 공식 파일/API 임포터, 빈 기준량 버그 수정 | PASS(픽스처) | — | — | — | — | 코드 완료, 공식 파일 실데이터 **NOT VERIFIED** |
| 음성 식사 기록: 파싱 → 확인 → 저장(멱등) | PASS(파서 표 + 회귀 표) | PASS | PASS | NOT VERIFIED | NOT VERIFIED | 가능(한국어 STT 미확인) |
| 날짜로 조회 / 읽어 주기(TTS) | PASS | PASS | PASS(speak 1회, 미지원 폴백) | NOT VERIFIED | NOT VERIFIED | 화면 가능, 한국어 음성 **미확인** |
| 분석 결과 → 일지 기록(분석당 1건) | PASS | PASS | PASS | — | — | 가능 |
| 재고 ↔ Excel 내보내기/병합/잠금/충돌/안전 자동 반영 | PASS(30) | PASS(API·실제 poller) | — | — | — | 가능(실제 OneDrive/Drive 클라이언트 **NOT VERIFIED**, `--workers 1` 전제) |
| 장기 사용 soak | PASS | — | — | — | — | 아래 수치 |

실행 증거 (2026-11-06 재실행)
- `python -m pytest -q` → **159 passed** (iteration 1의 40 포함; Excel 30, 일지 72, 영양 17).
- `node aiui-agent/tests/run-aiui-checks.mjs --with-server` → **24/24** (공식 validator issues 0; A-1 응답 유실 시나리오 추가).
- `python scripts/smoke_test.py` (실제 uvicorn, `INVENTORY_XLSX_PATH`=한글·공백 파일명, poll 1 s) → `RESULT PASS`; 종료 후 status `state ok`, `up_to_date`, pending 없음; `/admin/inventory-sync` 200.
- `python scripts/validate_nutrition_csv.py …public.csv …demo.csv` → 124 rows 0 failing / 6 rows 0 failing. 인자 없이 실행 → 사용법 출력, exit 2.
- `python -I scripts/build_nutrition_reference.py --mirrors /tmp/nutri-mirrors` → curated 175, 미러에 없음 1, **합의 없음으로 제외 50**, `mirror_cross_checked` 104, `single_mirror` 20 → **번들 124행(값 있음 93행)**. 이 중 37행은 health-log의 공식 식품코드 행이 기준(anchor), 10행은 1차 미러(toadsam)의 행 대신 다른 동명 행이 선택됨(예: 현미밥 120 kcal/100 mL → 172 kcal/100 g, D101-050000000-0001). 기준량 100 mL라 값을 비운 행 31. 상세: `sample-data/nutrition_reference_public.report.json`.
- `python scripts/soak_inventory_excel.py --uses 2000 --edits 60 --restarts 6` (수정 종류 무작위: 재고 변경·새 행·바코드 복사된 ID 오타·행 삭제·잘못된 값; poller와 같은 안전 자동 반영 + 일부 수동 반영):

| seed | 결과 | 시간 | 잠금 주입 | needs_review | 수동 반영 | 최대 행 수 exports/snapshots/imports/events | DB 크기 |
|---|---|---|---|---|---|---|---|
| 2026 | PASS | 36.1 s | 44 | 32 | 15 | 50 / 50 / 9 / 136 | 0.88 MB |
| 7 | PASS | 35.0 s | 41 | 18 | 11 | 50 / 50 / 13 / 131 | 0.86 MB |
| 99 | PASS | 36.6 s | 31 | 17 | 7 | 50 / 50 / 9 / 126 | 0.87 MB |

  재기동은 프로세스 내 연결 재생성입니다. 실제 앱(lifespan poller 0.1 s + 동시 HTTP /use 30회 + Excel 수정 4회)은 `test_x6_real_app_poller_with_concurrent_http_and_edits`, 커밋 직후 중단 복구는 `test_crash_after_commit_before_export_is_recovered`로 따로 확인했습니다.

한계
1. 영양값은 공식 사이트가 아니라 **공개 미러 4곳의 재배포본**입니다. 네 곳 모두 같은 원천(MFDS·농진청)을 가공한 것이라 서로 독립적인 검증이 아닙니다. `mirror_cross_checked`는 "같은 원천의 같은 행이 여러 미러에 똑같이 옮겨져 있다"는 뜻이고, 공식 값과의 일치는 공식 파일 임포트(`official_file_import`)로만 확인됩니다.
2. 같은 이름의 음식이 원자료에 여러 행(급식·외식 등)으로 있어, 미러들이 서로 다른 행을 고른 음식 50개는 합의가 없어 **제외**했습니다(부대찌개·추어탕·제육볶음·고등어구이 등). 원자료에 100 g 행이 없는 것이 아니라 대표 행을 정할 근거가 부족한 것입니다. 공식 파일을 임포트하면 채워집니다. (이전 문서의 "음식 DB의 상당수가 100 mL 기준" 설명은 1차 미러가 이름당 1행으로 중복을 제거한 결과를 원자료 성질로 잘못 설명한 것이라 정정합니다.)
3. 기준량이 100 mL인 31행은 kcal을 계산하지 않고 1인분을 `serving_size_ml`(mL)로만 보여 줍니다(mL→g 환산 금지).
4. 1회 제공량(1인분)은 집단 참고량입니다. '공기', '개' 같은 단위는 원자료에 없어 g을 추정하지 않습니다. 당류·나트륨은 미러 1곳 값(`micro_verification=single_mirror`)입니다.
5. Excel 내보내기는 통합문서를 새로 쓰므로 사용자 서식·추가 시트·수식은 보존되지 않습니다(수식 셀은 invalid로 보고).
6. 실제 OneDrive/Google Drive 동기화 클라이언트와 Windows 파일 잠금은 시뮬레이션(PermissionError 주입, `~$` 잠금 파일, 잘린 zip)으로만 시험했습니다. 여러 워커 프로세스 사이 잠금은 없으므로 서버는 `--workers 1`로 실행해야 합니다.
