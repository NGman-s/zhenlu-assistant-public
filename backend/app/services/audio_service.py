from __future__ import annotations

import hashlib
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
from app.services.job_state import ensure_no_active_job
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
    expected_sha256: str | None = None,
) -> ConsultationSession:
    session = get_session_or_404(db, session_id)
    existing = session.audio_file
    retry = bool(existing and expected_sha256 and existing.sha256 == expected_sha256)
    if existing and not retry:
        raise ApiError(409, "audio_exists", "该会话已有音频。重传需提供与原文件一致的 X-Audio-SHA256。")
    if not retry:
        ensure_editable(session)
        if session.transcript is not None or session.draft is not None:
            raise ApiError(409, "session_has_processing", "该会话已有处理结果，不能替换音频。")
    display_name = _safe_display_name(upload.filename)
    suffix = Path(display_name).suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        supported = "、".join(sorted(ext.lstrip(".") for ext in ALLOWED_AUDIO_EXTENSIONS))
        raise ApiError(415, "unsupported_audio_format", f"不支持该音频格式（{suffix or '无扩展名'}）。支持：{supported}。")
    if upload.size is not None and upload.size > settings.max_audio_bytes:
        raise ApiError(413, "audio_too_large", f"音频超过 {settings.max_audio_mb} MB 限制，请压缩后重试。")
    # Do not keep a DB read transaction open while receiving a potentially slow upload.
    db.commit()
    audio_id = new_id()
    relative_dir = Path(session_id)
    target_dir = settings.upload_dir / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = target_dir / f"{audio_id}{suffix}"
    temp_path = target_dir / f"{audio_id}{suffix}.part"
    total_size = 0
    digest = hashlib.sha256()
    try:
        with temp_path.open("wb") as handle:
            while chunk := await upload.read(CHUNK_SIZE):
                total_size += len(chunk)
                if total_size > settings.max_audio_bytes:
                    raise ApiError(413, "audio_too_large", f"音频超过 {settings.max_audio_mb} MB 限制，请压缩后重试。")
                digest.update(chunk)
                handle.write(chunk)
        if total_size == 0:
            raise ApiError(400, "empty_audio", "上传的音频文件为空。")
        checksum = digest.hexdigest()
        if expected_sha256 and checksum != expected_sha256:
            raise ApiError(400, "audio_checksum_mismatch", "音频校验值不匹配，请检查录音文件后重新上传。")
        # Re-read after the transfer, so a simultaneous transcript/upload cannot be overwritten.
        db.expire_all()
        session = get_session_or_404(db, session_id)
        if session.audio_file and expected_sha256 == session.audio_file.sha256:
            resolve_audio_path(settings, session.audio_file)
            temp_path.unlink(missing_ok=True)
            return session
        ensure_no_active_job(db, session_id)
        db.expire_all()
        session = get_session_or_404(db, session_id)
        if session.audio_file:
            if expected_sha256 and session.audio_file.sha256 == expected_sha256:
                resolve_audio_path(settings, session.audio_file)
                temp_path.unlink(missing_ok=True)
                db.commit()
                return session
            raise ApiError(409, "audio_exists", "该会话已有音频，请刷新后重试。")
        ensure_editable(session)
        if session.transcript or session.draft:
            raise ApiError(409, "session_has_processing", "该会话已有处理结果，不能替换音频。")
        temp_path.replace(final_path)
        session.audio_file = AudioFile(
            id=audio_id, session_id=session.id, original_filename=display_name,
            stored_relpath=(relative_dir / final_path.name).as_posix(),
            content_type=ALLOWED_AUDIO_EXTENSIONS[suffix], size_bytes=total_size, sha256=checksum,
            duration_ms=_read_wav_duration_ms(final_path) if suffix == ".wav" else None,
        )
        session.status = SessionStatus.AUDIO_READY
        session.error_message = None
        session.updated_at = utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        temp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        if isinstance(exc, IntegrityError):
            raise ApiError(409, "audio_exists", "该会话已有音频，请刷新后重试。") from None
        raise
    return get_session_or_404(db, session_id)


def resolve_audio_path(settings: Settings, audio: AudioFile) -> Path:
    root = settings.upload_dir.resolve()
    path = (root / audio.stored_relpath).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ApiError(404, "audio_file_missing", "音频文件不存在，请重新上传。")
    return path
