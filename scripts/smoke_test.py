"""End-to-end smoke test against a RUNNING backend (localhost or the HTTPS URL the glasses use).

    python scripts/smoke_test.py --base-url http://127.0.0.1:8000            # token from .env
    python scripts/smoke_test.py --base-url https://poc.example.com --token XXX --no-write

Task 1: list -> use 1 (idempotent, sent twice) -> stock -1 exactly once -> status lookup.
Task 2: synthetic before/after photos -> items -> analyze -> print per-food estimate.
With --no-write only read-only checks run (safe against a shared server).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

import _bootstrap  # noqa: F401
import requests

from backend.app.config import _load_dotenv, REPO_ROOT


def main(argv=None) -> int:
    _load_dotenv(REPO_ROOT / ".env")
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--token", default=os.environ.get("API_TOKEN", ""))
    p.add_argument("--product", default="CARE-SENS-AIR-SENSOR")
    p.add_argument("--no-write", action="store_true")
    a = p.parse_args(argv)
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {a.token}"
    if a.base_url.startswith("http://127.0.0.1") or a.base_url.startswith("http://localhost"):
        s.proxies.update({"http": None, "https": None})
    base = a.base_url.rstrip("/")
    ok = True

    def step(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")

    h = s.get(base + "/health", timeout=10)
    step("health", h.ok, h.text[:120])
    prods = s.get(base + "/api/v1/inventory/products", timeout=10)
    step("list products (auth)", prods.ok, f"{prods.status_code}")
    if not prods.ok:
        return 1
    stock0 = next((x["stock_qty"] for x in prods.json()["items"] if x["product_id"] == a.product), None)
    step(f"product {a.product} exists", stock0 is not None, f"stock={stock0}")
    if a.no_write or stock0 is None:
        return 0 if ok else 1

    if stock0 > 0:
        key = "smoke-" + uuid.uuid4().hex
        body = {"product_id": a.product, "quantity": 1, "idempotency_key": key, "confirmed": True, "source": "smoke_test"}
        r1 = s.post(base + "/api/v1/inventory/use", json=body, timeout=15)
        r2 = s.post(base + "/api/v1/inventory/use", json=body, timeout=15)
        stock1 = s.get(base + f"/api/v1/inventory/products/{a.product}", timeout=10).json()["stock_qty"]
        step("use 1 applied once despite duplicate send", r1.ok and r2.ok and r2.json()["replayed"] and stock1 == stock0 - 1,
             f"{stock0} -> {stock1}")
        st = s.get(base + f"/api/v1/inventory/operations/{key}", timeout=10).json()
        step("operation status lookup", st["applied"] is True)
    else:
        print("SKIP  use: stock is 0")

    from backend.tests.synthetic_meal import encode_jpeg, render_meal

    before, after, truth = render_meal(seed=7)
    sid = s.post(base + "/api/v1/meals/sessions", json={"note": "smoke"}, timeout=10).json()["session_id"]
    up = s.post(base + f"/api/v1/meals/{sid}/photos/before", files={"file": ("b.jpg", encode_jpeg(before), "image/jpeg")}, timeout=60)
    step("meal before upload", up.ok, f"detected_regions={len(up.json().get('detected_regions', []))}" if up.ok else up.text[:200])
    ua = s.post(base + f"/api/v1/meals/{sid}/photos/after", files={"file": ("a.jpg", encode_jpeg(after), "image/jpeg")}, timeout=60)
    step("meal after upload", ua.ok)
    items = [{"label": "밥", "initial_serving_grams": 200, "serving_source": "demo_assumption", "before_region": truth["밥"]["bbox"]},
             {"label": "김치", "before_region": truth["김치"]["bbox"]}]
    step("meal items", s.post(base + f"/api/v1/meals/{sid}/items", json={"items": items}, timeout=10).ok)
    res = s.post(base + f"/api/v1/meals/{sid}/analyze", json={"method": "auto"}, timeout=120)
    step("meal analyze", res.ok)
    if res.ok:
        r = res.json()
        print(json.dumps({"is_demo": r["is_demo"], "confidence": r["confidence"], "alignment": r["alignment"],
                          "foods": [{k: f[k] for k in ("label", "estimated_consumed_ratio", "estimated_consumed_grams", "kcal")}
                                    for f in r["foods"]],
                          "truth_eaten": {k: round(v["eaten_ratio"], 3) for k, v in truth.items() if k in ("밥", "김치")}},
                         ensure_ascii=False, indent=2))
        rice = next(f for f in r["foods"] if f["label"] == "밥")
        kimchi = next(f for f in r["foods"] if f["label"] == "김치")
        step("grams only where serving given", rice["estimated_consumed_grams"] is not None and kimchi["kcal"] is None)
    # Task 2b: voice meal diary (text path, same parser as voice)
    pc = s.post(base + "/api/v1/meal-logs/parse-command", json={"text": "어제 저녁 김밥 1인분이랑 배추김치 먹었어"}, timeout=10)
    step("diary parse (no write)", pc.ok and pc.json()["intent"] == "record", pc.text[:160] if not pc.ok else "")
    if pc.ok and pc.json()["requires_confirmation"]:
        cmd = pc.json()
        saved = s.post(base + "/api/v1/meal-logs", json={
            "log_date": cmd["date"], "meal_type": cmd["meal_type"], "confirmed": True, "idempotency_key": "smoke-" + uuid.uuid4().hex,
            "items": [{"food_name": i["food_name"], "nutrition_ref_id": i["nutrition_ref_id"], "quantity": i["quantity"],
                       "unit": i["unit"]} for i in cmd["items"]]}, timeout=10)
        step("diary save (confirmed)", saved.ok)
        summ = s.get(base + "/api/v1/meal-logs/summary", params={"date": cmd["date"]}, timeout=10).json()
        print("speech_text:", summ["speech_text"])
        step("diary summary speech_text <= 150 chars", len(summ["speech_text"]) <= 150)
        if saved.ok:
            s.delete(base + f"/api/v1/meal-logs/{saved.json()['log']['id']}", params={"confirmed": True}, timeout=10)
    s.delete(base + f"/api/v1/meals/{sid}", timeout=10)
    print("RESULT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
