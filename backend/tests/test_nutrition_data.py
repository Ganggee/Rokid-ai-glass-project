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
    assert len(rows) >= 100  # rows without mirror agreement are excluded, not filled (review N-1)
    assert all((r["source"], r["source_url"]) in {("MFDS_FOOD_DB", "https://www.data.go.kr/data/15100070/standard.do"),
                                                  ("RDA_NFCDB_10.4", "https://www.nics.go.kr/food")} for r in rows)
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


# ---------------------------------------------------------------- review 02 regressions
CONTRADICTED = {"부대찌개": 67, "추어탕": 32, "소불고기": 170, "깍두기": 33, "햄버거": 284, "볶음밥": 183, "순대": 181}


def _rows():
    return {r["food_name"]: r for r in csv.DictReader(PUBLIC.open(encoding="utf-8"))}


def test_n1_rows_contradicting_official_code_rows_are_not_bundled():
    rows = _rows()
    for name, official_kcal in CONTRADICTED.items():
        r = rows.get(name)
        assert r is None or (r["kcal_per_100g"] and abs(float(r["kcal_per_100g"]) - official_kcal) <= 1), (name, r)


def test_n1_report_lists_exclusions_and_cross_check_meaning():
    import json

    rep = json.loads((ROOT / "sample-data" / "nutrition_reference_public.report.json").read_text(encoding="utf-8"))
    excluded = {e["name"] for e in rep["excluded_disagreement"]}
    assert {"부대찌개", "추어탕", "소불고기", "깍두기", "햄버거", "볶음밥", "순대"} <= excluded
    assert rep["cross_checked"] + rep["single_mirror"] == rep["bundled_rows"]


def test_n1_select_rules_unit():
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_nutrition_reference as b

    def row(m, basis, kcal, carb=10.0, p=2.0, fat=1.0, scaled=False, code=None):
        return {"mirror": m, "basis": basis, "kcal": kcal, "carb": carb, "protein": p, "fat": fat, "serving": 100.0,
                "scaled": scaled, "code": code}

    # official-code anchor; one mirror only has a different value -> excluded (no consensus)
    d = b.select({"toadsam": [row("toadsam", "100g", 123)], "healthlog": [row("healthlog", "100g", 67, scaled=True, code="D1")],
                  "carb": [], "kangsogo7": [row("kangsogo7", None, 67)]})
    assert d["status"] == "excluded"
    # 100 g preferred over 100 mL; the mL row of another mirror is not a vote
    d = b.select({"toadsam": [row("toadsam", "100ml", 120)], "healthlog": [row("healthlog", "100g", 172, scaled=True, code="D2")],
                  "carb": [row("carb", None, 172)], "kangsogo7": [row("kangsogo7", None, 120), row("kangsogo7", None, 172)]})
    assert d["status"] == "ok" and d["basis"] == "100g" and d["values"]["kcal"] == 172 and d["verification"] == "mirror_cross_checked"
    # same-name variants in one mirror: one matching row is enough for THAT mirror, every comparable mirror must match
    d = b.select({"toadsam": [row("toadsam", "100g", 61)], "carb": [row("carb", None, 61)],
                  "kangsogo7": [row("kangsogo7", None, 19), row("kangsogo7", None, 61)], "healthlog": []})
    assert d["status"] == "ok" and d["agree"] == ["carb", "kangsogo7"]
    d = b.select({"toadsam": [row("toadsam", "100g", 50)], "carb": [], "kangsogo7": [], "healthlog": []})
    assert d["status"] == "ok" and d["verification"] == "single_mirror"


def test_n2_staples_have_100g_values():
    rows = _rows()
    for name in ("현미밥", "잡곡밥", "비빔밥", "라면", "짬뽕", "멸치볶음", "쌀밥", "김밥", "김치찌개"):
        r = rows[name]
        assert r["basis"] == "100g" and r["kcal_per_100g"] != "", name
    assert rows["현미밥"]["food_code"] == "D101-050000000-0001" and float(rows["현미밥"]["kcal_per_100g"]) == 172


def test_n3_ml_basis_rows_keep_serving_in_ml_only():
    rows = _rows()
    ml = [r for r in rows.values() if r["basis"] == "100ml"]
    assert ml and all(r["serving_size_g"] == "" and r["kcal_per_100g"] == "" for r in ml)
    assert rows["탕수육"]["serving_size_ml"] == "343"


def test_n3_ml_serving_is_never_shown_or_computed_as_grams(conn):
    from backend.app.services import meal_diary

    it = meal_diary.compute_item(conn, {"name": "탕수육"})
    assert it["grams"] is None and it["kcal"] is None and it["volume_ml"] == 343
    assert "volume_basis" in it["null_reason"]
    it2 = meal_diary.compute_item(conn, {"name": "탕수육", "grams": 200})  # stated grams of a mL-basis food
    assert it2["grams"] == 200 and it2["kcal"] is None


def test_n4_generic_alias_is_candidate_only(conn):
    for word, target in (("된장국", "호박된장국"), ("김", "조미김"), ("고구마", "고구마(생것)"), ("계란", "달걀(생것)"), ("빵", "식빵")):
        m = nl.match(conn, word)
        auto = m["exact"]
        assert auto is None or auto["is_demo"], (word, auto and auto["food_name"])
        assert any(c["food_name"] == target for c in m["candidates"]), (word, [c["food_name"] for c in m["candidates"]])
    assert nl.resolve_label(conn, "삶은계란")["food_name"] == "삶은달걀"  # true synonym stays automatic
    assert nl.resolve_label(conn, "공기밥")["food_name"] == "쌀밥"


def test_n6_validator_without_args_is_usage_error_and_checks_basis():
    assert val.main([]) == 2
    bad = {"id": "X", "food_name": "x", "source": "S", "verification": "single_mirror", "is_demo": "0",
           "source_url": "https://www.data.go.kr/x", "retrieved_at": "2026-11-06", "basis": "100ml",
           "kcal_per_100g": "50", "serving_size_g": "300"}
    errs = " | ".join(val.validate_row(bad))
    assert "100ml" in errs and "serving_size_g" in errs


def test_m1_migration_keeps_legacy_non_demo_rows_ranked(tmp_path):
    import sqlite3

    from backend.app.db import connect, init_db
    from backend.app.models import SCHEMA

    p = tmp_path / "v1.sqlite3"
    c = sqlite3.connect(p)
    v1 = SCHEMA.split("-- ---------------------------------------------------------------- meal diary")[0]
    c.executescript(v1)
    c.execute("INSERT INTO nutrition_references(id, food_name, kcal_per_100g, source, is_demo, updated_at) "
              "VALUES ('MFDS-API-1', '테스트', 100, 'MFDS_API', 0, 'x')")
    c.commit()
    c.close()
    conn = connect(p)
    init_db(conn)
    init_db(conn)
    assert nl.get_reference(conn, "MFDS-API-1")["verification"] == "legacy_api"


# ---------------------------------------------------------------- review 04 (round 2)
R4_WORDS = ["계란", "달걀", "계란후라이", "된장국", "국", "샐러드", "야채샐러드", "닭가슴살", "rice", "steamed rice", "egg",
            "fried egg"]


def test_r4_public_candidates_always_outrank_demo(conn):
    for w in R4_WORDS:
        m = nl.match(conn, w)
        public = [c for c in m["candidates"] if not c["is_demo"]]
        if m["exact"] is not None and m["exact"]["is_demo"]:
            assert not public, (w, "DEMO auto-confirmed although public candidates exist", [c["food_name"] for c in public])
        demo_seen = False
        for c in m["candidates"]:
            demo_seen = demo_seen or c["is_demo"]
            assert not (demo_seen and not c["is_demo"]), (w, "public candidate listed after a DEMO one")


def test_r4_demo_only_match_is_labelled_everywhere(client):
    from datetime import date
    from backend.app.db import connect
    c = connect(client.app.state.settings.database_path)
    try:  # a word that only a DEMO row knows
        c.execute("UPDATE nutrition_references SET aliases = COALESCE(aliases,'') || ';데모전용음식' WHERE id = 'DEMO-RICE'")
    finally:
        c.close()
    today = date.today().isoformat()
    p = client.post("/api/v1/meal-logs/parse-command", json={"text": "오늘 점심 데모전용음식 200g 먹었어"}).json()
    item = p["items"][0]
    assert item["ref_is_demo"] is True and item["nutrition_ref_id"] == "DEMO-RICE"
    r = client.post("/api/v1/meal-logs", json={"log_date": p["date"], "meal_type": "lunch", "items": [
        {"food_name": "데모전용음식", "grams": 200}], "idempotency_key": "r4-demo-only-0001", "confirmed": True})
    assert r.status_code in (200, 201), r.text
    s = client.get("/api/v1/meal-logs/summary", params={"date": p["date"]}).json()
    assert s["has_demo"] and "DEMO" in s["speech_text"] and any("DEMO" in ln for ln in s["display_lines"])
    assert today


def test_r5_rows_removed_from_bundle_are_retired_not_deleted(tmp_path):
    from backend.app.db import connect, init_db
    db = connect(tmp_path / "r5.sqlite3")
    init_db(db)
    csv_path = tmp_path / "nutrition_reference_public.csv"
    rows = list(csv.DictReader(open(ROOT / "sample-data" / "nutrition_reference_public.csv", encoding="utf-8-sig")))
    header = list(rows[0].keys())
    old = dict(rows[0], id="MFDS-D-OLDROW", food_name="철회된음식", aliases="")
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        w.writerows(rows + [old])
    nl.ensure_seeded(db, [csv_path])
    assert nl.match(db, "철회된음식")["exact"]["id"] == "MFDS-D-OLDROW"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:   # new bundle without the row
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
    nl.ensure_seeded(db, [csv_path])
    assert nl.match(db, "철회된음식")["exact"] is None                  # excluded from new matching
    assert nl.get_reference(db, "MFDS-D-OLDROW")["retired"]             # still there for past snapshots
    assert "철회된음식" not in nl.known_names(db)
    assert all(r["id"] != "MFDS-D-OLDROW" for r in nl.list_references(db))
    db.close()


def test_r7_hud_priority_names_are_in_the_bundle():
    names = set(_rows())
    missing = [n for n in nl.HUD_PRIORITY if n not in names]
    assert not missing, missing
    assert len(nl.HUD_PRIORITY) >= 20
