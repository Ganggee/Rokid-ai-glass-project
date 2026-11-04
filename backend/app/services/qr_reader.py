"""QR / 1D barcode decoding with OpenCV only (no extra native dependency).

This is a separate capability from OCR / visual recognition. It returns the raw
decoded strings; mapping to products is done by an exact lookup elsewhere.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def _decode(image_bytes: bytes) -> np.ndarray | None:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _variants(img: np.ndarray):
    """Original, downscaled (QR detector struggles with 4K photos) and contrast-boosted gray."""
    yield img
    h, w = img.shape[:2]
    longest = max(h, w)
    for target in (1600, 1000):
        if longest > target:
            scale = target / longest
            yield cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    yield cv2.cvtColor(cv2.equalizeHist(gray), cv2.COLOR_GRAY2BGR)


def decode_codes(image_bytes: bytes) -> list[dict[str, Any]]:
    img = _decode(image_bytes)
    if img is None:
        return []
    found: dict[tuple[str, str], dict[str, Any]] = {}
    qr = cv2.QRCodeDetector()
    barcode = cv2.barcode.BarcodeDetector() if hasattr(cv2, "barcode") else None
    for variant in _variants(img):
        try:
            ok, values, _points, _ = qr.detectAndDecodeMulti(variant)
            if ok:
                for v in values:
                    if v:
                        found.setdefault(("qr", v), {"format": "qr_code", "code_type": "qr", "raw_value": v})
        except cv2.error:
            pass
        if barcode is not None:
            try:
                result = barcode.detectAndDecodeWithType(variant)
                ok, infos, types = result[0], result[1], result[2]
                if ok:
                    for v, t in zip(infos, types):
                        if v:
                            found.setdefault(("barcode", v), {"format": str(t).lower(), "code_type": "barcode", "raw_value": v})
            except (cv2.error, AttributeError, IndexError):
                pass
        if found:
            break
    return list(found.values())
