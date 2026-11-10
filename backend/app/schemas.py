from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


FieldKey = Literal[
    "chief_complaint",
    "present_illness",
    "past_history",
    "medication_history",
    "allergy_history",
]


# ---------- 请求参数 ----------


class SessionCreate(BaseModel):
    patient_name: str = Field(min_length=1, max_length=80)
    patient_ref: str | None = Field(default=None, max_length=120)

    @field_validator("patient_name")
    @classmethod
    def strip_patient_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("患者称呼不能为空")
        return value

    @field_validator("patient_ref")
    @classmethod
    def normalize_patient_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class DraftFieldInput(BaseModel):
    field_key: FieldKey
    value: str = Field(min_length=1, max_length=4000)
    accept_suggestion: bool = False

    @field_validator("value")
    @classmethod
    def strip_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段内容不能为空")
        return value


class DraftUpdate(BaseModel):
    expected_revision: int = Field(ge=0)
    fields: list[DraftFieldInput] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def ensure_unique_fields(self) -> DraftUpdate:
        keys = [item.field_key for item in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("同一字段不能重复提交")
        return self


class RevisionRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class ManualTranscriptInput(BaseModel):
    text: str = Field(min_length=1, max_length=20000)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("问诊内容不能为空")
        if len([line for line in value.splitlines() if line.strip()]) > 200:
            raise ValueError("问诊内容不能超过 200 行")
        return value


class QuestionInput(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("问题不能为空")
        return value.strip()


class JobCreate(BaseModel):
    operation: Literal["transcribe", "structure", "generate", "regenerate", "ask"]
    request_id: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_revision: int | None = Field(default=None, ge=1)
    question: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_operation_fields(self) -> JobCreate:
        if (self.operation == "regenerate") != (self.expected_revision is not None):
            raise ValueError("仅重新生成操作需要 expected_revision")
        if (self.operation == "ask") != (self.question is not None):
            raise ValueError("仅问答操作需要 question")
        if self.question is not None:
            self.question = QuestionInput(question=self.question).question
        return self

    def operation_payload(self) -> dict:
        if self.operation == "regenerate":
            return {"expected_revision": self.expected_revision}
        if self.operation == "ask":
            return {"question": self.question}
        return {}


# ---------- 响应结构 ----------


class AudioOut(BaseModel):
    id: str
    filename: str
    content_type: str | None
    size_bytes: int
    sha256: str | None
    duration_ms: int | None
    uploaded_at: str
    url: str


class SegmentOut(BaseModel):
    id: str
    seq: int
    speaker: str
    text: str
    start_ms: int | None
    end_ms: int | None


class TranscriptOut(BaseModel):
    id: str
    provider: str
    is_mock: bool
    language: str
    notice: str
    created_at: str
    has_reliable_timestamps: bool
    segments: list[SegmentOut]


class SuggestionOut(BaseModel):
    value: str
    sources: list[SegmentOut]
    created_at: str


class DraftFieldOut(BaseModel):
    key: str
    label: str
    value: str
    ai_value: str
    origin: str
    is_doctor_edited: bool
    edited_at: str | None
    is_unmentioned: bool
    sources: list[SegmentOut]
    suggestion: SuggestionOut | None


class DraftOut(BaseModel):
    id: str
    provider: str
    is_mock: bool
    notice: str
    revision: int
    status: str
    created_at: str
    updated_at: str
    has_doctor_edits: bool
    has_suggestions: bool
    fields: list[DraftFieldOut]


class ConfirmedFieldOut(BaseModel):
    key: str
    label: str
    value: str
    origin: str
    sources: list[SegmentOut]


class ConfirmedRecordOut(BaseModel):
    id: str
    version: int
    draft_revision: int
    confirmed_at: str
    text: str
    fields: list[ConfirmedFieldOut]


class SessionSummaryOut(BaseModel):
    id: str
    patient_name: str
    patient_ref: str | None
    status: str
    status_label: str
    created_at: str
    updated_at: str
    has_audio: bool
    has_transcript: bool
    has_draft: bool
    confirmed_version: int


class SessionDetailOut(SessionSummaryOut):
    error_message: str | None
    audio: AudioOut | None
    transcript: TranscriptOut | None
    draft: DraftOut | None
    latest_record: ConfirmedRecordOut | None
    dialogue: dict | None


class SessionListOut(BaseModel):
    items: list[SessionSummaryOut]


class RecordTextOut(BaseModel):
    version: int
    confirmed_at: str
    text: str


class HealthOut(BaseModel):
    status: str
    asr_provider: str
    asr_is_mock: bool
    draft_provider: str
    draft_is_mock: bool
    assistant_provider: str
    assistant_is_mock: bool
    job_worker_enabled: bool
    dialogue_provider: str
