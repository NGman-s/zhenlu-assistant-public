import type { SessionSummary } from "../types";
import { formatShortDateTime, statusTone } from "../utils";

interface SidebarProps {
  sessions: SessionSummary[];
  selectedId: string | null;
  isLoading: boolean;
  deviceDisconnected: boolean;
  onSelect: (sessionId: string) => void;
  onCreate: () => void;
}

function BrandMark() {
  return (
    <div className="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 40 40" role="presentation">
        <path d="M10 9.5h14.5a5 5 0 0 1 5 5V30H15a5 5 0 0 1-5-5V9.5Z" />
        <path d="M15 23h3l2-6 3.5 9 2.2-5H29" />
      </svg>
    </div>
  );
}

export function Sidebar({
  sessions,
  selectedId,
  isLoading,
  deviceDisconnected,
  onSelect,
  onCreate,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <BrandMark />
        <div>
          <div className="brand-name">诊录助手</div>
          <div className="brand-subtitle">医生审核工作台</div>
        </div>
      </div>

      <button type="button" className="new-session-btn" onClick={onCreate} disabled={deviceDisconnected}>
        <span className="plus-mark" aria-hidden="true">
          +
        </span>
        新建问诊会话
      </button>

      <div className="session-section">
        <div className="session-section-head">
          <span>问诊会话</span>
          <span className="session-count">{sessions.length}</span>
        </div>

        <div className="session-list">
          {isLoading ? (
            <>
              <div className="session-skeleton" />
              <div className="session-skeleton" />
              <div className="session-skeleton" />
            </>
          ) : sessions.length === 0 ? (
            <div className="session-empty">
              <p>还没有会话</p>
              <span>点击上方按钮开始一次虚构病例演示。</span>
            </div>
          ) : (
            sessions.map((session) => {
              const active = session.id === selectedId;
              return (
                <button
                  type="button"
                  key={session.id}
                  className={`session-item${active ? " selected" : ""}`}
                  onClick={() => onSelect(session.id)}
                  aria-current={active ? "true" : undefined}
                >
                  <span
                    className={`status-dot tone-${statusTone(session.status)}`}
                    aria-hidden="true"
                  />
                  <span className="session-item-main">
                    <span className="session-patient">{session.patient_name}</span>
                    <span className="session-meta">
                      {session.status_label}
                      <span className="dot-separator">·</span>
                      {formatShortDateTime(session.updated_at)}
                    </span>
                  </span>
                  {session.confirmed_version > 0 ? (
                    <span className="session-version">v{session.confirmed_version}</span>
                  ) : null}
                </button>
              );
            })
          )}
        </div>
      </div>

      <div className="sidebar-footer">
        <div className="mock-mode-pill">
          <span className="pill-dot" aria-hidden="true" />
          虚构病例演示
        </div>
      </div>
    </aside>
  );
}
