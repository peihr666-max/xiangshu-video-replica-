import { lazy, Suspense, useMemo, useState } from "react";
// 客户 lane 基础与账户屏样式（F-01/P0-1 修复）：客户制品不含 styles.css，
// 全局 reset、:root 令牌与激活/登录/配对等屏样式必须随本入口加载。
import "./customer/customer-access.css";
import { ActivationPage } from "./customer/ActivationPage";
import { CustomerPairingFlow } from "./customer/CustomerPairingFlow";
import { CustomerWorkspace } from "./customer/CustomerWorkspace";
import { LoginPage } from "./customer/LoginPage";
import { SessionConflictDialog } from "./customer/SessionConflictDialog";
import {
  type CustomerCredentialStore,
  customerCredentialStore,
  useCustomerSession,
} from "./customer/useCustomerSession";

const ReviewWorkspace = import.meta.env.DEV
  ? lazy(() => import("./studio/ReviewWorkspace"))
  : null;

/** The single customer entry router (CW-013, refined by CW-019): every
 * browser path — the root, deep links, unmatched routes, and a historical
 * internal hash — converges on the customer state machine below, so the
 * internal `<App/>` fallback is deleted and the internal access-token shell
 * is structurally unreachable from here.
 *
 * CW-019: `/admin` is no longer a customer route. The management console now
 * ships as an independent build artifact (`client/dist-admin`, served by
 * nginx `location ^~ /admin/`), and this customer bundle must not contain any
 * admin code — the exclusion is enforced at build time by
 * `scripts/verify_customer_bundle.mjs` and at source level by
 * `entryContract.test.ts`. A request that still lands on the customer
 * `index.html` with `/admin` (misconfigured proxy, stale bookmark) degrades
 * to the customer shell rather than leaking admin UI. The only remaining
 * exception is the dev-only `/review/v1.4` review workspace, statically
 * eliminated in production builds.
 *
 * A fresh mount reads the real `window.location`, so refresh / back /
 * deep-link stay in the customer lane. The Tauri desktop customer build has
 * no admin lane at all and always mounts the customer shell. */
export function RootApp({
  path = window.location.pathname,
}: {
  path?: string;
}) {
  if (ReviewWorkspace && path === "/review/v1.4")
    return (
      <Suspense fallback={<p>正在加载 V1.4 审核工作区…</p>}>
        <ReviewWorkspace />
      </Suspense>
    );
  return (
    <CustomerShell startInPairing={path.startsWith("/customer/pairing")} />
  );
}

/** The customer entry (FE-02): the seven-screen customer state machine from
 * dev doc §4.1. It never renders the internal login shell, so the internal
 * access-token input is structurally not a customer entry. The workspace
 * screen reuses the shared shell under the customer identity. */
function CustomerShell({
  startInPairing = false,
}: {
  startInPairing?: boolean;
}) {
  // A stable store identity for the whole mount: the in-memory browser store
  // keeps its credentials in closures, so a per-render store would lose them
  // (and every lifecycle listener would re-mount on each render).
  const store = useMemo(customerCredentialStore, []);
  const [pairing, setPairing] = useState(startInPairing);

  if (pairing) {
    return (
      <CustomerPairingFlow store={store} onPaired={() => setPairing(false)} />
    );
  }

  // Mount the normal boot flow after pairing so it reads the saved device
  // credential. Returning without pairing still boots into activation.
  return (
    <CustomerSessionShell store={store} onPairDevice={() => setPairing(true)} />
  );
}

function CustomerSessionShell({
  store,
  onPairDevice,
}: {
  store: CustomerCredentialStore;
  onPairDevice(): void;
}) {
  const session = useCustomerSession(store);

  switch (session.screen) {
    case "checking":
      return (
        <main className="centered-shell">
          <section className="login-card" aria-live="polite">
            <span className="eyebrow">众墅之家 · AI 即创</span>
            <p className="login-hint">正在检查本机登录状态…</p>
          </section>
        </main>
      );
    case "activation":
      return (
        <ActivationPage
          onActivate={(input) => void session.activate(input)}
          isBusy={session.isBusy}
          error={session.error}
          onPairDevice={onPairDevice}
        />
      );
    case "login":
      return (
        <LoginPage
          onRetryLogin={() => void session.retryLogin()}
          isBusy={session.isBusy}
          error={session.error}
          conflict={session.conflict}
        />
      );
    case "binding-conflict":
      // The conflict screen only exists with conflict metadata; the reducer
      // and this component dispatch together, so a null conflict here means
      // the dialog already cancelled and the screen fell back to login.
      return session.conflict === null ? (
        <LoginPage
          onRetryLogin={() => void session.retryLogin()}
          isBusy={session.isBusy}
          error={session.error}
          conflict={session.conflict}
        />
      ) : (
        <SessionConflictDialog
          conflict={session.conflict}
          onCancel={session.cancelSessionSwitch}
          // Return the switch promise: the dialog awaits onSwitch to keep
          // its buttons disabled, so a discarded promise would let a second
          // click start another switch with a new idempotency key.
          onSwitch={() => session.switchSession()}
        />
      );
    case "workspace":
      // The workspace screen is only reachable after activate/login set the
      // identity; the checking fallback below is unreachable in practice.
      return session.user === null ? null : (
        <CustomerWorkspace
          user={session.user}
          sessionRuntime={session.sessionRuntime}
          onManualHeartbeat={() => void session.sendHeartbeatNow()}
          onLogout={session.logout}
          store={store}
          onSessionExpired={session.restartAfterExpiry}
        />
      );
    case "session-expired":
      return (
        <CustomerTerminalScreen
          title="登录已过期"
          description="会话已过期，请重新登录。"
          actionLabel="重新登录"
          onAction={session.restartAfterExpiry}
        />
      );
    case "session-replaced":
      return (
        <CustomerTerminalScreen
          title="本设备已下线"
          description="您的账号已在另一台设备上登录，本设备会话已被切换下线。"
          actionLabel="重新登录"
          onAction={session.restartAfterExpiry}
        />
      );
    case "device-revoked":
      return (
        <CustomerTerminalScreen
          title="设备已被解绑"
          description="本设备已被解绑，请重新激活后使用。"
          actionLabel="重新激活"
          onAction={session.restartAfterRevocation}
        />
      );
  }
}

/** A terminal screen (§4.2): displaced/expired/revoked sessions are reported
 * as exactly what they are — never as a balance, network, or generic service
 * failure — with the single recovery action the state machine allows. */
function CustomerTerminalScreen({
  title,
  description,
  actionLabel,
  onAction,
}: {
  title: string;
  description: string;
  actionLabel: string;
  onAction(): void;
}) {
  return (
    <main className="centered-shell">
      <section className="login-card" aria-labelledby="customer-terminal-title">
        <span className="eyebrow">众墅之家 · AI 即创</span>
        <h1 id="customer-terminal-title">{title}</h1>
        <p className="login-hint">{description}</p>
        <button type="button" onClick={onAction}>
          {actionLabel}
        </button>
      </section>
    </main>
  );
}
