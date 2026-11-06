# Rokid AI Glasses Dual PoC — Inventory & Meal Analysis

Rokid Glasses **RV101** + Hi Rokid + **AIUI Studio Global**에서 두 기능이 실제로 연결·동작 가능한지 확인하는 **기술 PoC**입니다 (상용/의료기기 아님).

| 과업 | 내용 | 상태 (2026-11-04) |
|---|---|---|
| 1. 재고관리 | 목록·QR/바코드·제품 사진·음성으로 제품 조회 → **확인 후** 사용량 차감 → 재실행 후에도 유지 | 백엔드·AIUI 로직 구현/자동 테스트 통과. Simulator/실기기 **미검증** |
| 2. 식단·영양 | 식전·식후 사진 → 음식별 **추정** 섭취 비율 → 제공량이 있을 때만 g·kcal·탄단지 | 백엔드·AIUI 로직 구현/합성 이미지 테스트 통과. 실사진/실기기 **미검증** |
| 2b. 음성 식사 일지 (iter. 2) | "11월 6일 아침 김밥 1인분이랑 김치 먹었어" → 확인 후 기록, "어제 저녁 기록 읽어줘" → 화면+음성 | 서버·AIUI 로직 테스트 통과. 한국어 STT/TTS 실기기 **미검증** |
| 1b. 재고 ↔ Excel (iter. 2) | 연동 폴더의 Excel로 내보내기·안전한 수정 자동 반영·잠금/충돌 처리·`/admin/inventory-sync` | 테스트·soak(2000회×3 seed) 통과. 실제 OneDrive/Drive 클라이언트 **미검증** |
| 영양 DB (iter. 2) | 식약처 음식·농진청 원재료 기반 124행(출처·검증 등급), 공식 파일 임포터 | 미러 교차검증 104행, 합의 없는 50개 제외 |

상세 결과: [`docs/poc-results.md`](docs/poc-results.md) · 실기기 체크리스트: [`docs/poc-test-plan.md`](docs/poc-test-plan.md)

## 구조
```
aiui-agent/   AIUI Agent (이 폴더만 AIUI Studio로 Import) — 촬영·입력·HUD
backend/      FastAPI + SQLite(정본) + OpenCV/OCR + 식사 비교·영양 계산
scripts/      seed / import / configure_agent / smoke_test / eval_synthetic_meals / purge_uploads
sample-data/  DEMO 데이터 (회사 데이터 아님)
docs/         아키텍처, API, AIUI 기능 매트릭스, 오픈소스 검토, 배포, 테스트 계획/결과, 인수인계
```

## 빠른 시작 (Windows PowerShell)
```powershell
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
Copy-Item .env.example .env          # API_TOKEN을 긴 임의값으로 변경
python scripts\seed_demo_data.py --reset
python -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
# 다른 창
python scripts\smoke_test.py --base-url http://127.0.0.1:8000
```
- OpenAPI: http://127.0.0.1:8000/docs · 식사 관리자 화면: http://127.0.0.1:8000/admin/meals
- 실제 Excel: `python scripts\import_inventory.py sample-data\real\재고.xlsx` (미리보기) → `--mode seed --apply` ([컬럼 가이드](sample-data/README.md))

## 테스트
```powershell
python -m pytest -q                                   # 159개: UNIT + API E2E(실제 서버 재기동 포함)
git clone --depth 1 https://github.com/yodaos-project/AIUI ..\AIUI
node aiui-agent\tests\run-aiui-checks.mjs --aiui-repo ..\AIUI --with-server --python python   # 24개
python scripts\soak_inventory_excel.py --seed 2026  # 재고+Excel 장기 사용 시험
python scripts\validate_nutrition_csv.py sample-data\nutrition_reference_public.csv sample-data\nutrition_demo.csv
```
AIUI 검사는 공식 저장소의 `bench/src/validator.js`(정적 규칙)와 `bench/src/behavior.js`(페이지 로직 실행기)를 사용하며, 렌더링/실기기 검증이 아닙니다.

## 안경에 올리기 (요약 — [상세](docs/aiui-studio-deploy.md))
1. 안경에서 접근 가능한 **HTTPS** 서버 준비 (localhost 불가: 안경→블루투스→폰 경유).
2. `python scripts\configure_agent.py --base-url https://<host> --token <API_TOKEN>` (비우면 LOCAL DEMO 모드).
3. AIUI Studio → **Import from local folder** → `aiui-agent/`.
4. Device Simulation → Preview로 확인 → Build & Review → **Package AIX**.
5. Hi Rokid → Settings → Developer → **Update glasses resource package** → "Hi Rokid, open Rokid Dual PoC".

## 과업 1: 영구 저장 문제 해결 방식
- **SERVER 모드**: SQLite가 정본. `POST /api/v1/inventory/use`는 `confirmed=true` + `idempotency_key` 필수, `BEGIN IMMEDIATE` 원자 처리, 음수 불가, 같은 키 재전송은 `replayed: true`로 1회만 반영.
- 안경은 POST 전 pending 저널을 `wx.setStorageSync`에 기록 → 응답 유실/앱 종료 후 재진입 시 `GET /operations/{key}`로 확인(무작정 재전송 안 함).
- **LOCAL DEMO 모드**: 서버 없이 안경 저장소에 재고 보관 → 단일 기기에서 20→19→재실행→19 확인용.

## 과업 2: 추정 정책
- 섭취 비율은 2D 면적 기반 **추정치**. g는 초기 제공량이 있을 때만, 영양소는 g와 100g당 값이 있을 때만 계산. 없으면 `null` + 사유.
- 합성/가정 값은 `is_demo` / `DEMO`. 영양 기본값(`sample-data/nutrition_demo.csv`)은 **DEMO_MOCK**(식약처 값 아님).
- Baseline 0(수동 영역) → Baseline 1(OpenCV 자동 정렬·마스크) → 선택 모델 플러그인(SAM 2, 미설치 시 폴백).
- 하이카디·케어센스·닥터눈 의료데이터 API/EMR 연동은 범위 밖.

## GitHub
이 저장소는 로컬 Git으로 만들어졌습니다. 작업 세션에서 GitHub 인증이 없어 원격 생성/push는 하지 않았습니다. 직접 올리려면:
```powershell
gh auth login
gh repo create rokid-ai-glasses-dual-poc --private --source . --remote origin --push
```

## 보안
`.env`, SQLite, `uploads/`, `reports/`, `sample-data/real/`, `*.aix`는 커밋 금지(.gitignore). `aiui-agent/lib/config.js`는 빈 값으로만 커밋(CI 검사).
라이선스: [`LICENSE-THIRD-PARTY.md`](LICENSE-THIRD-PARTY.md), 오픈소스 검토: [`docs/open-source-evaluation.md`](docs/open-source-evaluation.md).
