"""SQLite schema (sqlite3, no ORM). SQLite is the operational source of truth;
Excel/CSV is only an import/export format.

Schema changes are additive: each statement is idempotent so `init_db` can run
on every start without losing data.
"""

SCHEMA_VERSION = 1

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
