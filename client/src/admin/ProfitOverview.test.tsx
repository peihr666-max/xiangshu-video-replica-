import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAdminCsrfToken } from "../api";
import { ProfitOverview } from "./ProfitOverview";

const overviewPayload = {
  prices: [
    {
      price_date: "2099-01-01",
      price_768p_fen: 99,
      price_2k_fen: 199,
      note: "未来价格",
      created_by_username: "admin",
    },
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
      cost_unknown_count: 2,
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
    expect(screen.getByText("收入")).toBeInTheDocument();
    expect(screen.getByText("已确认成本")).toBeInTheDocument();
    // 成本口径前的日子：成本/毛利/利润率显示占位。
    expect(screen.getAllByText("口径前").length).toBeGreaterThan(0);
    expect(screen.getByText(/当前生效：768P 0.10 元\/秒/)).toBeInTheDocument();
    expect(screen.queryByText(/当前生效：768P 0.99 元\/秒/)).toBeNull();
  });

  it("opens the selected day details with its complete accounting basis", async () => {
    installFetch();
    render(<ProfitOverview />);

    await screen.findByRole("heading", { name: "日利润表" });
    fireEvent.click(screen.getAllByRole("button", { name: "查看明细" })[0]);

    const dialog = screen.getByRole("dialog", { name: "2026-09-04 利润明细" });
    expect(dialog).toHaveTextContent("结算秒数 10 秒");
    expect(dialog).toHaveTextContent("视频数 1");
    expect(dialog).toHaveTextContent("收入 1.00 元");
    expect(dialog).toHaveTextContent("成本 0.90 元");
    expect(dialog).toHaveTextContent("毛利 0.10 元");
    expect(dialog).toHaveTextContent("2 项真实用量未知");
  });

  it("draws smooth income and confirmed-cost paths", async () => {
    installFetch();
    render(<ProfitOverview />);

    await screen.findByRole("heading", { name: "日利润表" });
    const chart = screen.getByRole("img", {
      name: "收入与已确认成本趋势",
    });
    const paths = chart.querySelectorAll("path");
    expect(paths).toHaveLength(2);
    expect(paths[0]?.getAttribute("d")).toContain("C");
    expect(screen.getByText("已确认成本")).toBeInTheDocument();
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

    expect(
      fetchMock.mock.calls.some(
        ([url, options]) =>
          String(url).endsWith("/api/control/profit/daily-price") &&
          options?.method === "PUT",
      ),
    ).toBe(false);
    expect(
      screen.getByRole("dialog", { name: "确认保存每日售价" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认保存" }));

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
    expect(
      new Headers(putCall?.[1]?.headers).get("Idempotency-Key"),
    ).toBeTruthy();
  });

  it("reuses the price-save idempotency key after an ambiguous failure", async () => {
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "22222222-2222-4222-8222-222222222222",
    );
    let writeAttempts = 0;
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url.includes("/api/control/profit/overview") && !options?.method) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => overviewPayload,
        });
      }
      if (options?.method === "PUT") {
        writeAttempts += 1;
        return writeAttempts === 1
          ? Promise.reject(new TypeError("Failed to fetch"))
          : Promise.resolve({
              ok: true,
              status: 200,
              json: async () => overviewPayload.prices,
            });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ProfitOverview />);

    await screen.findByRole("heading", { name: "每日对外售价录入" });
    fireEvent.change(screen.getByLabelText(/操作原因/), {
      target: { value: "网络失败后重试" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存售价" }));
    fireEvent.click(screen.getByRole("button", { name: "确认保存" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Failed to fetch",
    );
    fireEvent.click(screen.getByRole("button", { name: "确认保存" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已保存");

    const keys = fetchMock.mock.calls
      .filter(([, options]) => options?.method === "PUT")
      .map(([, options]) =>
        new Headers(options?.headers).get("Idempotency-Key"),
      );
    expect(keys).toEqual([
      "22222222-2222-4222-8222-222222222222",
      "22222222-2222-4222-8222-222222222222",
    ]);
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
