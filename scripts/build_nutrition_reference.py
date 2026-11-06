"""Build sample-data/nutrition_reference_public.csv from public GitHub mirrors of the
MFDS 식품영양성분 데이터베이스 (음식) and RDA 국가표준식품성분 DB 10.4 (원재료), with cross-checking.

Why mirrors: the official download pages (data.go.kr, various.foodsafetykorea.go.kr, nics.go.kr) were
not reachable from the development sandbox. The official file import (scripts/import_nutrition_mfds.py)
remains the first-hand path and ranks above every mirror-derived row.

Mirror files are treated as untrusted DATA: they are parsed, never executed.

    git clone --depth 1 --filter=blob:none --no-checkout https://github.com/toadsam/Ajou_MuscleUp M/toadsam_Ajou_MuscleUp
    (cd M/toadsam_Ajou_MuscleUp && git checkout HEAD -- backend/src/main/resources/food/foods.tsv.gz)
    ... same for the other mirrors (see MIRRORS) ...
    python -I scripts/build_nutrition_reference.py --mirrors M

Representative-row rules (review 02, N-1/N-2; PM decision)
1. collect every same-name candidate row from every mirror (MFDS has several rows per dish name);
2. 100 g basis rows are preferred over 100 mL rows;
3. if health-log (rows carry the official 식품코드 URL) has the food, its row is the ANCHOR and only
   candidates whose values match it are allowed;
4. `mirror_cross_checked` only when >= 2 mirrors have the food and EVERY comparable mirror has a row
   matching the anchor. A mirror is comparable when it has a same-name row with the same basis or with
   an unknown basis (kangsogo7 and carb do not store the basis; a row value-identical to a toadsam row
   inherits that row's basis); a row with a known different basis
   (100 mL vs 100 g) is a different MFDS entry, not a vote. Any comparable mirror with only
   non-matching rows -> the anchor is rejected; if no anchor survives the food is EXCLUDED
   (`excluded_disagreement`). Values are never averaged or invented;
5. `single_mirror` when no other mirror has a comparable row.
100 mL basis -> per-100 g values and serving_size_g are left empty, serving_size_ml is kept (no mL->g).
sugars/sodium come only from kangsogo7 (other mirrors lack them): flagged micro_verification=single_mirror.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "sample-data" / "nutrition_curated_foods.csv"
OUT = ROOT / "sample-data" / "nutrition_reference_public.csv"
REPORT = ROOT / "sample-data" / "nutrition_reference_public.report.json"

MIRRORS = {
    "toadsam": ("toadsam/Ajou_MuscleUp", "toadsam_Ajou_MuscleUp", "backend/src/main/resources/food/foods.tsv.gz"),
    "carb": ("minseok08262-web/carb-loading-tracker", "minseok08262-web_carb-loading-tracker", "data/foods-db.json"),
    "kangsogo7": ("kangsogo7/meal-log", "kangsogo7_meal-log", "public/food-db.json"),
    "healthlog": ("sirloinbh/health-log", "sirloinbh_health-log", "database/migrations/005_foods_popular.sql"),
}
SOURCE = {
    "D": ("MFDS_FOOD_DB", "https://www.data.go.kr/data/15100070/standard.do"),   # 식약처 식품영양성분 DB (음식)
    "R": ("RDA_NFCDB_10.4", "https://www.nics.go.kr/food"),                       # 농진청 국가표준식품성분 DB 10.4
}
FIELDS = ["id", "food_name", "aliases", "category", "kcal_per_100g", "carbs_g_per_100g", "protein_g_per_100g",
          "fat_g_per_100g", "sugars_g_per_100g", "sodium_mg_per_100g", "serving_size_g", "serving_size_ml",
          "serving_unit", "basis", "food_code", "source", "source_url", "source_detail", "retrieved_at", "verification",
          "micro_verification", "is_demo"]
KEYS = ("kcal", "carb", "protein", "fat")


def f(v):
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "-", "-1", "NULL"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def commit_of(path: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


def _file(base: Path, key: str) -> Path:
    return base / MIRRORS[key][1] / MIRRORS[key][2]


def load_toadsam(base: Path) -> dict:
    out: dict = {}
    with gzip.open(_file(base, "toadsam")) as fh:
        for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8"), delimiter="\t"):
            if r["src"] in ("D", "R") and not r["maker"]:
                b = (r["basis"] or "").strip().lower() or None
                out.setdefault(r["name"], []).append({
                    "mirror": "toadsam", "kind": r["src"], "basis": b, "kcal": f(r["kcal"]), "carb": f(r["carb"]),
                    "protein": f(r["protein"]), "fat": f(r["fat"]), "serving": f(r["serving_g"]), "scaled": False})
    return out


def load_carb(base: Path) -> dict:
    out: dict = {}
    for name, carb, kcal, prot, fat, serving, kind in json.loads(_file(base, "carb").read_text(encoding="utf-8"))["items"]:
        out.setdefault(name, []).append({"mirror": "carb", "basis": None, "kcal": f(kcal), "carb": f(carb),
                                         "protein": f(prot), "fat": f(fat), "serving": f(serving), "scaled": False})
    return out


def load_kangsogo7(base: Path) -> dict:
    out: dict = {}
    for row in json.loads(_file(base, "kangsogo7").read_text(encoding="utf-8"))["foods"]:
        name, _kind, brand, kcal, carb, prot, fat, sugar, sodium, serving = row[:10]
        if brand:
            continue
        out.setdefault(name, []).append({"mirror": "kangsogo7", "basis": None, "kcal": f(kcal), "carb": f(carb),
                                         "protein": f(prot), "fat": f(fat), "sugar": f(sugar), "sodium": f(sodium),
                                         "serving": f(serving), "scaled": False})
    return out


_U = re.compile(r"\\([0-9A-Fa-f]{4})")
_HL = re.compile(r"\(U&'([^']*)',\s*(?:NULL|U?&?'[^']*'),\s*(?:NULL|U&'[^']*'),\s*([\d.]+),\s*'(g|mL)',\s*([\d.]+),\s*"
                 r"([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*(?:[\d.]+|NULL),\s*(?:[\d.]+|NULL),\s*'public',\s*'([^']+)'")


def load_healthlog(base: Path) -> dict:
    out: dict = {}
    for m in _HL.finditer(_file(base, "healthlog").read_text(encoding="utf-8")):
        name = _U.sub(lambda x: chr(int(x.group(1), 16)), m.group(1))
        serving, unit = float(m.group(2)), m.group(3)
        scale = 100.0 / serving
        code = re.search(r"searchFoodCd=([^&]+)", m.group(8))
        out.setdefault(name, []).append({
            "mirror": "healthlog", "basis": "100g" if unit == "g" else "100ml",
            "kcal": float(m.group(4)) * scale, "carb": float(m.group(5)) * scale, "protein": float(m.group(6)) * scale,
            "fat": float(m.group(7)) * scale, "serving": serving, "code": code.group(1) if code else None,
            "url": m.group(8), "scaled": True})
    return out


def matches(a: dict, b: dict) -> bool:
    """Same MFDS row? mirror-to-mirror values are copied (1 decimal); health-log is rescaled from per-serving totals."""
    scaled = a.get("scaled") or b.get("scaled")
    for k in KEYS:
        x, y = a.get(k), b.get(k)
        if x is None or y is None:
            if x is None and y is None:
                continue
            return False
        tol = (0.51 if k == "kcal" else 0.06) if scaled else 0.051
        if abs(x - y) > tol:
            return False
    return True


def comparable(row: dict, basis: str | None) -> bool:
    return row["basis"] is None or basis is None or row["basis"] == basis


def select(cands: dict[str, list[dict]]) -> dict:
    """cands: mirror -> same-name rows. Returns {'status': 'ok'|'excluded'|'missing', ...}."""
    if not any(cands.values()):
        return {"status": "missing"}
    # a basis-less row (carb / kangsogo7) whose values equal a toadsam row IS that MFDS row: inherit its basis
    toad_rows = [r for r in cands.get("toadsam", []) if r["basis"]]
    for m in ("carb", "kangsogo7"):
        for r in cands.get(m, []):
            if r["basis"] is None:
                same = [t for t in toad_rows if matches(t, r)]
                if same:
                    r["basis"] = same[0]["basis"]
                    r["basis_inferred"] = True
    if cands.get("healthlog"):
        anchors = cands["healthlog"][:1]                       # rule 3: official-code row is the anchor
    else:
        known = [r for m, rows in cands.items() for r in rows if r["basis"] is not None]
        unknown = [r for m, rows in cands.items() for r in rows if r["basis"] is None]
        anchors = sorted(known, key=lambda r: 0 if r["basis"] == "100g" else 1) + unknown   # rule 2
    rejected = []
    for anchor in anchors:
        basis = anchor["basis"]
        agree, disagree = [], []
        for m, rows in cands.items():
            if m == anchor["mirror"] or not rows:
                continue
            comp = [r for r in rows if comparable(r, basis)]
            if not comp:
                continue                                           # only rows of another basis: not a vote
            hit = next((r for r in comp if matches(anchor, r)), None)
            (agree if hit else disagree).append((m, hit))
        if disagree:
            rejected.append({"anchor": anchor["mirror"], "basis": basis, "disagree": [m for m, _ in disagree],
                             "anchor_kcal": round(anchor["kcal"], 1) if anchor["kcal"] is not None else None})
            continue
        # values with original precision: prefer an unscaled matching row (toadsam > carb > kangsogo7)
        rows_ok = [anchor] + [h for _, h in agree]
        order = {"toadsam": 0, "carb": 1, "kangsogo7": 2, "healthlog": 3}
        value_row = sorted(rows_ok, key=lambda r: (r["scaled"], order[r["mirror"]]))[0]
        if basis is None:                                          # anchor without basis info: use a known one if any
            basis = next((r["basis"] for r in rows_ok if r["basis"]), None)
        serving_row = anchor if anchor["mirror"] == "healthlog" else next(
            (r for r in rows_ok if r["mirror"] == "toadsam"), value_row)
        kang = next((r for r in rows_ok if r["mirror"] == "kangsogo7"), None)
        return {"status": "ok", "basis": basis, "values": {k: value_row[k] for k in KEYS},
                "value_mirror": value_row["mirror"], "anchor": anchor["mirror"],
                "serving": serving_row.get("serving"), "agree": sorted(m for m, _ in agree),
                "code": anchor.get("code"), "kang": kang, "rejected_anchors": rejected,
                "verification": "mirror_cross_checked" if agree else "single_mirror"}
    return {"status": "excluded", "rejected_anchors": rejected}


def lookup(db: dict, names: list[str]) -> list[dict]:
    for n in names:
        if n and n in db:
            return db[n]
    return []


def _fmt(v, nd=2):
    if v is None:
        return ""
    v = round(float(v), nd)
    return int(v) if v.is_integer() else v


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mirrors", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--report", type=Path, default=REPORT)
    a = ap.parse_args(argv)
    retrieved = date.today().isoformat()
    commits = {k: commit_of(a.mirrors / v[1]) for k, v in MIRRORS.items()}
    dbs = {"toadsam": load_toadsam(a.mirrors), "carb": load_carb(a.mirrors), "kangsogo7": load_kangsogo7(a.mirrors),
           "healthlog": load_healthlog(a.mirrors)}
    curated = list(csv.DictReader(CURATED.open(encoding="utf-8")))
    report = {"curated": len(curated), "missing": [], "excluded_disagreement": [], "cross_checked": 0, "single_mirror": 0,
              "anchored_by_official_code": 0, "basis_100ml_values_withheld": [], "chosen_over_primary_mirror": [],
              "mirrors": {k: {"repo": v[0], "commit": commits[k], "file": v[2]} for k, v in MIRRORS.items()}}
    out_rows = []
    for i, c in enumerate(curated, start=1):
        kind, name = c["kind"], c["db_name"]
        names = [name] + ([c["display_name"]] if kind == "R" else [])
        cands = {m: [r for r in lookup(db, names) if m != "toadsam" or r.get("kind") == kind] for m, db in dbs.items()}
        if cands["healthlog"] and cands["healthlog"][0].get("code") and not cands["healthlog"][0]["code"].startswith(kind):
            cands["healthlog"] = []                                 # same name, other food group
        d = select(cands)
        if d["status"] == "missing":
            report["missing"].append(name)
            continue
        if d["status"] == "excluded":
            report["excluded_disagreement"].append({"name": name, "candidates": {m: len(r) for m, r in cands.items() if r},
                                                    "rejected": d["rejected_anchors"]})
            continue
        report["cross_checked" if d["verification"] == "mirror_cross_checked" else "single_mirror"] += 1
        if d["anchor"] == "healthlog":
            report["anchored_by_official_code"] += 1
        per100 = d["basis"] == "100g"
        toad_first = (cands.get("toadsam") or [{}])[0]
        if toad_first and (toad_first.get("basis") != d["basis"] or not matches(toad_first, {**d["values"], "scaled": True})):
            report["chosen_over_primary_mirror"].append({"name": name, "toadsam_basis": toad_first.get("basis"),
                                                         "toadsam_kcal": toad_first.get("kcal"), "chosen_basis": d["basis"],
                                                         "chosen_kcal": d["values"]["kcal"], "anchor": d["anchor"]})
        if not per100:
            report["basis_100ml_values_withheld"].append(name)
        source, url = SOURCE[kind]
        kang = d["kang"]
        micro = per100 and kang is not None and (kang.get("sugar") is not None or kang.get("sodium") is not None)
        detail = (f"values from {d['value_mirror']}; anchor {d['anchor']}"
                  + (f" (official code {d['code']})" if d["code"] else "")
                  + f"; agrees: {','.join(d['agree']) or 'none (single)'}; commits "
                  + ",".join(f"{m}@{commits[m][:12]}" for m in sorted({d['anchor'], d['value_mirror'], *d['agree']})))
        serving = d["serving"]
        out_rows.append({
            "id": f"{'MFDS' if kind == 'D' else 'RDA'}-{kind}-{i:03d}",
            "food_name": c["display_name"],
            # '~alias' = generic word: offered as a candidate, never auto-matched (review N-4)
            "aliases": ";".join(dict.fromkeys(x for x in [name] + c["aliases"].split(";")
                                              if x and x.lstrip("~") != c["display_name"])),
            "category": c["category"],
            "kcal_per_100g": _fmt(d["values"]["kcal"], 1) if per100 else "",
            "carbs_g_per_100g": _fmt(d["values"]["carb"]) if per100 else "",
            "protein_g_per_100g": _fmt(d["values"]["protein"]) if per100 else "",
            "fat_g_per_100g": _fmt(d["values"]["fat"]) if per100 else "",
            "sugars_g_per_100g": _fmt(kang.get("sugar")) if micro else "",
            "sodium_mg_per_100g": _fmt(kang.get("sodium")) if micro else "",
            "serving_size_g": _fmt(serving, 1) if serving and d["basis"] == "100g" else "",
            "serving_size_ml": _fmt(serving, 1) if serving and d["basis"] == "100ml" else "",
            "serving_unit": "인분" if kind == "D" and serving else "",
            "basis": d["basis"] or "",
            "food_code": d["code"] or "",
            "source": source, "source_url": url, "source_detail": detail, "retrieved_at": retrieved,
            "verification": d["verification"], "micro_verification": "single_mirror" if micro else "",
            "is_demo": 0,
        })
    with a.out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out_rows)
    report["bundled_rows"] = len(out_rows)
    report["rows_with_values"] = sum(1 for r in out_rows if r["kcal_per_100g"] != "")
    a.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: (v if not isinstance(v, (list, dict)) else len(v)) for k, v in report.items() if k != "mirrors"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
