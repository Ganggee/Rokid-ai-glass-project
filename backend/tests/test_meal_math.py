"""Unit tests of the estimate/nutrition policy (no images)."""
from backend.app.services.meal_comparison import build_food_result

RICE_DEMO = {"id": "DEMO-RICE", "food_name": "밥", "kcal_per_100g": 150.0, "carbs_g_per_100g": 33.0,
             "protein_g_per_100g": 2.7, "fat_g_per_100g": 0.3, "source": "DEMO_MOCK", "is_demo": True}


def test_spec_example_10000_to_4000_px_with_200g():
    f = build_food_result("밥", 10000, 4000, 200, "demo_assumption", RICE_DEMO, "manual_region_area", [], [])
    assert f["estimated_remaining_ratio"] == 0.4
    assert f["estimated_consumed_ratio"] == 0.6
    assert f["estimated_consumed_grams"] == 120.0
    assert f["kcal"] == 180.0 and f["carbs_g"] == 39.6 and f["protein_g"] == 3.2 and f["fat_g"] == 0.4
    assert f["is_demo"] is True
    assert any("DEMO assumption" in a for a in f["assumptions"])


def test_no_initial_serving_means_no_grams_or_kcal():
    f = build_food_result("밥", 10000, 4000, None, None, RICE_DEMO, "auto_mask_in_region", [], [])
    assert f["estimated_consumed_ratio"] == 0.6
    assert f["estimated_consumed_grams"] is None and f["kcal"] is None and f["protein_g"] is None
    assert any("not computable" in a for a in f["assumptions"])


def test_no_reference_means_no_nutrients_but_grams_ok():
    f = build_food_result("미확인 음식", 8000, 2000, 150, "user", None, "manual_region_area", [], [])
    assert f["estimated_consumed_grams"] == 112.5 and f["kcal"] is None and f["source"] is None
    assert f["is_demo"] is False


def test_after_larger_than_before_gives_null_ratio_not_a_number():
    f = build_food_result("밥", 5000, 6500, 200, "user", RICE_DEMO, "auto_mask_in_region", [], [])
    assert f["estimated_consumed_ratio"] is None and f["estimated_consumed_grams"] is None and f["kcal"] is None
    assert any("larger_than_before" in w for w in f["warnings"])


def test_slightly_larger_is_clamped_to_zero_consumed():
    f = build_food_result("김치", 5000, 5400, None, None, None, "auto_mask_in_region", [], [])
    assert f["estimated_consumed_ratio"] == 0.0
    assert any("clamped" in w for w in f["warnings"])


def test_missing_before_area():
    f = build_food_result("밥", None, None, 200, "user", RICE_DEMO, "none", [], [])
    assert f["estimated_consumed_ratio"] is None and f["kcal"] is None
