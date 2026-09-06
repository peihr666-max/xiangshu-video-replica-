import { useCallback, useEffect, useState } from "react";
import {
  attachCustomerSessionToken,
  type CustomerActivationCodeReset,
  CustomerApiError,
  type CustomerDeviceListResponse,
  type CustomerProfile,
  customerApproveDevicePairing,
  customerDismissDevicePairing,
  customerGetProfile,
  customerListDevices,
  customerResetActivationCode,
  customerUnbindDevice,
  customerUpdateProfile,
} from "../api";
import { customerToCurrentUser } from "../RootApp";
import { StudioWorkspace } from "../studio/StudioWorkspace";
import type {
  CustomerCredentialStore,
  CustomerSessionRuntime,
  CustomerWorkspaceUser,
} from "./useCustomerSession";

/**
 * Customer workspace: the shared generation shell plus a session-backed
 * personal centre. Device actions still use the device credential stored in
 * the desktop vault; account and recharge data use the operator session.
 */
export function CustomerWorkspace({
  user,
  sessionRuntime = null,
  onManualHeartbeat,
  store,
  onSessionExpired,
}: {
  user: CustomerWorkspaceUser;
  sessionRuntime?: CustomerSessionRuntime | null;
  onManualHeartbeat?: () => void;
  store: CustomerCredentialStore;
  onSessionExpired: () => void;
}) {
  const [devices, setDevices] = useState<CustomerDeviceListResponse | null>(
    null,
  );
  const [profile, setProfile] = useState<CustomerProfile | null>(null);
  const [deviceError, setDeviceError] = useState("");
  const [workspaceCredentialReady, setWorkspaceCredentialReady] =
    useState(false);

  useEffect(() => {
    let active = true;
    let releaseSession = () => {};
    void store
      .loadSessionToken()
      .then((token) => {
        if (!active) {
          return;
        }
        if (token === null) {
          onSessionExpired();
          return;
        }
        releaseSession = attachCustomerSessionToken(token);
        void customerGetProfile({ kind: "session", token })
          .then((nextProfile) => {
            if (active) {
              setProfile(nextProfile);
            }
          })
          .catch((cause) => {
            if (cause instanceof CustomerApiError && cause.status === 401) {
              onSessionExpired();
            }
          });
        setWorkspaceCredentialReady(true);
      })
      .catch(() => {
        if (active) {
          onSessionExpired();
        }
      });
    return () => {
      active = false;
      releaseSession();
    };
  }, [store, onSessionExpired]);

  const loadDevices = useCallback(async () => {
    const token = await store.loadDeviceCredentialToken();
    if (token === null) {
      onSessionExpired();
      return;
    }
    try {
      const response = await customerListDevices({ kind: "device", token });
      setDevices(response);
      setDeviceError("");
    } catch (cause) {
      if (cause instanceof CustomerApiError && cause.status === 401) {
        onSessionExpired();
        return;
      }
      setDeviceError(
        cause instanceof Error && cause.message
          ? cause.message
          : "设备列表加载失败",
      );
    }
  }, [store, onSessionExpired]);

  useEffect(() => {
    void loadDevices();
  }, [loadDevices]);

  async function handleUnbind(deviceId: string) {
    if (
      !window.confirm("确认下线并解绑这台设备？当前设备解绑后需要重新激活。")
    ) {
      return;
    }
    const token = await store.loadDeviceCredentialToken();
    if (token === null) {
      onSessionExpired();
      return;
    }
    try {
      await customerUnbindDevice({ kind: "device", token }, deviceId, {
        idempotencyKey: crypto.randomUUID(),
      });
      await loadDevices();
    } catch (cause) {
      if (cause instanceof CustomerApiError && cause.status === 401) {
        onSessionExpired();
        return;
      }
      setDeviceError(
        cause instanceof Error && cause.message
          ? cause.message
          : "解绑设备失败",
      );
    }
  }

  async function handleApprovePairing(pairingId: string) {
    const token = await store.loadDeviceCredentialToken();
    if (token === null) {
      onSessionExpired();
      return;
    }
    try {
      await customerApproveDevicePairing({ kind: "device", token }, pairingId);
      await loadDevices();
    } catch (cause) {
      if (cause instanceof CustomerApiError && cause.status === 401) {
        onSessionExpired();
        return;
      }
      setDeviceError(
        cause instanceof Error && cause.message
          ? cause.message
          : "审批配对失败",
      );
    }
  }

  async function handleDismissPairing(pairingId: string) {
    if (!window.confirm("确认删除这个无效的设备绑定请求？")) {
      return;
    }
    const token = await store.loadDeviceCredentialToken();
    if (token === null) {
      onSessionExpired();
      return;
    }
    try {
      await customerDismissDevicePairing({ kind: "device", token }, pairingId);
      await loadDevices();
    } catch (cause) {
      if (cause instanceof CustomerApiError && cause.status === 401) {
        onSessionExpired();
        return;
      }
      setDeviceError(
        cause instanceof Error && cause.message
          ? cause.message
          : "删除设备绑定请求失败",
      );
    }
  }

  async function handleUpdateProfile(
    displayName: string,
  ): Promise<CustomerProfile> {
    const token = await store.loadSessionToken();
    if (token === null) {
      onSessionExpired();
      throw new Error("登录已失效，请重新进入工作台。");
    }
    try {
      return await customerUpdateProfile(
        { kind: "session", token },
        displayName,
      );
    } catch (cause) {
      if (cause instanceof CustomerApiError && cause.status === 401) {
        onSessionExpired();
      }
      throw cause;
    }
  }

  async function handleResetActivationCode(): Promise<CustomerActivationCodeReset> {
    const token = await store.loadSessionToken();
    if (token === null) {
      onSessionExpired();
      throw new Error("登录已失效，请重新进入工作台。");
    }
    try {
      return await customerResetActivationCode({ kind: "session", token });
    } catch (cause) {
      if (cause instanceof CustomerApiError && cause.status === 401) {
        onSessionExpired();
      }
      throw cause;
    }
  }

  return (
    <div className="customer-workspace">
      {workspaceCredentialReady ? (
        <StudioWorkspace
          currentUser={customerToCurrentUser(user, profile)}
          customerAccount={{
            devices,
            deviceError,
            onApprovePairing: (pairingId) =>
              void handleApprovePairing(pairingId),
            onDismissPairing: (pairingId) =>
              void handleDismissPairing(pairingId),
            onProfileUpdated: setProfile,
            onRefreshDevices: loadDevices,
            onResetActivationCode: handleResetActivationCode,
            onUnbind: (deviceId) => void handleUnbind(deviceId),
            onUpdateProfile: handleUpdateProfile,
            profile,
            store,
            onSessionExpired,
            sessionRuntime,
            onManualHeartbeat,
          }}
        />
      ) : (
        <main className="centered-shell" aria-live="polite">
          <p className="login-hint">正在进入工作区…</p>
        </main>
      )}
    </div>
  );
}
