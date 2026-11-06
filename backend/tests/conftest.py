from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.config import load_settings  # noqa: E402
from backend.app.db import connect, init_db  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.services import inventory_service as inv  # noqa: E402
from backend.app.services import nutrition_lookup  # noqa: E402

TOKEN = "test-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def seed(db_path: Path) -> None:
    conn = connect(db_path)
    init_db(conn)
    csv_path = ROOT / "sample-data" / "inventory_demo.csv"
    preview = inv.preview_import(conn, csv_path.name, csv_path.read_bytes())
    inv.commit_import(conn, preview["batch_id"], "seed", is_demo=True)
    nutrition_lookup.load_csv(conn, ROOT / "sample-data" / "nutrition_reference_public.csv")
    nutrition_lookup.load_csv(conn, ROOT / "sample-data" / "nutrition_demo.csv")
    conn.close()


@pytest.fixture()
def settings(tmp_path):
    return load_settings(env_file=tmp_path / "none.env", api_token=TOKEN,
                         database_path=tmp_path / "poc.sqlite3", upload_dir=tmp_path / "uploads")


@pytest.fixture()
def client(settings):
    from fastapi.testclient import TestClient

    seed(settings.database_path)
    app = create_app(settings)
    with TestClient(app) as c:
        c.headers.update(AUTH)
        yield c


@pytest.fixture()
def conn(settings):
    seed(settings.database_path)
    c = connect(settings.database_path)
    yield c
    c.close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServer:
    """Real uvicorn process (used for restart-persistence and API E2E tests)."""

    def __init__(self, db_path: Path, upload_dir: Path):
        self.db_path, self.upload_dir = db_path, upload_dir
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        env = {**os.environ, "API_TOKEN": TOKEN, "DATABASE_PATH": str(self.db_path), "INVENTORY_XLSX_PATH": "",
               "NUTRITION_CSV": "sample-data/nutrition_reference_public.csv,sample-data/nutrition_demo.csv",
               "UPLOAD_DIR": str(self.upload_dir), "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.app.main:create_app", "--factory",
             "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning"],
            cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        import requests

        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if requests.get(self.base + "/health", timeout=0.5, proxies={"http": None, "https": None}).ok:
                    return
            except requests.RequestException:
                time.sleep(0.2)
        out = self.proc.stdout.read().decode() if self.proc.poll() is not None else ""
        raise RuntimeError(f"server did not start: {out}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


@pytest.fixture()
def live_server(tmp_path):
    db = tmp_path / "live.sqlite3"
    seed(db)
    server = LiveServer(db, tmp_path / "uploads")
    server.start()
    yield server
    server.stop()
