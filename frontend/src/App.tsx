import { useCallback, useEffect, useRef, useState } from "react";
import { getSession, listSessions } from "./api";
import { AuthBoundary, authenticationEnabled, type AuthUser } from "./auth";
import type { SessionDetail, SessionSummary } from "./types";
import { errorMessage, formatShortDateTime } from "./utils";
import {
  defaultTemplates,
  loadTemplates,
  saveTemplates,
  type TemplateSettings,
} from "./templates";
import { NewConsultation } from "./components/NewConsultation";
import { TemplateManager } from "./components/TemplateManager";
import { Workspace } from "./components/Workspace";
import {
  ToastStack,
  type ToastItem,
  type ToastTone,
} from "./components/Toasts";
const pages = {
  home: "首页",
  new: "新建问诊",
  workbench: "审核工作台",
  records: "病历记录",
  templates: "模板管理",
  settings: "设置",
};
type Page = keyof typeof pages;
function initialPage(): Page {
  const route = location.hash.slice(1);
  return route in pages ? (route as Page) : "home";
}
const confirmed = (s: SessionSummary) =>
  s.status === "confirmed" || s.confirmed_version > 0;
function AppWorkspace({
  user,
  logout,
}: {
  user: AuthUser | null;
  logout: () => Promise<void>;
}) {
  const owner = user?.id || "local-single-user";
  const [page, setPage] = useState<Page>(initialPage),
    [mode, setMode] = useState<"text" | "audio">("text");
  const [sessions, setSessions] = useState<SessionSummary[]>([]),
    [workspace, setWorkspace] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true),
    [detailLoading, setDetailLoading] = useState(false),
    [error, setError] = useState("");
  const [dirty, setDirty] = useState(false),
    [busy, setBusy] = useState(false),
    [compact, setCompact] = useState(false);
  const [filter, setFilter] = useState("all"),
    [query, setQuery] = useState(""),
    [toasts, setToasts] = useState<ToastItem[]>([]);
  const [templates, setTemplates] =
    useState<TemplateSettings>(defaultTemplates);
  const [device, setDevice] = useState<{
    managed: boolean;
    connected: boolean;
  } | null>(null);
  const [density, setDensity] = useState("comfortable");
  const requestId = useRef(0),
    selectedId = useRef<string | null>(null),
    nextToast = useRef(0),
    mounted = useRef(true);
  const notify = useCallback((tone: ToastTone, message: string) => {
    const id = ++nextToast.current;
    setToasts((v) => [...v.slice(-3), { id, tone, message }]);
    window.setTimeout(() => {
      if (mounted.current) setToasts((v) => v.filter((t) => t.id !== id));
    }, 5000);
  }, []);
  const refresh = useCallback(async () => {
    try {
      const data = await listSessions();
      if (mounted.current) {
        setSessions(data.items);
        setError("");
      }
    } catch (e) {
      if (mounted.current) setError(errorMessage(e));
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    try {
      setTemplates(loadTemplates(owner));
    } catch (e) {
      notify("error", errorMessage(e));
    }
    return () => {
      mounted.current = false;
      requestId.current++;
    };
  }, [owner, refresh, notify]);
  useEffect(() => {
    if (initialPage() !== "workbench") return;
    let id: string | null = null;
    try {
      id = localStorage.getItem(`zhenlu.selected.${owner}`);
    } catch {
      return;
    }
    if (!id) return;
    const controller = new AbortController();
    selectedId.current = id;
    setDetailLoading(true);
    void getSession(id, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) setWorkspace(next);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorMessage(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [owner]);
  useEffect(() => {
    let cancelled = false,
      managed = false;
    async function check() {
      try {
        const r = await fetch("/api/device/status", {
          cache: "no-store",
          credentials: "same-origin",
        });
        if (!r.ok) throw Error();
        const next = (await r.json()) as {
          managed: boolean;
          connected: boolean;
        };
        managed = next.managed;
        if (!cancelled) setDevice(next);
      } catch {
        if (!cancelled && managed)
          setDevice((v) => (v ? { ...v, connected: false } : v));
      }
    }
    void check();
    const timer = setInterval(() => void check(), 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);
  const disconnected = device?.managed === true && !device.connected;
  const canLeave = useCallback(() => {
    if (busy) {
      notify("info", "正在处理当前会话，请稍候。");
      return false;
    }
    return (
      !dirty || confirm("当前有未保存修改，离开会放弃这些输入，确定继续？")
    );
  }, [busy, dirty, notify]);
  const navigate = useCallback(
    (next: Page) => {
      if (next === page) return;
      if (!canLeave()) {
        history.replaceState(null, "", `#${page}`);
        return;
      }
      document.querySelectorAll("audio").forEach((a) => a.pause());
      setDirty(false);
      setPage(next);
      setCompact(false);
      history.replaceState(null, "", `#${next}`);
    },
    [canLeave, page],
  );
  useEffect(() => {
    const hash = () => navigate(initialPage());
    window.addEventListener("hashchange", hash);
    return () => window.removeEventListener("hashchange", hash);
  }, [navigate]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty || busy) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, busy]);
  useEffect(() => {
    document.title = `诊录助手 · ${pages[page]}`;
  }, [page]);
  async function open(id: string) {
    if (!canLeave()) return;
    setDirty(false);
    document.querySelectorAll("audio").forEach((a) => a.pause());
    const token = ++requestId.current;
    selectedId.current = id;
    setDetailLoading(true);
    setWorkspace(null);
    setPage("workbench");
    history.replaceState(null, "", "#workbench");
    setError("");
    try {
      const next = await getSession(id);
      if (token === requestId.current && mounted.current) {
        setWorkspace(next);
        try {
          localStorage.setItem(`zhenlu.selected.${owner}`, id);
        } catch {
          /* Remembering selection is optional. */
        }
      }
    } catch (e) {
      if (token === requestId.current && mounted.current)
        setError(errorMessage(e));
    } finally {
      if (token === requestId.current && mounted.current)
        setDetailLoading(false);
    }
  }
  function newSession(input: "text" | "audio") {
    if (!canLeave()) return;
    setDirty(false);
    setMode(input);
    setPage("new");
    history.replaceState(null, "", "#new");
  }
  function updated(next: SessionDetail) {
    if (!mounted.current) return;
    if (selectedId.current === next.id) setWorkspace(next);
    void refresh();
  }
  function created(next: SessionDetail) {
    try {
      localStorage.setItem(`zhenlu.selected.${owner}`, next.id);
    } catch {
      /* optional */
    }
    selectedId.current = next.id;
    setWorkspace(next);
    setDirty(false);
    setPage("workbench");
    history.replaceState(null, "", "#workbench");
    void refresh();
  }
  function saveTemplate(next: TemplateSettings) {
    try {
      saveTemplates(owner, next);
      setTemplates(next);
      notify("success", "机构模板已保存。");
      return true;
    } catch {
      notify("error", "模板保存失败，请检查浏览器存储空间。");
      return false;
    }
  }
  async function signOut() {
    if (!canLeave()) return;
    if (!confirm("确定退出当前账号？")) return;
    try {
      await logout();
    } catch (e) {
      notify("error", errorMessage(e));
    }
  }
  const pending = sessions.filter((s) => !confirmed(s)),
    done = sessions.filter(confirmed);
  function sessionRows(items: SessionSummary[]) {
    return items.length ? (
      <div className="record-rows">
        {items.map((s) => (
          <div className="record-row" key={s.id}>
            <div className="record-symbol">{confirmed(s) ? "✓" : "≡"}</div>
            <div className="record-patient">
              <strong>{s.patient_name}</strong>
              <small>
                {s.patient_ref || "未填写编号"} ·{" "}
                {s.has_audio ? "音频问诊" : "文字问诊"}
              </small>
            </div>
            <div>
              <span
                className={`status-chip tone-${confirmed(s) ? "success" : "warning"}`}
              >
                {s.status_label}
              </span>
              <small>{formatShortDateTime(s.updated_at)}</small>
            </div>
            <button className="text-btn" onClick={() => void open(s.id)}>
              {confirmed(s) ? "查看记录" : "继续处理"} →
            </button>
          </div>
        ))}
      </div>
    ) : (
      <div className="module-empty">
        <strong>暂无相关记录</strong>
        <p>从文字或音频开始，记录会整理在这里。</p>
      </div>
    );
  }
  function heading(title: string, subtitle: string) {
    return (
      <div className="module-heading">
        <p className="eyebrow">ZHENLU · DOCTOR WORKSPACE</p>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
    );
  }
  return (
    <div
      className={`product-shell ${page === "workbench" ? "focused" : ""} ${compact ? "nav-open" : ""}`}
      data-density={density}
    >
      <aside className="product-nav">
        <a className="product-brand" href="#home" title="诊录助手首页">
          <span>≡</span>
          <div>
            诊录助手<small>医生工作空间</small>
          </div>
        </a>
        <nav aria-label="主导航">
          {(Object.entries(pages) as [Page, string][]).map(
            ([key, title], i) => (
              <button
                key={key}
                title={title}
                aria-label={title}
                aria-current={page === key ? "page" : undefined}
                className={page === key ? "active" : ""}
                onClick={() => navigate(key)}
              >
                <span aria-hidden="true">
                  {["⌂", "+", "▤", "▥", "☷", "⚙"][i]}
                </span>
                <span>{title}</span>
              </button>
            ),
          )}
        </nav>
        <div className="product-profile">
          <p>
            记录有依据
            <br />
            判断由医生
          </p>
          <strong>{user?.name || "单机工作空间"}</strong>
          <small>{user?.institution || "当前设备"}</small>
        </div>
      </aside>
      <div className="product-main">
        <header className="product-header">
          <div>
            <button
              className="nav-toggle"
              aria-label="展开或收起导航"
              aria-expanded={compact}
              onClick={() => setCompact(!compact)}
            >
              ☰
            </button>
            <span>
              工作空间 / <strong>{pages[page]}</strong>
            </span>
          </div>
          <div>
            <span>{user?.name || "单机模式"}</span>
            {authenticationEnabled && (
              <button className="text-btn" onClick={() => void signOut()}>
                退出登录
              </button>
            )}
          </div>
        </header>
        {device?.managed && (
          <div
            className={`device-banner ${disconnected ? "disconnected" : ""}`}
            role="status"
          >
            {disconnected
              ? "设备已断开，已暂停新建、生成与确认。请及时保存当前修改。"
              : "设备已连接"}
          </div>
        )}
        <main className="module-main">
          {error && (
            <div className="alert alert-error" role="alert">
              <span>{error}</span>
              <button
                className="btn btn-small"
                onClick={() => {
                  if (page === "workbench" && selectedId.current)
                    void open(selectedId.current);
                  else void refresh();
                }}
              >
                重试
              </button>
            </div>
          )}
          {page === "home" && (
            <>
              {heading(
                "把时间留给问诊。",
                "整理对话、核对病历，让每一条记录都有迹可循。",
              )}
              <div className="home-layout">
                <div>
                  <h2 className="section-heading">开始一份新问诊</h2>
                  <div className="entry-grid">
                    {(["text", "audio"] as const).map((input, i) => (
                      <button
                        className="entry-card"
                        disabled={disconnected}
                        key={input}
                        onClick={() => newSession(input)}
                      >
                        <small>
                          0{i + 1} / {input.toUpperCase()}
                        </small>
                        <span className="entry-symbol">
                          {input === "text" ? "≡" : "♩"}
                        </span>
                        <h2>{input === "text" ? "文字问诊" : "音频问诊"}</h2>
                        <p>
                          {input === "text"
                            ? "粘贴已有问诊对话，按原文整理病历。"
                            : "导入问诊录音，识别文字并核对原音。"}
                        </p>
                        <span>
                          {input === "text" ? "输入问诊文字" : "导入问诊音频"} →
                        </span>
                      </button>
                    ))}
                  </div>
                  <section className="surface home-section">
                    <div className="row-between">
                      <h2>
                        待处理会话 <small>{pending.length}</small>
                      </h2>
                      <button
                        className="text-btn"
                        onClick={() => {
                          setFilter("pending");
                          navigate("records");
                        }}
                      >
                        查看全部 →
                      </button>
                    </div>
                    {loading ? (
                      <p role="status">正在读取会话…</p>
                    ) : (
                      sessionRows(pending.slice(0, 3))
                    )}
                  </section>
                  <section className="surface home-section">
                    <div className="row-between">
                      <h2>最近确认的记录</h2>
                      <button
                        className="text-btn"
                        onClick={() => {
                          setFilter("confirmed");
                          navigate("records");
                        }}
                      >
                        病历记录 →
                      </button>
                    </div>
                    {sessionRows(done.slice(0, 2))}
                  </section>
                </div>
                <aside>
                  <section className="continue-card">
                    <small>YOUR NEXT STEP</small>
                    <h2>
                      {pending.length ? "继续上次的问诊" : "开启下一次问诊"}
                    </h2>
                    <p>
                      {pending[0]?.patient_name ||
                        "从文字或音频入口开始，逐步完成病历。"}
                    </p>
                    <strong>
                      {pending.length}
                      <small> 份待处理</small>
                    </strong>
                    <button
                      disabled={disconnected && !pending.length}
                      onClick={() =>
                        pending[0]
                          ? void open(pending[0].id)
                          : newSession("text")
                      }
                    >
                      {pending.length ? "继续处理" : "新建问诊"} →
                    </button>
                  </section>
                  <section className="workflow-guide">
                    <h2>一份病历，三步完成</h2>
                    <ol>
                      <li>
                        <strong>录入问诊内容</strong>
                        <p>文字与音频均可开始</p>
                      </li>
                      <li>
                        <strong>核对并修改病历</strong>
                        <p>查看原文，回听可靠区间</p>
                      </li>
                      <li>
                        <strong>确认并复制导出</strong>
                        <p>确认后只读，按模板输出</p>
                      </li>
                    </ol>
                  </section>
                  <button
                    className="template-shortcut"
                    onClick={() => navigate("templates")}
                  >
                    <strong>适配你的机构格式</strong>
                    <span>配置标题、字段映射与顺序 →</span>
                  </button>
                </aside>
              </div>
            </>
          )}
          {page === "new" && (
            <>
              {heading("新建问诊", "选择输入方式，完成后自动进入病历审核。")}
              <NewConsultation
                initialMode={mode}
                disconnected={disconnected}
                onComplete={created}
                onDirtyChange={setDirty}
                onBusyChange={setBusy}
              />
            </>
          )}
          {page === "workbench" &&
            (detailLoading ? (
              <p role="status">正在加载问诊…</p>
            ) : workspace ? (
              <Workspace
                key={workspace.id}
                workspace={workspace}
                notify={notify}
                onWorkspaceUpdated={updated}
                onDirtyChange={setDirty}
                onBusyChange={setBusy}
                deviceDisconnected={disconnected}
                templates={templates}
              />
            ) : (
              <>
                {heading("审核工作台", "选择已有会话，或开始一份新问诊。")}
                <section className="surface">
                  <button
                    className="btn btn-primary"
                    onClick={() => navigate("records")}
                  >
                    选择问诊记录
                  </button>
                  <button
                    className="btn btn-secondary"
                    disabled={disconnected}
                    onClick={() => newSession("text")}
                  >
                    新建文字问诊
                  </button>
                </section>
              </>
            ))}
          {page === "records" && (
            <>
              {heading("病历记录", "查找问诊会话，继续审核或导出确认记录。")}
              <section className="surface">
                <div className="records-toolbar">
                  <div className="filter-buttons">
                    {[
                      ["all", "全部会话"],
                      ["pending", "待处理"],
                      ["confirmed", "已确认"],
                    ].map(([key, title]) => (
                      <button
                        key={key}
                        className={filter === key ? "active" : ""}
                        aria-pressed={filter === key}
                        onClick={() => setFilter(key)}
                      >
                        {title}
                      </button>
                    ))}
                  </div>
                  <input
                    aria-label="搜索问诊记录"
                    placeholder="搜索患者、编号或会话"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </div>
                {sessionRows(
                  sessions.filter(
                    (s) =>
                      (filter === "all" ||
                        (filter === "confirmed"
                          ? confirmed(s)
                          : !confirmed(s))) &&
                      `${s.patient_name} ${s.patient_ref || ""} ${s.id}`
                        .toLowerCase()
                        .includes(query.toLowerCase()),
                  ),
                )}
              </section>
            </>
          )}
          {page === "templates" && (
            <>
              {heading(
                "模板管理",
                "调整输出标题、字段映射与顺序，适配机构格式。",
              )}
              <TemplateManager
                value={templates}
                onSave={saveTemplate}
                onDirtyChange={setDirty}
              />
            </>
          )}
          {page === "settings" && (
            <>
              {heading("设置", "管理工作空间与显示偏好。")}
              <div className="settings-layout">
                <section className="surface">
                  <h2>当前身份</h2>
                  <dl>
                    <dt>姓名</dt>
                    <dd>{user?.name || "未启用账号认证"}</dd>
                    <dt>机构</dt>
                    <dd>{user?.institution || "单机工作空间"}</dd>
                    <dt>运行方式</dt>
                    <dd>
                      {authenticationEnabled
                        ? "服务端认证"
                        : "当前设备单用户使用"}
                    </dd>
                  </dl>
                  {authenticationEnabled && (
                    <button
                      className="btn btn-secondary"
                      onClick={() => void signOut()}
                    >
                      退出登录
                    </button>
                  )}
                </section>
                <section className="surface">
                  <h2>显示偏好</h2>
                  <label className="form-label">
                    信息密度
                    <select
                      value={density}
                      onChange={(e) => setDensity(e.target.value)}
                    >
                      <option value="comfortable">舒适</option>
                      <option value="compact">紧凑</option>
                    </select>
                  </label>
                  <p className="small-note">
                    窄屏可以切换原文、病历与核对分栏。
                  </p>
                </section>
                <section className="surface">
                  <h2>记录与模板</h2>
                  <p>
                    问诊记录保存到当前服务。确认后只读，复制和导出仅读取确认版本。
                  </p>
                  <p>机构模板保存在此浏览器，可在模板管理中配置。</p>
                  <button
                    className="btn btn-secondary"
                    onClick={() => navigate("templates")}
                  >
                    管理模板
                  </button>
                </section>
              </div>
            </>
          )}
        </main>
      </div>
      <ToastStack
        items={toasts}
        onDismiss={(id) => setToasts((v) => v.filter((t) => t.id !== id))}
      />
    </div>
  );
}
export default function App() {
  return (
    <AuthBoundary>
      {(user, logout) => (
        <AppWorkspace key={user?.id || "local"} user={user} logout={logout} />
      )}
    </AuthBoundary>
  );
}
