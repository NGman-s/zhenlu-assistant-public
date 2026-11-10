from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import DraftStatus, SessionStatus
from app.errors import ApiError
from app.models import ConsultationSession
from app.schemas import SessionCreate
from app.services.job_state import recover_expired


def create_session(db: Session, payload: SessionCreate) -> ConsultationSession:
    session = ConsultationSession(
        patient_name=payload.patient_name,
        patient_ref=payload.patient_ref,
        status=SessionStatus.AWAITING_AUDIO,
    )
    db.add(session)
    db.commit()
    return get_session_or_404(db, session.id)


def get_session_or_404(db: Session, session_id: str) -> ConsultationSession:
    recover_expired(db, session_id)
    session = db.get(ConsultationSession, session_id)
    if session is None:
        raise ApiError(404, "session_not_found", "会话不存在，请刷新会话列表后重试。")
    return session


def list_sessions(db: Session) -> list[ConsultationSession]:
    recover_expired(db)
    statement = select(ConsultationSession).order_by(
        ConsultationSession.updated_at.desc(), ConsultationSession.created_at.desc()
    )
    return list(db.scalars(statement).all())


def ensure_editable(session: ConsultationSession) -> None:
    if session.status == SessionStatus.CONFIRMED:
        raise ApiError(
            409,
            "session_confirmed",
            "该会话已确认，记录已锁定，不能继续修改或重新生成。",
        )
    if session.draft is not None and session.draft.status == DraftStatus.CONFIRMED:
        raise ApiError(
            409,
            "session_confirmed",
            "该会话已确认，记录已锁定，不能继续修改或重新生成。",
        )
