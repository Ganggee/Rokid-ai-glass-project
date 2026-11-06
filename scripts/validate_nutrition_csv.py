"""Validate nutrition reference CSV files (advisor rubric).

    python scripts/validate_nutrition_csv.py sample-data/nutrition_reference_public.csv sample-data/nutrition_demo.csv

Checks every row:
* required: id, food_name, source, verification (enum), is_demo
* non-demo rows: https source_url on an allow-listed domain (*.go.kr, fdc.nal.usda.gov), ISO retrieved_at
* web_transcribed rows must carry source_quote containing every numeric value verbatim
* values >= 0; carbs+protein+fat <= 100 g per 100 g
* Atwater: |kcal - (4C + 4P + 9F)| <= max(20 % of kcal, 15 kcal), unless atwater_exempt holds a reason
Exit code 0 = all rows pass; 1 = failures (listed).
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

VERIFICATION = {"mirror_cross_checked", "single_mirror", "official_file_import", "web_transcribed", "demo_mock"}
NUM = ("kcal_per_100g", "carbs_g_per_100g", "protein_g_per_100g", "fat_g_per_100g", "sugars_g_per_100g",
       "sodium_mg_per_100g", "serving_size_g")


def allowed(url: str) -> bool:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host.endswith(".go.kr") or host == "fdc.nal.usda.gov")


def num(v):
    if v is None or str(v).strip() == "":
        return None
    return float(v)


def validate_row(r: dict) -> list[str]:
    errs = []
    for k in ("id", "food_name", "source"):
        if not (r.get(k) or "").strip():
            errs.append(f"missing {k}")
    demo = str(r.get("is_demo", "")).strip() in ("1", "true", "True")
    ver = (r.get("verification") or ("demo_mock" if demo else "")).strip()
    if ver not in VERIFICATION:
        errs.append(f"verification '{ver}' not in {sorted(VERIFICATION)}")
    if demo and ver != "demo_mock":
        errs.append("demo row must be verification=demo_mock")
    if not demo:
        if not allowed(r.get("source_url") or ""):
            errs.append(f"source_url not https on allow-listed domain: {r.get('source_url')!r}")
        try:
            date.fromisoformat((r.get("retrieved_at") or "").strip())
        except ValueError:
            errs.append("retrieved_at must be ISO date")
    vals = {}
    for k in NUM:
        try:
            vals[k] = num(r.get(k))
        except ValueError:
            errs.append(f"{k} not a number: {r.get(k)!r}")
            vals[k] = None
        if vals[k] is not None and vals[k] < 0:
            errs.append(f"{k} negative")
    if ver == "web_transcribed":
        quote = r.get("source_quote") or ""
        for k in NUM[:4]:
            if r.get(k) and r[k] not in quote:
                errs.append(f"{k}={r[k]} not found verbatim in source_quote")
    c, p, fat, kcal = vals["carbs_g_per_100g"], vals["protein_g_per_100g"], vals["fat_g_per_100g"], vals["kcal_per_100g"]
    if None not in (c, p, fat):
        if c + p + fat > 100.0 + 1e-6:
            errs.append(f"C+P+F = {c + p + fat:.1f} > 100 g")
        if kcal is not None and not (r.get("atwater_exempt") or "").strip():
            est = 4 * c + 4 * p + 9 * fat
            if abs(kcal - est) > max(0.2 * kcal, 15.0):
                errs.append(f"Atwater check failed: kcal {kcal} vs 4C+4P+9F {est:.1f}")
    return errs


def validate_file(path: Path) -> list[tuple[str, list[str]]]:
    failures = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            e = validate_row(r)
            if e:
                failures.append((r.get("id") or "?", e))
    return failures


def main(argv=None) -> int:
    paths = [Path(p) for p in (argv if argv is not None else sys.argv[1:])]
    total_fail = 0
    for p in paths:
        fails = validate_file(p)
        n = sum(1 for _ in csv.DictReader(p.open(encoding="utf-8-sig")))
        print(f"{p}: {n} rows, {len(fails)} failing")
        for rid, errs in fails:
            print(f"  {rid}: {'; '.join(errs)}")
        total_fail += len(fails)
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
