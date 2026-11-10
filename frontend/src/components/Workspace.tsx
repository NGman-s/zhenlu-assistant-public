import { useEffect, useState } from "react";
import {
  confirmDraft,
  generateDraft,
  regenerateDraft,
  saveManualTranscript,
  saveDraftFields,
  startTranscription,
  uploadSessionAudio,
} from "../api";
import type { BusyAction, SessionDetail } from "../types";
import {
  copyToClipboard,
  errorMessage,
  statusTone,
} from "../utils";
import { AudioPanel } from "./AudioPanel";
import { DraftPanel } from "./DraftPanel";
import { SourcePanel } from "./SourcePanel";
import { StatusStepper } from "./StatusStepper";
import { TranscriptPanel } from "./TranscriptPanel";
import type { ToastTone } from "./Toasts";

interface WorkspaceProps {
  workspace: SessionDetail;
  notify: (tone: ToastTone, message: string) => void;
  onWorkspaceUpdated: (workspace: SessionDetail) => void;
  onDirtyChange: (dirty: boolean) => void;
}

export function Workspace({
  workspace,
  notify,
  onWorkspaceUpdated,
  onDirtyChange,
}: WorkspaceProps) {
  const [busy, setBusy] = useState<BusyAction>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [selectedFieldKey, setSelectedFieldKey] = useState<string | null>(null);
  const [sourceFocusToken, setSourceFocusToken] = useState(0);

  useEffect(() => {
    if (!workspace.draft) {
      setSelectedFieldKey(null);
      return;
    }
    setSelectedFieldKey((current) => {
      if (current && workspace.draft?.fields.some((field) => field.key === current)) {
        return current;
      }
      return (
        workspace.draft?.fields.find((field) => field.sources.length > 0)?.key ??
        workspace.draft?.fields[0]?.key ??
        null
      );
    });
  }, [workspace]);

  async function runAction(
    action: Exclude<BusyAction, null>,
    task: () => Promise<SessionDetail>,
    successMessage: string | ((next: SessionDetail) => string),
  ): Promise<boolean> {
    if (busy) return false;
    setBusy(action);
    setActionError(null);
    try {
      const next = await task();
      onWorkspaceUpdated(next);
      notify(
        "success",
        typeof successMessage === "function"
          ? successMessage(next)
          : successMessage,
      );
      return true;
    } catch (error) {
      const message = errorMessage(error);
      setActionError(message);
      notify("error", message);
      return false;
    } finally {
      setBusy(null);
    }
  }

  function handleUpload(file: File) {
    void runAction(
      "upload",
      () => uploadSessionAudio(workspace.id, file),
      "音频已上传并保存到本机。",
    );
  }

  function handleTranscribe() {
    void runAction(
      "transcribe",
      () => startTranscription(workspace.id),
      "转写已完成，请核对对话内容。",
    );
  }

  async function handleManualTranscript(text: string): Promise<boolean> {
    return runAction(
      "transcribe",
      () => saveManualTranscript(workspace.id, text),
      "问诊内容已保存，可以生成病历草稿。",
    );
  }

  function handleGenerate() {
    void runAction(
      "generate",
      () => generateDraft(workspace.id),
      "病历草稿已生成，请逐项核对。",
    );
  }

  async function handleSave(
    fields: Array<{ field_key: string; value: string; accept_suggestion?: boolean }>,
    expectedRevision: number,
  ): Promise<boolean> {
    return runAction(
      "save",
      () => saveDraftFields(workspace.id, expectedRevision, fields),
      "医生修改已保存。",
    );
  }

  async function handleRegenerate(expectedRevision: number): Promise<boolean> {
    return runAction(
      "regenerate",
      () => regenerateDraft(workspace.id, expectedRevision),
      (next) =>
        next.draft?.has_suggestions
          ? "已重新生成；医生修改未被覆盖，请查看系统新建议。"
          : "已重新生成；医生修改过的字段保持不变。",
    );
  }

  async function handleConfirm(expectedRevision: number): Promise<boolean> {
    return runAction(
      "confirm",
      () => confirmDraft(workspace.id, expectedRevision),
      (next) =>
        `病历已确认为第 ${next.latest_record?.version ?? 1} 版，可以复制纯文本。`,
    );
  }

  async function handleCopy(): Promise<void> {
    const text = workspace.latest_record?.text;
    if (!text) {
      notify("error", "尚未生成已确认的病历文本。");
      return;
    }
    const copied = await copyToClipboard(text);
    notify(
      copied ? "success" : "error",
      copied ? "已复制已确认病历为纯文本。" : "复制失败，请手动选择文本复制。",
    );
  }

  function handleSelectSource(fieldKey: string) {
    setSelectedFieldKey(fieldKey);
    setSourceFocusToken((token) => token + 1);
    if (window.matchMedia("(max-width: 1200px)").matches) {
      window.setTimeout(() => {
        document
          .getElementById("source-panel")
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 60);
    }
  }

  const sourceField =
    workspace.draft?.fields.find((field) => field.key === selectedFieldKey) ?? null;
  const highlightIds = sourceField?.sources.map((source) => source.id) ?? [];

  return (
    <div className="workspace">
      <header className="workspace-header">
        <div className="workspace-title-block">
          <div className="title-line">
            <h1>{workspace.patient_name}</h1>
            {workspace.patient_ref ? (
              <span className="patient-ref">{workspace.patient_ref}</span>
            ) : null}
          </div>
          <p className="workspace-meta">
            <span title={workspace.id}>会话 {workspace.id.slice(0, 8).toUpperCase()}</span>
          </p>
        </div>
        <div className="workspace-header-actions">
          <span
            className={`status-chip tone-${statusTone(workspace.status)}`}
            data-status={workspace.status}
          >
            <span className="status-dot" aria-hidden="true" />
            {workspace.status_label}
          </span>
        </div>
      </header>

      <p className="service-notice">
        音频和问诊文字将发送至已配置的模型服务，病历草稿须经医生核对确认。
      </p>

      <StatusStepper
        status={workspace.status}
        hasAudio={workspace.audio !== null}
        hasTranscript={workspace.transcript !== null}
        hasDraft={workspace.draft !== null}
        busy={busy}
      />

      {workspace.status === "failed" && workspace.error_message ? (
        <div className="alert alert-error" role="alert">
          <div>
            <strong>上次处理失败</strong>
            <p>{workspace.error_message}</p>
          </div>
        </div>
      ) : null}

      {actionError ? (
        <div className="alert alert-error" role="alert">
          <div>
            <strong>操作未完成</strong>
            <p>{actionError}</p>
          </div>
          <button
            type="button"
            className="alert-close"
            onClick={() => setActionError(null)}
            aria-label="关闭错误提示"
          >
            ×
          </button>
        </div>
      ) : null}

      {!workspace.transcript || workspace.audio ? <AudioPanel
        workspace={workspace}
        busy={busy}
        onUpload={handleUpload}
      /> : null}

      <div className="review-grid">
        <TranscriptPanel
          workspace={workspace}
          busy={busy}
          highlightIds={highlightIds}
          focusToken={sourceFocusToken}
          onTranscribe={handleTranscribe}
          onManualSave={handleManualTranscript}
          onDirtyChange={onDirtyChange}
        />
        <DraftPanel
          workspace={workspace}
          busy={busy}
          selectedFieldKey={selectedFieldKey}
          onSelectField={handleSelectSource}
          onGenerate={handleGenerate}
          onSave={handleSave}
          onRegenerate={handleRegenerate}
          onConfirm={handleConfirm}
          onCopy={handleCopy}
          onDirtyChange={onDirtyChange}
        />
        <SourcePanel
          workspace={workspace}
          field={sourceField}
          onSelectField={handleSelectSource}
        />
      </div>

    </div>
  );
}
