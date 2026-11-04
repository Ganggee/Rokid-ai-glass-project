# API

Base: `http(s)://<host>:<port>` · OpenAPI UI: `/docs` · JSON spec: `/openapi.json`
Auth: every `/api/v1/*` call needs `Authorization: Bearer <API_TOKEN>`.

## Error schema
```json
{"error": {"code": "INSUFFICIENT_STOCK", "message": "Insufficient stock: 0 ea available, 1 requested.", "details": {"stock_qty": 0, "requested": 1}}}
```
| HTTP | code | 의미 |
|---|---|---|
| 401 | `UNAUTHORIZED` | 토큰 없음/불일치 |
| 422 | `VALIDATION_ERROR` | 요청 형식 오류 (`details.errors`) |
| 404 | `PRODUCT_NOT_FOUND`, `NOT_FOUND`, `ANALYSIS_NOT_FOUND` | 대상 없음 |
| 400 | `CONFIRMATION_REQUIRED` | `confirmed` ≠ true → **쓰기 없음** |
| 409 | `INSUFFICIENT_STOCK` | 음수 재고 방지 |
| 409 | `IDEMPOTENCY_KEY_REUSED` | 같은 키, 다른 내용 |
| 409 | `IMPORT_HAS_ERRORS`, `IMPORT_ALREADY_COMMITTED` | import 커밋 차단 |
| 409 | `BEFORE_PHOTO_REQUIRED`, `PHOTOS_REQUIRED` | 식사 단계 순서 |
| 413 / 415 | `PAYLOAD_TOO_LARGE` / `UNSUPPORTED_MEDIA_TYPE` | 업로드 제한 |

## Inventory (Task 1)
| Method | Path | 설명 |
|---|---|---|
| GET | `/health` | 공개. 상태·제품 수 |
| GET | `/api/v1/inventory/products?query=` | 이름/ID/별칭/분류/코드 검색 |
| GET | `/api/v1/inventory/products/{product_id}` | 단건 |
| POST | `/api/v1/inventory/use` | `{product_id, quantity, idempotency_key, confirmed, client_timestamp?, source?, note?}` → `{product, transaction, replayed}` |
| GET | `/api/v1/inventory/operations/{idempotency_key}` | `{applied, transaction, product}` — 네트워크 오류 후 재전송 대신 확인 |
| GET | `/api/v1/inventory/transactions?product_id=&limit=` | 이력(최신순) |
| POST | `/api/v1/inventory/resolve-code` | `{code, code_type: auto|qr|barcode}` → 정확 매칭만 |
| POST | `/api/v1/inventory/resolve-image` | 이미지(multipart `file` / `image/*` raw / `{image_base64}`) → `matched | candidates | unrecognized` + `evidence` |
| GET | `/api/v1/inventory/recognition-stats` | QR/바코드/OCR 결과 카운트(정확도 아님) |
| POST | `/api/v1/inventory/parse-command` | `{text}` → `{intent, product, quantity, requires_confirmation}` — **쓰기 없음** |
| POST | `/api/v1/inventory/import/preview` | multipart `file`(.csv/.xlsx), `column_mapping`(JSON), `sheet` → 검증 결과 + `batch_id` |
| POST | `/api/v1/inventory/import/commit` | `{batch_id, mode: seed|adjust|metadata, skip_invalid_rows}` |

예:
```powershell
$h = @{ Authorization = "Bearer $env:API_TOKEN" }
Invoke-RestMethod http://127.0.0.1:8000/api/v1/inventory/products -Headers $h
$body = @{ product_id="CARE-SENS-AIR-SENSOR"; quantity=1; idempotency_key=[guid]::NewGuid().ToString(); confirmed=$true } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/api/v1/inventory/use -Method Post -Headers $h -ContentType 'application/json' -Body $body
```

## Meals (Task 2)
| Method | Path | 설명 |
|---|---|---|
| POST | `/api/v1/meals/sessions` | `{note?}` → `{session_id}` (201) |
| GET | `/api/v1/meals/sessions` | 최근 세션 |
| POST | `/api/v1/meals/{id}/photos/before` | 사진 → `detected_regions[]`(라벨 없음), `label_options[]` |
| POST | `/api/v1/meals/{id}/photos/after` | 식전 사진 필요 |
| GET | `/api/v1/meals/{id}/photos/{before|after}` | 인증 필요, `no-store` |
| GET | `/api/v1/meals/{id}` | 상태, 사진 메타, items, 최신 분석 |
| POST | `/api/v1/meals/{id}/items` | `{items:[{label, nutrition_ref_id?, initial_serving_grams?, serving_source?: user|demo_assumption, before_region?, after_region?}]}` (전체 교체) |
| POST | `/api/v1/meals/{id}/analyze` | `{method: auto|manual|model}` |
| GET | `/api/v1/meals/{id}/results` | 최신 분석 |
| DELETE | `/api/v1/meals/{id}` | 세션·사진 삭제 |
| GET | `/api/v1/nutrition/search?q=&remote=` | 로컬 참조(100g당) + 선택 MFDS(미검증) |
| GET | `/api/v1/nutrition/references`, `/capabilities` | 참조 목록, OCR/모델/MFDS 상태 |
| GET | `/admin/meals` | PC 관리자 화면(수동 박스, 수동 업로드) |

Region: `{"type":"bbox","x":..,"y":..,"w":..,"h":..}` 또는 `{"type":"polygon","points":[[x,y],...]}` — 원본 사진 픽셀 좌표.

`analyze` 응답 `foods[]` 필드: `label, before_mask_area_px, after_mask_area_px, estimated_remaining_ratio, estimated_consumed_ratio, initial_serving_grams|null, estimated_consumed_grams|null, kcal|null, carbs_g|null, protein_g|null, fat_g|null, source, nutrition_ref_id, assumptions[], warnings[], analysis_method, is_demo`.
최상위: `analysis_id, analysis_method, requested_method, model_plugin, is_demo, confidence(low|medium), alignment, image_quality, warnings[], totals, totals_complete, disclaimer`.

## Schema (SQLite)
`products`, `product_codes`, `inventory_transactions`(append-only), `import_batches`, `recognition_events`, `meal_sessions`, `meal_images`, `meal_items`, `nutrition_references`, `meal_analyses`, `api_logs` — 정의: `backend/app/models.py`.
