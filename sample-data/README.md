# sample-data — DEMO only

All files here are **mock data** for the PoC. They are not company inventory and the nutrition values are not from the MFDS DB.

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

## nutrition_demo.csv
`source = DEMO_MOCK`, `is_demo = 1`. 파이프라인 시험용 임의값입니다. 실제 사용 전 MFDS OpenAPI(data.go.kr 15127578) 또는 검증된 표로 교체하세요.
