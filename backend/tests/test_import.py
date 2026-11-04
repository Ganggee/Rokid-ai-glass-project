"""Excel/CSV import: preview never writes products; seed never overwrites DB stock; adjust is logged."""
from __future__ import annotations

import io
import json
import uuid

from openpyxl import Workbook

from .conftest import ROOT


def _xlsx(rows, headers) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_reimport_seed_keeps_decremented_stock(client):
    client.post("/api/v1/inventory/use", json={"product_id": "CARE-SENS-AIR-SENSOR", "idempotency_key": uuid.uuid4().hex,
                                               "confirmed": True})
    content = (ROOT / "sample-data" / "inventory_demo.csv").read_bytes()
    prev = client.post("/api/v1/inventory/import/preview", files={"file": ("inventory_demo.csv", content, "text/csv")}).json()
    assert prev["error_count"] == 0 and prev["row_count"] == 3
    sensor_row = next(r for r in prev["rows"] if r["product_id"] == "CARE-SENS-AIR-SENSOR")
    assert sensor_row["exists_in_db"] and sensor_row["current_stock_qty"] == 19 and sensor_row["stock_qty"] == 20
    rep = client.post("/api/v1/inventory/import/commit", json={"batch_id": prev["batch_id"], "mode": "seed"}).json()
    assert rep["counts"]["skipped_existing"] == 3 and rep["counts"]["created"] == 0
    assert client.get("/api/v1/inventory/products/CARE-SENS-AIR-SENSOR").json()["stock_qty"] == 19
    again = client.post("/api/v1/inventory/import/commit", json={"batch_id": prev["batch_id"], "mode": "seed"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "IMPORT_ALREADY_COMMITTED"


def test_xlsx_korean_headers_mapping_errors_and_adjust(client):
    headers = ["품목코드", "품목명", "현재고", "바코드", "유효기간", "비고"]
    rows = [
        ["NEW-ITEM-1", "새 품목", 5, 123456789012, "2027-01-31", "x"],  # numeric cell: leading 0 already lost
        ["HICARDI-PATCH", "HiCardi Patch", 12, None, None, None],
        ["BAD-QTY", "수량 오류", -1, None, None, None],
        ["NEW-ITEM-1", "중복", 1, None, None, None],
        ["BAD-DATE", "날짜 오류", 3, None, "31/12/2027", None],
    ]
    content = _xlsx(rows, headers)
    prev = client.post("/api/v1/inventory/import/preview",
                       files={"file": ("real.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}).json()
    assert prev["column_mapping"]["product_id"] == "품목코드" and prev["column_mapping"]["stock_qty"] == "현재고"
    msgs = " | ".join(e["message"] for e in prev["errors"])
    assert "stock_qty must be an integer" in msgs and "duplicate product_id" in msgs and "yyyy-mm-dd" in msgs
    assert any(w["field"] == "barcode" for w in prev["warnings"])  # numeric barcode warning
    # products untouched by preview
    assert client.get("/api/v1/inventory/products/NEW-ITEM-1").status_code == 404
    blocked = client.post("/api/v1/inventory/import/commit", json={"batch_id": prev["batch_id"], "mode": "adjust"})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "IMPORT_HAS_ERRORS"
    rep = client.post("/api/v1/inventory/import/commit",
                      json={"batch_id": prev["batch_id"], "mode": "adjust", "skip_invalid_rows": True}).json()
    assert rep["counts"]["created"] == 1 and rep["counts"]["stock_adjusted"] == 1
    assert client.get("/api/v1/inventory/products/HICARDI-PATCH").json()["stock_qty"] == 12
    adj = [t for t in client.get("/api/v1/inventory/transactions", params={"product_id": "HICARDI-PATCH"}).json()["items"]
           if t["tx_type"] == "adjust"]
    assert len(adj) == 1 and adj[0]["stock_before"] == 15 and adj[0]["quantity_delta"] == -3


def test_explicit_column_mapping(client):
    csv_text = "Code,Name,Qty\nX-1,Item X,7\n"
    prev = client.post("/api/v1/inventory/import/preview",
                       files={"file": ("m.csv", csv_text.encode(), "text/csv")},
                       data={"column_mapping": json.dumps({"product_id": "Code", "product_name": "Name", "stock_qty": "Qty"})}).json()
    assert prev["error_count"] == 0
    client.post("/api/v1/inventory/import/commit", json={"batch_id": prev["batch_id"], "mode": "seed"})
    assert client.get("/api/v1/inventory/products/X-1").json()["stock_qty"] == 7


def test_missing_required_column(client):
    prev = client.post("/api/v1/inventory/import/preview", files={"file": ("bad.csv", b"foo,bar\n1,2\n", "text/csv")}).json()
    assert prev["error_count"] >= 2 and prev["rows"] == []
