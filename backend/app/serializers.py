from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.constants import SESSION_STATUS_LABELS, UNMENTIONED
from app.models import (
    AudioFile,
    ConfirmedRecord,
    ConsultationSession,
    DraftField,
    RecordDraft,
    Transcript,
    TranscriptSegment,
)


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def segment_dict(segment: TranscriptSegment) -> dict[str, Any]:
    return {
        "id": segment.id,
        "seq": segment.seq,
        "speaker": segment.speaker,
        "text": segment.text,
        "start_ms": segment.start_ms,
        "end_ms": segment.end_ms,
    }


def audio_dict(audio: AudioFile, session_id: str) -> dict[str, Any]:
    return {
        "id": audio.id,
        "filename": audio.original_filename,
        "content_type": audio.content_type,
        "size_bytes": audio.size_bytes,
        "duration_ms": audio.duration_ms,
        "uploaded_at": iso_utc(audio.created_at),
        "url": f"/api/sessions/{session_id}/audio",
    }


def transcript_dict(transcript: Transcript) -> dict[str, Any]:
    segments = [segment_dict(segment) for segment in transcript.segments]
    has_timestamps = bool(segments) and all(
        item["start_ms"] is not None and item["end_ms"] is not None
        for item in segments
    )
    return {
        "id": transcript.id,
        "provider": transcript.provider,
        "is_mock": transcript.is_mock,
        "language": transcript.language,
        "notice": transcript.notice,
        "created_at": iso_utc(transcript.created_at),
        "has_reliable_timestamps": has_timestamps,
        "segments": segments,
    }


def _segment_map(transcript: Transcript | None) -> dict[str, TranscriptSegment]:
    if transcript is None:
        return {}
    return {segment.id: segment for segment in transcript.segments}


def _sources(
    segment_ids: list[str] | tuple[str, ...] | None,
    segments: dict[str, TranscriptSegment],
) -> list[dict[str, Any]]:
    if not segment_ids:
        return []
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for segment_id in segment_ids:
        if segment_id in seen:
            continue
        segment = segments.get(segment_id)
        if segment is None:
            continue
        seen.add(segment_id)
        result.append(segment_dict(segment))
    return result


def _field_dict(
    field: DraftField, segments: dict[str, TranscriptSegment]
) -> dict[str, Any]:
    suggestion = None
    if field.suggested_value is not None:
        suggestion = {
            "value": field.suggested_value,
            "sources": _sources(field.suggested_source_segment_ids, segments),
            "created_at": iso_utc(field.suggestion_created_at),
        }
    return {
        "key": field.field_key,
        "label": field.label,
        "value": field.value,
        "ai_value": field.ai_value,
        "origin": field.origin,
        "is_doctor_edited": field.origin == "doctor",
        "edited_at": iso_utc(field.doctor_edited_at),
        "is_unmentioned": field.value.strip() == UNMENTIONED,
        "sources": _sources(field.source_segment_ids, segments),
        "suggestion": suggestion,
    }


def draft_dict(
    draft: RecordDraft, transcript: Transcript | None
) -> dict[str, Any]:
    segments = _segment_map(transcript)
    fields = [_field_dict(field, segments) for field in draft.fields]
    return {
        "id": draft.id,
        "provider": draft.provider,
        "is_mock": draft.is_mock,
        "notice": draft.notice,
        "revision": draft.revision,
        "status": draft.status,
        "created_at": iso_utc(draft.created_at),
        "updated_at": iso_utc(draft.updated_at),
        "has_doctor_edits": any(item["is_doctor_edited"] for item in fields),
        "has_suggestions": any(item["suggestion"] is not None for item in fields),
        "fields": fields,
    }


def confirmed_record_dict(record: ConfirmedRecord) -> dict[str, Any]:
    content = record.content or {}
    snapshot_fields = content.get("fields", [])
    fields = [
        {
            "key": item.get("key", ""),
            "label": item.get("label", ""),
            "value": item.get("value", ""),
            "origin": item.get("origin", "ai"),
            "sources": item.get("sources", []),
        }
        for item in snapshot_fields
    ]
    return {
        "id": record.id,
        "version": record.version,
        "draft_revision": record.draft_revision,
        "confirmed_at": iso_utc(record.confirmed_at),
        "text": record.text,
        "fields": fields,
    }


def latest_record(session: ConsultationSession) -> ConfirmedRecord | None:
    if not session.confirmed_records:
        return None
    return session.confirmed_records[-1]


def session_summary_dict(session: ConsultationSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "patient_name": session.patient_name,
        "patient_ref": session.patient_ref,
        "status": session.status,
        "status_label": (
            "问诊内容已录入"
            if session.status == "transcribed" and session.transcript is not None
            and session.transcript.provider == "manual"
            else SESSION_STATUS_LABELS.get(session.status, session.status)
        ),
        "created_at": iso_utc(session.created_at),
        "updated_at": iso_utc(session.updated_at),
        "has_audio": session.audio_file is not None,
        "has_transcript": session.transcript is not None,
        "has_draft": session.draft is not None,
        "confirmed_version": session.confirmed_version,
    }


def session_detail_dict(session: ConsultationSession) -> dict[str, Any]:
    audio = session.audio_file
    transcript = session.transcript
    draft = session.draft
    record = latest_record(session)
    detail = session_summary_dict(session)
    detail.update(
        {
            "error_message": session.error_message,
            "audio": audio_dict(audio, session.id) if audio else None,
            "transcript": transcript_dict(transcript) if transcript else None,
            "draft": draft_dict(draft, transcript) if draft else None,
            "latest_record": confirmed_record_dict(record) if record else None,
        }
    )
    return detail
