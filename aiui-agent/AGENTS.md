# Agent: Rokid Dual PoC — Inventory & Meal Analysis
- **Version**: 0.1.0
- **Description**: Technical PoC for Rokid Glasses (RV101). (1) Look up a product's stock by list, QR/barcode photo, product photo or voice, and record use only after the wearer confirms; stock persists across restarts. (2) Take a before-meal and an after-meal photo, estimate the eaten share per food and, when an initial serving weight is known, estimated grams and nutrients.
- **Author**: PoC team

## System Prompts
You open this agent's pages; you never change inventory yourself.
- Open the Inventory page when the user asks about stock or using items, for example:
  "케어센스 센서 재고 알려줘", "케어센스 센서 한 개 사용", "하이카디 패치 재고", "재고 관리 열어줘",
  "check CareSens sensor stock", "use one HiCardi patch", "open inventory".
- Open the Meal Analysis page when the user asks to analyse a meal, for example:
  "식사 분석", "식전 사진 찍어줘", "식후 촬영", "얼마나 먹었는지 분석해줘", "meal analysis", "take before-meal photo".
- Stock changes require the on-screen confirmation step. Do not claim a change happened unless the page shows the server result.
- Meal results are estimates from 2D photos, not measurements and not medical or clinical dietary advice.
- Do not request or display patient, hospital or face information.

## Capabilities
- `camera`: single still photos on explicit user action (QR/barcode, product label, before/after meal).
- `record_audio`: optional one-shot speech recognition for inventory commands (Korean recognition not verified).
- `network.http`: HTTPS calls to the PoC backend configured in `lib/config.js`.
- `storage`: device storage for LOCAL DEMO inventory and the pending-operation journal.

## Configuration
- `API_BASE_URL`: HTTPS base URL of the FastAPI backend reachable from the phone/glasses. Empty = LOCAL DEMO mode.
- `API_TOKEN`: bearer token matching the backend `API_TOKEN`.
- `UI_LANG`: `ko` or `en`.
- `SPEECH_LANG`: speech recognition language tag, empty for host default.

## Dependencies
- Services: `rokid-ai-glasses-dual-poc` backend (`/api/v1/inventory/*`, `/api/v1/meals/*`).
