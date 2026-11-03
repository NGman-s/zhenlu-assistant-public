import { useEffect, useRef, useState } from "react";
import type { BusyAction, SessionDetail } from "../types";
import { formatTimestamp } from "../utils";

interface TranscriptPanelProps {
  workspace: SessionDetail;
  busy: BusyAction;
  highlightIds: string[];
  focusToken: number;
  onTranscribe: () => void;
  onManualSave: (text: string) => Promise<boolean>;
  onDirtyChange: (dirty: boolean) => void;
}

function EmptyWaveform() {
  return (
    <div className="empty-wave" aria-hidden="true">
      <span />
      <span />
      <span />
      <span />
      <span />
      <span />
      <span />
    </div>
  );
}

export function TranscriptPanel({
  workspace,
  busy,
  highlightIds,
  focusToken,
  onTranscribe,
  onManualSave,
  onDirtyChange,
}: TranscriptPanelProps) {
  const transcript = workspace.transcript;
  const [manualOpen, setManualOpen] = useState(false);
  const [manualText, setManualText] = useState("");
  const lineCount = manualText.split(/\r?\n/).filter((line) => line.trim()).length;
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (focusToken === 0) return;
    const container = listRef.current;
    if (!container) return;
    const target = container.querySelector<HTMLElement>('[data-highlighted="true"]');
    if (!target) return;
    const containerRect = container.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const nextScrollTop =
      container.scrollTop + targetRect.top - containerRect.top - 12;
    container.scrollTo({ top: Math.max(0, nextScrollTop), behavior: "smooth" });
  }, [focusToken]);

  const highlightSet = new Set(highlightIds);

  return (
    <section className="card transcript-card">
      <header className="card-header">
        <div>
          <div className="heading-row">
            <h2>问诊转写</h2>
            {transcript?.provider === "manual" ? (
              <span className="badge badge-outline">手动录入</span>
            ) : transcript?.is_mock ? (
              <span className="badge badge-mock">模拟转写</span>
            ) : null}
          </div>
        </div>
        {transcript ? (
          <span className="revision-chip">{transcript.segments.length} 句</span>
        ) : null}
      </header>

      {!transcript ? (
        <div className="empty-panel">
              <EmptyWaveform />
              <h3>{workspace.audio ? "音频已就绪" : "录入问诊内容"}</h3>
              <p>{workspace.audio ? "选择示例转写，或手动录入问诊内容。" : "可直接输入问诊文字，也可以先上传音频。"}</p>
              {manualOpen ? (
                <div className="manual-transcript">
                  <label htmlFor="manual-transcript">问诊内容（每行一段）</label>
                  <textarea
                    id="manual-transcript"
                    className="field-textarea"
                    rows={7}
                    maxLength={20000}
                    value={manualText}
                    disabled={busy !== null}
                    onChange={(event) => {
                      setManualText(event.target.value);
                      onDirtyChange(Boolean(event.target.value.trim()));
                    }}
                    placeholder="请输入问诊内容，每行一段。"
                  />
                  <p>手动内容不会自动关联音频时间；保存后不可编辑。</p>
                  {lineCount > 200 ? <p className="field-error" role="alert">最多输入 200 行。</p> : null}
                  <div className="manual-actions">
                    <button type="button" className="btn btn-secondary" disabled={busy !== null} onClick={() => {
                      setManualOpen(false); setManualText(""); onDirtyChange(false);
                    }}>取消</button>
                    <button type="button" className="btn btn-primary" disabled={busy !== null || !manualText.trim() || lineCount > 200} onClick={async () => {
                      if (await onManualSave(manualText)) onDirtyChange(false);
                    }}>{busy === "transcribe" ? "保存中…" : "保存问诊内容"}</button>
                  </div>
                </div>
              ) : <>
              {workspace.audio ? <button
                type="button"
                className="btn btn-primary"
                onClick={onTranscribe}
                disabled={busy !== null}
              >
                {busy === "transcribe" ? (
                  <>
                    <span className="spinner" aria-hidden="true" />
                    正在模拟转写…
                  </>
                ) : (
                  "开始模拟转写"
                )}
              </button> : null}
              <button type="button" className="btn btn-secondary" onClick={() => setManualOpen(true)} disabled={busy !== null}>
                手动录入问诊内容
              </button>
              </>}
        </div>
      ) : (
        <>
          {transcript.provider === "manual" ? (
            <p className="transcript-notice">手动录入，未经过语音识别；无音频时间定位。</p>
          ) : transcript.is_mock && !transcript.has_reliable_timestamps ? (
            <p className="transcript-notice">未匹配内置示例，当前显示默认模拟对话。</p>
          ) : null}

          <div className="transcript-list" ref={listRef}>
            {transcript.segments.map((segment) => {
              const highlighted = highlightSet.has(segment.id);
              const speakerClass =
                segment.speaker === "医生"
                  ? "doctor"
                  : segment.speaker === "患者"
                    ? "patient"
                    : "unknown";
              return (
                <article
                  key={segment.id}
                  id={`segment-${segment.id}`}
                  className={`segment${highlighted ? " highlighted" : ""}`}
                  data-highlighted={highlighted ? "true" : "false"}
                >
                  <div className="segment-side">
                    <span className={`speaker-chip ${speakerClass}`}>
                      {segment.speaker}
                    </span>
                    {segment.start_ms != null && segment.end_ms != null ? (
                      <span className="segment-time">
                        {formatTimestamp(segment.start_ms)}–
                        {formatTimestamp(segment.end_ms)}
                      </span>
                    ) : null}
                  </div>
                  <p className="segment-text">{segment.text}</p>
                </article>
              );
            })}
          </div>

        </>
      )}
    </section>
  );
}
