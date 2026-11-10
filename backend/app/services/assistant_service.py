from __future__ import annotations

import hashlib
import json

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import AssistantTurn, ConsultationSession, RecordDraft, new_id
from app.providers.assistant import validate_answer
from app.providers.qwen_client import DraftProviderError
from app.serializers import iso_utc, segment_dict
from app.services.job_state import finish_job
from app.services.session_service import get_session_or_404


def assistant_context(session: ConsultationSession) -> dict:
    transcript, draft = session.transcript, session.draft
    if transcript is None:
        raise ApiError(409, "transcript_required", "请先录入问诊内容或完成转写。")
    # Evidence ID is distinct from the original segment ID, both are retained for UI navigation.
    evidence = [
        {**segment_dict(s), "id": f"segment:{s.id}", "kind": "segment", "segment_id": s.id}
        for s in transcript.segments
    ]
    version = {"transcript_id": transcript.id, "record_kind": "transcript", "draft_revision": None, "confirmed_version": None, "record_id": None}
    if session.confirmed_records:
        record = session.confirmed_records[-1]
        version.update(record_kind="confirmed", draft_revision=record.draft_revision, confirmed_version=record.version, record_id=record.id)
        fields = record.content.get("fields", [])
    elif draft:
        version.update(record_kind="draft", draft_revision=draft.revision, record_id=draft.id)
        fields = [{"key": f.field_key, "label": f.label, "value": f.value, "origin": f.origin} for f in draft.fields]
    else:
        fields = []
    for item in fields:
        evidence.append({
            "id": f'field:{item["key"]}', "kind": "field", "field_key": item["key"],
            "label": item["label"], "value": item["value"], "origin": item["origin"],
        })
    context = {"version": version, "evidence": evidence}
    if session.dialogue:
        version["dialogue_id"] = session.dialogue.id
        roles = {turn["segment_id"]: turn for turn in session.dialogue.turns}
        for item in evidence:
            turn = roles.get(item.get("segment_id"))
            if turn:
                item.update(role=turn["role"], role_basis=turn["role_basis"], content_kind=turn["content_kind"])
    if len(json.dumps(context, ensure_ascii=False)) > 150_000:
        raise ApiError(413, "assistant_context_too_large", "本次问诊内容过长，暂不支持助手查询；原始资料已保存。")
    return context


def context_hash(context: dict) -> str:
    return hashlib.sha256(json.dumps(context, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def ask_session(db: Session, session_id: str, question: str, provider, job_id: str | None = None) -> AssistantTurn:
    session = get_session_or_404(db, session_id)
    context = assistant_context(session)
    before = context_hash(context)
    # Release all read transactions before the external call.
    db.commit()
    try:
        result = provider.answer(question, context)
        parsed = validate_answer({"status": result.status, "answers": list(result.answers)}, context["evidence"])
    except DraftProviderError as exc:
        raise ApiError(502, exc.code, exc.message, metrics=exc.metadata) from None
    except (ValueError, TypeError):
        raise ApiError(502, "assistant_invalid_response", "助手回答格式或来源无效，请重试。") from None
    db.rollback()
    session = get_session_or_404(db, session_id)
    turn_id = new_id()
    finish_job(db, job_id, {"assistant_turn_id": turn_id, "context_version": context["version"]}, result.metadata)
    # The job row write serializes SQLite writers; CAS on the draft also covers other databases.
    if session.draft:
        version = context["version"]
        expected_status = "confirmed" if version["record_kind"] == "confirmed" else "editing"
        changed = db.execute(update(RecordDraft).where(
            RecordDraft.id == session.draft.id, RecordDraft.revision == version["draft_revision"],
            RecordDraft.status == expected_status,
        ).values(revision=RecordDraft.revision, updated_at=RecordDraft.updated_at).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise ApiError(409, "assistant_context_changed", "回答期间病历已更新，请针对最新版本重新提问。")
    db.expire_all()
    session = get_session_or_404(db, session_id)
    if context_hash(assistant_context(session)) != before:
        raise ApiError(409, "assistant_context_changed", "回答期间病历已更新，请针对最新版本重新提问。")
    evidence = {item["id"]: item for item in context["evidence"]}
    turn = AssistantTurn(
        id=turn_id, session_id=session_id, job_id=job_id, question=question,
        provider=provider.name, is_mock=provider.is_mock, status=parsed.status,
        answers=[{"text": item["text"], "sources": [evidence[ref] for ref in item["evidence_ids"]]} for item in parsed.answers],
        context_version=context["version"],
    )
    db.add(turn)
    db.commit()
    return turn


def turn_dict(turn: AssistantTurn) -> dict:
    return {
        "id": turn.id, "session_id": turn.session_id, "job_id": turn.job_id,
        "question": turn.question, "status": turn.status, "answers": turn.answers,
        "context_version": turn.context_version, "provider": turn.provider,
        "is_mock": turn.is_mock, "created_at": iso_utc(turn.created_at),
        "notice": {"insufficient": "当前记录不足以回答该问题，未提及不代表没有。", "out_of_scope": "助手仅查询当前会话记录，不提供诊断或治疗建议。"}.get(
            turn.status, "回答依据所标注版本的记录，请核对来源。"),
    }
