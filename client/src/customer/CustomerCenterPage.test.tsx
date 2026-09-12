import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { CustomerApiError } from "../api";
import type { WorkspaceShellProps } from "../workspace-shell";
import { CustomerCenterPage } from "./CustomerCenterPage";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  initialize: vi.fn(),
  create: vi.fn(),
  rotate: vi.fn(),
  revoke: vi.fn(),
  summary: vi.fn(),
  navigate: vi.fn(),
  notice: vi.fn(),
  transactions: vi.fn(),
  orders: vi.fn(),
}));
vi.mock("../studio/context", () => ({
  useStudio: () => ({
    navigate: mocks.navigate,
    notify: mocks.notice,
    user: { username: "alice", display_name: "Alice" },
  }),
}));
vi.mock("../studio/MainPages", () => ({
  PublishAccountsPanel: () => <div>发布账号真实面板</div>,
}));
vi.mock("../studio/live", () => ({ loadPublishAccounts: async () => [] }));
vi.mock("../api", async (original) => ({
  ...(await original<typeof import("../api")>()),
  customerListApiKeys: mocks.list,
  customerInitializeDefaultApiKey: mocks.initialize,
  customerCreateApiKey: mocks.create,
  customerRotateApiKey: mocks.rotate,
  customerRevokeApiKey: mocks.revoke,
  customerGetCenterSummary: mocks.summary,
  customerListWalletTransactions: mocks.transactions,
  customerListRechargeOrders: mocks.orders,
  getStudioNotificationPreferences: async () => ({ enabled: true }),
}));

const token = {
  id: "key-1",
  token_group_id: "key-1",
  credential_version: 1,
  key_prefix: "ABCDEFGH",
  label: "默认 Token",
  scopes: ["wallet"],
  created_at: "2026-09-12T12:00:00Z",
  last_used_at: null,
  revoked_at: null,
  is_default: true,
  total_consumed_credits: 0,
};
function setup() {
  vi.clearAllMocks();
  mocks.list.mockResolvedValue({ items: [token], total: 1 });
  mocks.summary.mockResolvedValue({
    user_id: "alice-id",
    available_credits: 125,
    reserved_credits: 10,
    total_consumed_credits: 22,
    active_tokens: 1,
  });
  mocks.transactions.mockResolvedValue({
    items: [],
    total: 0,
    limit: 20,
    offset: 0,
  });
  mocks.orders.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
  const account = {
    profile: {
      user_id: "alice-id",
      username: "alice",
      display_name: "Alice",
      joined_at: "2026-09-12T12:00:00Z",
      activation_code_masked: null,
      activation_status: null,
      activated_at: null,
      device_slots_used: 1,
      device_slots_total: null,
    },
    profileLoadError: "",
    devices: { slots: [], pending_pairings: [] },
    deviceError: "",
    store: { loadSessionToken: async () => "ephemeral-test-session" },
    onSessionExpired: vi.fn(),
    onRefreshProfile: vi.fn().mockResolvedValue(undefined),
    onRefreshDevices: vi.fn(),
    onLogout: vi.fn(),
    onUpdateProfile: vi.fn(),
    onProfileUpdated: vi.fn(),
    onUnbind: vi.fn(),
  } as unknown as NonNullable<WorkspaceShellProps["customerAccount"]>;
  return account;
}

test("renders real account points and six focused tabs without reissuing an existing default", async () => {
  render(<CustomerCenterPage account={setup()} />);
  expect(await screen.findByText("125")).toBeVisible();
  expect(screen.getAllByRole("tab")).toHaveLength(6);
  expect(screen.getByRole("tab", { name: "接口价格" })).toBeVisible();
  expect(screen.getByText("alice-id")).toBeVisible();
  expect(mocks.initialize).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "返回主界面" }));
  expect(mocks.navigate).toHaveBeenCalledWith("workbench");
});

test("creates a Token through the API and clears its one-time secret on close", async () => {
  const account = setup();
  mocks.create.mockResolvedValue({
    ...token,
    id: "key-2",
    label: "工作电脑",
    plaintext: "one-time-test-value",
  });
  render(<CustomerCenterPage account={account} />);
  await screen.findByText("125");
  fireEvent.click(screen.getByRole("button", { name: "新建 Token" }));
  fireEvent.change(screen.getByLabelText("Token 名称"), {
    target: { value: "工作电脑" },
  });
  fireEvent.click(screen.getByRole("button", { name: "确认新建" }));
  expect(await screen.findByDisplayValue("one-time-test-value")).toBeVisible();
  await waitFor(() =>
    expect(mocks.create).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "session" }),
      "工作电脑",
      expect.any(String),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "已保存，关闭" }));
  expect(
    screen.queryByDisplayValue("one-time-test-value"),
  ).not.toBeInTheDocument();
});

test("failed summary stays unknown and retry loads the real balance", async () => {
  const account = setup();
  mocks.summary.mockRejectedValueOnce(new Error("账号服务暂不可用"));
  render(<CustomerCenterPage account={account} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "账号服务暂不可用",
  );
  expect(screen.queryByText("125")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "重试加载账号" }));
  expect(await screen.findByText("125")).toBeVisible();
});

test("a revoked default is not re-created and order errors are not shown as empty history", async () => {
  const account = setup();
  mocks.list.mockResolvedValue({
    items: [{ ...token, revoked_at: "2026-09-12T13:00:00Z" }],
    total: 1,
  });
  mocks.orders.mockRejectedValueOnce(new Error("充值记录暂不可用"));
  render(<CustomerCenterPage account={account} />);
  expect(await screen.findByText("已撤销")).toBeVisible();
  expect(mocks.initialize).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("tab", { name: "充值记录" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "充值记录暂不可用",
  );
  expect(screen.queryByText("暂无充值记录")).toBeNull();
});

test("each function has one destination and account settings contain no device section", async () => {
  render(<CustomerCenterPage account={setup()} />);
  expect(await screen.findByText("125")).toBeVisible();
  expect(screen.queryByRole("tab", { name: "账号概览" })).toBeNull();
  expect(screen.getByRole("tab", { name: "Token 管理" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  fireEvent.click(screen.getByRole("tab", { name: "账号设置" }));
  expect(screen.queryByRole("button", { name: "新建 Token" })).toBeNull();
  expect(screen.queryByText("登录设备")).toBeNull();
  expect(screen.queryByRole("button", { name: /设备/ })).toBeNull();
  expect(screen.getByRole("switch", { name: "任务与公告通知" })).toBeVisible();
});

test("expired default recovery reloads existing credentials instead of looping on the expired key", async () => {
  const account = setup();
  mocks.list.mockResolvedValueOnce({ items: [], total: 0 });
  mocks.initialize.mockRejectedValue(
    new CustomerApiError({
      message: "恢复窗口已结束，请刷新列表后重试。",
      status: 409,
      code: "TOKEN_RETRY_EXPIRED",
    }),
  );
  render(<CustomerCenterPage account={account} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("恢复窗口已结束");
  fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
  expect(await screen.findByText("默认 Token")).toBeVisible();
  expect(mocks.initialize).toHaveBeenCalledTimes(1);
});
