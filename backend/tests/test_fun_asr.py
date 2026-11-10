from __future__ import annotations

import io
import json
import queue
import wave
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
import websocket
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.providers.demo_data import DemoCatalog
from app.providers.fun_asr import AsrProviderError, FunAsrProvider
from app.providers.registry import build_asr_provider

MODEL = "fun-asr-realtime-2026-02-28"
PROVIDER_NAME = f"fun-asr:{MODEL}"


def wav_bytes(
    *,
    channels: int = 1,
    sampwidth: int = 2,
    framerate: int = 16000,
    seconds: float = 0.2,
) -> bytes:
    buffer = io.BytesIO()
    frame_count = int(framerate * seconds)
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sampwidth)
        handle.setframerate(framerate)
        handle.writeframes(b"\x00" * frame_count * channels * sampwidth)
    return buffer.getvalue()


def write_wav(path: Path, **kwargs: Any) -> Path:
    path.write_bytes(wav_bytes(**kwargs))
    return path


def result_event(
    text: str,
    *,
    sentence_id: int = 1,
    begin_time: int | None = 170,
    end_time: int | None = 920,
    sentence_end: bool = True,
    heartbeat: bool = False,
    billed_seconds: int | None = 1,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "output": {
            "sentence": {
                "begin_time": begin_time,
                "end_time": end_time,
                "text": text,
                "heartbeat": heartbeat,
                "sentence_end": sentence_end,
                "sentence_id": sentence_id,
            }
        },
        "usage": {"duration": billed_seconds} if sentence_end and billed_seconds is not None else None,
    }
    return {"header": {"event": "result-generated", "task_id": "task"}, "payload": payload}


def finished_event() -> dict[str, Any]:
    return {"header": {"event": "task-finished", "task_id": "task"}, "payload": {}}


def failed_event(code: str = "CLIENT_ERROR", message: str = "secret upstream detail") -> dict[str, Any]:
    return {
        "header": {
            "event": "task-failed",
            "task_id": "task",
            "error_code": code,
            "error_message": message,
        },
        "payload": {},
    }


class FakeConnection:
    def __init__(self, responses: Iterable[dict[str, Any]] = ()) -> None:
        self.responses = list(responses)
        self.incoming: queue.Queue[str] = queue.Queue()
        self.text_messages: list[str] = []
        self.binary_messages: list[bytes] = []
        self.closed = False
        self.receive_timeout: float | None = None

    def send(self, payload: str) -> None:
        self.text_messages.append(payload)
        message = json.loads(payload)
        action = message["header"]["action"]
        task_id = message["header"]["task_id"]
        if action == "run-task":
            self.incoming.put(json.dumps({"header": {"event": "task-started", "task_id": task_id}, "payload": {}}))
        elif action == "finish-task":
            for response in self.responses:
                self.incoming.put(json.dumps(response, ensure_ascii=False))

    def send_binary(self, payload: bytes) -> None:
        self.binary_messages.append(payload)

    def recv(self) -> str:
        try:
            return self.incoming.get(timeout=0.05)
        except queue.Empty:
            raise websocket.WebSocketTimeoutException()

    def settimeout(self, timeout: float) -> None:
        self.receive_timeout = timeout

    def close(self) -> None:
        self.closed = True


def provider_for(connection: FakeConnection, **overrides: Any) -> FunAsrProvider:
    options: dict[str, Any] = {
        "workspace": "test-workspace",
        "timeout": 5.0,
        "sample_rate": 16000,
        "language_hints": ("zh",),
        "chunk_interval": 0.0,
        "connection_factory": lambda url, headers, timeout: connection,
    }
    options.update(overrides)
    return FunAsrProvider("wss://example.test/api-ws/v1/inference", MODEL, "test-secret", **options)


def test_registry_selects_fun_asr() -> None:
    sample_data = Path(__file__).resolve().parents[2] / "sample-data"
    settings = Settings(
        _env_file=None,
        asr_provider="fun-asr",
        fun_asr_base_url="wss://example.test",
        fun_asr_model=MODEL,
        fun_asr_api_key=SecretStr("test-secret"),
    )

    provider = build_asr_provider(settings, DemoCatalog(sample_data))

    assert provider.name == PROVIDER_NAME
    assert provider.is_mock is False


def test_fun_asr_streams_audio_and_keeps_final_sentences(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "consultation.wav")
    connection = FakeConnection([
        result_event("", sentence_id=1, sentence_end=False),
        result_event("好", sentence_id=1, sentence_end=False),
        result_event("", sentence_id=1, heartbeat=True),
        result_event("好，我知道了", sentence_id=1, begin_time=170, end_time=920),
        result_event("咳嗽三天", sentence_id=2, begin_time=1000, end_time=2500, billed_seconds=2),
        finished_event(),
    ])

    result = provider_for(connection).transcribe(audio, "consultation.wav")

    assert result.provider == PROVIDER_NAME
    assert result.is_mock is False
    assert result.language == "zh-CN"
    assert [(segment.text, segment.speaker, segment.start_ms, segment.end_ms) for segment in result.segments] == [
        ("好，我知道了", "未知", 170, 920),
        ("咳嗽三天", "未知", 1000, 2500),
    ]
    assert result.metadata["billed_duration_seconds"] == 3
    assert "真实语音识别结果" in result.notice
    assert "test-secret" not in result.notice

    run_task = json.loads(connection.text_messages[0])
    assert run_task["header"]["action"] == "run-task"
    assert run_task["header"]["streaming"] == "duplex"
    assert run_task["payload"]["task_group"] == "audio"
    assert run_task["payload"]["task"] == "asr"
    assert run_task["payload"]["function"] == "recognition"
    assert run_task["payload"]["model"] == MODEL
    assert run_task["payload"]["parameters"] == {
        "format": "wav",
        "sample_rate": 16000,
        "language_hints": ["zh"],
    }
    assert run_task["payload"]["input"] == {}

    finish_task = json.loads(connection.text_messages[-1])
    assert finish_task["header"]["action"] == "finish-task"
    assert finish_task["header"]["task_id"] == run_task["header"]["task_id"]
    assert finish_task["payload"] == {"input": {}}
    assert len(connection.binary_messages) == 3
    assert sum(len(chunk) for chunk in connection.binary_messages) == len(audio.read_bytes())
    assert connection.closed is True


def test_fun_asr_task_failure_does_not_leak_upstream_message(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "consultation.wav")
    connection = FakeConnection([failed_event()])

    with pytest.raises(AsrProviderError) as error:
        provider_for(connection).transcribe(audio, "consultation.wav")

    assert error.value.code == "fun_asr_failed"
    assert "CLIENT_ERROR" in error.value.message
    assert "secret upstream detail" not in error.value.message
    assert connection.closed is True


def test_fun_asr_empty_final_result_is_reported(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "consultation.wav")
    connection = FakeConnection([result_event("中间结果", sentence_end=False), finished_event()])

    with pytest.raises(AsrProviderError) as error:
        provider_for(connection).transcribe(audio, "consultation.wav")

    assert error.value.code == "fun_asr_empty_result"


@pytest.mark.parametrize(
    ("suffix", "wav_options", "expected_code"),
    [
        (".flac", {}, "fun_asr_unsupported_format"),
        (".ogg", {}, "fun_asr_unsupported_format"),
        (".wav", {"channels": 2}, "fun_asr_invalid_audio"),
        (".wav", {"sampwidth": 1}, "fun_asr_invalid_audio"),
    ],
)
def test_fun_asr_rejects_unusable_audio(
    tmp_path: Path,
    suffix: str,
    wav_options: dict[str, Any],
    expected_code: str,
) -> None:
    audio = tmp_path / f"input{suffix}"
    if suffix == ".wav":
        write_wav(audio, **wav_options)
    else:
        audio.write_bytes(b"not-audio")

    with pytest.raises(AsrProviderError) as error:
        provider_for(FakeConnection()).transcribe(audio, audio.name)

    assert error.value.code == expected_code


def test_fun_asr_endpoint_headers_and_auth_failure_are_safe(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "consultation.wav")
    seen: list[tuple[str, list[str], float]] = []

    def factory(url: str, headers: list[str], timeout: float) -> Any:
        seen.append((url, headers, timeout))
        raise websocket.WebSocketBadStatusException("bad status", 401, "secret response")

    provider = FunAsrProvider(
        "wss://example.test",
        MODEL,
        "test-secret",
        workspace="ws-1",
        timeout=5.0,
        connection_factory=factory,
    )
    with pytest.raises(AsrProviderError) as error:
        provider.transcribe(audio, "consultation.wav")

    assert error.value.code == "fun_asr_auth_failed"
    assert "test-secret" not in error.value.message
    assert "secret response" not in error.value.message
    url, headers, timeout = seen[0]
    assert url == "wss://example.test/api-ws/v1/inference"
    assert headers == [
        "Authorization: Bearer test-secret",
        "User-Agent: zhenlu-assistant/0.1",
        "X-DashScope-WorkSpace: ws-1",
    ]
    assert timeout == 5.0


def test_fun_asr_connection_error_is_safe(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "consultation.wav")

    def factory(url: str, headers: list[str], timeout: float) -> Any:
        raise OSError("secret network detail")

    provider = FunAsrProvider("wss://example.test", MODEL, "test-secret", connection_factory=factory)
    with pytest.raises(AsrProviderError) as error:
        provider.transcribe(audio, "consultation.wav")

    assert error.value.code == "fun_asr_connection_failed"
    assert "secret network detail" not in error.value.message


def test_fun_asr_configuration_is_validated() -> None:
    FunAsrProvider("ws://localhost", MODEL, "test-secret")
    with pytest.raises(ValueError):
        FunAsrProvider("ws://example.test", MODEL, "test-secret")
    with pytest.raises(ValueError):
        FunAsrProvider("wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com", MODEL, "test-secret")
    with pytest.raises(ValueError):
        FunAsrProvider("wss://example.test?model=other", MODEL, "test-secret")
    with pytest.raises(ValueError):
        FunAsrProvider("wss://user:pass@example.test", MODEL, "test-secret")
    with pytest.raises(ValueError):
        FunAsrProvider("wss://example.test", "invalid model", "test-secret")
    with pytest.raises(ValueError):
        FunAsrProvider("wss://example.test", MODEL, "")
    with pytest.raises(ValueError):
        FunAsrProvider("wss://example.test", MODEL, "test-secret", timeout=0)
    with pytest.raises(ValueError):
        FunAsrProvider("wss://example.test", MODEL, "test-secret", sample_rate=4000)
    with pytest.raises(ValueError):
        FunAsrProvider("wss://example.test", MODEL, "test-secret", chunk_interval=6)


def test_fun_asr_transcript_endpoint(client: TestClient) -> None:
    connection = FakeConnection([
        result_event("医生，我咳嗽三天。", sentence_id=1, begin_time=300, end_time=2600),
        finished_event(),
    ])
    client.app.state.asr_provider = provider_for(connection)
    session_id = client.post("/api/sessions", json={"patient_name": "虚构称呼"}).json()["id"]
    uploaded = client.post(
        f"/api/sessions/{session_id}/audio",
        files={"file": ("demo.wav", wav_bytes(), "audio/wav")},
    )
    assert uploaded.status_code == 201

    response = client.post(f"/api/sessions/{session_id}/transcript")
    assert response.status_code == 200, response.text
    transcript = response.json()["transcript"]
    assert transcript["provider"] == PROVIDER_NAME
    assert transcript["is_mock"] is False
    assert transcript["has_reliable_timestamps"] is True
    assert transcript["segments"][0]["speaker"] == "未知"
    assert transcript["segments"][0]["text"] == "医生，我咳嗽三天。"
    assert transcript["segments"][0]["start_ms"] == 300
    assert transcript["segments"][0]["end_ms"] == 2600
    assert "真实语音识别结果" in transcript["notice"]
    assert "test-secret" not in response.text


def test_fun_asr_failure_is_visible_and_retryable(client: TestClient) -> None:
    audio = wav_bytes()
    client.app.state.asr_provider = provider_for(FakeConnection([failed_event()]))
    session_id = client.post("/api/sessions", json={"patient_name": "虚构称呼"}).json()["id"]
    client.post(f"/api/sessions/{session_id}/audio", files={"file": ("demo.wav", audio, "audio/wav")})

    failed = client.post(f"/api/sessions/{session_id}/transcript")
    assert failed.status_code == 502
    assert failed.json()["code"] == "fun_asr_failed"
    assert "secret upstream detail" not in failed.text

    detail = client.get(f"/api/sessions/{session_id}").json()
    assert detail["status"] == "failed"
    assert detail["error_message"] == failed.json()["message"]
    assert detail["transcript"] is None

    client.app.state.asr_provider = provider_for(
        FakeConnection([result_event("咳嗽三天。"), finished_event()])
    )
    retried = client.post(f"/api/sessions/{session_id}/transcript")
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "transcribed"
