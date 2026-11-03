from __future__ import annotations

import logging
import wave
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.constants import ALLOWED_AUDIO_EXTENSIONS, SessionStatus
from app.errors import ApiError
from app.models import AudioFile, ConsultationSession, new_id, utcnow
from app.services.session_service import ensure_editable, get_session_or_404

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024


def _safe_display_name(filename: str | None) -> str:
    name = (filename or "").replace("\\", "/").split("/")[-1].strip()
    name = "".join(char for char in name if char.isprintable())
    return name[:180] or "未命名音频"


def _read_wav_duration_ms(path: Path) -> int | None:
    try:
        with wave.open(str(path), "rb") as handle:
            if handle.getframerate() <= 0:
                return None
            return round(handle.getnframes() * 1000 / handle.getframerate())
    except (wave.Error, EOFError, OSError):
        return None


async def store_audio(
    db: Session,
    session_id: str,
    upload: UploadFile,
    settings: Settings,
) -> ConsultationSession:
    session = get_session_or_404(db, session_id)
    ensure_editable(session)
    if session.audio_file is not None:
        raise ApiError(
            409,
            "audio_exists",
            "该会话已有音频。第一阶段每个会话仅支持一段音频，请新建会话。",
        )
    if session.transcript is not None or session.draft is not None:
        raise ApiError(409, "session_has_processing", "该会话已有处理结果，不能替换音频。")

    display_name = _safe_display_name(upload.filename)
    suffix = Path(display_name).suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        supported = "、".join(sorted(ext.lstrip(".") for ext in ALLOWED_AUDIO_EXTENSIONS))
        raise ApiError(
            415,
            "unsupported_audio_format",
            f"不支持该音频格式（{suffix or '无扩展名'}）。支持：{supported}。",
        )

    if upload.size is not None and upload.size > settings.max_audio_bytes:
        raise ApiError(
            413,
            "audio_too_large",
            f"音频超过 {settings.max_audio_mb} MB 限制，请压缩后重试。",
        )

    audio_id = new_id()
    relative_dir = Path(session.id)
    target_dir = settings.upload_dir / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = target_dir / f"{audio_id}{suffix}"
    temp_path = target_dir / f"{audio_id}{suffix}.part"

    total_size = 0
    try:
        with temp_path.open("wb") as handle:
            while chunk := await upload.read(CHUNK_SIZE):
                total_size += len(chunk)
                if total_size > settings.max_audio_bytes:
                    raise ApiError(
                        413,
                        "audio_too_large",
                        f"音频超过 {settings.max_audio_mb} MB 限制，请压缩后重试。",
                    )
                handle.write(chunk)
        if total_size == 0:
            raise ApiError(400, "empty_audio", "上传的音频文件为空。")
        temp_path.replace(final_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise

    duration_ms = _read_wav_duration_ms(final_path) if suffix == ".wav" else None
    stored_relpath = (relative_dir / final_path.name).as_posix()
    audio = AudioFile(
        id=audio_id,
        session_id=session.id,
        original_filename=display_name,
        stored_relpath=stored_relpath,
        content_type=ALLOWED_AUDIO_EXTENSIONS[suffix],
        size_bytes=total_size,
        duration_ms=duration_ms,
    )
    session.audio_file = audio
    session.status = SessionStatus.AUDIO_READY
    session.error_message = None
    session.updated_at = utcnow()

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        final_path.unlink(missing_ok=True)
        logger.warning("Concurrent audio upload rejected for session %s", session.id)
        raise ApiError(409, "audio_exists", "该会话已有音频，请刷新后重试。") from exc

    return get_session_or_404(db, session.id)


def resolve_audio_path(settings: Settings, audio: AudioFile) -> Path:
    root = settings.upload_dir.resolve()
    path = (root / audio.stored_relpath).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ApiError(404, "audio_file_missing", "音频文件不存在，请重新上传。")
    return path
