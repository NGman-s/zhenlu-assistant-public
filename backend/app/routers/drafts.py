from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ApiError
from app.schemas import DraftOut, DraftUpdate, RevisionRequest, SessionDetailOut
from app.serializers import draft_dict, session_detail_dict
from app.services.session_service import get_session_or_404
from app.services.workflow import generate_draft, regenerate_draft, update_draft

router = APIRouter(prefix="/sessions", tags=["病历草稿"])


@router.post("/{session_id}/draft", response_model=SessionDetailOut)
def generate(
    session_id: str, request: Request, db: Session = Depends(get_db)
) -> dict:
    session = generate_draft(
        db,
        session_id,
        request.app.state.draft_provider,
    )
    return session_detail_dict(session)


@router.get("/{session_id}/draft", response_model=DraftOut)
def get_draft(session_id: str, db: Session = Depends(get_db)) -> dict:
    session = get_session_or_404(db, session_id)
    if session.draft is None:
        raise ApiError(404, "draft_not_found", "该会话尚未生成病历草稿。")
    return draft_dict(session.draft, session.transcript)


@router.patch("/{session_id}/draft", response_model=SessionDetailOut)
def save_edits(
    session_id: str,
    payload: DraftUpdate,
    db: Session = Depends(get_db),
) -> dict:
    session = update_draft(db, session_id, payload)
    return session_detail_dict(session)


@router.post("/{session_id}/draft/regenerate", response_model=SessionDetailOut)
def regenerate(
    session_id: str,
    payload: RevisionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    session = regenerate_draft(
        db,
        session_id,
        payload.expected_revision,
        request.app.state.draft_provider,
    )
    return session_detail_dict(session)
