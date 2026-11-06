# 02 — 토의자(reviewer) 독립 검증 결과 (2026-11-06)

대상: `feature/iteration-2` @ `fd04fbe` (main 대비 커밋 5개, 48 files, +4259/−118).
기준: `docs/review/01-advisor-plan-review.md`(합격 기준), `docs/iteration-2-plan.md`(A-1 경로), `docs/poc-results.md`.
방법: 코더 보고를 쓰지 않고 직접 실행했습니다. 검증 스크립트는 모두 `/tmp/review/`에 두었고 저장소 코드는 바꾸지 않았습니다. 미러 파일은 `python -I`로 데이터로만 파싱했고, 미러 안의 스크립트는 실행하지 않았습니다.

## 1. 요약 (합격 기준 충족 여부 의견)

**의견: 조건부 불합격.** BLOCKER 1건과 아래 MAJOR 항목을 고친 뒤 재검토할 것을 권합니다.

- **체크리스트 형식 항목은 대부분 재현됩니다.** pytest 107 passed, AIUI 하네스 23/23(공식 validator issues 0), validator exit 0, soak seed 2026·7 수치까지 문서와 같습니다. 실제 uvicorn에서 돌린 smoke도 `RESULT PASS`입니다. 확인 없는 쓰기 → 400, 멱등 replay와 다른 payload → 409, 동시 8회 → 1건, 미래·365일 경계, 오래된 사본으로 덮어써도 19 유지, `_sync` 삭제 → blocked·파일 미변경, 잠금 → pending 후 해제 시 1회 반영도 모두 확인했습니다.
- **BLOCKER(X-1)**: 새 Excel 행이 기존 제품의 바코드/QR을 그대로 가지고 있으면(제품ID 오타, 행 복사) `IntegrityError`가 납니다. 그 뒤로는 동기화가 **영구 정지**합니다: API는 500, 이후 export 0회. status는 그대로 `up_to_date`/`exported`로 보입니다. "오류가 사용자에게 성공으로 보이는 경로"가 생깁니다.
- **영양 데이터(A)**: 값 자체는 미러 원문과 일치합니다(전사 오류 0/22). 하지만 "교차검증"은 **같은 이름의 행 중 하나라도 맞으면 통과**하는 방식입니다. MFDS 음식 DB에는 같은 이름의 행이 여러 개 있습니다(동명이식). 그래서 다른 미러가 반대하는 경우가 무시됩니다. `mirror_cross_checked` 142행 가운데 carb 미러가 반대하는 행이 33개, health-log(행마다 공식 식품코드 URL 보유)가 반대하는 행이 21개입니다. 또 "100 mL 기준이라 kcal 없음" 65행 중 **31행**은 다른 두 미러에 100 g 기준 대표행이 있습니다(현미밥·잡곡밥·비빔밥·라면·짬뽕·제육볶음·멸치볶음 등). 이 한계는 원자료의 성질이 아니라 1차 미러(toadsam)가 "이름당 1행"으로 중복을 없앤 결과입니다.
- **음성 일지(B)**: 합격 기준의 표현은 통과합니다. 기준 밖 자연어에서는 조용히 틀리는 경로가 있습니다. 조사 제거 정규식이 단어 내부를 지워 `브로콜리→"브 콜리"`, `포도→"포"`가 되고, `지난달 6일`과 `작년 11월 6일`은 **오늘 날짜로** 확정됩니다. 기록된 g만 있는 날의 speech_text에는 '추정'이 빠집니다.
- **Excel(C)**: 장기 사용 관점에서 두 가지가 걸립니다. `excel_exports`가 export마다(잠금 실패 poll 포함) 전체 스냅숏을 영구 보관해 DB가 계속 커집니다. 또 기본값 `AUTO_APPLY=false`에서는 사람이 Excel을 한 번 고치면 이후 /use 변경이 Excel에 **더 이상 저장되지 않습니다**. 확인 API 외에는 확인할 UI가 없습니다.

## 2. 이슈 표

심각도: BLOCKER(승인 전 필수) / MAJOR(승인 전 수정 권장) / MINOR / NIT. 재현 스크립트 경로는 `/tmp/review/*.py`입니다.

| ID | 심각도 | 영역 | 재현 방법(명령/입력) | 기대 | 실제 | 제안 |
|---|---|---|---|---|---|---|
| X-1 | **BLOCKER** | Excel merge | `python3 /tmp/review/excel_adv.py <repo>` §D, `/tmp/review/typo_api.py`: export된 파일에서 `CARE-SENS-AIR-SENSOR`의 product_id만 `…X`로 바꿈(바코드·QR 유지) → sync | 신규 생성 거부 또는 conflict/invalid로 보고. 나머지는 계속 동기화 | `_apply`→`inv._set_codes`에서 `UNIQUE constraint failed: product_codes…`. 트랜잭션 롤백 뒤 **매 sync마다 같은 예외**. 수동 apply API 500. 이후 /use 2회 → `pending True`, Excel 미갱신. `status.last_result.status`는 `up_to_date`/`exported` 그대로이고 이벤트 0건. dry-run은 `creates 1`만 보여 주고 경고 없음 | plan 단계에서 바코드·QR 중복을 `invalid_row`(또는 conflict)로 분류. `_apply` 예외를 잡아 `last_result=error`·이벤트로 남기고 export는 계속(파일 `blocked` 정책과 구분). 회귀 테스트와 soak 시나리오에 추가 |
| N-1 | MAJOR | 영양 교차검증 | `python3 -I /tmp/review/disagree.py /tmp/nutri-mirrors …public.csv …curated_foods.csv` | 다른 미러에 같은 이름이 있는데 값이 다르면 제외·보고(계획 A-1 "Rows that disagree are excluded") | `agrees()`는 kangsogo7의 동명 행(김치찌개 5행, 비빔밥 6행 등) 중 하나라도 맞으면 `mirror_cross_checked`로 판정. 다른 미러의 반대는 무시. 142행 중 carb 반대 33, health-log 반대 21. **값이 있는 행인데 공식코드 행과 모순되는 것 7건**: 부대찌개 123 vs 67 kcal(D306-284000000-0004), 추어탕 54 vs 32(D306-298000000-0001), 소불고기 186 vs 170, 깍두기 40 vs 33, 햄버거 264 vs 284, 볶음밥 193 vs 183, 순대 187 vs 181. 리포트의 `excluded_disagreement`는 9건만 보고 | 식품코드로 행을 고정(health-log 코드 또는 동명 행 전부 대조). '존재하는 모든 미러의 일치'를 요구하고, 불일치는 `ambiguous_name`으로 제외·보고. 등급 이름을 실제 의미에 맞게(`transcription_checked` 등) 바꾸기 |
| N-2 | MAJOR | 영양 행 선택 | 같은 스크립트 출력의 "100ml rows whose name has a different (100g) row" 31건. toadsam `scripts/food/README.md`: "음식: 같은 음식이 급식·외식 등으로 여러 줄 → **이름당 하나**(급식이 아닌 것 우선)" | 대표행(표준 식품코드, 100 g)이 있으면 그 행 사용 | 현미밥(toad 120/100 mL vs carb·health-log 172/100 g, D101-050000000-0001), 잡곡밥, 비빔밥(D101-018000000-0001, 142), 라면(D103-148000000-0001, 82), 짬뽕, 삼계탕, 제육볶음, 멸치볶음(114 vs 276) 등 주식이 kcal "미상". `HUD_PRIORITY` 24개 중 8개(잡곡밥·현미밥·미역국·콩나물국·제육볶음·고등어구이·멸치볶음·감자샐러드)가 값 없음. poc-results 한계 2("음식 DB의 상당수가 100 mL 기준")가 원인을 원자료 성질로 잘못 설명 | 1차 출처를 식품코드가 있는 행으로 바꾸거나 kangsogo7·carb에서 100 g 대표행을 고르도록 규칙 추가. 문서 한계 2 정정 |
| N-3 | MAJOR | 단위 해석 | `/tmp/review/api_adv.py`: `오늘 점심 비빔밥 먹었어` | 100 mL 기준 음식의 1인분은 mL이므로 g으로 표시하지 않음(결정 7·"mL→g 환산 금지") | `serving_size_g=530`(실제로는 mL. health-log 탕수육 `343, 'mL'`로 확인) → `grams=530, grams_basis=serving_size`가 스냅숏으로 저장되고 HUD에 `비빔밥 · 530g · 미상` 표시 | basis가 100ml이면 `serving_size_g`를 비우고 `serving_size_ml` 별도 컬럼 사용. compute_item에서 grams null + 사유. validator에 basis↔값 일관성 검사 추가 |
| P-1 | MAJOR | 음성 파서 | `python3 /tmp/review/parser_adv.py <repo>`: `어제 저녁 브로콜리랑 고로케 먹었어`, `오늘 간식 포도 먹었어`, `오늘 저녁 로제떡볶이 먹었어`, `오늘 점심 은갈치구이 먹었어`, `오늘 점심 김치찌개에 밥 먹었어` | 음식명 보존 | `_FILLER`가 `로|은|는|에|으로` 등을 **단어 내부에서도** 제거: `브 콜리`, `고 케`, `포`, `제떡볶이`, `갈치구이`, `김치찌개  밥`(1항목). `브로콜리`는 DB 별칭인데도 매칭 실패 | 조사는 어절 끝(`(?<=\S)(은|는|…)(?=\s|$)`)에서만 제거. 음식명 회귀 표 추가(DB의 모든 이름/별칭을 문장에 넣어 왕복) |
| P-2 | MAJOR | 날짜 해석 | 같은 스크립트: `지난달 6일 아침 기록 김밥`, `작년 11월 6일 아침 기록 김밥`(now=2026-11-06 12:00) | 2026-10-06 / 2025-11-06, 또는 되묻기 | 둘 다 **2026-11-06**, `status ok`, 질문 없음. 음식명도 `지난달 김밥`/`작년 김밥`으로 오염 | `지난달/저번 달/작년/올해/이번 달` 처리 또는 `ask`. 미처리 시간 표현이 남으면 확정 금지 |
| D-1 | MAJOR | speech_text | `/tmp/review/api_adv.py` §5: `{"food_name":"쌀밥","grams":210}`만 있는 날 summary | 결정 8 "'추정' 명시", 합격 기준 "추정 표시가 speech_text에" | `11월 3일 점심 기록입니다. 총 약 349킬로칼로리, 입력값입니다. 쌀밥.`, `is_estimate=false`. g만 사용자 입력이고 kcal은 미러 기준값으로 계산한 값 | kcal은 항상 '추정'으로 표기(g 출처와 분리). `is_estimate` 의미를 kcal 기준으로 |
| X-2 | MAJOR | Excel 장기 사용 | `/tmp/review/growth.py`(200제품, 사용 100회), `/tmp/review/excel_adv.py` §A2(PermissionError 20회 poll) | 기준선에 필요한 스냅숏만 보관, 크기 상한 | export마다 전체 스냅숏 저장(200제품 ≈ 49 KB/회, 사용 100회에 DB +5.8 MB). 잠금 실패 poll마다 행 +1(20 poll → 21행). `excel_exports`·`excel_sync_events` 삭제 코드 없음. 하루 1000회 사용이면 연 ~21 GB(추정치) | 최근 N개, 그리고 파일·충돌사본이 참조할 수 있는 export_id만 보관. 실패 export는 스냅숏 저장 생략 또는 재사용. 이벤트 보관 기간 설정. soak에 DB 크기 불변식 추가 |
| X-3 | MAJOR | Excel 기본 설정 | `/tmp/review/excel_adv.py` §L: 기본 `AUTO_APPLY=false`, poll 0.2 s, HICARDI 재고를 Excel에서 77로 수정 → API로 /use 3회 | 요구 3 "변경 시 Excel에 저장" 유지 | DB 16, Excel 19 유지. status `external_changes_pending_confirmation`, `pending_export true`. 확인은 `POST /excel-sync`뿐이고 AIUI·관리 화면에 버튼 없음. 또 `INVENTORY_XLSX_POLL_SECONDS`가 없는 예전 `.env`이면 기본 0이라 /use 후 자동 export 없음(문서상 "0 = 시작 시·수동만") | 확인 대기 중에도 Excel 쪽에 대기 상태를 표시(예: `_sync`/별도 시트, 상태 파일). 관리 화면/HUD 확인 경로 추가. 또는 기본 AUTO_APPLY=true + merge_delta. poll 기본값을 .env.example과 맞추기(5) |
| P-3 | MINOR | 음성 파서 | `어제 저녁에 김치찌개랑 밥 반 공기`, `오늘 점심 계란 두 개랑 우유 한 잔`, `오늘 저녁 삼겹살 2인분이랑 소주 한 병` | 날짜+끼니+음식이 있으면 record(확인 화면) | `intent unknown` → HUD "인식 못함". 동사(기록/먹었어)가 꼭 있어야 함 | 날짜·끼니·음식 조합이면 record로 추정(확인 단계가 있으므로 안전) |
| P-4 | MINOR | 음성 파서 | `오늘 아침 점심 둘 다 김밥 먹었어`, `오늘 점심 밥 두 공기 반 먹었어`, `오늘 점심 김밥 먹었어 아 아니다 라면` | 끼니 2개 → 되묻기. `2.5 공기`. 정정 처리 또는 되묻기 | breakfast만, 음식 `점심 둘 다 김밥`. `qty 2`, 이름 `밥 반`. `김밥 아 아니다 라면` 1항목 | 끼니가 여러 개면 ask. `N 단위 반` = N+0.5. `아니(다)` 이후 우선 또는 ask |
| P-5 | MINOR | 음성 파서(영어) | `breakfast today rice`, `log breakfast today rice 200g` | 영어는 범위가 명시되지 않음. 지원하면 일관되게 | 첫 문장 unknown. 둘째는 날짜 기본값(today 미인식), 음식 `log today rice` | 영어 미지원을 명시하거나 today/yesterday 추가 |
| N-4 | MINOR | 별칭 자동 매칭 | `오늘 점심 된장국 먹었어`, `… 김 …`, `… 고구마 …` | P1-7 취지: 짧은 일반어가 특정 변형으로 자동 확정되지 않음 | `된장국→호박된장국`(400 g, 124 kcal), `김→조미김`, `고구마→고구마(생것)`, `감자→생감자`, `계란→생달걀`, `떡→가래떡`, `빵→식빵`, `치즈→모차렐라` 자동 확정 | 일반어 별칭은 candidates로만. 또는 확인 화면에 "(변형 선택)" 강조 |
| N-5 | MINOR | 출처 표기 | toadsam `scripts/food/README.md` 출처표, 번들 `source_url` | 실제 받은 곳 표기. 농진청 행 출처표시 | toadsam은 K-FIND(various.foodsafetykorea.go.kr) 음식 DB 2026-08-28판 + **농진청 국가표준식품성분 DB 10.4**(R행)를 사용. 번들은 25개 R행까지 `MFDS_STD_DATA`, data.go.kr 15100064로 표기. LICENSE에 농진청 출처표시 없음. 당류·나트륨은 kangsogo7 단일 미러 값(교차검증 안 됨, 0이 '없음'일 가능성) | R행 `source=RDA_NFCDB_10.4`, LICENSE에 출처 추가. sugar/sodium에 별도 검증 등급 |
| N-6 | MINOR | validator | `python3 scripts/validate_nutrition_csv.py`(인자 없음) | 사용법 오류(exit≠0) | 출력 없이 **exit 0**(아무것도 검사 안 하고 통과). basis=100ml인데 값이 있는 경우, serving 단위 검사 없음. `atwater_exempt` 컬럼은 번들에 없음(예외 0건. 최대 편차는 고등어(구운것) 264 vs 304로 허용치의 76%) | 인자 없으면 기본 2파일 또는 exit 2. basis·serving 일관성 규칙 추가 |
| M-1 | MINOR | 마이그레이션 | `/tmp/review/mk_v1.py`(main 코드로 v1 DB 생성 + 비DEMO `MFDS_API` 행) → `/tmp/review/mig_test.py`(init_db 3회 + create_app 2회) | 멱등, 기존 비DEMO 행 등급 보존 | 멱등 OK(2회째 추가 컬럼 0, 재고·tx 불변, schema_version 2). 다만 v1의 `is_demo=0` 행이 `verification='demo_mock'`이 되어 최하위 순위가 되고, validator 기준으로도 위반 | 마이그레이션 시 `is_demo=0 AND verification='demo_mock'` → `single_mirror`/`legacy_api`로 보정 |
| X-4 | MINOR | Excel 수식/경고 | `excel_adv.py` §F: openpyxl로 `=20+10` 저장(캐시값 없음) | invalid 보고. 사용자 수식 보존(범위 제외) | invalid 1 + **`row_missing (never deleted…)` 경고가 함께 나옴**(행이 있는데 삭제로 보고). export가 수식을 20으로 덮어씀(이벤트로만 남음) | invalid 행은 row_missing 계산에서 제외. 수식 셀은 `formula_without_cached_value`로 명확히 |
| X-5 | MINOR | Excel 상태 | `excel_adv.py` §L: 재기동 직후 status | 의미 있는 상태 | `last_result.status = deferred_unstable`: poller 첫 관측과 서버 자신의 export 직후 매번 1회 발생 | 마지막 export 시 기록한 stat을 `observed`에 넣어 자기 쓰기를 안정 상태로 간주 |
| X-6 | MINOR | soak 범위 | `scripts/soak_inventory_excel.py`, `run_soak` | 합격 기준 "5+ 재기동"·장기 사용 | 재기동은 같은 프로세스에서 연결만 새로 만듦. poller 스레드·HTTP 동시성 없음. 외부 수정은 stock_qty만(ID·바코드·새 행 없음 → X-1을 못 잡음). Excel==DB는 마지막에만 확인 | 실제 `create_app`+poller로 짧은 soak 1회, 수정 종류 무작위화(새 행·ID 변경·행 삭제·정렬), 단계별 불변식 |
| X-7 | MINOR | 충돌 사본 판정 | `conflict_copies()` 정규식 `-[^.]+` | 동기화 클라이언트 충돌 사본만 | `inventory-backup.xlsx` 같은 사용자 파일도 "conflict copy"로 경고(경고뿐이라 영향 작음) | OneDrive(`-PC명`), Google Drive(` (1)`), Dropbox(`(… conflicted copy …)`) 패턴으로 한정 |
| A-1 | MINOR | AIUI diary | `diary.ink saveLog/switchCandidate` 코드 검토 | 응답 유실 뒤 재시도는 replay | 저장 응답이 유실된 뒤 사용자가 후보를 바꾸면 같은 `pending.key`에 다른 payload가 실려 **409로 고착** | 후보 변경 시 새 key 발급(서버 저장 여부를 먼저 `GET` 확인) |
| NIT-1 | NIT | 데이터 | 번들 aliases | — | `만두국;만두국`, `떡만두국;떡만두국` 중복 | 빌더에서 dedupe |
| NIT-2 | NIT | 문서 | iteration-2-plan "Deviations… see the coder report in the PR description" | 저장소 안에서 추적 가능 | 저장소에 없음 | docs에 편차 목록 추가 |

확인 결과 문제가 없었던 항목(기대 = 실제):
- **/use 잠금 중 연속 사용**: `~$` 존재 중 5회 사용 → `deferred_locked_by_excel`, DB 15/Excel 20, pending. 해제 후 1회 export → Excel 15.
- **`_sync` 삭제**: `blocked`, 파일 sha 불변, 이후 /use 후에도 덮어쓰지 않음.
- **행 순서 변경**: 변경 0, adjust 0.
- **빈 행 2개 삽입 + 값 변경**: 정상 반영.
- **헤더 한글화**(`제품ID/재고수량/제품명`): 매핑되어 반영.
- **같은 export 두 번 apply**: 두 번째는 sha가 이미 import된 것이므로 무시(stock 30 유지, adjust 1). 같은 옛 export_id 위의 다른 두 번째 수정 → 직전 import 기준 차분만 반영(32 = 기대 32).
- **충돌 사본 `inventory (1).xlsx`(값 0)**: 경고만, DB 20 유지.
- **오래된 사본 덮어쓰기**: 19 유지, adjust 0.
- **한글·공백·괄호 파일명** `재고 목록 (원본).xlsx`: export 성공, 실제 uvicorn에서도 성공.
- **트랜잭션 경계**: 파일 읽기·쓰기(`read_workbook`, `_write_workbook`, `os.replace`)는 모두 `BEGIN IMMEDIATE` 밖. 병합은 쓰기 잠금 안에서 다시 계획한 뒤 적용. export는 프로세스 내 `path_lock` 안에서만 실행되어 export끼리 경합 없음. 다중 워커(프로세스) 사이 잠금은 없으므로 uvicorn `--workers 1` 전제를 문서화 권장.
- **poller 종료**: 실제 uvicorn에 SIGINT → 2.3 s 안에 "Application shutdown complete", 잔여 프로세스 없음.
- **AIUI API 사용**: `speechSynthesis.speak(new SpeechSynthesisUtterance(text), 'enqueue')`는 `apis/ai.md`와 일치. `utterance.lang`·`cancel()` 미사용. 음성 인식 `start()`는 버튼/Enter 핸들러(`voice()`)에서만 호출해 interactive gate 조건을 지킴. TTS가 없으면 HUD 문구로 폴백.

## 3. 독립 검증한 영양 행 (22행)

선정: `random.seed(4242)`로 16행을 무작위 추출하고, 주식·문제 후보 8개(현미밥·김치찌개·비빔밥·고등어구이·라면·우유·두부·탕수육)를 지정 추가했습니다(비빔밥·탕수육은 무작위 표본과 겹쳐 중복 제거 후 22행). 파서는 코더 빌더와 별개로 직접 작성했습니다(`/tmp/review/verify_nutri.py`: toadsam TSV 행 분리, kangsogo7·carb JSON, health-log SQL을 `'g'|'mL'` 단위까지 파싱). 값 순서는 kcal / 탄수 / 단백 / 지방(/100), `serv` = 1인분.
미러 커밋: toadsam `6c36231`, carb `152a0a4`, kangsogo7 `a51bb95`, health-log `3b78a6d`.

| # | 식품명 | 번들 값 | 미러 원본 값 | 전사 일치 | 행 선택(동명이식) |
|---|---|---|---|---|---|
| 1 | 시금치나물 | 69/3.4/3.7/4.5, 당0.1 Na136, serv 50, 100g | toad 69/3.4/3.7/4.5 serv50 100g · kang(4행 중 1) 동일 · carb 동일 · HL 69/3.36/3.74/4.46 (D113-586000000-0001) | 일치 | 일치 |
| 2 | 어묵국 | 값 없음, serv 600, 100ml | toad D 32/4.2/2.2/0.8 100ml serv600 · kang·carb 32 | 일치(값 보류) | 일치 |
| 3 | 비빔밥 | 값 없음, serv 530, 100ml | toad 133/17.7/4.5/4.6 100ml · carb 142/18.8/6.9/4.3 serv450 · HL 142 /100g (D101-018000000-0001) | 일치 | **불일치**(대표행 142 kcal/100g 있음) |
| 4 | 브로콜리(데친것) | 26/4.5/3.2/0.2 | toad R "브로콜리, 데친것" 26/4.5/3.2/0.2 | 일치 | 단일 |
| 5 | 나박김치 | 10/1.1/0.5/0.4, serv 100 | toad 동일 · carb 동일 · kang 10/**1.2**/0.5/0.4 | 일치 | 일치(kang 0.1 차이로 당·Na는 비움) |
| 6 | 총각김치 | 42/7.9/1.9/0.3, 당3 Na630 | toad·kang·carb 동일 | 일치 | 일치 |
| 7 | 탕수육 | 값 없음, serv 343, 100ml | toad 113/11.2/6.7/4.4 100ml · HL **343 mL**, 113 (D412-566000000-0001) | 일치 | 일치. 단, serv 343은 **mL**(N-3) |
| 8 | 돼지고기볶음 | 175/9.1/11.5/10.3, 당4.1 Na526, serv 200 | toad·kang·carb 동일 | 일치 | 일치 |
| 9 | 청국장찌개 | 47/1.9/5/2.1, 당0 Na242 | toad·carb 동일 · kang 2행 중 1 일치 | 일치 | 일치 |
| 10 | 인절미 | 242/50.1/5.6/2.2, 당6.4 Na297 | toad·kang·carb 동일 | 일치 | 일치 |
| 11 | 감자샐러드 | 값 없음, serv 80, 100ml | toad 161/15.6/2.7/10 100ml · kang·carb 161 | 일치 | 일치 |
| 12 | 김밥 | 140/20/4.8/4.5, serv 230, D101-007000000-0001 | toad 동일 · carb 동일 · HL 140/19.98/4.84/4.55 · kang 140/20/4.8/**4.6** | 일치 | 일치 |
| 13 | 김치전 | 값 없음, serv 180, 100ml | toad 122 100ml · kang 4행 중 122 · **carb 134** serv150 | 일치 | **불일치 무시** |
| 14 | 추어탕 | 54/3.1/3.2/3.2, 당0 Na246, serv 350 | toad·kang·carb 54 · **HL 32**/2.68/2.27/1.32 serv1000 (D306-298000000-0001) | 일치 | **불일치 무시**(공식코드 행과 모순) |
| 15 | 감자탕 | 71/2.3/6.3/4.1, 당0 Na328, serv 530 | toad·carb·kang(5행 중 1)·HL(D106-260000000-0001) 동일 | 일치 | 일치 |
| 16 | 사과 | 52/14/0.3/0.1 (single_mirror) | toad R "사과, 생것" 52/14/0.3/0.1 · HL 52/13.96/0.26/0.07 (R108-050000001-0000) | 일치 | 일치. 등급은 과소(실제 2 미러) |
| 17 | 현미밥 | 값 없음, serv 300, 100ml | toad 120/25.8/2.3/0.4 100ml · **carb 172/38.9/3.1/0.5 serv230 · HL 172 /100g (D101-050000000-0001)** · kang 5행(120,121,172,118,120) | 일치 | **불일치**(대표행 172/100g) |
| 18 | 김치찌개 | 61/3/3.8/3.8, 당0.8 Na491, serv 400, D306-266000000-0001 | toad·carb 동일 · HL 61/2.98/3.77/3.75 · kang 5행 중 1(나머지 4행 19 kcal) | 일치 | 일치 |
| 19 | 고등어구이 | 값 없음, serv 170, 100ml | toad·carb 142 100ml · **HL 340 /100g** (D108-357110000-0001) | 일치 | **불일치 무시** |
| 20 | 라면 | 값 없음, serv 590, 100ml | toad 79 100ml serv590 · **carb 82 serv550 · HL 82 /100g (D103-148000000-0001)** | 일치 | **불일치**(대표행 82/100g) |
| 21 | 우유 | 67/4.9/3.1/3.9, 당4.8 Na40 | toad R·carb·kang·HL(R113-009000000-0000) 동일 | 일치 | 일치 |
| 22 | 두부 | 97/3.8/9.6/4.6, R121-043020300-0000 | toad·HL 동일 · kang 85/3/8/4.2 | 일치 | 부분(kang 반대) |

추가(전체 스캔 `/tmp/review/disagree.py`): 부대찌개 번들 123 vs HL 67(D306-284000000-0004), 멸치볶음 toad 114/100ml vs carb·HL 276/100g(D110-472000000-0001).

**결론**: 번들 값은 toadsam 행을 **그대로 전사**했습니다(22/22 전사 일치, 반올림 차이 외 오류 없음). 문제는 전사가 아니라 **어느 동명 행을 고르느냐**입니다(N-1, N-2).

**미러가 MFDS 데이터를 재배포한 것인지의 근거 평가**:
- kangsogo7: JSON `source`에 "식품의약품안전처 전국통합식품영양성분정보 표준데이터 (공공데이터포털)", `builtAt 2026-10-14`. 식품코드는 없고 동명 행이 여러 개.
- carb-loading-tracker: `source`에 "식품의약품안전처 식품영양성분 데이터베이스 (공공데이터포털 …표준데이터)". 이름당 1행, 코드 없음.
- toadsam: `scripts/food/README.md`에 출처표(K-FIND 가공식품·음식 DB, 농진청 DB 10.4), 원본 컬럼명 `식품명`·`영양성분함량기준량` 사용이 빌드 스크립트에 보임. 단, 음식은 이름당 1행으로 중복 제거했고, 기준량이 비면 `"100g"`으로 간주합니다(`str(r[c_basis] or "100g")`). 이것이 바로 지도교수 P1-5가 지적한 버그와 같은 처리라 일부 "100g" 행의 기준량은 확인할 수 없습니다.
- health-log: 95행마다 `various.foodsafetykorea.go.kr …searchFoodCd=…` 공식 상세 URL과 식품코드가 있어 출처 근거가 가장 강합니다. 다만 1인분 총량으로 환산·반올림된 값입니다.
- 종합: 네 곳 모두 MFDS(일부 농진청) 공개 데이터를 재가공한 것으로 보는 근거는 충분합니다. 다만 같은 원천을 가공한 것들이라 **서로 독립적인 검증이 아닙니다**. 미러 간 일치는 "전사 정확성"만 보장하고 "공식값과의 일치"는 보장하지 않습니다. 공식 상세 페이지 대조는 이 세션의 WebFetch allowlist 밖(`URL_NOT_ON_ALLOWLIST`)이라 하지 못했습니다.

## 4. 테스트 재실행 결과

| 명령 | 결과 |
|---|---|
| `python3 -m pytest -q` | `107 passed in 24.85s` (수집 107: excel 17, 파서 표 32건 포함) |
| `node aiui-agent/tests/run-aiui-checks.mjs --aiui-repo /tmp/aiui-src/jsar --with-server` | `23/23 passed`, exit 0, "official AIUI bench validator has no issues" |
| `python3 scripts/validate_nutrition_csv.py` (인자 없음) | 출력 없음, exit 0 (N-6) |
| `python3 scripts/validate_nutrition_csv.py sample-data/nutrition_reference_public.csv sample-data/nutrition_demo.csv` | `165 rows, 0 failing` / `6 rows, 0 failing`, exit 0 |
| 같은 validator + 일부러 만든 불량 CSV(`/tmp/review/neg/bad.csv`) | 2/2 failing(Atwater, 비허용 도메인), exit 1 (검출 기능 정상) |
| `python3 scripts/soak_inventory_excel.py --seed 99 --uses 2000 --edits 60 --restarts 6` (**새 seed**) | PASS, 32.6 s, locked 34, exports_written 594, excel_imports 58, conflicts 51, rejected 0 |
| 같은 명령 `--seed 2026` / `--seed 7` (문서 수치 재현) | 2026: locked 38·exports 593·imports 59·conflicts 53 / 7: locked 42·imports 55·conflicts 43. **poc-results.md와 일치** |
| 실제 uvicorn(포트 8765, `INVENTORY_XLSX_PATH=/tmp/review/smoke/linked/재고 목록.xlsx`, poll 1 s) + `scripts/smoke_test.py` | `RESULT PASS`, speech_text "11월 5일 저녁 기록입니다. 총 약 360킬로칼로리, 추정입니다. 김밥, 배추김치."(문서와 동일), 종료 후 status `up_to_date`, change_seq=exported_seq=4 |
| `/tmp/review/api_adv.py` | 확인 없음 400 · FUTURE_DATE 422 · 366일 DATE_OUT_OF_RANGE · 365일 200 · 2025-02-29 422 · 같은 키 replay true · 다른 payload 409 · (utterance/source만 다르면 replay. 지문에 미포함, 허용 가능) · 동시 16요청(같은 키 8 + 다른 키 8) → 같은 키 1행, 다른 키 8행 · 긴 요약 83자·3문장 |
| `/tmp/review/mig_test.py` (iteration-1 DB) | init_db 3회 + create_app 2회: 추가 컬럼 0, 재고·거래 불변, schema_version 2. M-1만 이슈 |

## 5. 문서 정확성

- **수치는 모두 재현됩니다**: 107 passed, 23/23, 165/6 rows 0 failing, 빌드 리포트 수치(175/1/9/142/23/65/165), soak 2026·7, smoke speech_text. 과장된 수치는 없습니다.
- **고칠 표현이 있습니다**:
  - (a) `mirror_cross_checked`를 "교차검증"이라 부르는 것: 실제로는 "동명 행 중 하나와 일치"이고, 다른 미러가 반대한 54건(carb 33 + HL 21, 일부 중복)이 보고되지 않았습니다(N-1).
  - (b) 한계 2 "음식 DB의 상당수(65/165)가 100 mL 기준": 원인 설명이 틀렸습니다. 1차 미러의 중복 제거 때문이고, 31행은 100 g 대표행이 있습니다(N-2).
  - (c) LICENSE/README의 "MFDS 데이터": R 25행은 농진청 DB 10.4에서 왔습니다(N-5).
  - (d) api.md "기준량이 100 mL인 음식은 g이 있어도 kcal null": 그 'g'은 사실 mL입니다(N-3).
  - (e) poc-results 표의 "재고 ↔ Excel … 가능": X-1(영구 정지)과 X-3(기본 설정에서 Excel 저장 중단)을 고려하면 "조건부"가 맞습니다.
- RV101·Simulator·실제 OneDrive/Drive 클라이언트는 모두 NOT VERIFIED로 표기되어 있어 정직합니다. soak의 재기동이 프로세스 내 재연결이라는 점도 문서에 명시되어 있습니다.
