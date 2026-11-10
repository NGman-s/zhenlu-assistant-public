from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ZHENLU_",
        env_file=str(PROJECT_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "诊录助手 API"
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'backend' / 'data' / 'zhenlu.db').as_posix()}"
    upload_dir: Path = PROJECT_ROOT / "backend" / "data" / "uploads"
    sample_data_dir: Path = PROJECT_ROOT / "sample-data"
    max_audio_mb: int = 50
    asr_provider: str = "mock"
    draft_provider: str = "mock"
    fun_asr_base_url: str = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
    fun_asr_model: str = "fun-asr-realtime-2026-02-28"
    fun_asr_api_key: SecretStr = SecretStr("")
    fun_asr_workspace: str = ""
    fun_asr_timeout_seconds: float = 300.0
    fun_asr_sample_rate: int = 16000
    fun_asr_language_hints: str = "zh"
    fun_asr_chunk_interval_seconds: float = 0.1
    qwen_base_url: str = ""
    qwen_model: str = "qwen3.7-plus"
    qwen_api_key: SecretStr = SecretStr("")
    qwen_timeout_seconds: float = 45.0
    qwen_attempt_timeout_seconds: float = Field(default=20.0, ge=1, le=600)
    qwen_max_retries: int = Field(default=1, ge=0, le=1)
    qwen_max_tokens: int = Field(default=2000, ge=256, le=8000)
    # 留空时不估算费用；单价须与实际模型和地域对应。
    qwen_input_price_per_million: float | None = Field(default=None, ge=0)
    qwen_output_price_per_million: float | None = Field(default=None, ge=0)
    assistant_provider: str = "mock"
    dialogue_provider: str = "rules"
    job_worker_enabled: bool = True
    job_poll_interval_seconds: float = Field(default=0.5, ge=0.05, le=30)
    job_lease_seconds: int = Field(default=600, ge=30, le=7200)
    mock_delay_seconds: float = 0.35
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    timezone_offset_hours: int = 8
    # 仅由本地连接程序设置；普通开发模式不启用设备流程。
    device_state_file: Path | None = None

    @property
    def fun_asr_language_hint_list(self) -> list[str]:
        return [hint.strip() for hint in self.fun_asr_language_hints.split(",") if hint.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_audio_bytes(self) -> int:
        return self.max_audio_mb * 1024 * 1024
