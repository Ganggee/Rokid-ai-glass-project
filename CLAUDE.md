# CLAUDE.md — working rules for AI coding sessions in this repo

Project: **Rokid AI Glasses Dual PoC — Inventory & Meal Analysis** (technical feasibility PoC, not a medical device).

## Layout
- `aiui-agent/` — AIUI agent (import this folder alone into AIUI Studio). Glasses = capture / input / HUD only.
- `backend/` — FastAPI + SQLite (source of truth), QR/OCR, meal image comparison, nutrition math.
- `scripts/` — seed, import, smoke test, purge. `sample-data/` — DEMO data only.
- `docs/` — capability matrix, API, deploy, test plan, results, handover.

## Non-negotiable rules
1. AIUI is not a browser or WeChat Mini Program. Use only APIs documented in the official `aiui-dev` skill
   (https://github.com/yodaos-project/AIUI/tree/main/skills/aiui-dev). Record anything else as NOT VERIFIED.
2. Stock changes happen only on the server, only with `confirmed: true`, inside `BEGIN IMMEDIATE`, once per
   `idempotency_key`. Never negative. LLM/voice output is parsed into a command; it never writes the DB.
3. 2D pixel area != grams or kcal. Grams/kcal are computed only when an initial serving weight exists;
   otherwise return `null` + a reason. Synthetic/assumed values are marked `is_demo` / `DEMO`.
4. Never commit `.env`, real inventory files, meal photos, voice logs, SQLite files or model weights.
5. Report test levels honestly: UNIT PASS / API E2E PASS / AIUI SIM PASS / RV101 DEVICE PASS / NOT VERIFIED.
6. Change existing user files incrementally; do not delete user AIUI code or design.

## Commands (repo root)
```
python -m pip install -r backend/requirements.txt
python scripts/seed_demo_data.py --reset
python -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
python -m pytest backend/tests -q
node aiui-agent/tests/run-aiui-checks.mjs --aiui-repo <path-to-cloned-yodaos-project/AIUI>
python scripts/smoke_test.py --base-url http://127.0.0.1:8000
```
