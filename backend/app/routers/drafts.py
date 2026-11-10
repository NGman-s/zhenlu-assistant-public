from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ApiError
from app.schemas import DraftOut, DraftUpdate, RevisionRequest, SessionDetailOut
from app.serializers import draft_dict, session_detail_dict
from app.services.session_service import get_session_or_404
from app.services.workflow import update_draft
from app.services.jobs import execute_inline
from app.routers.assistant import IdempotencyKey

router = APIRouter(prefix="/sessions", tags=["病历草稿"])


@router.post("/{session_id}/draft", response_model=SessionDetailOut)
def generate(
    session_id: str, request: Request, idempotency_key: IdempotencyKey = None, db: Session = Depends(get_db)
) -> dict:
    execute_inline(db, request.app, session_id, "generate", request_key=idempotency_key)
    session = get_session_or_404(db, session_id)
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
    idempotency_key: IdempotencyKey = None,
    db: Session = Depends(get_db),
) -> dict:
    execute_inline(db, request.app, session_id, "regenerate", {"expected_revision": payload.expected_revision}, idempotency_key)
    session = get_session_or_404(db, session_id)
    return session_detail_dict(session)
