"""Meal diary API (voice/manual/analysis logs, view, summary for TTS)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from .. import errors
from ..config import Settings
from ..deps import get_conn, get_settings, require_token
from ..errors import ApiError
from ..schemas import ErrorResponse
from ..services import meal_diary
from ..services.diary_parser import get_tz

router = APIRouter(prefix="/api/v1/meal-logs", tags=["meal-logs"], dependencies=[Depends(require_token)],
                   responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})

MealType = Literal["breakfast", "lunch", "dinner", "snack"]


class ParseIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    now: Optional[datetime] = Field(default=None, description="testing only: override the server clock (timezone-aware)")


class LogItemIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    food_name: str = Field(min_length=1, max_length=80)
    spoken_text: Optional[str] = Field(default=None, max_length=120)
    nutrition_ref_id: Optional[str] = None
    quantity: Optional[float] = Field(default=None, gt=0, le=50)
    unit: Optional[str] = Field(default=None, max_length=10)
    grams: Optional[float] = Field(default=None, gt=0, le=5000)


class LogIn(BaseModel):
    log_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    meal_type: MealType
    items: list[LogItemIn] = Field(min_length=1, max_length=15)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:\-]+$")
    confirmed: bool
    source: Literal["voice", "manual"] = "voice"
    utterance: Optional[str] = Field(default=None, max_length=300)


class FromSessionIn(BaseModel):
    meal_type: MealType
    log_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    confirmed: bool


def _now(settings: Settings) -> datetime:
    return datetime.now(get_tz(settings.app_timezone))


@router.post("/parse-command")
def parse_command(body: ParseIn, settings: Settings = Depends(get_settings), conn=Depends(get_conn)):
    """Text -> structured diary command with a nutrition preview. Never writes."""
    now = body.now.astimezone(get_tz(settings.app_timezone)) if body.now else _now(settings)
    return meal_diary.parse_command(conn, body.text, now)


@router.post("")
def create(body: LogIn, settings: Settings = Depends(get_settings), conn=Depends(get_conn)):
    """Save a confirmed log. Nutrition is recomputed on the server and stored as a snapshot."""
    return meal_diary.create_log(conn, log_date=body.log_date, meal_type=body.meal_type,
                                 items=[i.model_dump() for i in body.items], idempotency_key=body.idempotency_key,
                                 confirmed=body.confirmed, today=_now(settings).date(), source=body.source,
                                 utterance=body.utterance)


@router.post("/from-session/{session_id}")
def from_session(session_id: str, body: FromSessionIn, settings: Settings = Depends(get_settings), conn=Depends(get_conn)):
    """Log the latest analysis of a meal session (idempotent per analysis)."""
    today = _now(settings).date()
    return meal_diary.from_session(conn, session_id, meal_type=body.meal_type, log_date=body.log_date or today.isoformat(),
                                   confirmed=body.confirmed, today=today)


def _date(d: Optional[str], settings: Settings) -> str:
    if d is None:
        return _now(settings).date().isoformat()
    try:
        return date.fromisoformat(d).isoformat()
    except ValueError:
        raise ApiError(422, errors.VALIDATION_ERROR, "date must be YYYY-MM-DD")


@router.get("")
def list_logs(date: Optional[str] = Query(default=None), meal_type: Optional[MealType] = None,
              settings: Settings = Depends(get_settings), conn=Depends(get_conn)):
    d = _date(date, settings)
    return {"date": d, "items": meal_diary.list_logs(conn, d, meal_type)}


@router.get("/summary")
def summary(date: Optional[str] = Query(default=None), meal_type: Optional[MealType] = None,
            settings: Settings = Depends(get_settings), conn=Depends(get_conn)):
    """Daily (or per-meal) totals plus `speech_text` (<=150 chars, <=3 sentences) for speechSynthesis."""
    return meal_diary.summary(conn, _date(date, settings), meal_type)


@router.get("/{log_id}")
def get_log(log_id: str, conn=Depends(get_conn)):
    return meal_diary.get_log(conn, log_id)


@router.delete("/{log_id}")
def delete(log_id: str, confirmed: bool = Query(default=False), conn=Depends(get_conn)):
    """Soft delete (deleted_at). Requires confirmed=true. Not available by voice."""
    return meal_diary.delete_log(conn, log_id, confirmed)
