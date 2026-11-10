from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ApiError
from app.schemas import SessionDetailOut
from app.serializers import session_detail_dict
from app.services.audio_service import resolve_audio_path, store_audio
from app.services.session_service import get_session_or_404

router = APIRouter(prefix="/sessions", tags=["音频"])


@router.post(
    "/{session_id}/audio",
    response_model=SessionDetailOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_audio(
    session_id: str,
    request: Request,
    x_audio_sha256: Annotated[str | None, Header(pattern=r"^[a-f0-9]{64}$")] = None,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    session = await store_audio(db, session_id, file, request.app.state.settings, x_audio_sha256)
    return session_detail_dict(session)


@router.get("/{session_id}/audio", response_class=FileResponse)
def stream_audio(
    session_id: str, request: Request, db: Session = Depends(get_db)
) -> FileResponse:
    session = get_session_or_404(db, session_id)
    if session.audio_file is None:
        raise ApiError(404, "audio_not_found", "该会话尚未上传音频。")
    path = resolve_audio_path(request.app.state.settings, session.audio_file)
    return FileResponse(
        path,
        media_type=session.audio_file.content_type or "application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )
