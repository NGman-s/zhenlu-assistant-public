export type SessionStatus =
  | "awaiting_audio"
  | "audio_ready"
  | "transcribing"
  | "transcribed"
  | "generating_draft"
  | "draft_ready"
  | "confirmed"
  | "failed";

export type FieldOrigin = "ai" | "doctor";

export type BusyAction =
  | "upload"
  | "demo_upload"
  | "transcribe"
  | "generate"
  | "save"
  | "regenerate"
  | "confirm"
  | null;

export interface AudioInfo {
  id: string;
  filename: string;
  content_type: string | null;
  size_bytes: number;
  duration_ms: number | null;
  uploaded_at: string;
  url: string;
}

export interface TranscriptSegment {
  id: string;
  seq: number;
  speaker: string;
  text: string;
  start_ms: number | null;
  end_ms: number | null;
}

export interface Transcript {
  id: string;
  provider: string;
  is_mock: boolean;
  language: string;
  notice: string;
  created_at: string;
  has_reliable_timestamps: boolean;
  segments: TranscriptSegment[];
}

export interface FieldSuggestion {
  value: string;
  sources: TranscriptSegment[];
  created_at: string;
}

export interface DraftField {
  key: string;
  label: string;
  value: string;
  ai_value: string;
  origin: FieldOrigin;
  is_doctor_edited: boolean;
  edited_at: string | null;
  is_unmentioned: boolean;
  sources: TranscriptSegment[];
  suggestion: FieldSuggestion | null;
}

export interface Draft {
  id: string;
  provider: string;
  is_mock: boolean;
  notice: string;
  revision: number;
  status: "editing" | "confirmed";
  created_at: string;
  updated_at: string;
  has_doctor_edits: boolean;
  has_suggestions: boolean;
  fields: DraftField[];
}

export interface ConfirmedField {
  key: string;
  label: string;
  value: string;
  origin: FieldOrigin;
  sources: TranscriptSegment[];
}

export interface ConfirmedRecord {
  id: string;
  version: number;
  draft_revision: number;
  confirmed_at: string;
  text: string;
  fields: ConfirmedField[];
}

export interface SessionSummary {
  id: string;
  patient_name: string;
  patient_ref: string | null;
  status: SessionStatus;
  status_label: string;
  created_at: string;
  updated_at: string;
  has_audio: boolean;
  has_transcript: boolean;
  has_draft: boolean;
  confirmed_version: number;
}

export interface SessionDetail extends SessionSummary {
  error_message: string | null;
  audio: AudioInfo | null;
  transcript: Transcript | null;
  draft: Draft | null;
  latest_record: ConfirmedRecord | null;
}

export interface SessionListResponse {
  items: SessionSummary[];
}

export interface DemoCase {
  key: string;
  title: string;
  description: string;
  audio_filename: string;
  audio_url: string;
  dialogue_preview: string;
}

export interface DemoCaseListResponse {
  items: DemoCase[];
}
