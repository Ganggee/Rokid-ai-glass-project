"""Product photo -> candidate products.

Order: (1) QR/barcode decode + exact mapping, (2) OCR text (optional, Tesseract)
+ fuzzy match on product names/aliases. Visual appearance alone is not used to
assert identity: without a decodable code the result is at most a candidate
list that the user must confirm, or ``unrecognized``.
"""
from __future__ import annotations

import io
import shutil
import sqlite3
from typing import Any

from . import inventory_service as inv
from .qr_reader import decode_codes


def ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None


def run_ocr(image_bytes: bytes, lang: str = "eng") -> str:
    import pytesseract
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(image_bytes)) as img:
        img = ImageOps.exif_transpose(img).convert("L")
        if max(img.size) > 2000:
            img.thumbnail((2000, 2000))
        return pytesseract.image_to_string(img, lang=lang, timeout=20)


def resolve_image(conn: sqlite3.Connection, image_bytes: bytes, *, ocr_enabled: bool, ocr_lang: str) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    codes = decode_codes(image_bytes)
    for code in codes:
        result = inv.resolve_code(conn, code["raw_value"], code["code_type"])
        evidence.append({"method": code["code_type"], "format": code["format"], "raw_value": code["raw_value"],
                         "mapped": result["status"] == "matched"})
        if result["status"] == "matched":
            inv.record_recognition(conn, code["code_type"], "matched")
            return {**result, "evidence": evidence, "message": "Matched by decoded code. Confirm before using stock."}
    if codes:
        inv.record_recognition(conn, codes[0]["code_type"], "none")
    else:
        inv.record_recognition(conn, "qr", "none")

    if ocr_enabled and ocr_available():
        try:
            text = run_ocr(image_bytes, ocr_lang)
        except Exception as exc:  # OCR is best-effort
            inv.record_recognition(conn, "ocr", "error")
            evidence.append({"method": "ocr", "error": type(exc).__name__})
            text = ""
        clean = " ".join(text.split())
        if clean:
            evidence.append({"method": "ocr", "text_excerpt": clean[:160]})
            candidates = inv.match_products_by_text(conn, clean, limit=3)
            if candidates:
                inv.record_recognition(conn, "ocr", "candidates")
                return {"status": "candidates", "product": None, "candidates": candidates, "evidence": evidence,
                        "message": "OCR text suggests these products. The user must pick one; nothing is applied automatically."}
        inv.record_recognition(conn, "ocr", "none")
    else:
        inv.record_recognition(conn, "ocr", "unavailable")
        evidence.append({"method": "ocr", "status": "unavailable (disabled or Tesseract not installed)"})
    return {"status": "unrecognized", "product": None, "candidates": [], "evidence": evidence,
            "message": "No code or readable label found. Choose the product from the list."}
