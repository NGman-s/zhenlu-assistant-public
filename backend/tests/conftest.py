from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.support.demo_data import DemoCatalog
from tests.support.asr import MockTranscriptionProvider
from tests.support.draft import MockDraftProvider
from tests.support.assistant import MockAssistantProvider

SAMPLE_DATA_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def quiet_http_logs() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)


@pytest.fixture(autouse=True)
def test_providers(monkeypatch):
    catalog = DemoCatalog(SAMPLE_DATA_DIR)
    monkeypatch.setattr("app.main.build_asr_provider", lambda settings: MockTranscriptionProvider(catalog))
    monkeypatch.setattr("app.main.build_draft_provider", lambda settings: MockDraftProvider(catalog))
    monkeypatch.setattr("app.main.build_assistant_provider", lambda settings: MockAssistantProvider())


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        upload_dir=tmp_path / "uploads",
        max_audio_mb=20,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
