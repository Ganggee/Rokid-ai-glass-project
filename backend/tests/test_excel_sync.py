"""Inventory <-> Excel sync: export, 3-way merge with export_id baseline, locks, crashes, invalid input, soak."""
from __future__ import annotations

import random
import shutil
import uuid

import pytest
from openpyxl import load_workbook

from backend.app.db import connect
from backend.app.services import excel_sync as xs
from backend.app.services import inventory_service as inv

from .conftest import AUTH, seed

S, A, H = "CARE-SENS-AIR-SENSOR", "CARE-SENS-AIR-APPLICATOR", "HICARDI-PATCH"


@pytest.fixture()
def env(tmp_path):
    db = tmp_path / "x.sqlite3"
    seed(db)
    conn = connect(db)
    path = tmp_path / "linked" / "inventory.xlsx"
    yield conn, path
    conn.close()


def use(conn, pid=S, q=1):
    return inv.use_stock(conn, product_id=pid, quantity=q, idempotency_key=uuid.uuid4().hex, confirmed=True)


def stock(conn, pid=S):
    return inv.get_product(conn, pid)["stock_qty"]


def edit(path, changes: dict, delete_rows=(), add_rows=(), drop_sync=False):
    """Simulate a person editing the workbook in Excel (openpyxl keeps the other sheets)."""
    wb = load_workbook(path)
    ws = wb["inventory"]
    header = [c.value for c in ws[1]]
    col = {h: i + 1 for i, h in enumerate(header)}
    for row in range(ws.max_row, 1, -1):
        pid = ws.cell(row, col["product_id"]).value
        if pid in delete_rows:
            ws.delete_rows(row)
            continue
        for (cpid, field), value in changes.items():
            if pid == cpid:
                ws.cell(row, col[field]).value = value
    for r in add_rows:
        ws.append([r.get(h) for h in header])
    if drop_sync:
        del wb["_sync"]
    wb.save(path)


def sync(conn, path, apply=True, policy="merge_delta", **kw):
    return xs.sync_once(conn, path, apply=apply, policy=policy, **kw)


def excel_stock(path, pid=S):
    wb = load_workbook(path, data_only=True)
    ws = wb["inventory"]
    header = [c.value for c in ws[1]]
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[header.index("product_id")] == pid:
            return r[header.index("stock_qty")]
    return None


def adjusts(conn, pid=S):
    return [t for t in inv.list_transactions(conn, pid, 500) if t["tx_type"] == "adjust" and t["source"] == "excel_sync"]


def check_invariants(conn):
    for p in inv.search_products(conn, limit=500):
        total = conn.execute("SELECT COALESCE(SUM(quantity_delta),0) FROM inventory_transactions WHERE product_id = ?",
                             (p["product_id"],)).fetchone()[0]
        assert total == p["stock_qty"] >= 0, p


def test_export_sheets_round_trip(env):
    conn, path = env
    r = sync(conn, path)
    assert r["status"] == "exported" and path.exists()
    wb = load_workbook(path)
    assert wb.sheetnames == ["inventory", "transactions", "_sync"] and wb["_sync"].sheet_state == "veryHidden"
    assert wb["_sync"]["B1"].value == r["export"]["export_id"]
    # the exported file is a valid import file (same columns)
    prev = inv.preview_import(conn, "inventory.xlsx", path.read_bytes())
    assert prev["error_count"] == 0 and prev["row_count"] == 3
    assert sync(conn, path)["status"] == "up_to_date"
    use(conn)
    assert xs.is_pending(conn)
    sync(conn, path)
    assert excel_stock(path) == 19 and not xs.is_pending(conn)


def test_excel_only_edit_applied_as_adjust(env):
    conn, path = env
    sync(conn, path)
    edit(path, {(S, "stock_qty"): 25, (H, "location"): "Cabinet Z"})
    r = sync(conn, path)
    assert r["status"] == "merged_and_exported"
    assert stock(conn) == 25 and inv.get_product(conn, H)["location"] == "Cabinet Z"
    a = adjusts(conn)
    assert len(a) == 1 and a[0]["quantity_delta"] == 5
    # re-running on the same content never re-applies
    assert sync(conn, path)["status"] == "up_to_date" and len(adjusts(conn)) == 1
    check_invariants(conn)


def test_stale_copy_saved_over_newer_export_does_not_undo_use(env):
    """Advisor P0-1: user keeps the 20-stock file open, glasses use 1 (export 19), user saves the old copy."""
    conn, path = env
    sync(conn, path)
    stale = path.with_name("stale.bin")
    shutil.copy(path, stale)
    use(conn)
    sync(conn, path)
    assert excel_stock(path) == 19
    shutil.copy(stale, path)               # old file (export E1, sensor 20) comes back
    edit(path, {(A, "stock_qty"): 12})    # ...with an unrelated edit
    r = sync(conn, path)
    assert stock(conn) == 19, "stale copy must not resurrect the used item"
    assert stock(conn, A) == 12 and adjusts(conn) == []
    assert excel_stock(path) == 19 and r["status"] == "merged_and_exported"
    check_invariants(conn)


def test_both_changed_merge_delta(env):
    conn, path = env
    sync(conn, path)
    use(conn)                                # db 19, base 20
    edit(path, {(S, "stock_qty"): 25})       # excel +5 restock
    r = sync(conn, path)
    assert stock(conn) == 24 and any(c["kind"] == "both_changed" for c in r["plan"]["merges"]) and not r["plan"]["conflicts"]
    assert len(adjusts(conn)) == 1 and adjusts(conn)[0]["quantity_delta"] == 5
    assert excel_stock(path) == 24
    check_invariants(conn)


def test_negative_merge_kept_db_and_db_wins_excel_wins(env):
    conn, path = env
    sync(conn, path)
    edit(path, {(A, "stock_qty"): 5})        # excel -5 (base 10)
    use(conn, A, 8)                          # db 2 -> merge 2 + (5-10) = -3 -> conflict, keep db
    r = sync(conn, path)
    assert stock(conn, A) == 2
    assert any(c["kind"] == "merge_would_be_negative" for c in r["plan"]["conflicts"])
    sync(conn, path)
    edit(path, {(H, "stock_qty"): 30})
    use(conn, H)
    r = sync(conn, path, policy="db_wins")
    assert stock(conn, H) == 14
    edit(path, {(H, "stock_qty"): 30})
    use(conn, H)
    sync(conn, path, policy="excel_wins")
    assert stock(conn, H) == 30
    check_invariants(conn)


def test_unknown_baseline_blocks_and_never_overwrites(env):
    conn, path = env
    sync(conn, path)
    edit(path, {(S, "stock_qty"): 99}, drop_sync=True)
    before = path.read_bytes()
    use(conn)                                 # pending export must still not overwrite the file
    r = sync(conn, path)
    assert r["status"] == "blocked" and "unknown_baseline" in r["plan"]["blocked"]
    assert stock(conn) == 19 and path.read_bytes() == before and xs.is_pending(conn)


def test_locked_file_keeps_export_pending_then_exports_once(env, monkeypatch):
    conn, path = env
    sync(conn, path)

    def locked(src, dst):
        raise PermissionError("The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(xs, "_replace", locked)
    use(conn)                                 # /use itself is unaffected
    r = sync(conn, path)
    assert r["status"] == "pending_locked" and xs.is_pending(conn) and stock(conn) == 19
    assert not list(path.parent.glob(".~sync-*"))  # temp file cleaned up
    monkeypatch.setattr(xs, "_replace", __import__("os").replace)
    r = sync(conn, path)
    assert r["status"] == "exported" and excel_stock(path) == 19
    assert sync(conn, path)["status"] == "up_to_date"


def test_second_edit_on_same_export_id_while_locked_is_not_double_applied(env, monkeypatch):
    conn, path = env
    sync(conn, path)
    edit(path, {(S, "stock_qty"): 25})        # edit 1 (+5)
    monkeypatch.setattr(xs, "_replace", lambda a, b: (_ for _ in ()).throw(PermissionError("locked")))
    sync(conn, path)                          # applied, but re-export fails: file still has the same export_id
    assert stock(conn) == 25
    edit(path, {(S, "stock_qty"): 27})        # edit 2 (+2 relative to edit 1)
    sync(conn, path)
    assert stock(conn) == 27, "baseline must be edit-1 content, not the original export"
    monkeypatch.setattr(xs, "_replace", __import__("os").replace)
    sync(conn, path)
    assert excel_stock(path) == 27
    check_invariants(conn)


def test_truncated_file_is_transient(env):
    conn, path = env
    sync(conn, path)
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])  # sync client mid-download
    r = sync(conn, path)
    assert r["status"] == "deferred_unreadable" and stock(conn) == 20
    path.write_bytes(data)


def test_lock_file_and_conflict_copies(env):
    conn, path = env
    sync(conn, path)
    (path.parent / "~$inventory.xlsx").write_bytes(b"lock")
    assert sync(conn, path)["status"] == "deferred_locked_by_excel"
    (path.parent / "~$inventory.xlsx").unlink()
    shutil.copy(path, path.parent / "inventory (1).xlsx")
    edit(path.parent / "inventory (1).xlsx", {(S, "stock_qty"): 1})
    r = sync(conn, path)
    assert any(w["kind"] == "conflict_copies_ignored" for w in r["warnings"]) and stock(conn) == 20


def test_unstable_file_is_deferred_until_two_equal_observations(env):
    conn, path = env
    sync(conn, path)
    edit(path, {(S, "stock_qty"): 21})
    obs: dict = {}
    assert sync(conn, path, require_stable=True, observed=obs)["status"] == "deferred_unstable"
    assert sync(conn, path, require_stable=True, observed=obs)["status"] == "merged_and_exported"
    assert stock(conn) == 21


def test_deleted_row_restored_and_new_row_created(env):
    conn, path = env
    sync(conn, path)
    edit(path, {}, delete_rows=(H,), add_rows=({"product_id": "NEW-1", "product_name": "New item", "stock_qty": 4},))
    r = sync(conn, path)
    assert any("row_missing" in w["kind"] for w in r["plan"]["warnings"])
    assert stock(conn, H) == 15 and excel_stock(path, H) == 15  # restored on export
    assert stock(conn, "NEW-1") == 4
    check_invariants(conn)


def test_invalid_values_reported_not_applied(env):
    conn, path = env
    sync(conn, path)
    edit(path, {(S, "stock_qty"): -1, (A, "stock_qty"): 3.5, (H, "stock_qty"): 16})
    r = sync(conn, path)
    msgs = " ".join(i["message"] for i in r["plan"]["invalid"])
    assert "integer >= 0" in msgs and stock(conn) == 20 and stock(conn, A) == 10 and stock(conn, H) == 16
    assert excel_stock(path) == 20  # invalid cell replaced by DB value on export


def test_crash_after_commit_before_export_is_recovered(env):
    conn, path = env
    sync(conn, path)
    use(conn)                                # committed; "process dies" before any export
    conn2 = connect(conn.execute("PRAGMA database_list").fetchone()[2])
    try:                                     # restart: startup sync sees change_seq > exported_seq
        assert xs.is_pending(conn2)
        assert sync(conn2, path)["status"] == "exported" and excel_stock(path) == 19
    finally:
        conn2.close()


def test_api_preview_confirm_and_status(tmp_path):
    from fastapi.testclient import TestClient

    from backend.app.config import load_settings
    from backend.app.main import create_app

    from .conftest import TOKEN

    settings = load_settings(env_file=tmp_path / "none.env", api_token=TOKEN, database_path=tmp_path / "a.sqlite3",
                             upload_dir=tmp_path / "u", inventory_xlsx_path=tmp_path / "linked" / "inventory.xlsx",
                             inventory_xlsx_poll_seconds=0)
    seed(settings.database_path)
    with TestClient(create_app(settings)) as c:
        c.headers.update(AUTH)
        assert settings.inventory_xlsx_path.exists()  # startup sync exported
        edit(settings.inventory_xlsx_path, {(S, "stock_qty"): 22})
        prev = c.post("/api/v1/inventory/excel-sync", json={}).json()
        assert prev["status"] == "preview" and prev["plan"]["stock_changes"][0]["to"] == 22
        assert c.get(f"/api/v1/inventory/products/{S}").json()["stock_qty"] == 20
        bad = c.post("/api/v1/inventory/excel-sync", json={"dry_run": False})
        assert bad.status_code == 400 and bad.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
        ok = c.post("/api/v1/inventory/excel-sync", json={"dry_run": False, "confirmed": True}).json()
        assert ok["status"] == "merged_and_exported"
        assert c.get(f"/api/v1/inventory/products/{S}").json()["stock_qty"] == 22
        st = c.get("/api/v1/inventory/excel-sync/status").json()
        assert st["enabled"] and not st["pending_export"] and st["last_export"]["export_id"]


def test_disabled_sync_returns_409(client):
    r = client.post("/api/v1/inventory/excel-sync", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "EXCEL_SYNC_DISABLED"
    assert client.get("/api/v1/inventory/excel-sync/status").json()["enabled"] is False


def run_soak(conn, path, seed_value: int, uses: int, edits: int, restarts: int, db_path=None):
    """Random uses + human edits of several kinds + lock failures + reconnects, auto (safe) mode like the poller.
    Unsafe edits (typo with copied barcode, invalid value, negative merge) go to needs_review and are
    resolved by a manual apply (admin page), as a person would."""
    rng = random.Random(seed_value)
    pids = [S, A, H]
    stats = {"uses": 0, "rejected": 0, "edits": 0, "restarts": 0, "locked": 0, "needs_review": 0, "manual_applies": 0,
             "edit_kinds": {}}
    sync(conn, path)
    edit_points = set(rng.sample(range(uses), edits))
    restart_points = set(rng.sample(range(uses), restarts))
    new_seq = 0
    max_rows = {}
    for i in range(uses):
        pid = rng.choice(pids)
        try:
            use(conn, pid, rng.choice([1, 1, 1, 2]))
            stats["uses"] += 1
        except Exception:
            stats["rejected"] += 1
        if i in edit_points:
            wb = load_workbook(path, data_only=True)
            ws = wb["inventory"]
            header = [c.value for c in ws[1]]
            rows = {r[header.index("product_id")]: r for r in ws.iter_rows(min_row=2, values_only=True)}
            target = rng.choice(pids)
            kind = rng.choices(["stock", "new_row", "pid_typo", "delete_row", "invalid_value"], [6, 1, 1, 1, 1])[0]
            stats["edit_kinds"][kind] = stats["edit_kinds"].get(kind, 0) + 1
            q = int(rows[target][header.index("stock_qty")]) if target in rows else 0
            if kind == "stock":
                edit(path, {(target, "stock_qty"): max(0, q + rng.choice([5, 10, 20, -1]))})
            elif kind == "new_row":
                new_seq += 1
                edit(path, {}, add_rows=({"product_id": f"SOAK-NEW-{seed_value}-{new_seq}", "product_name": "soak", "stock_qty": 5},))
            elif kind == "pid_typo":
                src = rows.get(target)
                if src is not None:
                    dup = {h: src[k] for k, h in enumerate(header)}
                    dup["product_id"] = target + "-TYPO"
                    edit(path, {}, add_rows=(dup,))
            elif kind == "delete_row":
                edit(path, {}, delete_rows=(target,))
            else:
                edit(path, {(target, "stock_qty"): rng.choice([-1, 2.5, "many"])})
            stats["edits"] += 1
        if i in restart_points and db_path is not None:
            conn.close()
            conn = connect(db_path)
            stats["restarts"] += 1
        if rng.random() < 0.02:
            stats["locked"] += 1
            orig = xs._replace
            xs._replace = lambda a, b: (_ for _ in ()).throw(PermissionError("locked"))
            xs.sync_once(conn, path, apply=True, auto=True)
            xs._replace = orig
        if rng.random() < 0.3:
            r = xs.sync_once(conn, path, apply=True, auto=True)
            if r["status"] == "needs_review":
                stats["needs_review"] += 1
                if rng.random() < 0.5:  # the person opens /admin/inventory-sync and applies
                    assert sync(conn, path)["status"] in ("merged_and_exported", "exported"), "manual apply must not get stuck"
                    stats["manual_applies"] += 1
            assert r["status"] != "error", r
        for t in ("excel_exports", "excel_snapshots", "excel_imports", "excel_sync_events"):
            max_rows[t] = max(max_rows.get(t, 0), conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
        if i % 250 == 0:
            check_invariants(conn)
    final = sync(conn, path)  # manual apply resolves whatever is left
    if final["status"] not in ("up_to_date", "exported", "merged_and_exported"):
        raise AssertionError(final)
    assert sync(conn, path)["status"] == "up_to_date"
    check_invariants(conn)
    for p in inv.search_products(conn, limit=500):
        assert excel_stock(path, p["product_id"]) == p["stock_qty"], p["product_id"]
    keys = conn.execute("SELECT idempotency_key, COUNT(*) FROM inventory_transactions WHERE idempotency_key IS NOT NULL "
                        "GROUP BY idempotency_key HAVING COUNT(*) > 1").fetchall()
    assert not keys
    dup = conn.execute("SELECT file_sha256, COUNT(*) FROM excel_imports GROUP BY file_sha256 HAVING COUNT(*) > 1").fetchall()
    assert not dup
    assert conn.execute("SELECT COUNT(*) FROM products WHERE product_id LIKE '%-TYPO'").fetchone()[0] == 0
    # bounded storage (review X-2)
    assert max_rows["excel_exports"] <= xs.KEEP_EXPORTS + 2, max_rows
    assert max_rows["excel_snapshots"] <= xs.KEEP_EXPORTS + 2, max_rows
    assert max_rows["excel_imports"] <= (xs.KEEP_EXPORTS + 2) * xs.KEEP_IMPORTS_PER_EXPORT, max_rows
    assert max_rows["excel_sync_events"] <= xs.KEEP_EVENTS + 200, max_rows
    stats["max_rows"] = max_rows
    return conn, stats


def test_soak_small(env, tmp_path):
    conn, path = env
    # restock generously so uses keep succeeding
    for pid in (S, A, H):
        conn.execute("UPDATE products SET stock_qty = stock_qty + 300 WHERE product_id = ?", (pid,))
        conn.execute("INSERT INTO inventory_transactions(product_id, tx_type, quantity_delta, stock_before, stock_after, source, created_at) "
                     "SELECT product_id, 'adjust', 300, stock_qty - 300, stock_qty, 'test', 'now' FROM products WHERE product_id = ?", (pid,))
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    conn, stats = run_soak(conn, path, seed_value=7, uses=300, edits=20, restarts=2, db_path=db_path)
    assert stats["edits"] == 20 and stats["restarts"] == 2


# ---------------------------------------------------------------- review 02 regressions
def _rename_pid(path, old, new):
    wb = load_workbook(path)
    ws = wb["inventory"]
    header = [c.value for c in ws[1]]
    for row in range(2, ws.max_row + 1):
        if ws.cell(row, header.index("product_id") + 1).value == old:
            ws.cell(row, header.index("product_id") + 1).value = new
    wb.save(path)


def test_x1_new_row_with_duplicate_barcode_is_invalid_and_sync_continues(env):
    """X-1 BLOCKER: product_id typo keeps the barcode/QR of an existing product."""
    conn, path = env
    sync(conn, path)
    _rename_pid(path, S, S + "X")
    edit(path, {(A, "stock_qty"): 12})       # a valid change in the same file must still apply
    prev = sync(conn, path, dry_run=True)
    assert prev["status"] == "preview"
    assert any("already used" in i["message"] and i["product_id"] == S + "X" for i in prev["plan"]["invalid"]), prev["plan"]
    r = sync(conn, path)                      # manual apply: valid rows applied, bad row reported, export continues
    assert r["status"] == "merged_and_exported", r
    assert stock(conn, A) == 12
    assert conn.execute("SELECT COUNT(*) FROM products WHERE product_id = ?", (S + "X",)).fetchone()[0] == 0
    assert excel_stock(path, S) == 20          # original row restored on export
    use(conn)
    assert sync(conn, path)["status"] == "exported" and excel_stock(path) == 19  # never stuck


def test_x1_any_db_constraint_error_becomes_row_invalid(env, monkeypatch):
    conn, path = env
    sync(conn, path)
    edit(path, {}, add_rows=({"product_id": "NEW-A", "product_name": "A", "stock_qty": 1},
                             {"product_id": "NEW-B", "product_name": "B", "stock_qty": 2}))
    real = inv._set_codes
    import sqlite3

    def boom(c, pid, barcode, qr):
        if pid == "NEW-A":
            raise sqlite3.IntegrityError("simulated constraint")
        return real(c, pid, barcode, qr)

    monkeypatch.setattr(inv, "_set_codes", boom)
    r = sync(conn, path)
    assert r["status"] == "merged_and_exported"
    assert any(i.get("product_id") == "NEW-A" and "simulated constraint" in i["message"] for i in r["plan"]["invalid"])
    assert stock(conn, "NEW-B") == 2
    assert conn.execute("SELECT COUNT(*) FROM products WHERE product_id = 'NEW-A'").fetchone()[0] == 0
    check_invariants(conn)


def test_x1_unexpected_error_is_reported_not_up_to_date(env, monkeypatch):
    conn, path = env
    sync(conn, path)
    edit(path, {(S, "stock_qty"): 25})

    def broken(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(xs, "_apply", broken)
    r = sync(conn, path)
    assert r["status"] == "error" and "disk on fire" in r["error"]
    st = xs.status(conn, path, type("S", (), {"inventory_xlsx_merge_policy": "merge_delta", "inventory_xlsx_auto_apply": True,
                                               "inventory_xlsx_poll_seconds": 30})())
    assert st["last_result"]["status"] == "error" and st["state"] == "error" and st["last_error"]


def test_x1_duplicate_barcode_api_no_500(tmp_path):
    from fastapi.testclient import TestClient

    from backend.app.config import load_settings
    from backend.app.main import create_app

    from .conftest import TOKEN

    settings = load_settings(env_file=tmp_path / "none.env", api_token=TOKEN, database_path=tmp_path / "a.sqlite3",
                             upload_dir=tmp_path / "u", inventory_xlsx_path=tmp_path / "linked" / "inventory.xlsx",
                             inventory_xlsx_poll_seconds=0)
    seed(settings.database_path)
    with TestClient(create_app(settings), raise_server_exceptions=False) as c:
        c.headers.update(AUTH)
        _rename_pid(settings.inventory_xlsx_path, S, S + "-2")
        r = c.post("/api/v1/inventory/excel-sync", json={"dry_run": False, "confirmed": True})
        assert r.status_code == 200 and r.json()["status"] == "merged_and_exported"
        st = c.get("/api/v1/inventory/excel-sync/status").json()
        assert st["last_result"]["plan_counts"]["invalid"] == 1


def test_x3_auto_apply_only_safe_changes_and_holds_export(env):
    """Auto mode: conflicts/invalid stop auto-apply; DB changes stay pending; resolved -> exported."""
    conn, path = env
    sync(conn, path)
    edit(path, {(S, "stock_qty"): 25})
    assert xs.sync_once(conn, path, apply=True, auto=True)["status"] == "merged_and_exported" and stock(conn) == 25
    # unsafe: invalid value + a valid change -> nothing applied, file untouched, export pending
    edit(path, {(A, "stock_qty"): -3, (H, "stock_qty"): 40})
    before = path.read_bytes()
    use(conn)                                   # glasses keep working
    r = xs.sync_once(conn, path, apply=True, auto=True)
    assert r["status"] == "needs_review" and stock(conn, H) == 15 and stock(conn) == 24
    assert path.read_bytes() == before and xs.is_pending(conn)
    # the person fixes the cell -> next auto step applies and exports the pending use as well
    edit(path, {(A, "stock_qty"): 10})
    r = xs.sync_once(conn, path, apply=True, auto=True)
    assert r["status"] == "merged_and_exported" and stock(conn, H) == 40 and excel_stock(path) == 24
    assert not xs.is_pending(conn)


def test_x3_merge_delta_both_changed_is_safe_but_negative_is_not(env):
    conn, path = env
    sync(conn, path)
    edit(path, {(S, "stock_qty"): 30})
    use(conn)
    assert xs.sync_once(conn, path, apply=True, auto=True)["status"] == "merged_and_exported" and stock(conn) == 29
    edit(path, {(A, "stock_qty"): 1})
    use(conn, A, 5)
    r = xs.sync_once(conn, path, apply=True, auto=True)
    assert r["status"] == "needs_review" and stock(conn, A) == 5


def test_x2_snapshot_retention_bounded(env, monkeypatch):
    conn, path = env
    monkeypatch.setattr(xs, "KEEP_EXPORTS", 5)
    sync(conn, path)
    orig = xs._replace
    monkeypatch.setattr(xs, "_replace", lambda a, b: (_ for _ in ()).throw(PermissionError("locked")))
    use(conn)
    for _ in range(10):
        sync(conn, path)                        # failing polls must not add snapshots
    assert conn.execute("SELECT COUNT(*) FROM excel_exports").fetchone()[0] == 1
    monkeypatch.setattr(xs, "_replace", orig)
    for _ in range(12):
        use(conn)
        sync(conn, path)
    n_exp = conn.execute("SELECT COUNT(*) FROM excel_exports").fetchone()[0]
    n_snap = conn.execute("SELECT COUNT(*) FROM excel_snapshots").fetchone()[0]
    assert n_exp <= 6 and n_snap <= 6
    file_eid = load_workbook(path)["_sync"]["B1"].value
    assert conn.execute("SELECT 1 FROM excel_exports WHERE export_id = ?", (file_eid,)).fetchone()


def test_x2_identical_content_shares_snapshot(env):
    conn, path = env
    sync(conn, path)
    path.unlink()                                # forces a re-export with identical content
    sync(conn, path)
    assert conn.execute("SELECT COUNT(*) FROM excel_exports").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM excel_snapshots").fetchone()[0] == 1


def test_x4_formula_without_cache_is_invalid_not_row_missing(env):
    conn, path = env
    sync(conn, path)
    edit(path, {(S, "stock_qty"): "=20+10"})
    r = sync(conn, path, dry_run=True)
    kinds = [w["kind"] for w in r["plan"]["warnings"]]
    assert any("formula_without_cached_value" in i["message"] for i in r["plan"]["invalid"])
    assert not any("row_missing" in k for k in kinds)


def test_x5_own_export_is_not_reported_unstable(env):
    conn, path = env
    obs: dict = {}
    xs.sync_once(conn, path, apply=True, require_stable=True, observed=obs)
    use(conn)
    xs.sync_once(conn, path, apply=True, require_stable=True, observed=obs)
    assert xs.sync_once(conn, path, apply=True, require_stable=True, observed=obs)["status"] == "up_to_date"


def test_x7_only_sync_client_conflict_names(tmp_path):
    p = tmp_path / "inventory.xlsx"
    for n in ("inventory (1).xlsx", "inventory-DESKTOP-AB12.xlsx", "inventory (conflicted copy 2026-11-06).xlsx",
              "inventory-backup.xlsx", "inventory_old.xlsx"):
        (tmp_path / n).write_bytes(b"x")
    got = xs.conflict_copies(p)
    assert "inventory-backup.xlsx" not in got and "inventory_old.xlsx" not in got
    assert {"inventory (1).xlsx", "inventory (conflicted copy 2026-11-06).xlsx", "inventory-DESKTOP-AB12.xlsx"} <= set(got)


def test_x3_settings_defaults_and_admin_page(tmp_path, monkeypatch, client):
    from backend.app.config import load_settings

    for k in ("INVENTORY_XLSX_POLL_SECONDS", "INVENTORY_XLSX_AUTO_APPLY"):
        monkeypatch.delenv(k, raising=False)
    s = load_settings(env_file=tmp_path / "none.env", api_token="t" * 24)
    assert s.inventory_xlsx_poll_seconds == 30 and s.inventory_xlsx_auto_apply is True
    monkeypatch.setenv("INVENTORY_XLSX_POLL_SECONDS", "0")
    assert load_settings(env_file=tmp_path / "none.env", api_token="t" * 24).inventory_xlsx_poll_seconds == 0
    monkeypatch.setenv("INVENTORY_XLSX_POLL_SECONDS", "")
    assert load_settings(env_file=tmp_path / "none.env", api_token="t" * 24).inventory_xlsx_poll_seconds == 30
    page = client.get("/admin/inventory-sync")
    assert page.status_code == 200 and "Apply valid rows" in page.text and "excel-sync/status" in page.text


def test_x6_real_app_poller_with_concurrent_http_and_edits(tmp_path):
    """create_app + lifespan poller thread (0.1 s) + concurrent /use over HTTP + human edits -> converges."""
    import threading
    import time

    from fastapi.testclient import TestClient

    from backend.app.config import load_settings
    from backend.app.main import create_app

    from .conftest import TOKEN

    xlsx = tmp_path / "linked" / "inventory.xlsx"
    settings = load_settings(env_file=tmp_path / "none.env", api_token=TOKEN, database_path=tmp_path / "a.sqlite3",
                             upload_dir=tmp_path / "u", inventory_xlsx_path=xlsx, inventory_xlsx_poll_seconds=0.1)
    seed(settings.database_path)
    rng = random.Random(5)
    with TestClient(create_app(settings)) as c:
        c.headers.update(AUTH)
        c.post("/api/v1/inventory/import/preview")  # no-op request to warm up the app
        errors = []

        def worker(n):
            for _ in range(n):
                r = c.post("/api/v1/inventory/use", json={"product_id": rng.choice([S, A, H]), "quantity": 1,
                                                          "idempotency_key": uuid.uuid4().hex, "confirmed": True})
                if r.status_code not in (200, 409):
                    errors.append(r.text)

        threads = [threading.Thread(target=worker, args=(10,)) for _ in range(3)]
        for t in threads:
            t.start()
        for k in range(4):  # a person restocks in Excel while the glasses keep working
            time.sleep(0.4)
            for _ in range(50):
                try:
                    q = excel_stock(xlsx, H)
                    edit(xlsx, {(H, "stock_qty"): int(q) + 10})
                    break
                except Exception:
                    time.sleep(0.05)
        for t in threads:
            t.join()
        assert not errors, errors[:3]
        from datetime import datetime, timezone

        after_edits = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        deadline = time.time() + 15
        st = None
        while time.time() < deadline:  # wait for a poller result produced AFTER the last human edit
            st = c.get("/api/v1/inventory/excel-sync/status").json()
            lr = st["last_result"] or {}
            if (lr.get("at", "") > after_edits and lr.get("status") == "up_to_date" and st["state"] == "ok"
                    and not st["pending_export"]):
                break
            time.sleep(0.2)
        assert st["state"] == "ok" and not st["pending_export"], st
        for pid in (S, A, H):
            assert excel_stock(xlsx, pid) == c.get(f"/api/v1/inventory/products/{pid}").json()["stock_qty"]
    conn = connect(settings.database_path)
    try:
        check_invariants(conn)
        assert conn.execute("SELECT COUNT(*) FROM inventory_transactions WHERE source = 'excel_sync'").fetchone()[0] >= 1
    finally:
        conn.close()
