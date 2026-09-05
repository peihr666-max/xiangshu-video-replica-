import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CostDetails } from "./CostDetails";

const payload = {
  total_cost_fen: 48620,
  total_output_seconds: 4680,
  average_video_cost_per_second_fen: 10.389,
  unknown_count: 1,
  record_total: 1200,
  records_truncated: true,
  records: [],
  days: [
    {
      day: "2026-09-04",
      video_count: 312,
      output_seconds: 4680,
      video_768p_fen: 28980,
      video_2k_fen: 15240,
      analysis_fen: 3840,
      image_fen: 560,
      context_ir_fen: 0,
      total_cost_fen: 48620,
      unknown_count: 1,
    },
    {
      day: "2026-09-03",
      video_count: 2,
      output_seconds: 30,
      video_768p_fen: 300,
      video_2k_fen: 0,
      analysis_fen: 0,
      image_fen: 0,
      context_ir_fen: 0,
      total_cost_fen: 300,
      unknown_count: 0,
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CostDetails", () => {
  it("renders actual usage KPIs, daily categories and unknown usage", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({ ok: true, status: 200, json: async () => payload }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<CostDetails />);

    expect(await screen.findByText("已确认成本")).toBeInTheDocument();
    expect(screen.getByText("平均已确认视频成本")).toBeInTheDocument();
    expect(
      screen.getByText("操作记录仅加载最近 1,000 条，共 1,200 条。"),
    ).toBeInTheDocument();
    expect((await screen.findAllByText("¥486.20")).length).toBeGreaterThan(0);
    expect(screen.getByText("4,680 秒")).toBeInTheDocument();
    expect(screen.getByText("1 项未知")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "导出成本 CSV" })).toHaveAttribute(
      "href",
      expect.stringContaining("lookback_days=30"),
    );
    const chart = screen.getByRole("img", { name: "成本构成堆叠柱状图" });
    expect(chart.textContent?.indexOf("09-03")).toBeLessThan(
      chart.textContent?.indexOf("09-04") ?? 0,
    );
    expect(chart.querySelectorAll(".is-2k")).toHaveLength(1);

    fireEvent.change(screen.getByLabelText("时间范围"), {
      target: { value: "7" },
    });
    fireEvent.click(screen.getByRole("button", { name: "查询" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        expect.stringContaining("lookback_days=7"),
        expect.anything(),
      ),
    );
  });
});
