from __future__ import annotations

from app.config import Settings
from app.providers.base import DraftGenerationProvider, TranscriptionProvider
from app.providers.fun_asr import FunAsrProvider
from app.providers.qwen_draft import QwenDraftProvider


def build_asr_provider(settings: Settings) -> TranscriptionProvider:
    return FunAsrProvider.from_settings(settings)


def build_draft_provider(settings: Settings) -> DraftGenerationProvider:
    return QwenDraftProvider.from_settings(settings)
