# AIUI Studio → AIX → Hi Rokid → RV101 배포 절차

기준 문서: `documentation/0-guide/quickstart/quickstart.en-US.md` (AIUI Studio Global). 메뉴 이름은 Studio 버전에 따라 다를 수 있습니다(예: "Build & Review → Package AIX" / "Device Debug → Repackage and Save").
5핀 개발 케이블·ADB는 **필요 없습니다**(3핀 자석 충전 케이블 환경 기준).

## 0. 서버를 안경에서 접근 가능하게 만들기 (SERVER 모드)
안경의 HTTPS 요청은 **블루투스 → Hi Rokid 폰 앱** 경로로 나갑니다. `localhost`/`127.0.0.1`은 안경에서 접근할 수 없습니다.

| 방법 | 내용 | 상태 |
|---|---|---|
| A. 클라우드 VM + TLS | VM에서 uvicorn, 앞단 Caddy/nginx로 HTTPS(443) | 권장, NOT VERIFIED |
| B. 터널 | PC에서 `cloudflared tunnel --url http://127.0.0.1:8000` 또는 ngrok → 발급된 `https://...` 사용 | 빠른 시험용, NOT VERIFIED. PoC 전용 토큰만 사용 |
| C. 같은 Wi-Fi LAN | `--host 0.0.0.0`, Windows 방화벽 8000 허용, `http://<PC-IP>:8000` | HTTP 허용 여부 NOT VERIFIED |

```powershell
# PC에서 먼저 확인 (폰 브라우저에서도 https://<host>/health 가 열려야 함)
python -m uvicorn backend.app.main:create_app --factory --host 0.0.0.0 --port 8000
python scripts\smoke_test.py --base-url https://<host> --no-write
```

## 1. Agent 설정값 넣기
```powershell
python scripts\configure_agent.py --base-url https://<host> --token <API_TOKEN>    # SERVER 모드
# python scripts\configure_agent.py --lang en      # 한글 글리프가 깨지면
```
설정 없이 Import 하면 **LOCAL DEMO 모드**(재고를 안경 저장소에 보관, 식사 분석·식사 일지·Excel 동기화 비활성 — 모두 SERVER 모드 전용)로 동작합니다.
토큰이 AIX에 포함되므로 PoC 전용 토큰을 쓰고 시험 후 교체하세요. 커밋 전 `--reset`.

## 2. AIUI Studio로 가져오기
1. https://aiui-global.rokid.com/ 로그인.
2. **Import from local folder** → 저장소의 `aiui-agent/` 폴더 선택 (권장).
   - **Import from GitHub**: 저장소 URL + 경로 `aiui-agent` + 브랜치. Private 저장소 접근 가능 여부는 **미확인** → 안 되면 로컬 Import 사용.
3. 기존 `caresens-air-inventory` Agent를 유지하려면: 새 Agent로 Import해서 먼저 검증하세요. 기존 Agent에 합칠 경우 Code 탭에서 기존 `pages/inventory/inventory.ink`를 백업(다른 이름으로 복사)한 뒤 `lib/` 폴더와 새 페이지를 추가하고 `app.json`의 `pages`/`permissions`를 병합합니다. 기존 파일을 삭제하지 마세요.

## 3. Simulator 확인 (→ `AIUI SIM PASS` 기록)
Device Simulation → **Preview**. Temple Controls(click/double-click/swipe)로 포커스 이동·확인, Voice input으로 음성 시험.
- Home → 재고 관리 → CareSens Air Sensor → 1개 사용 → 사용 확인 → `19 ea 남음`
- Simulator를 닫았다 다시 Preview → 제품 목록이 **19** 인지 (LOCAL 모드면 Simulator 저장소 유지 여부도 함께 기록)
- SERVER 모드: 서버 `/api/v1/inventory/transactions`에 `use` 1건만 있는지
- 레이아웃: 숫자 `20`과 안내 문구가 겹치지 않는지 (이번 세션에서 렌더링은 확인 못 함)
- Simulator 카메라(PC 웹캠)와 실기기 카메라는 **별개 항목**으로 기록

## 4. AIX 패키징
Build & Review → **Package AIX** (성공 시 클라우드로 자동 동기화). 결과를 `docs/poc-results.md`의 "AIX 패키징" 행에 기록.
로컬 CLI(선택): `npm install -g @yodaos-pkg/aix-cli` → `aix pack aiui-agent -o dual-poc.aix` (`.aixignore`가 tests/ 제외).

## 5. 안경 리소스 업데이트
Hi Rokid 앱 → **Settings → Developer → Update glasses resource package** → "Agent resource package downloaded successfully" 확인.

## 6. 실기기 호출 (→ `RV101 DEVICE PASS` 항목별 기록)
"Hi Rokid, open Rokid Dual PoC" 또는 한국어 호출(`AGENTS.md`의 예시). 앱 목록에서 직접 실행해도 됩니다.
`docs/poc-test-plan.md` §3 실기기 체크리스트를 순서대로 진행하세요.

## 운영 제약
- 안경은 Hi Rokid 계정과 1:1 페어링. 개발 Agent는 그 계정의 AIUI Studio에서 패키징한 것만 리소스 업데이트로 내려옵니다. 후임자는 자신의 계정으로 Import → 패키징해야 합니다(`docs/handover.md`).
