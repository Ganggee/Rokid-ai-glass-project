"""Nutrition reference lookup (per 100 g).

Sources, in order:
1. ``nutrition_references`` table (seeded from a CSV; the bundled CSV is DEMO_MOCK).
2. Optional MFDS 식품영양성분DB OpenAPI (data.go.kr) when MFDS_API_KEY is set.
   Results are cached into the table with source='MFDS'. The operation name and
   response field names are configurable and NOT VERIFIED in this PoC (no key
   was available and outbound access to data.go.kr was not possible).
"""
from __future__ import annotations

import csv
import difflib
import json
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..db import utcnow, write_transaction


def _row(r: sqlite3.Row) -> dict[str, Any]:
    d = {k: r[k] for k in r.keys()}
    d["aliases"] = [a for a in (d.get("aliases") or "").split(";") if a]
    d["is_demo"] = bool(d["is_demo"])
    d.pop("updated_at", None)
    return d


def _float(value: str | None) -> float | None:
    if value is None or str(value).strip() in ("", "-", "N/A"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def load_csv(conn: sqlite3.Connection, path: Path) -> int:
    """Upsert references from CSV (columns as in sample-data/nutrition_demo.csv)."""
    count = 0
    with path.open(encoding="utf-8-sig", newline="") as fh, write_transaction(conn):
        for rec in csv.DictReader(fh):
            conn.execute(
                """INSERT INTO nutrition_references(id, food_name, aliases, kcal_per_100g, carbs_g_per_100g,
                   protein_g_per_100g, fat_g_per_100g, source, source_detail, is_demo, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET food_name=excluded.food_name, aliases=excluded.aliases,
                   kcal_per_100g=excluded.kcal_per_100g, carbs_g_per_100g=excluded.carbs_g_per_100g,
                   protein_g_per_100g=excluded.protein_g_per_100g, fat_g_per_100g=excluded.fat_g_per_100g,
                   source=excluded.source, source_detail=excluded.source_detail, is_demo=excluded.is_demo,
                   updated_at=excluded.updated_at""",
                (rec["id"], rec["food_name"], rec.get("aliases"), _float(rec.get("kcal_per_100g")),
                 _float(rec.get("carbs_g_per_100g")), _float(rec.get("protein_g_per_100g")),
                 _float(rec.get("fat_g_per_100g")), rec.get("source") or "UNKNOWN", rec.get("source_detail"),
                 1 if str(rec.get("is_demo", "1")).strip() in ("1", "true", "True") else 0, utcnow()),
            )
            count += 1
    return count


def ensure_seeded(conn: sqlite3.Connection, csv_path: Path) -> None:
    if conn.execute("SELECT COUNT(*) FROM nutrition_references").fetchone()[0] == 0 and csv_path.is_file():
        load_csv(conn, csv_path)


def get_reference(conn: sqlite3.Connection, ref_id: str) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM nutrition_references WHERE id = ?", (ref_id,)).fetchone()
    return _row(r) if r else None


def list_references(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_row(r) for r in conn.execute("SELECT * FROM nutrition_references ORDER BY food_name").fetchall()]


def search_local(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    q = query.strip().lower().replace(" ", "")
    scored = []
    for r in conn.execute("SELECT * FROM nutrition_references").fetchall():
        names = [r["food_name"]] + [a for a in (r["aliases"] or "").split(";") if a]
        best = 0.0
        for n in names:
            n2 = n.lower().replace(" ", "")
            if not n2:
                continue
            if n2 == q:
                s = 2.0
            elif q and (q in n2 or n2 in q):
                s = 1.0 + min(len(q), len(n2)) / 100
            else:
                s = difflib.SequenceMatcher(None, q, n2).ratio()
            best = max(best, s)
        if best >= 0.6:
            scored.append((best, r))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [_row(r) for _, r in scored[:limit]]


def resolve_label(conn: sqlite3.Connection, label: str) -> dict[str, Any] | None:
    hits = search_local(conn, label, limit=1)
    return hits[0] if hits else None


# ---------------------------------------------------------------- MFDS (optional, NOT VERIFIED)
# Candidate response keys; adjust after checking 출력메세지.xlsx for the current API version.
MFDS_FIELD_CANDIDATES = {
    "food_name": ("FOOD_NM_KR", "foodNm", "DESC_KOR"),
    "kcal": ("AMT_NUM1", "enerc", "NUTR_CONT1"),
    "protein": ("AMT_NUM3", "prot", "NUTR_CONT3"),
    "fat": ("AMT_NUM4", "fatce", "NUTR_CONT4"),
    "carbs": ("AMT_NUM7", "chocdf", "NUTR_CONT2"),
    "base": ("SERVING_SIZE", "nutConSrtrQua"),
    "code": ("FOOD_CD", "foodCd"),
}


def _pick(item: dict, keys) -> Any:
    for k in keys:
        if k in item and item[k] not in (None, ""):
            return item[k]
    return None


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
    out = []
    with write_transaction(conn):
        for it in items:
            name = _pick(it, MFDS_FIELD_CANDIDATES["food_name"])
            if not name:
                continue
            base = str(_pick(it, MFDS_FIELD_CANDIDATES["base"]) or "")
            ref_id = f"MFDS-{_pick(it, MFDS_FIELD_CANDIDATES['code']) or name}"
            values = {k: _float(_pick(it, MFDS_FIELD_CANDIDATES[k])) for k in ("kcal", "carbs", "protein", "fat")}
            per_100g = base.replace(" ", "").lower() in ("100g", "100", "")
            conn.execute(
                """INSERT INTO nutrition_references(id, food_name, aliases, kcal_per_100g, carbs_g_per_100g,
                   protein_g_per_100g, fat_g_per_100g, source, source_detail, is_demo, updated_at)
                   VALUES (?,?,?,?,?,?,?, 'MFDS', ?, 0, ?)
                   ON CONFLICT(id) DO UPDATE SET kcal_per_100g=excluded.kcal_per_100g,
                   carbs_g_per_100g=excluded.carbs_g_per_100g, protein_g_per_100g=excluded.protein_g_per_100g,
                   fat_g_per_100g=excluded.fat_g_per_100g, source_detail=excluded.source_detail,
                   updated_at=excluded.updated_at""",
                (ref_id, name, None,
                 values["kcal"] if per_100g else None, values["carbs"] if per_100g else None,
                 values["protein"] if per_100g else None, values["fat"] if per_100g else None,
                 f"data.go.kr 15127578 base={base or 'unknown'}" + ("" if per_100g else " (not per 100g; values withheld)"),
                 utcnow()),
            )
            out.append(ref_id)
    refs = [get_reference(conn, i) for i in out]
    return {"status": "ok", "items": [r for r in refs if r]}
