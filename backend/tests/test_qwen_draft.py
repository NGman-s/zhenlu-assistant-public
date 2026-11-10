from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers.base import TranscriptDocument, TranscriptSegmentData
from app.providers.qwen_draft import DraftProviderError, QwenDraftProvider


def response_for(request: httpx.Request, *, source_override: str | None = None) -> httpx.Response:
    body = json.loads(request.content)
    segments = json.loads(body["messages"][1]["content"])["segments"]
    fields = [
        {"key": "chief_complaint", "value": "咳嗽三天", "source_segment_ids": [source_override or segments[0]["id"]]},
        *[{"key": key, "value": "未提及", "source_segment_ids": []} for key in (
            "present_illness", "past_history", "medication_history", "allergy_history")],
    ]
    return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"fields": fields}, ensure_ascii=False)}}]})


def provider(handler, model: str = "qwen3.7-plus") -> QwenDraftProvider:
    return QwenDraftProvider("https://example.test/compatible-mode/v1", model, "test-secret", transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("legacy_manual", [False, True])
def test_qwen_text_to_review_and_doctor_edit_protection(client: TestClient, legacy_manual: bool) -> None:
    seen = []
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response_for(request)
    client.app.state.draft_provider = provider(handler)
    sid = client.post("/api/sessions", json={"patient_name": "虚构称呼"}).json()["id"]
    saved = client.post(f"/api/sessions/{sid}/transcript/manual", json={"text": "患者咳嗽三天。"})
    assert saved.status_code == 200 and saved.json()["audio"] is None
    assert saved.json()["transcript"]["is_mock"] is False
    if legacy_manual:
        from app.models import Transcript
        with client.app.state.db.session_factory() as db:
            transcript = db.get(Transcript, saved.json()["transcript"]["id"])
            transcript.is_mock = True
            db.commit()
    generated = client.post(f"/api/sessions/{sid}/draft")
    assert generated.status_code == 200, generated.text
    draft = generated.json()["draft"]
    assert draft["provider"] == "qwen:qwen3.7-plus" and draft["is_mock"] is False
    assert draft["fields"][0]["value"] == "咳嗽三天"
    assert draft["fields"][0]["sources"][0]["text"] == "患者咳嗽三天。"
    req = seen[0]
    body = json.loads(req.content)
    assert str(req.url) == "https://example.test/compatible-mode/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer test-secret"
    assert body["model"] == "qwen3.7-plus" and body["response_format"]["type"] == "json_schema"
    assert "虚构称呼" not in req.content.decode("utf-8")
    assert "test-secret" not in generated.text
    edited = client.patch(f"/api/sessions/{sid}/draft", json={"expected_revision": draft["revision"], "fields": [{"field_key": "chief_complaint", "value": "医生更正"}]}).json()
    regenerated = client.post(f"/api/sessions/{sid}/draft/regenerate", json={"expected_revision": edited["draft"]["revision"]}).json()
    assert regenerated["draft"]["fields"][0]["value"] == "医生更正"
    assert regenerated["draft"]["fields"][0]["suggestion"]["value"] == "咳嗽三天"
    confirmed = client.post(f"/api/sessions/{sid}/confirm", json={"expected_revision": regenerated["draft"]["revision"]}).json()
    assert "已经医生审核确认" in confirmed["latest_record"]["text"]
    assert "模拟" not in confirmed["latest_record"]["text"]


def test_failure_and_invalid_source_preserve_existing_draft(client: TestClient) -> None:
    client.app.state.draft_provider = provider(response_for, model="qwen3.8-flash")
    sid = client.post("/api/sessions", json={"patient_name": "虚构称呼"}).json()["id"]
    assert client.post(f"/api/sessions/{sid}/transcript/manual", json={"text": "患者咳嗽三天。"}).status_code == 200
    draft = client.post(f"/api/sessions/{sid}/draft").json()["draft"]
    client.app.state.draft_provider = provider(lambda req: response_for(req, source_override="not-a-real-segment"))
    bad = client.post(f"/api/sessions/{sid}/draft/regenerate", json={"expected_revision": draft["revision"]})
    assert bad.status_code == 502 and bad.json()["code"] == "draft_invalid_response"
    current = client.get(f"/api/sessions/{sid}").json()["draft"]
    assert current["revision"] == draft["revision"] and current["fields"] == draft["fields"]
    client.app.state.draft_provider = provider(lambda req: httpx.Response(401, text="test-secret patient-content"))
    error = client.post(f"/api/sessions/{sid}/draft/regenerate", json={"expected_revision": draft["revision"]})
    assert error.status_code == 502 and error.json()["code"] == "draft_auth_failed"
    assert "test-secret" not in error.text and "patient-content" not in error.text


def test_failed_first_generation_can_retry(client: TestClient) -> None:
    client.app.state.draft_provider = provider(lambda req: httpx.Response(429))
    sid = client.post("/api/sessions", json={"patient_name": "虚构称呼"}).json()["id"]
    client.post(f"/api/sessions/{sid}/transcript/manual", json={"text": "患者咳嗽三天。"})
    response = client.post(f"/api/sessions/{sid}/draft")
    assert response.status_code == 502 and response.json()["code"] == "draft_rate_limited"
    assert client.get(f"/api/sessions/{sid}").json()["draft"] is None
    client.app.state.draft_provider = provider(response_for)
    assert client.post(f"/api/sessions/{sid}/draft").status_code == 200


def test_workspace_endpoint_error_is_actionable_and_does_not_leak(client: TestClient) -> None:
    response = {"error": {"message": "Workspace endpoint is invalid.", "code": "invalid_parameter_error"}}
    client.app.state.draft_provider = provider(lambda req: httpx.Response(400, json=response))
    sid = client.post("/api/sessions", json={"patient_name": "虚构称呼"}).json()["id"]
    client.post(f"/api/sessions/{sid}/transcript/manual", json={"text": "患者咳嗽三天。"})
    result = client.post(f"/api/sessions/{sid}/draft")
    assert result.status_code == 502
    assert result.json()["code"] == "draft_workspace_invalid"
    assert "业务空间接口地址无效" in result.json()["message"]
    assert "test-secret" not in result.text


def test_rejects_missing_source_truncation_and_timeout() -> None:
    transcript = TranscriptDocument("1", (TranscriptSegmentData("s1", 0, "患者", "测试"),))
    for response in [
        httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}),
        httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}),
    ]:
        with pytest.raises(DraftProviderError) as error:
            provider(lambda req: response).generate(transcript)
        assert error.value.code == "draft_invalid_response"
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret in transport error", request=request)
    with pytest.raises(DraftProviderError) as error:
        provider(timeout).generate(transcript)
    assert error.value.code == "draft_timeout" and "secret" not in str(error.value)


def test_insecure_or_unconfigured_endpoint_rejected() -> None:
    with pytest.raises(ValueError):
        QwenDraftProvider("http://remote.example/v1", "qwen3.7-plus", "key")
    with pytest.raises(ValueError):
        QwenDraftProvider("https://example.test/v1?key=secret", "qwen3.7-plus", "key")
    with pytest.raises(ValueError):
        QwenDraftProvider("https://example.test/v1", "qwen3.7-plus", "")


@pytest.mark.parametrize("mutation", ["missing_source", "duplicate_key", "unmentioned_with_source"])
def test_invalid_model_fields_are_rejected(mutation: str) -> None:
    transcript = TranscriptDocument("1", (TranscriptSegmentData("s1", 0, "患者", "咳嗽三天"),))
    def invalid(request: httpx.Request) -> httpx.Response:
        base = response_for(request).json()
        content = json.loads(base["choices"][0]["message"]["content"])
        if mutation == "missing_source":
            content["fields"][0]["source_segment_ids"] = []
        elif mutation == "duplicate_key":
            content["fields"][1]["key"] = "chief_complaint"
        else:
            content["fields"][1]["source_segment_ids"] = ["s1"]
        base["choices"][0]["message"]["content"] = json.dumps(content, ensure_ascii=False)
        return httpx.Response(200, json=base)
    with pytest.raises(DraftProviderError) as error:
        provider(invalid).generate(transcript)
    assert error.value.code == "draft_invalid_response"
