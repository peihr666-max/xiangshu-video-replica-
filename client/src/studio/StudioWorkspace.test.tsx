import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createReviewData, createReviewState, reviewUser } from "./fixtures";
import { StudioWorkspace } from "./StudioWorkspace";
import { createState } from "./state";

const live = vi.hoisted(() => ({
  loadStudioData: vi.fn(),
  loadPersonAssets: vi.fn(),
  loadProjectDraft: vi.fn(),
  reloadTasks: vi.fn(async (): Promise<unknown[]> => []),
  reloadStats: vi.fn(async (): Promise<unknown> => null),
}));
vi.mock("./live", () => live);

const livePanel = vi.hoisted(() => ({
  project: {
    id: "project-1",
    owner_user_id: "review-user",
    name: "张工预算项目",
    status: "ACTIVE",
    reference_asset_id: "asset-1",
    reference_upload_status: "READY",
    analysis_status: "READY",
  },
}));
vi.mock("./LiveWorkspacePanel", () => ({
  LiveWorkspacePanel: (props: {
    handoffBatch?: { id: string } | null;
    onBatchCreated: (batch: { id: string }) => void;
    onClose: () => void;
    onHandoffConsumed?: () => void;
    onProjectSelected: (project: typeof livePanel.project) => void;
  }) => (
    <section aria-label="模拟已有功能工作区">
      <button
        type="button"
        onClick={() => props.onProjectSelected(livePanel.project)}
      >
        选择测试项目
      </button>
      <button
        type="button"
        onClick={() => props.onBatchCreated({ id: "batch-1" })}
      >
        创建测试批次
      </button>
      {props.handoffBatch ? (
        <span>存在交接批次</span>
      ) : (
        <span>没有交接批次</span>
      )}
      {props.onHandoffConsumed ? (
        <button type="button" onClick={props.onHandoffConsumed}>
          消费交接批次
        </button>
      ) : null}
      <button type="button" onClick={props.onClose}>
        返回新工作台
      </button>
    </section>
  ),
}));

describe("V1.4 workspace integration", () => {
  it("publishing accounts stay in account settings, not the publishing editor", () => {
    render(
      <StudioWorkspace
        currentUser={reviewUser}
        reviewData={createReviewData()}
        initialState={createReviewState("profile")}
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "发布账号" }));
    expect(
      screen.getByRole("heading", { name: "发布账号管理" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "用户档案" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "发布管理" }),
    ).not.toBeInTheDocument();
  });
  beforeEach(() => {
    vi.clearAllMocks();
    live.loadPersonAssets.mockResolvedValue({ assets: [], errors: [] });
    window.history.replaceState(null, "", "/#studio/workbench");
  });
  it("renders the approved navigation order and keeps review data isolated", () => {
    render(
      <StudioWorkspace
        currentUser={reviewUser}
        reviewData={createReviewData()}
        initialState={createReviewState("workbench")}
      />,
    );
    const nav = within(screen.getByRole("navigation", { name: "主要导航" }));
    expect(nav.getAllByRole("button").map((node) => node.textContent)).toEqual(
      expect.arrayContaining(["爆款视频", "文案工坊", "视频创作"]),
    );
    expect(
      screen.getByText("从一个乡墅灵感，开始视频创作"),
    ).toBeInTheDocument();
    expect(live.loadStudioData).not.toHaveBeenCalled();
    fireEvent.click(nav.getByRole("button", { name: "文案工坊" }));
    fireEvent.click(screen.getByRole("button", { name: "用于数字人口播" }));
    expect(screen.getByText("张工本人音色 V1")).toBeInTheDocument();
    expect(screen.getByText(/去文案工坊修改/)).toBeInTheDocument();
  });
  it("changing IP invalidates the previous person's voice and avatar", () => {
    render(
      <StudioWorkspace
        currentUser={reviewUser}
        reviewData={createReviewData()}
        initialState={createReviewState("oral")}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "更换 IP" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: /李总/ }),
    );
    expect(screen.queryByText("张工本人音色 V1")).not.toBeInTheDocument();
    expect(screen.getByText("待确认 V3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成口播视频" })).toBeDisabled();
  });
  it("cancelling a picker leaves the original draft intact", () => {
    render(
      <StudioWorkspace
        currentUser={reviewUser}
        reviewData={createReviewData()}
        initialState={createReviewState("oral")}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "更换 IP" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "关闭" }),
    );
    expect(screen.getByText("张工本人音色 V1")).toBeInTheDocument();
  });
  it("loads real data without falling back to review examples", async () => {
    live.loadStudioData.mockResolvedValue({
      people: [],
      assets: [],
      videos: [],
      tasks: [],
      projects: [],
      errors: ["人物库暂不可用"],
      loading: false,
      stats: null,
    });
    render(<StudioWorkspace currentUser={reviewUser} />);
    await waitFor(() => expect(live.loadStudioData).toHaveBeenCalled());
    expect(screen.getByText(/人物库暂不可用/)).toBeInTheDocument();
    expect(screen.queryByText("张工")).not.toBeInTheDocument();
    expect(screen.queryByText(/示例审核/)).not.toBeInTheDocument();
  });

  it("关闭已有项目工作区不会再次导入并覆盖当前草稿", async () => {
    const imported = createReviewState("workbench").draft;
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    live.loadProjectDraft.mockResolvedValue({ draft: imported, errors: [] });
    render(<StudioWorkspace currentUser={reviewUser} />);

    // 工作台“上传视频”已是图标化的本机文件上传；打开旧项目面板的入口
    // 是无来源时的“开始复刻”。
    fireEvent.click(screen.getByRole("button", { name: "开始复刻" }));
    fireEvent.click(screen.getByRole("button", { name: "选择测试项目" }));
    await waitFor(() => expect(live.loadProjectDraft).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "返回新工作台" }));
    await waitFor(() => expect(live.loadProjectDraft).toHaveBeenCalledTimes(1));
  });

  it("workbench metric cards show real platform stats", async () => {
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
      stats: {
        today_completed: 5,
        running: 2,
        queued: 1,
        needs_attention: 4,
        total_completed: 42,
      },
    });
    render(<StudioWorkspace currentUser={reviewUser} />);

    await waitFor(() => expect(screen.getByText("5")).toBeInTheDocument());
    // 队列 = running + queued（3）；待处理来自统计而非 20 条切片。
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("消费任务交接后清除暂存批次", async () => {
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    render(<StudioWorkspace currentUser={reviewUser} />);

    fireEvent.click(screen.getByRole("button", { name: "开始复刻" }));
    fireEvent.click(screen.getByRole("button", { name: "创建测试批次" }));
    expect(screen.getByText("存在交接批次")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "消费交接批次" }));
    expect(screen.getByText("没有交接批次")).toBeInTheDocument();
  });

  it("polls generation task progress silently while the workspace is open", async () => {
    vi.useFakeTimers();
    const runningTask = {
      id: "batch-9",
      batchId: "batch-9",
      title: "乡墅批次一",
      type: "视频生成" as const,
      status: "running" as const,
      progress: 45,
      submitted: "2026-09-06T09:00:00Z",
    };
    live.loadStudioData.mockResolvedValue({
      people: [],
      assets: [],
      videos: [],
      projects: [],
      errors: [],
      loading: false,
      stats: null,
      tasks: [runningTask],
    });
    live.reloadTasks.mockResolvedValue([
      { ...runningTask, status: "completed" as const, progress: 100 },
    ]);

    render(
      <StudioWorkspace
        currentUser={reviewUser}
        initialState={createState("tasks")}
      />,
    );
    await vi.waitFor(() =>
      expect(screen.getByText("生成中 45%")).toBeInTheDocument(),
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });

    expect(live.reloadTasks).toHaveBeenCalledWith(reviewUser);
    // "已完成" appears as both the filter tab and the refreshed row status.
    expect(screen.getAllByText("已完成")).toHaveLength(2);
    expect(screen.queryByText("生成中 45%")).not.toBeInTheDocument();
  });
});
