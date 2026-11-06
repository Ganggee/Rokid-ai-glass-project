# 05 — 지도교수 최종 심사 (2026-11-06)

대상: `feature/iteration-2` @ `992d765` (main 대비 커밋 10개, 52 files, +7681/−118).
기준: `01-advisor-plan-review.md`의 합격 기준. 참고 자료: 02(토의자 1차), 03(코더 대응), 04(토의자 재검증).
PM 승인 사항(X-3 안전 자동 반영, N-1 엄격 선정 124행)은 확정된 결정으로 보고 심사했습니다.
방법: 코드는 수정하지 않았습니다. 명령은 직접 실행했고, 심사용 스크립트는 저장소 밖 `/tmp/advisor/`에만 두었습니다. 미러 파일은 `python -I`로 데이터만 읽었습니다.

## 0. 최종 판정

**APPROVE WITH CONDITIONS.** 아래 §5의 merge 전 조건 M-1~M-4를 고친 뒤 merge합니다.

- 체크리스트 대부분은 직접 재현했습니다.
- review 02의 BLOCKER·MAJOR 9건은 모두 해결됐습니다. 04의 판정에 동의합니다.
- 실제 프로세스에서 SIGKILL을 반복해도 재고 무결성은 유지됐습니다.
- 남은 문제 1: 이번 심사에서 새로 찾은 문제 F-1. 서버가 내보내는 동안 사람이 Excel을 저장하면 그 수정이 **조용히 사라집니다**.
- 남은 문제 2: 합격 기준 "공식 행 > DEMO" 위반(R-4).
- 남은 문제 3: 가장 흔한 문장 형태에서 음식명이 잘림(R-2).
- 세 건 모두 국소 수정으로 고칠 수 있으므로 REJECT 사유는 아니라고 판단합니다.

## 1. 실행 결과 (직접 실행)

| 명령 | 결과 |
|---|---|
| `python3 -m pytest backend/tests -q` | **159 passed**, exit 0 (31.98 s) |
| `node aiui-agent/tests/run-aiui-checks.mjs --aiui-repo /tmp/aiui-src/jsar --with-server --python python3` | **24/24 passed**, exit 0. 공식 validator issues 0 |
| `python3 scripts/validate_nutrition_csv.py …public.csv …demo.csv` | 124 rows 0 failing / 6 rows 0 failing, exit 0. 인자 없이 실행하면 usage를 출력하고 exit 2 |
| `python3 scripts/soak_inventory_excel.py --seed 2026` | **PASS**, 38.9 s. locked 44, needs_review 32, manual 15. 최대 행 수 exports 50, snapshots 50. DB 0.87 MB. poc-results의 수치와 같음 |
| (심사용) 실제 uvicorn + SIGKILL 7회 + 동시 /use 1200회(4스레드, 같은 키로 재시도) + Excel 수정 18회 | stock=Σdelta 위반 0, 멱등 키 중복 0, import sha 중복 0, Excel==DB, 최종 `ok/up_to_date`. replay 11회 |
| (심사용) 실제 앱 흐름(lifespan poller 0.2 s, 한글 파일명) | §3-2 참조. 병합 산술이 모두 맞음 |
| (심사용) F-1 재현 | §4 참조 |

iteration-1 테스트 변경 확인: `test_meal_api.py`의 단정문 3곳이 바뀌었습니다. 공개 영양 행이 추가되어 매칭 결과가 달라진 데 따른 정당한 변경입니다. 약화된 단정은 없습니다.

## 2. 합격 기준 체크리스트

### 회귀
| 항목 | 판정 | 근거 |
|---|---|---|
| pytest 0 failed(기존 40 포함) | PASS | 159 passed |
| confirmed 없는 /use·/meal-logs·/excel-sync apply → 400, DB 불변 | PASS | `test_confirmation_idempotency_future`, `test_api_preview_confirm_and_status`, iteration-1 테스트. 04에서도 재현 |
| 멱등 replayed · 다른 payload 409 · 동시 8회 → 1회 | PASS | 테스트에서 통과. 실제 프로세스 kill 중 같은 키 재시도에서도 1200키가 각각 1행, replay 11 |
| 음수·소수 재고 invalid | PASS | Excel −3 → `needs_review`, DB 불변. soak의 invalid_value(−1, 2.5, "many") |
| 기준 중량 없으면 g·kcal null + 사유 | PASS | `계란 2개` → `reference_has_no_serving_size`, `밥 한 공기` → `unit_mismatch`, 100 mL → `volume_basis` |
| DEMO/추정 표시가 응답·화면·speech_text에 | PASS | "총 약 1440킬로칼로리, 추정, 일부 열량 미상, DEMO 포함입니다." display_lines에 "(추정)" |
| 비밀·실데이터 미추적 | PASS | `git ls-files`에 .env, sqlite, uploads, reports, real, aix 없음. 하네스 config.js 검사 PASS |
| 정확도 주장에 명령+출력, RV101 NOT VERIFIED | PASS | poc-results 표 수준 구분이 정직함 |

### 영양
| 항목 | 판정 | 근거 |
|---|---|---|
| validator exit 0(필수 필드·도메인·범위·C+P+F·Atwater) | PASS | 위 실행. 불량 행 검출은 `test_validator_rejects_bad_rows`, 02의 음성 대조 |
| 정규화 픽스처(100 g/200 g/100 mL/빈 값) | PASS | `test_per_100g_factor_rules`, `test_mfds_empty_basis_no_longer_treated_as_100g` |
| 김밥≠밥 자동 확정 | PASS | 김밥 → MFDS-D-007, 참치김밥 → 매칭 없음 + 후보 |
| **공식 행 > DEMO** | **FAIL** | R-4: `계란 2개` → DEMO-EGG, `rice 200g` → DEMO-RICE 300 kcal(DEMO_MOCK 임의값)로 자동 확정됨. 공개 행 `달걀(생것)`·`쌀밥`은 후보로만 나옴. 기본 `NUTRITION_CSV`에서 발생 |
| 기준값 갱신 후 과거 기록 kcal 불변 | PASS | `test_snapshot_survives_reference_update` |

### 음성 일지
| 항목 | 판정 | 근거 |
|---|---|---|
| 파서 표 ≥30건(now 주입, 지정 사례) | PASS | 표 32건 + P-2 15건 + P-1 10건. 2026-01-02, 11-06 00:30, 03-31 주입. `31일(4월)`은 표에 없어 직접 확인: now=4/15에 `31일` → 3/31, `30일` → 3/30(결정 4 "오늘 이후면 전월"과 일치) |
| 자정 경계 | PASS | 00:30 '오늘' → 경고. 23:59에 파싱하고 자정 뒤 저장해도 파싱 날짜가 유지됨 |
| speech_text 제한·'미상' | PASS | 86자·3문장. "일부 열량 미상" |
| from-session 멱등 | PASS | `test_from_session_is_idempotent` |
| 하네스 diary(확인 전 POST 0, 취소 0, speak 1), validator 0 | PASS | 24/24. 단, 로직 하네스이며 SIM이나 실기기 검증이 아님 |

### Excel
| 항목 | 판정 | 근거 |
|---|---|---|
| 오래된 사본 → 19 유지·adjust 0 | PASS | 테스트 + 04 |
| `_sync` 없음/모르는 export_id → apply 0·conflict | PASS | 기존 회사 파일을 그대로 지정한 경우 `blocked`, 파일 바이트 불변, DB 불변 |
| 잠금 → /use 성공·pending·해제 후 1회 | PASS | `~$` 잠금 중 수정과 /use → `pending_locked`. 닫은 뒤 13+(24−14)=23으로 병합·내보내기 |
| 잘린 zip transient | PASS | `test_truncated_file_is_transient` |
| 충돌 사본 경고만 | PASS | 테스트, 04 X-7 |
| 행 삭제 → DB 불변·복원·경고 | PASS | `test_deleted_row_restored_and_new_row_created` |
| 커밋 직후 kill → 재기동 시 pending export | PASS | 프로세스 내 테스트 + 심사용 실제 SIGKILL 7회 후 Excel==DB |
| soak(2000+ 사용, 50+ 수정, 5+ 재기동) 불변조건 | PASS(조건 정의 범위 안에서) | seed 2026 재실행 PASS. 문서화된 대로 soak의 재기동은 프로세스 내 재연결입니다. 실제 프로세스 kill 실험으로 보완했습니다. 다만 불변조건 목록에 "사람의 수정이 보존된다"가 없어 F-1을 잡지 못합니다(§4). 이것은 기준을 설계한 지도교수 쪽의 누락입니다 |

요약: 체크리스트 32개 항목 중 31개 PASS, 1개 FAIL(공식 행 > DEMO).

## 3. 과학적 타당성과 사용성

### 3-1. 과학적 타당성
- **출처 표시: PASS.**
  - 124행 모두 `source`, `source_url`, `source_detail`(미러@커밋, anchor 식품코드), `retrieved_at`, `verification`을 가집니다.
  - `source`는 MFDS_FOOD_DB 100행, RDA_NFCDB_10.4 24행입니다. 당류·나트륨은 `micro_verification=single_mirror`로 표시됩니다.
  - `source_url`은 실제로 받은 파일이 아니라 데이터셋 소개 페이지입니다. 실제 경로는 `source_detail`에 있으므로 수용합니다.
- **'추정' 표기: PASS.** 기준표로 계산한 kcal은 항상 `is_estimate=true`이고, 화면과 음성에 '추정'이 붙습니다.
- **GitHub 미러의 한계 기술: 대체로 정직합니다.** poc-results 한계 1·2는 미러 4곳이 같은 원천의 재가공본이라 독립 검증이 아니라는 점을 밝힙니다. 미러 간 일치는 전사 정확성만 뜻하고, 공식 값 확인은 공식 파일 임포트로만 가능하다는 점도 적혀 있습니다. 1차 미러의 중복 제거 때문에 생긴 오해도 정정했습니다. 다만 다른 문서들이 이 설명과 어긋납니다(§5 M-4).
  - `sample-data/README.md` 3행은 "nutrition values are not from the MFDS DB"라고 적어 공개 CSV와 모순됩니다.
  - `docs/required-inputs.md`에는 아직 "165행"이 남아 있습니다.
  - `docs/iteration-2-plan.md`의 Final design(165행, AUTO_APPLY opt-in, merge_delta를 conflict로 기록)이 낡았습니다.
  - 같은 문서의 Deviations 표는 기준을 "150~400"으로 잘못 인용합니다. 실제 기준은 최소 30 / 목표 60 / 상한 150이며, 124행은 기준 안입니다.
- **1회 제공량 기반 g의 단위 일치 규칙: PASS.**
  - 말한 g → `stated`.
  - 단위 없음 또는 '인분' → 수량 × 1인분(`serving_size`, 추정).
  - '공기', '개', '줄' → null + 사유.
  - 100 mL 기준 행 → mL만 표시하고 g·kcal은 null. mL→g 환산 없음.
  - 주의 1: `serving_size_g`는 원자료의 '식품중량'을 1인분으로 해석한 값입니다(Deviations 표에 명시). 예를 들어 선택된 MFDS 쌀밥 행(D301-022000000-0001)의 식품중량은 100 g입니다(미러 3곳이 일치). 그래서 "쌀밥 1인분" = 100 g = 166 kcal로 계산되어 집에서 먹는 한 공기보다 작게 나옵니다. 확인 화면에 g가 표시되므로 사용자가 바로잡을 수 있지만, 문서에 한 줄 명시가 필요합니다(M-4).
  - 주의 2: 가장 흔한 표현인 "밥 한 공기"는 항상 '미상'입니다. 결정 7대로의 보수적 동작이 맞습니다. 다음 iteration에서 공식 출처의 가정 계량 단위 표가 필요합니다.
- **장기 사용 시 무결성: PARTIAL.**
  - 지켜지는 것: 재고 불변조건(Σdelta, 음수 없음, 멱등)은 프로세스 kill 상황에서도 지켜졌습니다. 저장 공간 상한(exports·snapshots 50)도 지켜집니다.
  - F-1(새 문제): 서버가 내보내는 동안 사람이 저장하면 그 수정이 조용히 사라집니다. §4.
  - R-1: 50회보다 오래된 export를 기준으로 한 사본은 `blocked`가 됩니다. 안전하게 멈추지만 Excel 갱신이 중단되고, Excel 쪽에는 아무 표시가 없습니다. 심사용 실험(70회 export 뒤 수정 사본 복원)에서도 같았습니다. DB는 다시 반영하지 않았고(25 유지), 이후 pending이 쌓였습니다.
  - R-5: 이전 번들에서 철회된 행이 재시드 뒤에도 남습니다. 현재는 개발용 DB에만 해당합니다.

### 3-2. 사용자 관점
- **음성 일지(날짜·끼니 → 확인 → 저장 → 조회 → 읽기): 서버·하네스 수준에서 사용 가능.**
  - `11월 5일 저녁 김밥 1인분이랑 배추김치 먹었어` → 확인 항목 2개(230 g 322 kcal 추정 / 100 g 38 kcal 추정) → 저장 200 → 조회 → "11월 5일 저녁 기록입니다. 총 약 360킬로칼로리, 추정, 일부 열량 미상입니다…"(63자).
  - 막히는 지점:
    - R-2: `떡볶이랑` → "떡볶", `갈치구이랑` → "갈치구". 124개 이름 중 8개가 깨지고 kcal이 미상이 됩니다.
    - R-4: 계란·rice가 DEMO 값으로 기록됩니다.
    - `엊저녁 김밥 먹었어`: **오늘** 저녁으로 확정되고 음식은 "엊 김밥"이 됩니다(경고만 있고 status ok). 결정 4·P-2의 "모르는 날짜 조각은 되묻기"에서 빠진 경우입니다.
    - 띄어 쓴 `김치찌개 하고 공깃밥` → 1항목으로 붙습니다.
    - `이백그램` → g 인식 실패.
    - 제육볶음 등 제외된 50개 음식은 후보조차 없습니다(PM 승인 N-1의 대가).
  - 한국어 STT·TTS는 NOT VERIFIED입니다.
- **Excel(동기화 폴더 지정 → 수정 → 반영 → 안경 차감 → Excel 갱신): 사용 가능.**
  - 실제 앱에서 확인한 흐름:
    - 새 경로 지정 → 서버가 파일을 만듦.
    - /use → Excel 갱신.
    - `~$` 잠금 중 수정과 /use → 닫으면 양쪽 차분이 병합됨.
    - 잘못된 셀 → `needs_review`(파일 보존) → 셀을 고치면 22+(30−23)=29로 반영.
    - 이미 반영한 수정 사본을 다시 복원 → 다시 반영하지 않음.
  - 막히는 지점:
    - (a) 기존 회사 Excel을 그대로 지정하면 `blocked`입니다. 올바른 절차(`import_inventory.py`로 먼저 가져오기 → 서버가 만들 **새 파일 경로** 지정)는 어디에도 순서대로 적혀 있지 않고, troubleshooting의 사후 조치로만 나옵니다.
    - (b) `needs_review`/`blocked` 상태가 Excel이나 HUD에 보이지 않습니다(R-8).
    - (c) F-1.
- **문서만 보고 따라 하기: PARTIAL.**
  - README 빠른 시작과 `aiui-studio-deploy.md`(서버 → configure → Import → Preview → AIX → 리소스 업데이트)는 따라 할 수 있습니다.
  - `sample-data/README.md`의 Excel 설정 3줄도 명확합니다.
  - 하지만 `docs/troubleshooting.md`에 틀린 안내가 있습니다. "`INVENTORY_XLSX_AUTO_APPLY=false`(기본)"는 실제 기본값 true와 반대이고, "100 mL 65행"은 실제 31행입니다.
  - 일지가 SERVER 모드 전용인지는 배포 문서에 없습니다.

## 4. 새 문제 F-1 (MAJOR): 내보내는 동안 사람이 저장하면 수정이 조용히 사라짐

- 위치: `backend/app/services/excel_sync.py` `sync_once`.
  - L537에서 파일 sha를 읽습니다.
  - L602에서 `_sha(path) != last_export_sha`이면 내보냅니다.
  - L603 `export()` → L179 `_replace(tmp, path)`.
  - 읽은 뒤 교체하기 전에 파일이 바뀌었는지 다시 확인하지 않습니다. L602 조건은 오히려 "파일이 우리 export와 다르면" 덮어쓰기를 **유발**합니다.
- 결정적 재현(`/tmp/advisor/toctou.py`):
  ```
  sync(초기 export, H=15) → use → _replace를 감싸 "사람이 H를 25로 저장(원자적 rename)한 뒤 원래 replace" 실행
  → status exported, 이어서 poll 3회 → up_to_date, DB H=15, Excel H=15, excel_sync_events 0건
  ```
- 확률적 재현(`/tmp/advisor/race.py`, 실제 앱 + poller 1 s, 사람 수정 20회):

  | 조건 | 손실 |
  |---|---|
  | /use 1초 간격, 원자적 저장 | 160/160 반영, 손실 0 |
  | /use 1초 간격, 제자리 저장 | 135/135 반영, 손실 0 |
  | /use 0.05초 간격, 원자적 저장 | **150 중 40만 반영** |
  | /use 0.05초 간격, 제자리 저장 | 155 중 65만 반영 |

  모든 경우 최종 state는 `ok`이고 Excel==DB입니다. 그래서 soak 불변조건으로는 드러나지 않습니다.
- 평가:
  - PoC 사용 빈도에서는 확률이 낮습니다.
  - Windows에서는 Excel이 연 파일에 `os.replace`가 실패하는 경우가 많아 일부 완화됩니다.
  - 그러나 OneDrive나 Drive 클라이언트가 다른 PC에서 받은 수정을 쓰는 시점은 임의적입니다.
  - 결과가 "사람의 수정이 성공 상태로 사라짐"이므로 P0-1의 취지("수정을 되돌리지 않는다")를 어깁니다.

## 5. 조건

### merge 전 필수 (M)
| ID | 내용 | 완료 기준 |
|---|---|---|
| M-1 | **F-1 수정.** `_replace` 직전(같은 `path_lock` 안)에 파일 stat·sha가 이번 단계에서 읽은 값 또는 `last_export_sha`/알려진 import와 같은지 다시 확인합니다. 다르면 교체하지 않고 `deferred_changed`(pending 유지)로 끝냅니다. L602의 "sha가 다르면 export" 조건은 알려진 import일 때만 허용합니다 | 위 `_replace` 훅 재현을 회귀 테스트로 추가: 사람의 +10이 다음 poll에 반영되고(H=25), 이벤트 또는 상태가 남음. soak에 "사람 수정 합계 = excel_sync adjust 합계(needs_review로 보류된 것 제외)" 불변조건 추가 |
| M-2 | **R-4 수정.** 공개 행 후보가 있으면 DEMO 행을 자동 확정하지 않습니다(DEMO 별칭에도 일반어 규칙 적용) | 회귀 테스트: 모든 이름·별칭에서 "자동 확정 결과가 DEMO이면 non-DEMO 후보가 없음". `계란 2개`, `rice 200g`이 DEMO로 저장되지 않음 |
| M-3 | **R-2 수정 + `엊저녁` 처리.** 경계(`이랑/랑/하고`) 분리와 조사 제거는 사전을 우선합니다. 띄어 쓴 `하고`도 경계로 봅니다. `엊저녁`(엊그저께 포함)은 어제 저녁으로 처리하거나 되묻습니다. 날짜를 기본값으로 둔 경우 음식명에 날짜 조각이 남으면 되묻습니다 | 번들의 모든 이름·별칭을 `오늘 점심 X이랑 김밥 먹었어`, `… X 하고 김밥 …`에 넣어 왕복하는 테스트 0 실패. `엊저녁 김밥 먹었어` → 2026-11-05 dinner 또는 ask |
| M-4 | **문서 정정.** (a) troubleshooting의 AUTO_APPLY 기본값·65행 → 실제 값. (b) required-inputs 165 → 124. (c) sample-data/README 3행이 공개 CSV와 모순되지 않게. (d) iteration-2-plan Final design 갱신, Deviations의 기준 인용을 "30/60/150"으로. (e) sample-data/README에 **"처음 연결하기"** 절차(기존 Excel → `import_inventory.py` → 서버가 만들 새 경로 지정 → 기존 파일을 지정하면 blocked). (f) R-1 한계와 복구 절차(최근 50회 export보다 오래된 사본 → blocked). (g) '1인분' = 원자료 식품중량(쌀밥 100 g 예)이라는 점. (h) 일지는 SERVER 모드 전용인지 명시 | 문서 diff 검토 |

M-1~M-3은 각각 국소 수정과 테스트 1~2개로 끝납니다. 재심사는 코더 보고와 토의자 확인만으로 충분합니다. 지도교수 재심사는 필요 없습니다. 단, pytest·하네스·validator·soak seed 2026을 다시 실행한 출력을 첨부해야 합니다.

### 다음 iteration으로 넘길 것 (N)
- R-1의 근본 해결: 개수가 아니라 기간으로 보존(예: 14일 + 시간 단위 솎기 + 용량 상한).
- R-8 / blocked 가시화: HUD 재고 화면 배지, 동기화 폴더의 상태 파일(예: `inventory.SYNC-STATUS.txt`).
- R-9: LibreOffice `.~lock.*#` 패턴.
- X-5의 시작 직후 `deferred_unstable`.
- R-3 `아까/방금`, R-6 `마셨어/…에서/밤에`, 한글 수사 g(`이백그램`), 공식 출처의 가정 계량 단위 표(공기·개).
- R-5 철회 행 비활성화.
- R-7 HUD_PRIORITY와 번들 일치 테스트.
- R-10, R-11.
- 공식 MFDS 파일 실데이터 임포트로 미러 값 대조(현재 NOT VERIFIED).
- 실제 OneDrive/Google Drive 클라이언트와 Windows Excel 잠금 실험.
- OS 프로세스 재시작을 반복하는 soak를 CI 밖 수동 절차로 문서화(이번 심사에서 1회 PASS).
- Simulator → RV101 D1–D15, 한국어 STT/TTS.

## 6. 계획 단계 기준에 대한 자기 평가
- soak 불변조건에 "사람 수정 보존"과 "동시 쓰기"를 넣지 않았습니다. 그래서 F-1이 체크리스트를 모두 통과한 채 남았습니다. 다음 기준표에는 "외부 수정 합계 = 반영 합계 + 보고된 보류"를 넣겠습니다.
- 결정 9의 "공식 > DEMO"와 P1-7(일반어 자동 확정 금지)이 부딪칠 수 있다는 점(R-4)을 미리 정리하지 않았습니다. 우선순위는 **"DEMO는 공개 후보가 있으면 절대 자동 확정하지 않는다"**로 확정합니다.
