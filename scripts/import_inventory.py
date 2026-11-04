"""Import inventory from .xlsx/.csv into the SQLite source of truth.

Preview only (default, no DB product changes):
    python scripts/import_inventory.py sample-data/inventory_demo.csv
Apply explicitly:
    python scripts/import_inventory.py my.xlsx --mode seed --apply
Column mapping for real files (JSON {target_field: "header in file"}):
    python scripts/import_inventory.py real.xlsx --mapping mapping.json --sheet Sheet1

Modes
  seed      create new products only; existing products keep their DB stock (safe re-import)
  adjust    also set existing products' stock to the file value (writes 'adjust' history rows)
  metadata  update names/codes/LOT/location only; stock untouched
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from backend.app.config import REPO_ROOT, load_settings
from backend.app.db import connect, init_db
from backend.app.errors import ApiError
from backend.app.services import inventory_service as inv


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file", type=Path)
    p.add_argument("--mode", choices=["seed", "adjust", "metadata"], default="seed")
    p.add_argument("--apply", action="store_true", help="commit the previewed rows (otherwise preview only)")
    p.add_argument("--mapping", type=Path, help="JSON column mapping file")
    p.add_argument("--sheet", help="xlsx sheet name (default: first sheet)")
    p.add_argument("--skip-invalid-rows", action="store_true")
    p.add_argument("--demo", action="store_true", help="mark created products as DEMO data")
    p.add_argument("--report", type=Path, help="write the JSON report here (default reports/import_<batch>.json)")
    p.add_argument("--database", help="override DATABASE_PATH")
    args = p.parse_args(argv)

    overrides = {"database_path": args.database} if args.database else {}
    settings = load_settings(**overrides)
    conn = connect(settings.database_path)
    init_db(conn)
    mapping = json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping else None
    try:
        preview = inv.preview_import(conn, args.file.name, args.file.read_bytes(), mapping, args.sheet)
    except ApiError as exc:
        print(f"ERROR {exc.code}: {exc.message}", file=sys.stderr)
        return 2

    print(f"File: {args.file}  rows={preview['row_count']} valid={preview['valid_rows']} "
          f"errors={preview['error_count']} warnings={preview['warning_count']}")
    print(f"Column mapping: {json.dumps(preview['column_mapping'], ensure_ascii=False)}")
    for row in preview["rows"]:
        state = "EXISTS(db={})".format(row["current_stock_qty"]) if row["exists_in_db"] else "NEW"
        flag = " ERR: " + "; ".join(row["errors"]) if row["errors"] else ""
        print(f"  row {row['row']:>3} {row['product_id']!s:<28} qty={row['stock_qty']!s:<5} {state}{flag}")
    for w in preview["warnings"]:
        print(f"  WARN row {w['row']} {w['field']}: {w['message']}")

    report: dict = {"preview": {k: preview[k] for k in ("batch_id", "row_count", "valid_rows", "error_count", "warning_count")}}
    if args.apply:
        try:
            result = inv.commit_import(conn, preview["batch_id"], args.mode, args.skip_invalid_rows,
                                       source="import_cli", is_demo=args.demo)
        except ApiError as exc:
            print(f"NOT APPLIED {exc.code}: {exc.message}", file=sys.stderr)
            return 3
        report["commit"] = result
        print(f"APPLIED mode={args.mode}: {json.dumps(result['counts'], ensure_ascii=False)}")
    else:
        print("Preview only. Re-run with --apply to commit.")

    out = args.report or (REPO_ROOT / "reports" / f"import_{preview['batch_id']}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
