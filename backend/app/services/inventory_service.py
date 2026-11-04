"""Inventory domain logic: queries, atomic idempotent stock use, history,
Excel/CSV import (preview -> explicit commit), code lookup and command parsing.

Invariants enforced here (and by the schema):
* stock never goes below zero (CHECK constraint + guarded UPDATE);
* every stock change writes exactly one inventory_transactions row;
* a given idempotency_key is applied at most once (UNIQUE + lookup inside the
  same BEGIN IMMEDIATE transaction);
* nothing is written unless the request carries confirmed=true.
"""
from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import re
import sqlite3
import uuid
from datetime import date, datetime
from typing import Any, Iterable

from .. import errors
from ..db import utcnow, write_transaction
from ..errors import ApiError

PRODUCT_FIELDS = (
    "product_id", "product_name", "category", "stock_qty", "unit", "barcode",
    "qr_value", "lot_no", "expiration_date", "location", "aliases",
)

# Header aliases accepted automatically (Korean/English). A mapping JSON can override.
DEFAULT_HEADER_ALIASES: dict[str, list[str]] = {
    "product_id": ["product_id", "제품id", "제품코드", "품목코드", "품번", "id", "sku"],
    "product_name": ["product_name", "제품명", "품목명", "품명", "name"],
    "category": ["category", "분류", "카테고리", "품목구분"],
    "stock_qty": ["stock_qty", "재고", "재고수량", "수량", "현재고", "qty", "stock"],
    "unit": ["unit", "단위"],
    "barcode": ["barcode", "바코드", "ean", "gtin"],
    "qr_value": ["qr_value", "qr", "qr코드", "qrcode"],
    "lot_no": ["lot_no", "lot", "로트", "로트번호", "제조번호"],
    "expiration_date": ["expiration_date", "유효기간", "사용기한", "만료일", "exp", "expiry"],
    "location": ["location", "위치", "보관위치", "보관장소"],
    "aliases": ["aliases", "별칭", "검색어", "음성별칭"],
}


# ------------------------------------------------------------------ helpers
def _product(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = {k: row[k] for k in row.keys()}
    data["is_demo"] = bool(data.get("is_demo"))
    data.pop("aliases", None)
    data.pop("created_at", None)
    return data


def _tx(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = {k: row[k] for k in row.keys()}
    data.pop("import_batch_id", None)
    return data


def record_recognition(conn: sqlite3.Connection, kind: str, outcome: str) -> None:
    conn.execute(
        "INSERT INTO recognition_events(kind, outcome, created_at) VALUES (?, ?, ?)",
        (kind, outcome, utcnow()),
    )


def recognition_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT kind, outcome, COUNT(*) AS n FROM recognition_events GROUP BY kind, outcome ORDER BY kind"
    ).fetchall()
    stats: dict[str, dict[str, int]] = {}
    for r in rows:
        stats.setdefault(r["kind"], {})[r["outcome"]] = r["n"]
    return {"by_kind": stats, "note": "Counts of observed outcomes only. Not an accuracy measurement."}


# ------------------------------------------------------------------ queries
def get_product(conn: sqlite3.Connection, product_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
    if row is None:
        raise ApiError(404, errors.PRODUCT_NOT_FOUND, f"Product '{product_id}' not found")
    return _product(row)


def search_products(conn: sqlite3.Connection, query: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if not query:
        rows = conn.execute("SELECT * FROM products ORDER BY product_name LIMIT ?", (limit,)).fetchall()
        return [_product(r) for r in rows]
    like = f"%{query.strip()}%"
    rows = conn.execute(
        """SELECT DISTINCT p.* FROM products p
           LEFT JOIN product_codes c ON c.product_id = p.product_id
           WHERE p.product_id LIKE ? OR p.product_name LIKE ? OR p.category LIKE ?
                 OR p.aliases LIKE ? OR c.code_value = ?
           ORDER BY p.product_name LIMIT ?""",
        (like, like, like, like, query.strip(), limit),
    ).fetchall()
    return [_product(r) for r in rows]


def list_transactions(conn: sqlite3.Connection, product_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if product_id:
        rows = conn.execute(
            "SELECT * FROM inventory_transactions WHERE product_id = ? ORDER BY id DESC LIMIT ?",
            (product_id, limit),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM inventory_transactions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_tx(r) for r in rows]


def operation_status(conn: sqlite3.Connection, idempotency_key: str) -> dict[str, Any]:
    tx = conn.execute("SELECT * FROM inventory_transactions WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
    if tx is None:
        return {"idempotency_key": idempotency_key, "applied": False, "transaction": None, "product": None}
    product = conn.execute("SELECT * FROM products WHERE product_id = ?", (tx["product_id"],)).fetchone()
    return {"idempotency_key": idempotency_key, "applied": True, "transaction": _tx(tx), "product": _product(product)}


# ------------------------------------------------------------------ use (decrement)
def use_stock(
    conn: sqlite3.Connection,
    *,
    product_id: str,
    quantity: int,
    idempotency_key: str,
    confirmed: bool,
    client_timestamp: str | None = None,
    source: str = "api",
    note: str | None = None,
) -> dict[str, Any]:
    """Atomically decrement stock once per idempotency_key.

    Returns {"product", "transaction", "replayed"}. A replay with the same key
    and identical payload returns the original transaction without writing.
    """
    if not confirmed:
        raise ApiError(400, errors.CONFIRMATION_REQUIRED,
                       "confirmed must be true. Show the confirmation screen and resend only after the user confirms.")
    if quantity < 1:
        raise ApiError(422, errors.VALIDATION_ERROR, "quantity must be >= 1")

    with write_transaction(conn):
        existing = conn.execute(
            "SELECT * FROM inventory_transactions WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if existing is not None:
            if existing["product_id"] != product_id or existing["quantity_delta"] != -quantity:
                raise ApiError(409, errors.IDEMPOTENCY_KEY_REUSED,
                               "This idempotency_key was already used for a different request.",
                               {"existing_transaction_id": existing["id"]})
            product = conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
            return {"product": _product(product), "transaction": _tx(existing), "replayed": True}

        product = conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
        if product is None:
            raise ApiError(404, errors.PRODUCT_NOT_FOUND, f"Product '{product_id}' not found")
        before = product["stock_qty"]
        if before < quantity:
            raise ApiError(409, errors.INSUFFICIENT_STOCK,
                           f"Insufficient stock: {before} {product['unit']} available, {quantity} requested.",
                           {"stock_qty": before, "requested": quantity})
        now = utcnow()
        cur = conn.execute(
            "UPDATE products SET stock_qty = stock_qty - ?, updated_at = ? WHERE product_id = ? AND stock_qty >= ?",
            (quantity, now, product_id, quantity),
        )
        if cur.rowcount != 1:  # defensive: should be impossible under BEGIN IMMEDIATE
            raise ApiError(409, errors.INSUFFICIENT_STOCK, "Stock changed concurrently; retry with the same key.")
        tx_id = conn.execute(
            """INSERT INTO inventory_transactions
               (product_id, tx_type, quantity_delta, stock_before, stock_after, idempotency_key,
                source, client_timestamp, note, created_at)
               VALUES (?, 'use', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (product_id, -quantity, before, before - quantity, idempotency_key, source, client_timestamp, note, now),
        ).lastrowid
        tx = conn.execute("SELECT * FROM inventory_transactions WHERE id = ?", (tx_id,)).fetchone()
        product = conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
        return {"product": _product(product), "transaction": _tx(tx), "replayed": False}


# ------------------------------------------------------------------ code lookup
def resolve_code(conn: sqlite3.Connection, code: str, code_type: str = "auto") -> dict[str, Any]:
    """Exact lookup of a decoded QR/barcode string. No parsing of the content:
    whether a QR encodes a product type, LOT or serial is unknown, so only
    explicitly mapped values match."""
    value = code.strip()
    types = ("qr", "barcode") if code_type == "auto" else (code_type,)
    for t in types:
        row = conn.execute(
            "SELECT p.* FROM product_codes c JOIN products p ON p.product_id = c.product_id "
            "WHERE c.code_type = ? AND c.code_value = ?",
            (t, value),
        ).fetchone()
        if row is not None:
            return {"status": "matched", "product": _product(row), "candidates": [],
                    "evidence": [{"method": f"{t}_mapping", "raw_value": value}], "message": ""}
    row = conn.execute("SELECT * FROM products WHERE product_id = ?", (value,)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM products WHERE lower(product_id) = lower(?)", (value,)).fetchone()
    if row is not None:
        return {"status": "matched", "product": _product(row), "candidates": [],
                "evidence": [{"method": "product_id_exact", "raw_value": value}], "message": ""}
    return {"status": "unrecognized", "product": None, "candidates": [],
            "evidence": [{"method": "code_lookup", "raw_value": value}],
            "message": "Code is not mapped to any product. Select the product manually or add the code to the mapping."}


# ------------------------------------------------------------------ voice/text command parsing
_KO_NUM = {"한": 1, "하나": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4, "다섯": 5,
           "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}
_EN_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "a": 1, "an": 1}
_CANCEL = re.compile(r"(취소|그만|아니(요|오)?$|^no$|cancel|abort)", re.I)
_CONFIRM = re.compile(r"^(사용\s*확인|확인|예|네|응|맞아|confirm|yes|ok(ay)?)\s*[.!]?$", re.I)
_USE = re.compile(r"(사용|차감|썼|쓸게|소모|빼|\buse\b|\bused\b|consume)", re.I)
_QUERY = re.compile(r"(재고|몇\s*개|얼마|남았|조회|알려|stock|how\s+many|check)", re.I)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _aliases_for(row: sqlite3.Row) -> list[str]:
    names = [row["product_name"], row["product_id"]]
    if row["aliases"]:
        names.extend(a for a in row["aliases"].split(";"))
    return [n.strip() for n in names if n and n.strip()]


def match_products_by_text(conn: sqlite3.Connection, text: str, limit: int = 3) -> list[dict[str, Any]]:
    """Score products by alias containment, then fuzzy similarity."""
    compact = _compact(text)
    scored: list[tuple[float, sqlite3.Row, str]] = []
    for row in conn.execute("SELECT * FROM products").fetchall():
        best, best_alias = 0.0, ""
        for alias in _aliases_for(row):
            a = _compact(alias)
            if len(a) >= 2 and a in compact:
                score = 1.0 + len(a) / 100.0
            else:
                score = difflib.SequenceMatcher(None, a, compact).ratio() * 0.9
            if score > best:
                best, best_alias = score, alias
        if best >= 0.55:
            scored.append((best, row, best_alias))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [{"product": _product(r), "score": round(s, 3), "matched_alias": a} for s, r, a in scored[:limit]]


def _quantity(text: str) -> int | None:
    m = re.search(r"(\d+)\s*(개|ea|pcs?|box|박스)?", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(한|하나|두|둘|세|셋|네|넷|다섯|여섯|일곱|여덟|아홉|열)\s*(개|박스)", text)
    if m:
        return _KO_NUM[m.group(1)]
    m = re.search(r"\buse\s+(one|two|three|four|five|a|an)\b", text, re.I)
    if m:
        return _EN_NUM[m.group(1).lower()]
    return None


def parse_command(conn: sqlite3.Connection, text: str) -> dict[str, Any]:
    """Convert recognized speech/typed text into a structured command. Never writes."""
    t = text.strip()
    base = {"text": t, "quantity": None, "product": None, "candidates": []}
    if _CANCEL.search(t):
        return {**base, "intent": "cancel", "requires_confirmation": False}
    if _CONFIRM.match(t):
        return {**base, "intent": "confirm", "requires_confirmation": False}
    matches = match_products_by_text(conn, t)
    top = matches[0] if matches else None
    ambiguous = len(matches) > 1 and matches[1]["score"] >= matches[0]["score"] - 0.02
    product = top["product"] if top and not ambiguous else None
    candidates = matches if (ambiguous or not top) else []
    if _USE.search(t):
        return {**base, "intent": "use", "quantity": _quantity(t) or 1, "product": product,
                "candidates": candidates, "requires_confirmation": True}
    if _QUERY.search(t) or product:
        return {**base, "intent": "query_stock", "product": product, "candidates": candidates,
                "requires_confirmation": False}
    return {**base, "intent": "unknown", "candidates": candidates, "requires_confirmation": False}


# ------------------------------------------------------------------ import
def _cell_to_str(value: Any) -> tuple[str, bool]:
    """Return (text, was_numeric). Keeps integers without '.0'."""
    if value is None:
        return "", False
    if isinstance(value, bool):
        return str(value), False
    if isinstance(value, (datetime, date)):
        return (value.date() if isinstance(value, datetime) else value).isoformat(), False
    if isinstance(value, float):
        return (str(int(value)) if value.is_integer() else repr(value)), True
    if isinstance(value, int):
        return str(value), True
    return str(value).strip(), False


def read_table(filename: str, content: bytes, sheet: str | None = None) -> tuple[list[str], list[dict[str, tuple[str, bool]]]]:
    name = filename.lower()
    if name.endswith(".csv"):
        for enc in ("utf-8-sig", "cp949"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ApiError(422, errors.VALIDATION_ERROR, "CSV must be UTF-8 or CP949 encoded")
        reader = csv.reader(io.StringIO(text))
        table = [row for row in reader]
        if not table:
            raise ApiError(422, errors.VALIDATION_ERROR, "File is empty")
        headers = [h.strip() for h in table[0]]
        rows = [{headers[i]: (cell.strip(), False) for i, cell in enumerate(r) if i < len(headers)}
                for r in table[1:] if any(c.strip() for c in r)]
        return headers, rows
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb[sheet] if sheet else wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        try:
            header_row = next(it)
        except StopIteration:
            raise ApiError(422, errors.VALIDATION_ERROR, "Sheet is empty")
        headers = [_cell_to_str(h)[0] for h in header_row]
        rows = []
        for r in it:
            if r is None or all(c is None or str(c).strip() == "" for c in r):
                continue
            rows.append({headers[i]: _cell_to_str(c) for i, c in enumerate(r) if i < len(headers) and headers[i]})
        return headers, rows
    raise ApiError(415, errors.UNSUPPORTED_MEDIA_TYPE, "Only .csv and .xlsx files are supported")


def build_column_mapping(headers: Iterable[str], mapping: dict[str, str] | None = None) -> dict[str, str]:
    """Return {canonical_field: source_header}."""
    result: dict[str, str] = {}
    lowered = {h.strip().lower().replace(" ", ""): h for h in headers if h}
    for field, aliases in DEFAULT_HEADER_ALIASES.items():
        for alias in aliases:
            key = alias.lower().replace(" ", "")
            if key in lowered:
                result[field] = lowered[key]
                break
    for field, header in (mapping or {}).items():
        if field not in PRODUCT_FIELDS:
            raise ApiError(422, errors.VALIDATION_ERROR, f"Unknown target field in mapping: {field}")
        if header not in set(headers):
            raise ApiError(422, errors.VALIDATION_ERROR, f"Mapped header '{header}' not found in file")
        result[field] = header
    return result


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def preview_import(
    conn: sqlite3.Connection,
    filename: str,
    content: bytes,
    mapping: dict[str, str] | None = None,
    sheet: str | None = None,
) -> dict[str, Any]:
    headers, raw_rows = read_table(filename, content, sheet)
    colmap = build_column_mapping(headers, mapping)
    errs: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    for required in ("product_id", "product_name", "stock_qty"):
        if required not in colmap:
            errs.append({"row": None, "field": required, "message": f"Required column for '{required}' not found"})
    if errs:
        rows: list[dict[str, Any]] = []
    else:
        rows = []
        seen_ids: dict[str, int] = {}
        seen_codes: dict[tuple[str, str], int] = {}
        for idx, raw in enumerate(raw_rows, start=2):  # header is row 1
            row: dict[str, Any] = {"row": idx}
            row_errors: list[str] = []
            for field in PRODUCT_FIELDS:
                header = colmap.get(field)
                text, numeric = raw.get(header, ("", False)) if header else ("", False)
                row[field] = text or None
                if field in ("barcode", "qr_value") and numeric and text:
                    warns.append({"row": idx, "field": field,
                                  "message": "Stored as a number in Excel; leading zeros may already be lost. Format the column as Text."})
            pid = row["product_id"]
            if not pid:
                row_errors.append("product_id is required")
            elif pid in seen_ids:
                row_errors.append(f"duplicate product_id (also row {seen_ids[pid]})")
            else:
                seen_ids[pid] = idx
            if not row["product_name"]:
                row_errors.append("product_name is required")
            qty_text = row["stock_qty"]
            try:
                qty_f = float(qty_text) if qty_text is not None else None
                if qty_f is None or not qty_f.is_integer() or qty_f < 0:
                    raise ValueError
                row["stock_qty"] = int(qty_f)
            except (TypeError, ValueError):
                row_errors.append(f"stock_qty must be an integer >= 0 (got '{qty_text}')")
                row["stock_qty"] = None
            row["unit"] = row["unit"] or "ea"
            if row["expiration_date"] and not _DATE_RE.match(row["expiration_date"]):
                row_errors.append("expiration_date must be yyyy-mm-dd")
            for code_type, field in (("barcode", "barcode"), ("qr", "qr_value")):
                value = row[field]
                if not value:
                    continue
                key = (code_type, value)
                if key in seen_codes:
                    row_errors.append(f"duplicate {field} '{value}' (also row {seen_codes[key]})")
                else:
                    seen_codes[key] = idx
                owner = conn.execute(
                    "SELECT product_id FROM product_codes WHERE code_type = ? AND code_value = ?", key
                ).fetchone()
                if owner is not None and owner["product_id"] != pid:
                    row_errors.append(f"{field} '{value}' already mapped to product {owner['product_id']}")
            existing = conn.execute("SELECT stock_qty FROM products WHERE product_id = ?", (pid,)).fetchone() if pid else None
            row["exists_in_db"] = existing is not None
            row["current_stock_qty"] = existing["stock_qty"] if existing else None
            row["errors"] = row_errors
            for message in row_errors:
                errs.append({"row": idx, "field": None, "message": message})
            rows.append(row)
    batch_id = uuid.uuid4().hex
    sha = hashlib.sha256(content).hexdigest()
    preview = {
        "batch_id": batch_id,
        "filename": filename,
        "file_sha256": sha,
        "row_count": len(rows),
        "valid_rows": sum(1 for r in rows if not r["errors"]),
        "error_count": len(errs),
        "warning_count": len(warns),
        "errors": errs,
        "warnings": warns,
        "rows": rows,
        "column_mapping": colmap,
    }
    conn.execute(
        "INSERT INTO import_batches(id, filename, file_sha256, status, preview_json, created_at) VALUES (?, ?, ?, 'previewed', ?, ?)",
        (batch_id, filename, sha, json.dumps(preview, ensure_ascii=False), utcnow()),
    )
    return preview


def _set_codes(conn: sqlite3.Connection, product_id: str, barcode: str | None, qr_value: str | None) -> None:
    if barcode:
        conn.execute("DELETE FROM product_codes WHERE product_id = ? AND code_type = 'barcode'", (product_id,))
        conn.execute("INSERT INTO product_codes(code_type, code_value, product_id) VALUES ('barcode', ?, ?)", (barcode, product_id))
    if qr_value:
        conn.execute("DELETE FROM product_codes WHERE product_id = ? AND code_type = 'qr'", (product_id,))
        conn.execute("INSERT INTO product_codes(code_type, code_value, product_id) VALUES ('qr', ?, ?)", (qr_value, product_id))


_META_FIELDS = ("product_name", "category", "unit", "barcode", "qr_value", "lot_no", "expiration_date", "location", "aliases")


def commit_import(
    conn: sqlite3.Connection,
    batch_id: str,
    mode: str,
    skip_invalid_rows: bool = False,
    source: str = "import",
    is_demo: bool = False,
) -> dict[str, Any]:
    if mode not in ("seed", "adjust", "metadata"):
        raise ApiError(422, errors.VALIDATION_ERROR, "mode must be seed | adjust | metadata")
    with write_transaction(conn):
        batch = conn.execute("SELECT * FROM import_batches WHERE id = ?", (batch_id,)).fetchone()
        if batch is None:
            raise ApiError(404, errors.NOT_FOUND, "Import batch not found. Run preview first.")
        if batch["status"] == "committed":
            raise ApiError(409, errors.IMPORT_ALREADY_COMMITTED, "This import batch was already committed.",
                           {"report": json.loads(batch["report_json"] or "{}")})
        preview = json.loads(batch["preview_json"])
        if preview["error_count"] and not skip_invalid_rows:
            raise ApiError(409, errors.IMPORT_HAS_ERRORS,
                           "Preview has errors. Fix the file or commit with skip_invalid_rows=true.",
                           {"error_count": preview["error_count"]})
        now = utcnow()
        results = []
        counts = {"created": 0, "stock_adjusted": 0, "metadata_updated": 0, "skipped_existing": 0, "skipped_invalid": 0}
        for row in preview["rows"]:
            pid = row["product_id"]
            if row["errors"]:
                counts["skipped_invalid"] += 1
                results.append({"row": row["row"], "product_id": pid, "action": "skipped_invalid", "errors": row["errors"]})
                continue
            existing = conn.execute("SELECT * FROM products WHERE product_id = ?", (pid,)).fetchone()
            if existing is None:
                if mode == "metadata":
                    counts["skipped_invalid"] += 1
                    results.append({"row": row["row"], "product_id": pid, "action": "skipped_not_found"})
                    continue
                conn.execute(
                    """INSERT INTO products(product_id, product_name, category, stock_qty, unit, barcode, qr_value,
                       lot_no, expiration_date, location, aliases, is_demo, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (pid, row["product_name"], row["category"], row["stock_qty"], row["unit"], row["barcode"],
                     row["qr_value"], row["lot_no"], row["expiration_date"], row["location"], row["aliases"],
                     1 if is_demo else 0, now, now),
                )
                conn.execute(
                    """INSERT INTO inventory_transactions(product_id, tx_type, quantity_delta, stock_before, stock_after,
                       source, import_batch_id, note, created_at) VALUES (?, 'seed', ?, 0, ?, ?, ?, ?, ?)""",
                    (pid, row["stock_qty"], row["stock_qty"], source, batch_id, f"initial stock from {preview['filename']}", now),
                )
                _set_codes(conn, pid, row["barcode"], row["qr_value"])
                counts["created"] += 1
                results.append({"row": row["row"], "product_id": pid, "action": "created", "stock_qty": row["stock_qty"]})
                continue
            if mode == "seed":
                counts["skipped_existing"] += 1
                results.append({"row": row["row"], "product_id": pid, "action": "skipped_existing",
                                "db_stock_qty": existing["stock_qty"], "file_stock_qty": row["stock_qty"]})
                continue
            # adjust / metadata: update metadata fields that are present in the file
            updates = {f: row[f] for f in _META_FIELDS if row.get(f)}
            if updates:
                sets = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(f"UPDATE products SET {sets}, updated_at = ? WHERE product_id = ?",
                             (*updates.values(), now, pid))
                _set_codes(conn, pid, row["barcode"], row["qr_value"])
                counts["metadata_updated"] += 1
            action = {"row": row["row"], "product_id": pid, "action": "metadata_updated" if updates else "unchanged"}
            if mode == "adjust" and existing["stock_qty"] != row["stock_qty"]:
                delta = row["stock_qty"] - existing["stock_qty"]
                conn.execute("UPDATE products SET stock_qty = ?, updated_at = ? WHERE product_id = ?",
                             (row["stock_qty"], now, pid))
                conn.execute(
                    """INSERT INTO inventory_transactions(product_id, tx_type, quantity_delta, stock_before, stock_after,
                       source, import_batch_id, note, created_at) VALUES (?, 'adjust', ?, ?, ?, ?, ?, ?, ?)""",
                    (pid, delta, existing["stock_qty"], row["stock_qty"], source, batch_id,
                     f"stock adjustment from {preview['filename']}", now),
                )
                counts["stock_adjusted"] += 1
                action.update(action="stock_adjusted", stock_before=existing["stock_qty"], stock_after=row["stock_qty"])
            results.append(action)
        report = {"batch_id": batch_id, "filename": preview["filename"], "mode": mode, "committed_at": now,
                  "counts": counts, "rows": results}
        conn.execute("UPDATE import_batches SET status = 'committed', report_json = ?, committed_at = ? WHERE id = ?",
                     (json.dumps(report, ensure_ascii=False), now, batch_id))
        return report
