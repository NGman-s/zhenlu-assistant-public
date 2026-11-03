import type {
  DemoCase,
  DemoCaseListResponse,
  SessionDetail,
  SessionListResponse,
} from "./types";

const API_BASE = "/api";

export class ApiRequestError extends Error {
  status: number;
  code: string;

  constructor(message: string, status: number, code = "request_failed") {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

interface ErrorBody {
  code?: string;
  message?: string;
  detail?: unknown;
}

async function parseError(response: Response): Promise<ApiRequestError> {
  let body: ErrorBody | null = null;
  try {
    body = (await response.json()) as ErrorBody;
  } catch {
    body = null;
  }
  const message =
    (typeof body?.message === "string" && body.message) ||
    (typeof body?.detail === "string" && body.detail) ||
    `请求失败（HTTP ${response.status}）。`;
  return new ApiRequestError(message, response.status, body?.code);
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiRequestError(
      "无法连接后端服务，请确认 FastAPI 已在 8000 端口启动。",
      0,
      "network_error",
    );
  }
  if (!response.ok) {
    throw await parseError(response);
  }
  return (await response.json()) as T;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export function listSessions(signal?: AbortSignal): Promise<SessionListResponse> {
  return request<SessionListResponse>("/sessions", { signal });
}

export function getHealth(signal?: AbortSignal): Promise<{ draft_is_mock: boolean }> {
  return request<{ draft_is_mock: boolean }>("/health", { signal });
}

export function getSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<SessionDetail> {
  return request<SessionDetail>(`/sessions/${encodeURIComponent(sessionId)}`, {
    signal,
  });
}

export function createSession(payload: {
  patient_name: string;
  patient_ref?: string | null;
}): Promise<SessionDetail> {
  return request<SessionDetail>("/sessions", jsonInit("POST", payload));
}

export function uploadSessionAudio(
  sessionId: string,
  file: File,
): Promise<SessionDetail> {
  const form = new FormData();
  form.append("file", file);
  return request<SessionDetail>(
    `/sessions/${encodeURIComponent(sessionId)}/audio`,
    { method: "POST", body: form },
  );
}

export function startTranscription(sessionId: string): Promise<SessionDetail> {
  return request<SessionDetail>(
    `/sessions/${encodeURIComponent(sessionId)}/transcript`,
    { method: "POST" },
  );
}

export function saveManualTranscript(sessionId: string, text: string): Promise<SessionDetail> {
  return request<SessionDetail>(
    `/sessions/${encodeURIComponent(sessionId)}/transcript/manual`,
    jsonInit("POST", { text }),
  );
}

export function generateDraft(sessionId: string): Promise<SessionDetail> {
  return request<SessionDetail>(
    `/sessions/${encodeURIComponent(sessionId)}/draft`,
    { method: "POST" },
  );
}

export function saveDraftFields(
  sessionId: string,
  expectedRevision: number,
  fields: Array<{ field_key: string; value: string; accept_suggestion?: boolean }>,
): Promise<SessionDetail> {
  return request<SessionDetail>(
    `/sessions/${encodeURIComponent(sessionId)}/draft`,
    jsonInit("PATCH", { expected_revision: expectedRevision, fields }),
  );
}

export function regenerateDraft(
  sessionId: string,
  expectedRevision: number,
): Promise<SessionDetail> {
  return request<SessionDetail>(
    `/sessions/${encodeURIComponent(sessionId)}/draft/regenerate`,
    jsonInit("POST", { expected_revision: expectedRevision }),
  );
}

export function confirmDraft(
  sessionId: string,
  expectedRevision: number,
): Promise<SessionDetail> {
  return request<SessionDetail>(
    `/sessions/${encodeURIComponent(sessionId)}/confirm`,
    jsonInit("POST", { expected_revision: expectedRevision }),
  );
}

export function listDemoCases(signal?: AbortSignal): Promise<DemoCaseListResponse> {
  return request<DemoCaseListResponse>("/demo/cases", { signal });
}

export async function fetchDemoAudio(demoCase: DemoCase): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/demo/cases/${encodeURIComponent(demoCase.key)}/audio`);
  } catch {
    throw new ApiRequestError("无法加载示例音频，请检查后端服务。", 0, "network_error");
  }
  if (!response.ok) {
    throw await parseError(response);
  }
  return await response.blob();
}
