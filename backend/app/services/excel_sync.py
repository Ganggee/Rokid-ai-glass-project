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
* durability: triggers bump `change_seq` in the same transaction as every product change; an export
  records `exported_seq`. pending = change_seq > exported_seq, so a crash before export is retried.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
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
_replace = os.replace  # indirection so tests can simulate a locked file


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


def export(conn, path: Path, reason: str = "change") -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    seq, snap, tx = _snapshot(conn)
    export_id = uuid.uuid4().hex
    tmp = path.with_name(f".~sync-{export_id}.tmp.xlsx")
    _write_workbook(tmp, export_id, snap, tx)
    sha = _sha(tmp)
    now = utcnow()
    # record the snapshot BEFORE the file appears, so a crash cannot leave a file with an unknown export_id
    conn.execute("INSERT INTO excel_exports(export_id, path, change_seq, snapshot_json, sha256, status, error, created_at) "
                 "VALUES (?,?,?,?,?, 'failed', 'not yet replaced', ?)",
                 (export_id, str(path), seq, json.dumps(snap, ensure_ascii=False), sha, now))
    try:
        _replace(tmp, path)
    except OSError as exc:  # PermissionError on Windows while Excel has the file open
        try:
            tmp.unlink()
        except OSError:
            pass
        with write_transaction(conn):
            conn.execute("UPDATE excel_exports SET error = ? WHERE export_id = ?", (f"{type(exc).__name__}: {exc}", export_id))
            _set(conn, "pending_reason", f"file locked or not writable ({type(exc).__name__})")
            _event(conn, "export_failed", error=type(exc).__name__, reason=reason)
        return {"status": "pending_locked", "export_id": None, "error": type(exc).__name__}
    with write_transaction(conn):
        conn.execute("UPDATE excel_exports SET status = 'written', error = NULL WHERE export_id = ?", (export_id,))
        if seq > int(_get(conn, "exported_seq", "0")):
            _set(conn, "exported_seq", seq)
        _set(conn, "last_export_id", export_id)
        _set(conn, "last_export_sha", sha)
        _set(conn, "last_export_at", now)
        _set(conn, "pending_reason", "")
    return {"status": "exported", "export_id": export_id, "products": len(snap), "change_seq": seq}


# ------------------------------------------------------------------ read
def read_workbook(path: Path) -> dict[str, Any]:
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        wb = load_workbook(path, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, EOFError, OSError, ValueError) as exc:
        raise TransientRead(type(exc).__name__)
    export_id = None
    if "_sync" in wb.sheetnames:
        ws = wb["_sync"]
        if ws.cell(1, 1).value == "export_id":
            export_id = _norm(ws.cell(1, 2).value)
    if "inventory" not in wb.sheetnames:
        return {"export_id": export_id, "rows": {}, "invalid": [{"row": None, "message": "sheet 'inventory' missing"}],
                "structure_ok": False}
    ws = wb["inventory"]
    it = ws.iter_rows(values_only=True)
    try:
        headers = [str(h).strip() if h is not None else "" for h in next(it)]
    except StopIteration:
        return {"export_id": export_id, "rows": {}, "invalid": [{"row": None, "message": "empty sheet"}], "structure_ok": False}
    colmap = inv.build_column_mapping(headers)
    if "product_id" not in colmap or "stock_qty" not in colmap:
        return {"export_id": export_id, "rows": {}, "invalid": [{"row": 1, "message": "product_id/stock_qty columns missing"}],
                "structure_ok": False}
    idx = {f: headers.index(h) for f, h in colmap.items()}
    rows, invalid = {}, []
    for n, values in enumerate(it, start=2):
        if values is None or all(v is None or str(v).strip() == "" for v in values):
            continue
        get = lambda f: values[idx[f]] if f in idx and idx[f] < len(values) else None  # noqa: E731
        pid = _norm(inv._cell_to_str(get("product_id"))[0])
        if not pid:
            invalid.append({"row": n, "message": "product_id empty"})
            continue
        if pid in rows:
            invalid.append({"row": n, "product_id": pid, "message": "duplicate product_id"})
            continue
        q = get("stock_qty")
        if isinstance(q, bool) or q is None:
            invalid.append({"row": n, "product_id": pid, "message": f"stock_qty invalid: {q!r}"})
            continue
        try:
            qf = float(q)
        except (TypeError, ValueError):
            invalid.append({"row": n, "product_id": pid, "message": f"stock_qty not a number: {q!r}"})
            continue
        if not qf.is_integer() or qf < 0:
            invalid.append({"row": n, "product_id": pid, "message": f"stock_qty must be an integer >= 0: {q!r}"})
            continue
        rec = {"product_id": pid, "stock_qty": int(qf)}
        for f in META_FIELDS:
            rec[f] = _norm(inv._cell_to_str(get(f))[0]) if f in idx else None
        rec["_row"] = n
        rows[pid] = rec
    return {"export_id": export_id, "rows": rows, "invalid": invalid, "structure_ok": True}


# ------------------------------------------------------------------ merge
def _baseline(conn, export_id: str | None) -> dict | None:
    if not export_id:
        return None
    imp = conn.execute("SELECT excel_snapshot_json FROM excel_imports WHERE export_id = ? ORDER BY id DESC LIMIT 1",
                       (export_id,)).fetchone()
    if imp is not None:
        return json.loads(imp["excel_snapshot_json"])
    exp = conn.execute("SELECT snapshot_json FROM excel_exports WHERE export_id = ?", (export_id,)).fetchone()
    return json.loads(exp["snapshot_json"]) if exp else None


def plan_merge(conn, excel: dict, policy: str = "merge_delta") -> dict[str, Any]:
    plan = {"export_id": excel["export_id"], "stock_changes": [], "meta_changes": [], "creates": [], "conflicts": [],
            "warnings": [], "invalid": list(excel["invalid"]), "blocked": None}
    if not excel["structure_ok"]:
        plan["blocked"] = "invalid_structure"
        return plan
    base = _baseline(conn, excel["export_id"])
    if base is None:
        plan["blocked"] = "unknown_baseline (missing/unknown export_id: file not created by this server or _sync sheet removed)"
        return plan
    db = {r["product_id"]: dict(r) for r in conn.execute("SELECT * FROM products").fetchall()}
    for pid, ex in excel["rows"].items():
        b, d = base.get(pid), db.get(pid)
        if d is None and b is None:
            if not ex.get("product_name"):
                plan["invalid"].append({"row": ex["_row"], "product_id": pid, "message": "new product needs product_name"})
                continue
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
                    plan["conflicts"].append({"product_id": pid, "kind": "both_changed", "base": bq, "db": dq, "excel": exq,
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
            plan["meta_changes"].append({"product_id": pid, "fields": meta})
    for pid in base:
        if pid in db and pid not in excel["rows"]:
            plan["warnings"].append({"product_id": pid, "kind": "row_missing (never deleted; restored on next export)"})
    return plan


def _apply(conn, plan: dict, file_sha: str, excel: dict) -> dict[str, Any]:
    now = utcnow()
    applied = {"stock": 0, "meta": 0, "created": 0}
    for ch in plan["stock_changes"]:
        cur = conn.execute("SELECT stock_qty FROM products WHERE product_id = ?", (ch["product_id"],)).fetchone()["stock_qty"]
        if cur != ch["from"]:
            raise RuntimeError("stock changed during merge")  # cannot happen inside BEGIN IMMEDIATE
        if ch["to"] == cur:
            continue
        conn.execute("UPDATE products SET stock_qty = ?, updated_at = ? WHERE product_id = ?", (ch["to"], now, ch["product_id"]))
        conn.execute("""INSERT INTO inventory_transactions(product_id, tx_type, quantity_delta, stock_before, stock_after,
                        source, note, created_at) VALUES (?, 'adjust', ?, ?, ?, 'excel_sync', ?, ?)""",
                     (ch["product_id"], ch["to"] - cur, cur, ch["to"], f"{ch['kind']} export={plan['export_id'][:8]}", now))
        _event(conn, "stock_" + ch["kind"], ch["product_id"], before=cur, after=ch["to"])
        applied["stock"] += 1
    for mc in plan["meta_changes"]:
        sets = ", ".join(f"{k} = ?" for k in mc["fields"])
        conn.execute(f"UPDATE products SET {sets}, updated_at = ? WHERE product_id = ?",
                     (*mc["fields"].values(), now, mc["product_id"]))
        f = mc["fields"]
        if "barcode" in f or "qr_value" in f:
            row = conn.execute("SELECT barcode, qr_value FROM products WHERE product_id = ?", (mc["product_id"],)).fetchone()
            inv._set_codes(conn, mc["product_id"], row["barcode"], row["qr_value"])
        _event(conn, "metadata_update", mc["product_id"], fields=list(f))
        applied["meta"] += 1
    for c in plan["creates"]:
        conn.execute("""INSERT INTO products(product_id, product_name, category, stock_qty, unit, barcode, qr_value, lot_no,
                        expiration_date, location, aliases, is_demo, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
                     (c["product_id"], c["product_name"], c.get("category"), c["stock_qty"], c.get("unit") or "ea",
                      c.get("barcode"), c.get("qr_value"), c.get("lot_no"), c.get("expiration_date"), c.get("location"),
                      c.get("aliases"), now, now))
        conn.execute("""INSERT INTO inventory_transactions(product_id, tx_type, quantity_delta, stock_before, stock_after,
                        source, note, created_at) VALUES (?, 'seed', ?, 0, ?, 'excel_sync', 'created from Excel row', ?)""",
                     (c["product_id"], c["stock_qty"], c["stock_qty"], now))
        inv._set_codes(conn, c["product_id"], c.get("barcode"), c.get("qr_value"))
        _event(conn, "product_created", c["product_id"])
        applied["created"] += 1
    for cf in plan["conflicts"]:
        _event(conn, "conflict", cf.get("product_id"), cf)
    for w in plan["warnings"]:
        _event(conn, "warning", w.get("product_id"), w)
    for bad in plan["invalid"]:
        _event(conn, "invalid_row", bad.get("product_id"), bad)
    snapshot = {pid: {k: v for k, v in r.items() if k != "_row"} for pid, r in excel["rows"].items()}
    result = {"applied": applied, "conflicts": len(plan["conflicts"]), "invalid": len(plan["invalid"])}
    conn.execute("INSERT INTO excel_imports(export_id, file_sha256, excel_snapshot_json, result_json, applied_at) VALUES (?,?,?,?,?)",
                 (plan["export_id"], file_sha, json.dumps(snapshot, ensure_ascii=False), json.dumps(result), now))
    return result


# ------------------------------------------------------------------ orchestration
CONFLICT_COPY = re.compile(r"(\(\d+\)|-[^.]+|conflict|충돌|복사본| copy)", re.I)


def conflict_copies(path: Path) -> list[str]:
    stem, out = path.stem, []
    if not path.parent.is_dir():
        return out
    for p in path.parent.iterdir():
        if p == path or not p.is_file() or p.name.startswith((".~sync-", "~$")):
            continue
        if p.suffix.lower() in (".xlsx", ".xlsm") and p.stem.startswith(stem) and CONFLICT_COPY.search(p.stem[len(stem):]):
            out.append(p.name)
    return sorted(out)


def lock_file_present(path: Path) -> bool:
    return (path.parent / ("~$" + path.name)).exists() or (path.parent / ("~$" + path.name[2:])).exists()


def sync_once(conn, path: Path, *, apply: bool, policy: str = "merge_delta", require_stable: bool = False,
              observed: dict | None = None, dry_run: bool = False) -> dict[str, Any]:
    """One deterministic sync step. Returns a result dict (also stored as last_result)."""
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
            st = path.stat()
            stat = [st.st_size, st.st_mtime_ns]
            if require_stable and observed is not None:
                prev = observed.get(str(path))
                observed[str(path)] = stat
                if prev != stat:
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
                plan = plan_merge(conn, excel, policy)
                res["plan"] = plan
                if plan["blocked"]:
                    res["status"] = "blocked"
                    if not dry_run:
                        with write_transaction(conn):
                            _event(conn, "blocked", None, reason=plan["blocked"], file_sha=sha)
                    return _finish(conn, res, dry_run)  # never overwrite a file we cannot merge
                if dry_run:
                    res["status"] = "preview"
                    return res
                if not apply:
                    res["status"] = "external_changes_pending_confirmation"
                    return _finish(conn, res, dry_run)
                with write_transaction(conn):
                    plan = plan_merge(conn, excel, policy)  # re-plan under the write lock
                    res["plan"] = plan
                    res["merge"] = _apply(conn, plan, sha, excel)
        elif dry_run:
            res["status"] = "preview"
            res["plan"] = None
            return res
        if dry_run:
            res["status"] = "preview"
            return res
        if is_pending(conn) or not path.exists() or (path.exists() and _sha(path) != _get(conn, "last_export_sha")):
            res["export"] = export(conn, path)
            res["status"] = "exported" if res["export"]["status"] == "exported" else "pending_locked"
        else:
            res.setdefault("status", "up_to_date")
        if "merge" in res and res["status"] == "exported":
            res["status"] = "merged_and_exported"
        return _finish(conn, res, dry_run)


def _finish(conn, res: dict, dry_run: bool) -> dict:
    if not dry_run:
        slim = {k: v for k, v in res.items() if k != "plan"}
        if res.get("plan"):
            p = res["plan"]
            slim["plan_counts"] = {k: len(p[k]) for k in ("stock_changes", "meta_changes", "creates", "conflicts", "warnings", "invalid")}
            slim["blocked"] = p.get("blocked")
        with write_transaction(conn):
            _set(conn, "last_result", json.dumps(slim, ensure_ascii=False, default=str))
    return res


def status(conn, path: Path | None, settings) -> dict[str, Any]:
    if path is None:
        return {"enabled": False, "reason": "INVENTORY_XLSX_PATH not set"}
    last = _get(conn, "last_result")
    events = [dict(r) for r in conn.execute(
        "SELECT created_at, kind, product_id, detail FROM excel_sync_events ORDER BY id DESC LIMIT 20").fetchall()]
    return {
        "enabled": True, "path": str(path), "exists": Path(path).exists(), "pending_export": is_pending(conn),
        "change_seq": int(_get(conn, "change_seq", "0")), "exported_seq": int(_get(conn, "exported_seq", "0")),
        "pending_reason": _get(conn, "pending_reason") or None,
        "last_export": {"export_id": _get(conn, "last_export_id") or None, "at": _get(conn, "last_export_at") or None},
        "last_result": json.loads(last) if last else None,
        "lock_file_present": lock_file_present(Path(path)), "conflict_copies": conflict_copies(Path(path)),
        "merge_policy": settings.inventory_xlsx_merge_policy, "auto_apply": settings.inventory_xlsx_auto_apply,
        "poll_seconds": settings.inventory_xlsx_poll_seconds, "recent_events": events,
    }


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
                              policy=self.settings.inventory_xlsx_merge_policy, require_stable=True, observed=self.observed)
                finally:
                    conn.close()
            except Exception:  # keep polling; errors are visible via status/last_result
                import logging

                logging.getLogger("poc.excel").exception("excel sync step failed")
            self.wake.wait(self.settings.inventory_xlsx_poll_seconds)
            self.wake.clear()
