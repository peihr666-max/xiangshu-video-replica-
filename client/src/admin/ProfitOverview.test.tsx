import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAdminCsrfToken } from "../api";
import { ProfitOverview } from "./ProfitOverview";

const overviewPayload = {
  prices: [
    {
      price_date: "2026-09-04",
      price_768p_fen: 10,
      price_2k_fen: 20,
      note: null,
      created_by_username: "admin",
    },
  ],
  days: [
    {
      day: "2026-09-04",
      video_count: 1,
      settled_seconds: 10,
      revenue_fen: 100,
      cost_fen: 90,
      gross_fen: 10,
      margin_pct: 10.0,
    },
    {
      day: "2026-09-03",
      video_count: 3,
      settled_seconds: 30,
      revenue_fen: 0,
      cost_fen: null,
      gross_fen: null,
      margin_pct: null,
    },
  ],
  cost_coverage_note: "成本自 2026-09 费率快照启用起核算；更早区间不回填。",
};

function installFetch() {
  const fetchMock = vi.fn((url: string, options?: RequestInit) => {
    if (url.includes("/api/control/profit/overview") && !options?.method) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => overviewPayload,
      });
    }
    if (
      url.includes("/api/control/profit/daily-price") &&
      options?.method === "PUT"
    ) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => overviewPayload.prices,
      });
    }
    return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  setAdminCsrfToken("csrf-test");
  vi.stubGlobal("URL", {
    createObjectURL: vi.fn(() => "blob:test"),
    revokeObjectURL: vi.fn(),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ProfitOverview", () => {
  it("renders the daily price form and the profit table", async () => {
    installFetch();
    render(<ProfitOverview />);

    expect(
      await screen.findByRole("heading", { name: "每日对外售价录入" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "日利润表" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2026-09-04")).toBeInTheDocument();
    // 成本口径前的日子：成本/毛利/利润率显示占位。
    expect(screen.getAllByText("口径前").length).toBeGreaterThan(0);
  });

  it("saves the daily price with the write contract", async () => {
    const fetchMock = installFetch();
    render(<ProfitOverview />);

    await screen.findByRole("heading", { name: "每日对外售价录入" });
    fireEvent.change(screen.getByLabelText(/生效日期/), {
      target: { value: "2026-09-06" },
    });
    fireEvent.change(screen.getByLabelText(/768P 售价/), {
      target: { value: "0.12" },
    });
    fireEvent.change(screen.getByLabelText(/2K 售价/), {
      target: { value: "0.20" },
    });
    fireEvent.change(screen.getByLabelText(/操作原因/), {
      target: { value: "客户续费定价" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存售价" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, options]) =>
            String(url).endsWith("/api/control/profit/daily-price") &&
            options?.method === "PUT",
        ),
      ).toBe(true);
    });
    const putCall = fetchMock.mock.calls.find(
      ([url, options]) =>
        String(url).endsWith("/api/control/profit/daily-price") &&
        options?.method === "PUT",
    );
    const body = JSON.parse(String(putCall?.[1]?.body));
    expect(body).toMatchObject({
      price_date: "2026-09-06",
      price_768p_fen: 12,
      price_2k_fen: 20,
      confirm: true,
      reason: "客户续费定价",
    });
  });

  it("rejects a save without the mandatory reason", async () => {
    const fetchMock = installFetch();
    render(<ProfitOverview />);

    await screen.findByRole("heading", { name: "每日对外售价录入" });
    fireEvent.change(screen.getByLabelText(/操作原因/), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存售价" }));

    expect(await screen.findByText("请填写操作原因")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(
        ([url, options]) =>
          String(url).endsWith("/api/control/profit/daily-price") &&
          options?.method === "PUT",
      ),
    ).toBe(false);
  });

  it("hides the save action in read-only mode", async () => {
    installFetch();
    render(<ProfitOverview readOnly />);

    await screen.findByRole("heading", { name: "每日对外售价录入" });
    expect(screen.queryByRole("button", { name: "保存售价" })).toBeNull();
  });
});
