from __future__ import annotations

from enum import StrEnum


class SessionStatus(StrEnum):
    AWAITING_AUDIO = "awaiting_audio"
    AUDIO_READY = "audio_ready"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    GENERATING_DRAFT = "generating_draft"
    DRAFT_READY = "draft_ready"
    CONFIRMED = "confirmed"
    FAILED = "failed"


SESSION_STATUS_LABELS: dict[str, str] = {
    SessionStatus.AWAITING_AUDIO: "待录入问诊内容",
    SessionStatus.AUDIO_READY: "音频已上传",
    SessionStatus.TRANSCRIBING: "转写中",
    SessionStatus.TRANSCRIBED: "转写完成",
    SessionStatus.GENERATING_DRAFT: "生成草稿中",
    SessionStatus.DRAFT_READY: "草稿待审核",
    SessionStatus.CONFIRMED: "已确认",
    SessionStatus.FAILED: "处理失败",
}


class FieldOrigin(StrEnum):
    AI = "ai"
    DOCTOR = "doctor"


class DraftStatus(StrEnum):
    EDITING = "editing"
    CONFIRMED = "confirmed"


# 顺序即页面展示顺序，服务端不接受未知字段。
FIELD_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("chief_complaint", "主诉"),
    ("present_illness", "现病史"),
    ("past_history", "既往史"),
    ("medication_history", "用药史"),
    ("allergy_history", "过敏史"),
)

FIELD_LABELS: dict[str, str] = dict(FIELD_DEFINITIONS)
FIELD_KEYS: tuple[str, ...] = tuple(key for key, _ in FIELD_DEFINITIONS)

UNMENTIONED = "未提及"

ALLOWED_AUDIO_EXTENSIONS: dict[str, str] = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
}

MOCK_ASR_NOTICE = (
    "当前为模拟转写结果：文本来自内置虚构病例，未调用真实语音识别服务。"
    "示例音频中的时间信息来自示例数据生成记录；普通上传不提供可靠时间戳。"
)
MOCK_DRAFT_NOTICE = (
    "当前为模拟病历草稿：由内置规则从转写文本映射生成，未调用真实大模型。"
    "请医生逐项核对，尤其是未提及信息与来源原文。"
)
