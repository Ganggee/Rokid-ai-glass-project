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
    assert stock(conn) == 24 and any(c["kind"] == "both_changed" for c in r["plan"]["conflicts"])
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
                             upload_dir=tmp_path / "u", inventory_xlsx_path=tmp_path / "linked" / "inventory.xlsx")
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
    rng = random.Random(seed_value)
    pids = [S, A, H]
    stats = {"uses": 0, "rejected": 0, "edits": 0, "restarts": 0, "locked": 0}
    sync(conn, path)
    edit_points = set(rng.sample(range(uses), edits))
    restart_points = set(rng.sample(range(uses), restarts))
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
            rows = {r[header.index("product_id")]: r[header.index("stock_qty")] for r in ws.iter_rows(min_row=2, values_only=True)}
            target = rng.choice(pids)
            edit(path, {(target, "stock_qty"): max(0, int(rows[target]) + rng.choice([5, 10, 20, -1]))})
            stats["edits"] += 1
        if i in restart_points and db_path is not None:
            conn.close()
            conn = connect(db_path)
            stats["restarts"] += 1
        if rng.random() < 0.02:
            stats["locked"] += 1
            orig = xs._replace
            xs._replace = lambda a, b: (_ for _ in ()).throw(PermissionError("locked"))
            sync(conn, path)
            xs._replace = orig
        if rng.random() < 0.3:
            sync(conn, path)
    final = sync(conn, path)
    if final["status"] not in ("up_to_date", "exported", "merged_and_exported"):
        raise AssertionError(final)
    sync(conn, path)
    check_invariants(conn)
    for pid in pids:
        assert excel_stock(path, pid) == stock(conn, pid)
    keys = conn.execute("SELECT idempotency_key, COUNT(*) FROM inventory_transactions WHERE idempotency_key IS NOT NULL "
                        "GROUP BY idempotency_key HAVING COUNT(*) > 1").fetchall()
    assert not keys
    dup = conn.execute("SELECT file_sha256, COUNT(*) FROM excel_imports GROUP BY file_sha256 HAVING COUNT(*) > 1").fetchall()
    assert not dup
    return conn, stats


def test_soak_small(env, tmp_path):
    conn, path = env
    # restock generously so uses keep succeeding
    for pid in (S, A, H):
        conn.execute("UPDATE products SET stock_qty = stock_qty + 300 WHERE product_id = ?", (pid,))
        conn.execute("INSERT INTO inventory_transactions(product_id, tx_type, quantity_delta, stock_before, stock_after, source, created_at) "
                     "SELECT product_id, 'adjust', 300, stock_qty - 300, stock_qty, 'test', 'now' FROM products WHERE product_id = ?", (pid,))
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    conn, stats = run_soak(conn, path, seed_value=7, uses=200, edits=10, restarts=2, db_path=db_path)
    assert stats["edits"] == 10 and stats["restarts"] == 2
