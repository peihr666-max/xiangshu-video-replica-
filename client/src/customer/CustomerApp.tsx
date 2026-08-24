import { type JSX, useState } from "react";
import type { CustomerApiError } from "../api";
import { DevicePairingPage } from "./DevicePairingPage";
import { SessionConflictDialog } from "./SessionConflictDialog";
import { SessionDisplacedNotice } from "./SessionDisplacedNotice";
import { createBrowserCustomerCredentialStore } from "./store";
import {
  type CustomerActivationFormInput,
  type CustomerCredentialStore,
  type CustomerWorkspaceUser,
  useCustomerSession,
} from "./useCustomerSession";

const defaultStore = createBrowserCustomerCredentialStore();

/** 最小客户入口(T30/FE-03 过渡装配,挂载于 RootApp 的 /customer/)。
 *
 * 装配 useCustomerSession 状态机与配对/冲突/切换/被踢 UI,让新 UI 在
 * shipped 应用中可达。激活/登录/工作台为最小实现 —— T29(FE-02)正式
 * 页面、T31 设备管理与 T34 客户 E2E 合并后逐步替换。
 */
export function CustomerApp({
  store = defaultStore,
}: {
  store?: CustomerCredentialStore;
}): JSX.Element {
  const session = useCustomerSession(store);
  const [showPairing, setShowPairing] = useState(false);
  const [pairingNotice, setPairingNotice] = useState<string | null>(null);

  if (session.screen === "checking") {
    return <p className="customer-shell">正在检查本机凭据…</p>;
  }
  if (session.screen === "activation") {
    return (
      <ActivationScreen
        activate={session.activate}
        isBusy={session.isBusy}
        error={session.error}
      />
    );
  }
  if (session.screen === "login") {
    return (
      <LoginScreen
        retryLogin={session.retryLogin}
        isBusy={session.isBusy}
        error={session.error}
      />
    );
  }
  // The conflict screen only exists with conflict metadata; the reducer and
  // this component dispatch together, so a null conflict here means the
  // dialog already cancelled and the screen fell back to the workspace.
  if (session.screen === "binding-conflict" && session.conflict !== null) {
    return (
      <SessionConflictDialog
        conflict={session.conflict}
        onCancel={session.cancelSessionSwitch}
        onSwitch={() => {
          void session.switchSession();
        }}
      />
    );
  }
  if (session.screen === "session-expired") {
    return <SessionExpiredNotice onRestart={session.restartAfterExpiry} />;
  }
  if (session.screen === "session-replaced") {
    return <SessionDisplacedNotice onRestart={session.restartAfterReplaced} />;
  }
  if (session.screen === "device-revoked") {
    return <DeviceRevokedNotice onRestart={session.restartAfterRevocation} />;
  }

  if (showPairing) {
    return (
      <DevicePairingPage
        onSuccess={(result) => {
          setShowPairing(false);
          setPairingNotice(
            result.status === 202
              ? "配对请求已提交，等待第一设备批准。"
              : "设备已绑定，配对完成。",
          );
        }}
        onError={(error) => {
          setShowPairing(false);
          setPairingNotice(error.message);
        }}
        onCancel={() => setShowPairing(false)}
      />
    );
  }
  return (
    <WorkspaceScreen
      user={session.user}
      isBusy={session.isBusy}
      notice={pairingNotice}
      onPair={() => {
        setPairingNotice(null);
        setShowPairing(true);
      }}
      onLogout={() => {
        void session.logout();
      }}
    />
  );
}

function ActivationScreen({
  activate,
  isBusy,
  error,
}: {
  activate: (input: CustomerActivationFormInput) => Promise<void>;
  isBusy: boolean;
  error: CustomerApiError | null;
}): JSX.Element {
  const [activationCode, setActivationCode] = useState("");
  const [deviceName, setDeviceName] = useState("");

  return (
    <main
      className="customer-shell activation-screen"
      aria-labelledby="activation-title"
    >
      <h1 id="activation-title">激活</h1>
      <p className="page-subtitle">输入激活码开始使用工作台</p>
      <form
        className="customer-form"
        onSubmit={(e) => {
          e.preventDefault();
          void activate({ activationCode, deviceName });
        }}
      >
        <div className="form-group">
          <label htmlFor="activation-code">激活码</label>
          <input
            type="text"
            id="activation-code"
            value={activationCode}
            onChange={(e) => setActivationCode(e.target.value)}
            required
            aria-required="true"
          />
        </div>
        <div className="form-group">
          <label htmlFor="device-name">设备名</label>
          <input
            type="text"
            id="device-name"
            value={deviceName}
            onChange={(e) => setDeviceName(e.target.value)}
            required
            aria-required="true"
          />
        </div>
        <button type="submit" className="btn-primary" disabled={isBusy}>
          {isBusy ? "激活中…" : "激活"}
        </button>
      </form>
      {error !== null && (
        <p className="customer-error" role="alert">
          {error.message}
        </p>
      )}
    </main>
  );
}

function LoginScreen({
  retryLogin,
  isBusy,
  error,
}: {
  retryLogin: () => Promise<void>;
  isBusy: boolean;
  error: CustomerApiError | null;
}): JSX.Element {
  return (
    <main className="customer-shell login-screen" aria-labelledby="login-title">
      <h1 id="login-title">欢迎回来</h1>
      <p>此设备已绑定客户身份，恢复会话后继续使用工作台。</p>
      <button
        type="button"
        className="btn-primary"
        onClick={() => {
          void retryLogin();
        }}
        disabled={isBusy}
      >
        {isBusy ? "恢复中…" : "恢复登录"}
      </button>
      {error !== null && (
        <p className="customer-error" role="alert">
          {error.message}
        </p>
      )}
    </main>
  );
}

function WorkspaceScreen({
  user,
  isBusy,
  notice,
  onPair,
  onLogout,
}: {
  user: CustomerWorkspaceUser | null;
  isBusy: boolean;
  notice: string | null;
  onPair: () => void;
  onLogout: () => void;
}): JSX.Element {
  return (
    <main
      className="customer-shell workspace-screen"
      aria-labelledby="workspace-title"
    >
      <h1 id="workspace-title">工作台</h1>
      <p>用户 ID：{user?.userId ?? "未知"}</p>
      {notice !== null && (
        <p className="customer-notice" role="status">
          {notice}
        </p>
      )}
      <div className="workspace-actions">
        <button type="button" className="btn-primary" onClick={onPair}>
          配对第二设备
        </button>
        <button
          type="button"
          className="btn-secondary"
          onClick={onLogout}
          disabled={isBusy}
        >
          退出登录
        </button>
      </div>
    </main>
  );
}

function SessionExpiredNotice({
  onRestart,
}: {
  onRestart: () => void;
}): JSX.Element {
  return (
    <main className="customer-shell" aria-labelledby="expired-title">
      <h1 id="expired-title">会话已过期</h1>
      <p>登录状态已过期，设备凭据仍然有效，请重新登录。</p>
      <button type="button" className="btn-primary" onClick={onRestart}>
        重新登录
      </button>
    </main>
  );
}

function DeviceRevokedNotice({
  onRestart,
}: {
  onRestart: () => void;
}): JSX.Element {
  return (
    <main className="customer-shell" aria-labelledby="revoked-title">
      <h1 id="revoked-title">设备已撤销</h1>
      <p>此设备的凭据已被清除，需要使用激活码重新激活。</p>
      <button type="button" className="btn-primary" onClick={onRestart}>
        重新激活
      </button>
    </main>
  );
}
