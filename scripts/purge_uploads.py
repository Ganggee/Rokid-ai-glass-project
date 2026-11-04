"""Delete meal sessions (rows + photos) older than MEAL_RETENTION_DAYS (default 14).

    python scripts/purge_uploads.py            # dry run
    python scripts/purge_uploads.py --apply
    python scripts/purge_uploads.py --days 3 --apply
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import _bootstrap  # noqa: F401

from backend.app.config import load_settings
from backend.app.db import connect, init_db
from backend.app.services import meal_comparison


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args(argv)
    settings = load_settings()
    days = a.days if a.days is not None else settings.meal_retention_days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = connect(settings.database_path)
    init_db(conn)
    old = conn.execute("SELECT id, created_at FROM meal_sessions WHERE created_at < ?", (cutoff,)).fetchall()
    print(f"{len(old)} session(s) older than {days} day(s)")
    for row in old:
        print(f"  {row['id']} {row['created_at']}")
        if a.apply:
            meal_comparison.delete_session(conn, settings.upload_dir, row["id"])
    if old and not a.apply:
        print("Dry run. Add --apply to delete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
