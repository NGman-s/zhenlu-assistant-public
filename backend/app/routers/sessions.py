from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import SessionCreate, SessionDetailOut, SessionListOut
from app.serializers import session_detail_dict, session_summary_dict
from app.services.session_service import create_session, get_session_or_404, list_sessions

router = APIRouter(prefix="/sessions", tags=["会话"])


@router.post("", response_model=SessionDetailOut, status_code=status.HTTP_201_CREATED)
def create(payload: SessionCreate, db: Session = Depends(get_db)) -> dict:
    session = create_session(db, payload)
    return session_detail_dict(session)


@router.get("", response_model=SessionListOut)
def list_all(db: Session = Depends(get_db)) -> dict:
    sessions = list_sessions(db)
    return {"items": [session_summary_dict(session) for session in sessions]}


@router.get("/{session_id}", response_model=SessionDetailOut)
def detail(session_id: str, db: Session = Depends(get_db)) -> dict:
    session = get_session_or_404(db, session_id)
    return session_detail_dict(session)
