from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from app.providers.base import TranscriptDocument, TranscriptSegmentData
from app.providers.qwen_draft import DraftProviderError, QwenDraftProvider


DOCUMENT = TranscriptDocument("t1", (TranscriptSegmentData("s1", 0, "患者", "咳嗽三天"),))


def valid_response():
    fields = [{"key": key, "value": "未提及", "source_segment_ids": []} for key in (
        "chief_complaint", "present_illness", "past_history", "medication_history", "allergy_history")]
    fields[0].update(value="咳嗽三天", source_segment_ids=["s1"])
    return {"id": "request-123", "model": "actual-model-snapshot", "usage": {
        "prompt_tokens": 4000, "completion_tokens": 1000, "total_tokens": 5000,
        "prompt_tokens_details": {"cached_tokens": 12},
    }, "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"fields": fields})}}]}


def test_bounded_retry_records_each_attempt_and_partial_cost():
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, text="secret must never leave transport")
        return httpx.Response(200, json=valid_response())
    provider = QwenDraftProvider("https://test.example/v1", "test-model", "secret", transport=httpx.MockTransport(handler), input_price=2, output_price=8)
    result = provider.generate(DOCUMENT)
    assert len(calls) == 2
    assert calls[0]["enable_thinking"] is False and calls[0]["temperature"] == 0 and calls[0]["max_tokens"] == 2000
    assert [a["http_status"] for a in result.metadata["attempts"]] == [429, 200]
    assert result.metadata["usage"]["cached_tokens"] == 12
    assert result.metadata["estimated_cost_cny"] == pytest.approx(0.016)
    assert result.metadata["cost_status"] == "partial"
    assert result.metadata["actual_model"] == "actual-model-snapshot"
    assert "secret" not in json.dumps(result.metadata)


@pytest.mark.parametrize("status", [400, 401, 403])
def test_configuration_errors_do_not_retry(status):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(status, text="private-raw-response")
    provider = QwenDraftProvider("https://test.example/v1", "test-model", "secret", transport=httpx.MockTransport(handler))
    with pytest.raises(DraftProviderError) as exc:
        provider.generate(DOCUMENT)
    assert len(calls) == 1
    assert "private" not in str(exc.value) and "secret" not in str(exc.value.metadata)


def test_invalid_schema_keeps_usage_and_is_not_retried():
    calls = []
    def handler(request):
        calls.append(1)
        data = valid_response()
        data["choices"][0]["message"]["content"] = '{"fields": []}'
        return httpx.Response(200, json=data)
    provider = QwenDraftProvider("https://test.example/v1", "test-model", "secret", transport=httpx.MockTransport(handler))
    with pytest.raises(DraftProviderError) as exc:
        provider.generate(DOCUMENT)
    assert exc.value.code == "draft_invalid_response"
    assert exc.value.metadata["usage"]["prompt_tokens"] == 4000
    assert len(calls) == 1


def test_total_deadline_cancels_slow_chunked_response():
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(10):
                await asyncio.sleep(0.2)
                yield b" "
    provider = QwenDraftProvider("https://test.example/v1", "test-model", "secret", timeout=1,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=SlowBody())), max_retries=0)
    started = time.monotonic()
    with pytest.raises(DraftProviderError) as exc:
        provider.generate(DOCUMENT)
    assert exc.value.code == "draft_timeout"
    assert time.monotonic() - started < 1.8


def test_retry_after_larger_than_budget_fails_without_waiting():
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "3600"})
    provider = QwenDraftProvider("https://test.example/v1", "test-model", "secret", transport=httpx.MockTransport(handler))
    started = time.monotonic()
    with pytest.raises(DraftProviderError) as exc:
        provider.generate(DOCUMENT)
    assert exc.value.code == "draft_rate_limited"
    assert len(calls) == 1 and time.monotonic() - started < 1
