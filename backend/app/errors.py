"""Uniform JSON error schema: {"error": {"code", "message", "details"}}."""
from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}

    def to_body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


# Stable error codes (also documented in docs/api.md)
UNAUTHORIZED = "UNAUTHORIZED"
VALIDATION_ERROR = "VALIDATION_ERROR"
NOT_FOUND = "NOT_FOUND"
PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
IMPORT_HAS_ERRORS = "IMPORT_HAS_ERRORS"
IMPORT_ALREADY_COMMITTED = "IMPORT_ALREADY_COMMITTED"
UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
BEFORE_PHOTO_REQUIRED = "BEFORE_PHOTO_REQUIRED"
PHOTOS_REQUIRED = "PHOTOS_REQUIRED"
ANALYSIS_NOT_FOUND = "ANALYSIS_NOT_FOUND"
