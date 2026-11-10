import { useEffect, useRef, useState, type ReactNode } from "react";
import { errorMessage } from "./utils";

export interface AuthUser {
  id: string;
  name: string;
  institution?: string;
  role: "doctor";
}
interface AuthSession {
  user: AuthUser;
  expires_at?: string;
}
export const authenticationEnabled =
  import.meta.env.VITE_AUTH_MODE === "server";
let accessAllowed = !authenticationEnabled;
export function assertAuthenticated() {
  if (!accessAllowed) throw new Error("请重新登录后继续。");
}
const paths = {
  login: import.meta.env.VITE_AUTH_LOGIN_PATH || "/api/auth/login",
  current: import.meta.env.VITE_AUTH_ME_PATH || "/api/auth/me",
  logout: import.meta.env.VITE_AUTH_LOGOUT_PATH || "/api/auth/logout",
};
// These paths are an integration contract, not endpoints implemented by this repository.
export function csrfHeaders(): Record<string, string> {
  const cookie = document.cookie
    .split("; ")
    .find((value) => value.startsWith("csrftoken="));
  return cookie
    ? { "X-CSRFToken": decodeURIComponent(cookie.slice("csrftoken=".length)) }
    : {};
}
async function authRequest(
  path: string,
  body?: object,
): Promise<AuthSession | null> {
  if (!path.startsWith("/") || path.startsWith("//"))
    throw new Error("认证地址必须使用同源路径");
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    ...(body
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify(body),
        }
      : {}),
    signal: AbortSignal.timeout(15000),
  });
  if (response.status === 401)
    throw new Error(body ? "账号或密码不正确。" : "登录已过期，请重新登录。");
  if (!response.ok)
    throw new Error(
      response.status === 404
        ? "登录服务暂不可用，请联系管理员。"
        : "登录服务请求失败，请稍后重试。",
    );
  if (response.status === 204) return null;
  return response.json() as Promise<AuthSession>;
}
function validateSession(data: AuthSession | null): AuthSession {
  if (!data?.user?.id || !data.user.name || data.user.role !== "doctor")
    throw new Error("该账号暂无医生工作空间访问权限。");
  if (
    data.expires_at &&
    (!Number.isFinite(Date.parse(data.expires_at)) ||
      Date.parse(data.expires_at) <= Date.now())
  )
    throw new Error("登录已过期，请重新登录。");
  return data;
}
export function AuthBoundary({
  children,
}: {
  children: (user: AuthUser | null, logout: () => Promise<void>) => ReactNode;
}) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [ready, setReady] = useState(!authenticationEnabled);
  const [locked, setLocked] = useState(authenticationEnabled);
  const [message, setMessage] = useState("");
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const current = useRef<AuthSession | null>(null);
  current.current = session;
  function lock() {
    accessAllowed = false;
    setLocked(true);
    setMessage("登录已过期，请重新登录。当前页面的未保存输入会保留。");
    document.querySelectorAll("audio").forEach((audio) => audio.pause());
  }
  useEffect(() => {
    if (!authenticationEnabled) return;
    let stopped = false;
    void authRequest(paths.current)
      .then(validateSession)
      .then((data) => {
        if (!stopped) {
          setSession(data);
          setLocked(false);
          accessAllowed = true;
        }
      })
      .catch((error) => {
        if (!stopped) setMessage(errorMessage(error));
      })
      .finally(() => {
        if (!stopped) setReady(true);
      });
    const expired = () => lock();
    const check = () => {
      if (document.hidden || !current.current) return;
      void authRequest(paths.current)
        .then(validateSession)
        .then((data) => {
          if (stopped) return;
          if (data.user.id !== current.current?.user.id) {
            lock();
            return;
          }
          setSession(data);
        })
        .catch(() => {
          if (!stopped) lock();
        });
    };
    window.addEventListener("zhenlu:unauthorized", expired);
    document.addEventListener("visibilitychange", check);
    return () => {
      stopped = true;
      window.removeEventListener("zhenlu:unauthorized", expired);
      document.removeEventListener("visibilitychange", check);
    };
  }, []);
  useEffect(() => {
    document.body.classList.toggle("authentication-locked", locked);
    return () => document.body.classList.remove("authentication-locked");
  }, [locked]);
  useEffect(() => {
    if (!session?.expires_at || locked) return;
    const timer = window.setTimeout(
      lock,
      Math.min(
        2147483647,
        Math.max(0, Date.parse(session.expires_at) - Date.now()),
      ),
    );
    return () => clearTimeout(timer);
  }, [session, locked]);
  async function login(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!account.trim() || !password) {
      setMessage("请输入账号和密码。");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const next = validateSession(
        await authRequest(paths.login, { account: account.trim(), password }),
      );
      if (session && next.user.id !== session.user.id)
        throw new Error("请使用原账号恢复编辑；如需切换账号，请先退出。");
      setSession(next);
      setLocked(false);
      accessAllowed = true;
      setPassword("");
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    await authRequest(paths.logout, {});
    accessAllowed = false;
    setSession(null);
    setLocked(true);
    setAccount("");
    setPassword("");
    setMessage("");
  }
  return (
    <>
      {ready && (!authenticationEnabled || session) && (
        <div hidden={locked} inert={locked}>
          {children(session?.user ?? null, logout)}
        </div>
      )}
      {locked && (
        <div className="login-page">
          <section className="login-story">
            <div className="login-brand">
              诊录助手 <small>ZHENLU</small>
            </div>
            <div>
              <p className="eyebrow">FOR EVERY CONVERSATION</p>
              <h1>
                认真听诊，
                <br />
                从容记录。
              </h1>
              <p>
                让每一段问诊成为清晰的病历，
                <br />
                让每一条记录保留医生的判断。
              </p>
              <div className="login-steps">记录问诊 → 医生审核 → 确认归档</div>
            </div>
            <small>诊有所据 · 录有所循</small>
          </section>
          <section className="login-form-area">
            <form
              onSubmit={(event) => void login(event)}
              className="login-form"
            >
              <p className="eyebrow">欢迎回来</p>
              <h2>登录医生工作空间</h2>
              <p>使用你的工作账号继续。</p>
              <label>
                账号
                <input
                  autoComplete="username"
                  value={account}
                  onChange={(e) => setAccount(e.target.value)}
                  required
                  disabled={!ready || busy}
                />
              </label>
              <label>
                密码
                <div className="password-input">
                  <input
                    aria-label="密码"
                    type={visible ? "text" : "password"}
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    disabled={!ready || busy}
                  />
                  <button
                    type="button"
                    aria-label={visible ? "隐藏密码" : "显示密码"}
                    aria-pressed={visible}
                    onClick={() => setVisible(!visible)}
                  >
                    {visible ? "隐藏" : "显示"}
                  </button>
                </div>
              </label>
              <p className="field-error" role="alert">
                {message}
              </p>
              <button className="btn btn-primary" disabled={!ready || busy}>
                {!ready
                  ? "正在验证登录…"
                  : busy
                    ? "正在登录…"
                    : "登录工作空间 →"}
              </button>
              <p className="small-note">
                账号或密码遇到问题，请联系机构管理员。
              </p>
            </form>
          </section>
        </div>
      )}
    </>
  );
}
