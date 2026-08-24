import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import {
  CUSTOMER_SESSION_EXPIRED_EVENT,
  CUSTOMER_SESSION_REPLACED_EVENT,
  CUSTOMER_SESSION_REVOKED_EVENT,
  CustomerApiError,
  type CustomerDeviceCredential,
  customerActivate,
  customerHeartbeat,
  customerLogin,
  customerLogout,
  customerSwitch,
} from "../api";

/** The persistent-credential boundary for the customer lane (dev doc §14).
 *
 * The desktop build backs this with the Tauri DPAPI command bridge; tests and the browser lane inject an isolated, non-persistent implementation. The hook itself never touches localStorage/sessionStorage — §7/§10.2 forbid a plaintext secret in Web Storage, and the injected store is the only place a credential survives.
 */
export interface CustomerCredentialStore {
  loadDeviceCredentialToken(): Promise<string | null>;
  loadSessionToken(): Promise<string | null>;
  saveActivation(deviceToken: string, sessionToken: string): Promise<void>;
  saveSessionToken(sessionToken: string): Promise<void>;
  clearSessionToken(): Promise<void>;
  clearAllCredentials(): Promise<void>;
  /** The stable device fingerprint (§14: generated once, read forever). */
  deviceInstanceId(): Promise<string>;
  devicePlatform(): string;
}

export type CustomerSessionConflict = {
  deviceNameMasked: string;
  slotNo: number;
  leaseExpiresAt: string;
};

export type CustomerActivationFormInput = {
  activationCode: string;
  deviceName: string;
};

export type PendingPairing = {
  id: string;
  deviceFingerprint: string;
  slotNo: number;
  createdAt: string;
};

/** The workspace identity for the customer lane. Activation returns the username; a restart-restore login response carries only the user id (no customer /me endpoint exists yet), so the username degrades to null. */
export type CustomerWorkspaceUser = {
  userId: string;
  username: string | null;
};

const DEFAULT_HEARTBEAT_INTERVAL_MS = 30_000;

function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

/** A vault (credential-store) failure surfaced as a determinate customer error: the UI gets a readable message instead of a swallowed rejection. The credential store is local and opaque to the server; any I/O error is treated as "unknown" transport kind rather than inferred from a status code. */
function credentialStoreError(cause: unknown): CustomerApiError {
  // The underlying I/O error is intentionally not surfaced verbatim: the vault message may be OS-specific noise the customer cannot act on, and the error path is already observable through the UI copy.
  void cause;
  return new CustomerApiError({
    message: "本机凭据读写失败，请重试或重新激活",
    transportKind: "unknown",
  });
}

/**
 * The customer session orchestrator (FE-02): boots from the credential store, drives activate/login/logout, listens for the three lifecycle events (§10.1), and keeps the lease alive with heartbeats while the workspace is live. Screen transitions all flow through the customer-state reducer — nothing here jumps screens directly.
 */
export function useCustomerSession(
  store: CustomerCredentialStore,
  options?: { heartbeatIntervalMs?: number },
): {
  screen: CustomerScreen;
  isBusy: boolean;
  error: CustomerApiError | null;
  conflict: CustomerSessionConflict | null;
  user: CustomerWorkspaceUser | null;
  activate(input: CustomerActivationFormInput): Promise<void>;
  retryLogin(): Promise<void>;
  switchSession(): Promise<void>;
  cancelSessionSwitch(): void;
  logout(): Promise<void>;
  restartAfterExpiry(): void;
  restartAfterReplaced(): void;
  restartAfterRevocation(): void;
} {
  const [screen, dispatch] = useReducer(
    customerScreenReducer,
    initialCustomerScreen,
  );
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<CustomerApiError | null>(null);
  const [conflict, setConflict] = useState<CustomerSessionConflict | null>(
    null,
  );
  // The in-memory session token powers heartbeat/logout. The persistent copy lives only in the injected store; this state is intentionally not persisted anywhere else.
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [user, setUser] = useState<CustomerWorkspaceUser | null>(null);
  const sessionTokenRef = useRef<string | null>(null);
  const bootstrappedRef = useRef(false);

  const establishSession = useCallback(
    async (deviceToken: string) => {
      const credential: CustomerDeviceCredential = {
        kind: "device",
        token: deviceToken,
      };
      const previousSessionToken = await store.loadSessionToken();
      const result = await customerLogin(credential, {
        idempotencyKey: newIdempotencyKey(),
        sessionToken: previousSessionToken ?? undefined,
      });
      try {
        await store.saveSessionToken(result.session.session_token);
      } catch (cause) {
        throw credentialStoreError(cause);
      }
      sessionTokenRef.current = result.session.session_token;
      setSessionToken(result.session.session_token);
      setUser({ userId: result.session.user_id, username: null });
      return result;
    },
    [store],
  );

  // Boot: check the credential store once, then (FE-02 restart gate) try to restore a session automatically when a device credential exists. The cleanup resets the guard for React 18 StrictMode double-mounts — the customer lane would otherwise stay stuck on the checking screen forever.
  useEffect(() => {
    if (bootstrappedRef.current) {
      return;
    }
    bootstrappedRef.current = true;
    let cancelled = false;
    (async () => {
      let deviceToken: string | null;
      try {
        deviceToken = await store.loadDeviceCredentialToken();
      } catch {
        // An unreadable vault behaves like no credential: the user lands on the activation screen with a readable error (never a stuck checking screen).
        dispatch({ type: "boot-check-completed", hasDeviceCredential: false });
        if (!cancelled) {
          setError(credentialStoreError(null));
        }
        return;
      }
      if (cancelled) {
        return;
      }
      dispatch({
        type: "boot-check-completed",
        hasDeviceCredential: deviceToken !== null,
      });
      if (deviceToken === null) {
        return;
      }
      setIsBusy(true);
      try {
        await establishSession(deviceToken);
        if (!cancelled) {
          dispatch({ type: "login-succeeded" });
        }
      } catch (cause) {
        if (cancelled) {
          return;
        }
        if (cause instanceof CustomerApiError) {
          setError(cause);
          if (cause.kind === "other-device-online") {
            setConflict({
              deviceNameMasked: cause.onlineDeviceNameMasked ?? "",
              slotNo: cause.onlineSlotNo ?? 0,
              leaseExpiresAt: cause.leaseExpiresAt ?? "",
            });
            dispatch({ type: "conflict-detected" });
          }
        } else {
          setError(credentialStoreError(cause));
        }
      } finally {
        if (!cancelled) {
          setIsBusy(false);
        }
      }
    })();
    return () => {
      cancelled = true;
      // StrictMode double-mounts the effect; the second mount must boot again or the customer lane would sit on the checking screen forever.
      bootstrappedRef.current = false;
    };
  }, [establishSession, store]);

  // The three lifecycle events (§10.1) arrive on window — dispatched by the customer transport on any 401 that ends the session. Each one also does the right thing to the persisted credential: expired/replaced keep the device credential (§13.2: back to the login screen), revoked clears everything (recovery flow).
  useEffect(() => {
    const onExpired = () => {
      void store.clearSessionToken();
      sessionTokenRef.current = null;
      setSessionToken(null);
      setUser(null);
      setConflict(null);
      dispatch({ type: "session-expired" });
    };
    const onReplaced = () => {
      void store.clearSessionToken();
      sessionTokenRef.current = null;
      setSessionToken(null);
      setUser(null);
      setConflict(null);
      dispatch({ type: "session-replaced" });
    };
    const onRevoked = () => {
      void store.clearAllCredentials();
      sessionTokenRef.current = null;
      setSessionToken(null);
      setUser(null);
      setConflict(null);
      dispatch({ type: "device-revoked" });
    };
    window.addEventListener(CUSTOMER_SESSION_EXPIRED_EVENT, onExpired);
    window.addEventListener(CUSTOMER_SESSION_REPLACED_EVENT, onReplaced);
    window.addEventListener(CUSTOMER_SESSION_REVOKED_EVENT, onRevoked);
    return () => {
      window.removeEventListener(CUSTOMER_SESSION_EXPIRED_EVENT, onExpired);
      window.removeEventListener(CUSTOMER_SESSION_REPLACED_EVENT, onReplaced);
      window.removeEventListener(CUSTOMER_SESSION_REVOKED_EVENT, onRevoked);
    };
  }, [store]);

  // Keep the lease alive while the workspace is live. A failing heartbeat ends through the lifecycle events above (the transport dispatches them on the terminal 401s), so errors here intentionally do not switch screens — §4.2: a displaced/expired session must not masquerade as a generic network/service failure either.
  const heartbeatIntervalMs =
    options?.heartbeatIntervalMs ?? DEFAULT_HEARTBEAT_INTERVAL_MS;
  useEffect(() => {
    if (screen !== "workspace" || sessionToken === null) {
      return;
    }
    const timer = window.setInterval(() => {
      const token = sessionTokenRef.current;
      if (token === null) {
        return;
      }
      void customerHeartbeat({ kind: "session", token }).catch(() => {
        // Terminal outcomes arrive as lifecycle events; transient failures leave the next heartbeat to retry.
      });
    }, heartbeatIntervalMs);
    return () => {
      window.clearInterval(timer);
    };
  }, [heartbeatIntervalMs, screen, sessionToken]);

  const activate = useCallback(
    async (input: CustomerActivationFormInput) => {
      setIsBusy(true);
      setError(null);
      setConflict(null);
      try {
        const response = await customerActivate({
          activationCode: input.activationCode,
          deviceFingerprint: await store.deviceInstanceId(),
          deviceName: input.deviceName,
          devicePlatform: store.devicePlatform(),
          idempotencyKey: newIdempotencyKey(),
        });
        try {
          await store.saveActivation(
            response.device_token,
            response.session_token,
          );
        } catch (cause) {
          throw credentialStoreError(cause);
        }
        dispatch({ type: "activation-succeeded" });
        // Restore session immediately after activation completes successfully
        setSessionToken(response.session_token);
        sessionTokenRef.current = response.session_token;
        setUser({ userId: response.user_id, username: null });
      } catch (cause) {
        if (cause instanceof CustomerApiError) {
          setError(cause);
        } else {
          setError(credentialStoreError(cause));
        }
      } finally {
        setIsBusy(false);
      }
    },
    [store],
  );

  const retryLogin = useCallback(async () => {
    setIsBusy(true);
    setError(null);
    setConflict(null);
    try {
      const deviceToken = await store.loadDeviceCredentialToken();
      if (deviceToken === null) {
        dispatch({ type: "credential-missing" });
        return;
      }
      await establishSession(deviceToken);
      dispatch({ type: "login-succeeded" });
    } catch (cause) {
      if (cause instanceof CustomerApiError) {
        setError(cause);
        if (cause.kind === "other-device-online") {
          setConflict({
            deviceNameMasked: cause.onlineDeviceNameMasked ?? "",
            slotNo: cause.onlineSlotNo ?? 0,
            leaseExpiresAt: cause.leaseExpiresAt ?? "",
          });
          dispatch({ type: "conflict-detected" });
        }
      } else {
        setError(credentialStoreError(cause));
      }
    } finally {
      setIsBusy(false);
    }
  }, [establishSession, store]);

  // Explicit device switch (FE-03): the customer confirms the takeover in the
  // conflict dialog; the server atomically replaces the lease and mints a
  // fresh session token (§14). The UI must never assume the switch succeeded
  // before the server confirms it — only this action transitions to the
  // workspace.
  const switchSession = useCallback(async () => {
    setIsBusy(true);
    setError(null);
    try {
      const deviceToken = await store.loadDeviceCredentialToken();
      if (deviceToken === null) {
        dispatch({ type: "credential-missing" });
        return;
      }
      const previousSessionToken = await store.loadSessionToken();
      const result = await customerSwitch(
        { kind: "device", token: deviceToken },
        {
          idempotencyKey: newIdempotencyKey(),
          sessionToken: previousSessionToken ?? undefined,
        },
      );
      try {
        await store.saveSessionToken(result.session.session_token);
      } catch (cause) {
        throw credentialStoreError(cause);
      }
      sessionTokenRef.current = result.session.session_token;
      setSessionToken(result.session.session_token);
      setUser({ userId: result.session.user_id, username: null });
      setConflict(null);
      dispatch({ type: "login-succeeded" });
    } catch (cause) {
      if (cause instanceof CustomerApiError) {
        setError(cause);
      } else {
        setError(credentialStoreError(cause));
      }
    } finally {
      setIsBusy(false);
    }
  }, [store]);

  const cancelSessionSwitch = useCallback(() => {
    setConflict(null);
    dispatch({ type: "conflict-cancelled" });
  }, []);

  const logout = useCallback(async () => {
    setIsBusy(true);
    setError(null);
    setConflict(null);
    try {
      const currentToken = sessionTokenRef.current;
      if (currentToken !== null) {
        await customerLogout(
          { kind: "session", token: currentToken },
          {
            idempotencyKey: newIdempotencyKey(),
          },
        );
      }
      await store.clearSessionToken();
      sessionTokenRef.current = null;
      setSessionToken(null);
      setUser(null);
      setConflict(null);
      dispatch({ type: "logout" });
    } catch (cause) {
      void cause; // Don't surface logout errors as UI errors
      await store.clearSessionToken();
      sessionTokenRef.current = null;
      setSessionToken(null);
      setUser(null);
      setConflict(null);
      dispatch({ type: "logout" });
    } finally {
      setIsBusy(false);
    }
  }, [store]);

  const restartAfterExpiry = useCallback(() => {
    dispatch({ type: "session-expired" });
  }, []);

  const restartAfterReplaced = useCallback(() => {
    dispatch({ type: "session-replaced" });
  }, []);

  const restartAfterRevocation = useCallback(() => {
    dispatch({ type: "device-revoked" });
  }, []);

  return {
    screen,
    isBusy,
    error,
    conflict,
    user,
    activate,
    retryLogin,
    switchSession,
    cancelSessionSwitch,
    logout,
    restartAfterExpiry,
    restartAfterReplaced,
    restartAfterRevocation,
  };
}

// customer-state.ts imports go here to avoid circular dependencies
type CustomerScreen =
  | "checking"
  | "login"
  | "activation"
  | "workspace"
  | "binding-conflict"
  | "session-expired"
  | "session-replaced"
  | "device-revoked";

type CustomerScreenEvent =
  | { type: "boot-check-completed"; hasDeviceCredential: boolean }
  | { type: "activation-succeeded" }
  | { type: "login-succeeded" }
  | { type: "credential-missing" }
  | { type: "conflict-detected" }
  | { type: "conflict-cancelled" }
  | { type: "logout" }
  | { type: "session-expired" }
  | { type: "session-replaced" }
  | { type: "device-revoked" };

export function customerScreenReducer(
  screen: CustomerScreen,
  event: CustomerScreenEvent,
): CustomerScreen {
  switch (event.type) {
    case "boot-check-completed":
      return event.hasDeviceCredential ? "login" : "activation";
    case "activation-succeeded":
      return "workspace";
    case "login-succeeded":
      return screen === "login" || screen === "binding-conflict"
        ? "workspace"
        : screen;
    case "conflict-detected":
      return screen === "login" ? "binding-conflict" : screen;
    case "conflict-cancelled":
      return screen === "binding-conflict" ? "login" : screen;
    case "credential-missing":
      return screen === "login" ? "activation" : screen;
    case "logout":
      return "login";
    // Re-entering a terminal state means the customer tapped the recovery
    // button on the notice: expired/replaced keep the device credential and
    // return to login (§13.2), revoked clears everything and starts a fresh
    // activation (§10.1 recovery flow).
    case "session-expired":
      return screen === "session-expired" ? "login" : "session-expired";
    case "session-replaced":
      return screen === "session-replaced" ? "login" : "session-replaced";
    case "device-revoked":
      return screen === "device-revoked" ? "activation" : "device-revoked";
    default:
      return screen;
  }
}

export const initialCustomerScreen: CustomerScreen = "checking";
