"""Bounded JSON calls shared by the record and current-session assistant."""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from app.config import Settings


class DraftProviderError(Exception):
    """Only application-authored messages and allowlisted metadata leave this layer."""

    def __init__(self, code: str, message: str, metadata: dict | None = None) -> None:
        super().__init__(message)
        self.code, self.message = code, message
        self.metadata = metadata or {}


def _safe_id(value: object) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[\w.:-]{1,160}", value, flags=re.ASCII) else None


def _count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _usage(body: dict) -> dict:
    raw = body.get("usage")
    if not isinstance(raw, dict):
        return {}
    result = {key: raw[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens") if _count(raw.get(key)) is not None}
    for group, key in (("prompt_tokens_details", "cached_tokens"), ("completion_tokens_details", "reasoning_tokens")):
        detail = raw.get(group)
        if isinstance(detail, dict) and _count(detail.get(key)) is not None:
            result[key] = detail[key]
    return result


def _retry_delay(header: str | None, attempt: int) -> float:
    if header:
        try:
            seconds = float(header)
            return max(0.0, seconds) if math.isfinite(seconds) else 0.25 * (2 ** attempt)
        except ValueError:
            try:
                return max(0.0, (parsedate_to_datetime(header).astimezone(UTC) - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
    return 0.25 * (2 ** attempt)


class QwenJsonClient:
    def __init__(
        self, base_url: str, model: str, api_key: str, timeout: float = 120.0,
        *, transport=None, attempt_timeout: float = 20, max_retries: int = 1,
        max_tokens: int = 2000, input_price: float | None = None, output_price: float | None = None,
    ) -> None:
        base = base_url.strip().rstrip("/")
        parsed = urlsplit(base)
        local = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                or (parsed.scheme != "https" and not local)):
            raise ValueError("百炼接口地址必须为 HTTPS 地址（本机测试可使用 HTTP），不能包含账号、密码或查询参数。")
        if not _safe_id(model.strip()):
            raise ValueError("请配置有效的百炼模型 ID。")
        if not api_key.strip() or any(c in api_key for c in "\r\n"):
            raise ValueError("请选择 qwen 时配置有效的 ZHENLU_QWEN_API_KEY。")
        if not 1 <= timeout <= 600 or not 1 <= attempt_timeout <= 600 or max_retries not in (0, 1):
            raise ValueError("模型超时应为 1 至 600 秒，自动重试最多一次。")
        self.url = base if parsed.path.endswith("/chat/completions") else base + "/chat/completions"
        self.model, self.api_key = model.strip(), api_key.strip()
        self.timeout, self.attempt_timeout = timeout, attempt_timeout
        self.transport, self.max_retries, self.max_tokens = transport, max_retries, max_tokens
        self.input_price, self.output_price = input_price, output_price

    @classmethod
    def from_settings(cls, settings: Settings) -> QwenJsonClient:
        return cls(
            settings.qwen_base_url, settings.qwen_model, settings.qwen_api_key.get_secret_value(),
            settings.qwen_timeout_seconds, attempt_timeout=settings.qwen_attempt_timeout_seconds,
            max_retries=settings.qwen_max_retries, max_tokens=settings.qwen_max_tokens,
            input_price=settings.qwen_input_price_per_million, output_price=settings.qwen_output_price_per_million,
        )

    def complete(self, system: str, data: dict, response_format: dict, *, prompt_version: str, schema_version: str) -> tuple[object, dict]:
        # Sync providers run in FastAPI/worker threads, leaving the ASGI loop free.
        return asyncio.run(self._complete(system, data, response_format, prompt_version, schema_version))

    async def _complete(self, system: str, data: dict, response_format: dict, prompt_version: str, schema_version: str) -> tuple[object, dict]:
        started = time.monotonic()
        metrics = {
            "model": self.model, "prompt_version": prompt_version, "schema_version": schema_version,
            "attempts": [], "enable_thinking": False, "temperature": 0, "max_tokens": self.max_tokens,
            "estimated_cost_cny": None, "cost_status": "unknown",
        }
        payload = {
            "model": self.model, "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
            ], "response_format": response_format, "stream": False,
            "enable_thinking": False, "temperature": 0, "max_tokens": self.max_tokens,
        }
        try:
            async with asyncio.timeout(self.timeout):
                async with httpx.AsyncClient(transport=self.transport, follow_redirects=False, timeout=httpx.Timeout(self.attempt_timeout, connect=min(5.0, self.attempt_timeout))) as client:
                    for attempt in range(self.max_retries + 1):
                        item = {"number": attempt + 1, "usage": {}, "cost_status": "unknown"}
                        metrics["attempts"].append(item)
                        attempt_started = time.monotonic()
                        delay = 0.25
                        try:
                            async with asyncio.timeout(self.attempt_timeout):
                                async with client.stream("POST", self.url, headers={"Authorization": f"Bearer {self.api_key}"}, json=payload) as response:
                                    item["http_status"] = response.status_code
                                    item["request_id"] = _safe_id(response.headers.get("x-request-id"))
                                    delay = _retry_delay(response.headers.get("retry-after"), attempt)
                                    content = bytearray()
                                    async for chunk in response.aiter_bytes():
                                        content.extend(chunk)
                                        if len(content) > 1_000_000:
                                            raise DraftProviderError("draft_invalid_response", "模型返回内容过大，请重试。")
                                    self._check_status(response.status_code, content)
                            body = json.loads(content)
                            if not isinstance(body, dict):
                                raise ValueError("body")
                            item["request_id"] = _safe_id(body.get("id")) or item["request_id"]
                            item["usage"] = _usage(body)
                            actual_model = _safe_id(body.get("model"))
                            if actual_model:
                                metrics["actual_model"] = actual_model
                            metrics["usage"] = item["usage"]
                            choice = body["choices"][0]
                            if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
                                raise ValueError("incomplete response")
                            result = json.loads(choice["message"]["content"])
                            usage = item["usage"]
                            if (self.input_price is not None and self.output_price is not None
                                    and "prompt_tokens" in usage and "completion_tokens" in usage):
                                cost = (usage["prompt_tokens"] * self.input_price + usage["completion_tokens"] * self.output_price) / 1_000_000
                                item.update(estimated_cost_cny=cost, cost_status="estimated")
                                metrics.update(estimated_cost_cny=cost, cost_status="estimated" if attempt == 0 else "partial")
                            return result, metrics
                        except (httpx.TimeoutException, TimeoutError):
                            error = DraftProviderError("draft_timeout", "模型请求超时，请稍后重试。")
                        except httpx.HTTPError:
                            error = DraftProviderError("draft_connection_failed", "无法连接模型服务，请检查网络和接口地址。")
                        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                            error = DraftProviderError("draft_invalid_response", "模型返回格式或来源无效，请重试。")
                        except DraftProviderError as exc:
                            error = exc
                        finally:
                            item["elapsed_ms"] = round((time.monotonic() - attempt_started) * 1000)
                        item["error_code"] = error.code
                        retryable = error.code in {"draft_timeout", "draft_connection_failed", "draft_rate_limited", "draft_upstream_error"}
                        if not retryable or attempt == self.max_retries or delay >= self.timeout - (time.monotonic() - started):
                            raise error
                        await asyncio.sleep(delay)
        except TimeoutError:
            raise DraftProviderError("draft_timeout", "模型请求达到总时限，请稍后重试。", metrics) from None
        except DraftProviderError as exc:
            exc.metadata = metrics
            raise
        finally:
            metrics["elapsed_ms"] = round((time.monotonic() - started) * 1000)

    @staticmethod
    def _check_status(status: int, content: bytes) -> None:
        if status == 200:
            return
        errors = {
            401: ("draft_auth_failed", "模型服务鉴权失败，请检查密钥、地域和模型权限。"),
            403: ("draft_auth_failed", "模型服务鉴权失败，请检查密钥、地域和模型权限。"),
            429: ("draft_rate_limited", "模型服务暂时限流，请稍后重试。"),
        }
        if status in errors:
            raise DraftProviderError(*errors[status])
        if status >= 500:
            raise DraftProviderError("draft_upstream_error", "模型服务暂时不可用，请稍后重试。")
        if status == 400:
            try:
                body = json.loads(content)
                error = body.get("error", body)
                if isinstance(error, dict) and error.get("message") == "Workspace endpoint is invalid.":
                    raise DraftProviderError("draft_workspace_invalid", "百炼业务空间接口地址无效，请检查接口地址、地域和业务空间配置。")
            except (ValueError, AttributeError):
                pass
        raise DraftProviderError("draft_request_failed", "模型请求未被接受，请检查接口地址、模型及参数配置。")
