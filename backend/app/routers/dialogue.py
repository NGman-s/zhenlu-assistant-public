from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ApiError
from app.routers.assistant import IdempotencyKey
from app.serializers import dialogue_dict
from app.services.jobs import execute_inline
from app.services.session_service import get_session_or_404

router = APIRouter(prefix="/sessions", tags=["对话角色整理"])


@router.post("/{session_id}/dialogue")
def structure(session_id: str, request: Request, idempotency_key: IdempotencyKey = None, db: Session = Depends(get_db)) -> dict:
    execute_inline(db, request.app, session_id, "structure", request_key=idempotency_key)
    return dialogue_dict(get_session_or_404(db, session_id).dialogue)


@router.get("/{session_id}/dialogue")
def read_structure(session_id: str, db: Session = Depends(get_db)) -> dict:
    session = get_session_or_404(db, session_id)
    if session.dialogue is None:
        raise ApiError(404, "dialogue_not_found", "该会话尚未保存角色整理结果。")
    return dialogue_dict(session.dialogue)
