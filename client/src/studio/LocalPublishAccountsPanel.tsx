import { useEffect, useRef, useState } from "react";
import { useStudio } from "./context";
import {
  cancelLocalPublishLogin,
  canUseLocalPublishAccounts,
  checkLocalPublishLogin,
  focusLocalPublishLogin,
  type LocalPublishAccount,
  type LocalPublishLoginStatus,
  listLocalPublishAccounts,
  removeLocalPublishAccount,
  startLocalPublishLogin,
} from "./localPublishAccounts";
import {
  PlatformLogo,
  type PublishPlatform,
  publishPlatformNames,
} from "./PlatformLogo";
import { Button, Panel } from "./ui";
import "./publish-accounts.css";

const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "账号操作失败，请重试。";

const loginMessages: Record<LocalPublishLoginStatus["phase"], string> = {
  loading: "正在加载官方登录二维码…",
  qr_ready: "请使用对应平台的手机 App 扫码，并在手机上确认登录。",
  confirming: "已扫码，正在等待手机确认和平台账号信息…",
  action_required: "平台要求进一步验证，请按平台提示完成后重试。",
  expired: "二维码或本次连接已过期，请重新获取。",
  closed: "本次扫码连接已关闭，请重新获取二维码。",
  connected: "账号已连接。",
};
const loadingStatus: LocalPublishLoginStatus = {
  phase: "loading",
  image: null,
  account: null,
};

export function LocalPublishAccountsPanel({
  notify,
}: {
  notify(message: string): void;
}) {
  const { user, review } = useStudio();
  const [accounts, setAccounts] = useState<LocalPublishAccount[]>([]);
  const [platform, setPlatform] = useState<PublishPlatform>("douyin");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loginId, setLoginId] = useState<string | null>(null);
  const [loginStatus, setLoginStatus] = useState(loadingStatus);
  const [retryPoll, setRetryPoll] = useState(0);
  const [pollPaused, setPollPaused] = useState(false);
  const [removing, setRemoving] = useState<LocalPublishAccount | null>(null);
  const currentLogin = useRef<string | null>(null);
  const loginAccount = useRef<LocalPublishAccount | undefined>(undefined);
  const notifyRef = useRef(notify);
  notifyRef.current = notify;
  const generation = useRef(0);
  const pending = useRef(false);
  const native = canUseLocalPublishAccounts();
  useEffect(() => {
    void refresh;
    const current = ++generation.current;
    setError("");
    setAccounts([]);
    setLoading(true);
    if (review) {
      setLoading(false);
      return;
    }
    void listLocalPublishAccounts(user.id)
      .then((value) => {
        if (generation.current === current) setAccounts(value);
      })
      .catch((cause) => {
        if (generation.current === current) setError(errorMessage(cause));
      })
      .finally(() => {
        if (generation.current === current) setLoading(false);
      });
    return () => {
      generation.current += 1;
    };
  }, [user.id, review, refresh]);
  useEffect(() => {
    setLoginId(null);
    setLoginStatus(loadingStatus);
    setRemoving(null);
    setBusy(false);
    return () => {
      const id = currentLogin.current;
      if (id) void cancelLocalPublishLogin(user.id, id).catch(() => {});
      currentLogin.current = null;
    };
  }, [user.id]);
  useEffect(() => {
    void retryPoll;
    if (!loginId) return;
    let active = true;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout>;
    setPollPaused(false);
    const poll = async () => {
      try {
        const status = await checkLocalPublishLogin(user.id, loginId);
        if (!active || currentLogin.current !== loginId) return;
        failures = 0;
        setError("");
        setLoginStatus(status);
        if (status.phase === "connected" && status.account) {
          const account = status.account;
          currentLogin.current = null;
          setLoginId(null);
          setRefresh((value) => value + 1);
          notifyRef.current(
            `已连接 ${publishPlatformNames[account.platform]} · ${account.username}`,
          );
        } else if (status.phase !== "expired" && status.phase !== "closed") {
          timer = setTimeout(() => void poll(), 1500);
        }
      } catch (cause) {
        if (!active || currentLogin.current !== loginId) return;
        failures += 1;
        setLoginStatus(loadingStatus);
        setError(errorMessage(cause));
        if (failures < 3)
          timer = setTimeout(() => void poll(), failures * 1500);
        else setPollPaused(true);
      }
    };
    timer = setTimeout(() => void poll(), 1000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [loginId, user.id, retryPoll]);
  async function start(account?: LocalPublishAccount) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    setLoginStatus(loadingStatus);
    setPollPaused(false);
    loginAccount.current = account;
    if (account) setPlatform(account.platform);
    const current = generation.current;
    try {
      const id = await startLocalPublishLogin(
        user.id,
        account?.platform ?? platform,
        account?.id,
      );
      if (current !== generation.current) {
        await cancelLocalPublishLogin(user.id, id);
        return;
      }
      currentLogin.current = id;
      setLoginId(id);
    } catch (cause) {
      if (current === generation.current) setError(errorMessage(cause));
    } finally {
      pending.current = false;
      if (current === generation.current) setBusy(false);
    }
  }
  async function cancel(): Promise<boolean> {
    if (!loginId || pending.current) return false;
    pending.current = true;
    setBusy(true);
    currentLogin.current = null;
    const current = generation.current;
    try {
      await cancelLocalPublishLogin(user.id, loginId);
      if (current !== generation.current) return false;
      currentLogin.current = null;
      setLoginId(null);
      setLoginStatus(loadingStatus);
      setError("");
      return true;
    } catch (cause) {
      if (current !== generation.current) return false;
      currentLogin.current = loginId;
      setRetryPoll((value) => value + 1);
      setError(errorMessage(cause));
      return false;
    } finally {
      pending.current = false;
      if (current === generation.current) setBusy(false);
    }
  }
  async function restart() {
    const account = loginAccount.current;
    if (await cancel()) await start(account);
  }
  async function focus() {
    if (!loginId) return;
    try {
      await focusLocalPublishLogin(user.id, loginId);
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }
  async function remove() {
    if (!removing || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    const current = generation.current;
    try {
      await removeLocalPublishAccount(user.id, removing.id);
      if (current !== generation.current) return;
      setRemoving(null);
      setRefresh((value) => value + 1);
      notify(`已清除该账号的${native ? "本机" : "云端"}登录状态`);
    } catch (cause) {
      if (current === generation.current) setError(errorMessage(cause));
    } finally {
      pending.current = false;
      if (current === generation.current) setBusy(false);
    }
  }
  return (
    <Panel>
      <h2>发布账号管理</h2>
      <p>使用官方二维码扫码登录，用户名从平台读取。</p>
      {!native && !review && (
        <p role="status">
          网页端账号的登录状态加密保存在服务器，可在个人中心解绑。
        </p>
      )}
      {review && <p>审核预览：扫码和账号操作需登录工作台后使用。</p>}
      <div className="content-platform-options">
        {(Object.keys(publishPlatformNames) as PublishPlatform[]).map(
          (value) => (
            <Button
              key={value}
              aria-pressed={platform === value}
              disabled={busy || Boolean(loginId)}
              onClick={() => setPlatform(value)}
            >
              <PlatformLogo platform={value} />
              {publishPlatformNames[value]}
            </Button>
          ),
        )}
      </div>
      {error && (
        <p role="alert">
          {error}
          {!loginId && (
            <Button onClick={() => setRefresh((value) => value + 1)}>
              刷新账号
            </Button>
          )}
        </p>
      )}
      {native && <p>桌面端账号的登录状态分别保存在本机。</p>}
      {loading && <p role="status">正在读取发布账号…</p>}
      {accounts.map((account) => (
        <div className="studio-publish-account" key={account.id}>
          <PlatformLogo platform={account.platform} size={32} />
          <span>
            {publishPlatformNames[account.platform]} · {account.username}
            <small>账号 ID：{account.platform_user_id}</small>
          </span>
          <small>
            {native ? "本机已连接" : "云端已连接"} · 最后验证{" "}
            {new Date(account.verified_at * 1000).toLocaleString("zh-CN")}
          </small>
          <Button
            disabled={busy || Boolean(loginId) || user.role === "auditor"}
            onClick={() => void start(account)}
          >
            验证或重新登录
          </Button>
          <Button
            disabled={busy || Boolean(loginId) || user.role === "auditor"}
            onClick={() => setRemoving(account)}
          >
            解绑
          </Button>
        </div>
      ))}
      {loginId ? (
        <section
          className="publish-login"
          aria-label={`${publishPlatformNames[platform]}扫码登录`}
        >
          <h3>{publishPlatformNames[platform]}扫码添加账号</h3>
          {loginStatus.phase === "qr_ready" &&
            loginStatus.image &&
            /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/]+=*$/.test(
              loginStatus.image,
            ) && (
              <img
                className="publish-login__qr"
                src={loginStatus.image}
                alt={`${publishPlatformNames[platform]}登录二维码`}
                onError={() =>
                  setLoginStatus({ ...loadingStatus, phase: "action_required" })
                }
              />
            )}
          <p role="status">
            {pollPaused
              ? "自动检测已暂停，请重试检测或重新获取二维码。"
              : (loginStatus.message ?? loginMessages[loginStatus.phase])}
          </p>
          <div className="publish-login__actions">
            {native && (
              <Button
                disabled={busy || loginStatus.phase === "closed"}
                onClick={() => void focus()}
              >
                打开官方窗口
              </Button>
            )}
            {pollPaused && (
              <Button
                disabled={busy}
                onClick={() => setRetryPoll((value) => value + 1)}
              >
                重试检测
              </Button>
            )}
            <Button disabled={busy} onClick={() => void restart()}>
              重新获取二维码
            </Button>
            <Button disabled={busy} onClick={() => void cancel()}>
              取消扫码
            </Button>
          </div>
        </section>
      ) : (
        <Button
          disabled={review || loading || busy || user.role === "auditor"}
          onClick={() => void start()}
        >
          扫码添加账号
        </Button>
      )}
      {removing && (
        <fieldset>
          <legend>确认解绑账号</legend>
          <p>
            确认解绑 {removing.username} 并清除该账号的
            {native ? "本机" : "云端"}登录状态？
          </p>
          <Button disabled={busy} onClick={() => void remove()}>
            确认解绑
          </Button>
          <Button disabled={busy} onClick={() => setRemoving(null)}>
            取消
          </Button>
        </fieldset>
      )}
    </Panel>
  );
}
