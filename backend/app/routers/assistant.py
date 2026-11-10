from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ApiError
from app.models import AssistantTurn
from app.schemas import QuestionInput
from app.services.assistant_service import turn_dict
from app.services.jobs import execute_inline
from app.services.session_service import get_session_or_404

router = APIRouter(prefix="/sessions", tags=["会话助手"])
IdempotencyKey = Annotated[str | None, Header(max_length=100, min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")]


@router.post("/{session_id}/assistant/questions")
def ask(session_id: str, payload: QuestionInput, request: Request, idempotency_key: IdempotencyKey = None, db: Session = Depends(get_db)) -> dict:
    job = execute_inline(db, request.app, session_id, "ask", {"question": payload.question}, idempotency_key)
    turn = db.get(AssistantTurn, job.result["assistant_turn_id"])
    return turn_dict(turn)


@router.get("/{session_id}/assistant/questions")
def history(session_id: str, limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)) -> dict:
    get_session_or_404(db, session_id)
    turns = db.scalars(select(AssistantTurn).where(AssistantTurn.session_id == session_id).order_by(AssistantTurn.created_at.desc(), AssistantTurn.id).offset(offset).limit(limit))
    return {"items": [turn_dict(turn) for turn in turns]}


@router.get("/{session_id}/assistant/questions/{turn_id}")
def answer_detail(session_id: str, turn_id: str, db: Session = Depends(get_db)) -> dict:
    get_session_or_404(db, session_id)
    turn = db.scalar(select(AssistantTurn).where(AssistantTurn.id == turn_id, AssistantTurn.session_id == session_id))
    if turn is None:
        raise ApiError(404, "answer_not_found", "当前会话中不存在该回答。")
    return turn_dict(turn)
