"""Meal before/after photo analysis API (Task 2)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import FileResponse

from ..config import Settings
from ..deps import get_conn, get_settings, require_token
from ..schemas import AnalyzeRequest, ErrorResponse, MealItemsRequest
from ..services import meal_comparison as meals
from ..services.image_io import read_image_from_request

router = APIRouter(prefix="/api/v1/meals", tags=["meals"], dependencies=[Depends(require_token)],
                   responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})

_IMAGE_BODY = {"requestBody": {"content": {
    "multipart/form-data": {"schema": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}},
    "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
    "application/json": {"schema": {"type": "object", "properties": {"image_base64": {"type": "string"},
                                                                       "mime_type": {"type": "string"}}}},
}}}


@router.post("/sessions", status_code=201)
def create_session(note: Optional[str] = Body(default=None, embed=True, max_length=200), conn=Depends(get_conn)):
    return meals.create_session(conn, note)


@router.get("/sessions")
def list_sessions(limit: int = Query(20, ge=1, le=100), conn=Depends(get_conn)):
    return {"items": meals.list_sessions(conn, limit)}


@router.post("/{session_id}/photos/before", openapi_extra=_IMAGE_BODY)
async def upload_before(session_id: str, request: Request, settings: Settings = Depends(get_settings), conn=Depends(get_conn)):
    """Store the before-meal photo (re-encoded JPEG, metadata stripped). Returns unlabelled candidate regions
    and the label options from the nutrition reference table."""
    image = await read_image_from_request(request, settings.max_upload_bytes)
    return meals.save_photo(conn, settings.upload_dir, session_id, "before", image)


@router.post("/{session_id}/photos/after", openapi_extra=_IMAGE_BODY)
async def upload_after(session_id: str, request: Request, settings: Settings = Depends(get_settings), conn=Depends(get_conn)):
    image = await read_image_from_request(request, settings.max_upload_bytes)
    return meals.save_photo(conn, settings.upload_dir, session_id, "after", image)


@router.get("/{session_id}/photos/{kind}", response_class=FileResponse)
def get_photo(session_id: str, kind: str, settings: Settings = Depends(get_settings), conn=Depends(get_conn)):
    if kind not in ("before", "after"):
        from ..errors import ApiError

        raise ApiError(404, "NOT_FOUND", "kind must be before or after")
    return FileResponse(meals.photo_path(conn, settings.upload_dir, session_id, kind), media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})


@router.get("/{session_id}")
def get_session(session_id: str, conn=Depends(get_conn)):
    return meals.get_session(conn, session_id)


@router.post("/{session_id}/items")
def set_items(session_id: str, body: MealItemsRequest, conn=Depends(get_conn)):
    """Confirm food labels, optional initial serving grams and regions (replaces the item list)."""
    items = meals.set_items(conn, session_id, [i.model_dump(exclude_none=True) for i in body.items])
    return {"session_id": session_id, "items": items}


@router.post("/{session_id}/analyze")
def analyze(session_id: str, body: AnalyzeRequest = Body(default=AnalyzeRequest()),
            settings: Settings = Depends(get_settings), conn=Depends(get_conn)):
    """Compare before/after photos per food. Ratios are estimates; grams/nutrients only with an initial serving."""
    return meals.analyze(conn, settings.upload_dir, session_id, body.method, settings.food_model_plugin)


@router.get("/{session_id}/results")
def results(session_id: str, conn=Depends(get_conn)):
    return meals.latest_result(conn, session_id)


@router.delete("/{session_id}")
def delete(session_id: str, settings: Settings = Depends(get_settings), conn=Depends(get_conn)):
    """Delete the session, its items, analyses and stored photos."""
    return meals.delete_session(conn, settings.upload_dir, session_id)
