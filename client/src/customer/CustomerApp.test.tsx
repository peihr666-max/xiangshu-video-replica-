import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CustomerApiError,
  customerActivate,
  customerHeartbeat,
  customerLogin,
  customerLogout,
  customerSwitch,
} from "../api";
import { CustomerApp } from "./CustomerApp";
import { createBrowserCustomerCredentialStore } from "./store";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    customerActivate: vi.fn(),
    customerLogin: vi.fn(),
    customerSwitch: vi.fn(),
    customerLogout: vi.fn(),
    customerHeartbeat: vi.fn(),
  };
});

const activateMock = vi.mocked(customerActivate);
const loginMock = vi.mocked(customerLogin);
const switchMock = vi.mocked(customerSwitch);
const logoutMock = vi.mocked(customerLogout);
const heartbeatMock = vi.mocked(customerHeartbeat);

const loginResponse = {
  user_id: "u-1",
  device_id: "d-1",
  session_id: "s-1",
  session_token: "sess-new",
  session_epoch: 3,
  session_lease_expires_at: new Date(Date.now() + 30 * 60_000).toISOString(),
  request_id: "req-1",
};

function conflictError() {
  return new CustomerApiError({
    message: "另一设备在线",
    status: 409,
    code: "OTHER_DEVICE_ONLINE",
    onlineDeviceNameMasked: "iPhone •••• AB12",
    onlineSlotNo: 2,
    leaseExpiresAt: new Date(Date.now() + 1800_000).toISOString(),
  });
}

describe("CustomerApp (FE-03 / T30 minimal mount)", () => {
  afterEach(() => {
    activateMock.mockReset();
    loginMock.mockReset();
    switchMock.mockReset();
    logoutMock.mockReset();
    heartbeatMock.mockReset();
  });

  it("lands on the activation screen when the store has no device credential", async () => {
    const store = createBrowserCustomerCredentialStore();
    render(<CustomerApp store={store} />);

    expect(
      await screen.findByRole("heading", { name: "激活" }),
    ).toBeInTheDocument();
  });

  it("reaches the workspace after a successful activation", async () => {
    activateMock.mockResolvedValueOnce({
      username: "客户甲",
      user_id: "u-1",
      device_id: "d-1",
      device_token: "dev-1",
      session_token: "sess-1",
      session_epoch: 1,
      session_lease_expires_at: new Date(
        Date.now() + 30 * 60_000,
      ).toISOString(),
    });
    const store = createBrowserCustomerCredentialStore();
    render(<CustomerApp store={store} />);

    fireEvent.change(await screen.findByLabelText(/激活码/), {
      target: { value: "CODE-1" },
    });
    fireEvent.change(screen.getByLabelText(/设备名/), {
      target: { value: "我的电脑" },
    });
    fireEvent.click(screen.getByRole("button", { name: "激活" }));

    expect(
      await screen.findByRole("heading", { name: "工作台" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/用户 ID：u-1/)).toBeInTheDocument();
  });

  it("restores the session automatically when the device credential is valid", async () => {
    loginMock.mockResolvedValueOnce({
      status: 201,
      replayed: false,
      session: loginResponse,
    });
    const store = createBrowserCustomerCredentialStore();
    await store.saveActivation("dev-1", "sess-old");
    render(<CustomerApp store={store} />);

    expect(
      await screen.findByRole("heading", { name: "工作台" }),
    ).toBeInTheDocument();
  });

  it("shows the conflict dialog and reaches the workspace after an explicit switch", async () => {
    loginMock.mockRejectedValueOnce(conflictError());
    switchMock.mockResolvedValueOnce({
      status: 201,
      replayed: false,
      session: loginResponse,
    });
    const store = createBrowserCustomerCredentialStore();
    await store.saveActivation("dev-1", "sess-old");
    render(<CustomerApp store={store} />);

    // The dialog must not auto-switch: it waits for explicit confirmation.
    const dialog = await screen.findByRole("dialog");
    expect(switchMock).not.toHaveBeenCalled();

    fireEvent.click(
      within(dialog).getByRole("button", { name: /switch to this device/i }),
    );

    expect(
      await screen.findByRole("heading", { name: "工作台" }),
    ).toBeInTheDocument();
    expect(switchMock).toHaveBeenCalledTimes(1);
  });

  it("returns to the login screen when the conflict switch is cancelled", async () => {
    loginMock.mockRejectedValueOnce(conflictError());
    const store = createBrowserCustomerCredentialStore();
    await store.saveActivation("dev-1", "sess-old");
    render(<CustomerApp store={store} />);

    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /cancel/i }));

    expect(
      await screen.findByRole("heading", { name: "欢迎回来" }),
    ).toBeInTheDocument();
    expect(switchMock).not.toHaveBeenCalled();
  });

  it("logs out of the workspace back to the login screen", async () => {
    logoutMock.mockResolvedValueOnce(undefined);
    loginMock.mockResolvedValueOnce({
      status: 201,
      replayed: false,
      session: loginResponse,
    });
    const store = createBrowserCustomerCredentialStore();
    await store.saveActivation("dev-1", "sess-old");
    render(<CustomerApp store={store} />);

    fireEvent.click(await screen.findByRole("button", { name: "退出登录" }));

    expect(
      await screen.findByRole("heading", { name: "欢迎回来" }),
    ).toBeInTheDocument();
  });
});
