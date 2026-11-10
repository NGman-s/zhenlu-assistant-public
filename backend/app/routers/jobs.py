from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ProcessingJob
from app.schemas import JobCreate
from app.services.job_state import recover_expired
from app.services.jobs import get_job, job_dict, submit_job
from app.services.session_service import get_session_or_404

router = APIRouter(prefix="/sessions", tags=["处理任务"])


@router.post("/{session_id}/jobs", status_code=202)
def create_job(session_id: str, payload: JobCreate, request: Request, db: Session = Depends(get_db)) -> dict:
    return job_dict(submit_job(db, request.app, session_id, payload.operation, payload.operation_payload(), payload.request_id, background=True))


@router.get("/{session_id}/jobs")
def list_jobs(session_id: str, limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)) -> dict:
    get_session_or_404(db, session_id)
    recover_expired(db, session_id)
    jobs = db.scalars(select(ProcessingJob).where(ProcessingJob.session_id == session_id).order_by(ProcessingJob.created_at.desc(), ProcessingJob.id).offset(offset).limit(limit))
    return {"items": [job_dict(job) for job in jobs]}


@router.get("/{session_id}/jobs/{job_id}")
def job_detail(session_id: str, job_id: str, db: Session = Depends(get_db)) -> dict:
    return job_dict(get_job(db, session_id, job_id))


@router.get("/{session_id}/usage")
def session_usage(session_id: str, db: Session = Depends(get_db)) -> dict:
    get_session_or_404(db, session_id)
    jobs = list(db.scalars(select(ProcessingJob).where(ProcessingJob.session_id == session_id)))
    tokens = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "reasoning_tokens": 0}
    known_cost = 0.0
    unknown_cost_jobs = 0
    asr_seconds = 0
    statuses: dict[str, int] = {}
    for job in jobs:
        statuses[job.status] = statuses.get(job.status, 0) + 1
        metrics = job.metrics or {}
        attempts = metrics.get("attempts") or [{"usage": metrics.get("usage", {})}]
        for attempt in attempts:
            usage = attempt.get("usage", {})
            for key in tokens:
                value = usage.get(key)
                if type(value) is int and value >= 0:
                    tokens[key] += value
        estimate = metrics.get("estimated_cost_cny")
        if isinstance(estimate, (int, float)):
            known_cost += estimate
        if metrics.get("cost_status") not in ("estimated", "not_billed"):
            unknown_cost_jobs += 1
        seconds = metrics.get("billed_duration_seconds")
        if type(seconds) is int and seconds >= 0:
            asr_seconds += seconds
    return {"job_count": len(jobs), "jobs_by_status": statuses, "reported_tokens": tokens,
            "reported_asr_seconds": asr_seconds, "known_estimated_cost_cny": round(known_cost, 8),
            "jobs_with_unknown_or_partial_cost": unknown_cost_jobs,
            "notice": "仅汇总供应商已返回用量；估算不等于账单，失败和重试可能产生尚未报告的费用。"}
