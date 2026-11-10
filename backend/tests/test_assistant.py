from __future__ import annotations

import json

import httpx

from app.providers.assistant import AssistantResult, QwenAssistantProvider
from app.providers.qwen_client import QwenJsonClient


def prepare(client):
    sid = client.post("/api/sessions", json={"patient_name": "虚构助手病例"}).json()["id"]
    client.post(f"/api/sessions/{sid}/transcript/manual", json={"text": "患者：咳嗽三天，不记得是否药物过敏。"})
    client.post(f"/api/sessions/{sid}/draft")
    response = client.patch(f"/api/sessions/{sid}/draft", json={"expected_revision": 1, "fields": [{"field_key": "allergy_history", "value": "药物过敏史不详，待核对。"}]})
    assert response.status_code == 200
    return sid


def test_record_answers_keep_version_and_doctor_source(client):
    sid = prepare(client)
    url = f"/api/sessions/{sid}/assistant/questions"
    first = client.post(url, json={"question": "过敏信息是什么？"}, headers={"Idempotency-Key": "ask-1"})
    assert first.status_code == 200, first.text
    answer = first.json()
    assert answer["context_version"]["record_kind"] == "draft"
    assert answer["context_version"]["draft_revision"] == 2
    source = answer["answers"][0]["sources"][0]
    assert source["origin"] == "doctor" and source["id"] == "field:allergy_history"
    assert "不详" in answer["answers"][0]["text"]
    assert client.post(f"/api/sessions/{sid}/confirm", json={"expected_revision": 2}).status_code == 200
    repeated = client.post(url, json={"question": "过敏信息是什么？"}, headers={"Idempotency-Key": "ask-1"})
    assert repeated.json() == answer
    latest = client.post(url, json={"question": "过敏信息是什么？"}).json()
    assert latest["context_version"]["record_kind"] == "confirmed"
    assert latest["context_version"]["confirmed_version"] == 1
    assert len(client.get(url).json()["items"]) == 2
    assert client.get(f"{url}/{answer['id']}").json() == answer
    other = prepare(client)
    assert client.get(f"/api/sessions/{other}/assistant/questions/{answer['id']}").status_code == 404


def test_unknown_questions_and_treatment_do_not_produce_facts(client):
    sid = prepare(client)
    url = f"/api/sessions/{sid}/assistant/questions"
    missing = client.post(url, json={"question": "工作单位是什么？"}).json()
    assert missing["status"] == "insufficient" and missing["answers"] == []
    outside = client.post(url, json={"question": "建议吃什么药治疗？"}).json()
    assert outside["status"] == "out_of_scope" and outside["answers"] == []
    assert client.post(url, json={"question": "   "}).status_code == 422


def test_qwen_assistant_only_receives_current_session_and_rejects_unknown_sources(client):
    sid = prepare(client)
    other = client.post("/api/sessions", json={"patient_name": "不得外发的其他称呼"}).json()["id"]
    client.post(f"/api/sessions/{other}/transcript/manual", json={"text": "其他会话秘密内容"})
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        context = json.loads(payload["messages"][1]["content"])
        calls.append(context)
        assert "其他会话秘密内容" not in request.content.decode()
        assert "虚构助手病例" not in request.content.decode()
        data = {"status": "answered", "answers": [{"text": "药物过敏史不详，待核对。", "evidence_ids": ["field:allergy_history"]}]}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(data)}}]})
    client.app.state.assistant_provider = QwenAssistantProvider(QwenJsonClient("https://test.example/v1", "test-model", "not-a-real-key", transport=httpx.MockTransport(handler)))
    result = client.post(f"/api/sessions/{sid}/assistant/questions", json={"question": "过敏情况？"})
    assert result.status_code == 200 and result.json()["is_mock"] is False
    class Invalid:
        name = "invalid-assistant"
        is_mock = False
        def answer(self, question, context):
            return AssistantResult("answered", ({"text": "无过敏", "evidence_ids": ["segment:other-session"]},))
    client.app.state.assistant_provider = Invalid()
    bad = client.post(f"/api/sessions/{sid}/assistant/questions", json={"question": "过敏情况？"})
    assert bad.status_code == 502 and bad.json()["code"] == "assistant_invalid_response"
    assert len(client.get(f"/api/sessions/{sid}/assistant/questions").json()["items"]) == 1


def test_answer_against_changed_record_is_not_saved(client):
    sid = prepare(client)
    class Slow:
        name = "changing-assistant"
        is_mock = False
        def answer(self, question, context):
            edited = client.patch(f"/api/sessions/{sid}/draft", json={"expected_revision": 2, "fields": [{"field_key": "allergy_history", "value": "医生的新修改"}]})
            assert edited.status_code == 200
            return AssistantResult("answered", ({"text": "旧版本回答", "evidence_ids": ["field:allergy_history"]},))
    client.app.state.assistant_provider = Slow()
    response = client.post(f"/api/sessions/{sid}/assistant/questions", json={"question": "过敏情况？"})
    assert response.status_code == 409 and response.json()["code"] == "assistant_context_changed"
    assert client.get(f"/api/sessions/{sid}/assistant/questions").json()["items"] == []
    assert client.get(f"/api/sessions/{sid}").json()["draft"]["revision"] == 3
