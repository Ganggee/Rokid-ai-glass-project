# PoC test plan

결과 분류: `UNIT PASS` · `API E2E PASS` · `AIUI LOGIC HARNESS PASS`(공식 bench 로더, 렌더링 없음) · `AIUI SIM PASS`(사용자 확인) · `RV101 DEVICE PASS`(사용자 실기기 확인) · `NOT VERIFIED`.

## 1. 자동 테스트 (개발 PC / CI)
```powershell
python -m pytest -q                                                     # UNIT + API E2E (실제 uvicorn 재기동 포함)
git clone --depth 1 https://github.com/yodaos-project/AIUI ..\AIUI
node aiui-agent\tests\run-aiui-checks.mjs --aiui-repo ..\AIUI --with-server --python python
python scripts\smoke_test.py --base-url http://127.0.0.1:8000           # 서버 실행 중
python scripts\eval_synthetic_meals.py --n 20 --out reports\synthetic_eval.json
```

## 2. Simulator 체크리스트 (사용자)
| # | 시나리오 | 기대 결과 | 결과 |
|---|---|---|---|
| S1 | Home 진입 | 모드 표시(SERVER host / LOCAL DEMO), 버튼 2개, 겹침 없음 | |
| S2 | 재고 → 센서 → 1개 사용 → 확인 | 확인 화면 후 19 표시 | |
| S3 | Preview 재시작 → 재고 | 19 유지 | |
| S4 | 1개 사용 → 취소 | "취소됨 - 변경 없음", 수치 불변 | |
| S5 | 확인 버튼 연타 | 차감 1회 | |
| S6 | 서버 중지 후 사용 확인 | "응답 없음 - 처리 여부 확인 필요" → 서버 재개 후 "처리 여부 확인" | |
| S7 | 음성 "케어센스 센서 한 개 사용" | 확인 화면(수량 1). 한국어 인식 여부 별도 기록 | |
| S8 | QR 촬영(Simulator 웹캠) | 제품 화면 또는 "인식 실패 - 목록에서 선택" | |
| S9 | 식사: 새 식사 → 식전 → 라벨 → 식후 → 결과 | 비율, g/kcal은 g 입력 항목만, DEMO 표시 | |
| S10 | 한글 표시 | 글자 깨짐 여부 (깨지면 `--lang en`) | |

## 3. RV101 실기기 체크리스트 (사용자)
| # | 항목 | 기대 결과 | 결과 |
|---|---|---|---|
| D1 | AIX 패키징 성공 | Studio 성공 메시지 | |
| D2 | Hi Rokid 리소스 업데이트 성공 | "downloaded successfully" | |
| D3 | Agent 실행(음성 호출 / 목록) | Home 표시 | |
| D4 | LOCAL 모드: 20→19 → Agent 완전 종료 → 재실행 | **19** | |
| D5 | SERVER 모드: 서버 연결(폰 경유 HTTPS) | 제품 목록 로드 | |
| D6 | SERVER: 20→19 → 종료/재실행 → 19, 서버 재기동 → 19, 이력 1건 | | |
| D7 | 카메라 `takePhoto` 동작 | 시스템 프리뷰 후 촬영 | |
| D8 | 사진 mimeType / 크기 (서버 `meal_images` 또는 resolve-image evidence) | 기록 | |
| D9 | 온디바이스 `BarcodeDetector` | 결과 또는 서버 폴백 | |
| D10 | QR 정상 / 잘못된 코드 | 매칭 / 목록 폴백 | |
| D11 | 제품 촬영 OCR 후보 | 후보 선택 또는 인식 실패 | |
| D12 | 음성 한국어 인식 | 인식 문장 표시("인식: ...") | |
| D13 | 키 매핑: Backspace(뒤로), Enter(확인), 스와이프 포커스 | | |
| D14 | 식전/식후 촬영 업로드 → 분석 결과 HUD | | |
| D15 | 네트워크 끊김 중 사용 확인 → 재연결 후 재진입 | 이중 차감 없음 | |

## 4. 결과 기록 규칙
- 성공은 스크린샷/서버 로그(`api_logs`, `inventory_transactions`)로 증빙.
- 측정하지 않은 정확도·성공률은 쓰지 않는다. 합성 이미지 수치는 "synthetic"으로만 표기.
