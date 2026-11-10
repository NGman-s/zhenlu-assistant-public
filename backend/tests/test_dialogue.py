from __future__ import annotations

import json

import httpx

from app.providers.dialogue import DialogueResult, QwenDialogueProvider
from app.providers.qwen_client import QwenJsonClient
from app.providers.base import DraftResult, GeneratedField
from app.constants import FIELD_DEFINITIONS


def create(client, text):
    sid = client.post("/api/sessions", json={"patient_name": "虚构角色测试"}).json()["id"]
    saved = client.post(f"/api/sessions/{sid}/transcript/manual", json={"text": text})
    return sid, saved.json()["transcript"]


def test_explicit_roles_keep_original_text_annotations_and_unknowns(client):
    sid, raw = create(client, "医生：哪里不舒服？\n患者：咳嗽三天。\n【杂音】\n我也不确定。\n家属：我是患者家属。\n医生：（听不清）")
    response = client.post(f"/api/sessions/{sid}/dialogue", headers={"Idempotency-Key": "roles-1"})
    assert response.status_code == 200, response.text
    turns = response.json()["turns"]
    assert [t["role"] for t in turns] == ["医生", "患者", "未知", "未知", "家属", "未知"]
    assert [t["text"] for t in turns] == [s["text"] for s in raw["segments"]]
    assert [t["segment_id"] for t in turns] == [s["id"] for s in raw["segments"]]
    assert turns[2]["content_kind"] == turns[5]["content_kind"] == "annotation"
    assert all(t["start_ms"] is None for t in turns)
    assert client.get(f"/api/sessions/{sid}/transcript").json() == raw
    assert client.get(f"/api/sessions/{sid}").json()["dialogue"]["id"] == response.json()["id"]
    assert client.post(f"/api/sessions/{sid}/dialogue", headers={"Idempotency-Key": "roles-1"}).json() == response.json()
    assert client.post(f"/api/sessions/{sid}/dialogue").status_code == 409


def test_inferred_roles_are_distinguished_and_passed_to_draft(client):
    sid, raw = create(client, "我是今天的接诊医生。\n我是患者的母亲。\n孩子咳嗽了三天。")
    ids = [s["id"] for s in raw["segments"]]
    def handler(request):
        payload = json.loads(request.content)
        assert payload["response_format"]["json_schema"]["name"] == "dialogue_roles"
        roles = [
            {"segment_id": ids[0], "role": "医生", "source_segment_ids": [ids[0]]},
            {"segment_id": ids[1], "role": "家属", "source_segment_ids": [ids[1]]},
            {"segment_id": ids[2], "role": "未知", "source_segment_ids": []},
        ]
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"roles": roles})}}]})
    client.app.state.dialogue_provider = QwenDialogueProvider(QwenJsonClient("https://test.example/v1", "test-model", "test-key", transport=httpx.MockTransport(handler)))
    response = client.post(f"/api/sessions/{sid}/dialogue")
    assert response.status_code == 200
    assert [t["role_basis"] for t in response.json()["turns"]] == ["inferred", "inferred", "unknown"]
    class Draft:
        name = "role-aware-test"
        is_mock = False
        def generate(self, transcript):
            assert transcript.segments[0].role == "医生"
            assert transcript.segments[0].role_basis == "inferred"
            assert transcript.segments[0].speaker == "未知"
            return DraftResult(tuple(GeneratedField(k, label, "未提及", ()) for k, label in FIELD_DEFINITIONS), self.name, False, "测试")
    client.app.state.draft_provider = Draft()
    assert client.post(f"/api/sessions/{sid}/draft").status_code == 200


def test_bad_role_sources_or_dropped_segments_never_replace_original(client):
    sid, raw = create(client, "医生：什么症状？\n患者：头痛。")
    class Invalid:
        name = "bad-roles"
        is_mock = False
        def structure(self, transcript):
            return DialogueResult(({"segment_id": transcript.segments[0].id, "role": "患者", "source_segment_ids": ["foreign-session"]},))
    client.app.state.dialogue_provider = Invalid()
    result = client.post(f"/api/sessions/{sid}/dialogue")
    assert result.status_code == 502
    assert client.get(f"/api/sessions/{sid}/dialogue").status_code == 404
    assert client.get(f"/api/sessions/{sid}/transcript").json() == raw


def test_role_generation_after_a_draft_is_rejected(client):
    sid, _ = create(client, "患者：头痛。")
    assert client.post(f"/api/sessions/{sid}/draft").status_code == 200
    rejected = client.post(f"/api/sessions/{sid}/dialogue")
    assert rejected.status_code == 409 and rejected.json()["code"] == "draft_exists"
