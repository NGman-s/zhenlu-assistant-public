from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
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
    qwen_base_url: str = ""
    qwen_model: str = "qwen3.7-plus"
    qwen_api_key: SecretStr = SecretStr("")
    qwen_timeout_seconds: float = 120.0
    mock_delay_seconds: float = 0.35
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    timezone_offset_hours: int = 8
    # 仅由本地连接程序设置；普通开发模式不启用设备流程。
    device_state_file: Path | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_audio_bytes(self) -> int:
        return self.max_audio_mb * 1024 * 1024
