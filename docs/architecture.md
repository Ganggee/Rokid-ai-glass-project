# Architecture

```
사용자 ─▶ Rokid RV101 (AIUI Agent: 촬영·입력·HUD) ─BT─▶ Hi Rokid 폰 앱 ─HTTPS─▶ FastAPI 서버
                                                                              ├─ SQLite (재고·이력·식사 세션) = 정본
                                                                              ├─ uploads/ (식사 사진, gitignore)
                                                                              ├─ QR/바코드(OpenCV) · OCR(Tesseract, 선택)
                                                                              └─ 식사 비교(OpenCV baseline / 선택 모델) · 영양 계산
결과 JSON ◀──────────────────────────────────────────────────────────────────────┘
```
원칙: 안경에서는 대형 모델을 돌리지 않는다. 안경 = 촬영/입력/HUD, 서버 = 이미지 처리/DB/계산.

## Task 1 — 영구 저장 문제의 원인과 해결
- 보고된 증상: Simulator·실기기에서 20→19 후 Agent 재실행 시 20.
- 추정 원인(사용자 코드 미제공, 설명 기준): 페이지 `data: { stock: 20 }` 초기값만 있고 저장/서버 반영이 없음. Page 인스턴스가 다시 만들어지면 초기값으로 돌아감.
- 해결:
  1. **SERVER 모드**: 재고 정본 = 서버 SQLite. 차감은 `POST /api/v1/inventory/use` 한 곳에서만, `BEGIN IMMEDIATE` 트랜잭션 + `idempotency_key UNIQUE` + `CHECK(stock_qty >= 0)`.
     페이지는 화면 진입마다 서버에서 재조회.
  2. **pending-operation 저널**: POST 전에 `{key, productId, qty}`를 `wx.setStorageSync`로 기록 → 성공/확정 거절 시 삭제. 응답 유실·앱 종료 후 재진입 시 `GET /operations/{key}`로 반영 여부 확인. 재시도는 **같은 키**로만.
  3. **LOCAL DEMO 모드**(서버 미설정): 재고/이력을 `wx.setStorageSync`에 저장. 저장 실패 시 성공으로 표시하지 않음. 단일 기기용.

## Task 2 — 식전/식후 파이프라인
1. `POST /meals/sessions` → 세션 ID(안경 저장소에도 기록 → 재진입 시 이어서 진행)
2. 식전 사진 업로드 → JPEG 재인코딩(EXIF 제거) → 후보 영역(색+텍스처, 라벨 없음) + 라벨 옵션 반환
3. HUD에서 영역별 음식 라벨·제공량(g, 선택) 지정 → `POST /items`
4. 식후 사진 업로드 → `POST /analyze`
5. 정렬: SIFT → ORB → ECC(affine) 순, 실패 시 `alignment_failed` 경고 + confidence low
6. 영역별 측정: 수동(Baseline 0: 두 사진의 사용자 영역 면적, 카메라 배율 보정) 또는 자동(Baseline 1: 같은 영역에서 접시색 대비 색거리+텍스처 마스크, 식전에서 학습한 임계값을 식후에 동일 적용, 노출 보정)
7. 정책: 비율은 추정치, g는 초기 제공량이 있을 때만, 영양소는 g + 100g당 값이 있을 때만. 그렇지 않으면 `null` + `assumptions`/`warnings`.

## 모듈
| 경로 | 역할 |
|---|---|
| `backend/app/services/inventory_service.py` | 조회, 원자적 차감, 이력, import, 코드 매핑, 명령 파서 |
| `backend/app/services/image_io.py` | 업로드 3방식, MIME 실검증, 크기 제한, 재인코딩 |
| `backend/app/services/qr_reader.py`, `image_recognition.py` | QR/바코드(OpenCV) ↔ OCR 후보 — 서로 다른 기능, 통계 별도 기록 |
| `backend/app/vision/baseline_opencv.py` | 정렬, 마스크, 면적, 후보 영역 |
| `backend/app/vision/optional_food_model.py` | SAM2/FoodSAM 플러그인 인터페이스(폴백) |
| `backend/app/services/meal_comparison.py` | 세션/사진/아이템/분석/결과 정책 |
| `aiui-agent/lib/*.js` | API 클라이언트, 재고 백엔드(SERVER/LOCAL), 카메라/바코드/음성, i18n |
| `aiui-agent/pages/*` | Home, Inventory, Meal (단일 `.ink`) |

## 보안·개인정보
- 모든 `/api/v1` 요청에 `Authorization: Bearer <API_TOKEN>`. `/health`, `/admin/meals`(빈 HTML)만 공개.
- 로그(`api_logs`)에는 메서드/경로/상태/시간만. 본문·토큰·사진 미기록.
- 사진: 매직바이트 검증, 크기 제한(`MAX_UPLOAD_MB`), 서버가 파일명 결정(`uploads/meals/<uuid>/before.jpg`), 인증된 조회만, `DELETE /meals/{id}` 및 `scripts/purge_uploads.py`로 보관기간 관리.
- `.env`, SQLite, uploads, reports, 실데이터(`sample-data/real/`), `*.aix`는 gitignore.
