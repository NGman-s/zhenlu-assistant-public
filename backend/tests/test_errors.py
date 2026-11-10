from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TINY_WAV = b"RIFF\x00\x00\x00\x00WAVEfmt "


def create_session(client: TestClient) -> str:
    response = client.post("/api/sessions", json={"patient_name": "错误场景患者"})
    assert response.status_code == 201
    return response.json()["id"]


def test_validation_and_not_found_errors(client: TestClient) -> None:
    response = client.get("/api/sessions/not-a-real-session")
    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"

    response = client.post("/api/sessions", json={"patient_name": "   "})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"

    response = client.get("/api/demo/cases/not-a-case/audio")
    assert response.status_code == 404
    assert response.json()["code"] == "http_error"


def test_processing_order_errors(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(f"/api/sessions/{session_id}/transcript")
    assert response.status_code == 409
    assert response.json()["code"] == "audio_required"

    response = client.post(f"/api/sessions/{session_id}/draft")
    assert response.status_code == 409
    assert response.json()["code"] == "transcript_required"

    response = client.post(
        f"/api/sessions/{session_id}/confirm", json={"expected_revision": 0}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "draft_required"

    response = client.get(f"/api/sessions/{session_id}/record/text")
    assert response.status_code == 404
    assert response.json()["code"] == "record_not_confirmed"

    response = client.post(f"/api/sessions/{session_id}/draft")
    assert response.status_code == 409


def test_upload_validation_and_duplicate_audio(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/api/sessions/{session_id}/audio",
        files={"file": ("notes.txt", b"not audio", "text/plain")},
    )
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_audio_format"
    assert "支持" in response.json()["message"]

    still_waiting = client.get(f"/api/sessions/{session_id}").json()
    assert still_waiting["status"] == "awaiting_audio"

    response = client.post(
        f"/api/sessions/{session_id}/audio",
        files={"file": ("empty.wav", b"", "audio/wav")},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "empty_audio"

    response = client.post(
        f"/api/sessions/{session_id}/audio",
        files={"file": ("../../path-name.wav", TINY_WAV, "audio/wav")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["audio"]["filename"] == "path-name.wav"

    response = client.post(
        f"/api/sessions/{session_id}/audio",
        files={"file": ("second.wav", TINY_WAV, "audio/wav")},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "audio_exists"

    response = client.post(f"/api/sessions/{session_id}/transcript")
    assert response.status_code == 200
    response = client.post(f"/api/sessions/{session_id}/transcript")
    assert response.status_code == 409
    assert response.json()["code"] == "transcript_exists"

    response = client.post(f"/api/sessions/{session_id}/draft")
    assert response.status_code == 200
    response = client.post(f"/api/sessions/{session_id}/draft")
    assert response.status_code == 409
    assert response.json()["code"] == "draft_exists"

    response = client.post(
        f"/api/sessions/{session_id}/draft/regenerate",
        json={"expected_revision": 99},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "revision_conflict"

    response = client.post(
        f"/api/sessions/{session_id}/confirm", json={"expected_revision": 99}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "revision_conflict"

    response = client.get(f"/api/sessions/{session_id}/audio")
    assert response.status_code == 200
    assert response.content == TINY_WAV


def test_oversized_audio_is_rejected(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'large.db').as_posix()}",
        upload_dir=tmp_path / "uploads",
        max_audio_mb=0,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        session_id = create_session(client)
        response = client.post(
            f"/api/sessions/{session_id}/audio",
            files={"file": ("too-large.wav", TINY_WAV, "audio/wav")},
        )
        assert response.status_code == 413
        assert response.json()["code"] == "audio_too_large"
        assert "0 MB" in response.json()["message"]


@pytest.mark.parametrize("provider", ["asr_provider", "draft_provider", "assistant_provider"])
def test_runtime_rejects_removed_mock_providers(provider: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{provider: "mock"})


def test_default_provider_factories_build_cloud_services() -> None:
    from app.providers.registry import build_asr_provider, build_draft_provider
    from app.providers.assistant import build_assistant_provider

    settings = Settings(
        _env_file=None,
        qwen_base_url="https://example.test/v1",
        qwen_api_key="test-key",
        fun_asr_api_key="test-key",
    )
    assert build_asr_provider(settings).name.startswith("fun-asr:")
    assert build_draft_provider(settings).name.startswith("qwen:")
    assert build_assistant_provider(settings).name.startswith("qwen-assistant:")
