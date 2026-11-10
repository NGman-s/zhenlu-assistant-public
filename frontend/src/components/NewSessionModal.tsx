import { useState, type FormEvent } from "react";
import { Modal } from "./Modal";
import { errorMessage } from "../utils";

interface NewSessionModalProps {
  onClose: () => void;
  onCreate: (payload: {
    patient_name: string;
    patient_ref: string | null;
  }) => Promise<void>;
}

export function NewSessionModal({ onClose, onCreate }: NewSessionModalProps) {
  const [patientName, setPatientName] = useState("");
  const [patientRef, setPatientRef] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    const name = patientName.trim();
    if (!name) {
      setError("请填写患者称呼。");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onCreate({
        patient_name: name,
        patient_ref: patientRef.trim() || null,
      });
      onClose();
    } catch (createError) {
      setError(errorMessage(createError));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title="新建问诊会话"
      subtitle="为本次问诊建立记录，可输入文字或上传音频。"
      onClose={onClose}
      closeDisabled={submitting}
      footer={
        <>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onClose}
            disabled={submitting}
          >
            取消
          </button>
          <button
            type="submit"
            form="new-session-form"
            className="btn btn-primary"
            disabled={submitting}
          >
            {submitting ? "正在创建…" : "创建会话"}
          </button>
        </>
      }
    >
      <form id="new-session-form" className="form" onSubmit={handleSubmit}>
        <label className="form-field">
          <span className="form-label">
            患者称呼 <span className="required-mark">*</span>
          </span>
          <input
            className="text-input"
            value={patientName}
            onChange={(event) => setPatientName(event.target.value)}
            placeholder="例如：患者 A"
            maxLength={80}
            autoFocus
            disabled={submitting}
          />
          <span className="form-help">建议使用患者代号。</span>
        </label>

        <label className="form-field">
          <span className="form-label">患者编号 / 备注（可选）</span>
          <input
            className="text-input"
            value={patientRef}
            onChange={(event) => setPatientRef(event.target.value)}
            placeholder="例如：2026-001"
            maxLength={120}
            disabled={submitting}
          />
        </label>

        {error ? (
          <div className="inline-error" role="alert">
            {error}
          </div>
        ) : null}

        <div className="notice notice-muted">
          当前用于开发验证。音频和问诊文字将发送至模型服务，请确认资料处理授权。
        </div>
      </form>
    </Modal>
  );
}
