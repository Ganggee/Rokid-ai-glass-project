"""API E2E: real uvicorn process. 20 -> 19 -> server restart -> 19 (the original bug was a reset to 20)."""
from __future__ import annotations

import requests

from .conftest import AUTH

NOPROXY = {"http": None, "https": None}


def test_stock_survives_server_restart(live_server):
    s = requests.Session()
    s.headers.update(AUTH)
    s.proxies.update(NOPROXY)
    url = live_server.base + "/api/v1/inventory"
    assert s.get(url + "/products/CARE-SENS-AIR-SENSOR").json()["stock_qty"] == 20

    r = s.post(url + "/use", json={"product_id": "CARE-SENS-AIR-SENSOR", "quantity": 1,
                                   "idempotency_key": "restart-test-key", "confirmed": True, "source": "e2e"})
    assert r.status_code == 200 and r.json()["product"]["stock_qty"] == 19

    live_server.stop()
    live_server.start()  # same SQLite file, new process

    assert s.get(url + "/products/CARE-SENS-AIR-SENSOR").json()["stock_qty"] == 19
    # client retry after restart with the same key must not decrement again
    r2 = s.post(url + "/use", json={"product_id": "CARE-SENS-AIR-SENSOR", "quantity": 1,
                                    "idempotency_key": "restart-test-key", "confirmed": True, "source": "e2e"})
    assert r2.status_code == 200 and r2.json()["replayed"] is True
    assert s.get(url + "/products/CARE-SENS-AIR-SENSOR").json()["stock_qty"] == 19
    uses = [t for t in s.get(url + "/transactions").json()["items"] if t["tx_type"] == "use"]
    assert len(uses) == 1
