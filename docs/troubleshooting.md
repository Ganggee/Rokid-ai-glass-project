# Troubleshooting

| 증상 | 원인 후보 | 조치 |
|---|---|---|
| 재실행하면 재고가 20으로 돌아감 | 기존 코드가 `data.stock = 20` 초기값만 사용 | 이 저장소의 inventory 페이지 사용. LOCAL 모드는 `inv.local.v1` 저장소, SERVER 모드는 서버 재조회 |
| Home에 `LOCAL DEMO` 표시 | `config.js` API_BASE_URL/TOKEN 비어 있음 | `scripts/configure_agent.py --base-url ... --token ...` 후 재패키징 |
| "네트워크 오류"/"시간 초과" | 안경→폰→서버 경로 불통, localhost 사용 | 폰 브라우저에서 `https://<host>/health` 확인. 터널/TLS 구성 |
| "인증 실패 (토큰 확인)" | 서버 `.env` API_TOKEN ≠ config.js | 두 값 일치시키고 재패키징 |
| "응답 없음 - 처리 여부 확인 필요" | 요청 후 응답 유실 | "처리 여부 확인" → 서버가 반영 여부 응답. "다시 시도"는 같은 키로 재전송(이중 차감 없음) |
| 서버 시작 시 `API_TOKEN is not set` | `.env` 없음 | `Copy-Item .env.example .env` 후 값 설정 |
| `uvicorn: Error loading ASGI app` | `--factory` 누락 | `python -m uvicorn backend.app.main:create_app --factory` |
| QR 인식 실패 | 너무 멀거나 흐림, 실제 QR 값이 매핑에 없음 | 가까이 촬영(`wide` 모드). `resolve-image` 응답 `evidence.raw_value` 확인 후 `qr_value` 매핑 |
| OCR 후보 없음 | Tesseract 미설치/비활성 | Windows: UB Mannheim Tesseract 설치 + PATH, `.env OCR_ENABLED=true` |
| 식사 후보 영역 0개 / 밥 누락 | 흰 음식·흰 접시, 단색 배경 | HUD에서 "라벨 없이 계속" 후 PC `/admin/meals`에서 박스 지정 → Analyze |
| `alignment_failed` | 두 사진 시점/거리 차이 큼, 특징 없는 배경 | 같은 위치·각도에서 재촬영. 식판 테두리/테이블 패턴이 보이게 |
| `after_area_larger_than_before` | 음식 추가·이동, 정렬 오류 | 비율 `null`로 표시됨(정상 동작). 재촬영 또는 수동 박스 |
| g/kcal이 n/a | 초기 제공량 미입력 또는 영양 참조 없음 | HUD 제공량 선택, 또는 관리자 화면에서 g·영양 참조 지정 |
| 한글이 □로 표시 | 기기 폰트 미지원 가능성 | `configure_agent.py --lang en` |
| 카메라 사용 불가 | 권한 거부, interactive gate | 버튼 탭/Enter로 직접 촬영. `app.json` permissions에 CAMERA 확인 |
| `pip install` 실패(프록시) | 사내망 | `pip --proxy`, 또는 오프라인 wheel |

## Iteration 2
| 증상 | 원인 후보 | 조치 |
|---|---|---|
| 음식이 kcal "미상" | 기준량이 100 mL인 음식(국·면 등 65행), 정확 일치 없음, 단위 불일치('공기' vs '인분') | g를 말하기("밥 200그램"), '1인분'으로 말하기, 후보 바꾸기 버튼 |
| 식사 일지 날짜가 하루 어긋남 | 자정 이후 '오늘' | 확인 화면의 전체 날짜 확인, '어제'라고 말하기. `APP_TIMEZONE` 확인 |
| Windows에서 `ZoneInfoNotFoundError` 경고 없이 +09:00 사용 | tzdata 미설치 | Asia/Seoul은 고정 +09:00으로 처리(DST 없음). 다른 시간대면 `pip install tzdata` |
| 업그레이드 후 영양 행이 6개뿐 | 예전 `.env`의 `NUTRITION_CSV=sample-data/nutrition_demo.csv` | `NUTRITION_CSV=sample-data/nutrition_reference_public.csv,sample-data/nutrition_demo.csv`로 수정 후 재시작 |
| Excel status `blocked` | 서버가 만들지 않은 파일, `_sync` 숨김 시트 삭제, 다른 파일을 같은 이름으로 덮어씀 | 파일을 다른 이름으로 옮기고 서버가 새로 내보내게 한 뒤, 바꿀 값은 새 파일에 다시 입력. 또는 `import_inventory.py --mode adjust`로 명시적 반영 |
| `pending_locked` 지속 | Excel에서 파일을 열어 둠, 동기화 클라이언트 잠금 | 파일 닫기 → 다음 poll에 1회 내보내기 |
| Excel 수정이 반영 안 됨 | `INVENTORY_XLSX_AUTO_APPLY=false`(기본) | `POST /api/v1/inventory/excel-sync {"dry_run": false, "confirmed": true}` 또는 AUTO_APPLY=true |
| 내 서식/추가 시트가 사라짐 | 내보내기가 통합문서를 새로 씀 | 서식·메모는 다른 파일에 두기(범위 제외) |

### Iteration 2 (review 02 이후)
| 증상 | 원인 | 조치 |
|---|---|---|
| status `needs_review`, Excel이 갱신되지 않음 | Excel에 invalid 행(음수·소수·수식·바코드 중복) 또는 conflict(음수가 되는 병합, 양쪽 메타데이터 수정)가 있음. 자동 반영은 멈추고 파일을 덮어쓰지 않음 | `/admin/inventory-sync`에서 미리보기 → 셀을 고치거나 Apply(유효한 행만 반영, 나머지 보고). DB 변경은 사라지지 않고 바로 내보내짐 |
| status `error` | 예상하지 못한 예외(`last_error`에 기록) | 서버 로그와 `last_error` 확인. 같은 파일은 다음 poll에 재시도되며 성공 전까지 `ok`로 표시되지 않음 |
| 음식 이름이 확인 화면에서 바뀜/잘림 | 조사는 단어 끝에서, 영양 사전에 있는 이름이 될 때만 제거 | 사전에 없는 음식은 말한 그대로 남고 kcal 미상. 후보 바꾸기 버튼 사용 |
| "지난달", "저번 주" 등으로 말했더니 날짜를 되물음 | 이해하지 못한 날짜 표현은 오늘로 저장하지 않고 되묻도록 설계 | "10월 6일"처럼 날짜로 말하기 |
| uvicorn을 여러 워커로 실행 | 프로세스 사이 동기화 잠금 없음 | `--workers 1`로 실행 |
