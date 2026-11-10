from __future__ import annotations

import time
import hashlib
from pathlib import Path

from tests.support import MOCK_ASR_NOTICE
from app.providers.base import AsrResult, AsrSegment
from tests.support.demo_data import DemoCatalog


class MockTranscriptionProvider:
    name = "mock-consultation-asr-v1"
    is_mock = True

    def __init__(self, catalog: DemoCatalog, delay_seconds: float = 0.0) -> None:
        self._catalog = catalog
        self._delay_seconds = max(0.0, delay_seconds)

    def transcribe(self, audio_path: Path, original_filename: str) -> AsrResult:
        if self._delay_seconds:
            time.sleep(self._delay_seconds)

        matched_case = self._catalog.match_audio_filename(original_filename)
        if matched_case is not None:
            root = self._catalog.directory.resolve()
            sample_path = (root / matched_case.audio_filename).resolve()
            if not sample_path.is_relative_to(root) or not sample_path.is_file():
                matched_case = None
            else:
                def digest(path: Path) -> bytes:
                    with path.open("rb") as handle:
                        return hashlib.file_digest(handle, "sha256").digest()

                if digest(audio_path) != digest(sample_path):
                    matched_case = None
        case = matched_case or self._catalog.list()[0]
        notice = MOCK_ASR_NOTICE
        if matched_case is None:
            notice += (
                " 上传文件未匹配内置示例音频，已使用默认虚构病例，"
                "所有句子均不提供时间戳。"
            )

        segments = tuple(
            AsrSegment(
                speaker=line.speaker,
                text=line.text,
                start_ms=line.start_ms if matched_case else None,
                end_ms=line.end_ms if matched_case else None,
            )
            for line in case.dialogue
        )
        return AsrResult(
            segments=segments,
            provider=self.name,
            is_mock=True,
            language="zh-CN",
            notice=notice,
            metadata={
                "case_key": case.key,
                "matched_sample_audio": matched_case is not None,
            },
        )
