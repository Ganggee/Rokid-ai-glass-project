"""Build sample-data/nutrition_reference_public.csv from public GitHub mirrors of the
MFDS 전국통합식품영양성분정보 표준데이터, with cross-checking between mirrors.

Why mirrors: the official download pages (data.go.kr, various.foodsafetykorea.go.kr) were not
reachable from the development sandbox. The official file import (scripts/import_nutrition_mfds.py)
remains the first-hand path; run it on a PC that can download the official file.

Mirror files are treated as untrusted DATA: they are parsed, never executed.

    git clone --depth 1 --filter=blob:none --no-checkout https://github.com/toadsam/Ajou_MuscleUp M/toadsam_Ajou_MuscleUp
    (cd M/toadsam_Ajou_MuscleUp && git checkout HEAD -- backend/src/main/resources/food/foods.tsv.gz)
    ... same for the other mirrors (see MIRRORS below) ...
    python -I scripts/build_nutrition_reference.py --mirrors M

Rules
* primary values come from the toadsam mirror (it keeps the original basis 100g/100ml and 1인분 g);
* a row is `mirror_cross_checked` when at least one other mirror has the same food name with
  kcal/carb/protein/fat equal (|diff| <= 0.05; health-log values are rescaled from its serving);
* `single_mirror` when no other mirror has that name; EXCLUDED when other mirrors have the name
  but none agrees (reported);
* basis 100ml or missing -> per-100 g values are left empty (no mL->g conversion);
* serving_unit '인분' only for 음식 rows (the source documents 음식 serving as 1인분).
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
OFFICIAL_URL = {
    "D": "https://www.data.go.kr/data/15100070/standard.do",  # 전국통합식품영양성분정보(음식)표준데이터
    "R": "https://www.data.go.kr/data/15100064/standard.do",  # 전국통합식품영양성분정보 표준데이터(원재료성식품 포함)
}
TOL = 0.05
FIELDS = ["id", "food_name", "aliases", "category", "kcal_per_100g", "carbs_g_per_100g", "protein_g_per_100g",
          "fat_g_per_100g", "sugars_g_per_100g", "sodium_mg_per_100g", "serving_size_g", "serving_unit", "basis",
          "food_code", "source", "source_url", "source_detail", "retrieved_at", "verification", "is_demo"]


def f(v):
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "-", "-1"):
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


def load_toadsam(base: Path):
    rows = {}
    with gzip.open(base / MIRRORS["toadsam"][1] / MIRRORS["toadsam"][2]) as fh:
        for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8"), delimiter="\t"):
            if r["src"] in ("D", "R") and not r["maker"]:
                rows.setdefault((r["src"], r["name"]), []).append(r)
    return rows


def load_carb(base: Path):
    data = json.loads((base / MIRRORS["carb"][1] / MIRRORS["carb"][2]).read_text(encoding="utf-8"))["items"]
    out = {}
    for name, carb, kcal, prot, fat, serving, kind in data:
        out.setdefault(name, []).append({"kcal": f(kcal), "carb": f(carb), "protein": f(prot), "fat": f(fat),
                                         "serving": f(serving)})
    return out


def load_kangsogo7(base: Path):
    data = json.loads((base / MIRRORS["kangsogo7"][1] / MIRRORS["kangsogo7"][2]).read_text(encoding="utf-8"))["foods"]
    out = {}
    for row in data:
        name, _kind, brand, kcal, carb, prot, fat, sugar, sodium, serving = row[:10]
        if brand:
            continue
        out.setdefault(name, []).append({"kcal": f(kcal), "carb": f(carb), "protein": f(prot), "fat": f(fat),
                                         "sugar": f(sugar), "sodium": f(sodium), "serving": f(serving)})
    return out


_U = re.compile(r"\\([0-9A-Fa-f]{4})")


def _uesc(s: str) -> str:
    return _U.sub(lambda m: chr(int(m.group(1), 16)), s)


def load_healthlog(base: Path):
    sql = (base / MIRRORS["healthlog"][1] / MIRRORS["healthlog"][2]).read_text(encoding="utf-8")
    out = {}
    pat = re.compile(r"\(U&'([^']*)',\s*(NULL|'[^']*'),\s*U&'[^']*',\s*([\d.]+),\s*'g',\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),"
                     r"\s*([\d.]+),\s*([\d.]+|NULL),\s*([\d.]+|NULL),\s*'public',\s*'([^']+)'")
    for m in pat.finditer(sql):
        name = _uesc(m.group(1))
        serving = float(m.group(3))
        scale = 100.0 / serving
        code = re.search(r"searchFoodCd=([^&]+)", m.group(10))
        out.setdefault(name, []).append({"kcal": float(m.group(4)) * scale, "carb": float(m.group(5)) * scale,
                                         "protein": float(m.group(6)) * scale, "fat": float(m.group(7)) * scale,
                                         "serving": serving, "code": code.group(1) if code else None,
                                         "url": m.group(10), "scaled": True})
    return out


def agrees(p: dict, o: dict, scaled: bool = False) -> bool:
    tol = 0.11 if scaled else TOL  # rescaled from rounded per-serving values
    for k in ("kcal", "carb", "protein", "fat"):
        a, b = p.get(k), o.get(k)
        if a is None or b is None:
            if a is None and b is None:
                continue
            return False
        if abs(a - b) > (tol * max(1.0, abs(a) / 10) if scaled else tol):
            return False
    if not scaled and p.get("serving") and o.get("serving") and abs(p["serving"] - o["serving"]) > TOL:
        return False
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mirrors", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--report", type=Path, default=REPORT)
    a = ap.parse_args(argv)
    retrieved = date.today().isoformat()
    commits = {k: commit_of(a.mirrors / v[1]) for k, v in MIRRORS.items()}
    toad = load_toadsam(a.mirrors)
    others = {"carb": load_carb(a.mirrors), "kangsogo7": load_kangsogo7(a.mirrors), "healthlog": load_healthlog(a.mirrors)}
    curated = list(csv.DictReader(CURATED.open(encoding="utf-8")))
    out_rows, report = [], {"curated": len(curated), "missing_in_primary": [], "excluded_disagreement": [],
                            "cross_checked": 0, "single_mirror": 0, "basis_not_100g": [], "mirrors": {}}
    for k, (repo, _d, path) in MIRRORS.items():
        report["mirrors"][k] = {"repo": repo, "commit": commits[k], "file": path}
    for i, c in enumerate(curated, start=1):
        kind, name = c["kind"], c["db_name"]
        cands = toad.get((kind, name)) or []
        if not cands:
            report["missing_in_primary"].append(name)
            continue
        best = None
        for r in cands:
            p = {"kcal": f(r["kcal"]), "carb": f(r["carb"]), "protein": f(r["protein"]), "fat": f(r["fat"]),
                 "serving": f(r["serving_g"])}
            agree_with, present_in = [], []
            extra = {}
            for mk, db in others.items():
                variants = db.get(name) or []
                if variants:
                    present_in.append(mk)
                for v in variants:
                    if agrees(p, v, scaled=v.get("scaled", False)):
                        agree_with.append(mk)
                        if mk == "kangsogo7":
                            extra["sugar"], extra["sodium"] = v.get("sugar"), v.get("sodium")
                        if mk == "healthlog":
                            extra["code"] = v.get("code")
                        break
            cand = (r, p, agree_with, present_in, extra)
            if best is None or len(agree_with) > len(best[2]):
                best = cand
        r, p, agree_with, present_in, extra = best
        if present_in and not agree_with:
            report["excluded_disagreement"].append({"name": name, "present_in": present_in})
            continue
        verification = "mirror_cross_checked" if agree_with else "single_mirror"
        report["cross_checked" if agree_with else "single_mirror"] += 1
        basis = (r["basis"] or "").strip().lower()
        per100 = basis == "100g"
        if not per100:
            report["basis_not_100g"].append({"name": name, "basis": r["basis"]})
        detail = (f"mirror {MIRRORS['toadsam'][0]}@{commits['toadsam'][:12]}:{MIRRORS['toadsam'][2]} (src={kind});"
                  f" agrees with {','.join(f'{m}@{commits[m][:12]}' for m in agree_with) or 'no other mirror (single)'}")
        out_rows.append({
            "id": f"MFDS-{kind}-{i:03d}",
            "food_name": c["display_name"],
            "aliases": ";".join([x for x in [name] + c["aliases"].split(";") if x and x != c["display_name"]]),
            "category": c["category"],
            "kcal_per_100g": p["kcal"] if per100 else "",
            "carbs_g_per_100g": p["carb"] if per100 else "",
            "protein_g_per_100g": p["protein"] if per100 else "",
            "fat_g_per_100g": p["fat"] if per100 else "",
            "sugars_g_per_100g": (extra.get("sugar") if per100 and extra.get("sugar") is not None else ""),
            "sodium_mg_per_100g": (extra.get("sodium") if per100 and extra.get("sodium") is not None else ""),
            "serving_size_g": p["serving"] or "",
            "serving_unit": "인분" if kind == "D" and p["serving"] else "",
            "basis": r["basis"] or "",
            "food_code": extra.get("code") or "",
            "source": "MFDS_STD_DATA",
            "source_url": OFFICIAL_URL[kind],
            "source_detail": detail,
            "retrieved_at": retrieved,
            "verification": verification,
            "is_demo": 0,
        })
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for row in out_rows:
            w.writerow({k: ("" if v is None else (int(v) if isinstance(v, float) and v.is_integer() else v))
                        for k, v in row.items()})
    report["bundled_rows"] = len(out_rows)
    a.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in report.items() if k != "mirrors"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
