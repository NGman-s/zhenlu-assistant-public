from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ApiError
from app.schemas import ManualTranscriptInput, SessionDetailOut, TranscriptOut
from app.serializers import session_detail_dict, transcript_dict
from app.services.session_service import get_session_or_404
from app.services.workflow import create_manual_transcript, transcribe_session

router = APIRouter(prefix="/sessions", tags=["转写"])


@router.post("/{session_id}/transcript/manual", response_model=SessionDetailOut)
def manual_transcript(
    session_id: str, payload: ManualTranscriptInput, db: Session = Depends(get_db)
) -> dict:
    return session_detail_dict(create_manual_transcript(db, session_id, payload.text))


@router.post("/{session_id}/transcript", response_model=SessionDetailOut)
def transcribe(
    session_id: str, request: Request, db: Session = Depends(get_db)
) -> dict:
    session = transcribe_session(
        db,
        session_id,
        request.app.state.settings,
        request.app.state.asr_provider,
    )
    return session_detail_dict(session)


@router.get("/{session_id}/transcript", response_model=TranscriptOut)
def get_transcript(
    session_id: str, db: Session = Depends(get_db)
) -> dict:
    session = get_session_or_404(db, session_id)
    if session.transcript is None:
        raise ApiError(404, "transcript_not_found", "该会话尚未完成转写。")
    return transcript_dict(session.transcript)
