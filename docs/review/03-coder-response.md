# 03 — 코더 응답 (review 02 조치 내역, 2026-11-06)

대상 브랜치: `feature/iteration-2`. 원칙: 이슈마다 재현 테스트를 먼저 추가하고, 실패를 확인한 다음 고쳤습니다.
- Excel 11건: 수정 전 실행 결과 `11 failed, 17 passed`.
- 파서 표: `29 failed`.
- 영양 테스트: `5 failed`.
- A-1 하네스 시나리오: 이전 `diary.ink`로 돌리면 FAIL (`네트워크 오류`).

## 조치 표

| ID | 심각도 | 판정 | 조치 | 커밋 | 테스트 |
|---|---|---|---|---|---|
| X-1 | BLOCKER | **FIXED** | 계획 단계에서 바코드/QR이 다른 제품 것과 겹치면(신규 행·메타데이터 변경) 그 행을 invalid로 분류합니다. dry-run은 apply를 실제로 실행한 뒤 ROLLBACK해서 DB 거부도 미리보기에 그대로 보여 줍니다. 적용 단계에서는 행마다 SAVEPOINT를 걸어, DB 제약 위반이 나면 그 행만 되돌리고 invalid로 보고한 뒤 나머지 동기화와 내보내기를 계속합니다. 예상하지 못한 예외는 `status=error` + `last_error`로 남기고 `ok`/`up_to_date`로 표시하지 않습니다. status에 `state` 필드를 추가했습니다 | `0f86e0a` | `test_x1_new_row_with_duplicate_barcode_is_invalid_and_sync_continues`, `test_x1_any_db_constraint_error_becomes_row_invalid`, `test_x1_unexpected_error_is_reported_not_up_to_date`, `test_x1_duplicate_barcode_api_no_500`; soak에 `pid_typo` 수정 추가 |
| N-1 | MAJOR | **FIXED** | 대표 행 선정 규칙을 PM 결정 ①~⑤대로 바꿨습니다(`select()`). 결과: 124행(교차검증 104, 단일 20), 공식코드 행 기준 37행, **합의 없음으로 제외 50건**(report.json에 후보 수·거부 사유 기록). 기준이 다른 행의 투표 처리는 "해석" 항목 참고 | `d98111a` | `test_n1_rows_contradicting_official_code_rows_are_not_bundled`(부대찌개·추어탕·소불고기·깍두기·햄버거·볶음밥·순대), `test_n1_report_lists_exclusions_and_cross_check_meaning`, `test_n1_select_rules_unit` |
| N-2 | MAJOR | **FIXED** | 100 g 행을 100 mL 행보다 우선합니다. 현미밥 172, 잡곡밥 146, 비빔밥 142, 라면 82, 짬뽕 58, 멸치볶음 276, 삼계탕 101(모두 100 g, 공식코드 기준). poc-results 한계 2를 사실대로 고쳤습니다(1차 미러의 이름당 1행 중복 제거가 원인) | `d98111a` | `test_n2_staples_have_100g_values` |
| N-3 | MAJOR | **FIXED** | 기준이 100 mL인 행은 1인분을 `serving_size_ml`로만 둡니다(`serving_size_g` 비움, 검증기가 강제). 일지는 `volume_ml`을 쓰고 g·kcal은 null, `null_reason=volume_basis`입니다. HUD와 표시 줄은 `mL`로 표기합니다 | `d98111a` | `test_n3_ml_basis_rows_keep_serving_in_ml_only`, `test_n3_ml_serving_is_never_shown_or_computed_as_grams`, `test_gram_policy` |
| P-1 | MAJOR | **FIXED** | 조사는 단어 끝에서만, 제거한 결과가 영양 사전(이름+별칭)에 있을 때만 제거합니다. 사전은 서버가 넘깁니다. `랑/이랑/하고`는 항목 경계로 처리합니다. 사전이 없을 때는 단어를 자르지 않습니다 | `00e9211` | `test_p1_particles_only_at_word_end_and_only_into_dictionary_words`(10건: 브로콜리·포도·로제떡볶이·김치·버섯·은갈치구이·김치찌개에 밥 등), `test_p1_without_dictionary_nothing_is_cut_inside_words` |
| P-2 | MAJOR | **FIXED** | 처리하는 표현: 지난달·저번 달·이번 달·다음달 + N일, 작년·지난해·재작년·올해·내년 + M월 D일, N일 전, 어젯밤. 그 밖의 날짜 조각(저번 주, 2주 전, 며칠 전, 요일 등)이 남아 있으면 되묻습니다(오늘로 기본 저장하지 않음). 날짜 조각이 음식명에 섞이지 않게 했습니다 | `00e9211` | `test_p2_relative_month_year_or_ask_never_silent_today`(15건) |
| D-1 | MAJOR | **FIXED** | 기준표로 계산한 kcal은 g를 직접 말했어도 항상 `is_estimate=true`입니다. speech_text, 표시 줄, HUD에 '추정'을 붙이고 "입력값" 문구는 없앴습니다 | `d98111a` | `test_d1_stated_grams_day_speech_says_estimate`, `test_gram_policy` |
| X-2 | MAJOR | **FIXED** | 스냅숏은 내보내기에 성공했을 때만 남깁니다(실패하면 행 삭제). 내용 해시로 중복을 없앴습니다(`excel_snapshots`). 보존 범위는 최근 50개(`KEEP_EXPORTS`)와 파일에 적힌 export_id입니다. imports는 export당 5건, events는 2000건까지 둡니다 | `0f86e0a` | `test_x2_snapshot_retention_bounded`, `test_x2_identical_content_shares_snapshot`; soak에서 행 수 상한 확인(seed 3개 모두 exports/snapshots 최대 50) |
| X-3 | MAJOR | **FIXED** | `AUTO_APPLY` 기본값을 true로 바꾸되 안전한 계획(`is_safe`: 기준 있음, conflict·invalid 없음)만 자동 반영합니다. 안전하지 않으면 `needs_review`가 되어 반영하지 않고 파일도 덮어쓰지 않으며, DB 변경은 pending으로 쌓였다가 해결되는 즉시 내보냅니다. `/admin/inventory-sync`(미리보기, invalid/conflict 목록, Apply, 이벤트) 화면을 추가했습니다. poll은 미설정·빈 값이면 30초이고 0은 명시적으로 넣었을 때만 끕니다. `.env.example`과 문서를 갱신했습니다 | `0f86e0a` | `test_x3_auto_apply_only_safe_changes_and_holds_export`, `test_x3_merge_delta_both_changed_is_safe_but_negative_is_not`, `test_x3_settings_defaults_and_admin_page` |
| P-3 | MINOR | **FIXED** | 날짜나 끼니와 음식이 함께 있으면 동사가 없어도 record로 봅니다(확인 단계는 그대로 거침) | `00e9211` | `test_p3_record_without_verb_when_date_meal_food_present` |
| P-4 | MINOR | **FIXED** | 끼니가 2개면 되묻습니다. `N 공기 반`은 N+0.5로 계산합니다. 정정 표현(아니다·말고)이 있으면 되묻습니다 | `00e9211` | `test_p4_multiple_meals_and_corrections_ask` |
| P-5 | MINOR | **PARTIAL** | today/yesterday/tomorrow와 영어 끼니·log를 처리합니다. 영어 문장 전체는 지원하지 않습니다(한국어 우선) | `00e9211` | `test_p5_english_today_yesterday` |
| N-4 | MINOR | **FIXED** | 일반어 별칭(`~된장국`, `~김`, `~계란`, `~고구마`, `~빵` 등 42개)은 후보로만 보여 줍니다. 정확히 일치하는 행이 있어도 후보 목록은 함께 내줍니다 | `d98111a` | `test_n4_generic_alias_is_candidate_only` |
| N-5 | MINOR | **FIXED** | 원재료 행은 `source=RDA_NFCDB_10.4`로 바꾸고 LICENSE에 농진청 출처표시를 넣었습니다. 당류·나트륨은 `micro_verification=single_mirror`로 표시합니다 | `d98111a`, 문서 커밋 | `test_public_rows_have_provenance_and_cross_check_majority` |
| N-6 | MINOR | **FIXED** | 인자 없이 실행하면 사용법을 출력하고 exit 2로 끝납니다. basis와 값·serving의 일관성 규칙을 추가했습니다(100ml → 값과 `serving_size_g` 비어야 함). `atwater_exempt`가 필요한 행은 없습니다 | `d98111a` | `test_n6_validator_without_args_is_usage_error_and_checks_basis` |
| M-1 | MINOR | **FIXED** | 마이그레이션 때 v1의 `is_demo=0`이면서 `demo_mock`인 행을 `legacy_api`로 보정합니다(DEMO보다 높은 순위, 검증기 허용 값) | `d98111a` | `test_m1_migration_keeps_legacy_non_demo_rows_ranked` |
| X-4 | MINOR | **FIXED** | 캐시값이 없는 수식은 `formula_without_cached_value`로 보고합니다. invalid 행은 row_missing 경고에서 뺍니다 | `0f86e0a` | `test_x4_formula_without_cache_is_invalid_not_row_missing` |
| X-5 | MINOR | **FIXED** | 서버가 직접 내보낸 파일의 stat을 `observed`에 기록해 `deferred_unstable`이 생기지 않게 했습니다 | `0f86e0a` | `test_x5_own_export_is_not_reported_unstable` |
| X-6 | MINOR | **PARTIAL** | soak의 수정 종류를 무작위화했습니다(재고·새 행·ID 오타·행 삭제·잘못된 값). 안전 자동 반영과 수동 반영을 섞고, 250회마다 불변식을 검사하고, 행 수 상한을 확인합니다. 실제 앱 테스트를 추가했습니다(lifespan poller 0.1초, 동시 HTTP /use 30회, Excel 수정 4회, 수렴 확인). OS 프로세스 재시작을 반복하는 soak는 하지 않았습니다(CI 시간과 불안정성 때문. 시작 시 복구는 기존 테스트로 확인) | `0f86e0a`, `e21c192` | `test_soak_small`, `test_x6_real_app_poller_with_concurrent_http_and_edits` |
| X-7 | MINOR | **FIXED** | 충돌 사본 판정을 ` (N)`, `-PC명`(대문자), Dropbox `(… conflicted copy …)`, `(충돌 …)` 패턴으로만 한정했습니다 | `0f86e0a` | `test_x7_only_sync_client_conflict_names` |
| A-1 | MINOR | **FIXED** | 저장 결과가 불확실한 상태에서 후보를 바꾸면 먼저 서버를 조회합니다. 이미 저장됐으면 그 기록을 보여 주고, 아니면 새 idempotency key를 발급합니다 | `00e9211` | 하네스 `DIARY: save response lost -> switch candidate -> server checked first, no 409, one log` |
| NIT-1 | NIT | **FIXED** | 별칭 중복을 제거했습니다(`dict.fromkeys`) | `d98111a` | 번들 CSV |
| NIT-2 | NIT | **FIXED** | `docs/iteration-2-plan.md`에 "Deviations" 표를 추가했습니다 | 문서 커밋 | — |

## 해석과 남긴 것

1. **N-1 ④ "비교 가능한 미러"의 해석.**
   - kangsogo7과 carb는 기준량(basis)을 저장하지 않습니다. 그래서 이 두 미러의 행은 basis를 알 수 없는 행으로 보고 모두 투표에 넣었습니다(보수적).
   - toadsam의 행처럼 basis가 100 mL로 알려진 행은 100 g 기준 행과 다른 MFDS 행이라 투표에서 뺐습니다.
   - 이 규칙 때문에 엄격해져서 50개가 제외됐습니다. 목표 행 수(150)를 채우지 않았습니다(PM ⑤ "값을 만들지 말 것").
2. **X-3 "conflict"의 범위.**
   - 양쪽 차분을 모두 보존하는 `merge_delta`(예: 안경에서 −1, Excel에서 +10 → +9)는 conflict가 아니라 `merges`로 분류했습니다.
   - 이것까지 멈추면 Excel을 열어 둔 채 사용하는 평상시에도 매번 관리 화면 확인이 필요해지기 때문입니다.
   - 음수가 되는 병합, 메타데이터를 양쪽에서 수정한 경우, db_wins/excel_wins 덮어쓰기는 conflict로 남아 자동 반영을 멈춥니다.
   - PM 결정과 다르면 `is_safe()` 한 곳만 바꾸면 됩니다.
3. **X-1 수동 Apply 뒤 오타 행.** 수동 Apply 뒤에는 오타 행(신규 생성이 거부된 행)이 다음 내보내기에서 사라집니다. 원래 제품 행은 복원되고, 거부 내역은 status와 이벤트에 남습니다. 자동 모드에서는 반영도 내보내기도 하지 않으므로 사람이 파일에서 바로 고칠 수 있습니다.
4. **브랜치 중 DB.** `excel_exports` 스키마가 바뀌었습니다(`snapshot_json` → `snapshot_sha`). iteration 2 브랜치에서 만든 개발용 DB는 다시 만들어야 합니다. main(v1) DB는 영향이 없습니다(마이그레이션 테스트로 확인).

## 재실행 결과 (수정 후)

| 명령 | 결과 |
|---|---|
| `python -m pytest -q` | **159 passed** |
| `node aiui-agent/tests/run-aiui-checks.mjs --aiui-repo /tmp/aiui-src/jsar --with-server` | **24/24**, validator issues 0 |
| `python scripts/validate_nutrition_csv.py …public.csv …demo.csv` | 124 / 6 rows, 0 failing; 인자 없음 → exit 2 |
| `python scripts/soak_inventory_excel.py --seed {2026,7,99} --uses 2000 --edits 60 --restarts 6` | 3/3 PASS. 각 36.1 / 35.0 / 36.6초. needs_review 32 / 18 / 17. exports·snapshots 최대 50, DB 약 0.87 MB |
| 실제 uvicorn + `scripts/smoke_test.py` (Excel 동기화 켬, 한글 파일명) | `RESULT PASS`, status `ok`·`up_to_date`, `/admin/inventory-sync` 200 |
| `/tmp/review/typo_api.py` | dry-run `preview`(invalid 1), apply `200 merged_and_exported`, status pending 없음 |
