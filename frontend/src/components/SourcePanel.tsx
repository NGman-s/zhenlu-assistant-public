import type { DraftField, SessionDetail, TranscriptSegment } from "../types";
import { formatTimestamp } from "../utils";

interface SourcePanelProps {
  workspace: SessionDetail;
  field: DraftField | null;
  onSelectField: (fieldKey: string) => void;
}

export function SourcePanel({
  workspace,
  field,
  onSelectField,
}: SourcePanelProps) {
  const transcript = workspace.transcript;
  const audio = workspace.audio;

  function seekAndPlay(source: TranscriptSegment) {
    window.dispatchEvent(
      new CustomEvent("zhenlu:play-source", {
        detail: { sessionId: workspace.id, source },
      }),
    );
  }

  return (
    <aside className="card source-card" id="source-panel">
      <header className="card-header compact">
        <div>
          <h2>原文来源</h2>
        </div>
      </header>

      {!transcript ? (
        <div className="source-empty">
          <p>完成语音转写后，字段可关联到问诊原句。</p>
        </div>
      ) : !field ? (
        <div className="source-empty">
          <p>点击病历字段旁的“查看来源”，在这里核对对应原文。</p>
          <div className="source-field-shortcuts">
            {workspace.draft?.fields
              .filter((draftField) => draftField.sources.length > 0)
              .slice(0, 4)
              .map((draftField) => (
                <button
                  type="button"
                  key={draftField.key}
                  onClick={() => onSelectField(draftField.key)}
                >
                  {draftField.label}
                </button>
              ))}
          </div>
        </div>
      ) : (
        <div className="source-content">
          <div className="source-field-head">
            <div>
              <span className="source-field-label">{field.label}</span>
              <span className="source-field-count">
                {field.sources.length > 0
                  ? `${field.sources.length} 句关联原文`
                  : "无关联原文"}
              </span>
            </div>
          </div>

          {field.origin === "doctor" ? (
            <p className="source-caution">
              当前字段含医生修改。以下来源是系统草稿生成时关联的原文，不自动代表修改后的新内容。
            </p>
          ) : null}

          {field.sources.length === 0 ? (
            <div className="source-empty inline">
              <p>没有关联原文。</p>
            </div>
          ) : (
            <div className="source-list">
              {field.sources.map((source, index) => (
                <article className="source-item" key={source.id}>
                  <div className="source-item-head">
                    <span
                      className={`speaker-chip ${
                        source.speaker === "医生"
                          ? "doctor"
                          : source.speaker === "患者"
                            ? "patient"
                            : "unknown"
                      }`}
                    >
                      {source.speaker}
                    </span>
                    <span className="source-seq">原文 {index + 1}</span>
                  </div>
                  <blockquote className="source-quote">
                    {source.text}
                  </blockquote>
                  <div className="source-item-foot">
                    {transcript.has_reliable_timestamps &&
                    source.start_ms != null &&
                    source.end_ms != null &&
                    source.end_ms > source.start_ms ? (
                      <>
                        <span className="source-time">
                          {formatTimestamp(source.start_ms)}–
                          {formatTimestamp(source.end_ms)}
                        </span>
                        {audio ? (
                          <button
                            type="button"
                            className="text-btn"
                            onClick={() => seekAndPlay(source)}
                          >
                            回听此段
                          </button>
                        ) : null}
                      </>
                    ) : (
                      <span className="source-time muted">无可靠时间信息</span>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
