"""Meal diary: voice/manual/analysis logs with per-item nutrition SNAPSHOTS.

Gram policy (advisor decision 7):
  stated grams -> grams_basis=stated
  quantity x serving_size_g only when the spoken unit equals the reference serving_unit, or no unit was spoken
    -> grams_basis=serving_size (always an estimate)
  otherwise grams/kcal are null with a null_reason (never invented)
Nutrients only when grams AND the per-100 g value exist. Values are copied into meal_log_items at write time.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import date, datetime
from typing import Any

from .. import errors
from ..db import utcnow, write_transaction
from ..errors import ApiError
from . import nutrition_lookup
from .diary_parser import MEAL_KO, parse

MAX_ITEMS = 15
UNIT_EQUIV = {"인분": "인분"}  # only units documented by the source are equivalent to serving_unit


def compute_item(conn: sqlite3.Connection, item: dict[str, Any]) -> dict[str, Any]:
    """Resolve one spoken/typed food into a snapshot row (server-side, client numbers are never trusted)."""
    name = (item.get("food_name") or item.get("name") or "").strip()
    ref = None
    candidates: list[dict] = []
    if item.get("nutrition_ref_id"):
        ref = nutrition_lookup.get_reference(conn, item["nutrition_ref_id"])
        if ref is None:
            raise ApiError(422, errors.VALIDATION_ERROR, f"Unknown nutrition_ref_id {item['nutrition_ref_id']}")
    elif name:
        m = nutrition_lookup.match(conn, name)
        ref, candidates = m["exact"], m["candidates"]
    qty = item.get("quantity")
    unit = item.get("unit")
    grams = item.get("grams")
    basis, reason, volume_ml = "unknown", None, None
    unit_ok = unit is None or (ref is not None and ref.get("serving_unit") and UNIT_EQUIV.get(unit) == ref.get("serving_unit"))
    ml_basis = ref is not None and (ref.get("basis") or "").lower().replace(" ", "") == "100ml"
    if ml_basis and ref.get("serving_size_ml") and unit_ok:
        volume_ml = round((qty if qty else 1) * ref["serving_size_ml"], 1)  # shown as mL, never as g (review N-3)
    if grams is not None:
        if grams <= 0 or grams > 5000:
            raise ApiError(422, errors.VALIDATION_ERROR, "grams must be in (0, 5000]")
        basis = "stated"
        if ml_basis:
            reason = "volume_basis (reference values are per 100 mL; grams are not converted)"
    elif ml_basis:
        reason = "volume_basis (reference values are per 100 mL; mL is not converted to g)"
    elif ref is None:
        reason = "no_exact_nutrition_match"
    elif not ref.get("serving_size_g"):
        reason = "reference_has_no_serving_size"
    elif unit_ok:
        grams = (qty if qty else 1) * ref["serving_size_g"]
        basis = "serving_size"
    else:
        reason = f"unit_mismatch ({unit} vs reference {ref.get('serving_unit') or 'unitless'} serving)"
    per = {k: (ref.get(k) if ref else None) for k in ("kcal_per_100g", "carbs_g_per_100g", "protein_g_per_100g", "fat_g_per_100g")}
    vals = {"kcal": None, "carbs_g": None, "protein_g": None, "fat_g": None}
    if grams is not None and ref is not None and not ml_basis:
        if per["kcal_per_100g"] is None:
            reason = reason or f"no_per_100g_value (basis {ref.get('basis') or 'unknown'})"
        for out_k, per_k in (("kcal", "kcal_per_100g"), ("carbs_g", "carbs_g_per_100g"),
                             ("protein_g", "protein_g_per_100g"), ("fat_g", "fat_g_per_100g")):
            if per[per_k] is not None:
                vals[out_k] = round(per[per_k] * grams / 100.0, 1)
    elif grams is not None:
        reason = reason or "no_exact_nutrition_match"
    return {
        "food_name": ref["food_name"] if ref else name,
        "spoken_text": item.get("text") or item.get("spoken_text") or name,
        "nutrition_ref_id": ref["id"] if ref else None,
        "ref_source": ref["source"] if ref else None,
        "ref_verification": ref["verification"] if ref else None,
        "ref_is_demo": bool(ref and ref["is_demo"]),
        "quantity": qty, "unit": unit,
        "grams": round(grams, 1) if grams is not None else None,
        "grams_basis": basis,
        "volume_ml": volume_ml,
        **per, **vals,
        "null_reason": reason if vals["kcal"] is None else None,
        # nutrient values come from reference tables -> always an estimate, even when grams were stated (review D-1)
        "is_estimate": True,
        "candidates": [{"id": c["id"], "food_name": c["food_name"], "verification": c["verification"],
                        "is_demo": c["is_demo"]} for c in candidates[:3]],
    }


def parse_command(conn: sqlite3.Connection, text: str, now: datetime) -> dict[str, Any]:
    names = nutrition_lookup.known_names(conn)
    result = parse(text, now, known=lambda n: "".join(n.lower().split()) in names)
    if result["intent"] == "record":
        result["items"] = [compute_item(conn, f) for f in result["foods"][:MAX_ITEMS]]
        result["requires_confirmation"] = not result["questions"]
    else:
        result["items"] = []
        result["requires_confirmation"] = False
    result["note"] = "Parsed only. Nothing was saved; confirm on the HUD and POST /api/v1/meal-logs."
    return result


def _check_date(log_date: str, today: date) -> None:
    try:
        d = date.fromisoformat(log_date)
    except ValueError:
        raise ApiError(422, errors.VALIDATION_ERROR, "log_date must be YYYY-MM-DD")
    if d > today:
        raise ApiError(422, "FUTURE_DATE", "Meals cannot be logged for a future date", {"log_date": log_date})
    if (today - d).days > 365:
        raise ApiError(422, "DATE_OUT_OF_RANGE", "Meals older than 365 days cannot be logged")


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _insert_items(conn, log_id: str, items: list[dict]) -> None:
    for pos, it in enumerate(items):
        conn.execute(
            """INSERT INTO meal_log_items(id, log_id, position, food_name, spoken_text, nutrition_ref_id, ref_source,
               ref_verification, ref_is_demo, quantity, unit, grams, grams_basis, kcal_per_100g, carbs_g_per_100g,
               protein_g_per_100g, fat_g_per_100g, kcal, carbs_g, protein_g, fat_g, null_reason, is_estimate, volume_ml)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uuid.uuid4().hex, log_id, pos, it["food_name"], it.get("spoken_text"), it.get("nutrition_ref_id"),
             it.get("ref_source"), it.get("ref_verification"), 1 if it.get("ref_is_demo") else 0, it.get("quantity"),
             it.get("unit"), it.get("grams"), it["grams_basis"], it.get("kcal_per_100g"), it.get("carbs_g_per_100g"),
             it.get("protein_g_per_100g"), it.get("fat_g_per_100g"), it.get("kcal"), it.get("carbs_g"),
             it.get("protein_g"), it.get("fat_g"), it.get("null_reason"), 1 if it.get("is_estimate") else 0,
             it.get("volume_ml")))


def get_log(conn, log_id: str) -> dict[str, Any]:
    r = conn.execute("SELECT * FROM meal_logs WHERE id = ?", (log_id,)).fetchone()
    if r is None:
        raise ApiError(404, errors.NOT_FOUND, "Meal log not found")
    log = {k: r[k] for k in r.keys()}
    log.pop("note", None)
    log["meal_label"] = MEAL_KO[log["meal_type"]]
    items = []
    for i in conn.execute("SELECT * FROM meal_log_items WHERE log_id = ? ORDER BY position", (log_id,)).fetchall():
        d = {k: i[k] for k in i.keys()}
        d["ref_is_demo"], d["is_estimate"] = bool(d["ref_is_demo"]), bool(d["is_estimate"])
        d.pop("log_id", None)
        items.append(d)
    log["items"] = items
    return log


def create_log(conn: sqlite3.Connection, *, log_date: str, meal_type: str, items: list[dict], idempotency_key: str,
               confirmed: bool, today: date, source: str = "voice", utterance: str | None = None) -> dict[str, Any]:
    if not confirmed:
        raise ApiError(400, errors.CONFIRMATION_REQUIRED, "confirmed must be true (confirm on the HUD first)")
    if meal_type not in MEAL_KO:
        raise ApiError(422, errors.VALIDATION_ERROR, "meal_type must be breakfast|lunch|dinner|snack")
    if not items or len(items) > MAX_ITEMS:
        raise ApiError(422, errors.VALIDATION_ERROR, f"1..{MAX_ITEMS} items required")
    _check_date(log_date, today)
    clean_in = [{k: it.get(k) for k in ("food_name", "spoken_text", "nutrition_ref_id", "quantity", "unit", "grams")}
                for it in items]
    fp = _fingerprint({"log_date": log_date, "meal_type": meal_type, "items": clean_in})
    computed = [compute_item(conn, it) for it in clean_in]
    with write_transaction(conn):
        existing = conn.execute("SELECT id, note FROM meal_logs WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if existing is not None:
            if existing["note"] != fp:
                raise ApiError(409, errors.IDEMPOTENCY_KEY_REUSED, "idempotency_key already used for a different log")
            log_id, replayed = existing["id"], True
        else:
            log_id, replayed = uuid.uuid4().hex, False
            conn.execute("INSERT INTO meal_logs(id, log_date, meal_type, source, idempotency_key, utterance, note, created_at) "
                         "VALUES (?,?,?,?,?,?,?,?)", (log_id, log_date, meal_type, source, idempotency_key, utterance, fp, utcnow()))
            _insert_items(conn, log_id, computed)
    return {"log": get_log(conn, log_id), "replayed": replayed}


def from_session(conn: sqlite3.Connection, session_id: str, *, meal_type: str, log_date: str, confirmed: bool,
                 today: date) -> dict[str, Any]:
    if not confirmed:
        raise ApiError(400, errors.CONFIRMATION_REQUIRED, "confirmed must be true")
    if meal_type not in MEAL_KO:
        raise ApiError(422, errors.VALIDATION_ERROR, "meal_type must be breakfast|lunch|dinner|snack")
    _check_date(log_date, today)
    row = conn.execute("SELECT id, result_json FROM meal_analyses WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                       (session_id,)).fetchone()
    if row is None:
        raise ApiError(404, errors.ANALYSIS_NOT_FOUND, "No analysis for this meal session")
    res = json.loads(row["result_json"])
    items = []
    for f in res["foods"]:
        ref = nutrition_lookup.get_reference(conn, f["nutrition_ref_id"]) if f.get("nutrition_ref_id") else None
        items.append({
            "food_name": f["label"], "spoken_text": None, "nutrition_ref_id": f.get("nutrition_ref_id"),
            "ref_source": f.get("source"), "ref_verification": ref["verification"] if ref else None,
            "ref_is_demo": bool(f.get("is_demo")), "quantity": f.get("estimated_consumed_ratio"), "unit": "eaten_ratio",
            "grams": f.get("estimated_consumed_grams"), "grams_basis": "analysis" if f.get("estimated_consumed_grams") is not None else "unknown",
            "kcal_per_100g": ref["kcal_per_100g"] if ref else None, "carbs_g_per_100g": ref["carbs_g_per_100g"] if ref else None,
            "protein_g_per_100g": ref["protein_g_per_100g"] if ref else None, "fat_g_per_100g": ref["fat_g_per_100g"] if ref else None,
            "kcal": f.get("kcal"), "carbs_g": f.get("carbs_g"), "protein_g": f.get("protein_g"), "fat_g": f.get("fat_g"),
            "null_reason": None if f.get("kcal") is not None else "analysis_without_grams_or_reference",
            "is_estimate": True,
        })
    with write_transaction(conn):
        existing = conn.execute("SELECT id FROM meal_logs WHERE analysis_id = ?", (row["id"],)).fetchone()
        if existing:
            return {"log": get_log(conn, existing["id"]), "replayed": True}
        log_id = uuid.uuid4().hex
        conn.execute("INSERT INTO meal_logs(id, log_date, meal_type, source, meal_session_id, analysis_id, created_at) "
                     "VALUES (?,?,?,?,?,?,?)", (log_id, log_date, meal_type, "analysis", session_id, row["id"], utcnow()))
        _insert_items(conn, log_id, items)
    return {"log": get_log(conn, log_id), "replayed": False}


def list_logs(conn, log_date: str, meal_type: str | None = None) -> list[dict[str, Any]]:
    q = "SELECT id FROM meal_logs WHERE log_date = ? AND deleted_at IS NULL"
    args: list = [log_date]
    if meal_type:
        q += " AND meal_type = ?"
        args.append(meal_type)
    order = "CASE meal_type WHEN 'breakfast' THEN 0 WHEN 'lunch' THEN 1 WHEN 'dinner' THEN 2 ELSE 3 END, created_at"
    return [get_log(conn, r["id"]) for r in conn.execute(q + " ORDER BY " + order, args).fetchall()]


def delete_log(conn, log_id: str, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise ApiError(400, errors.CONFIRMATION_REQUIRED, "confirmed must be true")
    get_log(conn, log_id)
    with write_transaction(conn):
        conn.execute("UPDATE meal_logs SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (utcnow(), log_id))
    return {"id": log_id, "deleted": True}


def _sum(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v), 1) if v else None


def summary(conn, log_date: str, meal_type: str | None = None) -> dict[str, Any]:
    logs = list_logs(conn, log_date, meal_type)
    items = [i for lg in logs for i in lg["items"]]
    totals = {k: _sum(i[k] for i in items) for k in ("kcal", "carbs_g", "protein_g", "fat_g")}
    complete = bool(items) and all(i["kcal"] is not None for i in items)
    has_demo = any(i["ref_is_demo"] for i in items)
    is_estimate = bool(items)  # reference-based kcal is always an estimate
    d = date.fromisoformat(log_date)
    head = f"{d.month}월 {d.day}일"
    meals = []
    for lg in logs:
        if lg["meal_label"] not in meals:
            meals.append(lg["meal_label"])
    if not logs:
        speech = f"{head} {MEAL_KO.get(meal_type, '') + ' ' if meal_type else ''}식사 기록이 없습니다."
        lines = [speech]
    else:
        s1 = f"{head} {', '.join(meals)} 기록입니다."
        if totals["kcal"] is None:
            s2 = "열량은 미상입니다."
        else:
            s2 = f"총 약 {round(totals['kcal'])}킬로칼로리, 추정"
            s2 += ("" if complete else ", 일부 열량 미상") + (", DEMO 포함" if has_demo else "") + "입니다."
        names = [i["food_name"] for i in items]
        s3 = ", ".join(names[:3]) + (f" 외 {len(names) - 3}개." if len(names) > 3 else ".")
        speech = " ".join([s1, s2, s3])
        if len(speech) > 150:
            s3 = ", ".join(names[:1]) + f" 외 {len(names) - 1}개."
            speech = " ".join([s1, s2, s3])
        if len(speech) > 150:
            speech = speech[:149] + "…"
        def amount(i):
            if i.get("grams") is not None:
                return f"{round(i['grams'])}g "
            if i.get("volume_ml") is not None:
                return f"{round(i['volume_ml'])}mL "
            return ""

        lines = [f"{lg['meal_label']}: " + ", ".join(
            f"{i['food_name']} {amount(i)}{('약 %dkcal(추정)' % round(i['kcal'])) if i['kcal'] is not None else '열량 미상'}"
            f"{' [DEMO]' if i.get('ref_is_demo') else ''}"
            for i in lg["items"]) for lg in logs]
    return {"date": log_date, "meal_type": meal_type, "logs": logs, "totals": totals, "totals_complete": complete,
            "has_demo": has_demo, "is_estimate": is_estimate, "speech_text": speech, "display_lines": lines,
            "disclaimer": "Estimates for a technical PoC; not a clinical dietary record."}
