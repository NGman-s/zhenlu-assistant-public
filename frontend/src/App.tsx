import { useCallback, useEffect, useRef, useState } from "react";
import { createSession, getHealth, getSession, listDemoCases, listSessions } from "./api";
import type { DemoCase, SessionDetail, SessionSummary } from "./types";
import { errorMessage } from "./utils";
import { NewSessionModal } from "./components/NewSessionModal";
import { Onboarding } from "./components/Onboarding";
import { Sidebar } from "./components/Sidebar";
import { ToastStack, type ToastItem, type ToastTone } from "./components/Toasts";
import { Workspace } from "./components/Workspace";

const SELECTED_SESSION_KEY = "zhenlu.selectedSessionId";

function PageLoader() {
  return (
    <div className="page-loader" role="status">
      <span className="spinner large" aria-hidden="true" />
      <p>正在载入问诊工作台…</p>
    </div>
  );
}

function WorkspaceSkeleton() {
  return (
    <div className="workspace skeleton-workspace" aria-hidden="true">
      <div className="skeleton-line w25" />
      <div className="skeleton-line w35 tall" />
      <div className="skeleton-line w45" />
      <div className="skeleton-stepper" />
      <div className="skeleton-card wide" />
      <div className="skeleton-grid">
        <div className="skeleton-card" />
        <div className="skeleton-card" />
        <div className="skeleton-card" />
      </div>
    </div>
  );
}

interface ErrorStateProps {
  message: string;
  onRetry: () => void;
}

function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="error-state">
      <p className="eyebrow">连接或加载失败</p>
      <h1>暂时无法打开工作台</h1>
      <p>{message}</p>
      <button type="button" className="btn btn-primary" onClick={onRetry}>
        重新连接
      </button>
      <span className="error-hint">
        请确认后端服务已启动：http://127.0.0.1:8000/api/health
      </span>
    </div>
  );
}

export default function App() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<SessionDetail | null>(null);
  const [demoCases, setDemoCases] = useState<DemoCase[]>([]);
  const [bootLoading, setBootLoading] = useState(true);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [showNewSession, setShowNewSession] = useState(false);
  const [bootNonce, setBootNonce] = useState(0);
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [dirty, setDirty] = useState(false);
  const [asrIsMock, setAsrIsMock] = useState<boolean | null>(null);
  const [draftIsMock, setDraftIsMock] = useState<boolean | null>(null);
  const [device, setDevice] = useState<{ managed: boolean; connected: boolean; mode: string } | null>(null);

  useEffect(() => {
    let stopped = false;
    let managed = false;
    async function checkDevice() {
      try {
        const response = await fetch("/api/device/status", { cache: "no-store" });
        if (!response.ok) throw new Error("device status unavailable");
        const status = await response.json() as { managed: boolean; connected: boolean; mode: string };
        managed = status.managed;
        if (!stopped) setDevice(status);
      } catch {
        if (!stopped && managed) setDevice((current) => current ? { ...current, connected: false } : current);
      }
    }
    void checkDevice();
    const timer = window.setInterval(checkDevice, 2000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, []);

  const selectedIdRef = useRef<string | null>(null);
  const toastIdRef = useRef(1);

  const notify = useCallback((tone: ToastTone, message: string) => {
    const id = toastIdRef.current;
    toastIdRef.current += 1;
    setToasts((current) => [...current.slice(-3), { id, tone, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 4500);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const refreshSessions = useCallback(async () => {
    try {
      const data = await listSessions();
      setSessions(data.items);
    } catch (error) {
      notify("error", `刷新会话列表失败：${errorMessage(error)}`);
    }
  }, [notify]);

  useEffect(() => {
    let cancelled = false;
    setBootLoading(true);
    setPageError(null);

    async function bootstrap() {
      try {
        const health = await getHealth();
        if (!cancelled) {
          setAsrIsMock(health.asr_is_mock);
          setDraftIsMock(health.draft_is_mock);
        }
      } catch {
        if (!cancelled) {
          setAsrIsMock(null);
          setDraftIsMock(null);
        }
      }
      try {
        const data = await listSessions();
        if (cancelled) return;
        setSessions(data.items);
        const remembered = window.localStorage.getItem(SELECTED_SESSION_KEY);
        const initial =
          data.items.find((session) => session.id === remembered)?.id ??
          data.items[0]?.id ??
          null;
        setSelectedId(initial);
      } catch (error) {
        if (!cancelled) setPageError(errorMessage(error));
      } finally {
        if (!cancelled) setBootLoading(false);
      }

      try {
        const cases = await listDemoCases();
        if (!cancelled) setDemoCases(cases.items);
      } catch (error) {
        if (!cancelled) {
          notify("error", `示例病例加载失败：${errorMessage(error)}`);
        }
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [bootNonce, notify]);

  useEffect(() => {
    selectedIdRef.current = selectedId;
    if (selectedId) {
      window.localStorage.setItem(SELECTED_SESSION_KEY, selectedId);
    }
  }, [selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setWorkspace(null);
      setWorkspaceLoading(false);
      return;
    }

    const controller = new AbortController();
    setWorkspaceLoading(true);
    setPageError(null);
    getSession(selectedId, controller.signal)
      .then((next) => {
        setWorkspace(next);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setPageError(errorMessage(error));
        setWorkspace(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setWorkspaceLoading(false);
      });

    return () => controller.abort();
  }, [selectedId]);

  const handleWorkspaceUpdated = useCallback(
    (next: SessionDetail) => {
      if (selectedIdRef.current === next.id) {
        setWorkspace(next);
      }
      void refreshSessions();
    },
    [refreshSessions],
  );

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const handleSelect = useCallback(
    (sessionId: string) => {
      if (sessionId === selectedIdRef.current) return;
      if (dirty && !window.confirm("当前内容有未保存修改。切换会丢失这些修改，确定继续吗？")) return;
      setDirty(false);
      setSelectedId(sessionId);
      setWorkspace(null);
      setPageError(null);
    },
    [dirty],
  );

  const handleCreate = useCallback(
    async (payload: { patient_name: string; patient_ref: string | null }) => {
      const created = await createSession(payload);
      setDirty(false);
      setSessions((current) => [
        created,
        ...current.filter((session) => session.id !== created.id),
      ]);
      setWorkspace(created);
      setSelectedId(created.id);
      notify("success", `已创建「${created.patient_name}」的问诊会话。`);
      void refreshSessions();
    },
    [notify, refreshSessions],
  );

  const showError = !bootLoading && Boolean(pageError) && !workspace;

  return (
    <div className="app-shell">
      <Sidebar
        sessions={sessions}
        selectedId={selectedId}
        isLoading={bootLoading}
        deviceDisconnected={device?.managed === true && !device.connected}
        onSelect={handleSelect}
        onCreate={() => {
          if (!dirty || window.confirm("当前内容有未保存修改。新建会话会丢失这些修改，确定继续吗？")) {
            setShowNewSession(true);
          }
        }}
      />

      <main className="main">
        {device?.managed ? (
          <div className={`device-banner${device.connected ? "" : " disconnected"}`} role="status" aria-live="polite">
            {device.connected
              ? `设备已连接 · ${device.mode === "simulation" ? "模拟插拔" : device.mode === "identity-prototype" ? "签名验证原型" : "USB 检测"}（尚未接入正式授权）`
              : "设备已断开，新的操作已暂停。本地服务即将关闭；请及时保存或复制未保存的内容。"}
          </div>
        ) : null}
        {bootLoading ? (
          <PageLoader />
        ) : showError ? (
          <ErrorState
            message={pageError ?? "未知错误"}
            onRetry={() => setBootNonce((value) => value + 1)}
          />
        ) : selectedId === null ? (
          <Onboarding onCreate={() => setShowNewSession(true)} deviceDisconnected={device?.managed === true && !device.connected} />
        ) : workspaceLoading && !workspace ? (
          <WorkspaceSkeleton />
        ) : workspace ? (
          <Workspace
            key={workspace.id}
            workspace={workspace}
            demoCases={demoCases}
            notify={notify}
            onWorkspaceUpdated={handleWorkspaceUpdated}
            onDirtyChange={setDirty}
            asrIsMock={asrIsMock}
            draftIsMock={draftIsMock}
          />
        ) : (
          <WorkspaceSkeleton />
        )}
      </main>

      <ToastStack items={toasts} onDismiss={dismissToast} />

      {showNewSession ? (
        <NewSessionModal
          onClose={() => setShowNewSession(false)}
          onCreate={handleCreate}
        />
      ) : null}
    </div>
  );
}
