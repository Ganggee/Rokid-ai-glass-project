"""SQLite connection helpers.

* WAL journal + busy timeout so the API and CLI scripts can share the file.
* Connections run in autocommit mode (isolation_level=None); writers open an
  explicit ``BEGIN IMMEDIATE`` transaction via :func:`write_transaction`, which
  takes the database write lock up front so read-check-write sequences (stock
  check then decrement) are atomic.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import MIGRATION_COLUMNS, SCHEMA, SCHEMA_VERSION


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Add columns introduced after v1. Idempotent: checks PRAGMA table_info first."""
    added = []
    for table, cols in MIGRATION_COLUMNS.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, decl in cols:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                added.append(f"{table}.{name}")
    # v1 non-DEMO rows (e.g. MFDS_API) got the column default 'demo_mock' -> keep them ranked above DEMO (review M-1)
    conn.execute("UPDATE nutrition_references SET verification = 'legacy_api' WHERE is_demo = 0 AND verification = 'demo_mock'")
    return added


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    migrate(conn)
    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )


@contextmanager
def write_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE ... COMMIT, rolling back on any exception."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
