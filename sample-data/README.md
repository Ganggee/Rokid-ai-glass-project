# sample-data

- `inventory_demo.*`, `nutrition_demo.csv`: **DEMO mock data** for the PoC (not company inventory; `nutrition_demo.csv` values are invented, `is_demo=1`).
- `nutrition_reference_public.csv`: **public data** — MFDS 식품영양성분 DB / RDA 국가표준식품성분 DB values taken from public GitHub mirrors with provenance (see below). Not DEMO, but cross-checked mirrors, not first-hand official files.

## inventory_demo.csv / inventory_demo.xlsx — Excel column guide

| 필드 | 예시 | 규칙 | 자동 인식 헤더(별칭) |
|---|---|---|---|
| `product_id` | `CARE-SENS-AIR-SENSOR` | 필수, 파일 내 고유 | 제품ID, 제품코드, 품목코드, 품번, id, sku |
| `product_name` | `CareSens Air Sensor` | 필수 | 제품명, 품목명, 품명, name |
| `category` | `CGM_SENSOR` | 선택 | 분류, 카테고리, 품목구분 |
| `stock_qty` | `20` | 필수, 정수 ≥ 0 | 재고, 재고수량, 수량, 현재고, qty |
| `unit` | `ea` | 기본 `ea` | 단위 |
| `barcode` | `0880000000001` | 선택, **Excel에서 텍스트 서식**(앞자리 0 보존). 숫자 셀이면 경고 | 바코드, ean, gtin |
| `qr_value` | `CARE-SENS-AIR-SENSOR` | 선택. QR에 실제로 인코딩된 문자열과 **정확히 일치**해야 매칭(임의 파싱 없음) | qr, qr코드 |
| `lot_no` | `DEMO-LOT-A` | 선택 | lot, 로트, 로트번호, 제조번호 |
| `expiration_date` | `2027-12-31` | 선택, yyyy-mm-dd (Excel 날짜 셀 허용) | 유효기간, 사용기한, 만료일 |
| `location` | `Demo cabinet A` | 선택 | 위치, 보관위치 |
| `aliases` | `케어센스 센서;센서` | 선택, `;` 구분. 음성/텍스트 검색용 | 별칭, 검색어 |

헤더가 다르면 매핑 JSON을 사용합니다:
```json
{"product_id": "자재번호", "product_name": "자재명", "stock_qty": "가용재고"}
```
```powershell
python scripts\import_inventory.py sample-data\real\inventory.xlsx --mapping mapping.json            # 미리보기만
python scripts\import_inventory.py sample-data\real\inventory.xlsx --mapping mapping.json --mode seed --apply
```
`sample-data/real/` 은 `.gitignore` 대상입니다. 실제 회사 파일은 여기에만 두세요.

Import 모드: `seed`(신규만 생성, 기존 재고 유지 — 재수입 안전) · `adjust`(기존 재고를 파일 값으로 조정, `adjust` 이력 기록) · `metadata`(이름/코드/LOT만 갱신).

## Excel 동기화 (서버 SERVER 모드 전용)
안경 LOCAL 모드의 재고는 안경 저장소의 JSON이라 Excel과 연결되지 않습니다. Excel 연동은 서버(SQLite 정본)에서 합니다.
```powershell
# .env
INVENTORY_XLSX_PATH=C:\Users\<me>\OneDrive\Rokid\inventory.xlsx
INVENTORY_XLSX_POLL_SECONDS=30    # 비우면 30초, 0 = 백그라운드 동기화 명시적 끔
INVENTORY_XLSX_AUTO_APPLY=true     # 기본값. 안전한 수정만 자동 반영(알려진 기준, conflict·invalid 없음)
```
- 서버가 파일을 만들고, 재고가 바뀔 때마다 다시 씁니다. `inventory` 시트만 수정하세요(`transactions`는 읽기 전용, 숨김 `_sync` 시트는 지우지 마세요).
- 파일을 열어 둔 동안에는 내보내기가 대기(pending)했다가 닫으면 반영됩니다.
- 오래된 사본으로 덮어써도 그 사이의 안경 사용 기록은 되돌려지지 않습니다(export_id 기준 병합).
- 행을 지워도 제품은 삭제되지 않고 다음 내보내기에서 복원됩니다. 새 행은 새 제품으로 추가됩니다.
- 잘못된 셀(음수·소수·수식·다른 제품 바코드)이 있으면 자동 반영을 멈추고(`needs_review`) 파일을 덮어쓰지 않습니다. 브라우저에서 `http://<서버>/admin/inventory-sync`로 미리보기·Apply.
- 상태: `GET /api/v1/inventory/excel-sync/status`(사람이 읽는 `reason_text` 포함), 수동 반영: `POST /api/v1/inventory/excel-sync {"dry_run": false, "confirmed": true}`. 서버는 `--workers 1`로 실행하세요.
- 서버가 파일을 쓰는 순간 사람이 저장해도 그 저장본은 덮어쓰지 않습니다(현재 파일을 옆으로 옮겨 확인한 뒤 "없을 때만 생성"으로 새 파일을 놓음). 이 경우 상태는 `waiting`(`deferred_changed`)이 되고 다음 poll에 사람의 수정을 먼저 병합합니다. 하드 링크를 지원하지 않는 폴더(일부 가상 드라이브)에서는 `os.replace`로 대체하며 status의 `cas_mode=replace`로 표시됩니다(아주 짧은 경합 구간이 남음).
- 셀 하나라도 잘못되면 그 파일의 **모든** 자동 반영과 내보내기가 보류됩니다(설계: 사람의 다른 수정까지 덮어쓰지 않기 위해). 관리 화면에서 셀을 고치거나 유효한 행만 Apply하세요.

### 처음 연결하기 (기존 회사 Excel이 있을 때)
1. 기존 파일을 **먼저 가져오기**: `python scripts\import_inventory.py 기존재고.xlsx` (미리보기) → `--mode seed --apply`.
2. `.env`의 `INVENTORY_XLSX_PATH`에는 서버가 **새로 만들 파일 경로**를 지정합니다(예: `...\OneDrive\Rokid\inventory.xlsx`). 기존 파일 경로를 그대로 지정하면 서버가 만든 파일이 아니라서(`_sync` 시트 없음) `blocked`가 되고 아무것도 반영·덮어쓰지 않습니다.
3. 서버를 시작하면 새 파일이 만들어집니다. 이후로는 이 파일만 열어서 고치세요.

### 오래된 사본과 복구
- 병합 기준(스냅숏)은 **최근 50회 내보내기 또는 최근 90일 중 더 넓은 범위**(90일 안에서는 최대 5000개 + 하루 1개)를 보관합니다. 그 범위 안의 오래된 사본을 저장하면 사용 기록을 보존한 채 사람의 수정만 병합합니다.
- 범위를 벗어난 아주 오래된 사본(또는 `_sync` 시트를 지운 파일)은 `blocked`로 멈추고 파일을 덮어쓰지 않습니다. `/admin/inventory-sync`에서 둘 중 하나를 고르세요(모두 `confirmed` 필요):
  - **파일 수정 버리고 DB 값으로 다시 내보내기** (`POST /api/v1/inventory/excel-sync/resolve {"action":"discard_file","confirmed":true}`): 현재 파일은 `data/excel_backups/`에 백업됩니다.
  - **파일 값을 재고에 반영** (`{"action":"apply_file_values"}`): `dry_run:true`로 바뀔 값을 먼저 보여 줍니다. 파일의 값을 절대값으로 보고 차이를 `adjust` 이력으로 기록하므로, 그 파일 저장 이후의 사용 기록이 덮어써질 수 있습니다.
- LibreOffice로 열면 `.~lock.<파일명>#`, Excel이면 `~$<파일명>` 잠금 파일을 보고 저장을 미룹니다.

## nutrition_reference_public.csv (공개 데이터)
식약처 식품영양성분 데이터베이스(음식)와 농진청 국가표준식품성분 DB 10.4(원재료)를 재배포한 공개 GitHub 저장소 4곳에서 동명 행을 모두 모아 대표 행을 고른 124행입니다(규칙: 100 g 우선, 공식 식품코드 행이 있으면 그 행 기준, 모든 미러가 일치할 때만 `mirror_cross_checked`, 합의가 없으면 제외 — 50개 제외는 report.json). 각 행의 `source_detail`에 저장소@커밋, `verification`에 검증 등급이 있습니다. 100 mL 기준 행(31행)은 `serving_size_ml`만 있고 값은 비어 있습니다. **'1인분'(`serving_size_g`)은 원자료의 '식품중량' 열**입니다. 집에서 먹는 양과 다를 수 있습니다(예: 쌀밥 1인분 = 100 g = 166 kcal로 계산되어 보통 한 공기보다 작음). 확인 화면에 g가 표시되니 "밥 210그램"처럼 g로 말하면 그 값을 씁니다. 번들에서 빠진 행은 재시드 때 삭제하지 않고 `retired`로 표시해 과거 기록만 유지합니다. 재생성: `scripts/build_nutrition_reference.py`, 검증: `scripts/validate_nutrition_csv.py`. 공식 파일을 받으면 `scripts/import_nutrition_mfds.py --file …`로 1차 출처 값을 넣으세요(우선 적용). 출처표시: 식품의약품안전처 식품영양성분 데이터베이스.

## nutrition_demo.csv
`source = DEMO_MOCK`, `is_demo = 1`. 파이프라인 시험용 임의값입니다. 실제 사용 전 MFDS OpenAPI(data.go.kr 15127578) 또는 검증된 표로 교체하세요.
