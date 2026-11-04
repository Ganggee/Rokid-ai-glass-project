"""Image intake shared by inventory (QR/OCR) and meal photos.

Accepted request bodies (the AIUI client can use whichever its runtime supports):
1. multipart/form-data with a ``file`` field (fetch + FormData, documented in AIUI Web APIs)
2. raw body with ``Content-Type: image/jpeg|png|webp`` (ArrayBuffer body)
3. JSON ``{"image_base64": "...", "mime_type": "image/webp"}`` (wx.arrayBufferToBase64 + JSON)

The bytes are verified by decoding with Pillow (magic-byte check, not the
client's Content-Type). EXIF/GPS metadata is dropped on re-encode.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
from dataclasses import dataclass

from fastapi import Request
from PIL import Image, ImageOps, UnidentifiedImageError

from .. import errors
from ..errors import ApiError

ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
MAX_PIXELS = 40_000_000  # decompression-bomb guard


@dataclass
class IncomingImage:
    raw: bytes
    mime_type: str
    width: int
    height: int
    sha256: str

    def to_clean_jpeg(self, quality: int = 92) -> bytes:
        """Re-encode without metadata, applying EXIF orientation."""
        with Image.open(io.BytesIO(self.raw)) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=quality)
            return out.getvalue()


def validate_image_bytes(data: bytes, max_bytes: int) -> IncomingImage:
    if not data:
        raise ApiError(422, errors.VALIDATION_ERROR, "Empty image body")
    if len(data) > max_bytes:
        raise ApiError(413, errors.PAYLOAD_TOO_LARGE, f"Image exceeds {max_bytes // (1024 * 1024)} MB limit")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ApiError(415, errors.UNSUPPORTED_MEDIA_TYPE, f"Not a decodable JPEG/PNG/WEBP image: {type(exc).__name__}")
    if fmt not in ALLOWED_FORMATS:
        raise ApiError(415, errors.UNSUPPORTED_MEDIA_TYPE, f"Unsupported image format {fmt}; use JPEG, PNG or WEBP")
    return IncomingImage(raw=data, mime_type=ALLOWED_FORMATS[fmt], width=width, height=height,
                         sha256=hashlib.sha256(data).hexdigest())


async def read_image_from_request(request: Request, max_bytes: int) -> IncomingImage:
    ctype = (request.headers.get("content-type") or "").lower()
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes * 1.4 + 4096:
        raise ApiError(413, errors.PAYLOAD_TOO_LARGE, "Request body too large")
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise ApiError(422, errors.VALIDATION_ERROR, "multipart body needs a 'file' field")
        data = await upload.read()
        return validate_image_bytes(data, max_bytes)
    if ctype.startswith("application/json"):
        try:
            payload = json.loads(await request.body())
            data = base64.b64decode(payload["image_base64"], validate=True)
        except (ValueError, KeyError, TypeError, binascii.Error):
            raise ApiError(422, errors.VALIDATION_ERROR, "JSON body needs a valid base64 'image_base64'")
        return validate_image_bytes(data, max_bytes)
    if ctype.startswith("image/") or ctype.startswith("application/octet-stream"):
        return validate_image_bytes(await request.body(), max_bytes)
    raise ApiError(415, errors.UNSUPPORTED_MEDIA_TYPE,
                   "Send multipart/form-data (file), image/* raw bytes, or JSON {image_base64}")
