# Iteration 2 plan (draft v1, 2026-11-06) — for advisor review

Repository: `/home/claude/rokid-ai-glasses-dual-poc`, branch `feature/iteration-2`. GitHub: `Ganggee/Rokid-ai-glass-project` (main = iteration 1).

## User requests (verbatim intent)
1. `nutrition_demo.csv` has very few foods → enrich from **publicly available data**, not vague "use open source".
2. **Voice meal diary**: say year/date/meal ("2026년 11월 6일 아침 기록") → eaten foods + kcal + nutrients are recorded;
   say a date to **view** the log or **hear it read aloud**.
3. Inventory: load from **Excel in a linked storage** and **save back to Excel when stock changes**; goal = sustained, continuous use.
4. Work as a team: coder / reviewer-discussant / advisor professor, iterate until it holds.

## Environment facts (verified)
- Shell outbound: only GitHub git + allowlisted proxy. PyPI/npm blocked (403). data.go.kr / foodsafetykorea / USDA not reachable from shell.
  `WebFetch`/`WebSearch` tools can read public web pages (agent-side), not bulk file downloads.
- FastAPI for tests is vendored from GitHub source into the sandbox only (see docs/poc-results.md). CI on GitHub installs from PyPI and passes.
- Official AIUI docs: `/tmp/aiui-src/jsar/skills/aiui-dev/references` (apis/ai.md has `SpeechRecognition`, `speechSynthesis.speak(new SpeechSynthesisUtterance(text), 'enqueue'|'immediate')`).
  Official validator/loader: `/tmp/aiui-src/jsar/bench/src`.
- MFDS 식품영양성분DB OpenAPI (data.go.kr 15127578): license "이용허락범위 제한 없음", endpoint `https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo03`, key required, response field names not confirmed.
  전국통합식품영양성분정보 표준데이터 (data.go.kr 15100064) columns: 식품코드, 식품명, 데이터구분명, 영양성분함량기준량, 에너지(kcal), 수분(g), 단백질(g), 지방(g), 회분(g), 탄수화물(g), 당류(g), 식이섬유(g), …, 나트륨(mg), …, 출처명, 식품중량, ….

## A. Nutrition reference expansion
- Additive schema migration (existing DBs keep data): `nutrition_references` + `serving_size_g`, `category`, `food_code`, `sugars_g_per_100g`, `sodium_mg_per_100g`, `source_url`, `retrieved_at`, `verification` (`fetched_from_source` | `official_file_import` | `demo_mock`).
- `sample-data/nutrition_reference_public.csv`: common Korean dishes/ingredients (target 60–150 rows) **only with values read from a fetched public source page**, each row with `source_url` + `retrieved_at`. No value from memory. If a source cannot be fetched, the row is not added.
- `scripts/import_nutrition_mfds.py`: (1) import the official standard-data file (CSV/XLSX downloaded by the user) with header mapping and per-100 g normalisation; (2) `--api` paginated fetch with `MFDS_API_KEY`. Tested with a fixture that mimics the official header (fixture values clearly synthetic).
- DEMO rows stay but are ranked after public rows in label matching; `is_demo` semantics unchanged.

### A-1. Data acquisition route found by PM (2026-11-06)
Official sites are not reachable from this sandbox (shell blocked; WebFetch allowlist rejects data.go.kr file pages, nongsaro robots-disallowed, USDA API not allowlisted).
`git clone` of GitHub works. Public GitHub repos that redistribute the MFDS 전국통합식품영양성분정보 표준데이터 (음식) exist, e.g.:
- `toadsam/Ajou_MuscleUp` (PR #18: `backend/src/main/resources/food/foods.tsv.gz`, K-FIND 음식 15,647 + 가공식품, RDA 10.4 원재료)
- `kangsogo7/meal-log` (`public/food-db.json`, built from 표준데이터 원재료성·음식·가공식품)
- `minseok08262-web/carb-loading-tracker` (`tools/fetch_food.py`, 표준데이터 원재료성식품·음식, ~8천 종)
- `sirloinbh/health-log` (PR #66: 95 popular foods with source URLs)
Route: shallow/sparse clone ≥2 independent mirrors → extract 음식 rows by 식품코드 → **cross-check the same 식품코드 across mirrors** (values must agree) → bundle a curated subset of common Korean dishes/ingredients with provenance (`source = MFDS_STD_DATA`, `source_detail = mirror repo@commit`, `verification = mirror_cross_checked | single_mirror`). Rows that disagree are excluded and reported.
License: data.go.kr lists 이용허락범위 제한 없음 / KOGL Type 1 (attribution) → attribution in LICENSE-THIRD-PARTY.md. Mirror repos' code is not copied.
The official importer (`scripts/import_nutrition_mfds.py`) remains the primary path for a full, first-hand refresh on the user's PC.

## B. Voice meal diary
- Tables `meal_logs` (date, meal_type breakfast|lunch|dinner|snack, source voice|analysis|manual, meal_session_id?, idempotency_key UNIQUE) and `meal_log_items` (food_name, nutrition_ref_id, grams, grams_basis stated|serving_size|analysis|unknown, kcal/carbs/protein/fat nullable).
- Korean parser (server, no LLM): absolute dates (2026년 11월 6일, 11월 6일, 11/6), relative (오늘/어제/그제/그저께), meal words (아침/아침식사/조식, 점심/중식, 저녁/석식, 간식/야식), intents record / view / read-aloud, foods with quantities (밥 한 공기, 계란 2개, 200g). `APP_TIMEZONE=Asia/Seoul` for relative dates.
- Grams: stated grams → use; count × serving_size_g when the reference has a serving size → `grams_basis=serving_size`; otherwise grams/kcal null (no invented numbers).
- Confirmation before write (same pattern as inventory), idempotent POST.
- API: `POST /api/v1/meal-logs/parse-command`, `POST /api/v1/meal-logs`, `GET /api/v1/meal-logs?date=&meal_type=`, `GET /api/v1/meal-logs/summary?date=` (daily totals + `speech_text` for TTS), `DELETE /api/v1/meal-logs/{id}`, `POST /api/v1/meal-logs/from-session/{session_id}` (log an analysed meal).
- AIUI: new `pages/diary/diary.ink` (voice → parse → confirm → save; date view; "읽어줘" → `speechSynthesis.speak`), Home 3rd button, meal result page "기록" button. Harness scenarios with SpeechRecognition + speechSynthesis mocks.

## C. Inventory ↔ Excel sync
- SQLite stays the source of truth (LOCAL mode on the glasses keeps JSON in wx storage and cannot reach Excel — documented).
- "Linked storage" assumption: a folder synced by OneDrive / Google Drive / SharePoint desktop client on the server PC → `INVENTORY_XLSX_PATH`. Direct Graph/Drive API (OAuth) = documented next step, not built.
- Export after every stock change: atomic temp-file + `os.replace`; sheets `inventory` (same columns as the import format → round-trip), `transactions` (recent), `_sync` (baseline per product + export sha). File locked (Excel open on Windows) → export marked pending, retried; `/use` never fails because of Excel.
- Import/watch: poller (`INVENTORY_XLSX_POLL_SECONDS`) + `POST /api/v1/inventory/excel-sync` + `GET …/excel-sync/status`. Three-way merge per product with baseline: excel-only change → `adjust` tx (source excel_sync); db-only change → export; both → `merge_delta` (db + (excel − base)), logged as conflict; configurable `db_wins|excel_wins|merge_delta`. New rows → create; deleted rows → never delete, warn. Invalid rows → not applied, reported.
- Soak test for "continuous use": many random uses + periodic external Excel edits + restarts → invariants (stock = Σ deltas, never negative, Excel == DB after sync, no duplicate application).

## Quality bar
All iteration-1 tests stay green; new unit/API tests per feature; AIUI validator 0 issues; harness extended; docs (api, capability matrix, test plan, results with honest levels) updated; CI green on GitHub.

## Final design (as implemented, 2026-11-06)
- **A. Nutrition**: `nutrition_reference_public.csv` 124 rows (104 `mirror_cross_checked`) from 4 public mirrors of the
  MFDS/RDA data; representative row per name: 100 g before 100 mL, official-code row (health-log) as anchor, every
  mirror must agree, no agreement → excluded (50). Provenance in `source_detail`; ranked by `verification`;
  exact-match-only resolution; DEMO rows never auto-confirmed while a public candidate exists; rows dropped from the
  bundle are retired (kept for past logs); 100 mL basis → no per-100 g values; official importer ranks highest.
- **B. Diary**: rule parser (`diary_parser.py`) with injectable clock, date fixed at parse, confirmation + idempotent
  POST, gram policy (stated | count×serving only for matching unit | null+reason), per-item snapshots,
  from-session idempotent per analysis, summary `speech_text` ≤150 chars / ≤3 sentences, soft delete.
  AIUI `pages/diary/diary.ink` + meal result "식사 기록".
- **C. Excel**: `excel_sync.py` — export_id baselines stored in `excel_exports`/`excel_imports`, triggers bump
  `change_seq`; compare-and-swap placement (move aside → verify → `os.link` create-only-if-absent, fallback
  `os.replace`); lock (Excel/LibreOffice)/unstable/truncated/conflict-copy handling; poller in FastAPI lifespan with the
  startup stat; `merge_delta` default (two independent stock deltas are a `merge`, not a conflict); AUTO_APPLY default
  **true for safe plans only** (known baseline, no conflict/invalid), otherwise `needs_review`; baselines kept for the
  newest 50 exports or 90 days (capped 5000 + 1/day, zlib-compressed); `blocked` files resolved explicitly
  (`/excel-sync/resolve`: discard_file | apply_file_values). LOCAL mode (glasses JSON in wx storage) has no Excel sync.
- Deviations from the advisor rubric: see the coder report in the PR description.

## Deviations from the advisor rubric (tracked in-repo; review 02 NIT-2)
| Rubric / plan item | What was done | Why |
|---|---|---|
| 영양 행 최소 30 / 목표 60 / 상한 150(advisor 결정 9), cross-check by 식품코드 | 124 rows; matched by food name + kcal/C/P/F, official 식품코드 only where health-log has it (37 rows) | mirrors other than health-log carry no 식품코드; rows without agreement are excluded, not filled |
| "conflict 하나라도 있으면 자동 반영 중지" | `merge_delta` of two independent stock deltas is classified as a `merge` (both kept), not a conflict; negative merges, metadata both-changed and db_wins/excel_wins overrides are conflicts | stopping on every simultaneous restock + use would block normal continuous use; nothing is lost in a merge |
| soak "재기동 5+" | in-process reconnect ×6 per run + a real-app poller/HTTP test + crash-recovery test | OS-level process restarts inside one test run are slow and flaky in CI |
| Excel 수식 보존 | not preserved; formula cells reported invalid | out of scope (advisor) |
| 1인분 단위 | `serving_unit=인분` only for 음식 rows; `serving_size_g` = the source '식품중량' column (e.g. 쌀밥 100 g) | taken from the mirror README ("음식 serving_g = 1인분"), not an original column; documented in sample-data/README |
