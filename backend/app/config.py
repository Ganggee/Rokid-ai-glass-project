"""Runtime settings loaded from environment variables (and an optional .env file).

No third-party dotenv dependency: a tiny parser reads KEY=VALUE lines so the
backend runs with the minimal requirements on Windows PowerShell.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file without overriding existing values."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else (REPO_ROOT / path)


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_token: str
    database_path: Path
    upload_dir: Path
    max_upload_bytes: int = 15 * 1024 * 1024
    meal_retention_days: int = 14
    nutrition_csvs: tuple = field(default_factory=lambda: (REPO_ROOT / "sample-data" / "nutrition_reference_public.csv",
                                                           REPO_ROOT / "sample-data" / "nutrition_demo.csv"))
    mfds_api_key: str = ""
    mfds_base_url: str = "https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo03"
    mfds_operation: str = "getFoodNtrCpntDbInq03"
    ocr_enabled: bool = True
    ocr_lang: str = "eng"
    food_model_plugin: str = "none"
    app_timezone: str = "Asia/Seoul"
    inventory_xlsx_path: Path | None = None
    inventory_xlsx_poll_seconds: float = 30.0
    inventory_xlsx_merge_policy: str = "merge_delta"
    inventory_xlsx_auto_apply: bool = True


def load_settings(env_file: Path | None = None, **overrides) -> Settings:
    """Build Settings from the environment. ``overrides`` win (used by tests)."""
    _load_dotenv(env_file or (REPO_ROOT / ".env"))
    env = os.environ
    values = dict(
        api_token=env.get("API_TOKEN", ""),
        database_path=_resolve(env.get("DATABASE_PATH", "data/poc.sqlite3")),
        upload_dir=_resolve(env.get("UPLOAD_DIR", "uploads")),
        max_upload_bytes=int(float(env.get("MAX_UPLOAD_MB", "15")) * 1024 * 1024),
        meal_retention_days=int(env.get("MEAL_RETENTION_DAYS", "14")),
        nutrition_csvs=tuple(_resolve(p.strip()) for p in env.get(
            "NUTRITION_CSV", "sample-data/nutrition_reference_public.csv,sample-data/nutrition_demo.csv").split(",") if p.strip()),
        mfds_api_key=env.get("MFDS_API_KEY", ""),
        mfds_base_url=env.get("MFDS_BASE_URL", "https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo03"),
        mfds_operation=env.get("MFDS_OPERATION", "getFoodNtrCpntDbInq03"),
        ocr_enabled=_bool(env.get("OCR_ENABLED"), True),
        ocr_lang=env.get("OCR_LANG", "eng"),
        food_model_plugin=env.get("FOOD_MODEL_PLUGIN", "none").strip().lower() or "none",
        app_timezone=env.get("APP_TIMEZONE", "Asia/Seoul"),
        inventory_xlsx_path=_resolve(env["INVENTORY_XLSX_PATH"]) if env.get("INVENTORY_XLSX_PATH") else None,
        # unset/empty -> 30 s; "0" only when explicitly configured (= background poller off)
        inventory_xlsx_poll_seconds=float(env.get("INVENTORY_XLSX_POLL_SECONDS", "").strip() or 30),
        inventory_xlsx_merge_policy=env.get("INVENTORY_XLSX_MERGE_POLICY", "merge_delta"),
        inventory_xlsx_auto_apply=_bool(env.get("INVENTORY_XLSX_AUTO_APPLY"), True),
    )
    values.update(overrides)
    for key in ("database_path", "upload_dir"):
        if isinstance(values[key], str):
            values[key] = _resolve(values[key])
    if isinstance(values.get("inventory_xlsx_path"), str):
        values["inventory_xlsx_path"] = _resolve(values["inventory_xlsx_path"])
    if float(values["inventory_xlsx_poll_seconds"]) < 0:
        raise RuntimeError("INVENTORY_XLSX_POLL_SECONDS must be >= 0 (0 = explicitly off)")
    if values["inventory_xlsx_merge_policy"] not in ("merge_delta", "db_wins", "excel_wins"):
        raise RuntimeError("INVENTORY_XLSX_MERGE_POLICY must be merge_delta | db_wins | excel_wins")
    values["nutrition_csvs"] = tuple(_resolve(p) if isinstance(p, str) else p for p in values["nutrition_csvs"])
    settings = Settings(**values)
    if not settings.api_token:
        raise RuntimeError(
            "API_TOKEN is not set. Copy .env.example to .env and set a long random API_TOKEN; "
            "write APIs are never served without authentication."
        )
    return settings
