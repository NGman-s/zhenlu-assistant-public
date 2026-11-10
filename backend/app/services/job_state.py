"""Lease fencing shared by workers and artifact writers; no provider imports."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.constants import SessionStatus
from app.errors import ApiError
from app.models import ConsultationSession, ProcessingJob, utcnow


def finish_job(db: Session, job_id: str | None, result: dict, metrics: dict | None = None) -> None:
    """Fence first; commit the result and this state in the SAME DB transaction."""
    if job_id is None:
        return
    now = utcnow()
    changed = db.execute(update(ProcessingJob).where(
        ProcessingJob.id == job_id, ProcessingJob.status == "running",
        ProcessingJob.active_session_id.is_not(None), ProcessingJob.lease_expires_at > now,
    ).values(
        status="succeeded", active_session_id=None, finished_at=now, result=result, metrics=metrics or {},
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.rollback()
        raise ApiError(409, "job_expired", "处理任务已中断或失效，迟到结果未保存，请查看任务状态后重试。")


def fail_job(db: Session, job_id: str, error: ApiError, metrics: dict | None = None) -> None:
    db.rollback()
    job = db.get(ProcessingJob, job_id)
    if job is None:
        return
    now = utcnow()
    changed = db.execute(update(ProcessingJob).where(
        ProcessingJob.id == job_id, ProcessingJob.status == "running",
        ProcessingJob.active_session_id.is_not(None), ProcessingJob.lease_expires_at > now,
    ).values(
        status="failed", active_session_id=None, finished_at=now,
        error_code=error.code, error_message=error.message, error_status=error.status_code,
        metrics=metrics or {},
    ).execution_options(synchronize_session=False))
    if changed.rowcount == 1 and job.operation != "ask":
        _restore_session(db, job.session_id, error.message)
    db.commit()
    recover_expired(db, job.session_id)


def _restore_session(db: Session, session_id: str, message: str) -> None:
    session = db.get(ConsultationSession, session_id, populate_existing=True)
    if session is None or session.confirmed_version:
        return
    session.status = SessionStatus.DRAFT_READY if session.draft else SessionStatus.FAILED
    session.error_message = message
    session.updated_at = utcnow()


def recover_expired(db: Session, session_id: str | None = None) -> int:
    now = utcnow()
    query = select(ProcessingJob).where(
        ProcessingJob.active_session_id.is_not(None), ProcessingJob.lease_expires_at <= now,
        ProcessingJob.status.in_(["queued", "running"]),
    )
    if session_id:
        query = query.where(ProcessingJob.session_id == session_id)
    jobs = list(db.scalars(query))
    recovered = 0
    for job in jobs:
        message = "上次处理已中断或超时，原始资料和已有病历已保留，请重新提交任务。"
        changed = db.execute(update(ProcessingJob).where(
            ProcessingJob.id == job.id, ProcessingJob.active_session_id.is_not(None),
            ProcessingJob.status.in_(["queued", "running"]), ProcessingJob.lease_expires_at <= now,
        ).values(
            status="interrupted", active_session_id=None, finished_at=now,
            error_code="job_interrupted", error_message=message, error_status=409,
        ).execution_options(synchronize_session=False))
        if changed.rowcount == 1:
            recovered += 1
            if job.operation != "ask":
                _restore_session(db, job.session_id, message)
    if jobs:
        db.commit()
        db.expire_all()
    return recovered


def recover_legacy_states(db: Session) -> None:
    """Old releases stored only a 'processing' label, with no recoverable job."""
    ids = list(db.scalars(select(ConsultationSession.id).where(
        ConsultationSession.status.in_([SessionStatus.TRANSCRIBING, SessionStatus.GENERATING_DRAFT]),
        ~ConsultationSession.id.in_(select(ProcessingJob.active_session_id).where(ProcessingJob.active_session_id.is_not(None))),
    )))
    for sid in ids:
        _restore_session(db, sid, "旧版未完成的处理已恢复为可重试状态，已有资料已保留。")
    db.commit()


def ensure_no_active_job(db: Session, session_id: str) -> None:
    recover_expired(db, session_id)
    # Acquire the session write lock before checking the slot. Submitters lock it too.
    db.execute(update(ConsultationSession).where(ConsultationSession.id == session_id).values(
        updated_at=ConsultationSession.updated_at,
    ).execution_options(synchronize_session=False))
    if db.scalar(select(ProcessingJob.id).where(ProcessingJob.active_session_id == session_id)):
        raise ApiError(409, "operation_in_progress", "该会话已有处理任务，请等待完成或查看任务状态。")
