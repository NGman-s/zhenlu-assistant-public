from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.constants import FIELD_KEYS


@dataclass(frozen=True)
class DemoLine:
    speaker: str
    text: str
    start_ms: int | None
    end_ms: int | None


@dataclass(frozen=True)
class DemoDraftField:
    value: str
    source_indexes: tuple[int, ...]


@dataclass(frozen=True)
class DemoCase:
    key: str
    title: str
    description: str
    audio_filename: str
    dialogue: tuple[DemoLine, ...]
    draft: dict[str, DemoDraftField]

    @property
    def texts(self) -> tuple[str, ...]:
        return tuple(line.text for line in self.dialogue)


class DemoCatalog:
    """读取 sample-data 下的虚构病例，供 mock 服务与演示音频接口使用。"""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._cases: dict[str, DemoCase] | None = None

    def _load(self) -> dict[str, DemoCase]:
        if self._cases is not None:
            return self._cases
        if not self.directory.exists():
            raise RuntimeError(f"模拟病例子目录不存在：{self.directory}")
        cases: dict[str, DemoCase] = {}
        for path in sorted(self.directory.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            key = str(raw["key"])
            draft: dict[str, DemoDraftField] = {}
            for field_key, item in raw.get("draft", {}).items():
                if field_key not in FIELD_KEYS:
                    continue
                indexes = tuple(int(i) for i in item.get("source_indexes", []))
                draft[field_key] = DemoDraftField(
                    value=str(item.get("value", "")),
                    source_indexes=indexes,
                )
            dialogue = tuple(
                DemoLine(
                    speaker=str(line["speaker"]),
                    text=str(line["text"]),
                    start_ms=line.get("start_ms"),
                    end_ms=line.get("end_ms"),
                )
                for line in raw["dialogue"]
            )
            cases[key] = DemoCase(
                key=key,
                title=str(raw["title"]),
                description=str(raw.get("description", "")),
                audio_filename=str(raw["audio_file"]),
                dialogue=dialogue,
                draft=draft,
            )
        if not cases:
            raise RuntimeError(f"未在 {self.directory} 找到模拟病例 JSON")
        self._cases = cases
        return cases

    def list(self) -> list[DemoCase]:
        return sorted(self._load().values(), key=lambda case: case.key)

    def get(self, key: str) -> DemoCase | None:
        return self._load().get(key)

    def match_audio_filename(self, filename: str) -> DemoCase | None:
        normalized = filename.strip().lower()
        for case in self.list():
            if case.audio_filename.lower() == normalized:
                return case
            if case.key.lower() in normalized:
                return case
        return None

    def find_by_texts(self, texts: tuple[str, ...]) -> DemoCase | None:
        for case in self.list():
            if case.texts == texts:
                return case
        return None
