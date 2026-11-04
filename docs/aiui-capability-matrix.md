# AIUI capability matrix (Rokid Glasses RV101, AIUI Studio Global)

조사 기준: 공식 `aiui-dev` Skill 및 문서 — https://github.com/yodaos-project/AIUI (jsar-project/AIUI 와 동일 내용), 2026-11-04 `main` 브랜치.
판정 기호: **확인됨(문서)** = 공식 Skill/문서에 시그니처가 명시됨 · **확인됨(하네스)** = 문서 API를 사용한 코드가 공식 bench 로더에서 동작 ·
**실기기 검증 필요** = 문서상 존재하나 RV101에서 직접 확인하지 않음 · **미지원/미확인** = 문서 근거 없음.

> 이 PoC 세션에는 AIUI Studio, Simulator, 안경이 연결되어 있지 않았습니다. 아래 어떤 항목도 `AIUI SIM PASS` / `RV101 DEVICE PASS`가 아닙니다.

| 항목 | 판정 | 근거 (공식) | 이 저장소의 사용 | 대체 방법 |
|---|---|---|---|---|
| 카메라 촬영 | 확인됨(문서) · 실기기 검증 필요 | `skills/aiui-dev/references/apis/wx.md` — `wx.media.createCameraContext()` → `takePhoto(options)` → `Promise<{data: ArrayBuffer, mimeType}>`, **interactive call site 필요**. `documentation/3-api/media/media-capture.*` — `mode: 'wide'|'telephoto'|'default'`, `enableSystemPreview` | `lib/device.js capturePhoto()` — 탭/키 핸들러에서 직접 호출. QR은 `wide`, 제품·식사는 `telephoto` | PC 관리자 화면(`/admin/meals`) 수동 업로드, 모바일에서 API로 업로드 |
| 카메라 사진 파일 전달 | 확인됨(문서) · 실기기 검증 필요 | `apis/web.md` — `fetch`, `FormData`, `File`; `apis/wx.md` — `wx.arrayBufferToBase64`. 네트워크는 **블루투스→Hi Rokid 폰 앱** 경유(`documentation/3-api/network.*`) | `lib/api-client.js uploadImage()` — FormData(Blob) 우선, 없으면 base64 JSON. 서버는 multipart/raw/base64 3방식 수용 | 업로드 실패 시 PC 관리자 화면 업로드 |
| 사진 mimeType | 실기기 검증 필요 | 공식 scanner 샘플이 WebP 디코더를 동봉 → 기기 사진이 WebP일 수 있음 | 서버가 Pillow로 JPEG/PNG/WEBP 판별 후 JPEG 재인코딩(EXIF 제거) | — |
| 연속 프레임/실시간 | 문서상 일부 존재 · **MVP 범위 밖** | `getUserMedia({video})`, `ImageCapture.grabFrame()`, `MediaRecorder video/webm|mp4` | 사용 안 함(명시적 정지 사진만) | 정지 사진 2장 방식 |
| 온디바이스 QR/바코드 | 확인됨(문서) · 실기기 검증 필요 | `apis/canvas.md` — `BarcodeDetector.detect(Blob|ImageData|raw)`; 공식 `samples/scanner` | `lib/device.js detectCodesOnDevice()` — 실패/미지원 시 `null` → 서버 OpenCV 디코딩 | 서버 `POST /inventory/resolve-image` |
| 한국어 음성 인식 | **미확인** | `apis/ai.md` — `SpeechRecognition`(lang 기본 ''=host default), `SpeechRecognitionSession({lang})`. 지원 언어 목록 문서 없음 | `lib/device.js recognizeOnce()` + 서버 `/parse-command`. `CONFIG.SPEECH_LANG` 기본 '' | 버튼(터치패드) 조작, Simulator 텍스트 → `handleCommandText()` |
| 의도 라우팅 (Agent 호출) | 실기기 검증 필요 | Quickstart: "Hi Rokid, open the xxx agent" 의미 매칭. `AGENTS.md` System Prompts | `aiui-agent/AGENTS.md`에 한/영 호출 예시 | 앱 목록에서 직접 실행 |
| 기본 비서 → 커스텀 Agent 자동 전달 | **미확인** (가정하지 않음) | 문서 근거 없음 | 페이지 안에서만 음성 명령 처리 | — |
| UI/버튼 | 확인됨(문서) | `components.md`(37개 태그: `button`, `scroll-view`, `text` …). `<camera>` 태그는 **카탈로그에 없음**(scanner 샘플에는 등장) | 카탈로그 태그만 사용, 공식 validator 통과 | — |
| 키/터치패드 이벤트 | 확인됨(문서, Rokid Glasses) · RV101 매핑 실기기 검증 필요 | `events.md` — `Backspace`, `ArrowUp/Down`, `Enter`, `GlobalHook`; Glasses 2·컬러 모델 매핑 미확인 | `onKeyUp` Backspace = 뒤로(확인 화면에서는 취소). 나머지는 host 기본 포커스 이동/Enter 활성화 | — |
| 외부 HTTP(S) | 확인됨(문서) · 실기기 검증 필요 | `apis/web.md` fetch, `apis/wx.md` wx.request(timeout 기본 60000) | `fetch` + 자체 타임아웃, 모든 실패를 상태로 반환 | — |
| 로컬 영속 저장 | 확인됨(문서) · **확인됨(하네스)** | `apis/wx.md` — `wx.setStorageSync/getStorageSync`(JSON 직렬화, 실패 시 throw), `apis/web.md` localStorage, `navigator.storage` | LOCAL 모드 재고 + pending-operation 저널 + 식사 세션 ID | SERVER 모드(SQLite)가 정본 |
| Agent Worker 영속성 | 확인됨(문서) | Worker `this` 값은 종료 시 리셋, "Persist durable state in storage" | Worker 미사용 | — |
| AIX 패키징 | 확인됨(문서) · 이 세션에서 미실행 | `documentation/0-guide/bundle/aix.*`, `aix pack`(`@yodaos-pkg/aix-cli`), `.aixignore` | `aiui-agent/.aixignore`(tests 제외). npm 레지스트리 차단으로 `aix` 미설치 → NOT VERIFIED | AIUI Studio **Build & Review → Package AIX** |
| 안경 리소스 업데이트 | 확인됨(문서) · 사용자가 기존 Agent로 성공 경험 | Quickstart VI: Hi Rokid **Settings → Developer → Update glasses resource package** | docs/aiui-studio-deploy.md 절차 | — |
| GitHub Import (Studio) | 확인됨(문서) · Private 저장소 접근 미확인 | Quickstart III Method 3 | `aiui-agent/` 단독 디렉터리로 Import 가능 구조 | **Local folder import** |
| 온디바이스 LLM 이미지 입력 | 문서 존재 · 미사용 | `apis/ai.md` LanguageModel `image_url` | 사용 안 함(음식 분류 확장 후보) | 서버 측 분류 |

## 공식 검증 도구 사용 결과
- `bench/src/validator.js validateWorkspace(aiui-agent)` → **issues 0** (manifest, 라우트, 태그, 핸들러, 스타일 규칙).
- `bench/src/behavior.js loadLogic()` 로 페이지 로직을 실행하는 하네스 18/18 PASS (`aiui-agent/tests/run-aiui-checks.mjs`). 렌더링/레이아웃/실제 카메라는 검증하지 못함.
