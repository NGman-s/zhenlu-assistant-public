from __future__ import annotations

from app.config import Settings
from app.providers.base import DraftGenerationProvider, TranscriptionProvider
from app.providers.demo_data import DemoCatalog
from app.providers.fun_asr import FunAsrProvider
from app.providers.mock_asr import MockTranscriptionProvider
from app.providers.mock_draft import MockDraftProvider
from app.providers.qwen_draft import QwenDraftProvider


def build_asr_provider(
    settings: Settings, catalog: DemoCatalog
) -> TranscriptionProvider:
    if settings.asr_provider == "mock":
        return MockTranscriptionProvider(catalog, settings.mock_delay_seconds)
    if settings.asr_provider == "fun-asr":
        return FunAsrProvider.from_settings(settings)
    raise RuntimeError(
        f"不支持的 ASR provider：{settings.asr_provider}。"
        "可选值为 mock 或 fun-asr；接入其他真实 ASR 时请实现 TranscriptionProvider 并在此注册。"
    )


def build_draft_provider(
    settings: Settings, catalog: DemoCatalog
) -> DraftGenerationProvider:
    if settings.draft_provider == "mock":
        return MockDraftProvider(catalog, settings.mock_delay_seconds)
    if settings.draft_provider == "qwen":
        return QwenDraftProvider.from_settings(settings)
    raise RuntimeError(
        f"不支持的草稿 provider：{settings.draft_provider}。"
        "可选值为 mock 或 qwen。"
    )
