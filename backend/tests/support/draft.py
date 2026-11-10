from __future__ import annotations

import time

from app.constants import (
    FIELD_DEFINITIONS,
    UNMENTIONED,
)
from app.providers.base import DraftResult, GeneratedField, TranscriptDocument
from tests.support.demo_data import DemoCatalog
from tests.support import MOCK_DRAFT_NOTICE


class MockDraftProvider:
    name = "mock-rule-based-draft-v1"
    is_mock = True

    def __init__(self, catalog: DemoCatalog, delay_seconds: float = 0.0) -> None:
        self._catalog = catalog
        self._delay_seconds = max(0.0, delay_seconds)

    def generate(self, transcript: TranscriptDocument) -> DraftResult:
        if self._delay_seconds:
            time.sleep(self._delay_seconds)

        texts = tuple(segment.text.strip() for segment in transcript.segments)
        case = self._catalog.find_by_texts(texts)
        notice = MOCK_DRAFT_NOTICE
        if case is None:
            notice += " 当前转写未能匹配内置虚构病例，所有字段均按“未提及”返回。"

        fields: list[GeneratedField] = []
        for key, label in FIELD_DEFINITIONS:
            generated = case.draft.get(key) if case else None
            if generated is None or not generated.value.strip():
                fields.append(
                    GeneratedField(
                        key=key,
                        label=label,
                        value=UNMENTIONED,
                        source_segment_ids=(),
                    )
                )
                continue

            source_ids: list[str] = []
            for index in generated.source_indexes:
                if 0 <= index < len(transcript.segments):
                    segment_id = transcript.segments[index].id
                    if segment_id not in source_ids:
                        source_ids.append(segment_id)

            fields.append(
                GeneratedField(
                    key=key,
                    label=label,
                    value=generated.value,
                    source_segment_ids=tuple(source_ids),
                )
            )

        return DraftResult(
            fields=tuple(fields),
            provider=self.name,
            is_mock=True,
            notice=notice,
        )
