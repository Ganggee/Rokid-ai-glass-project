"""Import the OFFICIAL MFDS 식품영양성분 standard data (first-hand source) into the nutrition table.

1) File downloaded by you (CSV or XLSX) from
   https://www.data.go.kr/data/15100070/standard.do  (전국통합식품영양성분정보(음식)표준데이터)
   or https://various.foodsafetykorea.go.kr/nutrient/  (식품영양성분 DB 내려받기):

    python scripts/import_nutrition_mfds.py --file 전국통합식품영양성분정보_음식_표준데이터.csv
    python scripts/import_nutrition_mfds.py --file food.xlsx --only-names sample-data/nutrition_curated_foods.csv
    python scripts/import_nutrition_mfds.py --file food.csv --out sample-data/nutrition_reference_official.csv   # CSV instead of DB

2) OpenAPI with MFDS_API_KEY in .env (data.go.kr 15127578; operation/field names NOT VERIFIED):

    python scripts/import_nutrition_mfds.py --api --query 김치찌개 --query 쌀밥

Rows get verification=official_file_import and rank above mirror-derived rows.
Per-100 g normalisation: basis '100g' as-is, 'Ng' rescaled, mL / empty / unknown -> values left empty.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

import _bootstrap  # noqa: F401

from backend.app.services.nutrition_lookup import COLUMNS, per_100g_factor

HEADER_ALIASES = {
    "food_code": ["식품코드", "FOOD_CD"],
    "food_name": ["식품명", "FOOD_NM_KR", "DESC_KOR"],
    "category": ["식품대분류명", "식품대분류", "데이터구분명", "FOOD_CAT1_NM"],
    "basis": ["영양성분함량기준량", "영양성분기준량", "NUTRI_AMOUNT_SERVING", "SERVING_SIZE"],
    "kcal": ["에너지(kcal)", "에너지(㎉)", "에너지", "AMT_NUM1"],
    "carbs": ["탄수화물(g)", "탄수화물", "AMT_NUM7"],
    "protein": ["단백질(g)", "단백질", "AMT_NUM3"],
    "fat": ["지방(g)", "지질(g)", "지방", "AMT_NUM4"],
    "sugars": ["당류(g)", "당류", "AMT_NUM8"],
    "sodium": ["나트륨(mg)", "나트륨", "AMT_NUM13"],
    "weight": ["식품중량", "1회섭취참고량", "1회 섭취참고량", "Z10500", "SERVING_WT"],
    "source_name": ["출처명", "SUB_REF_NAME"],
}
OFFICIAL_PAGE = "https://www.data.go.kr/data/15100070/standard.do"


def _f(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _grams(v):
    """'350g' / '350' / 350 -> 350.0 ; '200mL' -> None."""
    if v is None:
        return None
    s = str(v).strip().lower().replace(" ", "")
    if s.endswith("ml") or s.endswith("l"):
        return None
    s = s[:-1] if s.endswith("g") else s
    return _f(s)


def read_rows(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        headers = [str(h).strip() if h is not None else "" for h in next(it)]
        return [{headers[i]: ("" if c is None else str(c)) for i, c in enumerate(r) if i < len(headers)} for r in it]
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit("CSV must be UTF-8 or CP949")
    return list(csv.DictReader(io.StringIO(text)))


def map_headers(headers) -> dict[str, str]:
    hs = {h.strip(): h for h in headers if h}
    out = {}
    for field, aliases in HEADER_ALIASES.items():
        for a in aliases:
            if a in hs:
                out[field] = hs[a]
                break
    for req in ("food_name", "kcal"):
        if req not in out:
            raise SystemExit(f"required column for '{req}' not found; headers={list(hs)[:20]}")
    return out


def convert(rows: list[dict[str, str]], retrieved_at: str, source_url: str, only: set[str] | None = None):
    if not rows:
        return [], {"rows": 0}
    m = map_headers(rows[0].keys())
    out, stats = [], {"rows": len(rows), "imported": 0, "values_withheld_basis": 0, "skipped_filter": 0}
    for idx, r in enumerate(rows, start=1):
        g = lambda k: r.get(m[k]) if k in m else None  # noqa: E731
        name = (g("food_name") or "").strip()
        if not name:
            continue
        if only is not None and name not in only:
            stats["skipped_filter"] += 1
            continue
        basis = (g("basis") or "").strip()
        factor = per_100g_factor(basis)
        if factor is None:
            stats["values_withheld_basis"] += 1

        def norm(key):
            v = _f(g(key))
            return "" if v is None or factor is None else round(v * factor, 3)

        code = (g("food_code") or "").strip()
        out.append({
            "id": f"MFDS-{code}" if code else f"MFDS-FILE-{idx}",
            "food_name": name, "aliases": "", "category": (g("category") or "").strip(),
            "kcal_per_100g": norm("kcal"), "carbs_g_per_100g": norm("carbs"), "protein_g_per_100g": norm("protein"),
            "fat_g_per_100g": norm("fat"), "sugars_g_per_100g": norm("sugars"), "sodium_mg_per_100g": norm("sodium"),
            "serving_size_g": _grams(g("weight")) or "", "serving_unit": "", "basis": basis, "food_code": code,
            "source": "MFDS_STD_DATA", "source_url": source_url,
            "source_detail": f"official file import ({(g('source_name') or '').strip() or 'MFDS'})",
            "retrieved_at": retrieved_at, "verification": "official_file_import", "is_demo": 0,
        })
        stats["imported"] += 1
    return out, stats


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", type=Path)
    p.add_argument("--api", action="store_true")
    p.add_argument("--query", action="append", default=[])
    p.add_argument("--only-names", type=Path, help="CSV with a db_name column (e.g. nutrition_curated_foods.csv)")
    p.add_argument("--out", type=Path, help="write CSV instead of the database")
    p.add_argument("--retrieved-at", default=date.today().isoformat())
    p.add_argument("--database")
    a = p.parse_args(argv)
    if not a.file and not a.api:
        p.error("--file or --api required")
    from backend.app.config import load_settings
    from backend.app.db import connect, init_db
    from backend.app.services import nutrition_lookup

    only = None
    if a.only_names:
        only = {r["db_name"] for r in csv.DictReader(a.only_names.open(encoding="utf-8"))}
    if a.file:
        rows, stats = convert(read_rows(a.file), a.retrieved_at, OFFICIAL_PAGE, only)
    else:
        settings = load_settings(**({"database_path": a.database} if a.database else {}))
        if not settings.mfds_api_key:
            print("MFDS_API_KEY not set in .env", file=sys.stderr)
            return 2
        conn = connect(settings.database_path)
        init_db(conn)
        results = [nutrition_lookup.search_mfds(conn, q, settings.mfds_api_key, settings.mfds_base_url,
                                                settings.mfds_operation) for q in a.query]
        print(json.dumps([{"status": r["status"], "items": len(r["items"])} for r in results], ensure_ascii=False))
        return 0
    print(json.dumps(stats, ensure_ascii=False))
    if a.out:
        with a.out.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(COLUMNS))
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {a.out}")
        return 0
    settings = load_settings(**({"database_path": a.database} if a.database else {}))
    conn = connect(settings.database_path)
    init_db(conn)
    print(f"upserted {nutrition_lookup.upsert_rows(conn, rows)} rows into {settings.database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
