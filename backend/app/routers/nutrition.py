"""Nutrition reference search (per 100 g)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..config import Settings
from ..deps import get_conn, get_settings, require_token
from ..services import nutrition_lookup
from ..vision.optional_food_model import plugin_status

router = APIRouter(prefix="/api/v1/nutrition", tags=["nutrition"], dependencies=[Depends(require_token)])


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=50), remote: bool = False,
           settings: Settings = Depends(get_settings), conn=Depends(get_conn)):
    """Search the local reference table. With remote=true and MFDS_API_KEY configured, also query the
    MFDS 식품영양성분DB OpenAPI and cache results (NOT VERIFIED in this PoC)."""
    local = nutrition_lookup.search_local(conn, q)
    out = {"query": q, "items": local, "remote": None}
    if remote:
        if not settings.mfds_api_key:
            out["remote"] = {"status": "disabled", "reason": "MFDS_API_KEY not configured"}
        else:
            out["remote"] = nutrition_lookup.search_mfds(conn, q, settings.mfds_api_key, settings.mfds_base_url,
                                                         settings.mfds_operation)
    return out


@router.get("/references")
def references(conn=Depends(get_conn)):
    return {"items": nutrition_lookup.list_references(conn)}


@router.get("/capabilities")
def capabilities(settings: Settings = Depends(get_settings)):
    from ..services.image_recognition import ocr_available

    return {"ocr": {"enabled": settings.ocr_enabled, "available": ocr_available(), "lang": settings.ocr_lang},
            "food_model_plugin": plugin_status(settings.food_model_plugin),
            "mfds_api": {"configured": bool(settings.mfds_api_key), "verified": False}}
