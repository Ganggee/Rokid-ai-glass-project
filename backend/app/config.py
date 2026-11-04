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
    nutrition_csv: Path = field(default_factory=lambda: REPO_ROOT / "sample-data" / "nutrition_demo.csv")
    mfds_api_key: str = ""
    mfds_base_url: str = "https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo03"
    mfds_operation: str = "getFoodNtrCpntDbInq03"
    ocr_enabled: bool = True
    ocr_lang: str = "eng"
    food_model_plugin: str = "none"


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
        nutrition_csv=_resolve(env.get("NUTRITION_CSV", "sample-data/nutrition_demo.csv")),
        mfds_api_key=env.get("MFDS_API_KEY", ""),
        mfds_base_url=env.get("MFDS_BASE_URL", "https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo03"),
        mfds_operation=env.get("MFDS_OPERATION", "getFoodNtrCpntDbInq03"),
        ocr_enabled=_bool(env.get("OCR_ENABLED"), True),
        ocr_lang=env.get("OCR_LANG", "eng"),
        food_model_plugin=env.get("FOOD_MODEL_PLUGIN", "none").strip().lower() or "none",
    )
    values.update(overrides)
    for key in ("database_path", "upload_dir", "nutrition_csv"):
        if isinstance(values[key], str):
            values[key] = _resolve(values[key])
    settings = Settings(**values)
    if not settings.api_token:
        raise RuntimeError(
            "API_TOKEN is not set. Copy .env.example to .env and set a long random API_TOKEN; "
            "write APIs are never served without authentication."
        )
    return settings
