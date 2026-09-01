import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearAdminActivationSession,
  exchangeAdminSession,
} from "../api.admin";
import { ActivationCodesPage } from "./ActivationCodesPage";

function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  });
}

const CSRF_TOKEN_TEXT = "csrf-token-1";

const exchangePayload = {
  session_id: "session-1",
  expires_at: "2026-08-23T20:00:00+00:00",
  csrf_token: CSRF_TOKEN_TEXT,
  actor: {
    user_id: "admin-1",
    username: "admin",
    display_name: "管理员一号",
    role: "admin",
  },
};

const codesPage = {
  items: [
    {
      code_id: "code-1",
      batch_id: "batch-1",
      masked_code: "XS****01",
      status: "GENERATED",
      bound_user_id: null,
      bound_username: null,
      issued_at: null,
      devices: [],
    },
    {
      code_id: "code-2",
      batch_id: "batch-1",
      masked_code: "XS****02",
      status: "ACTIVE",
      bound_user_id: "user-9",
      bound_username: "customer_9",
      issued_at: "2026-08-20T10:00:00+00:00",
      devices: [
        {
          device_id: "device-1",
          slot_no: 1,
          display_name: "办公室电脑",
          platform: "windows",
          status: "BOUND",
          bound_at: "2026-08-20T10:05:00+00:00",
          last_active_at: "2026-08-21T10:05:00+00:00",
          unbound_at: null,
          revoked_at: null,
        },
      ],
    },
  ],
  limit: 50,
  offset: 0,
};

function installFetch(options?: { list?: "ok" | "unauthorized" }) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith("/api/control/admin/session/exchange")) {
      return jsonResponse(exchangePayload);
    }
    if (url.includes("/api/control/activation-codes?")) {
      if (options?.list === "unauthorized") {
        return jsonResponse(
          {
            detail: {
              code: "ADMIN_SESSION_INVALID",
              message: "Admin session is missing, revoked or invalid.",
            },
          },
          401,
        );
      }
      return jsonResponse(codesPage);
    }
    if (
      url.endsWith("/activation-codes/code-1/reveal") &&
      init?.method === "POST"
    ) {
      return jsonResponse({
        code_id: "code-1",
        activation_code: "XS04-AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD",
        masked_code: "XS****01",
        request_id: "req-reveal-1",
      });
    }
    if (
      url.endsWith("/activation-codes/code-2/revoke") &&
      init?.method === "POST"
    ) {
      return jsonResponse({
        code_id: "code-2",
        status: "REVOKED",
        request_id: "req-revoke-1",
      });
    }
    if (url.endsWith("/devices/device-1/unbind") && init?.method === "POST") {
      return jsonResponse({
        device_id: "device-1",
        status: "UNBOUND",
        outcome: "unbound",
        request_id: "req-unbind-1",
      });
    }
    throw new Error(`unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("ActivationCodesPage", () => {
  beforeEach(async () => {
    installFetch();
    await exchangeAdminSession("ASX1.body.signature");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    clearAdminActivationSession();
  });

  it("shows activation codes, bound accounts and related devices together", async () => {
    render(<ActivationCodesPage />);

    expect(await screen.findByText("XS****01")).toBeInTheDocument();
    expect(screen.getByText("customer_9")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "1 台设备" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "1 台设备" }));

    expect(screen.getByText("办公室电脑")).toBeInTheDocument();
    expect(screen.getByText("Windows")).toBeInTheDocument();
    expect(screen.getByText("已绑定")).toBeInTheDocument();
  });

  it("copies a code through the audited reveal route", async () => {
    const fetchMock = installFetch();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(<ActivationCodesPage />);
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "复制" }))[0],
    );

    expect(await screen.findByText(/req-reveal-1/)).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(
      "XS04-AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD",
    );
    const revealCall = fetchMock.mock.calls.find(([url]) =>
      String(url).endsWith("/activation-codes/code-1/reveal"),
    );
    expect(revealCall?.[1]?.body).toBe(
      JSON.stringify({ confirm: true, reason: "后台复制激活码" }),
    );
  });

  it("revokes a code with reason and explicit confirmation", async () => {
    const fetchMock = installFetch();
    render(<ActivationCodesPage />);

    fireEvent.click(
      (await screen.findAllByRole("button", { name: "撤销激活码" }))[1],
    );
    fireEvent.change(screen.getByLabelText("操作原因"), {
      target: { value: "客户申请停用" },
    });
    fireEvent.click(screen.getByLabelText("我已确认操作"));
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }));

    expect(await screen.findByText(/req-revoke-1/)).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "已撤销" })).toBeInTheDocument();
    const revokeCall = fetchMock.mock.calls.find(([url]) =>
      String(url).endsWith("/activation-codes/code-2/revoke"),
    );
    expect(revokeCall?.[1]?.body).toBe(
      JSON.stringify({ confirm: true, reason: "客户申请停用" }),
    );
  });

  it("unbinds a device without revoking its activation code", async () => {
    render(<ActivationCodesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "1 台设备" }));
    fireEvent.click(screen.getByRole("button", { name: "解绑设备" }));
    fireEvent.change(screen.getByLabelText("操作原因"), {
      target: { value: "客户更换电脑" },
    });
    fireEvent.click(screen.getByLabelText("我已确认操作"));
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }));

    expect(await screen.findByText(/req-unbind-1/)).toBeInTheDocument();
    expect(screen.getByText("已解绑")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "使用中" })).toBeInTheDocument();
  });

  it("filters locally by account and requests the selected status", async () => {
    const fetchMock = installFetch();
    render(<ActivationCodesPage />);
    await screen.findByText("XS****01");

    fireEvent.change(screen.getByLabelText("搜索"), {
      target: { value: "customer_9" },
    });
    expect(screen.queryByText("XS****01")).toBeNull();
    expect(screen.getByText("XS****02")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("状态"), {
      target: { value: "ACTIVE" },
    });
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).endsWith(
            "/api/control/activation-codes?status=ACTIVE&limit=50&offset=0",
          ),
        ),
      ).toBe(true),
    );
  });

  it("reports an expired session and hides writes for auditors", async () => {
    installFetch({ list: "unauthorized" });
    const onSessionExpired = vi.fn();
    const { unmount } = render(
      <ActivationCodesPage onSessionExpired={onSessionExpired} />,
    );
    expect(
      await screen.findByText(/会话已失效，请重新登录/),
    ).toBeInTheDocument();
    expect(onSessionExpired).toHaveBeenCalled();
    unmount();

    installFetch();
    render(<ActivationCodesPage readOnly />);
    expect(await screen.findByText("XS****01")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "复制" })).toBeNull();
    expect(screen.queryByRole("button", { name: "撤销激活码" })).toBeNull();
    expect(screen.getByText(/当前为只读模式/)).toBeInTheDocument();
  });
});
