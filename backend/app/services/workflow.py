from __future__ import annotations

import logging
import re

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import Settings
from app.constants import (
    FIELD_DEFINITIONS,
    FIELD_KEYS,
    DraftStatus,
    FieldOrigin,
    SessionStatus,
)
from app.errors import ApiError
from app.models import (
    ConfirmedRecord,
    ConsultationSession,
    DraftField,
    RecordDraft,
    Transcript,
    TranscriptSegment,
    new_id,
    utcnow,
)
from app.providers.base import (
    DraftGenerationProvider,
    DraftResult,
    TranscriptionProvider,
)
from app.providers.fun_asr import AsrProviderError
from app.providers.qwen_draft import DraftProviderError, _parse_fields
from app.schemas import DraftUpdate
from app.serializers import segment_dict
from app.services.audio_service import resolve_audio_path
from app.services.dialogue_service import transcript_document
from app.services.export import build_record_text
from app.services.job_state import ensure_no_active_job, finish_job
from app.services.session_service import ensure_editable, get_session_or_404

logger = logging.getLogger(__name__)


def _clean_times(
    start_ms: int | None, end_ms: int | None
) -> tuple[int | None, int | None]:
    if start_ms is None or end_ms is None:
        return None, None
    if start_ms < 0 or end_ms <= start_ms:
        return None, None
    return start_ms, end_ms


def _mark_failed(db: Session, session: ConsultationSession, message: str) -> None:
    session.status = SessionStatus.FAILED
    session.error_message = message
    session.updated_at = utcnow()
    db.commit()


def _normalized_generated_fields(
    result: DraftResult, valid_segment_ids: set[str]
) -> dict[str, tuple[str, str, list[str]]]:
    try:
        fields = _parse_fields({"fields": [
            {"key": field.key, "value": field.value, "source_segment_ids": list(field.source_segment_ids)}
            for field in result.fields
        ]}, valid_segment_ids)
    except (ValueError, TypeError):
        raise ApiError(502, "draft_invalid_response", "模型返回格式或来源无效，请重试。", metrics=result.metadata) from None
    return {
        field.key: (field.label, field.value, list(field.source_segment_ids))
        for field in fields
    }


def _clear_suggestion(field: DraftField) -> None:
    field.suggested_value = None
    field.suggested_source_segment_ids = None
    field.suggestion_created_at = None


def _claim_draft(db: Session, draft: RecordDraft, revision: int, *, confirm: bool = False) -> None:
    """Claim the version in the database before changing fields or confirming."""
    values = {"status": DraftStatus.CONFIRMED} if confirm else {"revision": revision + 1}
    result = db.execute(
        update(RecordDraft)
        .where(
            RecordDraft.id == draft.id,
            RecordDraft.revision == revision,
            RecordDraft.status == DraftStatus.EDITING,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise ApiError(409, "revision_conflict", "草稿已更新或确认，请保留当前输入后刷新页面。")
    db.refresh(draft)


def transcribe_session(
    db: Session,
    session_id: str,
    settings: Settings,
    provider: TranscriptionProvider,
    *, job_id: str | None = None,
) -> ConsultationSession:
    session = get_session_or_404(db, session_id)
    ensure_editable(session)
    if session.audio_file is None:
        raise ApiError(409, "audio_required", "请先上传音频，再开始转写。")
    if session.transcript is not None:
        raise ApiError(409, "transcript_exists", "该会话已完成转写，不能重复执行。")

    audio_path = resolve_audio_path(settings, session.audio_file)
    session.status = SessionStatus.TRANSCRIBING
    session.error_message = None
    session.updated_at = utcnow()
    db.commit()

    try:
        result = provider.transcribe(
            audio_path=audio_path,
            original_filename=session.audio_file.original_filename,
        )
    except AsrProviderError as exc:
        logger.warning("ASR provider failed for session %s: %s", session.id, exc.code)
        if job_id is None:
            _mark_failed(db, session, exc.message)
        raise ApiError(502, exc.code, exc.message, metrics=getattr(exc, "metadata", {})) from None
    except Exception as exc:
        logger.error("ASR provider failed for session %s (%s)", session.id, type(exc).__name__)
        if job_id is None:
            _mark_failed(db, session, "语音转写失败，请稍后重试或检查音频文件。")
        raise ApiError(
            502, "asr_failed", "语音转写服务暂时不可用，请稍后重试。"
        ) from exc

    db.rollback()
    session = get_session_or_404(db, session_id)
    ensure_editable(session)
    clean_segments = [
        segment for segment in result.segments if segment.text.strip()
    ]
    if not clean_segments:
        if job_id is None:
            _mark_failed(db, session, "转写未返回任何有效文本，请更换音频后重试。")
        raise ApiError(502, "empty_transcript", "转写结果为空，请更换音频后重试。")

    transcript = Transcript(
        id=new_id(),
        session_id=session.id,
        audio_file_id=session.audio_file.id,
        provider=result.provider,
        is_mock=result.is_mock,
        language=result.language or "zh-CN",
        notice=result.notice,
    )
    for seq, segment in enumerate(clean_segments):
        start_ms, end_ms = _clean_times(segment.start_ms, segment.end_ms)
        transcript.segments.append(
            TranscriptSegment(
                id=new_id(),
                seq=seq,
                speaker=segment.speaker.strip() or "未知",
                text=segment.text.strip(),
                start_ms=start_ms,
                end_ms=end_ms,
            )
        )

    finish_job(db, job_id, {"transcript_id": transcript.id}, result.metadata)
    session.transcript = transcript
    session.status = SessionStatus.TRANSCRIBED
    session.error_message = None
    session.updated_at = utcnow()
    db.commit()
    return get_session_or_404(db, session.id)


def _explicit_speaker(line: str) -> str:
    match = re.match(r"^(医生|医师|患者|病人|家属)\s*[:：]", line)
    return {"医师": "医生", "病人": "患者"}.get(match[1], match[1]) if match else "未知"


def create_manual_transcript(db: Session, session_id: str, text: str) -> ConsultationSession:
    ensure_no_active_job(db, session_id)
    session = get_session_or_404(db, session_id)
    ensure_editable(session)
    if session.transcript is not None:
        raise ApiError(409, "transcript_exists", "该会话已有问诊内容。")
    if session.status in (SessionStatus.TRANSCRIBING, SessionStatus.GENERATING_DRAFT):
        raise ApiError(409, "processing", "会话正在处理中，请稍后重试。")
    transcript = Transcript(
        id=new_id(), session_id=session.id,
        audio_file_id=session.audio_file.id if session.audio_file else None,
        provider="manual", is_mock=False, language="zh-CN",
        notice="问诊内容由用户手动录入，未经过语音识别；无音频时间定位。",
    )
    for seq, line in enumerate(line.strip() for line in text.splitlines() if line.strip()):
        transcript.segments.append(TranscriptSegment(
            id=new_id(), seq=seq, speaker=_explicit_speaker(line), text=line,
            start_ms=None, end_ms=None,
        ))
    session.transcript = transcript
    session.status = SessionStatus.TRANSCRIBED
    session.error_message = None
    session.updated_at = utcnow()
    db.commit()
    return get_session_or_404(db, session.id)


def generate_draft(
    db: Session,
    session_id: str,
    provider: DraftGenerationProvider,
    *, job_id: str | None = None,
) -> ConsultationSession:
    session = get_session_or_404(db, session_id)
    ensure_editable(session)
    if session.transcript is None:
        raise ApiError(409, "transcript_required", "请先完成语音转写，再生成病历草稿。")
    if session.draft is not None:
        raise ApiError(
            409,
            "draft_exists",
            "该会话已生成草稿。如需更新，请使用“重新生成草稿”。",
        )

    transcript = session.transcript
    document = transcript_document(session)
    session.status = SessionStatus.GENERATING_DRAFT
    session.error_message = None
    session.updated_at = utcnow()
    db.commit()

    try:
        result = provider.generate(document)
    except DraftProviderError as exc:
        logger.warning("Draft provider failed for session %s: %s", session.id, exc.code)
        if job_id is None:
            _mark_failed(db, session, exc.message)
        raise ApiError(502, exc.code, exc.message, metrics=getattr(exc, "metadata", {})) from None
    except Exception as exc:
        logger.error("Draft provider failed for session %s (%s)", session.id, type(exc).__name__)
        if job_id is None:
            _mark_failed(db, session, "病历草稿生成失败，请稍后重试。")
        raise ApiError(
            502, "draft_generation_failed", "病历草稿生成服务暂时不可用，请稍后重试。"
        ) from None

    db.rollback()
    session = get_session_or_404(db, session_id)
    ensure_editable(session)
    normalized = _normalized_generated_fields(
        result, {segment.id for segment in transcript.segments}
    )
    draft = RecordDraft(
        id=new_id(),
        session_id=session.id,
        transcript_id=transcript.id,
        provider=result.provider,
        is_mock=result.is_mock,
        notice=result.notice,
        revision=1,
        status=DraftStatus.EDITING,
    )
    for position, (key, _) in enumerate(FIELD_DEFINITIONS):
        label, value, source_ids = normalized[key]
        draft.fields.append(
            DraftField(
                field_key=key,
                label=label,
                position=position,
                ai_value=value,
                value=value,
                origin=FieldOrigin.AI,
                source_segment_ids=source_ids,
            )
        )

    finish_job(db, job_id, {"draft_id": draft.id, "draft_revision": 1}, result.metadata)
    session.draft = draft
    session.status = SessionStatus.DRAFT_READY
    session.error_message = None
    session.updated_at = utcnow()
    db.commit()
    return get_session_or_404(db, session.id)


def update_draft(
    db: Session, session_id: str, payload: DraftUpdate
) -> ConsultationSession:
    session = get_session_or_404(db, session_id)
    ensure_editable(session)
    draft = session.draft
    if draft is None:
        raise ApiError(409, "draft_required", "该会话还没有病历草稿。")
    if draft.revision != payload.expected_revision:
        raise ApiError(
            409,
            "revision_conflict",
            "草稿已在其他操作中更新，请先复制当前未保存内容，再刷新页面重新编辑。",
        )

    fields_by_key = {field.field_key: field for field in draft.fields}
    for item in payload.fields:
        field = fields_by_key.get(item.field_key)
        if field is None:
            raise ApiError(400, "unknown_field", f"未知病历字段：{item.field_key}")
        if item.accept_suggestion and (field.suggested_value is None or item.value.strip() != field.suggested_value):
            raise ApiError(409, "suggestion_changed", "系统建议已变化，请刷新后重新选择。")
    _claim_draft(db, draft, payload.expected_revision)
    changed = False
    now = utcnow()
    for item in payload.fields:
        field = fields_by_key.get(item.field_key)
        if field is None:
            raise ApiError(400, "unknown_field", f"未知病历字段：{item.field_key}")
        value = item.value.strip()
        if value == field.value:
            continue
        field.value = value
        field.origin = FieldOrigin.DOCTOR
        field.doctor_edited_at = now
        if item.accept_suggestion:
            field.source_segment_ids = list(field.suggested_source_segment_ids or [])
        _clear_suggestion(field)
        changed = True

    if changed:
        draft.updated_at = now
        session.status = SessionStatus.DRAFT_READY
        session.error_message = None
        session.updated_at = now
    db.commit()

    return get_session_or_404(db, session.id)


def regenerate_draft(
    db: Session,
    session_id: str,
    payload_revision: int,
    provider: DraftGenerationProvider,
    *, job_id: str | None = None,
) -> ConsultationSession:
    session = get_session_or_404(db, session_id)
    ensure_editable(session)
    draft = session.draft
    if draft is None or session.transcript is None:
        raise ApiError(409, "draft_required", "该会话还没有可重新生成的病历草稿。")
    if draft.revision != payload_revision:
        raise ApiError(
            409,
            "revision_conflict",
            "草稿已在其他操作中更新，请刷新页面后再重新生成。",
        )

    transcript = session.transcript
    document = transcript_document(session)
    db.commit()
    try:
        result = provider.generate(document)
    except DraftProviderError as exc:
        logger.warning("Draft regeneration failed for session %s: %s", session.id, exc.code)
        raise ApiError(502, exc.code, exc.message + " 当前内容未被覆盖。", metrics=exc.metadata) from None
    except Exception as exc:
        logger.error("Draft regeneration failed for session %s (%s)", session.id, type(exc).__name__)
        raise ApiError(
            502, "draft_generation_failed", "草稿重新生成失败，当前内容未被覆盖。"
        ) from None

    normalized = _normalized_generated_fields(
        result, {segment.id for segment in transcript.segments}
    )
    db.rollback()
    session = get_session_or_404(db, session_id)
    draft = session.draft
    finish_job(db, job_id, {"draft_id": draft.id, "draft_revision": payload_revision + 1}, result.metadata)
    _claim_draft(db, draft, payload_revision)
    now = utcnow()
    for field in draft.fields:
        label, new_value, source_ids = normalized[field.field_key]
        if field.origin == FieldOrigin.DOCTOR:
            if new_value != field.value:
                field.suggested_value = new_value
                field.suggested_source_segment_ids = source_ids
                field.suggestion_created_at = now
            else:
                _clear_suggestion(field)
            continue

        field.label = label
        field.ai_value = new_value
        field.value = new_value
        field.source_segment_ids = source_ids
        _clear_suggestion(field)

    draft.provider = result.provider
    draft.is_mock = draft.is_mock or result.is_mock
    draft.notice = result.notice

    draft.updated_at = now
    session.status = SessionStatus.DRAFT_READY
    session.error_message = None
    session.updated_at = now
    db.commit()
    return get_session_or_404(db, session.id)


def confirm_draft(
    db: Session,
    session_id: str,
    settings: Settings,
    expected_revision: int,
) -> ConsultationSession:
    session = get_session_or_404(db, session_id)
    ensure_editable(session)
    draft = session.draft
    if draft is None or session.transcript is None:
        raise ApiError(409, "draft_required", "该会话还没有可确认的病历草稿。")
    if draft.revision != expected_revision:
        raise ApiError(
            409,
            "revision_conflict",
            "草稿已在其他操作中更新，请刷新页面后再确认。",
        )

    _claim_draft(db, draft, expected_revision, confirm=True)
    segment_map = {segment.id: segment for segment in session.transcript.segments}
    snapshot_fields: list[dict] = []
    for field in draft.fields:
        if field.field_key not in FIELD_KEYS:
            continue
        sources = []
        for segment_id in field.source_segment_ids or []:
            segment = segment_map.get(segment_id)
            if segment is not None:
                sources.append(segment_dict(segment))
        snapshot_fields.append(
            {
                "key": field.field_key,
                "label": field.label,
                "value": field.value,
                "origin": field.origin,
                "sources": sources,
            }
        )

    confirmed_at = utcnow()
    version = session.confirmed_version + 1
    text = build_record_text(
        session=session,
        fields=snapshot_fields,
        is_mock=draft.is_mock or (
            session.transcript.is_mock and session.transcript.provider != "manual"
        ),
        confirmed_at=confirmed_at,
        timezone_offset_hours=settings.timezone_offset_hours,
    )
    record = ConfirmedRecord(
        id=new_id(),
        session_id=session.id,
        version=version,
        draft_revision=draft.revision,
        content={"fields": snapshot_fields},
        text=text,
        confirmed_at=confirmed_at,
    )
    session.confirmed_records.append(record)
    session.confirmed_version = version
    session.status = SessionStatus.CONFIRMED
    session.error_message = None
    session.updated_at = confirmed_at
    draft.status = DraftStatus.CONFIRMED
    draft.updated_at = confirmed_at
    db.commit()
    return get_session_or_404(db, session.id)


def get_confirmed_record(
    db: Session, session_id: str
) -> ConfirmedRecord:
    session = get_session_or_404(db, session_id)
    if not session.confirmed_records:
        raise ApiError(404, "record_not_confirmed", "该会话尚未确认，暂无可用病历文本。")
    return session.confirmed_records[-1]
