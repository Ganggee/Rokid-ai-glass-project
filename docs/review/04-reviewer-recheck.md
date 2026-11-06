# 04 — 토의자 재검증 (review 02 → 03 조치 확인, 2026-11-06)

대상: `feature/iteration-2` @ `992d765`(review 02 이후 커밋 5개: `0f86e0a`, `d98111a`, `00e9211`, `e21c192`, `992d765`).
방법: 코더 보고(03)를 그대로 믿지 않고 직접 실행했습니다. 쓴 것:
- review 02의 재현 스크립트: `/tmp/review/excel_adv2.py`, `typo_api.py`, `parser_api.py`, `verify_nutri.py`
- 새 스크립트: `recheck_x.py`, `disagree2.py`, `api2.py`, `demo_win.py`, `stale_rows.py`, `misc.py`

코드는 수정하지 않았습니다.

## 1. 요약

**review 02의 BLOCKER/MAJOR 9건은 원래 재현 입력 기준으로 모두 VERIFIED입니다.** 다만 수정 과정에서 **MAJOR 회귀 2건**(R-1, R-4)이 생겼고, P-1 범위에서 **새 MAJOR 1건**(R-2)을 찾았습니다.

의견: **조건부 합격 직전.** R-1·R-2·R-4를 고친 뒤 지도교수 최종 판단으로 넘기기를 권합니다(세 건 모두 국소 수정으로 보입니다).

## 2. 재실행 결과

| 명령 | 결과 |
|---|---|
| `python3 -m pytest -q` | `159 passed in 32.80s` |
| `node aiui-agent/tests/run-aiui-checks.mjs --aiui-repo /tmp/aiui-src/jsar --with-server` | `24/24 passed`, exit 0 (validator issues 0) |
| `python3 scripts/validate_nutrition_csv.py` (인자 없음) | usage 출력, exit 2 |
| `python3 scripts/validate_nutrition_csv.py …public.csv …demo.csv` | 124 rows 0 failing / 6 rows 0 failing, exit 0 |
| `python3 scripts/soak_inventory_excel.py --seed 4242 --uses 2000 --edits 60 --restarts 6` (**새 seed**) | PASS, 40.0 s. 잠금 45, needs_review 31, 수동 반영 12. 수정 종류: stock 39·new_row 5·invalid 6·pid_typo 6·delete 4. 최대 행 수 exports 50·snapshots 50·imports 10·events 143. DB 0.88 MB |
| 실제 uvicorn(포트 8766, **poll·AUTO_APPLY 미설정 = 기본값**, 한글 파일명) + `scripts/smoke_test.py` | `RESULT PASS`. 시작 직후 status `waiting/deferred_unstable`(X-5 참고). smoke 후 `ok/up_to_date`, pending 없음, `/admin/inventory-sync` 200, SIGINT 후 2.0 s에 종료 |

## 3. review 02 이슈별 판정

| ID | 원 심각도 | 판정 | 근거(재현) |
|---|---|---|---|
| X-1 | BLOCKER | **VERIFIED** | `recheck_x.py` R5: ID 오타(바코드 유지) → dry-run `preview`, `safe_for_auto_apply=false`, invalid "barcode … already used", error 없음. auto(poller 경로) → `needs_review`, 파일 유지, /use 후 pending. 수동 apply → `merged_and_exported`, state `ok_with_rejected_rows`, Excel S=19=DB. 다음 /use → export 정상(18=18). `typo_api.py`: API 200(이전 500) |
| N-1 | MAJOR | **VERIFIED** | `disagree2.py`: 값이 있는 93행 전부에서, 같은 이름을 가진 모든 미러(carb·kangsogo7·health-log)에 일치 값이 있음(**불일치 0**). 공식코드 행과 모순되던 7행(부대찌개·추어탕·소불고기·깍두기·햄버거·볶음밥·순대)은 번들에서 제외. 무작위 15행 대조는 §5 |
| N-2 | MAJOR | **VERIFIED** | 현미밥 172·잡곡밥 146·비빔밥 142·라면 82·짬뽕 58·멸치볶음 276·삼계탕 101이 모두 100 g + 공식 식품코드. "100 mL 행인데 다른 미러에 100 g 대표행이 있는 경우" 0건(이전 31건). 대가: 번들 165→124행(값 있음 100→93행). R-7 참고 |
| N-3 | MAJOR | **VERIFIED** | 100ml 31행 모두 `serving_size_g` 비어 있고 `serving_size_ml`만 있음. `감자샐러드` → grams null, `volume_ml 80`, `null_reason=volume_basis`. 표시 줄 "감자샐러드 80mL 열량 미상" |
| P-1 | MAJOR | **VERIFIED**(원 입력) | 브로콜리·고로케·포도·로제떡볶이·은갈치구이 보존. "김치찌개에 밥" → 2항목. 단, 같은 범위에서 새 문제 R-2 |
| P-2 | MAJOR | **VERIFIED** | `지난달 6일` → 2026-10-06, `작년 11월 6일` → 2025-11-06. now=3/31에 `지난달 31일` → "2월에는 31일이 없습니다" 되묻기. `다음달 1일` → future. 다만 R-3(회귀) |
| D-1 | MAJOR | **VERIFIED** | 기록된 g만 있는 날 → "총 약 349킬로칼로리, 추정입니다." `is_estimate=true` |
| X-2 | MAJOR | **VERIFIED** | 200제품 × 600회 사용 → exports 50·snapshots 50, DB 약 3.2 MB에서 더 늘지 않음. 잠금 실패 20 poll → exports 1행(이전 21). 다만 보존 개수 50개 상한 때문에 R-1(회귀) |
| X-3 | MAJOR | **VERIFIED** | 기본값 AUTO_APPLY=true·poll 30 s. `excel_adv2.py` §L: Excel 수정 + /use 3회 → DB 16 = Excel 16, `up_to_date`(이전에는 Excel 19에서 멈춤). 안전하지 않은 수정 → `needs_review`(R4·R8), 고치면 즉시 반영. `/admin/inventory-sync` 200, 출력 escape, API는 토큰 필요. 남은 점은 R-8 |
| P-3 | MINOR | VERIFIED | 동사 없는 `어제 저녁에 김치찌개랑 밥 반 공기` → record + 확인 |
| P-4 | MINOR | VERIFIED | `아침 점심 둘 다` → 끼니 되묻기. `두 공기 반` → quantity 2.5. 정정 표현 → 되묻기 |
| P-5 | MINOR | PARTIAL(수용) | `breakfast today rice` → record. 하지만 `rice`가 DEMO 행으로 갑니다(R-4) |
| N-4 | MINOR | VERIFIED → **REGRESSION R-4** | 일반어는 공개 행에서 후보로만 나오지만, DEMO 행의 일반 별칭이 자동 확정됨 |
| N-5 | MINOR | VERIFIED | R행 24개 `source=RDA_NFCDB_10.4`, `micro_verification=single_mirror` 70행 |
| N-6 | MINOR | VERIFIED | 인자 없음 → exit 2. 100ml 행 일관성 규칙 동작 |
| M-1 | MINOR | VERIFIED | 저장해 둔 v1 DB(`/tmp/review/mig/v1.sqlite3` 사본): init_db 3회 + create_app 2회 → 추가 컬럼 0, 재고·tx 불변, `MFDS-API-X` → `legacy_api` |
| X-4 | MINOR | VERIFIED | `=20+10`(캐시값 없음) → "formula_without_cached_value", row_missing 경고 없음 |
| X-5 | MINOR | **NOT FIXED**(재기동 경로) | 서버가 직접 내보낸 뒤에는 해결됨. 그러나 프로세스 시작 직후 첫 poll은 여전히 `deferred_unstable`이고, state가 최대 poll 간격(기본 30 s)만큼 `waiting`으로 보임(실제 uvicorn에서 확인). 시작 시 sync에서 stat을 `observed`에 넣으면 해결 |
| X-6 | MINOR | PARTIAL(수용) | 수정 종류 무작위화와 실제 앱 테스트를 확인. OS 재시작 반복은 없음(문서에 명시) |
| X-7 | MINOR | VERIFIED | `inventory-backup.xlsx`·`inventory_2026.xlsx`는 제외. ` (1)`, `-DESKTOP-AB12`, Dropbox `conflicted copy`만 사본으로 판정 |
| A-1 | MINOR | VERIFIED | 하네스 시나리오 PASS. 코드상 결과가 불확실한 저장 뒤에는 `list`로 먼저 확인하고 새 key 발급(NIT R-10) |
| NIT-1 | NIT | VERIFIED | 별칭 중복 0 |
| NIT-2 | NIT | VERIFIED | plan에 Deviations 표 있음 |

## 4. 새 이슈 / 회귀

| ID | 심각도 | 구분 | 재현 | 기대 | 실제 | 제안 |
|---|---|---|---|---|---|---|
| R-1 | **MAJOR** | REGRESSION(X-2) | `recheck_x.py` R3: export E1 파일 보관 → /use+export 60회 → E1 사본에 HICARDI=999 저장 → sync | 지도교수 P0-1: 오래된 사본도 export_id 기준으로 병합(사용 기록 보존 + 사람의 수정 반영) | E1 스냅숏이 `KEEP_EXPORTS=50` 밖이라 삭제됨 → **`blocked`**(unknown_baseline). 이후 /use가 있어도 파일을 덮어쓰지 않아 Excel 저장이 사람 조치 전까지 멈춤. `~$` 잠금이 없는 환경(Excel Online/OneDrive 웹, LibreOffice는 R-9 참고)에서 바쁜 날이면 실제로 생길 수 있음. 50개 안쪽(R2, 10회)은 정상 병합 | 보존 기준을 개수가 아니라 기간으로(예: 14일. 제품 200개 기준 49 KB/회, 용량 상한 병행). 또는 오래된 export는 일정 간격(예: 1시간에 1개)으로 솎아 남기고, 그 기준으로 보수적으로 병합 + 관리 화면에서 확인. 한계를 문서화 |
| R-2 | **MAJOR** | 신규(P-1 범위, 이전 버전에도 있었음) | `misc.py`: `오늘 점심 <이름>이랑 김밥 먹었어` 왕복 | 음식명 보존 | 124개 중 **8개 실패**: `떡볶이랑→떡볶`, `라볶이→라볶`, `삼겹살구이→삼겹살구`, `갈치구이/꽁치구이/조기구이/옥수수구이→…구`, `오이소박이→오이소박`. 모음으로 끝나는 '…이' 음식에서 `이랑`을 먼저 경계로 자름. 결과는 매칭 실패 → kcal 미상 | 경계 분리 시 사전 우선: `X이`가 사전에 있으면 `랑`에서 자르기. 모든 이름·별칭에 대해 `랑/이랑/하고/에/은/는` 왕복 테스트 추가 |
| R-4 | **MAJOR** | REGRESSION(N-4) | `demo_win.py`, `api2.py` | 합격 기준 "공식 행 > DEMO" | 공개 행의 일반 별칭(`~`)은 후보로만 나오지만, DEMO CSV의 별칭은 일반어로 표시되지 않아 **12개 단어가 DEMO 행으로 자동 확정**: 계란·달걀·계란후라이·된장국·국·샐러드·야채샐러드·닭가슴살·rice·steamed rice·egg·fried egg. 예: `rice 200g` → DEMO-RICE 300 kcal(공개 쌀밥은 332), `계란 2개` → DEMO-EGG. 기본 `NUTRITION_CSV`가 public+demo라 기본 설정에서 발생. 이전 버전에서는 `계란`이 공개 `달걀(생것)`으로 매칭됨 | 공개 행 후보가 있으면 DEMO 행은 자동 확정하지 않기(또는 DEMO 별칭에도 같은 일반어 규칙 적용). 기본 NUTRITION_CSV에서 demo 제외 검토. 회귀 테스트: 모든 별칭에 대해 "exact가 DEMO이면 non-DEMO 후보 없음" |
| R-3 | MINOR | REGRESSION(P-2 되묻기 확대) | `parser_api.py`: `아까 점심 김밥 먹었어`, `방금 간식 바나나 먹었어` | 오늘(당일 표현) | "'아까' 날짜 표현을 이해하지 못했습니다" 되묻기. 그 밖의 정상 문장 34개(오늘/어제/그저께/N일/M월 D일/한글 수사/어젯밤/자정 00:30/1월 2일의 12월 31일 등)는 되묻지 않음 | `아까/방금/조금 전/좀 전`은 오늘(`relative`, 확인 화면에 날짜 표시)로 처리 |
| R-5 | MINOR | 신규 | `stale_rows.py`: 이전 번들로 시드된 DB → 새 번들로 재시드 | 철회된 행 제거 또는 비활성화 | upsert만 하므로 철회된 66행이 남음. `부대찌개` → MFDS-D-049 123 kcal `mirror_cross_checked`, 전체 190행. 이전 브랜치 DB나 향후 번들 갱신 때 모순값이 계속 쓰임 | 같은 CSV 출처(source_detail/파일 키)에서 사라진 id는 `withdrawn` 표시 후 매칭에서 제외 |
| R-6 | MINOR | 신규 | `parser_api.py` | 흔한 표현 처리 | `우유 한 잔 마셨어` → `우유  마셨어`, `커피 마셨어`, `회사에서 김밥`, `김밥이었어`가 매칭 안 됨. `어제 밤에 라면` → 끼니 되묻기 + `밤에 라면` | `마셨어/마심/이었어/였어` 제거, `…에서` 장소어 제거, `밤(에)` → 저녁/야식 되묻기 선택지 |
| R-7 | MINOR | 신규(N-1/N-2의 대가) | `nutrition_lookup.HUD_PRIORITY` | HUD 우선 목록 24개가 모두 있음 | 깍두기·제육볶음·소불고기·고등어구이가 번들에서 빠져 목록이 조용히 20개로 줄어듦. 반찬류 핵심 항목이 사라짐 | 목록 갱신, 또는 공식 파일 임포트 안내를 HUD 문구/문서에 추가. 테스트로 목록과 번들 일치 확인 |
| R-8 | MINOR | 신규(X-3 설계) | `recheck_x.py` R4: 유효한 수정 1건 + `abc` 셀 1건 | 문제 행만 보류 | 셀 하나 때문에 **전체** 반영과 export가 보류됨(설계대로). Excel 파일 자체에는 아무 표시가 없어, 사용자는 관리 화면을 열기 전까지 Excel이 오래된 값이라는 것을 모름 | HUD 재고 화면에 sync state 배지 표시, 또는 문서에 운영 절차 명시. 문제 행만 제외한 부분 자동 반영 옵션도 검토 |
| R-9 | MINOR | 신규(기존 코드) | `misc.py`: `.~lock.inventory.xlsx#` 생성 | LibreOffice로 열린 파일도 잠금으로 인식 | `lock_file_present=False` → 열려 있는 동안에도 export가 파일을 교체. 저장 시 옛 export_id → R-1과 겹치면 blocked | LibreOffice 잠금 패턴 `.~lock.<name>#` 추가 |
| R-10 | NIT | 신규 | `diary.ink switchCandidate` | — | `list` 확인 시점에 첫 저장 요청이 아직 진행 중이면 새 key로 두 번째 저장이 가능(중복 1건) | `attempted` 중에는 응답을 받을 때까지 후보 변경 비활성화 |
| R-11 | NIT | 신규 | 브랜치 이전 버전 DB | — | `excel_exports.snapshot_json` 구 스키마 DB는 export마다 `status=error`(03에서 "재생성" 안내). 마이그레이션 없음 | 미배포라 수용. 시작 시 감지해서 명확한 오류 문구로 |

## 5. 새 번들 무작위 15행 대조 (`random.seed(777)`, 독립 파서 `verify_nutri.py`)

값 순서는 kcal / 탄수 / 단백 / 지방(/100). 미러 커밋은 02와 같습니다.

| # | 식품명 | 번들 값 | 미러 원본 값 | 일치 |
|---|---|---|---|---|
| 1 | 설렁탕 | 24/0.4/4.3/0.6, serv 500 g, D105-231000000-0001 | toad·carb·kang(3행 중 1) 동일, HL 24/0.36/4.26/0.58 같은 코드 | 일치 |
| 2 | 소갈비찜 | 값 없음, 100ml, 750 mL | toad 111 100ml·carb 111·kang 111(그 밖의 행은 basis 미상) | 일치 |
| 3 | 라볶이 | 134/20.1/2.8/4.7, serv 200 | toad·carb 동일, kang 3행 중 1 | 일치 |
| 4 | 파김치 | 49/8.5/2.5/0.6 | toad·kang·carb 동일 | 일치 |
| 5 | 황태해장국 | 30/0.9/4.1/1.1, D305-258000000-0001 | toad·carb 동일, kang C 1.0, HL 30/0.95/4.08/1.13 | 일치 |
| 6 | 배 | 45/12.2/0.3/0, RDA | toad R "배, 생것" 동일 | 일치(단일) |
| 7 | 우동 | 값 없음, 100ml, 800 mL | toad 71 100ml·carb 71·kang 4행 중 1 | 일치 |
| 8 | 두부달걀탕 | 값 없음, 100ml, 320 mL | toad 45 100ml·carb·kang 동일 | 일치 |
| 9 | 카페라떼 | 값 없음, 100ml, 355 mL | toad 38 100ml·carb·kang 동일 | 일치 |
| 10 | 김밥 | 140/20/4.8/4.5, D101-007000000-0001 | toad·carb 동일, HL 140/19.98/4.84/4.55 | 일치 |
| 11 | 당근 | 33/7.7/0.8/0.2, RDA | toad R "당근, 뿌리, 생것" 동일 | 일치(단일) |
| 12 | 브로콜리(데친것) | 26/4.5/3.2/0.2, RDA | toad R 동일 | 일치(단일) |
| 13 | 녹두전 | 값 없음, 100ml, 158.9 mL | toad 92 100ml·carb·kang 동일 | 일치 |
| 14 | 두부조림 | 143/4.4/9.6/9.7, 당3.6 Na161, D111-517000000-0001 | **toad는 142/100ml(다른 행)**, carb 143 동일, HL 143/4.4/9.64/9.66 같은 코드 | 일치(대표행 선택 정상) |
| 15 | 총각김치 | 42/7.9/1.9/0.3 | toad·kang·carb 동일 | 일치 |

결과: 15/15 일치. 전체 스캔(`disagree2.py`)에서도 값이 있는 93행 모두 불일치 0입니다.
