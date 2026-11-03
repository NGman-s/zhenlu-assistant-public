from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class TranscriptSegmentData:
    id: str
    seq: int
    speaker: str
    text: str
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass(frozen=True)
class TranscriptDocument:
    id: str
    segments: tuple[TranscriptSegmentData, ...]


@dataclass(frozen=True)
class AsrSegment:
    speaker: str
    text: str
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass(frozen=True)
class AsrResult:
    segments: tuple[AsrSegment, ...]
    provider: str
    is_mock: bool
    language: str
    notice: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GeneratedField:
    key: str
    label: str
    value: str
    source_segment_ids: tuple[str, ...]


@dataclass(frozen=True)
class DraftResult:
    fields: tuple[GeneratedField, ...]
    provider: str
    is_mock: bool
    notice: str


class TranscriptionProvider(Protocol):
    """真实 ASR 实现只需满足此协议。

    契约：
    - 不得伪造 start_ms/end_ms；无法可靠定位时返回 None。
    - 返回逐句文本，供服务端建立字段来源关联。
    - is_mock 必须如实标识结果来源。
    """

    name: str
    is_mock: bool

    def transcribe(
        self, audio_path: Path, original_filename: str
    ) -> AsrResult: ...


class DraftGenerationProvider(Protocol):
    """真实大模型草稿实现只需满足此协议。

    契约：
    - 返回主诉、现病史、既往史、用药史、过敏史五个字段。
    - source_segment_ids 必须引用转写文档中真实存在的句子。
    - 对话未提及的字段返回“未提及”，不得推断为“无”。
    """

    name: str
    is_mock: bool

    def generate(self, transcript: TranscriptDocument) -> DraftResult: ...
