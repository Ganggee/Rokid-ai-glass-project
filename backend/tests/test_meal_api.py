"""Task 2 API E2E on synthetic before/after images with known ground truth."""
from __future__ import annotations

import base64

import cv2
import numpy as np
import pytest

from .synthetic_meal import encode_jpeg, render_meal

TOL = 0.10  # synthetic images only; says nothing about real photos


@pytest.fixture()
def meal(client):
    before, after, truth = render_meal(seed=7)
    sid = client.post("/api/v1/meals/sessions", json={"note": "pytest"}).json()["session_id"]
    return client, sid, encode_jpeg(before), encode_jpeg(after), truth


def _upload(client, sid, kind, data):
    return client.post(f"/api/v1/meals/{sid}/photos/{kind}", files={"file": (f"{kind}.jpg", data, "image/jpeg")})


def test_after_requires_before(meal):
    client, sid, _b, a, _t = meal
    r = _upload(client, sid, "after", a)
    assert r.status_code == 409 and r.json()["error"]["code"] == "BEFORE_PHOTO_REQUIRED"


def test_full_pipeline_auto_regions_and_nutrition(meal):
    client, sid, b, a, truth = meal
    up = _upload(client, sid, "before", b).json()
    assert up["status"] == "before_captured"
    assert len(up["detected_regions"]) >= 2  # colourful foods found; white rice may be missed (documented)
    names = [o["food_name"] for o in up["label_options"]]
    assert names[0] == "쌀밥" and "배추김치" in names and len(names) <= 20
    assert _upload(client, sid, "after", a).json()["status"] == "after_captured"
    items = [
        {"label": "밥", "nutrition_ref_id": "DEMO-RICE", "initial_serving_grams": 200, "serving_source": "demo_assumption",
         "before_region": truth["밥"]["bbox"]},
        {"label": "김치", "before_region": truth["김치"]["bbox"]},  # no grams -> no kcal
        {"label": "계란", "initial_serving_grams": 50, "before_region": truth["계란"]["bbox"]},
        {"label": "샐러드", "initial_serving_grams": 80, "before_region": truth["샐러드"]["bbox"]},
    ]
    assert client.post(f"/api/v1/meals/{sid}/items", json={"items": items}).status_code == 200
    res = client.post(f"/api/v1/meals/{sid}/analyze", json={"method": "auto"}).json()
    assert res["alignment"]["status"] == "ok"
    assert res["is_demo"] is True and res["confidence"] in ("low", "medium")
    foods = {f["label"]: f for f in res["foods"]}
    for label, t in truth.items():
        est = foods[label]["estimated_consumed_ratio"]
        assert est is not None and abs(est - t["eaten_ratio"]) <= TOL, (label, est, t["eaten_ratio"])
        for key in ("label", "before_mask_area_px", "after_mask_area_px", "estimated_remaining_ratio", "initial_serving_grams",
                    "estimated_consumed_grams", "kcal", "carbs_g", "protein_g", "fat_g", "source", "assumptions",
                    "warnings", "analysis_method", "is_demo"):
            assert key in foods[label]
    rice = foods["밥"]
    assert rice["estimated_consumed_grams"] == pytest.approx(200 * rice["estimated_consumed_ratio"], abs=0.2)
    assert rice["kcal"] == pytest.approx(150 * rice["estimated_consumed_grams"] / 100, abs=0.2)
    assert rice["source"] == "DEMO_MOCK" and rice["is_demo"]
    assert foods["김치"]["estimated_consumed_grams"] is None and foods["김치"]["kcal"] is None
    # exact alias match now prefers the cross-checked public MFDS row over the DEMO row
    assert foods["계란"]["source"] == "MFDS_STD_DATA" and foods["계란"]["is_demo"] is False
    assert res["totals_complete"] is False
    # results endpoint returns the stored analysis; session status updated
    assert client.get(f"/api/v1/meals/{sid}/results").json()["analysis_id"] == res["analysis_id"]
    assert client.get(f"/api/v1/meals/{sid}").json()["status"] == "analyzed"


def test_manual_boxes_baseline0(meal):
    client, sid, b, a, truth = meal
    _upload(client, sid, "before", b)
    _upload(client, sid, "after", a)
    before_box = {"type": "bbox", "x": 300, "y": 300, "w": 100, "h": 100}   # 10000 px
    after_box = {"type": "bbox", "x": 330, "y": 300, "w": 50, "h": 80}      # 4000 px
    client.post(f"/api/v1/meals/{sid}/items", json={"items": [{"label": "밥", "initial_serving_grams": 200,
                "serving_source": "demo_assumption", "before_region": before_box, "after_region": after_box}]})
    res = client.post(f"/api/v1/meals/{sid}/analyze", json={"method": "manual"}).json()
    f = res["foods"][0]
    assert f["analysis_method"] == "manual_region_area"
    assert f["before_mask_area_px"] == 10000
    # after area is corrected by the measured camera scale change (~1.0 here)
    assert abs(f["estimated_consumed_ratio"] - 0.6) < 0.02
    assert abs(f["estimated_consumed_grams"] - 120) < 4


def test_no_items_uses_detected_regions_without_nutrition(meal):
    client, sid, b, a, _t = meal
    _upload(client, sid, "before", b)
    _upload(client, sid, "after", a)
    res = client.post(f"/api/v1/meals/{sid}/analyze", json={}).json()
    assert res["foods"] and all(f["label"].startswith("UNLABELED") for f in res["foods"])
    assert all(f["kcal"] is None and f["estimated_consumed_grams"] is None for f in res["foods"])


def test_unrelated_after_photo_is_flagged(meal):
    client, sid, b, _a, truth = meal
    _upload(client, sid, "before", b)
    rng = np.random.default_rng(1)
    other = np.full((1134, 1512, 3), 40, np.uint8)
    cv2.circle(other, (700, 500), 300, (30, 160, 230), -1)
    other = np.clip(other.astype(np.int16) + rng.normal(0, 3, other.shape), 0, 255).astype(np.uint8)
    _upload(client, sid, "after", encode_jpeg(other))
    client.post(f"/api/v1/meals/{sid}/items", json={"items": [{"label": "밥", "before_region": truth["밥"]["bbox"]}]})
    res = client.post(f"/api/v1/meals/{sid}/analyze", json={}).json()
    assert res["alignment"]["status"] == "failed"
    assert res["confidence"] == "low"
    assert any("alignment_failed" in w for w in res["warnings"])


def test_model_method_falls_back_with_warning(meal):
    client, sid, b, a, truth = meal
    _upload(client, sid, "before", b)
    _upload(client, sid, "after", a)
    client.post(f"/api/v1/meals/{sid}/items", json={"items": [{"label": "김치", "before_region": truth["김치"]["bbox"]}]})
    res = client.post(f"/api/v1/meals/{sid}/analyze", json={"method": "model"}).json()
    assert res["model_plugin"]["available"] is False
    assert any("fell back" in w for w in res["warnings"])
    assert res["foods"][0]["estimated_consumed_ratio"] is not None


def test_base64_upload_photo_fetch_auth_and_delete(meal, settings):
    client, sid, b, _a, _t = meal
    r = client.post(f"/api/v1/meals/{sid}/photos/before", json={"image_base64": base64.b64encode(b).decode()})
    assert r.status_code == 200
    photo = client.get(f"/api/v1/meals/{sid}/photos/before")
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/v1/meals/{sid}/photos/before", headers={"Authorization": "Bearer nope"}).status_code == 401
    folder = settings.upload_dir / "meals" / sid
    assert folder.is_dir()
    assert client.delete(f"/api/v1/meals/{sid}").json()["deleted"] is True
    assert not folder.exists()
    assert client.get(f"/api/v1/meals/{sid}").status_code == 404


def test_results_before_analysis_404(meal):
    client, sid, *_ = meal
    r = client.get(f"/api/v1/meals/{sid}/results")
    assert r.status_code == 404 and r.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_nutrition_search_and_admin_page(client):
    hits = client.get("/api/v1/nutrition/search", params={"q": "쌀밥"}).json()["items"]
    assert hits[0]["food_name"] == "쌀밥" and hits[0]["verification"] == "mirror_cross_checked" and hits[0]["is_demo"] is False
    # DEMO row still reachable, ranked after public rows
    assert any(h["id"] == "DEMO-RICE" for h in client.get("/api/v1/nutrition/search", params={"q": "밥"}).json()["items"])
    remote = client.get("/api/v1/nutrition/search", params={"q": "밥", "remote": True}).json()["remote"]
    assert remote["status"] == "disabled"
    page = client.get("/admin/meals")
    assert page.status_code == 200 and "Meal before/after PoC" in page.text
    caps = client.get("/api/v1/nutrition/capabilities").json()
    assert caps["mfds_api"]["verified"] is False
