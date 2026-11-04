"""Meal sessions: photo storage, items, before/after analysis and nutrition estimate.

Policy (enforced in code, see build_food_result):
* the consumed share is an ESTIMATE from 2D image area;
* grams are computed only when an initial serving weight exists;
* nutrients only when grams AND a per-100 g reference value exist;
* anything assumed or mocked sets is_demo / source=DEMO_* and is listed in assumptions;
* when the comparison is not trustworthy the ratio is null with a reason — no
  plausible-looking number is filled in.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Optional

from .. import errors
from ..db import utcnow, write_transaction
from ..errors import ApiError
from ..vision import baseline_opencv as cvb
from ..vision.optional_food_model import plugin_status
from . import nutrition_lookup
from .image_io import IncomingImage

ADDED_FOOD_TOLERANCE = 1.15


# ------------------------------------------------------------------ sessions
def create_session(conn: sqlite3.Connection, note: Optional[str] = None) -> dict[str, Any]:
    sid = uuid.uuid4().hex
    now = utcnow()
    conn.execute("INSERT INTO meal_sessions(id, status, note, created_at, updated_at) VALUES (?, 'created', ?, ?, ?)",
                 (sid, note, now, now))
    return {"session_id": sid, "status": "created", "created_at": now}


def _session_row(conn, sid):
    row = conn.execute("SELECT * FROM meal_sessions WHERE id = ?", (sid,)).fetchone()
    if row is None:
        raise ApiError(404, errors.NOT_FOUND, "Meal session not found")
    return row


def _image_rows(conn, sid):
    return {r["kind"]: r for r in conn.execute("SELECT * FROM meal_images WHERE session_id = ?", (sid,)).fetchall()}


def _items(conn, sid) -> list[dict[str, Any]]:
    out = []
    for r in conn.execute("SELECT * FROM meal_items WHERE session_id = ? ORDER BY position", (sid,)).fetchall():
        d = {k: r[k] for k in r.keys()}
        d["before_region"] = json.loads(d["before_region"]) if d["before_region"] else None
        d["after_region"] = json.loads(d["after_region"]) if d["after_region"] else None
        out.append(d)
    return out


def get_session(conn: sqlite3.Connection, sid: str) -> dict[str, Any]:
    s = _session_row(conn, sid)
    imgs = _image_rows(conn, sid)
    latest = conn.execute("SELECT id, created_at, analysis_method, is_demo FROM meal_analyses WHERE session_id = ? "
                          "ORDER BY created_at DESC LIMIT 1", (sid,)).fetchone()
    return {
        "session_id": sid,
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "photos": {k: {"url": f"/api/v1/meals/{sid}/photos/{k}", "width": r["width"], "height": r["height"],
                       "size_bytes": r["size_bytes"], "created_at": r["created_at"],
                       **({"detected_regions": json.loads(r["detected_regions"])} if r["detected_regions"] else {})}
                   for k, r in imgs.items()},
        "items": _items(conn, sid),
        "latest_analysis": dict(latest) if latest else None,
    }


def list_sessions(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT id, status, created_at, updated_at FROM meal_sessions ORDER BY created_at DESC LIMIT ?",
                        (limit,)).fetchall()
    return [{"session_id": r["id"], "status": r["status"], "created_at": r["created_at"], "updated_at": r["updated_at"]}
            for r in rows]


def save_photo(conn: sqlite3.Connection, upload_dir: Path, sid: str, kind: str, image: IncomingImage) -> dict[str, Any]:
    session = _session_row(conn, sid)
    imgs = _image_rows(conn, sid)
    if kind == "after" and "before" not in imgs:
        raise ApiError(409, errors.BEFORE_PHOTO_REQUIRED, "Upload the before-meal photo first")
    clean = image.to_clean_jpeg()
    folder = upload_dir / "meals" / sid
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{kind}.jpg"
    tmp = folder / f".{kind}.{uuid.uuid4().hex}.tmp"
    tmp.write_bytes(clean)
    detected = None
    if kind == "before":
        try:
            detected = cvb.detect_food_regions(clean)
        except Exception:  # candidate detection is a convenience, never a blocker
            detected = []
    now = utcnow()
    with write_transaction(conn):
        conn.execute("DELETE FROM meal_images WHERE session_id = ? AND kind = ?", (sid, kind))
        conn.execute(
            """INSERT INTO meal_images(id, session_id, kind, file_path, mime_type, width, height, size_bytes, sha256,
               detected_regions, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (uuid.uuid4().hex, sid, kind, str(path.relative_to(upload_dir)), "image/jpeg", image.width, image.height,
             len(clean), image.sha256, json.dumps(detected) if detected is not None else None, now),
        )
        new_status = "before_captured" if kind == "before" else "after_captured"
        if kind == "before" and "after" in imgs:
            new_status = "after_captured"  # retake of before keeps the after photo
        conn.execute("UPDATE meal_sessions SET status = ?, updated_at = ? WHERE id = ?", (new_status, now, sid))
        tmp.replace(path)
    result = {"session_id": sid, "kind": kind, "status": new_status, "width": image.width, "height": image.height,
              "stored_bytes": len(clean), "previous_status": session["status"]}
    if kind == "before":
        result["detected_regions"] = detected or []
        result["label_options"] = [{"id": r["id"], "food_name": r["food_name"], "is_demo": r["is_demo"]}
                                   for r in nutrition_lookup.list_references(conn)]
        result["note"] = ("Regions are unlabelled colour/texture candidates. White food on white plates is often "
                          "missed; draw regions in the PC admin page if needed.")
    return result


def photo_path(conn, upload_dir: Path, sid: str, kind: str) -> Path:
    _session_row(conn, sid)
    row = _image_rows(conn, sid).get(kind)
    if row is None:
        raise ApiError(404, errors.NOT_FOUND, f"No {kind} photo")
    return upload_dir / row["file_path"]


def set_items(conn: sqlite3.Connection, sid: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _session_row(conn, sid)
    now = utcnow()
    with write_transaction(conn):
        conn.execute("DELETE FROM meal_items WHERE session_id = ?", (sid,))
        for pos, it in enumerate(items):
            ref_id = it.get("nutrition_ref_id")
            if ref_id and nutrition_lookup.get_reference(conn, ref_id) is None:
                raise ApiError(422, errors.VALIDATION_ERROR, f"Unknown nutrition_ref_id {ref_id}")
            source = it.get("serving_source") or ("user" if it.get("initial_serving_grams") else None)
            conn.execute(
                """INSERT INTO meal_items(id, session_id, position, label, nutrition_ref_id, initial_serving_grams,
                   serving_source, before_region, after_region, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex, sid, pos, it["label"].strip(), ref_id, it.get("initial_serving_grams"), source,
                 json.dumps(it["before_region"]) if it.get("before_region") else None,
                 json.dumps(it["after_region"]) if it.get("after_region") else None, now),
            )
        conn.execute("UPDATE meal_sessions SET updated_at = ? WHERE id = ?", (now, sid))
    return _items(conn, sid)


def delete_session(conn: sqlite3.Connection, upload_dir: Path, sid: str) -> dict[str, Any]:
    _session_row(conn, sid)
    with write_transaction(conn):
        conn.execute("DELETE FROM meal_sessions WHERE id = ?", (sid,))
    shutil.rmtree(upload_dir / "meals" / sid, ignore_errors=True)
    return {"session_id": sid, "deleted": True}


# ------------------------------------------------------------------ analysis
def _round(v, n=1):
    return None if v is None else round(float(v), n)


def build_food_result(label: str, before_px, after_px, initial_g, serving_source, ref, method: str,
                      warnings: list[str], assumptions: list[str]) -> dict[str, Any]:
    remaining = consumed = None
    if before_px is None or before_px <= 0:
        warnings.append("before_area_missing")
    elif "no_food_detected_in_before_region" in warnings:
        pass
    else:
        r = (after_px or 0.0) / before_px
        if r > ADDED_FOOD_TOLERANCE:
            warnings.append("after_area_larger_than_before (food added, moved, or misaligned) - verification needed")
        else:
            if r > 1.0:
                warnings.append("after_area_slightly_larger_than_before_clamped")
                r = 1.0
            remaining, consumed = r, 1.0 - r
    grams = kcal = carbs = protein = fat = None
    if consumed is not None and initial_g:
        grams = initial_g * consumed
        if serving_source == "demo_assumption":
            assumptions.append(f"initial serving {initial_g:g} g is a DEMO assumption, not a measured weight")
        else:
            assumptions.append(f"initial serving {initial_g:g} g entered by the user (not weighed by the system)")
    elif consumed is not None:
        assumptions.append("initial serving weight not provided -> grams and nutrients not computable")
    if grams is not None and ref is not None:
        def per(v):
            return None if v is None else v * grams / 100.0
        kcal, carbs, protein, fat = (per(ref["kcal_per_100g"]), per(ref["carbs_g_per_100g"]),
                                     per(ref["protein_g_per_100g"]), per(ref["fat_g_per_100g"]))
        assumptions.append(f"nutrients per 100 g from {ref['source']} ({ref['food_name']})"
                           + (" - DEMO mock values" if ref["is_demo"] else ""))
    elif grams is not None:
        assumptions.append("no nutrition reference matched this label -> nutrients not computable")
    assumptions.append("2D image area is used as a proxy for amount; volume, density and hidden food are ignored")
    is_demo = bool((ref and ref["is_demo"]) or serving_source == "demo_assumption")
    return {
        "label": label,
        "before_mask_area_px": _round(before_px, 0),
        "after_mask_area_px": _round(after_px, 0),
        "estimated_remaining_ratio": _round(remaining, 3),
        "estimated_consumed_ratio": _round(consumed, 3),
        "initial_serving_grams": initial_g,
        "estimated_consumed_grams": _round(grams),
        "kcal": _round(kcal),
        "carbs_g": _round(carbs),
        "protein_g": _round(protein),
        "fat_g": _round(fat),
        "source": (ref["source"] if ref else None),
        "nutrition_ref_id": (ref["id"] if ref else None),
        "assumptions": assumptions,
        "warnings": warnings,
        "analysis_method": method,
        "is_demo": is_demo,
    }


def analyze(conn: sqlite3.Connection, upload_dir: Path, sid: str, method: str = "auto",
            model_plugin: str = "none") -> dict[str, Any]:
    _session_row(conn, sid)
    imgs = _image_rows(conn, sid)
    if "before" not in imgs or "after" not in imgs:
        raise ApiError(409, errors.PHOTOS_REQUIRED, "Both before and after photos are required")
    before_full = cvb.decode((upload_dir / imgs["before"]["file_path"]).read_bytes())
    after_full = cvb.decode((upload_dir / imgs["after"]["file_path"]).read_bytes())
    before, s_b = cvb.to_proc(before_full)
    after, _ = cvb.to_proc(after_full)
    image_warnings: list[str] = []
    if before_full.shape[:2] != after_full.shape[:2]:
        image_warnings.append("photos_have_different_resolution")
    alignment = cvb.align(before, after)
    if alignment.status != "ok":
        image_warnings.append(f"alignment_failed ({alignment.message}) - results unreliable")
    elif alignment.scale_change and abs(alignment.scale_change - 1.0) > 0.15:
        image_warnings.append("camera_distance_changed_between_photos")
    after_aligned = cvb.warp_to_before(after, alignment, (before.shape[1], before.shape[0]))
    qb, qa = cvb.image_quality(before), cvb.image_quality(after)
    if abs(qb["brightness"] - qa["brightness"]) > 25:
        image_warnings.append("brightness_differs_between_photos")
    for name, q in (("before", qb), ("after", qa)):
        if q["sharpness"] < 30:
            image_warnings.append(f"{name}_photo_blurry")

    model = plugin_status(model_plugin)
    method_note = None
    if method == "model" and not model["available"]:
        method_note = f"model plugin unavailable ({model['reason']}); fell back to OpenCV baseline"
        image_warnings.append(method_note)

    items = _items(conn, sid)
    foods = []
    if not items:
        # no labels: whole plate from detected candidate regions, nutrients not computable
        detected = json.loads(imgs["before"]["detected_regions"] or "[]")
        items = [{"label": f"UNLABELED-{d['id']}", "before_region": d["region"], "after_region": None,
                  "initial_serving_grams": None, "serving_source": None, "nutrition_ref_id": None} for d in detected]
        if not items:
            image_warnings.append("no_items_and_no_detected_regions - label foods or draw regions")
    methods_used = set()
    for it in items:
        warnings: list[str] = []
        assumptions: list[str] = []
        ref = None
        if it.get("nutrition_ref_id"):
            ref = nutrition_lookup.get_reference(conn, it["nutrition_ref_id"])
        elif not it["label"].startswith("UNLABELED"):
            ref = nutrition_lookup.resolve_label(conn, it["label"])
            if ref:
                assumptions.append(f"label '{it['label']}' matched nutrition reference '{ref['food_name']}' by name")
        if it.get("before_region") and it.get("after_region") and method in ("auto", "manual", "model"):
            m = cvb.measure_manual(it["before_region"], it["after_region"], alignment)
        elif it.get("before_region") and method != "manual":
            m = cvb.measure_auto_region(before, after_aligned, it["before_region"], s_b)
        else:
            m = cvb.RegionMeasurement(None, None, "none",
                                      ["no_region_for_item - draw the food region (manual) or use a detected region"])
        methods_used.add(m.method)
        warnings.extend(m.warnings)
        if alignment.status != "ok" and m.method == "auto_mask_in_region":
            warnings.append("alignment_failed_same_region_compared_unaligned")
        foods.append(build_food_result(it["label"], m.before_area_px, m.after_area_px, it.get("initial_serving_grams"),
                                       it.get("serving_source"), ref, m.method, warnings, assumptions))

    def total(key):
        vals = [f[key] for f in foods if f[key] is not None]
        return round(sum(vals), 1) if vals else None

    totals = {k: total(k) for k in ("estimated_consumed_grams", "kcal", "carbs_g", "protein_g", "fat_g")}
    totals_complete = bool(foods) and all(f["kcal"] is not None for f in foods)
    confidence = "low"
    if alignment.status == "ok" and alignment.inlier_ratio >= 0.4 and not image_warnings \
            and all(not f["warnings"] for f in foods):
        confidence = "medium"  # never 'high': 2D area is a proxy
    analysis_method = "+".join(sorted(methods_used)) or "none"
    result = {
        "analysis_id": uuid.uuid4().hex,
        "session_id": sid,
        "created_at": utcnow(),
        "analysis_method": analysis_method,
        "requested_method": method,
        "model_plugin": model,
        "is_demo": any(f["is_demo"] for f in foods),
        "confidence": confidence,
        "alignment": {"status": alignment.status, "method": alignment.message, "inliers": alignment.inliers,
                      "inlier_ratio": alignment.inlier_ratio, "scale_change": alignment.scale_change},
        "image_quality": {"before": {k: round(v, 1) for k, v in qb.items()}, "after": {k: round(v, 1) for k, v in qa.items()}},
        "warnings": image_warnings,
        "foods": foods,
        "totals": totals,
        "totals_complete": totals_complete,
        "disclaimer": "Technical PoC estimate from two 2D photos. Not a measurement of intake and not a clinical "
                      "dietary assessment.",
    }
    now = result["created_at"]
    with write_transaction(conn):
        conn.execute("INSERT INTO meal_analyses(id, session_id, analysis_method, is_demo, result_json, created_at) "
                     "VALUES (?,?,?,?,?,?)", (result["analysis_id"], sid, analysis_method, 1 if result["is_demo"] else 0,
                                             json.dumps(result, ensure_ascii=False), now))
        conn.execute("UPDATE meal_sessions SET status = 'analyzed', updated_at = ? WHERE id = ?", (now, sid))
    return result


def latest_result(conn: sqlite3.Connection, sid: str) -> dict[str, Any]:
    _session_row(conn, sid)
    row = conn.execute("SELECT result_json FROM meal_analyses WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                       (sid,)).fetchone()
    if row is None:
        raise ApiError(404, errors.ANALYSIS_NOT_FOUND, "No analysis yet. POST /analyze first.")
    return json.loads(row["result_json"])
