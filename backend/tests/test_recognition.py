"""QR/barcode decoding and OCR candidate lookup are separate capabilities."""
from __future__ import annotations

import base64

import cv2
import numpy as np
import pytest

from backend.app.services.image_recognition import ocr_available


def _png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def qr_image(text: str, rotate: bool = False) -> bytes:
    q = cv2.QRCodeEncoder.create().encode(text)
    q = cv2.resize(q, (q.shape[1] * 10, q.shape[0] * 10), interpolation=cv2.INTER_NEAREST)
    q = cv2.copyMakeBorder(q, 60, 60, 60, 60, cv2.BORDER_CONSTANT, value=255)
    if rotate:
        q = cv2.rotate(q, cv2.ROTATE_90_CLOCKWISE)
    return _png(cv2.cvtColor(q, cv2.COLOR_GRAY2BGR))


def label_image(text: str) -> bytes:
    img = np.full((220, 1100, 3), 255, np.uint8)
    cv2.putText(img, text, (30, 130), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 0, 0), 5, cv2.LINE_AA)
    return _png(img)


def test_qr_multipart_matches_product(client):
    r = client.post("/api/v1/inventory/resolve-image", files={"file": ("qr.png", qr_image("HICARDI-PATCH"), "image/png")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "matched" and body["product"]["product_id"] == "HICARDI-PATCH"
    assert body["evidence"][0]["method"] == "qr"


def test_qr_raw_body_and_base64_json(client):
    raw = client.post("/api/v1/inventory/resolve-image", content=qr_image("CARE-SENS-AIR-SENSOR", rotate=True),
                      headers={"Content-Type": "image/png"}).json()
    assert raw["product"]["product_id"] == "CARE-SENS-AIR-SENSOR"
    b64 = client.post("/api/v1/inventory/resolve-image", json={
        "image_base64": base64.b64encode(qr_image("CARE-SENS-AIR-APPLICATOR")).decode(), "mime_type": "image/png"}).json()
    assert b64["product"]["product_id"] == "CARE-SENS-AIR-APPLICATOR"


def test_unmapped_qr_is_not_parsed(client):
    body = client.post("/api/v1/inventory/resolve-image",
                       files={"file": ("qr.png", qr_image("LOT:DEMO-LOT-A;SN:000123"), "image/png")}).json()
    assert body["status"] in ("unrecognized", "candidates")
    assert body["product"] is None
    assert any(e.get("raw_value") == "LOT:DEMO-LOT-A;SN:000123" and e["mapped"] is False for e in body["evidence"])


@pytest.mark.skipif(not ocr_available(), reason="Tesseract not installed")
def test_ocr_gives_candidates_not_a_match(client):
    body = client.post("/api/v1/inventory/resolve-image",
                       files={"file": ("label.png", label_image("HiCardi Patch"), "image/png")}).json()
    assert body["status"] == "candidates"
    assert body["candidates"][0]["product"]["product_id"] == "HICARDI-PATCH"
    assert body["product"] is None  # user must confirm


def test_blank_photo_unrecognized_and_stats_recorded(client):
    blank = _png(np.full((300, 300, 3), 128, np.uint8))
    body = client.post("/api/v1/inventory/resolve-image", files={"file": ("b.png", blank, "image/png")}).json()
    assert body["status"] == "unrecognized"
    stats = client.get("/api/v1/inventory/recognition-stats").json()["by_kind"]
    assert "qr" in stats


def test_rejects_non_images_and_oversize(client, settings):
    r = client.post("/api/v1/inventory/resolve-image", files={"file": ("x.png", b"not an image", "image/png")})
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    big = b"\xff\xd8" + b"0" * (settings.max_upload_bytes + 10)
    r = client.post("/api/v1/inventory/resolve-image", content=big, headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 413
