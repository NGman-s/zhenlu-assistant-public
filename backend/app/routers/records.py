from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ConfirmedRecordOut, RecordTextOut, RevisionRequest, SessionDetailOut
from app.serializers import confirmed_record_dict, iso_utc, session_detail_dict
from app.services.workflow import confirm_draft, get_confirmed_record

router = APIRouter(prefix="/sessions", tags=["确认与复制"])


@router.post("/{session_id}/confirm", response_model=SessionDetailOut)
def confirm(
    session_id: str,
    payload: RevisionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    session = confirm_draft(
        db,
        session_id,
        request.app.state.settings,
        payload.expected_revision,
    )
    return session_detail_dict(session)


@router.get("/{session_id}/record", response_model=ConfirmedRecordOut)
def get_record(session_id: str, db: Session = Depends(get_db)) -> dict:
    record = get_confirmed_record(db, session_id)
    return confirmed_record_dict(record)


@router.get("/{session_id}/record/text", response_model=RecordTextOut)
def get_record_text(session_id: str, db: Session = Depends(get_db)) -> dict:
    record = get_confirmed_record(db, session_id)
    return {
        "version": record.version,
        "confirmed_at": iso_utc(record.confirmed_at),
        "text": record.text,
    }
