"""Nutrition data: provenance validation, per-100 g normalisation, exact-match policy, MFDS empty-basis bug."""
from __future__ import annotations

import csv
import sys

from backend.app.services import nutrition_lookup as nl

from .conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import import_nutrition_mfds as imp  # noqa: E402
import validate_nutrition_csv as val  # noqa: E402

PUBLIC = ROOT / "sample-data" / "nutrition_reference_public.csv"


def test_bundled_csvs_pass_validator():
    assert val.main([str(PUBLIC), str(ROOT / "sample-data" / "nutrition_demo.csv")]) == 0


def test_public_rows_have_provenance_and_cross_check_majority():
    rows = list(csv.DictReader(PUBLIC.open(encoding="utf-8")))
    assert len(rows) >= 150
    assert all(r["source"] == "MFDS_STD_DATA" and r["source_url"].startswith("https://www.data.go.kr/") for r in rows)
    assert all("@" in r["source_detail"] for r in rows)  # mirror repo@commit recorded
    checked = sum(r["verification"] == "mirror_cross_checked" for r in rows)
    assert checked / len(rows) > 0.8
    # 100 mL basis rows keep the food name but no per-100 g values (no mL->g conversion)
    ml = [r for r in rows if r["basis"].lower() == "100ml"]
    assert ml and all(r["kcal_per_100g"] == "" for r in ml)


def test_validator_rejects_bad_rows():
    bad = {"id": "X", "food_name": "x", "source": "S", "verification": "single_mirror", "is_demo": "0",
           "source_url": "http://example.com/x", "retrieved_at": "2026-13-01",
           "kcal_per_100g": "500", "carbs_g_per_100g": "60", "protein_g_per_100g": "30", "fat_g_per_100g": "20"}
    errs = " | ".join(val.validate_row(bad))
    assert "allow-listed" in errs and "ISO" in errs and "C+P+F" in errs
    atw = dict(bad, source_url="https://www.data.go.kr/x", retrieved_at="2026-11-06", kcal_per_100g="50",
               carbs_g_per_100g="20", protein_g_per_100g="5", fat_g_per_100g="5")
    assert any("Atwater" in e for e in val.validate_row(atw))
    assert not val.validate_row(dict(atw, atwater_exempt="alcohol content"))
    web = dict(atw, verification="web_transcribed", kcal_per_100g="145", atwater_exempt="x", source_quote="열량 140")
    assert any("verbatim" in e for e in val.validate_row(web))


def test_per_100g_factor_rules():
    assert nl.per_100g_factor("100g") == 1.0
    assert nl.per_100g_factor("200 g") == 0.5
    for b in ("100mL", "100ml", "", None, "1회", "100mg"):
        assert nl.per_100g_factor(b) is None


def test_mfds_empty_basis_no_longer_treated_as_100g():
    rows = nl.mfds_items_to_rows([
        {"FOOD_NM_KR": "A", "FOOD_CD": "1", "NUTRI_AMOUNT_SERVING": "", "AMT_NUM1": "100"},
        {"FOOD_NM_KR": "B", "FOOD_CD": "2", "NUTRI_AMOUNT_SERVING": "100g", "AMT_NUM1": "120"},
        {"FOOD_NM_KR": "C", "FOOD_CD": "3", "NUTRI_AMOUNT_SERVING": "200g", "AMT_NUM1": "300"},
        {"FOOD_NM_KR": "D", "FOOD_CD": "4", "NUTRI_AMOUNT_SERVING": "100mL", "AMT_NUM1": "50"},
    ], "2026-11-06", "https://www.data.go.kr/data/15127578/openapi.do")
    kcal = {r["food_name"]: r["kcal_per_100g"] for r in rows}
    assert kcal == {"A": None, "B": 120.0, "C": 150.0, "D": None}


def test_official_file_import_fixture(tmp_path):
    # fixture mimics the official header; values are SYNTHETIC
    f = tmp_path / "official.csv"
    f.write_text("식품코드,식품명,데이터구분명,영양성분함량기준량,에너지(kcal),탄수화물(g),단백질(g),지방(g),당류(g),나트륨(mg),식품중량\n"
                 "D000-TEST-0001,테스트밥,음식,100g,150,33,3,0.5,0,1,210g\n"
                 "D000-TEST-0002,테스트국,음식,100mL,30,3,2,1,0,300,500g\n"
                 "D000-TEST-0003,테스트떡,음식,200g,400,80,8,2,10,200,\n", encoding="utf-8")
    rows, stats = imp.convert(imp.read_rows(f), "2026-11-06", imp.OFFICIAL_PAGE)
    by = {r["food_name"]: r for r in rows}
    assert by["테스트밥"]["kcal_per_100g"] == 150 and by["테스트밥"]["serving_size_g"] == 210
    assert by["테스트국"]["kcal_per_100g"] == "" and stats["values_withheld_basis"] == 1
    assert by["테스트떡"]["kcal_per_100g"] == 200 and by["테스트떡"]["verification"] == "official_file_import"
    assert by["테스트밥"]["id"] == "MFDS-D000-TEST-0001"


def test_exact_match_only_and_ranking(conn):
    assert nl.resolve_label(conn, "김밥")["food_name"] == "김밥"
    m = nl.match(conn, "참치김밥")  # not in the table: partial matches are candidates only
    assert m["exact"] is None and any(c["food_name"] == "김밥" for c in m["candidates"])
    # '밥' exact alias of 쌀밥 (cross-checked) wins over DEMO-RICE ('밥' food_name)
    assert nl.resolve_label(conn, "밥")["id"].startswith("MFDS-")
    assert nl.resolve_label(conn, "흰 쌀 밥")["food_name"] == "쌀밥"  # spaces ignored


def test_official_import_outranks_mirror(conn):
    nl.upsert_rows(conn, [{"id": "MFDS-OFFICIAL-X", "food_name": "쌀밥", "kcal_per_100g": 160, "source": "MFDS_STD_DATA",
                           "verification": "official_file_import", "is_demo": 0}])
    assert nl.resolve_label(conn, "쌀밥")["id"] == "MFDS-OFFICIAL-X"
