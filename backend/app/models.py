from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.constants import DraftStatus, FieldOrigin, SessionStatus


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class ConsultationSession(Base):
    __tablename__ = "consultation_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    patient_name: Mapped[str] = mapped_column(String(80))
    patient_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=SessionStatus.AWAITING_AUDIO, nullable=False, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    audio_file: Mapped[AudioFile | None] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )
    transcript: Mapped[Transcript | None] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )
    dialogue: Mapped[StructuredDialogue | None] = relationship(
        cascade="all, delete-orphan", uselist=False, lazy="selectin",
    )
    draft: Mapped[RecordDraft | None] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )
    confirmed_records: Mapped[list[ConfirmedRecord]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ConfirmedRecord.version",
        lazy="selectin",
    )


class AudioFile(Base):
    __tablename__ = "audio_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("consultation_sessions.id", ondelete="CASCADE"), unique=True
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_relpath: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    session: Mapped[ConsultationSession] = relationship(back_populates="audio_file")


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("consultation_sessions.id", ondelete="CASCADE"), unique=True
    )
    audio_file_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("audio_files.id", ondelete="CASCADE"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(80))
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="zh-CN")
    notice: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    session: Mapped[ConsultationSession] = relationship(back_populates="transcript")
    segments: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="transcript",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.seq",
        lazy="selectin",
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (UniqueConstraint("transcript_id", "seq", name="uq_segment_seq"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    transcript_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("transcripts.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(String(20), default="未知")
    text: Mapped[str] = mapped_column(Text)
    # 没有可靠时间信息时必须保持 NULL，不伪造时间戳。
    start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    transcript: Mapped[Transcript] = relationship(back_populates="segments")


class RecordDraft(Base):
    __tablename__ = "record_drafts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("consultation_sessions.id", ondelete="CASCADE"), unique=True
    )
    transcript_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("transcripts.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(80))
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notice: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=DraftStatus.EDITING, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    session: Mapped[ConsultationSession] = relationship(back_populates="draft")
    fields: Mapped[list[DraftField]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="DraftField.position",
        lazy="selectin",
    )


class DraftField(Base):
    __tablename__ = "draft_fields"
    __table_args__ = (UniqueConstraint("draft_id", "field_key", name="uq_draft_field"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    draft_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("record_drafts.id", ondelete="CASCADE"), index=True
    )
    field_key: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer)
    ai_value: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(12), default=FieldOrigin.AI)
    source_segment_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    suggested_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_source_segment_ids: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True
    )
    suggestion_created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    doctor_edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    draft: Mapped[RecordDraft] = relationship(back_populates="fields")


class ConfirmedRecord(Base):
    __tablename__ = "confirmed_records"
    __table_args__ = (
        UniqueConstraint("session_id", "version", name="uq_confirmed_version"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("consultation_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer)
    draft_revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)
    text: Mapped[str] = mapped_column(Text)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    session: Mapped[ConsultationSession] = relationship(
        back_populates="confirmed_records"
    )


Index("ix_sessions_updated_at", ConsultationSession.updated_at)


class ProcessingJob(Base):
    """Durable operation and lease. A non-null slot allows one model job per session."""

    __tablename__ = "processing_jobs"
    __table_args__ = (
        UniqueConstraint("session_id", "request_key", name="uq_job_request"),
        Index("ix_jobs_dispatch", "dispatch_mode", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("consultation_sessions.id", ondelete="CASCADE"), index=True)
    active_session_id: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    request_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    operation: Mapped[str] = mapped_column(String(24))
    dispatch_mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    provider: Mapped[str] = mapped_column(String(160))
    input_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    base_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)


class AssistantTurn(Base):
    __tablename__ = "assistant_turns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("consultation_sessions.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("processing_jobs.id"), unique=True, nullable=True)
    question: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(160))
    is_mock: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(24))
    answers: Mapped[list[dict]] = mapped_column(JSON)
    context_version: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StructuredDialogue(Base):
    __tablename__ = "structured_dialogues"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("consultation_sessions.id", ondelete="CASCADE"), unique=True)
    transcript_id: Mapped[str] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[str] = mapped_column(String(160))
    is_mock: Mapped[bool] = mapped_column(Boolean)
    turns: Mapped[list[dict]] = mapped_column(JSON)
    notice: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
