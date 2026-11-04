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
