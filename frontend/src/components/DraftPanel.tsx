import { useEffect, useState } from "react";
import type { BusyAction, Draft, SessionDetail } from "../types";
import { formatDateTime } from "../utils";
import { Modal } from "./Modal";

interface DraftPanelProps {
  workspace: SessionDetail;
  busy: BusyAction;
  selectedFieldKey: string | null;
  onSelectField: (fieldKey: string) => void;
  onGenerate: () => void;
  onSave: (
    fields: Array<{ field_key: string; value: string; accept_suggestion?: boolean }>,
    expectedRevision: number,
  ) => Promise<boolean>;
  onRegenerate: (expectedRevision: number) => Promise<boolean>;
  onConfirm: (expectedRevision: number) => Promise<boolean>;
  onCopy: () => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
  draftIsMock: boolean | null;
}

function DraftEmpty({
  workspace,
  busy,
  onGenerate,
  draftIsMock,
}: Pick<DraftPanelProps, "workspace" | "busy" | "onGenerate" | "draftIsMock">) {
  const manualTemplate = workspace.transcript?.provider === "manual" && draftIsMock === true;
  return (
    <section className="card draft-card">
      <header className="card-header">
        <div>
          <div className="heading-row">
            <h2>病历草稿</h2>
            <span className="badge badge-outline">尚未生成</span>
          </div>
        </div>
      </header>

      <div className="empty-panel draft-empty">
        {workspace.transcript ? (
          <>
            <h3>问诊内容已就绪</h3>
            <p>{manualTemplate ? "创建模板后，请根据问诊内容逐项填写。" : draftIsMock === false ? "生成时会将问诊文字发送到已配置的模型服务。" : "可以生成病历草稿，请核对所有内容。"}</p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={onGenerate}
              disabled={busy !== null}
            >
              {busy === "generate" ? (
                <>
                  <span className="spinner" aria-hidden="true" />
                  正在生成草稿…
                </>
              ) : (
                manualTemplate ? "创建病历模板" : draftIsMock === true ? "生成结构化草稿（模拟）" : "生成病历草稿"
              )}
            </button>
          </>
        ) : (
          <>
            <h3>等待问诊内容</h3>
            <p>录入文字或完成转写后，即可生成病历草稿。</p>
          </>
        )}
      </div>
    </section>
  );
}

interface DraftEditorProps extends DraftPanelProps {
  draft: Draft;
}

function DraftEditor({
  workspace,
  draft,
  busy,
  selectedFieldKey,
  onSelectField,
  onSave,
  onRegenerate,
  onConfirm,
  onCopy,
  onDirtyChange,
  draftIsMock,
}: DraftEditorProps) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(draft.fields.map((field) => [field.key, field.value])),
  );
  const [formError, setFormError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"confirm" | "regenerate" | null>(null);
  const [acceptedSuggestions, setAcceptedSuggestions] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setValues(
      Object.fromEntries(draft.fields.map((field) => [field.key, field.value])),
    );
    setFormError(null);
    setAcceptedSuggestions({});
  }, [draft.id, draft.revision]);

  const confirmed = draft.status === "confirmed";
  const manualTemplate = draft.provider === "manual-template";
  const anyBusy = busy !== null;
  const dirtyFields = draft.fields.filter(
    (field) => (values[field.key] ?? "").trim() !== field.value,
  );
  const dirty = dirtyFields.length > 0;
  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  const record = workspace.latest_record;
  const nextVersion = workspace.confirmed_version + 1;

  function updateValue(fieldKey: string, value: string) {
    setValues((current) => ({ ...current, [fieldKey]: value }));
    setAcceptedSuggestions((current) => ({ ...current, [fieldKey]: false }));
    setFormError(null);
  }

  function resetUnsaved() {
    setValues(
      Object.fromEntries(draft.fields.map((field) => [field.key, field.value])),
    );
    setFormError(null);
    setAcceptedSuggestions({});
  }

  async function handleSave() {
    if (!dirty || anyBusy) return;
    if (dirtyFields.some((field) => !(values[field.key] ?? "").trim())) {
      setFormError("字段内容不能为空，请填写“未提及”或具体的病历内容。");
      return;
    }
    setFormError(null);
    await onSave(
      dirtyFields.map((field) => ({
        field_key: field.key,
        value: (values[field.key] ?? "").trim(),
        accept_suggestion: acceptedSuggestions[field.key] === true,
      })),
      draft.revision,
    );
  }

  async function handleConfirm() {
    await onConfirm(draft.revision);
    setDialog(null);
  }

  async function handleRegenerate() {
    await onRegenerate(draft.revision);
    setDialog(null);
  }

  return (
    <section className="card draft-card">
      <header className="card-header">
        <div>
          <div className="heading-row">
            <h2>病历草稿</h2>
            {manualTemplate ? <span className="badge badge-outline">手动填写</span> : draft.provider.startsWith("qwen:") ? <span className="badge badge-outline">AI 草稿</span> : draft.is_mock ? <span className="badge badge-mock">模拟草稿</span> : null}
            {draft.has_doctor_edits ? (
              <span className="badge badge-doctor">含医生修改</span>
            ) : null}
            {confirmed ? <span className="badge badge-confirmed">已确认</span> : null}
          </div>
        </div>
      </header>

      {confirmed && record ? (
        <div className="confirmed-banner">
          <span className="confirmed-mark" aria-hidden="true">
            ✓
          </span>
          <div className="confirmed-copy">
            <strong>病历已确认 · 第 {record.version} 版</strong>
            <p>
              确认于 {formatDateTime(record.confirmed_at)} · 来自草稿 r
              {record.draft_revision}
            </p>
          </div>
          <button type="button" className="btn btn-primary btn-small" onClick={onCopy}>
            复制病历文本
          </button>
        </div>
      ) : null}

      {manualTemplate && !confirmed ? <p className="transcript-notice">这是待填写模板，不会自动提取内容。请逐项核对“未提及”并手动填写。</p> : null}
      <div className="field-list">
        {draft.fields.map((field) => {
          const fieldDirty =
            (values[field.key] ?? "").trim() !== field.value;
          const selected = selectedFieldKey === field.key;
          return (
            <div
              className={`field-block${selected ? " source-selected" : ""}${
                fieldDirty ? " dirty" : ""
              }`}
              key={field.key}
            >
              <div className="field-head">
                <div className="field-title-row">
                  <label className="field-label" htmlFor={`draft-field-${field.key}`}>
                    {field.label}
                  </label>
                  {field.origin === "doctor" ? (
                    <span className="badge badge-doctor">医生修改</span>
                  ) : null}
                  {fieldDirty ? (
                    <span className="badge badge-dirty">未保存</span>
                  ) : null}
                </div>
                <button
                  type="button"
                  className={`source-link${selected ? " selected" : ""}`}
                  onClick={() => onSelectField(field.key)}
                  aria-pressed={selected}
                >
                  {field.sources.length > 0
                    ? `查看来源 ${field.sources.length}`
                    : "无来源"}
                </button>
              </div>

              {confirmed ? (
                <div className="field-readonly">{field.value}</div>
              ) : (
                <textarea
                  id={`draft-field-${field.key}`}
                  className="field-textarea"
                  value={values[field.key] ?? ""}
                  onChange={(event) => updateValue(field.key, event.target.value)}
                  rows={2}
                  maxLength={4000}
                  disabled={anyBusy}
                />
              )}

              {field.suggestion && !confirmed ? (
                <div className="suggestion-box">
                  <div className="suggestion-head">
                    <span className="badge badge-warning">系统新建议</span>
                    <span>未覆盖当前医生修改内容</span>
                  </div>
                  <p>{field.suggestion.value}</p>
                  <button
                    type="button"
                    className="btn btn-tiny"
                    onClick={() => {
                      updateValue(field.key, field.suggestion?.value ?? "");
                      setAcceptedSuggestions((current) => ({ ...current, [field.key]: true }));
                    }}
                    disabled={anyBusy}
                  >
                    填入建议值
                  </button>
                </div>
              ) : null}

              {(field.origin === "doctor" && field.edited_at) ||
              (field.sources.length === 0 && !field.is_unmentioned && field.origin === "ai") ? (
                <div className="field-foot">
                  {field.origin === "doctor" && field.edited_at ? (
                    <span>医生修改于 {formatDateTime(field.edited_at)}</span>
                  ) : null}
                  {field.sources.length === 0 && !field.is_unmentioned && field.origin === "ai" ? (
                    <span className="field-warning">无原文来源，请人工核对</span>
                  ) : null}
                </div>
              ) : null}

              {!manualTemplate && field.origin === "doctor" && field.ai_value !== field.value ? (
                <details className="ai-original">
                  <summary>查看系统原始草稿</summary>
                  <p>{field.ai_value}</p>
                </details>
              ) : null}
            </div>
          );
        })}
      </div>

      {confirmed ? (
        <>
          {record ? (
            <details className="text-preview">
              <summary>查看可复制纯文本</summary>
              <pre>{record.text}</pre>
            </details>
          ) : null}
          <p className="locked-note">
            确认版本已单独保存并锁定，当前页面不能继续修改。医生修改与自动草稿已分别保留。
          </p>
        </>
      ) : (
        <footer className="draft-footer">
          <div className="draft-footer-status" aria-live="polite">
            {formError ? (
              <p className="field-error" role="alert">
                {formError}
              </p>
            ) : dirty ? (
              <p className="unsaved-hint">
                有 {dirtyFields.length} 处未保存修改
                <button type="button" className="text-btn" onClick={resetUnsaved}>
                  撤销
                </button>
              </p>
            ) : null}
          </div>

          <div className="draft-actions">
            {!manualTemplate || draftIsMock === false ? <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setDialog("regenerate")}
              disabled={anyBusy || dirty}
              title={dirty ? "请先保存或撤销未保存修改" : undefined}
            >
              {busy === "regenerate" ? (
                <>
                  <span className="spinner dark" aria-hidden="true" />
                  正在重生成…
                </>
              ) : (
                draftIsMock === true ? "重新生成（模拟）" : "重新生成"
              )}
            </button> : null}
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleSave}
              disabled={anyBusy || !dirty}
            >
              {busy === "save" ? "保存中…" : "保存修改"}
            </button>
            <button
              type="button"
              className="btn btn-confirm"
              onClick={() => setDialog("confirm")}
              disabled={anyBusy || dirty}
              title={dirty ? "请先保存修改" : undefined}
            >
              {busy === "confirm" ? "确认中…" : "确认病历"}
            </button>
          </div>
        </footer>
      )}

      {dialog === "confirm" ? (
        <Modal
          title="确认病历并锁定版本"
          subtitle="确认前请再次核对字段内容与原文来源。"
          onClose={() => setDialog(null)}
          closeDisabled={busy === "confirm"}
          footer={
            <>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setDialog(null)}
                disabled={busy === "confirm"}
              >
                返回检查
              </button>
              <button
                type="button"
                className="btn btn-confirm"
                onClick={handleConfirm}
                disabled={busy === "confirm"}
              >
                {busy === "confirm" ? "正在确认…" : `确认并生成第 ${nextVersion} 版`}
              </button>
            </>
          }
        >
          <div className="confirm-summary">
            <dl>
              <div>
                <dt>患者</dt>
                <dd>{workspace.patient_name}</dd>
              </div>
              <div>
                <dt>字段</dt>
                <dd>{draft.fields.length} 项</dd>
              </div>
              <div>
                <dt>来源草稿</dt>
                <dd>r{draft.revision}</dd>
              </div>
              <div>
                <dt>医生修改</dt>
                <dd>{draft.has_doctor_edits ? "有，已保留" : "无"}</dd>
              </div>
            </dl>
            {draft.has_suggestions ? (
              <div className="notice notice-warning">
                当前仍有系统新建议未处理。确认将使用医生当前字段内容，未采纳的系统建议不会写入确认记录。
              </div>
            ) : null}
            <div className="notice notice-warning">
              确认后将保存当前内容为只读版本，并锁定草稿。锁定后不能继续编辑或重新生成。
            </div>
            {record ? (
              <p className="dialog-footnote">
                该会话已有第 {record.version} 版确认记录；本阶段不支持二次确认。
              </p>
            ) : null}
          </div>
        </Modal>
      ) : null}

      {dialog === "regenerate" ? (
        <Modal
          title="重新生成草稿"
          subtitle={draftIsMock === false ? "将问诊文字发送至模型服务，并根据字段来源决定是否更新。" : "系统会再次生成草稿，并根据字段来源决定是否更新。"}
          onClose={() => setDialog(null)}
          closeDisabled={busy === "regenerate"}
          footer={
            <>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setDialog(null)}
                disabled={busy === "regenerate"}
              >
                取消
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleRegenerate}
                disabled={busy === "regenerate"}
              >
                {busy === "regenerate" ? "正在重新生成…" : "确认重新生成"}
              </button>
            </>
          }
        >
          <div className="notice notice-muted">
            系统生成且未被医生修改的字段会更新；医生已修改的字段不会被覆盖，系统结果只会作为建议展示，需医生主动填入。
          </div>
        </Modal>
      ) : null}
    </section>
  );
}

export function DraftPanel(props: DraftPanelProps) {
  const { workspace } = props;
  if (!workspace.draft) {
    return (
      <DraftEmpty
        workspace={workspace}
        busy={props.busy}
        onGenerate={props.onGenerate}
        draftIsMock={props.draftIsMock}
      />
    );
  }
  return <DraftEditor {...props} draft={workspace.draft} />;
}
