from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample-data"


@pytest.fixture(scope="session", autouse=True)
def quiet_http_logs() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        upload_dir=tmp_path / "uploads",
        sample_data_dir=SAMPLE_DATA_DIR,
        mock_delay_seconds=0,
        max_audio_mb=20,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
