"""Long-run soak test for inventory + Excel sync ("can this run continuously?").

    python scripts/soak_inventory_excel.py --seed 2026 --uses 2000 --edits 60 --restarts 6

Random stock uses, simulated human edits of several kinds (stock change, new row, product_id typo with a
copied barcode, deleted row, invalid value), safe auto-apply like the poller with manual applies for
rows that need review, simulated locked-file export failures and
connection restarts (in-process: the SQLite connection and sync state are recreated; the OS process is
not restarted — server-restart recovery is covered by tests). At the end it asserts:
  stock == sum of transaction deltas for every product, never negative, Excel == DB after sync,
  no idempotency key applied twice, no Excel file content applied twice, no typo product created,
  sync tables stay bounded (KEEP_EXPORTS or the 90-day window capped at KEEP_MAX_EXPORTS, KEEP_EVENTS), and
  every human stock edit survives: Σ excel_sync adjusts = Σ human deltas − reported negative-merge conflicts.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import _bootstrap  # noqa: F401

from backend.app.db import connect
from backend.tests.conftest import seed
from backend.tests.test_excel_sync import run_soak


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--uses", type=int, default=2000)
    p.add_argument("--edits", type=int, default=60)
    p.add_argument("--restarts", type=int, default=6)
    a = p.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "soak.sqlite3"
        seed(db)
        conn = connect(db)
        for pid in ("CARE-SENS-AIR-SENSOR", "CARE-SENS-AIR-APPLICATOR", "HICARDI-PATCH"):
            conn.execute("UPDATE products SET stock_qty = stock_qty + 3000 WHERE product_id = ?", (pid,))
            conn.execute("INSERT INTO inventory_transactions(product_id, tx_type, quantity_delta, stock_before, stock_after, "
                         "source, created_at) SELECT product_id, 'adjust', 3000, stock_qty - 3000, stock_qty, 'soak_setup', 'setup' "
                         "FROM products WHERE product_id = ?", (pid,))
        t0 = time.perf_counter()
        conn, stats = run_soak(conn, Path(tmp) / "linked" / "inventory.xlsx", a.seed, a.uses, a.edits, a.restarts, db_path=db)
        stats["seconds"] = round(time.perf_counter() - t0, 1)
        stats["excel_imports"] = conn.execute("SELECT COUNT(*) FROM excel_imports").fetchone()[0]
        stats["exports_retained"] = conn.execute("SELECT COUNT(*) FROM excel_exports WHERE status='written'").fetchone()[0]
        stats["conflicts_logged"] = conn.execute("SELECT COUNT(*) FROM excel_sync_events WHERE kind='conflict'").fetchone()[0]
        stats["db_bytes"] = db.stat().st_size
        stats["result"] = "PASS (all invariants held)"
        conn.close()
    print(json.dumps({"seed": a.seed, **stats}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
