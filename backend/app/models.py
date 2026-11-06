"""SQLite schema (sqlite3, no ORM). SQLite is the operational source of truth;
Excel/CSV is only an import/export format.

Schema changes are additive: each statement is idempotent so `init_db` can run
on every start without losing data.
"""

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------------------------------------------------------------- inventory
CREATE TABLE IF NOT EXISTS products (
    product_id      TEXT PRIMARY KEY,
    product_name    TEXT NOT NULL,
    category        TEXT,
    stock_qty       INTEGER NOT NULL CHECK (stock_qty >= 0),
    unit            TEXT NOT NULL DEFAULT 'ea',
    barcode         TEXT,
    qr_value        TEXT,
    lot_no          TEXT,
    expiration_date TEXT,
    location        TEXT,
    aliases         TEXT,
    is_demo         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- QR / barcode -> product mapping (one product may carry several codes)
CREATE TABLE IF NOT EXISTS product_codes (
    code_type  TEXT NOT NULL CHECK (code_type IN ('qr', 'barcode')),
    code_value TEXT NOT NULL,
    product_id TEXT NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
    PRIMARY KEY (code_type, code_value)
);

-- Append-only stock history. Every stock change writes exactly one row.
CREATE TABLE IF NOT EXISTS inventory_transactions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id        TEXT NOT NULL REFERENCES products(product_id),
    tx_type           TEXT NOT NULL CHECK (tx_type IN ('seed', 'use', 'adjust')),
    quantity_delta    INTEGER NOT NULL,
    stock_before      INTEGER NOT NULL,
    stock_after       INTEGER NOT NULL CHECK (stock_after >= 0),
    idempotency_key   TEXT UNIQUE,
    source            TEXT NOT NULL,
    client_timestamp  TEXT,
    import_batch_id   TEXT,
    note              TEXT,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tx_product ON inventory_transactions(product_id, id);

CREATE TABLE IF NOT EXISTS import_batches (
    id           TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    file_sha256  TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('previewed', 'committed')),
    preview_json TEXT NOT NULL,
    report_json  TEXT,
    created_at   TEXT NOT NULL,
    committed_at TEXT
);

-- Recognition outcomes so QR/barcode vs OCR success can be reported separately
CREATE TABLE IF NOT EXISTS recognition_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,       -- qr | barcode | ocr | code_lookup
    outcome    TEXT NOT NULL,       -- matched | candidates | none | error | unavailable
    created_at TEXT NOT NULL
);

-- ---------------------------------------------------------------- meals
CREATE TABLE IF NOT EXISTS meal_sessions (
    id         TEXT PRIMARY KEY,
    status     TEXT NOT NULL,       -- created | before_captured | after_captured | analyzed
    note       TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meal_images (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES meal_sessions(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('before', 'after')),
    file_path  TEXT NOT NULL,
    mime_type  TEXT NOT NULL,
    width      INTEGER NOT NULL,
    height     INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256     TEXT NOT NULL,
    detected_regions TEXT,      -- JSON candidate regions (before photo only)
    created_at TEXT NOT NULL,
    UNIQUE (session_id, kind)
);

CREATE TABLE IF NOT EXISTS nutrition_references (
    id                  TEXT PRIMARY KEY,
    food_name           TEXT NOT NULL,
    aliases             TEXT,
    kcal_per_100g       REAL,
    carbs_g_per_100g    REAL,
    protein_g_per_100g  REAL,
    fat_g_per_100g      REAL,
    source              TEXT NOT NULL,
    source_detail       TEXT,
    is_demo             INTEGER NOT NULL DEFAULT 1,
    updated_at          TEXT NOT NULL
);
-- iteration 2 columns are added by db.migrate() (PRAGMA table_info based, idempotent)

CREATE TABLE IF NOT EXISTS meal_items (
    id                    TEXT PRIMARY KEY,
    session_id            TEXT NOT NULL REFERENCES meal_sessions(id) ON DELETE CASCADE,
    position              INTEGER NOT NULL,
    label                 TEXT NOT NULL,
    nutrition_ref_id      TEXT REFERENCES nutrition_references(id),
    initial_serving_grams REAL,
    serving_source        TEXT,     -- user | demo_assumption | NULL
    before_region         TEXT,     -- JSON {"type":"bbox"|"polygon", ...} in before-image pixels
    after_region          TEXT,     -- JSON, optional manual region in after-image pixels
    created_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meal_analyses (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES meal_sessions(id) ON DELETE CASCADE,
    analysis_method TEXT NOT NULL,
    is_demo         INTEGER NOT NULL,
    result_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

-- ---------------------------------------------------------------- meal diary (iteration 2)
CREATE TABLE IF NOT EXISTS meal_logs (
    id              TEXT PRIMARY KEY,
    log_date        TEXT NOT NULL,          -- YYYY-MM-DD, fixed at parse time (APP_TIMEZONE)
    meal_type       TEXT NOT NULL CHECK (meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')),
    source          TEXT NOT NULL CHECK (source IN ('voice', 'analysis', 'manual')),
    meal_session_id TEXT,
    analysis_id     TEXT UNIQUE,            -- one log per analysis (from-session idempotency)
    idempotency_key TEXT UNIQUE,
    utterance       TEXT,
    note            TEXT,
    created_at      TEXT NOT NULL,
    deleted_at      TEXT
);
CREATE INDEX IF NOT EXISTS ix_meal_logs_date ON meal_logs(log_date, meal_type);

-- Values are SNAPSHOTS at logging time: later reference updates never change history.
CREATE TABLE IF NOT EXISTS meal_log_items (
    id                 TEXT PRIMARY KEY,
    log_id             TEXT NOT NULL REFERENCES meal_logs(id) ON DELETE CASCADE,
    position           INTEGER NOT NULL,
    food_name          TEXT NOT NULL,
    spoken_text        TEXT,
    nutrition_ref_id   TEXT,
    ref_source         TEXT,
    ref_verification   TEXT,
    ref_is_demo        INTEGER NOT NULL DEFAULT 0,
    quantity           REAL,
    unit               TEXT,
    grams              REAL,
    grams_basis        TEXT NOT NULL CHECK (grams_basis IN ('stated', 'serving_size', 'analysis', 'unknown')),
    volume_ml          REAL,               -- 1인분 volume for 100 mL-basis foods (never converted to g)
    kcal_per_100g      REAL,
    carbs_g_per_100g   REAL,
    protein_g_per_100g REAL,
    fat_g_per_100g     REAL,
    kcal               REAL,
    carbs_g            REAL,
    protein_g          REAL,
    fat_g              REAL,
    null_reason        TEXT,
    is_estimate        INTEGER NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------------- inventory <-> Excel (iteration 2)
-- key/value state: change_seq (bumped by triggers on every product/stock change), exported_seq, ...
CREATE TABLE IF NOT EXISTS excel_sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO excel_sync_state(key, value) VALUES ('change_seq', '0');
INSERT OR IGNORE INTO excel_sync_state(key, value) VALUES ('exported_seq', '0');

-- One row per SUCCESSFUL export (a 'writing' row exists only between temp-file write and replace).
-- The snapshot (deduplicated by content hash) is the merge BASELINE for files carrying this export_id.
-- Retention: newest KEEP_EXPORTS (50) + the export_id currently written in the file.
CREATE TABLE IF NOT EXISTS excel_snapshots (
    sha           TEXT PRIMARY KEY,
    snapshot_json TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS excel_exports (
    export_id     TEXT PRIMARY KEY,
    path          TEXT NOT NULL,
    change_seq    INTEGER NOT NULL,
    snapshot_sha  TEXT NOT NULL REFERENCES excel_snapshots(sha),
    sha256        TEXT,
    status        TEXT NOT NULL CHECK (status IN ('writing', 'written')),
    created_at    TEXT NOT NULL
);

-- Every applied external edit (file content) — never applied twice (file_sha UNIQUE).
CREATE TABLE IF NOT EXISTS excel_imports (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    export_id           TEXT NOT NULL,
    file_sha256         TEXT NOT NULL UNIQUE,
    excel_snapshot_json TEXT NOT NULL,
    result_json         TEXT NOT NULL,
    applied_at          TEXT NOT NULL
);

-- conflicts / warnings / applied changes for status and audit
CREATE TABLE IF NOT EXISTS excel_sync_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind       TEXT NOT NULL,
    product_id TEXT,
    detail     TEXT
);

CREATE TRIGGER IF NOT EXISTS trg_products_insert_seq AFTER INSERT ON products BEGIN
    UPDATE excel_sync_state SET value = CAST(value AS INTEGER) + 1 WHERE key = 'change_seq';
END;
CREATE TRIGGER IF NOT EXISTS trg_products_update_seq AFTER UPDATE ON products BEGIN
    UPDATE excel_sync_state SET value = CAST(value AS INTEGER) + 1 WHERE key = 'change_seq';
END;

-- ---------------------------------------------------------------- ops
-- Request log without bodies, tokens or photo content.
CREATE TABLE IF NOT EXISTS api_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    method      TEXT NOT NULL,
    path        TEXT NOT NULL,
    status      INTEGER NOT NULL,
    duration_ms REAL NOT NULL,
    error_code  TEXT
);
"""


# Columns added after SCHEMA_VERSION 1. db.migrate() adds the missing ones (ALTER TABLE ADD COLUMN).
MIGRATION_COLUMNS = {
    "nutrition_references": [
        ("category", "TEXT"),
        ("sugars_g_per_100g", "REAL"),
        ("sodium_mg_per_100g", "REAL"),
        ("serving_size_g", "REAL"),
        ("serving_unit", "TEXT"),
        ("basis", "TEXT"),
        ("food_code", "TEXT"),
        ("source_url", "TEXT"),
        ("retrieved_at", "TEXT"),
        ("verification", "TEXT NOT NULL DEFAULT 'demo_mock'"),
        ("serving_size_ml", "REAL"),
        ("micro_verification", "TEXT"),
    ],
    "meal_log_items": [
        ("volume_ml", "REAL"),
    ],
}
