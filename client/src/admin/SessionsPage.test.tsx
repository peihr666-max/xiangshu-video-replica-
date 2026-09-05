import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAdminCsrfToken } from "../api";
import { SessionsPage } from "./SessionsPage";

function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  });
}

const CUSTOMER_ID = "customer-1";
const sessionItem = {
  session_id: "sess-1",
  user_id: CUSTOMER_ID,
  username: "customer_one",
  device_id: "device-1",
  session_epoch: 3,
  lease_until: "2026-09-01T12:01:00+00:00",
  last_heartbeat_at: "2026-09-01T11:59:30+00:00",
  created_at: "2026-08-30T08:00:00+00:00",
  updated_at: "2026-09-01T11:59:30+00:00",
  device_name: "办公室电脑",
  platform: "windows",
  slot_no: 1,
  device_status: "ACTIVE",
};

function sessionList() {
  return { items: [sessionItem], total: 1, limit: 50, offset: 0 };
}

describe("SessionsPage", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-09-01T12:00:00+00:00"));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads all live sessions on mount and renders the lease card", async () => {
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
      jsonResponse(sessionList()),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<SessionsPage />);

    expect(await screen.findByText("customer_one")).toBeInTheDocument();
    expect(screen.getByText("办公室电脑 · Windows")).toBeInTheDocument();
    expect(screen.getByText("租约剩余 60 秒")).toBeInTheDocument();
    expect(screen.getByText("心跳 30 秒前")).toBeInTheDocument();
    expect(screen.getByText("Epoch 3")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "67",
    );
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      "/api/control/customer-sessions/live?limit=50&offset=0",
    );
  });

  it("loads the requested customer automatically", async () => {
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
      jsonResponse(sessionList()),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<SessionsPage userId={CUSTOMER_ID} />);

    await screen.findByText("customer_one");
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      `/api/control/customers/${CUSTOMER_ID}/sessions?limit=50`,
    );
    expect(screen.queryByLabelText("客户 ID")).not.toBeInTheDocument();
  });

  it("revokes a session with a reason and refreshes the live list", async () => {
    setAdminCsrfToken("csrf-token-1");
    const fetchMock = vi.fn((url: string, _init?: RequestInit) =>
      String(url).includes("/revoke")
        ? jsonResponse({ request_id: "revoke-1" })
        : jsonResponse(sessionList()),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<SessionsPage />);
    await screen.findByText("customer_one");
    fireEvent.click(
      screen.getByRole("button", { name: "强制下线 customer_one" }),
    );
    fireEvent.change(screen.getByLabelText("操作原因"), {
      target: { value: "客服确认账号异常" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认强制下线" }));

    expect(
      await screen.findByText(/已强制下线 customer_one/),
    ).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const revokeCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/revoke"),
    );
    expect(revokeCall?.[1]).toMatchObject({ method: "POST" });
    expect(JSON.parse(String(revokeCall?.[1]?.body))).toMatchObject({
      confirm: true,
      reason: "客服确认账号异常",
      session_epoch: 3,
    });
  });

  it("keeps the revoke idempotency key after an ambiguous failure", async () => {
    setAdminCsrfToken("csrf-token-1");
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "11111111-1111-4111-8111-111111111111",
    );
    let revokeAttempts = 0;
    const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
      if (String(url).includes("/revoke")) {
        revokeAttempts += 1;
        return revokeAttempts === 1
          ? Promise.reject(new TypeError("Failed to fetch"))
          : jsonResponse({ request_id: "revoke-1" });
      }
      return jsonResponse(sessionList());
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SessionsPage />);
    await screen.findByText("customer_one");
    fireEvent.click(
      screen.getByRole("button", { name: "强制下线 customer_one" }),
    );
    fireEvent.change(screen.getByLabelText("操作原因"), {
      target: { value: "网络失败后重试" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认强制下线" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Failed to fetch",
    );
    fireEvent.click(screen.getByRole("button", { name: "确认强制下线" }));
    expect(
      await screen.findByText(/已强制下线 customer_one/),
    ).toBeInTheDocument();

    const keys = fetchMock.mock.calls
      .filter(([url]) => String(url).includes("/revoke"))
      .map(([, init]) => new Headers(init?.headers).get("Idempotency-Key"));
    expect(keys).toEqual([
      "11111111-1111-4111-8111-111111111111",
      "11111111-1111-4111-8111-111111111111",
    ]);
  });

  it("keeps the adjustment form secondary and uses seconds", async () => {
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
      jsonResponse(sessionList()),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<SessionsPage userId={CUSTOMER_ID} />);

    await screen.findByText("customer_one");
    expect(screen.queryByLabelText("加款秒数")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开后台加秒" }));
    expect(screen.getByLabelText("加款秒数")).toBeInTheDocument();
    expect(screen.queryByText(/加款条数/)).not.toBeInTheDocument();
  });

  it("hides all write actions for read-only operators", async () => {
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
      jsonResponse(sessionList()),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<SessionsPage userId={CUSTOMER_ID} readOnly />);

    await screen.findByText("customer_one");
    expect(
      screen.queryByRole("button", { name: /强制下线/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /后台加秒/ }),
    ).not.toBeInTheDocument();
  });
});
