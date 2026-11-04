"""FastAPI dependencies: settings, per-request SQLite connection, bearer auth."""
from __future__ import annotations

import hmac
from typing import Iterator

from fastapi import Depends, Request

from . import errors
from .config import Settings
from .db import connect
from .errors import ApiError


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_conn(settings: Settings = Depends(get_settings)) -> Iterator:
    conn = connect(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


def require_token(request: Request, settings: Settings = Depends(get_settings)) -> None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token or not hmac.compare_digest(token.strip(), settings.api_token):
        raise ApiError(401, errors.UNAUTHORIZED, "Missing or invalid bearer token")
