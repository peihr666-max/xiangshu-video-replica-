import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OverviewPage } from "./OverviewPage";

const summaryPayload = {
  today: {
    generation_count: 328,
    succeeded: 302,
    online_devices: 47,
    active_customers: 89,
    recharge_fen: 485000,
  },
  trend: [
    { day: "2026-08-30", succeeded: 210, failed: 28 },
    { day: "2026-09-05", succeeded: 302, failed: 12 },
  ],
  todos: {
    pending_pairings: 3,
    failed_tasks_7d: 5,
    reconciliation_problems: 2,
    expiring_codes_7d: 0,
  },
  device_slots: { bound: 918, total: 1024 },
};

function installFetch() {
  const fetchMock = vi.fn((url: string) => {
    if (url.includes("/api/control/dashboard/summary")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => summaryPayload,
      });
    }
    return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.stubGlobal("URL", {
    createObjectURL: vi.fn(() => "blob:test"),
    revokeObjectURL: vi.fn(),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("OverviewPage", () => {
  it("renders KPI cards, trend, todos and quick actions from the summary", async () => {
    const onNavigate = vi.fn();
    installFetch();
    render(<OverviewPage onNavigate={onNavigate} />);

    expect(await screen.findByText("328")).toBeInTheDocument();
    expect(screen.getByText("¥4850.00")).toBeInTheDocument();
    expect(screen.getByText("918 / 1024")).toBeInTheDocument();
    expect(screen.getByText("近 7 日生成趋势")).toBeInTheDocument();

    // 待办计数
    expect(screen.getByText("待批准配对")).toBeInTheDocument();
    expect(screen.getByText("对账不一致")).toBeInTheDocument();
    // 即将过期激活码为 0 时不提供「去处理」
    const expiring = screen.getByText("即将过期激活码").closest("li");
    expect(expiring?.querySelector("button")).toBeNull();

    // 快捷操作跳转
    fireEvent.click(screen.getByRole("button", { name: "经营分析" }));
    expect(onNavigate).toHaveBeenCalledWith("analytics");
  });

  it("shows an error banner when the summary request fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new Error("network down"))),
    );
    render(<OverviewPage />);

    expect(await screen.findByText(/network down/)).toBeInTheDocument();
  });
});
