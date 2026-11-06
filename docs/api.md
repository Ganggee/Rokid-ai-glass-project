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

## Meal diary (iteration 2)
| Method | Path | 설명 |
|---|---|---|
| POST | `/api/v1/meal-logs/parse-command` | `{text, now?}` → `{intent: record|view|read|confirm|cancel|unknown, date, date_status: ok|ask|future|out_of_range|missing, meal_type, items[] (영양 미리보기), questions[], warnings[], requires_confirmation}` — **쓰기 없음**. 날짜는 이 시점에 확정 |
| POST | `/api/v1/meal-logs` | `{log_date, meal_type, items:[{food_name, nutrition_ref_id?, quantity?, unit?, grams?}], idempotency_key, confirmed, source?, utterance?}` → `{log, replayed}`. 영양값은 서버가 재계산 후 **스냅숏** 저장. 미래 날짜 422 `FUTURE_DATE`, 365일 초과 422 `DATE_OUT_OF_RANGE` |
| POST | `/api/v1/meal-logs/from-session/{session_id}` | `{meal_type, log_date?, confirmed}` — 최신 분석 결과를 기록(분석당 1건, 재호출 `replayed`) |
| GET | `/api/v1/meal-logs?date=&meal_type=` | 해당 날짜 기록(삭제 제외) |
| GET | `/api/v1/meal-logs/summary?date=&meal_type=` | 합계, `totals_complete`, `has_demo`, `is_estimate`, `display_lines[]`, `speech_text`(≤150자·≤3문장, 미상·추정·DEMO 표기) |
| GET | `/api/v1/meal-logs/{id}` | 단건 |
| DELETE | `/api/v1/meal-logs/{id}?confirmed=true` | soft delete(`deleted_at`). 음성 삭제 없음 |

g 규칙(영양값은 항상 기준표 값이므로 kcal은 항상 `is_estimate=true`, 화면·`speech_text`에 '추정'): 말한 g → `stated`; 단위를 말하지 않았거나 단위가 기준표 `serving_unit`(음식=`인분`)과 같으면 수량×1회 제공량 → `serving_size`(추정); 그 외(예: '공기', '개') → g/kcal `null` + `null_reason`. 기준량이 100 mL인 음식은 1인분을 `volume_ml`(mL)로만 보여 주고 g·kcal은 `null`(`null_reason=volume_basis`). mL를 g로 바꾸지 않습니다.

## Inventory ↔ Excel sync (iteration 2)
| Method | Path | 설명 |
|---|---|---|
| POST | `/api/v1/inventory/excel-sync` | `{dry_run: true}`(기본) = 병합 계획 미리보기만. `{dry_run: false, confirmed: true}` = 외부 수정 3-way 병합 + 현재 재고 내보내기. `confirmed` 없으면 400. 미설정이면 409 `EXCEL_SYNC_DISABLED` |
| GET | `/api/v1/inventory/excel-sync/status` | 경로, `state`, `reason_text`(사람이 읽는 한 문장), `pending_export`, `change_seq/exported_seq`, 마지막 export/결과, 잠금 파일(Excel `~$`, LibreOffice `.~lock.#`)·충돌 사본, `cas_mode`(link/replace), 최근 이벤트 |
| POST | `/api/v1/inventory/excel-sync/resolve` | `{action: discard_file \| apply_file_values, dry_run?, confirmed}` — `blocked`/`needs_review`일 때 명시적 해결. discard_file = 파일 백업(`data/excel_backups/`) 후 DB 값으로 다시 내보내기. apply_file_values = 파일의 유효 행을 절대값으로 보고 `adjust` 기록 후 내보내기(`dry_run:true`로 미리보기). `confirmed` 없으면 400 |

`status` 응답(GET)에는 `state`(`ok` | `ok_with_rejected_rows` | `needs_review` | `blocked` | `error` | `pending_locked` | `waiting` | `disabled`), `last_error`, `stored`(동기화 테이블 행 수)가 있습니다. 실패한 상태에서 `ok`/`up_to_date`를 표시하지 않습니다.

자동 반영(`INVENTORY_XLSX_AUTO_APPLY=true`, 기본값)은 **안전한 변경만** 적용합니다: 알려진 export_id 기준(baseline)이 있고 conflict·invalid 행이 없을 때. 하나라도 있으면 `needs_review` — 아무것도 반영하지 않고, 파일을 덮어쓰지 않으며(사람의 수정이 보존됨), DB 변경은 pending export로 쌓였다가 파일이 고쳐지거나 `/admin/inventory-sync`에서 Apply하면 즉시 내보냅니다. 수동 Apply(`dry_run=false, confirmed=true`)는 유효한 행만 반영하고 거부된 행(바코드/QR 중복, DB 제약 위반 등)은 `plan.invalid`로 보고한 뒤 내보내기를 계속합니다. 서로 독립인 두 재고 차분을 더하는 `merge_delta`는 `plan.merges`(양쪽 보존)로 분류되며 conflict가 아닙니다.

관리 화면: `GET /admin/inventory-sync` (토큰 입력 방식은 `/admin/meals`와 같음; 미리보기, invalid/conflict 목록, Apply 버튼, 최근 이벤트).

`status` 값: `exported`, `merged_and_exported`, `up_to_date`, `pending_locked`, `needs_review`, `error`, `blocked`(export_id 미상 — 파일 덮어쓰지 않음), `deferred_locked_by_excel`, `deferred_unstable`, `deferred_unreadable`, `deferred_changed`(쓰는 순간 사람이 저장 — 사람의 저장본 유지, 다음 poll에 병합), `external_changes_pending_confirmation`, `preview`.

보관: 병합 기준 스냅숏은 최근 50회 또는 최근 90일(최대 5000 + 하루 1개, zlib 압축) 중 넓은 쪽 + 현재 파일의 export_id.

## Nutrition (iteration 2 changes)
- 응답 행에 `verification`(`official_file_import` > `mirror_cross_checked` > `single_mirror` > `web_transcribed` > `demo_mock`), `serving_size_g`, `serving_unit`, `basis`, `source_url`, `retrieved_at`.
- 자동 매칭은 이름/별칭 **정확 일치**만. 부분 일치와 일반어 별칭(`suggest_aliases`, 예: 된장국→호박된장국, 계란→달걀(생것))은 `candidates`로만 제공.
- 행 필드 추가: `serving_size_ml`(100 mL 기준 음식), `micro_verification`(당류·나트륨 검증 등급), `verification=legacy_api`(iteration 1 DB의 비DEMO 행).
