"""Inventory API (Task 1)."""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from .. import errors
from ..config import Settings
from ..deps import get_conn, get_settings, require_token
from ..errors import ApiError
from ..schemas import (
    ErrorResponse, ImportCommitRequest, ImportPreview, OperationStatus, ParseCommandRequest, ParsedCommand,
    Product, ProductList, ResolveCodeRequest, ResolveResult, TransactionList, UseRequest, UseResponse,
)
from ..services import image_recognition, inventory_service as inv
from ..services.image_io import read_image_from_request

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"], dependencies=[Depends(require_token)],
                   responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})


@router.get("/products", response_model=ProductList)
def list_products(query: Optional[str] = Query(default=None, max_length=100), limit: int = Query(50, ge=1, le=200),
                  conn=Depends(get_conn)):
    items = inv.search_products(conn, query, limit)
    return {"items": items, "count": len(items)}


@router.get("/products/{product_id}", response_model=Product, responses={404: {"model": ErrorResponse}})
def get_product(product_id: str, conn=Depends(get_conn)):
    return inv.get_product(conn, product_id)


@router.post("/use", response_model=UseResponse,
             responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
def use(body: UseRequest, conn=Depends(get_conn)):
    """Decrement stock after explicit user confirmation. Idempotent per `idempotency_key`:
    resending the same key returns the original result with `replayed: true`."""
    return inv.use_stock(conn, product_id=body.product_id, quantity=body.quantity,
                         idempotency_key=body.idempotency_key, confirmed=body.confirmed,
                         client_timestamp=body.client_timestamp, source=body.source, note=body.note)


@router.get("/operations/{idempotency_key}", response_model=OperationStatus)
def operation(idempotency_key: str, conn=Depends(get_conn)):
    """Check whether a /use request with this key was applied (use after a network error
    instead of blindly re-sending)."""
    return inv.operation_status(conn, idempotency_key)


@router.get("/transactions", response_model=TransactionList)
def transactions(product_id: Optional[str] = None, limit: int = Query(50, ge=1, le=500), conn=Depends(get_conn)):
    items = inv.list_transactions(conn, product_id, limit)
    return {"items": items, "count": len(items)}


@router.post("/resolve-code", response_model=ResolveResult)
def resolve_code(body: ResolveCodeRequest, conn=Depends(get_conn)):
    result = inv.resolve_code(conn, body.code, body.code_type)
    inv.record_recognition(conn, "code_lookup", result["status"] if result["status"] == "matched" else "none")
    return result


@router.post("/resolve-image", response_model=ResolveResult,
             openapi_extra={"requestBody": {"content": {
                 "multipart/form-data": {"schema": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}},
                 "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
                 "application/json": {"schema": {"type": "object", "properties": {"image_base64": {"type": "string"}}}},
             }}})
async def resolve_image(request: Request, settings: Settings = Depends(get_settings), conn=Depends(get_conn)):
    """Product photo -> QR/barcode match, or OCR-based candidates, or `unrecognized`. Never changes stock."""
    image = await read_image_from_request(request, settings.max_upload_bytes)
    return image_recognition.resolve_image(conn, image.raw, ocr_enabled=settings.ocr_enabled, ocr_lang=settings.ocr_lang)


@router.get("/recognition-stats")
def recognition_stats(conn=Depends(get_conn)):
    return inv.recognition_stats(conn)


@router.post("/parse-command", response_model=ParsedCommand)
def parse_command(body: ParseCommandRequest, conn=Depends(get_conn)):
    """Turn recognized speech or typed text into a structured command. Never writes."""
    return inv.parse_command(conn, body.text)


@router.post("/import/preview", response_model=ImportPreview)
async def import_preview(file: UploadFile = File(...), column_mapping: Optional[str] = Form(default=None),
                         sheet: Optional[str] = Form(default=None),
                         settings: Settings = Depends(get_settings), conn=Depends(get_conn)):
    """Validate a .csv/.xlsx file and store a preview batch. Does not change products or stock."""
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise ApiError(413, errors.PAYLOAD_TOO_LARGE, "File too large")
    mapping = None
    if column_mapping:
        try:
            mapping = json.loads(column_mapping)
            assert isinstance(mapping, dict)
        except (ValueError, AssertionError):
            raise ApiError(422, errors.VALIDATION_ERROR, "column_mapping must be a JSON object {field: header}")
    return inv.preview_import(conn, file.filename or "upload.csv", content, mapping, sheet)


@router.post("/import/commit")
def import_commit(body: ImportCommitRequest, conn=Depends(get_conn)):
    """Apply a previewed batch explicitly. `seed` never overwrites existing stock."""
    return inv.commit_import(conn, body.batch_id, body.mode, body.skip_invalid_rows, source="import_api")
