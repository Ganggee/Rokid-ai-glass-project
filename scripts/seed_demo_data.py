"""Seed DEMO inventory (20/10/15) and DEMO nutrition references.

Safe to run repeatedly: inventory uses `seed` mode, so existing products keep
their current (already decremented) stock. Use --reset to start from scratch.

    python scripts/seed_demo_data.py
    python scripts/seed_demo_data.py --reset   # deletes the SQLite file first
"""
from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from backend.app.config import REPO_ROOT, load_settings
from backend.app.db import connect, init_db
from backend.app.services import inventory_service as inv
from backend.app.services import nutrition_lookup


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true", help="delete the database file before seeding")
    p.add_argument("--database", help="override DATABASE_PATH")
    args = p.parse_args(argv)
    settings = load_settings(**({"database_path": args.database} if args.database else {}))
    if args.reset:
        for suffix in ("", "-wal", "-shm"):
            f = settings.database_path.with_name(settings.database_path.name + suffix)
            if f.exists():
                f.unlink()
    conn = connect(settings.database_path)
    init_db(conn)
    csv_path = REPO_ROOT / "sample-data" / "inventory_demo.csv"
    preview = inv.preview_import(conn, csv_path.name, csv_path.read_bytes())
    report = inv.commit_import(conn, preview["batch_id"], "seed", source="seed_demo", is_demo=True)
    n = nutrition_lookup.load_csv(conn, settings.nutrition_csv)
    print(f"Inventory seed: {report['counts']}")
    for p_ in inv.search_products(conn):
        print(f"  {p_['product_id']:<28} {p_['stock_qty']:>4} {p_['unit']}  (DEMO={p_['is_demo']})")
    print(f"Nutrition references loaded: {n} from {settings.nutrition_csv.name}")
    print(f"Database: {settings.database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
