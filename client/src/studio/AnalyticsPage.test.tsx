import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createReviewData, createReviewState, reviewUser } from "./fixtures";
import type { StudioContextValue } from "./types";

const { useStudio } = vi.hoisted(() => ({ useStudio: vi.fn() }));
vi.mock("./context", () => ({ useStudio }));

import { AnalyticsPage } from "./AnalyticsPage";

function studio(
  overrides: Partial<StudioContextValue> = {},
): StudioContextValue {
  return {
    state: createReviewState("analytics"),
    data: createReviewData(),
    review: true,
    user: reviewUser,
    navigate: vi.fn(),
    patchDraft: vi.fn(),
    patchState: vi.fn(),
    updateData: vi.fn(),
    notify: vi.fn(),
    openPicker: vi.fn(),
    openLive: vi.fn(),
    requestGeneration: vi.fn(),
    saveDraft: vi.fn(),
    refresh: vi.fn(),
    ...overrides,
  };
}

describe("V1.4 数据看板", () => {
  beforeEach(() => useStudio.mockReset());

  it("呈现三项筛选、四个指标、完整图表和三条作品表现", () => {
    useStudio.mockReturnValue(studio());
    render(<AnalyticsPage />);

    expect(screen.getByLabelText("时间筛选")).toHaveValue("7");
    expect(screen.getByLabelText("平台筛选")).toHaveValue("all");
    expect(screen.getByLabelText("人物筛选")).toHaveValue("all");
    expect(screen.getByText("示例数据")).toBeInTheDocument();
    expect(screen.getByText("已发布视频")).toBeInTheDocument();
    expect(screen.getByText("12.8 万")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "近7天播放趋势" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("合计播放：12.8 万")).toHaveLength(2);
    expect(screen.getAllByText("抖音").length).toBeGreaterThan(0);
    expect(screen.getAllByText("视频号").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("row")).toHaveLength(4);
  });

  it("平台、人物与时间筛选会改变审核数据", () => {
    useStudio.mockReturnValue(studio());
    render(<AnalyticsPage />);

    fireEvent.change(screen.getByLabelText("平台筛选"), {
      target: { value: "视频号" },
    });
    expect(screen.getByText("农村自建房户型避坑")).toBeInTheDocument();
    expect(screen.queryByText("张工 · 建房预算")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("平台筛选"), {
      target: { value: "all" },
    });
    fireEvent.change(screen.getByLabelText("人物筛选"), {
      target: { value: "zhang" },
    });
    expect(screen.getByText("张工 · 建房预算")).toBeInTheDocument();
    expect(screen.queryByText("农村自建房户型避坑")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("时间筛选"), {
      target: { value: "30" },
    });
    expect(screen.getByText("三代同堂的家这样设计")).toBeInTheDocument();
  });

  it("查看作品进入与该行关联的真实任务或来源", () => {
    const value = studio();
    useStudio.mockReturnValue(value);
    render(<AnalyticsPage />);

    const firstRow = screen.getByRole("row", {
      name: /\u5f20\u5de5 · \u5efa\u623f\u9884\u7b97/,
    });
    fireEvent.click(within(firstRow).getByRole("button", { name: "查看视频" }));
    expect(value.navigate).toHaveBeenCalledWith("task-detail", {
      selectedTaskId: "task-completed",
      returnTo: "analytics",
    });

    const thirdRow = screen.getByRole("row", {
      name: /农村自建房户型避坑/,
    });
    fireEvent.click(within(thirdRow).getByRole("button", { name: "查看视频" }));
    expect(value.navigate).toHaveBeenCalledWith("viral-detail", {
      selectedVideoId: "视频号-3",
      returnTo: "analytics",
    });
  });

  it("再创作会清理旧草稿并带入所选来源与人物", () => {
    const value = studio();
    useStudio.mockReturnValue(value);
    render(<AnalyticsPage />);

    const row = screen.getByRole("row", {
      name: /农村自建房户型避坑/,
    });
    fireEvent.click(
      within(row).getByRole("button", { name: "再次创作（从该视频）" }),
    );
    expect(value.patchDraft).toHaveBeenCalledWith(
      expect.objectContaining({
        sourceId: "视频号-3",
        ipId: "wang",
        prompt: "",
        referenceIds: [],
        firstFrameId: undefined,
        audioId: undefined,
      }),
    );
    expect(value.navigate).toHaveBeenCalledWith("replica", {
      selectedVideoId: "视频号-3",
      returnTo: "analytics",
    });
  });

  it("正式工作区没有统计接口时不显示审核数值", () => {
    useStudio.mockReturnValue(
      studio({
        review: false,
        data: {
          people: [],
          assets: [],
          videos: [],
          tasks: [],
          projects: [],
          errors: [],
          loading: false,
          stats: null,
        },
      }),
    );
    render(<AnalyticsPage />);
    expect(screen.getByText("数据接口尚未接通")).toBeInTheDocument();
    expect(screen.queryByText("12.8 万")).not.toBeInTheDocument();
    expect(screen.queryByText("示例数据")).not.toBeInTheDocument();
  });
});
