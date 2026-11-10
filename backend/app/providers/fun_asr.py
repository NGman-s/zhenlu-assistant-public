"""Fun-ASR real-time WebSocket transcription; no requests occur at startup."""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
import wave
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import websocket

from app.config import Settings
from app.providers.base import AsrResult, AsrSegment

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT_PATH = "/api-ws/v1/inference"
CONNECT_TIMEOUT_SECONDS = 10.0
RECEIVE_POLL_SECONDS = 1.0
STARTUP_TIMEOUT_SECONDS = 10.0
COMPRESSED_CHUNK_BYTES = 3200
MIN_SAMPLE_RATE = 8000
MAX_SAMPLE_RATE = 48000
SAFE_ERROR_CODE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
SUPPORTED_AUDIO_FORMATS: dict[str, str] = {
    ".wav": "wav",
    ".mp3": "mp3",
    ".aac": "aac",
    ".amr": "amr",
    ".opus": "opus",
    ".speex": "speex",
}


class AsrProviderError(Exception):
    """A user-safe ASR error that never contains credentials or raw upstream text."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class _SentenceEvent:
    sentence_id: int
    text: str
    start_ms: int | None
    end_ms: int | None
    is_final: bool
    billed_seconds: int | None


class _TaskState:
    __slots__ = ("sentences", "billed_seconds", "started", "finished", "error")

    def __init__(self) -> None:
        self.sentences: dict[int, tuple[str, int | None, int | None]] = {}
        self.billed_seconds = 0
        self.started = False
        self.finished = False
        self.error: AsrProviderError | None = None


def _normalize_endpoint(value: str) -> str:
    endpoint = value.strip()
    if any(char.isspace() for char in endpoint):
        raise ValueError("Fun-ASR 接口地址不能包含空白字符。")
    parsed = urlsplit(endpoint)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "Fun-ASR 接口地址必须包含有效主机名，且不能包含账号、密码或查询参数。"
        )
    if "{" in parsed.hostname or "}" in parsed.hostname:
        raise ValueError("请将 Fun-ASR 接口地址中的 {WorkspaceId} 替换为真实业务空间 ID。")
    local_ws = parsed.scheme == "ws" and parsed.hostname in LOCAL_HOSTS
    if parsed.scheme != "wss" and not local_ws:
        raise ValueError("Fun-ASR 接口地址必须为 wss:// 地址；本机测试可使用 ws://localhost。")
    path = parsed.path.rstrip("/") or DEFAULT_ENDPOINT_PATH
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _non_negative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _parse_sentence_event(payload: object) -> _SentenceEvent | None:
    if not isinstance(payload, dict):
        return None
    output = payload.get("output")
    if not isinstance(output, dict):
        return None
    sentence = output.get("sentence")
    if not isinstance(sentence, dict) or sentence.get("heartbeat") is True:
        return None
    text = sentence.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    sentence_id = _non_negative_int(sentence.get("sentence_id"))
    if sentence_id is None:
        return None
    usage = payload.get("usage")
    billed_seconds = _non_negative_int(usage.get("duration")) if isinstance(usage, dict) else None
    return _SentenceEvent(
        sentence_id=sentence_id,
        text=text.strip(),
        start_ms=_non_negative_int(sentence.get("begin_time")),
        end_ms=_non_negative_int(sentence.get("end_time")),
        is_final=sentence.get("sentence_end") is True,
        billed_seconds=billed_seconds,
    )


def _record_sentence(state: _TaskState, event: _SentenceEvent) -> None:
    if not event.is_final:
        return
    state.sentences[event.sentence_id] = (event.text, event.start_ms, event.end_ms)
    if event.billed_seconds is not None:
        state.billed_seconds += event.billed_seconds


def _run_task_message(
    task_id: str,
    model: str,
    audio_format: str,
    sample_rate: int,
    language_hints: tuple[str, ...],
) -> dict[str, Any]:
    parameters: dict[str, Any] = {"format": audio_format, "sample_rate": sample_rate}
    if language_hints:
        parameters["language_hints"] = list(language_hints)
    return {
        "header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"},
        "payload": {
            "task_group": "audio",
            "task": "asr",
            "function": "recognition",
            "model": model,
            "parameters": parameters,
            "input": {},
        },
    }


def _finish_task_message(task_id: str) -> dict[str, Any]:
    return {
        "header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"},
        "payload": {"input": {}},
    }


def _supported_formats_text() -> str:
    return "、".join(sorted(set(SUPPORTED_AUDIO_FORMATS.values())))


def _prepare_audio(
    audio_path: Path,
    original_filename: str,
    configured_sample_rate: int,
) -> tuple[str, int, int]:
    suffix = audio_path.suffix.lower() or Path(original_filename).suffix.lower()
    audio_format = SUPPORTED_AUDIO_FORMATS.get(suffix)
    if audio_format is None:
        raise AsrProviderError(
            "fun_asr_unsupported_format",
            f"Fun-ASR 实时接口不支持该音频格式（{suffix or '无扩展名'}）。"
            f"支持：{_supported_formats_text()}；ogg/webm/flac/m4a 请先转码为单声道 16-bit PCM WAV。",
        )
    try:
        size = audio_path.stat().st_size
    except OSError as exc:
        raise AsrProviderError("fun_asr_input_invalid", "无法读取音频文件，请重新上传。") from exc
    if size == 0:
        raise AsrProviderError("fun_asr_input_invalid", "音频文件为空，请重新上传。")

    sample_rate = configured_sample_rate
    chunk_size = COMPRESSED_CHUNK_BYTES
    if audio_format == "wav":
        try:
            with wave.open(str(audio_path), "rb") as handle:
                if handle.getcomptype() != "NONE":
                    raise AsrProviderError(
                        "fun_asr_invalid_audio",
                        "WAV 音频不是 PCM 编码；请先转换为单声道 16-bit PCM WAV。",
                    )
                channels = handle.getnchannels()
                sample_width = handle.getsampwidth()
                sample_rate = handle.getframerate()
                frame_count = handle.getnframes()
        except (wave.Error, EOFError, OSError) as exc:
            raise AsrProviderError(
                "fun_asr_invalid_audio",
                "无法解析 WAV 音频；请先转换为单声道 16-bit PCM WAV。",
            ) from exc
        if channels != 1:
            raise AsrProviderError(
                "fun_asr_invalid_audio",
                "Fun-ASR 实时接口仅支持单声道音频，请转码后重试。",
            )
        if sample_width != 2:
            raise AsrProviderError(
                "fun_asr_invalid_audio",
                "Fun-ASR 实时接口要求 16-bit PCM WAV，请转码后重试。",
            )
        if frame_count == 0:
            raise AsrProviderError("fun_asr_input_invalid", "WAV 音频没有有效音频帧，请重新上传。")
        chunk_size = max(320, (int(sample_rate * 0.2) // 2) * 2)

    if not MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE:
        raise AsrProviderError(
            "fun_asr_invalid_audio",
            f"音频采样率必须在 {MIN_SAMPLE_RATE}—{MAX_SAMPLE_RATE} Hz 之间。",
        )
    return audio_format, sample_rate, chunk_size


def _default_connection_factory(url: str, headers: list[str], timeout: float) -> Any:
    return websocket.create_connection(
        url,
        timeout=timeout,
        header=headers,
        enable_multithread=True,
    )


def _set_receive_timeout(connection: Any) -> None:
    try:
        connection.settimeout(RECEIVE_POLL_SECONDS)
    except AttributeError:
        pass


def _close_quietly(connection: Any) -> None:
    try:
        connection.close()
    except Exception:
        logger.debug("Fun-ASR connection close failed", exc_info=True)


def _safe_error_code(header: dict[str, Any]) -> str:
    code = header.get("error_code")
    if isinstance(code, str):
        code = code.strip()
        if SAFE_ERROR_CODE.match(code):
            return code
    return ""


def _failure_message(header: dict[str, Any]) -> str:
    code = _safe_error_code(header)
    return (
        f"语音识别服务返回错误（{code}），请稍后重试。"
        if code
        else "语音识别服务返回错误，请稍后重试。"
    )


def _receive_events(
    connection: Any,
    state: _TaskState,
    ready: Event,
    finished: Event,
    deadline: float,
) -> None:
    try:
        while True:
            if time.monotonic() >= deadline:
                state.error = AsrProviderError(
                    "fun_asr_timeout",
                    "语音识别未在限定时间内完成，请缩短音频或增大超时时间。",
                )
                break
            try:
                raw = connection.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except (websocket.WebSocketException, OSError) as exc:
                logger.warning("Fun-ASR receive failed: %s", type(exc).__name__)
                state.error = AsrProviderError(
                    "fun_asr_connection_failed",
                    "语音识别连接中断，请稍后重试。",
                )
                break
            if not isinstance(raw, str):
                state.error = AsrProviderError(
                    "fun_asr_invalid_response",
                    "语音识别服务返回了非文本消息，请重试。",
                )
                break
            try:
                event = json.loads(raw)
            except ValueError:
                state.error = AsrProviderError(
                    "fun_asr_invalid_response",
                    "语音识别服务返回的 JSON 无效，请重试。",
                )
                break
            header = event.get("header") if isinstance(event, dict) else None
            if not isinstance(header, dict):
                state.error = AsrProviderError(
                    "fun_asr_invalid_response",
                    "语音识别服务返回的消息缺少 header，请重试。",
                )
                break
            event_name = header.get("event")
            if event_name == "task-started":
                state.started = True
                ready.set()
            elif event_name == "result-generated":
                sentence = _parse_sentence_event(event.get("payload"))
                if sentence is not None:
                    _record_sentence(state, sentence)
            elif event_name == "task-finished":
                state.finished = True
                break
            elif event_name == "task-failed":
                logger.warning("Fun-ASR task failed: %s", _safe_error_code(header) or "unknown")
                state.error = AsrProviderError("fun_asr_failed", _failure_message(header))
                state.finished = True
                break
    finally:
        if state.error is None and not state.finished:
            state.error = AsrProviderError(
                "fun_asr_connection_failed",
                "语音识别连接已结束，但未收到任务完成事件。",
            )
        state.finished = True
        finished.set()
        ready.set()


def _send_audio(
    connection: Any,
    audio_path: Path,
    chunk_size: int,
    interval: float,
    finished: Event,
    deadline: float,
    timeout_seconds: float,
) -> None:
    timeout_message = (
        f"音频发送未在 {int(timeout_seconds)} 秒内完成，请缩短音频或增大超时时间。"
    )
    with audio_path.open("rb") as handle:
        while not finished.is_set():
            if time.monotonic() >= deadline:
                raise AsrProviderError("fun_asr_timeout", timeout_message)
            chunk = handle.read(chunk_size)
            if not chunk:
                return
            connection.send_binary(chunk)
            if interval > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AsrProviderError("fun_asr_timeout", timeout_message)
                time.sleep(min(interval, remaining))


class FunAsrProvider:
    """Streams an uploaded audio file to Fun-ASR-Realtime and returns final sentences."""

    is_mock = False

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        *,
        workspace: str = "",
        timeout: float = 300.0,
        sample_rate: int = 16000,
        language_hints: Iterable[str] = (),
        chunk_interval: float = 0.1,
        connection_factory: Callable[[str, list[str], float], Any] = _default_connection_factory,
    ) -> None:
        endpoint = _normalize_endpoint(base_url)
        model = model.strip()
        api_key = api_key.strip()
        workspace = workspace.strip()
        language_hints = tuple(hint.strip() for hint in language_hints if hint.strip())

        if not model or len(model) > 120 or any(char.isspace() for char in model):
            raise ValueError("请配置有效的 Fun-ASR 模型 ID。")
        if not api_key or any(char in api_key for char in "\r\n"):
            raise ValueError("请选择 fun-asr 时配置有效的 ZHENLU_FUN_ASR_API_KEY。")
        if len(workspace) > 120 or any(char in workspace for char in "\r\n"):
            raise ValueError("ZHENLU_FUN_ASR_WORKSPACE 无效。")
        if not 1 <= timeout <= 3600:
            raise ValueError("ZHENLU_FUN_ASR_TIMEOUT_SECONDS 应为 1 至 3600 秒。")
        if not MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE:
            raise ValueError(
                f"ZHENLU_FUN_ASR_SAMPLE_RATE 应为 {MIN_SAMPLE_RATE} 至 {MAX_SAMPLE_RATE} Hz。"
            )
        if not 0 <= chunk_interval <= 5:
            raise ValueError("ZHENLU_FUN_ASR_CHUNK_INTERVAL_SECONDS 应为 0 至 5 秒。")

        self._endpoint = endpoint
        self._model = model
        self._api_key = api_key
        self._workspace = workspace
        self._timeout = timeout
        self._sample_rate = sample_rate
        self._language_hints = language_hints
        self._chunk_interval = chunk_interval
        self._connection_factory = connection_factory
        self._language = "zh-CN" if "zh" in language_hints else (language_hints[0] if language_hints else "zh-CN")
        self.name = f"fun-asr:{model}"

    @classmethod
    def from_settings(cls, settings: Settings) -> FunAsrProvider:
        return cls(
            settings.fun_asr_base_url,
            settings.fun_asr_model,
            settings.fun_asr_api_key.get_secret_value(),
            workspace=settings.fun_asr_workspace,
            timeout=settings.fun_asr_timeout_seconds,
            sample_rate=settings.fun_asr_sample_rate,
            language_hints=settings.fun_asr_language_hint_list,
            chunk_interval=settings.fun_asr_chunk_interval_seconds,
        )

    def transcribe(self, audio_path: Path, original_filename: str) -> AsrResult:
        audio_format, sample_rate, chunk_size = _prepare_audio(
            audio_path,
            original_filename,
            self._sample_rate,
        )
        task_id = str(uuid.uuid4())
        state = _TaskState()
        ready = Event()
        finished = Event()
        deadline = time.monotonic() + self._timeout
        connection = self._connect()
        try:
            connection.send(
                json.dumps(
                    _run_task_message(task_id, self._model, audio_format, sample_rate, self._language_hints),
                    ensure_ascii=False,
                )
            )
            Thread(
                target=_receive_events,
                args=(connection, state, ready, finished, deadline),
                name="fun-asr-receiver",
                daemon=True,
            ).start()

            if not ready.wait(min(STARTUP_TIMEOUT_SECONDS, max(0.1, self._timeout))):
                raise AsrProviderError("fun_asr_timeout", "语音识别服务未确认任务启动，请稍后重试。")
            self._raise_for_error(state)
            if not state.started:
                raise AsrProviderError(
                    "fun_asr_invalid_response",
                    "语音识别服务未返回 task-started，请重试。",
                )

            _send_audio(
                connection,
                audio_path,
                chunk_size,
                self._chunk_interval,
                finished,
                deadline,
                self._timeout,
            )
            self._raise_for_error(state)
            if state.finished:
                raise AsrProviderError(
                    "fun_asr_invalid_response",
                    "语音识别服务在音频发送完成前结束了任务，请重试。",
                )

            connection.send(json.dumps(_finish_task_message(task_id), ensure_ascii=False))
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not finished.wait(remaining):
                raise AsrProviderError(
                    "fun_asr_timeout",
                    f"语音识别未在 {int(self._timeout)} 秒内完成，请缩短音频或增大 ZHENLU_FUN_ASR_TIMEOUT_SECONDS。",
                )
            self._raise_for_error(state)
            return self._build_result(state, audio_format, sample_rate)
        except AsrProviderError:
            raise
        except (websocket.WebSocketException, OSError) as exc:
            logger.warning("Fun-ASR transcription failed: %s", type(exc).__name__)
            raise AsrProviderError(
                "fun_asr_connection_failed",
                "语音识别服务连接或音频发送失败，请稍后重试。",
            ) from None
        finally:
            _close_quietly(connection)

    def _connect(self) -> Any:
        timeout = min(CONNECT_TIMEOUT_SECONDS, max(1.0, self._timeout))
        try:
            connection = self._connection_factory(self._endpoint, self._request_headers(), timeout)
        except websocket.WebSocketBadStatusException as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code in (401, 403):
                raise AsrProviderError(
                    "fun_asr_auth_failed",
                    "语音识别服务鉴权失败，请检查密钥、地域、业务空间和接口地址。",
                ) from None
            logger.warning("Fun-ASR handshake failed with status %s", status_code)
            raise AsrProviderError(
                "fun_asr_connection_failed",
                "无法连接语音识别服务，请检查网络和接口地址。",
            ) from None
        except (websocket.WebSocketException, OSError) as exc:
            logger.warning("Fun-ASR connection failed: %s", type(exc).__name__)
            raise AsrProviderError(
                "fun_asr_connection_failed",
                "无法连接语音识别服务，请检查网络和接口地址。",
            ) from None
        _set_receive_timeout(connection)
        return connection

    def _request_headers(self) -> list[str]:
        headers = [
            f"Authorization: Bearer {self._api_key}",
            "User-Agent: zhenlu-assistant/0.1",
        ]
        if self._workspace:
            headers.append(f"X-DashScope-WorkSpace: {self._workspace}")
        return headers

    @staticmethod
    def _raise_for_error(state: _TaskState) -> None:
        if state.error is not None:
            raise state.error

    def _build_result(self, state: _TaskState, audio_format: str, sample_rate: int) -> AsrResult:
        if not state.sentences:
            raise AsrProviderError(
                "fun_asr_empty_result",
                "语音识别未返回任何最终文本，请检查音频内容或质量后重试。",
            )
        segments = tuple(
            AsrSegment(speaker="未知", text=text, start_ms=start_ms, end_ms=end_ms)
            for _, (text, start_ms, end_ms) in sorted(state.sentences.items())
        )
        notice = (
            f"真实语音识别结果（{self._model}）：文本由模型自动识别，可能存在错字、漏句或断句偏差，"
            "必须由医生逐项核对。该接口未返回说话人信息，所有句子说话人为“未知”。"
        )
        return AsrResult(
            segments=segments,
            provider=self.name,
            is_mock=False,
            language=self._language,
            notice=notice,
            metadata={
                "model": self._model,
                "format": audio_format,
                "sample_rate": sample_rate,
                "sentence_count": len(segments),
                "billed_duration_seconds": state.billed_seconds,
            },
        )
