import { useEffect, useRef, useState } from "react";
import {
  createSession,
  generateDraft,
  getSession,
  saveManualTranscript,
  startTranscription,
  uploadSessionAudio,
} from "../api";
import type { SessionDetail } from "../types";
import { errorMessage } from "../utils";
export function NewConsultation({
  initialMode,
  disconnected,
  onComplete,
  onDirtyChange,
  onBusyChange,
}: {
  initialMode: "text" | "audio";
  disconnected: boolean;
  onComplete: (s: SessionDetail) => void;
  onDirtyChange: (v: boolean) => void;
  onBusyChange: (v: boolean) => void;
}) {
  const [mode, setMode] = useState(initialMode),
    [patient, setPatient] = useState(""),
    [reference, setReference] = useState(""),
    [text, setText] = useState(""),
    [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false),
    [progress, setProgress] = useState(""),
    [error, setError] = useState(""),
    [created, setCreated] = useState<SessionDetail | null>(null);
  const working = useRef(false);
  useEffect(() => {
    onDirtyChange(!!(patient || reference || text || file));
  }, [patient, reference, text, file, onDirtyChange]);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (working.current || disconnected) return;
    if (!patient.trim()) {
      setError("请输入患者姓名或代号。");
      return;
    }
    if (
      mode === "text" &&
      (!text.trim() ||
        text.length > 20000 ||
        text.split(/\r?\n/).filter((s) => s.trim()).length > 200)
    ) {
      setError("请输入问诊文字，最多 200 行、20,000 字符。");
      return;
    }
    if (
      mode === "audio" &&
      (!file ||
        !file.size ||
        file.size > 50 * 1024 * 1024 ||
        !/\.(wav|mp3|m4a|ogg|webm|flac)$/i.test(file.name))
    ) {
      setError(
        "请选择有效音频文件，支持 WAV、MP3、M4A、OGG、WebM、FLAC，最大 50 MB。",
      );
      return;
    }
    working.current = true;
    setBusy(true);
    onBusyChange(true);
    setError("");
    try {
      setProgress("正在创建问诊…");
      let next = created
        ? await getSession(created.id)
        : await createSession({
            patient_name: patient.trim(),
            patient_ref: reference.trim() || null,
          });
      setCreated(next);
      if (!next.transcript) {
        if (mode === "audio") {
          if (!next.audio) {
            setProgress("正在上传录音…");
            next = await uploadSessionAudio(next.id, file!);
            setCreated(next);
          }
          setProgress("正在识别问诊录音，请保持页面打开…");
          next = await startTranscription(next.id);
        } else {
          setProgress("正在保存问诊原文…");
          next = await saveManualTranscript(next.id, text.trim());
        }
        setCreated(next);
      }
      if (!next.draft) {
        setProgress("正在整理病历草稿…");
        next = await generateDraft(next.id);
        setCreated(next);
      }
      onDirtyChange(false);
      onComplete(next);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
      working.current = false;
      onBusyChange(false);
      setProgress("");
    }
  }
  return (
    <div className="intake-layout">
      <section className="surface">
        <div className="input-modes" role="group" aria-label="问诊输入方式">
          {(["text", "audio"] as const).map((m) => (
            <button
              key={m}
              aria-pressed={mode === m}
              className={mode === m ? "active" : ""}
              disabled={busy || !!created}
              onClick={() => setMode(m)}
            >
              {m === "text" ? "文字输入" : "音频导入"}
            </button>
          ))}
        </div>
        <form onSubmit={(e) => void submit(e)}>
          <fieldset disabled={busy || !!created}>
            <div className="form-grid">
              <label className="form-label">
                患者姓名或代号
                <input
                  value={patient}
                  maxLength={100}
                  required
                  onChange={(e) => setPatient(e.target.value)}
                  placeholder="请输入患者姓名或代号"
                />
              </label>
              <label className="form-label">
                就诊编号（选填）
                <input
                  value={reference}
                  maxLength={100}
                  onChange={(e) => setReference(e.target.value)}
                />
              </label>
            </div>
            {mode === "text" ? (
              <label className="form-label">
                问诊对话
                <textarea
                  rows={10}
                  maxLength={20000}
                  required
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="医生：哪里不舒服？&#10;患者：……"
                />
                <small>
                  {text.length} / 20000 字符 · 每行一段，最多 200 行
                </small>
              </label>
            ) : (
              <label className="upload-entry">
                选择问诊录音
                <input
                  type="file"
                  accept=".wav,.mp3,.m4a,.ogg,.webm,.flac"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                />
                <small>
                  {file
                    ? file.name
                    : "支持 WAV、MP3、M4A、OGG、WebM、FLAC · 最大 50 MB"}
                </small>
              </label>
            )}
          </fieldset>
          <p className="service-notice">
            音频和问诊文字将发送至已配置的模型服务，病历草稿须经医生核对确认。
          </p>
          <p role="status">{progress}</p>
          <p className="field-error" role="alert">
            {error}
          </p>
          <div className="page-actions">
            {created && !busy && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  onDirtyChange(false);
                  onComplete(created);
                }}
              >
                打开已保存会话
              </button>
            )}
            <button className="btn btn-primary" disabled={busy || disconnected}>
              {busy
                ? "正在处理…"
                : created
                  ? "继续处理此会话"
                  : "生成病历并进入审核 →"}
            </button>
          </div>
          {created && (
            <p className="small-note">
              问诊已建立。重试会继续当前会话，不会重复创建。
            </p>
          )}
        </form>
      </section>
      <aside className="intake-guidance">
        <p className="eyebrow">医生始终掌握最终记录</p>
        <h2>
          输入只是开始，
          <br />
          确认才是定稿。
        </h2>
        <p>原文、病历和来源并排展示，支持逐项核对与原音回听。</p>
        <ol>
          <li>文字与音频均可开始</li>
          <li>医生修改优先保留</li>
          <li>确认后锁定为只读</li>
        </ol>
      </aside>
    </div>
  );
}
