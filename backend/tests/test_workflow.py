from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import ApiError
from app.schemas import DraftUpdate
from app.services.session_service import get_session_or_404
from app.services.workflow import confirm_draft, update_draft
from app.providers.base import (
    DraftResult,
    GeneratedField,
    TranscriptDocument,
)

SAMPLE_DATA_DIR = Path(__file__).resolve().parents[2] / "sample-data"
FIELD_KEYS = [
    "chief_complaint",
    "present_illness",
    "past_history",
    "medication_history",
    "allergy_history",
]


def create_session(client: TestClient, name: str = "演示患者 A") -> str:
    response = client.post(
        "/api/sessions",
        json={"patient_name": name, "patient_ref": "DEMO-001"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload_sample(client: TestClient, session_id: str, case_key: str) -> dict[str, Any]:
    audio_path = SAMPLE_DATA_DIR / f"mock-consultation-{case_key}.wav"
    with audio_path.open("rb") as handle:
        response = client.post(
            f"/api/sessions/{session_id}/audio",
            files={"file": (audio_path.name, handle, "audio/wav")},
        )
    assert response.status_code == 201, response.text
    return response.json()


def upload_bytes(
    client: TestClient,
    session_id: str,
    content: bytes,
    filename: str,
    content_type: str = "audio/wav",
) -> Any:
    return client.post(
        f"/api/sessions/{session_id}/audio",
        files={"file": (filename, content, content_type)},
    )


def start_transcript(client: TestClient, session_id: str) -> dict[str, Any]:
    response = client.post(f"/api/sessions/{session_id}/transcript")
    assert response.status_code == 200, response.text
    return response.json()


def start_draft(client: TestClient, session_id: str) -> dict[str, Any]:
    response = client.post(f"/api/sessions/{session_id}/draft")
    assert response.status_code == 200, response.text
    return response.json()


def prepare_draft(client: TestClient, case_key: str = "case-01") -> tuple[str, dict]:
    session_id = create_session(client)
    upload_sample(client, session_id, case_key)
    start_transcript(client, session_id)
    workspace = start_draft(client, session_id)
    return session_id, workspace


class VariantDraftProvider:
    name = "test-variant-draft"
    is_mock = True

    def generate(self, transcript: TranscriptDocument) -> DraftResult:
        first_id = transcript.segments[0].id
        second_id = transcript.segments[1].id
        fields = (
            GeneratedField(
                "chief_complaint",
                "主诉",
                "系统新建议主诉。",
                (first_id,),
            ),
            GeneratedField(
                "present_illness",
                "现病史",
                "系统更新的现病史。",
                (second_id,),
            ),
            GeneratedField("past_history", "既往史", "未提及", ()),
            GeneratedField("medication_history", "用药史", "未提及", ()),
            GeneratedField("allergy_history", "过敏史", "未提及", ()),
        )
        return DraftResult(
            fields=fields, provider=self.name, is_mock=True, notice="测试建议来源"
        )


class FailingAsrProvider:
    name = "test-failing-asr"
    is_mock = True

    def transcribe(self, audio_path: Path, original_filename: str) -> Any:
        raise RuntimeError("simulated ASR outage")


class InvalidSourceDraftProvider:
    name = "test-invalid-source-draft"
    is_mock = True

    def generate(self, transcript: TranscriptDocument) -> DraftResult:
        first_id = transcript.segments[0].id
        fields = tuple(
            GeneratedField(
                key,
                label,
                "测试内容",
                ("does-not-exist", first_id, first_id),
            )
            for key, label in zip(
                FIELD_KEYS,
                ["主诉", "现病史", "既往史", "用药史", "过敏史"],
                strict=True,
            )
        )
        return DraftResult(
            fields=fields, provider=self.name, is_mock=True, notice="测试来源校验"
        )


def test_full_flow_from_mock_audio_to_confirmed_copy(
    client: TestClient, app: FastAPI
) -> None:
    health = client.get("/api/health").json()
    assert health["mock_mode"] is True
    assert health["asr_is_mock"] is True
    assert health["draft_is_mock"] is True

    cases = client.get("/api/demo/cases").json()["items"]
    assert [case["key"] for case in cases] == ["case-01", "case-02"]
    assert client.get("/api/demo/cases/case-01/audio").headers["content-type"].startswith(
        "audio/wav"
    )

    session_id = create_session(client)
    session = client.get(f"/api/sessions/{session_id}").json()
    assert session["status"] == "awaiting_audio"
    assert session["status_label"] == "待录入问诊内容"
    assert session["audio"] is None
    assert session["transcript"] is None
    assert session["draft"] is None

    workspace = upload_sample(client, session_id, "case-01")
    assert workspace["status"] == "audio_ready"
    assert workspace["audio"]["filename"] == "mock-consultation-case-01.wav"
    assert workspace["audio"]["duration_ms"] > 100_000
    assert Path(app.state.settings.upload_dir / session_id).is_dir()

    listed = client.get("/api/sessions").json()["items"]
    assert len(listed) == 1
    assert listed[0]["has_audio"] is True
    assert listed[0]["has_transcript"] is False

    workspace = start_transcript(client, session_id)
    transcript = workspace["transcript"]
    assert workspace["status"] == "transcribed"
    assert transcript["provider"] == "mock-consultation-asr-v1"
    assert transcript["is_mock"] is True
    assert "未调用真实语音识别服务" in transcript["notice"]
    assert transcript["has_reliable_timestamps"] is True
    assert len(transcript["segments"]) == 22
    assert all(segment["start_ms"] is not None for segment in transcript["segments"])
    segment_ids = {segment["id"] for segment in transcript["segments"]}

    fetched_transcript = client.get(
        f"/api/sessions/{session_id}/transcript"
    ).json()
    assert fetched_transcript["segments"] == transcript["segments"]

    workspace = start_draft(client, session_id)
    draft = workspace["draft"]
    assert workspace["status"] == "draft_ready"
    assert draft["is_mock"] is True
    assert "未调用真实大模型" in draft["notice"]
    assert len(draft["fields"]) == 5
    assert [field["key"] for field in draft["fields"]] == FIELD_KEYS
    fields = {field["key"]: field for field in draft["fields"]}
    for field in draft["fields"]:
        assert field["origin"] == "ai"
        assert field["is_doctor_edited"] is False
        assert set(source["id"] for source in field["sources"]).issubset(segment_ids)
    assert fields["chief_complaint"]["value"] == "咳嗽、咳痰5天，伴发热2天。"
    assert len(fields["allergy_history"]["sources"]) == 1

    original_ai_value = fields["chief_complaint"]["value"]
    edited_value = "咳嗽、咳黄白痰伴发热5天，医生已核对。"
    response = client.patch(
        f"/api/sessions/{session_id}/draft",
        json={
            "expected_revision": 0,
            "fields": [{"field_key": "chief_complaint", "value": edited_value}],
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "revision_conflict"

    response = client.patch(
        f"/api/sessions/{session_id}/draft",
        json={
            "expected_revision": 1,
            "fields": [{"field_key": "chief_complaint", "value": edited_value}],
        },
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["draft"]["revision"] == 2
    chief = next(
        field
        for field in saved["draft"]["fields"]
        if field["key"] == "chief_complaint"
    )
    assert chief["value"] == edited_value
    assert chief["ai_value"] == original_ai_value
    assert chief["origin"] == "doctor"
    assert chief["is_doctor_edited"] is True
    assert chief["edited_at"] is not None

    response = client.post(
        f"/api/sessions/{session_id}/draft/regenerate",
        json={"expected_revision": 2},
    )
    assert response.status_code == 200, response.text
    regenerated = response.json()
    assert regenerated["draft"]["revision"] == 3
    chief = next(
        field
        for field in regenerated["draft"]["fields"]
        if field["key"] == "chief_complaint"
    )
    assert chief["value"] == edited_value
    assert chief["origin"] == "doctor"
    assert chief["suggestion"] is not None
    assert chief["suggestion"]["value"] == original_ai_value
    assert len(chief["suggestion"]["sources"]) == 2

    response = client.post(
        f"/api/sessions/{session_id}/confirm", json={"expected_revision": 3}
    )
    assert response.status_code == 200, response.text
    confirmed = response.json()
    assert confirmed["status"] == "confirmed"
    assert confirmed["status_label"] == "已确认"
    assert confirmed["confirmed_version"] == 1
    record = confirmed["latest_record"]
    assert record["version"] == 1
    assert "主诉：" + edited_value in record["text"]
    assert "既往史：" in record["text"]
    assert "仅供演示" in record["text"]
    confirmed_chief = next(
        field for field in record["fields"] if field["key"] == "chief_complaint"
    )
    assert confirmed_chief["origin"] == "doctor"
    assert confirmed_chief["value"] == edited_value

    record_response = client.get(f"/api/sessions/{session_id}/record")
    assert record_response.status_code == 200
    assert record_response.json()["text"] == record["text"]
    text_response = client.get(f"/api/sessions/{session_id}/record/text")
    assert text_response.status_code == 200
    assert text_response.json()["version"] == 1
    assert text_response.json()["text"] == record["text"]

    audio_response = client.get(f"/api/sessions/{session_id}/audio")
    assert audio_response.status_code == 200
    assert audio_response.headers["content-type"].startswith("audio/wav")
    assert audio_response.content[:4] == b"RIFF"

    listed = client.get("/api/sessions").json()["items"][0]
    assert listed["status"] == "confirmed"
    assert listed["confirmed_version"] == 1
    assert listed["has_draft"] is True

    locked_patch = client.patch(
        f"/api/sessions/{session_id}/draft",
        json={
            "expected_revision": 3,
            "fields": [{"field_key": "chief_complaint", "value": "确认后再改"}],
        },
    )
    assert locked_patch.status_code == 409
    assert locked_patch.json()["code"] == "session_confirmed"
    assert (
        client.post(
            f"/api/sessions/{session_id}/draft/regenerate",
            json={"expected_revision": 3},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/sessions/{session_id}/confirm", json={"expected_revision": 3}
        ).status_code
        == 409
    )


def test_unmentioned_fields_are_explicit_and_copyable(client: TestClient) -> None:
    session_id, workspace = prepare_draft(client, "case-02")
    fields = {field["key"]: field for field in workspace["draft"]["fields"]}

    for key in ("past_history", "medication_history", "allergy_history"):
        assert fields[key]["value"] == "未提及"
        assert fields[key]["is_unmentioned"] is True
        assert fields[key]["sources"] == []

    assert fields["chief_complaint"]["value"] == "咽痛伴干咳3天。"
    assert len(fields["chief_complaint"]["sources"]) == 1

    response = client.post(
        f"/api/sessions/{session_id}/confirm", json={"expected_revision": 1}
    )
    assert response.status_code == 200
    text = response.json()["latest_record"]["text"]
    assert "既往史：未提及" in text
    assert "用药史：未提及" in text
    assert "过敏史：未提及" in text
    assert "既往史：无" not in text


def test_regeneration_protects_doctor_edits_and_offers_explicit_suggestion(
    client: TestClient, app: FastAPI
) -> None:
    session_id, _ = prepare_draft(client, "case-01")
    doctor_value = "医生确认后的主诉内容。"
    response = client.patch(
        f"/api/sessions/{session_id}/draft",
        json={
            "expected_revision": 1,
            "fields": [{"field_key": "chief_complaint", "value": doctor_value}],
        },
    )
    assert response.status_code == 200

    app.state.draft_provider = VariantDraftProvider()
    response = client.post(
        f"/api/sessions/{session_id}/draft/regenerate",
        json={"expected_revision": 2},
    )
    assert response.status_code == 200, response.text
    draft = response.json()["draft"]
    assert draft["revision"] == 3
    assert draft["has_doctor_edits"] is True
    assert draft["has_suggestions"] is True
    fields = {field["key"]: field for field in draft["fields"]}

    chief = fields["chief_complaint"]
    assert chief["value"] == doctor_value
    assert chief["origin"] == "doctor"
    assert chief["suggestion"]["value"] == "系统新建议主诉。"
    assert len(chief["suggestion"]["sources"]) == 1

    present = fields["present_illness"]
    assert present["value"] == "系统更新的现病史。"
    assert present["ai_value"] == "系统更新的现病史。"
    assert present["origin"] == "ai"

    response = client.patch(
        f"/api/sessions/{session_id}/draft",
        json={
            "expected_revision": 3,
            "fields": [
                {"field_key": "chief_complaint", "value": "系统新建议主诉。", "accept_suggestion": True}
            ],
        },
    )
    assert response.status_code == 200
    adopted = response.json()["draft"]
    assert adopted["revision"] == 4
    chief = next(
        field for field in adopted["fields"] if field["key"] == "chief_complaint"
    )
    assert chief["value"] == "系统新建议主诉。"
    assert chief["origin"] == "doctor"
    assert chief["suggestion"] is None
    assert [source["seq"] for source in chief["sources"]] == [0]
    assert adopted["has_suggestions"] is False

    confirmed = client.post(
        f"/api/sessions/{session_id}/confirm", json={"expected_revision": 4}
    )
    assert confirmed.status_code == 200
    assert "主诉：系统新建议主诉。" in confirmed.json()["latest_record"]["text"]
    assert confirmed.json()["latest_record"]["fields"][0]["sources"][0]["seq"] == 0


def test_invalid_sources_are_dropped_by_server(
    client: TestClient, app: FastAPI
) -> None:
    session_id = create_session(client)
    upload_sample(client, session_id, "case-01")
    start_transcript(client, session_id)
    app.state.draft_provider = InvalidSourceDraftProvider()
    workspace = start_draft(client, session_id)

    for field in workspace["draft"]["fields"]:
        assert len(field["sources"]) == 1
        assert field["sources"][0]["seq"] == 0
        assert field["sources"][0]["id"] != "does-not-exist"


def test_provider_failure_is_visible_and_retryable(
    client: TestClient, app: FastAPI
) -> None:
    session_id = create_session(client)
    upload_sample(client, session_id, "case-01")
    mock_provider = app.state.asr_provider
    app.state.asr_provider = FailingAsrProvider()

    response = client.post(f"/api/sessions/{session_id}/transcript")
    assert response.status_code == 502
    assert response.json()["code"] == "asr_failed"

    session = client.get(f"/api/sessions/{session_id}").json()
    assert session["status"] == "failed"
    assert session["error_message"]
    assert session["transcript"] is None

    app.state.asr_provider = mock_provider
    retried = client.post(f"/api/sessions/{session_id}/transcript")
    assert retried.status_code == 200
    assert retried.json()["status"] == "transcribed"
    assert retried.json()["error_message"] is None


def test_unmatched_audio_has_no_fabricated_timestamps(client: TestClient) -> None:
    session_id = create_session(client)
    response = upload_bytes(
        client,
        session_id,
        b"RIFF\x00\x00\x00\x00WAVEfmt ",
        "renamed-consultation.wav",
    )
    assert response.status_code == 201, response.text
    workspace = start_transcript(client, session_id)
    transcript = workspace["transcript"]
    assert transcript["has_reliable_timestamps"] is False
    assert all(segment["start_ms"] is None for segment in transcript["segments"])
    assert all(segment["end_ms"] is None for segment in transcript["segments"])
    assert "所有句子均不提供时间戳" in transcript["notice"]

    # 模拟草稿仍可基于默认虚构文本生成，并且来源只引用转写中的真实句子。
    workspace = start_draft(client, session_id)
    transcript_ids = {segment["id"] for segment in transcript["segments"]}
    all_source_ids = {
        source["id"]
        for field in workspace["draft"]["fields"]
        for source in field["sources"]
    }
    assert all_source_ids.issubset(transcript_ids)


def test_same_filename_with_different_content_has_no_sample_timestamps(client: TestClient) -> None:
    session_id = create_session(client)
    response = upload_bytes(client, session_id, b"not a sample", "mock-consultation-case-01.wav")
    assert response.status_code == 201
    transcript = start_transcript(client, session_id)["transcript"]
    assert not transcript["has_reliable_timestamps"]
    assert all(segment["start_ms"] is None for segment in transcript["segments"])


def test_stale_parallel_save_and_confirm_are_rejected(client: TestClient, app: FastAPI) -> None:
    session_id, _ = prepare_draft(client)
    first = app.state.db.session_factory()
    second = app.state.db.session_factory()
    try:
        a = get_session_or_404(first, session_id)
        b = get_session_or_404(second, session_id)
        assert a.draft.revision == b.draft.revision == 1
        update_draft(first, session_id, DraftUpdate(expected_revision=1, fields=[
            {"field_key": "chief_complaint", "value": "第一位医生的修改"}
        ]))
        with pytest.raises(ApiError) as error:
            update_draft(second, session_id, DraftUpdate(expected_revision=1, fields=[
                {"field_key": "chief_complaint", "value": "第二位医生的修改"}
            ]))
        assert error.value.code == "revision_conflict"
        result = client.get(f"/api/sessions/{session_id}").json()
        assert result["draft"]["fields"][0]["value"] == "第一位医生的修改"
    finally:
        first.close()
        second.close()

    first = app.state.db.session_factory()
    second = app.state.db.session_factory()
    try:
        a = get_session_or_404(first, session_id)
        b = get_session_or_404(second, session_id)
        assert a.draft.revision == b.draft.revision == 2
        confirm_draft(first, session_id, app.state.settings, 2)
        with pytest.raises(ApiError) as error:
            update_draft(second, session_id, DraftUpdate(expected_revision=2, fields=[
                {"field_key": "chief_complaint", "value": "确认后的旧页面修改"}
            ]))
        assert error.value.code == "revision_conflict"
        result = client.get(f"/api/sessions/{session_id}").json()
        assert result["status"] == "confirmed"
        assert result["draft"]["fields"][0]["value"] == result["latest_record"]["fields"][0]["value"]
    finally:
        first.close()
        second.close()


def test_save_during_regeneration_is_not_overwritten(client: TestClient, app: FastAPI) -> None:
    session_id, _ = prepare_draft(client)

    class ConcurrentProvider(VariantDraftProvider):
        def generate(self, transcript: TranscriptDocument) -> DraftResult:
            response = client.patch(f"/api/sessions/{session_id}/draft", json={
                "expected_revision": 1,
                "fields": [{"field_key": "chief_complaint", "value": "并发保存"}],
            })
            assert response.status_code == 200
            return super().generate(transcript)

    app.state.draft_provider = ConcurrentProvider()
    response = client.post(f"/api/sessions/{session_id}/draft/regenerate", json={"expected_revision": 1})
    assert response.status_code == 409
    assert response.json()["code"] == "revision_conflict"
    result = client.get(f"/api/sessions/{session_id}").json()
    assert result["draft"]["fields"][0]["value"] == "并发保存"


def test_manual_transcript_and_template_workflow(client: TestClient) -> None:
    session_id = create_session(client)
    url = f"/api/sessions/{session_id}/transcript/manual"
    assert client.post(url, json={"text": "  \n  "}).status_code == 422
    assert client.post(url, json={"text": "\n".join(["a"] * 201)}).status_code == 422
    response = client.post(url, json={"text": "医生：哪里不舒服？\n\n患者：咳嗽三天。"})
    assert response.status_code == 200, response.text
    transcript = response.json()["transcript"]
    assert response.json()["audio"] is None
    assert transcript["provider"] == "manual"
    assert [segment["text"] for segment in transcript["segments"]] == ["医生：哪里不舒服？", "患者：咳嗽三天。"]
    assert all(segment["start_ms"] is None and segment["end_ms"] is None for segment in transcript["segments"])
    assert client.post(url, json={"text": "重复"}).status_code == 409
    draft = start_draft(client, session_id)["draft"]
    assert draft["provider"] == "manual-template"
    assert all(field["value"] == "未提及" and not field["sources"] for field in draft["fields"])
    assert client.post(f"/api/sessions/{session_id}/draft/regenerate", json={"expected_revision": draft["revision"]}).status_code == 409
    saved = client.patch(f"/api/sessions/{session_id}/draft", json={"expected_revision": draft["revision"], "fields": [{"field_key": "chief_complaint", "value": "咳嗽三天"}]})
    assert saved.status_code == 200
    confirmed = client.post(f"/api/sessions/{session_id}/confirm", json={"expected_revision": saved.json()["draft"]["revision"]})
    assert confirmed.status_code == 200
    assert "咳嗽三天" in confirmed.json()["latest_record"]["text"]
    assert "仅供演示" in confirmed.json()["latest_record"]["text"]
