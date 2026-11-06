"""FastAPI application factory.

Run (PowerShell, repo root):
    python -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
OpenAPI docs: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import errors
from .config import Settings, load_settings
from .db import connect, init_db, utcnow
from .errors import ApiError

log = logging.getLogger("poc")

APP_VERSION = "0.1.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        poller = None
        if settings.inventory_xlsx_path is not None:
            from .services import excel_sync

            c = connect(settings.database_path)
            try:  # export changes left pending by a crash / merge edits made while the server was down
                excel_sync.sync_once(c, settings.inventory_xlsx_path, apply=settings.inventory_xlsx_auto_apply,
                                     policy=settings.inventory_xlsx_merge_policy)
            except Exception:
                log.exception("initial Excel sync failed")
            finally:
                c.close()
            if settings.inventory_xlsx_poll_seconds > 0:
                poller = excel_sync.Poller(settings, connect)
                poller.start()
                app_.state.excel_notify = poller.notify
        try:
            yield
        finally:
            if poller is not None:
                poller.stop()

    app = FastAPI(
        lifespan=lifespan,
        title="Rokid AI Glasses Dual PoC API",
        version=APP_VERSION,
        description="Task 1 inventory (persistent, idempotent stock use) and Task 2 before/after meal photo analysis. "
        "All /api/v1 endpoints require `Authorization: Bearer <API_TOKEN>`. Meal results are estimates for a "
        "technical PoC, not a clinical dietary assessment.",
    )
    app.state.settings = settings
    app.state.excel_notify = lambda: None

    conn = connect(settings.database_path)
    try:
        init_db(conn)
        from .services.nutrition_lookup import ensure_seeded

        ensure_seeded(conn, settings.nutrition_csvs)
    finally:
        conn.close()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content=exc.to_body())

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError):
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {
            "code": errors.VALIDATION_ERROR, "message": "Request validation failed", "details": {"errors": details}}})

    @app.middleware("http")
    async def _access_log(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = (time.perf_counter() - start) * 1000
        # Path + status only: never bodies, tokens or photo bytes.
        try:
            c = connect(settings.database_path)
            try:
                c.execute("INSERT INTO api_logs(created_at, method, path, status, duration_ms) VALUES (?,?,?,?,?)",
                          (utcnow(), request.method, request.url.path[:200], response.status_code, round(duration, 2)))
            finally:
                c.close()
        except Exception:  # logging must never break a request
            log.exception("api_logs insert failed")
        return response

    @app.get("/health", tags=["ops"])
    def health():
        c = connect(settings.database_path)
        try:
            products = c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        finally:
            c.close()
        return {"status": "ok", "version": APP_VERSION, "database": settings.database_path.name,
                "products": products, "time": utcnow()}

    from .routers import inventory

    from .routers import admin, meal_logs, meals, nutrition

    app.include_router(inventory.router)
    app.include_router(meals.router)
    app.include_router(meal_logs.router)
    app.include_router(nutrition.router)
    app.include_router(admin.router)
    return app
