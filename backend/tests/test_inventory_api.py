"""Task 1 inventory: persistence, idempotency, negative-stock guard, auth, lookup."""
from __future__ import annotations

import threading
import uuid

from backend.app.db import connect
from backend.app.services import inventory_service as inv

SENSOR = "CARE-SENS-AIR-SENSOR"


def use(client, key=None, qty=1, confirmed=True, pid=SENSOR):
    return client.post("/api/v1/inventory/use", json={
        "product_id": pid, "quantity": qty, "idempotency_key": key or uuid.uuid4().hex,
        "confirmed": confirmed, "client_timestamp": "2026-11-04T09:00:00+09:00", "source": "pytest"})


def stock(client, pid=SENSOR) -> int:
    return client.get(f"/api/v1/inventory/products/{pid}").json()["stock_qty"]


def test_seeded_demo_products(client):
    body = client.get("/api/v1/inventory/products").json()
    got = {p["product_id"]: p["stock_qty"] for p in body["items"]}
    assert got == {"CARE-SENS-AIR-SENSOR": 20, "CARE-SENS-AIR-APPLICATOR": 10, "HICARDI-PATCH": 15}
    assert all(p["is_demo"] for p in body["items"])


def test_search_by_korean_alias_and_code(client):
    assert client.get("/api/v1/inventory/products", params={"query": "하이카디"}).json()["items"][0]["product_id"] == "HICARDI-PATCH"
    assert client.get("/api/v1/inventory/products", params={"query": "0880000000002"}).json()["items"][0]["product_id"] == "CARE-SENS-AIR-APPLICATOR"


def test_use_20_to_19_and_history_has_one_row(client):
    r = use(client, key="key-20-to-19")
    assert r.status_code == 200, r.text
    assert r.json()["product"]["stock_qty"] == 19
    assert r.json()["replayed"] is False
    assert stock(client) == 19
    txs = client.get("/api/v1/inventory/transactions", params={"product_id": SENSOR}).json()["items"]
    uses = [t for t in txs if t["tx_type"] == "use"]
    assert len(uses) == 1 and uses[0]["stock_before"] == 20 and uses[0]["stock_after"] == 19


def test_same_idempotency_key_twice_decrements_once(client):
    a = use(client, key="dup-key-0001")
    b = use(client, key="dup-key-0001")
    assert a.status_code == b.status_code == 200
    assert b.json()["replayed"] is True
    assert a.json()["transaction"]["id"] == b.json()["transaction"]["id"]
    assert stock(client) == 19
    uses = [t for t in client.get("/api/v1/inventory/transactions").json()["items"] if t["tx_type"] == "use"]
    assert len(uses) == 1


def test_key_reuse_with_different_payload_rejected(client):
    assert use(client, key="reuse-key-01").status_code == 200
    r = use(client, key="reuse-key-01", qty=2)
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert stock(client) == 19


def test_unconfirmed_request_writes_nothing(client):
    r = use(client, confirmed=False)
    assert r.status_code == 400 and r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert stock(client) == 20
    assert not [t for t in client.get("/api/v1/inventory/transactions").json()["items"] if t["tx_type"] == "use"]


def test_cannot_go_below_zero(client):
    r = use(client, qty=10, pid="CARE-SENS-AIR-APPLICATOR")
    assert r.status_code == 200 and r.json()["product"]["stock_qty"] == 0
    r = use(client, qty=1, pid="CARE-SENS-AIR-APPLICATOR")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert stock(client, "CARE-SENS-AIR-APPLICATOR") == 0
    r = use(client, qty=16, pid="HICARDI-PATCH")
    assert r.status_code == 409 and stock(client, "HICARDI-PATCH") == 15


def test_operation_status_lets_client_recover_after_network_error(client):
    key = "net-drop-key-77"
    assert client.get(f"/api/v1/inventory/operations/{key}").json()["applied"] is False
    use(client, key=key)
    status = client.get(f"/api/v1/inventory/operations/{key}").json()
    assert status["applied"] is True and status["product"]["stock_qty"] == 19


def test_auth_required(client):
    r = client.get("/api/v1/inventory/products", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"
    r = client.post("/api/v1/inventory/use", headers={"Authorization": ""},
                    json={"product_id": SENSOR, "idempotency_key": "x" * 10, "confirmed": True})
    assert r.status_code == 401
    assert stock(client) == 20
    assert client.get("/health").status_code == 200


def test_unknown_product_and_validation_errors(client):
    r = use(client, pid="NOPE")
    assert r.status_code == 404 and r.json()["error"]["code"] == "PRODUCT_NOT_FOUND"
    r = client.post("/api/v1/inventory/use", json={"product_id": SENSOR, "idempotency_key": "short", "confirmed": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_resolve_code_exact_only(client):
    ok = client.post("/api/v1/inventory/resolve-code", json={"code": "CARE-SENS-AIR-SENSOR"}).json()
    assert ok["status"] == "matched" and ok["product"]["product_id"] == SENSOR
    bc = client.post("/api/v1/inventory/resolve-code", json={"code": "0880000000003", "code_type": "barcode"}).json()
    assert bc["product"]["product_id"] == "HICARDI-PATCH"
    bad = client.post("/api/v1/inventory/resolve-code", json={"code": "(01)08800000000019(17)271231(10)LOTX"}).json()
    assert bad["status"] == "unrecognized" and bad["product"] is None


def test_concurrent_requests_same_key_apply_once(settings, conn):
    """Threads hammering the service with one key: exactly one decrement."""
    results = []

    def worker():
        c = connect(settings.database_path)
        try:
            results.append(inv.use_stock(c, product_id=SENSOR, quantity=1, idempotency_key="race-key-123",
                                         confirmed=True)["replayed"])
        finally:
            c.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [False] + [True] * 7
    assert inv.get_product(conn, SENSOR)["stock_qty"] == 19


def test_concurrent_distinct_keys_never_negative(settings, conn):
    """15 patches, 25 concurrent single-unit uses with distinct keys -> stock 0, 10 rejections."""
    outcomes = []

    def worker(i):
        c = connect(settings.database_path)
        try:
            inv.use_stock(c, product_id="HICARDI-PATCH", quantity=1, idempotency_key=f"k-{i:04d}-abcd", confirmed=True)
            outcomes.append("ok")
        except Exception as exc:  # ApiError INSUFFICIENT_STOCK
            outcomes.append(getattr(exc, "code", type(exc).__name__))
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert outcomes.count("ok") == 15 and outcomes.count("INSUFFICIENT_STOCK") == 10
    assert inv.get_product(conn, "HICARDI-PATCH")["stock_qty"] == 0


def test_parse_command_never_writes(client):
    r = client.post("/api/v1/inventory/parse-command", json={"text": "케어센스 센서 한 개 사용"}).json()
    assert r["intent"] == "use" and r["quantity"] == 1 and r["product"]["product_id"] == SENSOR
    assert r["requires_confirmation"] is True
    assert stock(client) == 20
    q = client.post("/api/v1/inventory/parse-command", json={"text": "케어센스 센서 재고 알려줘"}).json()
    assert q["intent"] == "query_stock" and q["product"]["product_id"] == SENSOR
    assert client.post("/api/v1/inventory/parse-command", json={"text": "사용 확인"}).json()["intent"] == "confirm"
    assert client.post("/api/v1/inventory/parse-command", json={"text": "취소"}).json()["intent"] == "cancel"
    two = client.post("/api/v1/inventory/parse-command", json={"text": "하이카디 패치 두 개 사용"}).json()
    assert two["quantity"] == 2 and two["product"]["product_id"] == "HICARDI-PATCH"
    en = client.post("/api/v1/inventory/parse-command", json={"text": "use one CareSens Air Applicator"}).json()
    assert en["intent"] == "use" and en["product"]["product_id"] == "CARE-SENS-AIR-APPLICATOR"
