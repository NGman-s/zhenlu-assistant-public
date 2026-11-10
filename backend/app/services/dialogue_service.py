from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.constants import SessionStatus
from app.models import StructuredDialogue, new_id, utcnow
from app.providers.base import TranscriptDocument, TranscriptSegmentData
from app.providers.dialogue import annotation_kind, explicit_role, validate_roles
from app.providers.qwen_client import DraftProviderError
from app.services.job_state import finish_job
from app.services.session_service import ensure_editable, get_session_or_404


def transcript_document(session) -> TranscriptDocument:
    roles = {t["segment_id"]: t for t in session.dialogue.turns} if session.dialogue else {}
    return TranscriptDocument(session.transcript.id, tuple(
        TranscriptSegmentData(
            id=s.id, seq=s.seq, speaker=s.speaker, text=s.text, start_ms=s.start_ms, end_ms=s.end_ms,
            role=roles.get(s.id, {}).get("role"), role_basis=roles.get(s.id, {}).get("role_basis"),
        ) for s in session.transcript.segments
    ))


def structure_session(db: Session, session_id: str, provider, job_id: str | None = None) -> StructuredDialogue:
    session = get_session_or_404(db, session_id)
    ensure_editable(session)
    if session.transcript is None:
        raise ApiError(409, "transcript_required", "请先录入问诊内容或完成转写。")
    if session.dialogue:
        raise ApiError(409, "dialogue_exists", "角色整理已经保存。")
    if session.draft:
        raise ApiError(409, "draft_exists", "请在首次生成病历前整理角色，避免改变已审核草稿的依据。")
    document = transcript_document(session)
    if sum(len(s.text) for s in document.segments) > 100_000:
        raise ApiError(413, "dialogue_input_too_large", "当前对话过长，暂不支持角色整理；原文已保存。")
    db.commit()
    try:
        result = provider.structure(document)
        roles = validate_roles({"roles": list(result.roles)}, document)
    except DraftProviderError as exc:
        raise ApiError(502, exc.code, exc.message, metrics=exc.metadata) from None
    except (ValueError, TypeError):
        raise ApiError(502, "dialogue_invalid_response", "角色整理结果无效，原文未改变。") from None
    sources = {s.id: s for s in document.segments}
    turns = []
    for item in roles:
        s = sources[item["segment_id"]]
        explicit = explicit_role(s.speaker, s.text)
        turns.append({
            **item, "seq": s.seq, "speaker": s.speaker, "text": s.text,
            "role_basis": "unknown" if item["role"] == "未知" else ("explicit" if explicit != "未知" else "inferred"),
            "content_kind": annotation_kind(s.text), "start_ms": s.start_ms, "end_ms": s.end_ms,
        })
    db.rollback()
    session = get_session_or_404(db, session_id)
    dialogue = StructuredDialogue(
        id=new_id(), session_id=session_id, transcript_id=document.id, provider=provider.name,
        is_mock=provider.is_mock, turns=turns,
        notice="原文逐句保留。角色推断需人工核对；文本标注不代表已完成音频降噪或声纹分离。",
    )
    finish_job(db, job_id, {"dialogue_id": dialogue.id}, result.metadata)
    session.dialogue = dialogue
    session.status = SessionStatus.TRANSCRIBED
    session.error_message = None
    session.updated_at = utcnow()
    db.commit()
    return dialogue
