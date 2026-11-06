"""Inventory <-> Excel workbook sync (server-side, SERVER mode only).

SQLite stays the source of truth. The workbook (INVENTORY_XLSX_PATH, e.g. inside a OneDrive /
Google Drive / SharePoint synced folder) is a human-editable mirror:

* EXPORT after stock/product changes: sheets `inventory` (same columns as the import format),
  `transactions` (read-only, never imported) and `_sync` (veryHidden, holds only the export_id).
  Written to a temp file and atomically replaced. A locked file (Excel open on Windows) leaves the
  export pending; requests never fail because of Excel.
* IMPORT external edits with a three-way merge per product. The BASELINE is the DB snapshot stored
  for the file's export_id (advisor P0-1) — or the last applied content of that same export_id — so
  an old copy saved over a newer export cannot undo stock use. Unknown/missing export_id -> nothing
  is applied (conflict reported) and the file is not overwritten.
* SAFE auto-apply (poller): only changes with a known baseline and no conflict / invalid row are
  applied automatically. Otherwise status = needs_review, nothing is applied, the file is NOT
  overwritten (the person's edits stay visible) and DB changes accumulate as a pending export until
  the file is fixed or the change is applied from /admin/inventory-sync (manual apply applies the
  valid rows and reports the rejected ones).
* a row the database rejects (duplicate barcode/QR, any constraint) is rolled back alone (SAVEPOINT)
  and reported as invalid; the rest of the sync and later exports continue.
* durability: triggers bump `change_seq` in the same transaction as every product change; an export
  records `exported_seq`. pending = change_seq > exported_seq, so a crash before export is retried.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Any

from .. import errors
from ..db import utcnow, write_transaction
from ..errors import ApiError
from . import inventory_service as inv

FIELDS = inv.PRODUCT_FIELDS
META_FIELDS = tuple(f for f in FIELDS if f not in ("product_id", "stock_qty"))
TEXT_FIELDS = ("product_id", "barcode", "qr_value")
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_replace = os.replace  # indirection so tests can simulate a locked file / a racing save
_link = os.link        # atomic "create only if absent" (compare-and-swap placement, advisor M-1)
KEEP_EXPORTS = 50       # newest successful exports whose snapshots stay usable as merge baselines ...
KEEP_DAYS = 90          # ... OR every successful export younger than this (whichever keeps more; review R-1)
KEEP_MAX_EXPORTS = 5000  # hard cap inside the 90-day window: beyond it keep the newest N + one per day
KEEP_IMPORTS_PER_EXPORT = 5
KEEP_EVENTS = 2000


class TransientRead(Exception):
    """File is being written/synced (truncated zip, unreadable) — retry later, change nothing."""


def path_lock(path: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(Path(path).resolve()), threading.Lock())


# ------------------------------------------------------------------ state helpers
def _get(conn, key: str, default: str = "") -> str:
    r = conn.execute("SELECT value FROM excel_sync_state WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else default


def _set(conn, key: str, value) -> None:
    conn.execute("INSERT INTO excel_sync_state(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, str(value)))


def _event(conn, kind: str, product_id: str | None = None, detail: dict | None = None, **kw) -> None:
    detail = {**(detail or {}), **kw}
    conn.execute("INSERT INTO excel_sync_events(created_at, kind, product_id, detail) VALUES (?,?,?,?)",
                 (utcnow(), kind, product_id, json.dumps(detail, ensure_ascii=False, default=str)))


def is_pending(conn) -> bool:
    return int(_get(conn, "change_seq", "0")) > int(_get(conn, "exported_seq", "0"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _norm(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


# ------------------------------------------------------------------ export
def _pack(text: str) -> str:
    """Snapshots are stored zlib-compressed (base64, 'z1:' prefix) to keep the 90-day window small."""
    import base64
    import zlib

    return "z1:" + base64.b64encode(zlib.compress(text.encode("utf-8"), 9)).decode("ascii")


def _unpack(stored: str) -> str:
    if stored.startswith("z1:"):
        import base64
        import zlib

        return zlib.decompress(base64.b64decode(stored[3:])).decode("utf-8")
    return stored  # rows written before compression


def _snapshot(conn):
    conn.execute("BEGIN")
    try:
        seq = int(_get(conn, "change_seq", "0"))
        rows = conn.execute("SELECT * FROM products ORDER BY product_id").fetchall()
        tx = conn.execute("SELECT * FROM inventory_transactions ORDER BY id DESC LIMIT 500").fetchall()
    finally:
        conn.execute("COMMIT")
    snap = {r["product_id"]: {f: r[f] for f in FIELDS} for r in rows}
    return seq, snap, tx


def _write_workbook(tmp: Path, export_id: str, snap: dict, tx) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "inventory"
    ws.append(list(FIELDS))
    for p in snap.values():
        ws.append([p[f] for f in FIELDS])
    for col_idx, f in enumerate(FIELDS, start=1):
        if f in TEXT_FIELDS:
            for row in ws.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
                for c in row:
                    c.number_format = "@"
    ws.freeze_panes = "A2"
    wt = wb.create_sheet("transactions")
    wt.append(["READ ONLY - not imported. 수정해도 반영되지 않습니다."])
    wt.append(["id", "created_at", "product_id", "tx_type", "quantity_delta", "stock_before", "stock_after", "source", "note"])
    for t in tx:
        wt.append([t["id"], t["created_at"], t["product_id"], t["tx_type"], t["quantity_delta"], t["stock_before"],
                   t["stock_after"], t["source"], t["note"]])
    meta = wb.create_sheet("_sync")
    meta.append(["export_id", export_id])
    meta.append(["exported_at", utcnow()])
    meta.append(["note", "Do not edit. Used to merge your edits safely."])
    meta.sheet_state = "veryHidden"
    wb.save(tmp)


def _stat(path: Path):
    st = path.stat()
    return [st.st_size, st.st_mtime_ns]


def _retain(conn) -> None:
    """Bounded storage: newest KEEP_EXPORTS exports, plus every export younger than KEEP_DAYS, plus the
    export_id currently in the file. Snapshots are content-deduplicated, so the 90-day window costs one
    snapshot per distinct stock state, not one per export."""
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat(timespec="milliseconds")
    keep = {r["export_id"] for r in conn.execute(
        "SELECT export_id FROM excel_exports WHERE status = 'written' ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (KEEP_EXPORTS,)).fetchall()}
    window = [(r["export_id"], r["created_at"]) for r in conn.execute(
        "SELECT export_id, created_at FROM excel_exports WHERE status = 'written' AND created_at >= ? "
        "ORDER BY created_at DESC, rowid DESC", (cutoff,)).fetchall()]
    if len(window) > KEEP_MAX_EXPORTS:  # busy server: newest N + the latest export of each older day
        keep |= {eid for eid, _ in window[:KEEP_MAX_EXPORTS]}
        days_seen: set = set()
        for eid, created in window[KEEP_MAX_EXPORTS:]:
            if created[:10] not in days_seen:
                days_seen.add(created[:10])
                keep.add(eid)
    else:
        keep |= {eid for eid, _ in window}
    for k in ("file_export_id", "last_export_id"):
        v = _get(conn, k)
        if v:
            keep.add(v)
    for r in conn.execute("SELECT export_id FROM excel_exports").fetchall():
        if r["export_id"] not in keep:
            conn.execute("DELETE FROM excel_exports WHERE export_id = ?", (r["export_id"],))
    conn.execute("DELETE FROM excel_imports WHERE export_id NOT IN (SELECT export_id FROM excel_exports)")
    conn.execute("""DELETE FROM excel_imports WHERE id IN (
                      SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY export_id ORDER BY id DESC) AS rn
                                      FROM excel_imports) WHERE rn > ?)""", (KEEP_IMPORTS_PER_EXPORT,))
    conn.execute("DELETE FROM excel_snapshots WHERE sha NOT IN (SELECT snapshot_sha FROM excel_exports)")
    conn.execute("DELETE FROM excel_sync_events WHERE id <= (SELECT MAX(id) FROM excel_sync_events) - ?", (KEEP_EVENTS,))


def _acceptable_to_overwrite(conn, sha: str) -> bool:
    """The file may be replaced only if it is our last export or content we have already merged."""
    if sha == _get(conn, "last_export_sha"):
        return True
    return conn.execute("SELECT 1 FROM excel_imports WHERE file_sha256 = ?", (sha,)).fetchone() is not None


def _place(conn, tmp: Path, path: Path, force: bool = False) -> str:
    """Compare-and-swap placement of a freshly written export (advisor M-1 / F-1).

    1. move the current file aside (atomic rename; a locked file raises -> pending_locked)
    2. verify the moved file is our last export or already-merged content; otherwise put it back
       and defer (the person's save wins, it is merged on the next poll)
    3. place the new file with os.link = create-only-if-absent, so a save that lands between
       steps 1 and 3 is never overwritten. Filesystems without hard links fall back to os.replace
       (tiny residual window; status reports cas_mode=replace).
    Returns "placed" or a short reason string."""
    aside = None
    if path.exists():
        aside = path.with_name(f".~sync-aside-{uuid.uuid4().hex}{path.suffix}")
        _replace(path, aside)
        if not force and not _acceptable_to_overwrite(conn, _sha(aside)):
            try:
                _link(aside, path)
                aside.unlink()
            except FileExistsError:  # yet another save arrived: keep the newest at the path
                _keep_aside(conn, aside, path)
            except OSError:
                if not path.exists():
                    _replace(aside, path)
                else:
                    _keep_aside(conn, aside, path)
            return "external_change_before_write"
    try:
        _link(tmp, path)
        tmp.unlink()
        mode = "link"
    except FileExistsError:
        if aside is not None:
            aside.unlink()  # our own previous export (verified above); the new file at the path is the person's
        return "external_change_during_write"
    except (OSError, AttributeError, NotImplementedError):
        if path.exists():  # appeared meanwhile and we cannot do an exclusive create: never overwrite it
            if aside is not None:
                aside.unlink()
            return "external_change_during_write"
        _replace(tmp, path)
        mode = "replace"
    if aside is not None:
        try:
            aside.unlink()
        except OSError:
            pass
    with write_transaction(conn):
        _set(conn, "cas_mode", mode)
    return "placed"


def _keep_aside(conn, aside: Path, path: Path) -> None:
    """Two saves raced with an export: keep the older one as a visible conflict copy (never merged)."""
    keep = path.with_name(f"{path.stem} (sync-conflict {uuid.uuid4().hex[:6]}){path.suffix}")
    _replace(aside, keep)
    with write_transaction(conn):
        _event(conn, "conflict_copy_created", None, file=keep.name)


def export(conn, path: Path, reason: str = "change", observed: dict | None = None, force: bool = False) -> dict[str, Any]:
    """force=True only for the explicit operator action 'discard_file' (the file was backed up first)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    seq, snap, tx = _snapshot(conn)
    export_id = uuid.uuid4().hex
    tmp = path.with_name(f".~sync-{export_id}.tmp.xlsx")
    _write_workbook(tmp, export_id, snap, tx)
    sha = _sha(tmp)
    snap_json = json.dumps(snap, ensure_ascii=False, sort_keys=True)
    snap_sha = hashlib.sha256(snap_json.encode("utf-8")).hexdigest()
    now = utcnow()
    # record the baseline BEFORE the file appears, so a crash cannot leave a file with an unknown export_id
    with write_transaction(conn):
        conn.execute("INSERT OR IGNORE INTO excel_snapshots(sha, snapshot_json, created_at) VALUES (?,?,?)",
                     (snap_sha, _pack(snap_json), now))
        conn.execute("INSERT INTO excel_exports(export_id, path, change_seq, snapshot_sha, sha256, status, created_at) "
                     "VALUES (?,?,?,?,?, 'writing', ?)", (export_id, str(path), seq, snap_sha, sha, now))
    try:
        placed = _place(conn, tmp, path, force=force)
    except OSError as exc:  # PermissionError on Windows while Excel has the file open
        try:
            tmp.unlink()
        except OSError:
            pass
        reason_txt = f"file locked or not writable ({type(exc).__name__})"
        with write_transaction(conn):  # failed attempts leave no rows behind
            conn.execute("DELETE FROM excel_exports WHERE export_id = ?", (export_id,))
            conn.execute("DELETE FROM excel_snapshots WHERE sha = ? AND sha NOT IN (SELECT snapshot_sha FROM excel_exports)",
                         (snap_sha,))
            if _get(conn, "pending_reason") != reason_txt:
                _event(conn, "export_failed", error=type(exc).__name__, reason=reason)
            _set(conn, "pending_reason", reason_txt)
        return {"status": "pending_locked", "export_id": None, "error": type(exc).__name__}
    if placed != "placed":  # the file changed under us: keep the person's version, merge it next poll
        try:
            tmp.unlink()
        except OSError:
            pass
        with write_transaction(conn):
            conn.execute("DELETE FROM excel_exports WHERE export_id = ?", (export_id,))
            conn.execute("DELETE FROM excel_snapshots WHERE sha = ? AND sha NOT IN (SELECT snapshot_sha FROM excel_exports)",
                         (snap_sha,))
            _event(conn, "export_deferred_external_change", None, why=placed, reason=reason)
            _set(conn, "pending_reason", "file changed while exporting; merging it first")
        return {"status": "deferred_changed", "export_id": None, "detail": placed}
    with write_transaction(conn):
        conn.execute("UPDATE excel_exports SET status = 'written' WHERE export_id = ?", (export_id,))
        if seq > int(_get(conn, "exported_seq", "0")):
            _set(conn, "exported_seq", seq)
        _set(conn, "last_export_id", export_id)
        _set(conn, "file_export_id", export_id)
        _set(conn, "last_export_sha", sha)
        _set(conn, "last_export_at", now)
        _set(conn, "pending_reason", "")
        _retain(conn)
    if observed is not None:  # our own write is a stable state, not "unstable" (review X-5)
        observed[str(path)] = _stat(path)
    return {"status": "exported", "export_id": export_id, "products": len(snap), "change_seq": seq}


# ------------------------------------------------------------------ read
def read_workbook(path: Path) -> dict[str, Any]:
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        wb = load_workbook(path, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, EOFError, OSError, ValueError) as exc:
        raise TransientRead(type(exc).__name__)
    raw_ws = None
    export_id = None
    if "_sync" in wb.sheetnames:
        ws = wb["_sync"]
        if ws.cell(1, 1).value == "export_id":
            export_id = _norm(ws.cell(1, 2).value)
    base = {"export_id": export_id, "rows": {}, "invalid": [], "invalid_pids": set(), "structure_ok": False}
    if "inventory" not in wb.sheetnames:
        base["invalid"].append({"row": None, "message": "sheet 'inventory' missing"})
        return base
    ws = wb["inventory"]
    it = ws.iter_rows(values_only=True)
    try:
        headers = [str(h).strip() if h is not None else "" for h in next(it)]
    except StopIteration:
        base["invalid"].append({"row": None, "message": "empty sheet"})
        return base
    colmap = inv.build_column_mapping(headers)
    if "product_id" not in colmap or "stock_qty" not in colmap:
        base["invalid"].append({"row": 1, "message": "product_id/stock_qty columns missing"})
        return base
    idx = {f: headers.index(h) for f, h in colmap.items()}
    rows, invalid, invalid_pids = {}, [], set()
    for n, values in enumerate(it, start=2):
        if values is None or all(v is None or str(v).strip() == "" for v in values):
            continue
        get = lambda f: values[idx[f]] if f in idx and idx[f] < len(values) else None  # noqa: E731
        pid = _norm(inv._cell_to_str(get("product_id"))[0])
        if not pid:
            invalid.append({"row": n, "message": "product_id empty"})
            continue

        def bad(msg):
            invalid.append({"row": n, "product_id": pid, "message": msg})
            invalid_pids.add(pid)

        if pid in rows:
            bad("duplicate product_id")
            continue
        q = get("stock_qty")
        if q is None:
            if raw_ws is None:
                raw_ws = load_workbook(path, data_only=False)["inventory"]
            raw = raw_ws.cell(n, idx["stock_qty"] + 1).value
            if isinstance(raw, str) and raw.startswith("="):
                bad(f"stock_qty is a formula without cached value (formula_without_cached_value: {raw}); type a number")
            else:
                bad("stock_qty empty")
            continue
        if isinstance(q, bool):
            bad(f"stock_qty invalid: {q!r}")
            continue
        try:
            qf = float(q)
        except (TypeError, ValueError):
            bad(f"stock_qty not a number: {q!r}")
            continue
        if not qf.is_integer() or qf < 0:
            bad(f"stock_qty must be an integer >= 0: {q!r}")
            continue
        rec = {"product_id": pid, "stock_qty": int(qf)}
        for f in META_FIELDS:
            rec[f] = _norm(inv._cell_to_str(get(f))[0]) if f in idx else None
        rec["_row"] = n
        rows[pid] = rec
    base.update(rows=rows, invalid=invalid, invalid_pids=invalid_pids, structure_ok=True)
    return base


# ------------------------------------------------------------------ merge
def _baseline(conn, export_id: str | None) -> dict | None:
    if not export_id:
        return None
    imp = conn.execute("SELECT excel_snapshot_json FROM excel_imports WHERE export_id = ? ORDER BY id DESC LIMIT 1",
                       (export_id,)).fetchone()
    if imp is not None:
        return json.loads(imp["excel_snapshot_json"])
    exp = conn.execute("SELECT s.snapshot_json FROM excel_exports e JOIN excel_snapshots s ON s.sha = e.snapshot_sha "
                       "WHERE e.export_id = ?", (export_id,)).fetchone()
    return json.loads(_unpack(exp["snapshot_json"])) if exp else None


def plan_merge(conn, excel: dict, policy: str = "merge_delta", base_override: dict | None = None) -> dict[str, Any]:
    """conflicts = cases where something would be lost or cannot be decided (negative merge, metadata
    changed on both sides, db_wins/excel_wins overrides). A merge_delta of two independent stock deltas
    keeps both and is listed in `merges` (safe)."""
    plan = {"export_id": excel["export_id"], "stock_changes": [], "meta_changes": [], "creates": [], "merges": [],
            "conflicts": [], "warnings": [], "invalid": list(excel["invalid"]), "blocked": None}
    if not excel["structure_ok"]:
        plan["blocked"] = "invalid_structure"
        return plan
    base = base_override if base_override is not None else _baseline(conn, excel["export_id"])
    if base is None:
        plan["blocked"] = "unknown_baseline (missing/unknown export_id: file not created by this server or _sync sheet removed)"
        return plan
    db = {r["product_id"]: dict(r) for r in conn.execute("SELECT * FROM products").fetchall()}
    owner = {(r["code_type"], r["code_value"]): r["product_id"] for r in conn.execute("SELECT * FROM product_codes")}

    def code_clash(pid, rec):
        for ctype, field in (("barcode", "barcode"), ("qr", "qr_value")):
            v = rec.get(field)
            if v and owner.get((ctype, v)) not in (None, pid):
                return f"{field} '{v}' already used by product {owner[(ctype, v)]}"
        return None

    def claim(pid, rec):
        for ctype, field in (("barcode", "barcode"), ("qr", "qr_value")):
            if rec.get(field):
                owner[(ctype, rec[field])] = pid

    for pid, ex in excel["rows"].items():
        b, d = base.get(pid), db.get(pid)
        if d is None and b is None:
            if not ex.get("product_name"):
                plan["invalid"].append({"row": ex["_row"], "product_id": pid, "message": "new product needs product_name"})
                continue
            clash = code_clash(pid, ex)
            if clash:
                plan["invalid"].append({"row": ex["_row"], "product_id": pid,
                                        "message": f"new product rejected: {clash} (product_id typo or copied row?)"})
                continue
            claim(pid, ex)
            plan["creates"].append({k: v for k, v in ex.items() if k != "_row"})
            continue
        if d is None:
            plan["warnings"].append({"product_id": pid, "kind": "product_missing_in_db"})
            continue
        if b is None:
            if ex["stock_qty"] != d["stock_qty"]:
                plan["conflicts"].append({"product_id": pid, "kind": "row_added_for_existing_product", "excel": ex["stock_qty"],
                                          "db": d["stock_qty"], "action": "kept_db"})
            continue
        exq, bq, dq = ex["stock_qty"], b["stock_qty"], d["stock_qty"]
        if exq != bq:
            if dq == bq:
                plan["stock_changes"].append({"product_id": pid, "from": dq, "to": exq, "kind": "excel_edit"})
            elif policy == "db_wins":
                plan["conflicts"].append({"product_id": pid, "kind": "both_changed", "base": bq, "db": dq, "excel": exq, "action": "kept_db"})
            elif policy == "excel_wins":
                plan["stock_changes"].append({"product_id": pid, "from": dq, "to": exq, "kind": "both_changed_excel_wins"})
                plan["conflicts"].append({"product_id": pid, "kind": "both_changed", "base": bq, "db": dq, "excel": exq, "action": "excel_wins"})
            else:
                new = dq + (exq - bq)
                if new < 0:
                    plan["conflicts"].append({"product_id": pid, "kind": "merge_would_be_negative", "base": bq, "db": dq,
                                              "excel": exq, "action": "kept_db"})
                else:
                    plan["stock_changes"].append({"product_id": pid, "from": dq, "to": new, "kind": "merge_delta"})
                    plan["merges"].append({"product_id": pid, "kind": "both_changed", "base": bq, "db": dq, "excel": exq,
                                           "action": f"merged_to_{new}"})
        meta = {}
        for f in META_FIELDS:
            ev, bv, dv = _norm(ex.get(f)), _norm(b.get(f)), _norm(d.get(f))
            if ev == bv:
                continue
            if dv == bv:
                if f == "product_name" and not ev:
                    continue
                meta[f] = ev
            else:
                plan["conflicts"].append({"product_id": pid, "kind": "metadata_both_changed", "field": f, "action": "kept_db"})
        if meta:
            clash = code_clash(pid, meta)
            if clash:
                plan["invalid"].append({"row": ex["_row"], "product_id": pid, "message": f"metadata change rejected: {clash}"})
                for f in ("barcode", "qr_value"):
                    meta.pop(f, None)
            else:
                claim(pid, meta)
        if meta:
            plan["meta_changes"].append({"product_id": pid, "fields": meta})
    for pid in base:
        if pid in db and pid not in excel["rows"] and pid not in excel["invalid_pids"]:
            plan["warnings"].append({"product_id": pid, "kind": "row_missing (never deleted; restored on next export)"})
    return plan


def is_safe(plan: dict) -> bool:
    return not plan["blocked"] and not plan["conflicts"] and not plan["invalid"]


def _row_step(conn, plan: dict, pid: str, row, fn) -> bool:
    """Run one change inside a SAVEPOINT; a database rejection rolls back only this row (review X-1)."""
    conn.execute("SAVEPOINT xs_row")
    try:
        fn()
    except sqlite3.IntegrityError as exc:
        conn.execute("ROLLBACK TO xs_row")
        conn.execute("RELEASE xs_row")
        plan["invalid"].append({"row": row, "product_id": pid, "message": f"rejected by database: {exc}"})
        return False
    conn.execute("RELEASE xs_row")
    return True


def _apply(conn, plan: dict, file_sha: str, excel: dict) -> dict[str, Any]:
    now = utcnow()
    applied = {"stock": 0, "meta": 0, "created": 0}
    rows = excel["rows"]

    for ch in plan["stock_changes"]:
        pid = ch["product_id"]

        def do_stock(ch=ch, pid=pid):
            cur = conn.execute("SELECT stock_qty FROM products WHERE product_id = ?", (pid,)).fetchone()["stock_qty"]
            if cur != ch["from"]:
                raise RuntimeError("stock changed during merge")  # cannot happen inside BEGIN IMMEDIATE
            if ch["to"] == cur:
                return
            conn.execute("UPDATE products SET stock_qty = ?, updated_at = ? WHERE product_id = ?", (ch["to"], now, pid))
            conn.execute("""INSERT INTO inventory_transactions(product_id, tx_type, quantity_delta, stock_before, stock_after,
                            source, note, created_at) VALUES (?, 'adjust', ?, ?, ?, 'excel_sync', ?, ?)""",
                         (pid, ch["to"] - cur, cur, ch["to"], f"{ch['kind']} export={plan['export_id'][:8]}", now))
            _event(conn, "stock_" + ch["kind"], pid, before=cur, after=ch["to"])

        if _row_step(conn, plan, pid, rows.get(pid, {}).get("_row"), do_stock):
            applied["stock"] += 1

    for mc in plan["meta_changes"]:
        pid = mc["product_id"]

        def do_meta(mc=mc, pid=pid):
            sets = ", ".join(f"{k} = ?" for k in mc["fields"])
            conn.execute(f"UPDATE products SET {sets}, updated_at = ? WHERE product_id = ?", (*mc["fields"].values(), now, pid))
            f = mc["fields"]
            if "barcode" in f or "qr_value" in f:
                row = conn.execute("SELECT barcode, qr_value FROM products WHERE product_id = ?", (pid,)).fetchone()
                inv._set_codes(conn, pid, row["barcode"], row["qr_value"])
            _event(conn, "metadata_update", pid, fields=list(f))

        if _row_step(conn, plan, pid, rows.get(pid, {}).get("_row"), do_meta):
            applied["meta"] += 1

    for c in plan["creates"]:
        pid = c["product_id"]

        def do_create(c=c, pid=pid):
            conn.execute("""INSERT INTO products(product_id, product_name, category, stock_qty, unit, barcode, qr_value, lot_no,
                            expiration_date, location, aliases, is_demo, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
                         (pid, c["product_name"], c.get("category"), c["stock_qty"], c.get("unit") or "ea",
                          c.get("barcode"), c.get("qr_value"), c.get("lot_no"), c.get("expiration_date"), c.get("location"),
                          c.get("aliases"), now, now))
            conn.execute("""INSERT INTO inventory_transactions(product_id, tx_type, quantity_delta, stock_before, stock_after,
                            source, note, created_at) VALUES (?, 'seed', ?, 0, ?, 'excel_sync', 'created from Excel row', ?)""",
                         (pid, c["stock_qty"], c["stock_qty"], now))
            inv._set_codes(conn, pid, c.get("barcode"), c.get("qr_value"))
            _event(conn, "product_created", pid)

        if _row_step(conn, plan, pid, rows.get(pid, {}).get("_row"), do_create):
            applied["created"] += 1

    for cf in plan["conflicts"]:
        _event(conn, "conflict", cf.get("product_id"), cf)
    for m in plan["merges"]:
        _event(conn, "merge", m.get("product_id"), m)
    for w in plan["warnings"]:
        _event(conn, "warning", w.get("product_id"), w)
    for bad in plan["invalid"]:
        _event(conn, "invalid_row", bad.get("product_id"), bad)
    snapshot = {pid: {k: v for k, v in r.items() if k != "_row"} for pid, r in excel["rows"].items()}
    result = {"applied": applied, "conflicts": len(plan["conflicts"]), "invalid": len(plan["invalid"])}
    conn.execute("INSERT OR IGNORE INTO excel_imports(export_id, file_sha256, excel_snapshot_json, result_json, applied_at) VALUES (?,?,?,?,?)",
                 (plan["export_id"], file_sha, json.dumps(snapshot, ensure_ascii=False), json.dumps(result), now))
    return result


# ------------------------------------------------------------------ orchestration
# Sync-client conflict copies only: " (1)" (Windows / Google Drive), "-PCNAME" (OneDrive, upper-case host name),
# "(... conflicted copy ...)" (Dropbox), "(충돌 ...)".
CONFLICT_COPY = re.compile(r"^(\s\(\d+\)|\s?\([^)]*conflicted copy[^)]*\)|\s\(sync-conflict [0-9a-f]+\)|-[A-Z0-9][A-Z0-9-]{2,30}|\s?\(충돌[^)]*\))$")


def conflict_copies(path: Path) -> list[str]:
    stem, out = path.stem, []
    if not path.parent.is_dir():
        return out
    for p in path.parent.iterdir():
        if p == path or not p.is_file() or p.name.startswith((".~sync-", "~$", ".~lock.")):
            continue
        if p.suffix.lower() in (".xlsx", ".xlsm") and p.stem.startswith(stem) and CONFLICT_COPY.match(p.stem[len(stem):]):
            out.append(p.name)
    return sorted(out)


def lock_file_present(path: Path) -> bool:
    """Excel: `~$name.xlsx` (long names: first 2 chars replaced). LibreOffice: `.~lock.name.xlsx#`."""
    d = path.parent
    return ((d / ("~$" + path.name)).exists() or (d / ("~$" + path.name[2:])).exists()
            or (d / f".~lock.{path.name}#").exists())


def _note_problem(conn, kind: str, sha: str, **detail) -> None:
    """Log blocked / needs_review / error once per file content (polls repeat every N seconds)."""
    key = f"{kind}:{sha}"
    if _get(conn, "last_problem") != key:
        _event(conn, kind, None, file_sha=sha, **detail)
        _set(conn, "last_problem", key)


def sync_once(conn, path: Path, *, apply: bool, policy: str = "merge_delta", require_stable: bool = False,
              observed: dict | None = None, dry_run: bool = False, auto: bool = False) -> dict[str, Any]:
    """One deterministic sync step. Returns a result dict (also stored as last_result).

    apply=False: report external edits only.  auto=True (poller): apply only safe plans (is_safe).
    auto=False with apply=True (admin / API, confirmed): apply valid rows, report rejected ones."""
    path = Path(path)
    with path_lock(path):
        res: dict[str, Any] = {"at": utcnow(), "path": str(path), "warnings": []}
        copies = conflict_copies(path)
        if copies:
            res["warnings"].append({"kind": "conflict_copies_ignored", "files": copies})
        if path.exists():
            if lock_file_present(path):
                res["status"] = "deferred_locked_by_excel"
                return _finish(conn, res, dry_run)
            stat = _stat(path)
            if observed is not None:
                prev = observed.get(str(path))
                observed[str(path)] = stat  # also on the startup sync, so the first poll is not "unstable" (X-5)
                if require_stable and prev != stat:
                    res["status"] = "deferred_unstable"
                    return _finish(conn, res, dry_run)
            sha = _sha(path)
            known_import = conn.execute("SELECT 1 FROM excel_imports WHERE file_sha256 = ?", (sha,)).fetchone()
            if sha != _get(conn, "last_export_sha") and not known_import:
                try:
                    excel = read_workbook(path)
                except TransientRead as exc:
                    res["status"] = "deferred_unreadable"
                    res["error"] = str(exc)
                    return _finish(conn, res, dry_run)
                if excel["export_id"] and not dry_run:
                    with write_transaction(conn):
                        _set(conn, "file_export_id", excel["export_id"])
                plan = plan_merge(conn, excel, policy)
                res["plan"] = plan
                if plan["blocked"]:
                    res["status"] = "blocked"
                    if not dry_run:
                        with write_transaction(conn):
                            _note_problem(conn, "blocked", sha, reason=plan["blocked"])
                    return _finish(conn, res, dry_run)  # never overwrite a file we cannot merge
                if dry_run:
                    # simulate the apply and roll back, so database rejections show up in the preview too
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        _apply(conn, plan, sha, excel)
                    except Exception as exc:  # noqa: BLE001 - reported, never raised to the client
                        res["error"] = f"{type(exc).__name__}: {exc}"
                    finally:
                        conn.execute("ROLLBACK")
                    res["status"] = "preview"
                    res["safe_for_auto_apply"] = is_safe(plan)
                    return res
                if not apply:
                    res["status"] = "external_changes_pending_confirmation"
                    return _finish(conn, res, dry_run)
                if auto and not is_safe(plan):
                    res["status"] = "needs_review"
                    with write_transaction(conn):
                        _note_problem(conn, "needs_review", sha, conflicts=len(plan["conflicts"]), invalid=len(plan["invalid"]))
                    return _finish(conn, res, dry_run)  # export held: the person's edits stay in the file
                try:
                    with write_transaction(conn):
                        plan = plan_merge(conn, excel, policy)  # re-plan under the write lock
                        res["plan"] = plan
                        if auto and not is_safe(plan):
                            raise _Unsafe()
                        res["merge"] = _apply(conn, plan, sha, excel)
                except _Unsafe:
                    res["status"] = "needs_review"
                    return _finish(conn, res, dry_run)
                except Exception as exc:  # noqa: BLE001 - surfaced through status, never as success
                    res["status"] = "error"
                    res["error"] = f"{type(exc).__name__}: {exc}"
                    with write_transaction(conn):
                        _set(conn, "last_error", json.dumps({"at": res["at"], "error": res["error"]}, ensure_ascii=False))
                        _note_problem(conn, "error", sha, error=res["error"])
                    return _finish(conn, res, dry_run)
        elif dry_run:
            res["status"] = "preview"
            res["plan"] = None
            return res
        if dry_run:
            res["status"] = "preview"
            return res
        try:
            if is_pending(conn) or not path.exists() or _sha(path) != _get(conn, "last_export_sha"):
                res["export"] = export(conn, path, observed=observed)
                es = res["export"]["status"]
                res["status"] = "exported" if es == "exported" else ("deferred_changed" if es == "deferred_changed"
                                                                      else "pending_locked")
            else:
                res.setdefault("status", "up_to_date")
        except Exception as exc:  # noqa: BLE001
            res["status"] = "error"
            res["error"] = f"export failed: {type(exc).__name__}: {exc}"
            with write_transaction(conn):
                _set(conn, "last_error", json.dumps({"at": res["at"], "error": res["error"]}, ensure_ascii=False))
            return _finish(conn, res, dry_run)
        if "merge" in res and res["status"] == "exported":
            res["status"] = "merged_and_exported"
        if res["status"] in ("exported", "merged_and_exported", "up_to_date"):
            with write_transaction(conn):
                _set(conn, "last_problem", "")
        return _finish(conn, res, dry_run)


class _Unsafe(Exception):
    pass


def _finish(conn, res: dict, dry_run: bool) -> dict:
    if not dry_run:
        slim = {k: v for k, v in res.items() if k != "plan"}
        if res.get("plan"):
            p = res["plan"]
            slim["plan_counts"] = {k: len(p[k]) for k in ("stock_changes", "meta_changes", "creates", "merges", "conflicts",
                                                         "warnings", "invalid")}
            slim["blocked"] = p.get("blocked")
            slim["conflicts"] = p["conflicts"][:20]
            slim["invalid"] = p["invalid"][:20]
        with write_transaction(conn):
            _set(conn, "last_result", json.dumps(slim, ensure_ascii=False, default=str))
    return res


STATE = {"exported": "ok", "merged_and_exported": "ok", "up_to_date": "ok", "pending_locked": "pending_locked",
         "deferred_locked_by_excel": "pending_locked", "deferred_unstable": "waiting", "deferred_unreadable": "waiting",
         "deferred_changed": "waiting",
         "needs_review": "needs_review", "external_changes_pending_confirmation": "needs_review", "blocked": "blocked",
         "error": "error"}


def status(conn, path: Path | None, settings) -> dict[str, Any]:
    if path is None:
        return {"enabled": False, "reason": "INVENTORY_XLSX_PATH not set", "state": "disabled"}
    last = _get(conn, "last_result")
    last_res = json.loads(last) if last else None
    err = _get(conn, "last_error")
    events = [dict(r) for r in conn.execute(
        "SELECT created_at, kind, product_id, detail FROM excel_sync_events ORDER BY id DESC LIMIT 30").fetchall()]
    state = STATE.get((last_res or {}).get("status"), "unknown")
    if state == "ok" and (last_res or {}).get("plan_counts", {}).get("invalid"):
        state = "ok_with_rejected_rows"
    return {
        "enabled": True, "path": str(path), "exists": Path(path).exists(), "state": state,
        "reason_text": reason_text(state, last_res or {}, is_pending(conn)),
        "pending_export": is_pending(conn),
        "change_seq": int(_get(conn, "change_seq", "0")), "exported_seq": int(_get(conn, "exported_seq", "0")),
        "pending_reason": _get(conn, "pending_reason") or None,
        "last_export": {"export_id": _get(conn, "last_export_id") or None, "at": _get(conn, "last_export_at") or None},
        "file_export_id": _get(conn, "file_export_id") or None,
        "last_result": last_res, "last_error": json.loads(err) if err else None,
        "lock_file_present": lock_file_present(Path(path)), "conflict_copies": conflict_copies(Path(path)),
        "merge_policy": settings.inventory_xlsx_merge_policy, "auto_apply": settings.inventory_xlsx_auto_apply,
        "poll_seconds": settings.inventory_xlsx_poll_seconds, "recent_events": events,
        "cas_mode": _get(conn, "cas_mode") or None,
        "stored": {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                   for t in ("excel_exports", "excel_snapshots", "excel_imports", "excel_sync_events")},
    }


def reason_text(state: str, last: dict, pending: bool) -> str:
    """One Korean sentence for people (admin page / HUD)."""
    counts = last.get("plan_counts") or {}
    if state == "ok":
        return "Excel 파일과 데이터베이스가 일치합니다."
    if state == "ok_with_rejected_rows":
        return f"반영했지만 {counts.get('invalid', 0)}개 행은 오류로 제외했습니다. 관리 화면에서 확인하세요."
    if state == "pending_locked":
        return "Excel 파일이 열려 있어(잠금) 저장을 미뤘습니다. 파일을 닫으면 자동으로 저장합니다."
    if state == "waiting":
        return "파일이 동기화 중이거나 바뀌는 중이라 잠시 후 다시 확인합니다."
    if state == "needs_review":
        return (f"Excel 수정 중 자동 반영할 수 없는 항목이 있습니다(충돌 {counts.get('conflicts', 0)}, 오류 "
                f"{counts.get('invalid', 0)}). 관리 화면에서 확인 후 반영하세요. 그동안 재고 변경은 서버에 저장되고"
                + (" Excel 저장은 보류 중입니다." if pending else " 있습니다."))
    if state == "blocked":
        b = str(last.get("blocked") or "")
        if b.startswith("unknown_baseline"):
            return ("이 Excel 파일이 언제 내보낸 것인지 알 수 없어(기준 스냅숏 없음: 아주 오래된 사본이거나 _sync 시트가 "
                    "지워짐) 자동 병합을 멈췄습니다. 관리 화면에서 '파일 수정 버리고 다시 내보내기' 또는 '파일 값 반영'을 "
                    "선택하세요.")
        return "Excel 파일 구조가 올바르지 않아(inventory 시트·열 이름) 동기화를 멈췄습니다."
    if state == "error":
        return "동기화 중 예상하지 못한 오류가 났습니다. 관리 화면의 마지막 오류를 확인하세요."
    if state == "disabled":
        return "Excel 동기화가 꺼져 있습니다(INVENTORY_XLSX_PATH 미설정)."
    return "아직 동기화 기록이 없습니다."


RESOLVE_ACTIONS = ("discard_file", "apply_file_values")


def resolve(conn, path: Path, action: str, *, confirmed: bool, backup_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    """Explicit operator actions for a file the safe merge cannot handle (review R-1).

    discard_file: back up the current file, then export the DB values over it (the file's edits are dropped).
    apply_file_values: treat every valid row of the file as the intended absolute value (baseline = current DB),
      record differences as 'adjust' transactions, then export. dry_run shows the plan first."""
    if action not in RESOLVE_ACTIONS:
        raise ApiError(422, errors.VALIDATION_ERROR, f"action must be one of {RESOLVE_ACTIONS}")
    if not dry_run:
        check_confirmed(confirmed)
    path = Path(path)
    with path_lock(path):
        res: dict[str, Any] = {"at": utcnow(), "path": str(path), "action": action, "warnings": []}
        if action == "discard_file":
            if dry_run:
                res.update(status="preview", message="The file will be backed up and replaced by the database values.")
                return res
            backup = None
            if path.exists():
                import shutil

                backup_dir.mkdir(parents=True, exist_ok=True)
                stamp = utcnow().replace(":", "").replace("-", "")[:15]
                backup = backup_dir / f"{path.stem}-discarded-{stamp}-{uuid.uuid4().hex[:6]}{path.suffix}"
                shutil.copy2(path, backup)
            res["backup"] = str(backup) if backup else None
            res["export"] = export(conn, path, reason="discard_file", force=True)
            res["status"] = "exported" if res["export"]["status"] == "exported" else "pending_locked"
            with write_transaction(conn):
                _event(conn, "file_edits_discarded", None, backup=res["backup"])
                if res["status"] == "exported":
                    _set(conn, "last_problem", "")
            return _finish(conn, res, False)
        if not path.exists():
            raise ApiError(404, errors.NOT_FOUND, "Excel file not found")
        try:
            excel = read_workbook(path)
        except TransientRead as exc:
            raise ApiError(409, "EXCEL_FILE_BUSY", f"File is being written or synced ({exc}); retry shortly")
        if not excel["structure_ok"]:
            raise ApiError(409, "EXCEL_STRUCTURE_INVALID", "Sheet 'inventory' with product_id/stock_qty is required",
                           {"invalid": excel["invalid"][:20]})
        sha = _sha(path)

        def plan_now():
            db_base = {r["product_id"]: {f: r[f] for f in FIELDS} for r in conn.execute("SELECT * FROM products").fetchall()}
            p = plan_merge(conn, excel, "excel_wins", base_override=db_base)
            p["export_id"] = excel["export_id"] or f"manual-{uuid.uuid4().hex}"
            return p

        if dry_run:
            res.update(status="preview", plan=plan_now())
            return res
        with write_transaction(conn):
            plan = plan_now()
            res["plan"] = plan
            res["merge"] = _apply(conn, plan, sha, excel)
            _event(conn, "file_values_applied", None, file_sha=sha, applied=res["merge"]["applied"])
        res["export"] = export(conn, path, reason="apply_file_values")
        res["status"] = "merged_and_exported" if res["export"]["status"] == "exported" else "pending_locked"
        if res["status"] == "merged_and_exported":
            with write_transaction(conn):
                _set(conn, "last_problem", "")
        return _finish(conn, res, False)


def require_enabled(settings) -> Path:
    if settings.inventory_xlsx_path is None:
        raise ApiError(409, "EXCEL_SYNC_DISABLED", "Set INVENTORY_XLSX_PATH in .env to enable Excel sync")
    return settings.inventory_xlsx_path


def check_confirmed(confirmed: bool) -> None:
    if not confirmed:
        raise ApiError(400, errors.CONFIRMATION_REQUIRED, "confirmed must be true to apply Excel changes")


class Poller:
    """Background thread: export pending changes / merge external edits every N seconds (lifespan-managed)."""

    def __init__(self, settings, connect):
        self.settings, self.connect = settings, connect
        self.stop_event, self.wake = threading.Event(), threading.Event()
        self.observed: dict = {}
        self.thread = threading.Thread(target=self._run, name="excel-sync", daemon=True)

    def start(self):
        self.thread.start()

    def notify(self):
        self.wake.set()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        self.thread.join(timeout=10)

    def _run(self):
        while not self.stop_event.is_set():
            try:
                conn = self.connect(self.settings.database_path)
                try:
                    sync_once(conn, self.settings.inventory_xlsx_path, apply=self.settings.inventory_xlsx_auto_apply,
                              policy=self.settings.inventory_xlsx_merge_policy, require_stable=True, observed=self.observed,
                              auto=True)
                finally:
                    conn.close()
            except Exception:  # keep polling; errors are visible via status/last_result
                import logging

                logging.getLogger("poc.excel").exception("excel sync step failed")
            self.wake.wait(self.settings.inventory_xlsx_poll_seconds)
            self.wake.clear()
