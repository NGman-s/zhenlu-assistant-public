from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.device_state import read_device_state
from app.main import create_app


def write_state(path: Path, connected: bool, heartbeat: float | None = None) -> None:
    path.write_text(json.dumps({"connected": connected, "mode": "identity-prototype", "heartbeat": heartbeat if heartbeat is not None else time.time()}), encoding="utf-8")


def test_device_state_fails_closed_when_missing_stale_or_invalid(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    assert read_device_state(None)["managed"] is False
    assert read_device_state(path)["connected"] is False
    write_state(path, True, time.time() - 60)
    assert read_device_state(path)["connected"] is False
    path.write_text("invalid", encoding="utf-8")
    assert read_device_state(path)["connected"] is False
    write_state(path, True)
    assert read_device_state(path)["connected"] is True


def test_disconnect_blocks_new_actions_but_allows_saving_edits(settings: Settings, tmp_path: Path) -> None:
    state = tmp_path / "device.json"
    settings.device_state_file = state
    write_state(state, True)
    app = create_app(settings)
    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"patient_name": "虚构患者"}).json()
        sid = session["id"]
        audio = Path(__file__).resolve().parent / "fixtures" / "mock-consultation-case-01.wav"
        with audio.open("rb") as handle:
            assert client.post(f"/api/sessions/{sid}/audio", files={"file": (audio.name, handle, "audio/wav")}).status_code == 201
        assert client.post(f"/api/sessions/{sid}/transcript/manual", json={"text": "测试问诊"}).status_code == 200
        draft = client.post(f"/api/sessions/{sid}/draft").json()["draft"]
        write_state(state, False)
        assert client.get("/api/device/status").json()["connected"] is False
        assert client.post("/api/sessions", json={"patient_name": "另一个"}).status_code == 423
        assert client.post(f"/api/sessions/{sid}/confirm", json={"expected_revision": draft["revision"]}).status_code == 423
        saved = client.patch(f"/api/sessions/{sid}/draft", json={"expected_revision": draft["revision"], "fields": [{"field_key": "chief_complaint", "value": "测试内容"}]})
        assert saved.status_code == 200
        write_state(state, True)
        assert client.post(f"/api/sessions/{sid}/confirm", json={"expected_revision": saved.json()["draft"]["revision"]}).status_code == 200
