"""Nutrition reference lookup (per 100 g).

Sources, best first (one row = one source, never averaged):
1. official_file_import — MFDS standard data file / API imported by scripts/import_nutrition_mfds.py
2. mirror_cross_checked — MFDS standard data taken from >=2 agreeing public GitHub mirrors
   (sample-data/nutrition_reference_public.csv, built by scripts/build_nutrition_reference.py)
3. single_mirror        — same, present in one mirror only
4. web_transcribed      — values copied from a web page (must carry source_quote)
5. demo_mock            — sample-data/nutrition_demo.csv (pipeline testing only)

Matching (advisor P1-7): exact name/alias match (spaces/case ignored) is the only automatic match.
Partial matches ("김밥" contains "밥") are returned as candidates for the user to confirm.
"""
from __future__ import annotations

import csv
import difflib
import hashlib
import json
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from ..db import utcnow, write_transaction

VERIFICATION_RANK = {"official_file_import": 0, "mirror_cross_checked": 1, "single_mirror": 2,
                     "web_transcribed": 3, "legacy_api": 4, "demo_mock": 9}
COLUMNS = ("id", "food_name", "aliases", "category", "kcal_per_100g", "carbs_g_per_100g", "protein_g_per_100g",
           "fat_g_per_100g", "sugars_g_per_100g", "sodium_mg_per_100g", "serving_size_g", "serving_size_ml", "serving_unit",
           "basis", "food_code", "source", "source_url", "source_detail", "retrieved_at", "verification",
           "micro_verification", "is_demo")

# Short list shown first on the glasses when labelling food regions (cycling through 170 names is unusable).
# Must stay in sync with sample-data/nutrition_reference_public.csv (test_r7_hud_priority_names_are_in_the_bundle).
HUD_PRIORITY = ["쌀밥", "잡곡밥", "현미밥", "김밥", "배추김치", "총각김치", "달걀(생것)", "삶은달걀", "된장찌개",
                "김치찌개", "미역국", "콩나물국", "돼지고기볶음", "조기구이", "멸치볶음", "시금치나물",
                "콩나물무침", "두부조림", "떡볶이", "닭가슴살샐러드", "감자샐러드", "사과", "바나나", "우유"]


def _row(r: sqlite3.Row) -> dict[str, Any]:
    d = {k: r[k] for k in r.keys()}
    al = [a for a in (d.get("aliases") or "").split(";") if a]
    d["aliases"] = [a for a in al if not a.startswith("~")]
    d["suggest_aliases"] = [a[1:] for a in al if a.startswith("~")]
    d["is_demo"] = bool(d["is_demo"])
    d.pop("updated_at", None)
    return d


def _float(value) -> float | None:
    if value is None or str(value).strip() in ("", "-", "N/A", "None"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _norm(s: str) -> str:
    return "".join(str(s or "").lower().split())


def upsert_rows(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]], source_file: str | None = None) -> int:
    count = 0
    now = utcnow()
    with write_transaction(conn):
        for rec in rows:
            demo = str(rec.get("is_demo", "0")).strip() in ("1", "true", "True")
            verification = (rec.get("verification") or ("demo_mock" if demo else "single_mirror")).strip()
            values = {
                "id": rec["id"], "food_name": rec["food_name"], "aliases": rec.get("aliases") or None,
                "category": rec.get("category") or None,
                "kcal_per_100g": _float(rec.get("kcal_per_100g")), "carbs_g_per_100g": _float(rec.get("carbs_g_per_100g")),
                "protein_g_per_100g": _float(rec.get("protein_g_per_100g")), "fat_g_per_100g": _float(rec.get("fat_g_per_100g")),
                "sugars_g_per_100g": _float(rec.get("sugars_g_per_100g")), "sodium_mg_per_100g": _float(rec.get("sodium_mg_per_100g")),
                "serving_size_g": _float(rec.get("serving_size_g")), "serving_size_ml": _float(rec.get("serving_size_ml")),
                "serving_unit": rec.get("serving_unit") or None, "micro_verification": rec.get("micro_verification") or None,
                "basis": rec.get("basis") or None, "food_code": rec.get("food_code") or None,
                "source": rec.get("source") or "UNKNOWN", "source_url": rec.get("source_url") or None,
                "source_detail": rec.get("source_detail") or None, "retrieved_at": rec.get("retrieved_at") or None,
                "verification": verification, "is_demo": 1 if demo else 0, "updated_at": now,
                "source_file": source_file, "retired": 0,
            }
            cols = ", ".join(values)
            marks = ", ".join("?" for _ in values)
            updates = ", ".join(f"{k}=excluded.{k}" for k in values if k != "id")
            conn.execute(f"INSERT INTO nutrition_references({cols}) VALUES ({marks}) "
                         f"ON CONFLICT(id) DO UPDATE SET {updates}", tuple(values.values()))
            count += 1
    return count


MIRROR_VERIFICATIONS = ("mirror_cross_checked", "single_mirror")


def load_csv(conn: sqlite3.Connection, path: Path, retire_missing: bool = True) -> int:
    """Upsert references from a CSV with the COLUMNS header (missing columns are allowed).

    Rows that came from the same bundled file before but are no longer in it are RETIRED, not deleted
    (review R-5): past meal-log snapshots keep pointing at them, new matching ignores them. Rows from
    before source_file existed are treated as part of the public bundle when they carry a mirror
    verification."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    n = upsert_rows(conn, rows, source_file=path.name)
    if retire_missing:
        ids = {r["id"] for r in rows}
        mirror_file = any((r.get("verification") or "") in MIRROR_VERIFICATIONS for r in rows)
        with write_transaction(conn):
            for r in conn.execute("SELECT id, source_file, verification FROM nutrition_references WHERE retired = 0").fetchall():
                same_file = r["source_file"] == path.name or (
                    r["source_file"] is None and mirror_file and r["verification"] in MIRROR_VERIFICATIONS)
                if same_file and r["id"] not in ids:
                    conn.execute("UPDATE nutrition_references SET retired = 1, updated_at = ? WHERE id = ?", (utcnow(), r["id"]))
    return n


def ensure_seeded(conn: sqlite3.Connection, csv_paths: Iterable[Path]) -> None:
    """Load each bundled CSV once per content version (sha recorded in schema_meta)."""
    for path in csv_paths:
        if not path.is_file():
            continue
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        key = f"nutrition_csv:{path.name}"
        row = conn.execute("SELECT value FROM schema_meta WHERE key = ?", (key,)).fetchone()
        if row is not None and row["value"] == sha:
            continue
        load_csv(conn, path)
        conn.execute("INSERT INTO schema_meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (key, sha))


def get_reference(conn: sqlite3.Connection, ref_id: str) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM nutrition_references WHERE id = ?", (ref_id,)).fetchone()
    return _row(r) if r else None


def _ranked(rows):
    return sorted(rows, key=lambda r: (VERIFICATION_RANK.get(r["verification"], 5), r["food_name"]))


def list_references(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_row(r) for r in _ranked(conn.execute("SELECT * FROM nutrition_references WHERE retired = 0").fetchall())]


def hud_label_options(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    """A short, ranked list for cycling on the HUD: priority names first, then DEMO rows."""
    refs = list_references(conn)
    by_name: dict[str, dict] = {}
    for r in refs:
        by_name.setdefault(r["food_name"], r)
    out = [by_name[n] for n in HUD_PRIORITY if n in by_name]
    for r in refs:
        if len(out) >= limit:
            break
        if r["is_demo"] and r not in out:
            out.append(r)
    return out[:limit]


def _names(r, auto_only: bool = False) -> list[str]:
    al = [a for a in (r["aliases"] or "").split(";") if a]
    if auto_only:
        return [r["food_name"]] + [a for a in al if not a.startswith("~")]
    return [r["food_name"]] + [a.lstrip("~") for a in al]


def match(conn: sqlite3.Connection, label: str, limit: int = 5) -> dict[str, Any]:
    """{"exact": ref|None, "candidates": [ref...]} — only exact name/alias matches are automatic."""
    q = _norm(label)
    rows = conn.execute("SELECT * FROM nutrition_references WHERE retired = 0").fetchall()
    exact = _ranked([r for r in rows if any(_norm(n) == q for n in _names(r, auto_only=True))])
    # generic words ('~alias', e.g. 된장국 -> 호박된장국) are offered first but never auto-matched (review N-4)
    suggested = _ranked([r for r in rows if any(_norm(n) == q for n in _names(r))])
    scored = []
    for r in rows:
        best = 0.0
        for n in _names(r):
            n2 = _norm(n)
            if not n2 or not q:
                continue
            if q in n2 or n2 in q:
                s = 0.8 + min(len(q), len(n2)) / (10 * max(len(q), len(n2)))
            else:
                s = difflib.SequenceMatcher(None, q, n2).ratio() * 0.8
            best = max(best, s)
        if best >= 0.5:
            scored.append((best, VERIFICATION_RANK.get(r["verification"], 5), r))
    scored.sort(key=lambda t: (-t[0], t[1]))
    chosen = exact[0] if exact else None
    pool, seen = [], set()
    for r in list(exact) + list(suggested) + [r for _, _, r in scored]:
        if r["id"] not in seen:
            seen.add(r["id"])
            pool.append(r)
    # DEMO is never auto-confirmed while any public candidate exists (review R-4, advisor §6)
    if chosen is not None and chosen["is_demo"] and any(not r["is_demo"] for r in pool):
        chosen = None
    cands = [r for r in pool if chosen is None or r["id"] != chosen["id"]]
    public, demo = [r for r in cands if not r["is_demo"]], [r for r in cands if r["is_demo"]]
    keep_public = limit - (1 if demo else 0)            # public first, always; the best DEMO row stays reachable last
    cands = public[:keep_public] + demo[: limit - len(public[:keep_public])]
    return {"exact": _row(chosen) if chosen else None, "candidates": [_row(r) for r in cands]}


def known_names(conn: sqlite3.Connection) -> set[str]:
    """Normalized food names + all aliases (incl. generic ones): the parser's dictionary."""
    out = set()
    for r in conn.execute("SELECT food_name, aliases FROM nutrition_references WHERE retired = 0").fetchall():
        for n in _names(r):
            out.add(_norm(n))
    return out


def search_local(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    m = match(conn, query, limit - 1 if limit > 1 else limit)  # leave room for the exact row
    return ([m["exact"]] if m["exact"] else []) + m["candidates"][: limit - (1 if m["exact"] else 0)]


def resolve_label(conn: sqlite3.Connection, label: str) -> dict[str, Any] | None:
    """Automatic resolution = exact match only (advisor P1-7)."""
    return match(conn, label)["exact"]


# ---------------------------------------------------------------- per-100 g normalisation (shared with importer)
def per_100g_factor(basis: str | None) -> float | None:
    """'100g' -> 1.0 ; '200g' -> 0.5 ; '100mL'/''/unknown -> None (values withheld, no mL->g conversion)."""
    if basis is None:
        return None
    b = str(basis).strip().lower().replace(" ", "")
    if not b or not b.endswith("g") or b.endswith("mg") or b.endswith("kg"):
        return None
    try:
        amount = float(b[:-1])
    except ValueError:
        return None
    return 100.0 / amount if amount > 0 else None


# ---------------------------------------------------------------- MFDS (optional, NOT VERIFIED)
MFDS_FIELD_CANDIDATES = {
    "food_name": ("FOOD_NM_KR", "foodNm", "DESC_KOR"),
    "kcal": ("AMT_NUM1", "enerc", "NUTR_CONT1"),
    "protein": ("AMT_NUM3", "prot", "NUTR_CONT3"),
    "fat": ("AMT_NUM4", "fatce", "NUTR_CONT4"),
    "carbs": ("AMT_NUM7", "chocdf", "NUTR_CONT2"),
    "base": ("NUTRI_AMOUNT_SERVING", "SERVING_SIZE", "nutConSrtrQua"),
    "code": ("FOOD_CD", "foodCd"),
}


def _pick(item: dict, keys) -> Any:
    for k in keys:
        if k in item and item[k] not in (None, ""):
            return item[k]
    return None


def mfds_items_to_rows(items: list[dict], retrieved_at: str, source_url: str) -> list[dict[str, Any]]:
    rows = []
    for it in items:
        name = _pick(it, MFDS_FIELD_CANDIDATES["food_name"])
        if not name:
            continue
        base = _pick(it, MFDS_FIELD_CANDIDATES["base"])
        factor = per_100g_factor(base)
        vals = {k: _float(_pick(it, MFDS_FIELD_CANDIDATES[k])) for k in ("kcal", "carbs", "protein", "fat")}

        def norm(v):
            return None if v is None or factor is None else round(v * factor, 2)

        code = _pick(it, MFDS_FIELD_CANDIDATES["code"])
        rows.append({"id": f"MFDS-API-{code or name}", "food_name": name, "kcal_per_100g": norm(vals["kcal"]),
                     "carbs_g_per_100g": norm(vals["carbs"]), "protein_g_per_100g": norm(vals["protein"]),
                     "fat_g_per_100g": norm(vals["fat"]), "basis": base, "food_code": code, "source": "MFDS_API",
                     "source_url": source_url, "source_detail": "data.go.kr 15127578 OpenAPI",
                     "retrieved_at": retrieved_at, "verification": "official_file_import", "is_demo": 0})
    return rows


def search_mfds(conn: sqlite3.Connection, query: str, api_key: str, base_url: str, operation: str,
                timeout: float = 8.0) -> dict[str, Any]:
    params = urllib.parse.urlencode({"serviceKey": api_key, "pageNo": 1, "numOfRows": 10, "type": "json",
                                     "FOOD_NM_KR": query})
    url = f"{base_url.rstrip('/')}/{operation}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (fixed https endpoint)
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__, "items": []}
    body = payload.get("body") or payload.get("response", {}).get("body") or {}
    items = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    rows = mfds_items_to_rows(items, utcnow()[:10], "https://www.data.go.kr/data/15127578/openapi.do")
    if rows:
        upsert_rows(conn, rows)
    return {"status": "ok", "items": [get_reference(conn, r["id"]) for r in rows]}
