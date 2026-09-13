import { useEffect, useRef, useState } from "react";
import { useStudio } from "./context";
import {
  cancelLocalPublishLogin,
  canUseLocalPublishAccounts,
  checkLocalPublishLogin,
  type LocalPublishAccount,
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

const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "账号操作失败，请重试。";

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
  const [removing, setRemoving] = useState<LocalPublishAccount | null>(null);
  const currentLogin = useRef<string | null>(null);
  const generation = useRef(0);
  const pending = useRef(false);
  const native = canUseLocalPublishAccounts();
  useEffect(() => {
    void refresh;
    const current = ++generation.current;
    setError("");
    setAccounts([]);
    setLoading(true);
    if (review || !native) {
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
  }, [user.id, review, native, refresh]);
  useEffect(
    () => () => {
      const id = currentLogin.current;
      if (id) void cancelLocalPublishLogin(user.id, id).catch(() => {});
      currentLogin.current = null;
    },
    [user.id],
  );
  useEffect(() => {
    if (!loginId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const account = await checkLocalPublishLogin(user.id, loginId);
        if (!active) return;
        if (account) {
          currentLogin.current = null;
          setLoginId(null);
          setRefresh((value) => value + 1);
          notify(
            `已连接 ${publishPlatformNames[account.platform]} · ${account.username}`,
          );
        } else timer = setTimeout(() => void poll(), 1500);
      } catch (cause) {
        if (active) setError(errorMessage(cause));
      }
    };
    timer = setTimeout(() => void poll(), 1000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [loginId, user.id, notify]);
  async function start(account?: LocalPublishAccount) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
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
  async function cancel() {
    if (!loginId || pending.current) return;
    pending.current = true;
    setBusy(true);
    try {
      await cancelLocalPublishLogin(user.id, loginId);
      currentLogin.current = null;
      setLoginId(null);
      setError("");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  async function remove() {
    if (!removing || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await removeLocalPublishAccount(user.id, removing.id);
      setRemoving(null);
      setRefresh((value) => value + 1);
      notify("已清除该账号的本机登录状态");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <Panel>
      <h2>发布账号管理</h2>
      <p>
        使用官方二维码扫码登录。各账号的登录状态分别保存在本机，用户名从平台读取。
      </p>
      {!native && !review && (
        <p role="status">
          请使用 Windows 桌面客户端管理发布账号。网页端不会保存平台 Cookie。
        </p>
      )}
      {review && <p>审核预览：扫码和账号操作需在桌面端登录后使用。</p>}
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
      {loading && <p role="status">正在读取本机账号…</p>}
      {accounts.map((account) => (
        <div className="studio-publish-account" key={account.id}>
          <PlatformLogo platform={account.platform} size={32} />
          <span>
            {publishPlatformNames[account.platform]} · {account.username}
            <small>账号 ID：{account.platform_user_id}</small>
          </span>
          <small>
            本机已连接 · 最后验证{" "}
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
        <div role="status">
          <p>
            请在打开的官方窗口使用手机扫码并确认登录。读取到平台用户名后会自动完成连接。
          </p>
          <Button disabled={busy} onClick={() => void cancel()}>
            取消扫码
          </Button>
        </div>
      ) : (
        <Button
          disabled={
            !native || review || loading || busy || user.role === "auditor"
          }
          onClick={() => void start()}
        >
          扫码添加账号
        </Button>
      )}
      {removing && (
        <fieldset>
          <legend>确认解绑账号</legend>
          <p>确认解绑 {removing.username} 并清除该账号的本机登录状态？</p>
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
