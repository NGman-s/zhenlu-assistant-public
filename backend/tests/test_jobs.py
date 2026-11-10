from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.constants import FIELD_DEFINITIONS
from app.main import create_app
from app.models import ProcessingJob, utcnow
from app.providers.base import DraftResult, GeneratedField
from app.services.jobs import run_job


class RealShapeProvider:
    name = "test-real-shape"
    is_mock = False

    def generate(self, transcript):
        return DraftResult(tuple(
            GeneratedField(key, label, "咳嗽三天" if i == 0 else "未提及", (transcript.segments[0].id,) if i == 0 else ())
            for i, (key, label) in enumerate(FIELD_DEFINITIONS)
        ), self.name, False, "测试", {"model": "test", "usage": {"prompt_tokens": 12}})


def text_session(client):
    sid = client.post("/api/sessions", json={"patient_name": "虚构测试"}).json()["id"]
    response = client.post(f"/api/sessions/{sid}/transcript/manual", json={"text": "患者：咳嗽三天。\n医生：是否服药？"})
    assert response.status_code == 200
    assert [s["speaker"] for s in response.json()["transcript"]["segments"]] == ["患者", "医生"]
    return sid


def test_inline_idempotency_records_metrics_and_does_not_generate_twice(client):
    calls = []
    class Provider(RealShapeProvider):
        def generate(self, transcript):
            calls.append(transcript.id)
            return super().generate(transcript)
    client.app.state.draft_provider = Provider()
    sid = text_session(client)
    url = f"/api/sessions/{sid}/draft"
    first = client.post(url, headers={"Idempotency-Key": "generate-1"})
    repeat = client.post(url, headers={"Idempotency-Key": "generate-1"})
    assert first.status_code == repeat.status_code == 200
    assert first.json()["draft"] == repeat.json()["draft"]
    assert len(calls) == 1
    jobs = client.get(f"/api/sessions/{sid}/jobs").json()["items"]
    assert len(jobs) == 1 and jobs[0]["status"] == "succeeded"
    assert jobs[0]["result"]["draft_revision"] == 1
    assert jobs[0]["metrics"]["usage"]["prompt_tokens"] == 12
    assert jobs[0]["elapsed_ms"] >= 0
    conflict = client.post(f"/api/sessions/{sid}/jobs", json={"operation": "regenerate", "expected_revision": 1, "request_id": "generate-1"})
    assert conflict.status_code == 409 and conflict.json()["code"] == "idempotency_conflict"


def test_parallel_initial_generation_has_one_provider_call(client):
    entered, release = Event(), Event()
    calls = []
    class Provider(RealShapeProvider):
        def generate(self, transcript):
            calls.append(1)
            entered.set()
            assert release.wait(5)
            return super().generate(transcript)
    client.app.state.draft_provider = Provider()
    sid = text_session(client)
    url = f"/api/sessions/{sid}/draft"
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(client.post, url)
        try:
            assert entered.wait(5)
            second = client.post(url)
            assert second.status_code == 409 and second.json()["code"] == "operation_in_progress"
            assert client.get(f"/api/sessions/{sid}/jobs").json()["items"][0]["status"] == "running"
        finally:
            release.set()
        assert future.result().status_code == 200
    assert len(calls) == 1


def test_expired_result_cannot_overwrite_a_new_success(client):
    class LateProvider(RealShapeProvider):
        first = True
        def generate(self, transcript):
            if self.first:
                self.first = False
                with client.app.state.db.session_factory() as db:
                    db.execute(update(ProcessingJob).where(ProcessingJob.active_session_id == sid).values(lease_expires_at=utcnow() - timedelta(seconds=1)))
                    db.commit()
                current = client.get(f"/api/sessions/{sid}").json()
                assert current["status"] == "failed"
                retry = client.post(f"/api/sessions/{sid}/draft", headers={"Idempotency-Key": "retry"})
                assert retry.status_code == 200
                self.saved_id = retry.json()["draft"]["id"]
            return super().generate(transcript)
    provider = LateProvider()
    client.app.state.draft_provider = provider
    sid = text_session(client)
    late = client.post(f"/api/sessions/{sid}/draft", headers={"Idempotency-Key": "expired"})
    assert late.status_code == 409 and late.json()["code"] == "job_expired"
    current = client.get(f"/api/sessions/{sid}").json()
    assert current["draft"]["id"] == provider.saved_id and current["status"] == "draft_ready"
    jobs = client.get(f"/api/sessions/{sid}/jobs").json()["items"]
    assert {job["status"] for job in jobs} == {"interrupted", "succeeded"}


def test_confirm_during_regeneration_keeps_confirmed_snapshot(client):
    client.app.state.draft_provider = RealShapeProvider()
    sid = text_session(client)
    original = client.post(f"/api/sessions/{sid}/draft").json()["draft"]
    class ConfirmingProvider(RealShapeProvider):
        def generate(self, transcript):
            assert client.post(f"/api/sessions/{sid}/confirm", json={"expected_revision": 1}).status_code == 200
            return super().generate(transcript)
    client.app.state.draft_provider = ConfirmingProvider()
    result = client.post(f"/api/sessions/{sid}/draft/regenerate", json={"expected_revision": 1})
    assert result.status_code == 409
    current = client.get(f"/api/sessions/{sid}").json()
    assert current["status"] == "confirmed"
    assert current["latest_record"]["fields"][0]["value"] == original["fields"][0]["value"]
    assert current["draft"]["revision"] == 1


def test_background_queue_survives_restart_and_is_processed(settings):
    settings.job_worker_enabled = False
    with TestClient(create_app(settings)) as client:
        sid = text_session(client)
        job = client.post(f"/api/sessions/{sid}/jobs", json={"operation": "generate", "request_id": "persistent"})
        assert job.status_code == 202 and job.json()["status"] == "queued"
        jid = job.json()["id"]
        assert client.get(f"/api/sessions/{sid}").json()["draft"] is None
    settings.job_worker_enabled = True
    with TestClient(create_app(settings)) as client:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get(f"/api/sessions/{sid}/jobs/{jid}").json()
            if job["status"] == "succeeded":
                break
            time.sleep(0.02)
        assert job["status"] == "succeeded"
        assert client.get(f"/api/sessions/{sid}").json()["draft"]["id"] == job["result"]["draft_id"]
        other = text_session(client)
        assert client.get(f"/api/sessions/{other}/jobs/{jid}").status_code == 404


def test_restart_recovers_expired_job_and_legacy_processing(settings):
    settings.job_worker_enabled = False
    with TestClient(create_app(settings)) as client:
        sid = text_session(client)
        job = client.post(f"/api/sessions/{sid}/jobs", json={"operation": "generate"}).json()
        with client.app.state.db.session_factory() as db:
            db.execute(update(ProcessingJob).where(ProcessingJob.id == job["id"]).values(status="running", started_at=utcnow() - timedelta(seconds=60), lease_expires_at=utcnow() - timedelta(seconds=1)))
            db.commit()
    with TestClient(create_app(settings)) as client:
        recovered = client.get(f"/api/sessions/{sid}/jobs/{job['id']}").json()
        assert recovered["status"] == "interrupted"
        assert client.post(f"/api/sessions/{sid}/draft").status_code == 200


def test_queued_job_rejects_provider_change(settings):
    settings.job_worker_enabled = False
    with TestClient(create_app(settings)) as client:
        sid = text_session(client)
        job = client.post(f"/api/sessions/{sid}/jobs", json={"operation": "generate"}).json()
        client.app.state.draft_provider = RealShapeProvider()
        run_job(client.app, job["id"])
        saved = client.get(f"/api/sessions/{sid}/jobs/{job['id']}").json()
        assert saved["status"] == "failed" and saved["error"]["code"] == "provider_changed"
        assert client.get(f"/api/sessions/{sid}").json()["draft"] is None


def test_failed_request_id_replays_failure_without_billing_again(client):
    from app.providers.qwen_client import DraftProviderError
    calls = []
    class FailingProvider(RealShapeProvider):
        def generate(self, transcript):
            calls.append(1)
            raise DraftProviderError("draft_auth_failed", "测试鉴权失败", {"attempts": [{"http_status": 401}]})
    client.app.state.draft_provider = FailingProvider()
    sid = text_session(client)
    for _ in range(2):
        result = client.post(f"/api/sessions/{sid}/draft", headers={"Idempotency-Key": "failed"})
        assert result.status_code == 502 and result.json()["code"] == "draft_auth_failed"
    assert len(calls) == 1
    saved = client.get(f"/api/sessions/{sid}/jobs").json()["items"][0]
    assert saved["metrics"]["attempts"][0]["http_status"] == 401
