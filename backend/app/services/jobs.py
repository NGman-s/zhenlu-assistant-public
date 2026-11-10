from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from threading import Event, Thread
from collections.abc import Callable

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.constants import SessionStatus
from app.errors import ApiError
from app.models import ConsultationSession, ProcessingJob, new_id, utcnow
from app.serializers import iso_utc
from app.services.assistant_service import ask_session, assistant_context, context_hash
from app.services.job_state import fail_job, recover_expired
from app.services.session_service import ensure_editable, get_session_or_404
from app.services.workflow import generate_draft, regenerate_draft, transcribe_session
from app.services.dialogue_service import structure_session

logger = logging.getLogger(__name__)


def provider_for(app, operation: str):
    if operation == "transcribe":
        return app.state.asr_provider
    if operation == "ask":
        return app.state.assistant_provider
    if operation == "structure":
        return app.state.dialogue_provider
    return app.state.draft_provider


def validate_operation(session, operation: str, payload: dict, provider) -> None:
    if operation == "ask":
        assistant_context(session)
        return
    ensure_editable(session)
    if operation == "transcribe":
        if session.audio_file is None:
            raise ApiError(409, "audio_required", "请先上传音频，再开始转写。")
        if session.transcript:
            raise ApiError(409, "transcript_exists", "该会话已完成转写，不能重复执行。")
    elif operation in ("generate", "structure"):
        if session.transcript is None:
            raise ApiError(409, "transcript_required", "请先录入问诊内容或完成转写，再生成病历草稿。")
        if session.draft:
            raise ApiError(409, "draft_exists", "该会话已生成草稿，请使用重新生成。")
        if operation == "structure" and session.dialogue:
            raise ApiError(409, "dialogue_exists", "角色整理已经保存。")
    elif operation == "regenerate":
        if session.draft is None or session.transcript is None:
            raise ApiError(409, "draft_required", "该会话还没有可重新生成的病历草稿。")
        if session.draft.provider == "manual-template" and provider.is_mock:
            raise ApiError(409, "manual_draft", "手动填写的模板不支持重新生成。")
        if session.draft.revision != payload["expected_revision"]:
            raise ApiError(409, "revision_conflict", "草稿已更新，请刷新后再重新生成。")
    else:
        raise ApiError(422, "invalid_operation", "未知处理操作。")


def input_hash(session, operation: str, payload: dict) -> str:
    if operation == "ask":
        return context_hash({"question": payload["question"], **assistant_context(session)})
    data = {"operation": operation, "payload": payload}
    if operation == "transcribe":
        audio = session.audio_file
        data["audio"] = [audio.id, audio.size_bytes, audio.stored_relpath] if audio else None
    else:
        t = session.transcript
        data["transcript"] = {"id": t.id, "segments": [[s.id, s.speaker, s.text] for s in t.segments]} if t else None
        data["revision"] = session.draft.revision if session.draft else None
        data["dialogue_id"] = session.dialogue.id if session.dialogue else None
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _existing_request(db: Session, session_id: str, key: str | None, operation: str, payload: dict):
    if key is None:
        return None
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.session_id == session_id, ProcessingJob.request_key == key))
    if job and (job.operation != operation or job.payload != payload):
        raise ApiError(409, "idempotency_conflict", "该请求编号已用于不同操作，请使用新的请求编号。")
    return job


def submit_job(db: Session, app, session_id: str, operation: str, payload: dict,
               request_key: str | None, *, background: bool) -> ProcessingJob:
    get_session_or_404(db, session_id)
    recover_expired(db, session_id)
    existing = _existing_request(db, session_id, request_key, operation, payload)
    if existing:
        return existing
    db.execute(update(ConsultationSession).where(ConsultationSession.id == session_id).values(
        updated_at=ConsultationSession.updated_at,
    ).execution_options(synchronize_session=False))
    db.expire_all()
    existing = _existing_request(db, session_id, request_key, operation, payload)
    if existing:
        return existing
    session = get_session_or_404(db, session_id)
    provider = provider_for(app, operation)
    validate_operation(session, operation, payload, provider)
    if db.scalar(select(ProcessingJob.id).where(ProcessingJob.active_session_id == session_id)):
        raise ApiError(409, "operation_in_progress", "该会话已有处理任务，请等待完成或查看任务状态。")
    job = ProcessingJob(
        id=new_id(), session_id=session_id, active_session_id=session_id,
        operation=operation, provider=provider.name, payload=payload, request_key=request_key,
        dispatch_mode="background" if background else "inline", status="queued",
        input_hash=input_hash(session, operation, payload),
        base_revision=session.draft.revision if session.draft else None,
        lease_expires_at=None if background else utcnow() + timedelta(seconds=60),
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _existing_request(db, session_id, request_key, operation, payload)
        if existing:
            return existing
        raise ApiError(409, "operation_in_progress", "该会话已有处理任务，请查看任务状态。") from None
    return job


def get_job(db: Session, session_id: str, job_id: str) -> ProcessingJob:
    get_session_or_404(db, session_id)
    recover_expired(db, session_id)
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id, ProcessingJob.session_id == session_id).execution_options(populate_existing=True))
    if job is None:
        raise ApiError(404, "job_not_found", "当前会话中不存在该任务。")
    return job


def run_job(app, job_id: str, *, propagate: bool = False, on_claimed: Callable[[], None] | None = None) -> None:
    with app.state.db.session_factory() as db:
        now = utcnow()
        settings = app.state.settings
        lease = max(settings.job_lease_seconds, int(max(settings.qwen_timeout_seconds, settings.fun_asr_timeout_seconds)) + 30)
        claimed = db.execute(update(ProcessingJob).where(
            ProcessingJob.id == job_id, ProcessingJob.status == "queued", ProcessingJob.active_session_id.is_not(None),
        ).values(status="running", started_at=now, lease_expires_at=now + timedelta(seconds=lease)).execution_options(synchronize_session=False))
        db.commit()
        if claimed.rowcount != 1:
            return
        if on_claimed:
            on_claimed()
        job = db.get(ProcessingJob, job_id)
        try:
            session = get_session_or_404(db, job.session_id)
            provider = provider_for(app, job.operation)
            if provider.name != job.provider:
                raise ApiError(409, "provider_changed", "任务排队期间模型配置已变化，请重新提交。")
            validate_operation(session, job.operation, job.payload, provider)
            if input_hash(session, job.operation, job.payload) != job.input_hash:
                raise ApiError(409, "job_input_changed", "排队期间问诊或病历版本已更新，请重新提交。")
            if job.operation == "transcribe":
                transcribe_session(db, job.session_id, settings, provider, job_id=job.id)
            elif job.operation == "generate":
                generate_draft(db, job.session_id, provider, job_id=job.id)
            elif job.operation == "structure":
                structure_session(db, job.session_id, provider, job_id=job.id)
            elif job.operation == "regenerate":
                regenerate_draft(db, job.session_id, job.payload["expected_revision"], provider, job_id=job.id)
            else:
                ask_session(db, job.session_id, job.payload["question"], provider, job_id=job.id)
        except ApiError as exc:
            fail_job(db, job_id, exc, exc.metrics)
            if propagate:
                raise
        except Exception as exc:
            logger.error("Job %s failed (%s)", job_id, type(exc).__name__)
            error = ApiError(502, "processing_failed", "处理服务暂时不可用，已有资料已保留，请稍后重试。")
            fail_job(db, job_id, error)
            if propagate:
                raise error from None


def execute_inline(db: Session, app, session_id: str, operation: str, payload: dict | None = None, request_key: str | None = None) -> ProcessingJob:
    job = submit_job(db, app, session_id, operation, payload or {}, request_key, background=False)
    job_id = job.id
    # Close this request's read transaction before another session writes.
    db.commit()
    if job.status == "queued":
        run_job(app, job_id, propagate=True)
    db.expire_all()
    job = get_job(db, session_id, job_id)
    if job.status in ("queued", "running"):
        raise ApiError(409, "operation_in_progress", "该请求正在处理中，请查看任务状态。")
    if job.status != "succeeded":
        raise ApiError(job.error_status or 409, job.error_code or "processing_failed", job.error_message or "任务失败，请使用新的请求编号重试。")
    return job


def job_dict(job: ProcessingJob) -> dict:
    elapsed = None
    if job.started_at and job.finished_at:
        elapsed = max(0, round((job.finished_at - job.started_at).total_seconds() * 1000))
    return {
        "id": job.id, "session_id": job.session_id, "request_id": job.request_key,
        "operation": job.operation, "status": job.status, "provider": job.provider,
        "base_revision": job.base_revision, "input_hash": job.input_hash,
        "created_at": iso_utc(job.created_at), "started_at": iso_utc(job.started_at),
        "finished_at": iso_utc(job.finished_at), "lease_expires_at": iso_utc(job.lease_expires_at),
        "elapsed_ms": elapsed, "result": job.result, "metrics": job.metrics,
        "error": {"code": job.error_code, "message": job.error_message} if job.error_code else None,
    }


class JobWorker:
    """One bounded background worker per app; database claims also allow multiple processes."""

    def __init__(self, app) -> None:
        self.app = app
        self.stop_event = Event()
        self.thread = Thread(target=self._run, name="zhenlu-job-worker", daemon=True)
        self.active_id: str | None = None

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                with self.app.state.db.session_factory() as db:
                    recover_expired(db)
                    job_id = db.scalar(select(ProcessingJob.id).where(
                        ProcessingJob.dispatch_mode == "background", ProcessingJob.status == "queued",
                    ).order_by(ProcessingJob.created_at).limit(1))
                if job_id and not self.stop_event.is_set():
                    def remember_claim() -> None:
                        self.active_id = job_id
                    run_job(self.app, job_id, on_claimed=remember_claim)
                    self.active_id = None
                    continue
            except Exception as exc:
                logger.error("Job worker iteration failed (%s)", type(exc).__name__)
            self.stop_event.wait(self.app.state.settings.job_poll_interval_seconds)

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=1)
        if self.thread.is_alive() and self.active_id:
            with self.app.state.db.session_factory() as db:
                db.execute(update(ProcessingJob).where(
                    ProcessingJob.id == self.active_id, ProcessingJob.status == "running",
                ).values(lease_expires_at=utcnow()))
                db.commit()
                recover_expired(db)
