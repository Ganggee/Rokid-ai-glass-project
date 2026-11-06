# aiui-agent

AIUI Studio에 이 폴더만 Import 합니다 (Local folder import 권장). `.aixignore`가 `tests/`와 이 README를 패키지에서 제외합니다.

| 파일 | 역할 |
|---|---|
| `AGENTS.md` | Agent 정체성, 한/영 호출 의도, 권한 설명 |
| `app.json` | pages(index, inventory, meal), permissions(CAMERA, RECORD_AUDIO) |
| `pages/index/index.ink` | Home: 모드 표시, 두 기능 진입 |
| `pages/inventory/inventory.ink` | 재고: 목록/QR/제품촬영/음성 → 상세 → 확인 → 차감, 이력, pending 복구 |
| `pages/meal/meal.ink` | 식사: 새 식사 → 식전 촬영 → 영역 라벨·g → 식후 촬영 → 결과 → 식사 기록 |
| `pages/diary/diary.ink` | 식사 일지: 음성 기록(확인 후 저장)·날짜 조회·읽어 주기(TTS) |
| `lib/config.js` | API_BASE_URL / API_TOKEN / UI_LANG / SPEECH_LANG (커밋 시 빈 값) |
| `lib/api-client.js` | fetch 래퍼(타임아웃, 오류 분류), 사진 업로드(FormData → base64 폴백) |
| `lib/inventory-client.js` | SERVER / LOCAL 백엔드, pending 저널, 재조정 |
| `lib/device.js` | `takePhoto`, `BarcodeDetector`, `SpeechRecognition` (공식 문서 API만) |
| `lib/diary-client.js`, `lib/meal-client.js`, `lib/command-parser.js`, `lib/i18n.js`, `lib/storage.js`, `lib/ids.js` | 보조 |

조작: 포커스 이동/Enter는 host 기본 동작, `Backspace` = 뒤로(확인 화면에서는 취소).
테스트: `node tests/run-aiui-checks.mjs --aiui-repo <AIUI clone> --with-server`.
