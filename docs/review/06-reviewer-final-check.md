# 06 — 토의자 최종 확인 (Round 2, 2026-11-06)

**대상**: `feature/iteration-2` @ `08c1e84`. Round 2 커밋은 `5155de9`, `7ebe2dc`, `eef009b`, `08c1e84`입니다.

**범위**(코디네이터 지시에 따라 좁힘):
- 지도교수 merge 조건 M-1~M-4
- review 04의 R-1, R-2, R-4
- pytest, 하네스
- 새 BLOCKER/MAJOR 여부

**방법**: 코드는 수정하지 않았습니다. 스크립트는 모두 `/tmp/review/`에 있습니다. M-1은 지도교수의 `/tmp/advisor/*` 스크립트를 쓰지 않고, 직접 작성한 훅과 스레드 경합으로 재현했습니다.

## 판정: **MERGE OK**

- M-1~M-4와 R-1·R-2·R-4가 모두 해결됐습니다.
- 새 BLOCKER/MAJOR는 없습니다.
- 남은 MINOR/NIT(§4)는 다음 iteration으로 넘겨도 됩니다.

## 1. 실행 결과

| 명령 | 결과 |
|---|---|
| `python3 -m pytest -q` | **213 passed** in 39.75 s |
| `node aiui-agent/tests/run-aiui-checks.mjs --aiui-repo /tmp/aiui-src/jsar --with-server` | **24/24 passed**, exit 0 |

## 2. 지도교수 조건 M-1~M-4

### M-1 / F-1 (내보내는 중 사람의 저장이 사라짐): **VERIFIED**

새 구현 `_place()`의 동작:
1. 현재 파일을 옆(aside)으로 옮깁니다.
2. 옮긴 파일의 sha를 확인합니다. 마지막 export이거나 이미 병합한 내용일 때만 덮어씁니다.
3. 새 파일을 `os.link`로 놓습니다. 이 방식은 경로에 파일이 없을 때만 생성되므로, 그사이 들어온 저장을 덮어쓰지 않습니다.

**결정적 재현** (`/tmp/review/f1_hooks.py`): /use 1회 뒤 sync를 돌리면서, 사람이 H에 +10을 저장하는 시점을 단계마다 끼워 넣었습니다.

| 끼워 넣은 시점 | 결과 |
|---|---|
| 임시 workbook을 쓴 직후 원자적 저장 | `deferred_changed` → `up_to_date`. DB H 15→25, Excel 25. 이벤트 `export_deferred_external_change` |
| 파일을 옆으로 옮긴 순간 원자적 저장 | 동일. 15→25 유지 |
| 옆으로 옮긴 순간 제자리 저장(경로에 새 파일 생성) | 동일. 15→25 유지 |
| 저장 2회가 겹침 | 15→35(두 수정 모두 반영). 오래된 쪽은 `inventory (sync-conflict …).xlsx`로 남고 status `conflict_copies`에 표시 |
| 하드 링크 미지원(`os.link` OSError) + 쓰는 중 저장 | `deferred_changed` → 15→25 유지 |

**확률적 재현** (`/tmp/review/f1_race.py`): 실제 앱(lifespan poller 0.05 s), /use 0.02 s 간격 스레드, 한글 파일명. 사람 수정 20회 × 4회 실행.

| 저장 방식 | 결과 |
|---|---|
| 원자적 저장(seed 1, 2) | **20/20, 20/20 반영** |
| 제자리 저장(seed 1, 2) | **20/20, 20/20 반영** |

모든 실행이 state `ok`, `cas_mode=link`, 충돌 사본 0개로 끝났습니다. 수정 전 지도교수 측정은 150 중 40 반영이었습니다.

**잔여**(아래 S-1): 파일을 export **이전부터** 열어 둔 채 그 핸들로 제자리 쓰기를 하고, 그 쓰기가 sha 확인 직후 몇 ms 안에 일어나면 수정이 사라집니다. 재현은 됐지만 조건이 매우 좁습니다. Windows에서는 열린 파일의 rename이 실패해 `pending_locked`가 되므로 해당하지 않고, Excel과 동기화 클라이언트는 임시 파일 + rename 방식으로 저장합니다. 그래서 MINOR로 봅니다.

### M-2 / R-4 (DEMO 자동 확정): **VERIFIED**
- `/tmp/review/demo_win.py`: 공개 후보가 있는데도 DEMO로 자동 확정되는 단어가 **0개**입니다(이전 12개).
- `계란 2개`, `rice 200g`, `된장국`은 자동 확정 없이 후보로만 나옵니다. 저장해도 DEMO 값이 들어가지 않습니다.

### M-3 / R-2 (음식명 잘림 + 엊저녁): **VERIFIED**
- `/tmp/review/misc.py`: `오늘 점심 <이름>(이)랑 김밥 먹었어` 왕복 실패 **0/124**(이전 8개).
- `떡볶이 랑 김밥`, `김치찌개 하고 …`, `갈치구이랑 …`, `고등어구이랑 …`이 모두 이름을 보존합니다.
- `엊저녁 김밥` → 2026-11-05 dinner. `엊그저께` → 되묻기.
- 정상 문장 34개 회귀 스캔: 되묻는 것은 `어제 밤에 라면` 1건뿐이고, 이는 의도된 "저녁/야식" 질문입니다. `아까`·`방금`은 오늘로 처리되고(R-3 해결), `마셨어`·`회사에서`·`이었어`도 처리됩니다.

### M-4 (문서): **VERIFIED**
- 낡은 문구 grep 결과 0건: `AUTO_APPLY=false(기본)`, `65행`, `165행`, `150~400`.
- 반영 확인:
  - troubleshooting: 기본값 true로 정정
  - sample-data/README: 머리말 모순 해소, "처음 연결하기", 오래된 사본·복구, 1인분 = 식품중량(쌀밥 100 g)
  - plan Deviations: "최소 30 / 목표 60 / 상한 150"
  - aiui-studio-deploy: 일지·분석·Excel = SERVER 모드 전용

## 3. 토의자 이슈 R-1, R-2, R-4

| ID | 판정 | 근거 |
|---|---|---|
| R-1 | **VERIFIED** | `recheck_x.py` R3: 60회 export보다 오래된 사본에 H=999를 저장 → `merged_and_exported`, H 115→1099(병합 산술 정확), 이후 정상 export. 보관은 90일 창이고 스냅숏은 zlib 압축됩니다. 200제품 × 300 export에서 1.7 MB 증가(약 5.8 KB/회), 상한 5000이면 수십 MB 수준입니다. `blocked`가 되면 `/excel-sync/resolve`로 처리합니다: 확인 없음 → 400, 토큰 없음 → 401, `discard_file`은 백업(`…/excel_backups/inventory-discarded-….xlsx`) 뒤 다시 export, `apply_file_values`는 dry-run 미리보기에서 파일을 바꾸지 않음 |
| R-2 | **VERIFIED** | §2 M-3 |
| R-4 | **VERIFIED** | §2 M-2 |

review 02 회귀 재실행(`recheck_x.py` R2, R4~R8): X-1 경로(dry-run invalid → auto `needs_review` → 수동 apply `ok_with_rejected_rows` → 다음 export 정상), dry-run DB 불변, 안전 병합, 음수 병합 `needs_review`가 모두 이전과 같습니다. LibreOffice 잠금(R-9)은 이제 감지됩니다.

## 4. 새 이슈 (BLOCKER/MAJOR 없음)

| ID | 심각도 | 내용 | 제안 |
|---|---|---|---|
| S-1 | MINOR | F-1 잔여 창: export 전부터 열려 있던 핸들로 하는 제자리 쓰기(sha 확인 직후 몇 ms 안). `f1_hooks.py` case 6에서 수정 손실 재현 | 문서에 잔여 창을 명시. 필요하면 링크 직전에 aside의 stat(mtime/size)을 다시 확인 |
| S-2 | MINOR(NOT VERIFIED) | CAS 동안 경로에서 파일이 잠깐 **없어집니다**(aside rename ~ link). OneDrive/Drive 클라이언트가 이를 삭제로 동기화할 가능성, 그리고 OneDrive 폴더에서 하드 링크가 동작하는지는 실제 클라이언트로 확인되지 않았습니다 | X1~X5 실기 시험 항목에 "export 중 다른 PC에 삭제가 전파되지 않는지", `cas_mode` 기록을 추가 |
| S-3 | NIT | `공깃밥`(표준 표기)이 매칭되지 않음. 별칭은 `공기밥`만 있음 | 별칭 추가 |
| S-4 | NIT | 제외된 50개 음식(달걀말이·고등어구이·국밥 등)은 후보도 없이 "미상"입니다. PM이 승인한 대가이며, 공식 파일 임포트로 채워집니다 | 다음 iteration |
