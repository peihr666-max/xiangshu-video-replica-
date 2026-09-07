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
  // C7 云端草稿：默认无草稿/空列表，具体用例再覆盖。
  loadCloudDraft: vi.fn(async (): Promise<unknown> => undefined),
  loadDraftMaterials: vi.fn(async () => ({
    assets: [],
    unavailableIds: [],
  })),
  loadSavedScriptList: vi.fn(async (): Promise<unknown[]> => []),
  persistCloudDraft: vi.fn(async (_draft: unknown): Promise<void> => {}),
  persistSavedScript: vi.fn(
    async (_script: unknown, _sourceProjectId?: string): Promise<void> => {},
  ),
  publishScriptVersion: vi.fn(
    async (_projectId: string, _text: string): Promise<boolean> => true,
  ),
  extractScriptFromUpload: vi.fn(
    async (
      _projectId: string,
      _assetId: string,
    ): Promise<{ text: string }> => ({
      text: "",
    }),
  ),
}));
vi.mock("./live", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ...live,
}));

// 视频生成（C2）：只覆盖新引入的四个 api 出口，其余保持原模块行为，
// 避免既有用例（不触发这些函数）受 mock 影响。
const api = vi.hoisted(() => ({
  completeMaterialUpload: vi.fn(),
  createMaterialUploadIntent: vi.fn(),
  createOralTask: vi.fn(),
  getOralPrice: vi.fn(async () => ({ unit_price_fen: 100 })),
  getIndependentCapabilities: vi.fn(
    async (): Promise<{
      extended_modes_enabled: boolean;
      t2v_enabled: boolean;
      i2v_enabled: boolean;
      r2v_enabled: boolean;
      last_frame_enabled: boolean;
      max_reference_images: number;
      max_quantity: number;
    }> => ({
      extended_modes_enabled: true,
      t2v_enabled: true,
      i2v_enabled: true,
      r2v_enabled: true,
      last_frame_enabled: true,
      max_reference_images: 4,
      max_quantity: 4,
    }),
  ),
  getGenerationPriceQuote: vi.fn(
    async (): Promise<{
      resolution: string;
      duration_seconds: number;
      quantity: number;
      unit_price_fen_per_second: number;
      estimated_seconds: number;
      estimated_price_fen: number;
    }> => ({
      resolution: "768P",
      duration_seconds: 8,
      quantity: 1,
      unit_price_fen_per_second: 120,
      estimated_seconds: 8,
      estimated_price_fen: 960,
    }),
  ),
  createIndependentVideoTask: vi.fn(),
  listUserSavedPrompts: vi.fn(async (): Promise<unknown[]> => []),
  uploadMaterial: vi.fn(),
}));
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ...api,
}));

const livePanel = vi.hoisted(() => ({
  props: vi.fn(),
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
    characterIdentityId?: string;
    panel?: string;
  }) => {
    livePanel.props(props);
    return (
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
    );
  },
}));

describe("V1.4 workspace integration", () => {
  it("保持共享壳层尺寸稳定，避免路由切换时 Logo 和标题跳动", () => {
    const { container } = render(
      <StudioWorkspace
        currentUser={reviewUser}
        reviewData={createReviewData()}
        initialState={createReviewState("workbench")}
      />,
    );
    const shell = container.querySelector(".studio-shell");
    const main = container.querySelector(".studio-main");
    const sidebar = container.querySelector(".studio-sidebar");

    expect(shell?.className).not.toContain("studio-route-");
    expect(main).toHaveClass("studio-route-workbench");
    expect(sidebar?.closest("[class*='studio-route-']")).toBeNull();

    fireEvent.click(
      within(screen.getByRole("navigation", { name: "主要导航" })).getByRole(
        "button",
        { name: /任务中心/ },
      ),
    );

    expect(shell?.className).not.toContain("studio-route-");
    expect(main).toHaveClass("studio-route-tasks");
    expect(sidebar?.closest("[class*='studio-route-']")).toBeNull();
  });

  it("左下角与右上角使用同一个账号头像", () => {
    render(
      <StudioWorkspace
        currentUser={reviewUser}
        reviewData={createReviewData()}
        initialState={createReviewState("workbench")}
      />,
    );

    const accountAvatar = screen
      .getByRole("button", { name: "用户档案，积分 2680" })
      .querySelector("img");
    const topAvatar = screen
      .getByRole("button", { name: "用户档案" })
      .querySelector("img");

    expect(accountAvatar).not.toBeNull();
    expect(accountAvatar?.getAttribute("src")).toBe(
      topAvatar?.getAttribute("src"),
    );
  });

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

  it("按 IP 二创始终使用文案草稿当前人物而非历史人物页选择", async () => {
    const state = createReviewState("copy");
    state.selectedPersonId = "zhang";
    state.draft.ipId = "li";
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });

    render(<StudioWorkspace currentUser={reviewUser} initialState={state} />);
    await screen.findByRole("button", { name: "按 IP 二创" });
    fireEvent.click(screen.getByRole("button", { name: "按 IP 二创" }));

    await waitFor(() =>
      expect(livePanel.props).toHaveBeenLastCalledWith(
        expect.objectContaining({
          panel: "analysis",
          characterIdentityId: "li",
        }),
      ),
    );
  });

  it("场景形象进入口播分身后由真实 Studio 状态保留为照片来源", () => {
    const state = createReviewState("person-photos");
    state.draft.imageId = undefined;
    render(
      <StudioWorkspace
        currentUser={reviewUser}
        initialState={state}
        reviewData={createReviewData()}
      />,
    );

    const sceneCard = screen.getByText("庭院讲解", {
      selector: "strong",
    }).parentElement;
    if (!sceneCard) throw new Error("scene card not found");
    fireEvent.click(
      within(sceneCard).getByRole("button", { name: "制作口播分身" }),
    );

    expect(
      screen.getByRole("heading", { name: "制作口播分身" }),
    ).toBeInTheDocument();
    expect(screen.getByText("已选：庭院讲解")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "开始制作照片分身" }),
    ).toBeDisabled();
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
    expect(screen.getByText("粘贴一条爆款乡墅视频链接，")).toBeInTheDocument();
    expect(screen.getByText("快速生成它的原创视频")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "用户档案，积分 2680" }),
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
      analytics7: null,
      analytics30: null,
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
      analytics7: null,
      analytics30: null,
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

  describe("C7 云端草稿", () => {
    // 前面的轮询用例开启了 fake timers 且不恢复；本组用例的 waitFor 依赖
    // 真实 setTimeout，先显式切回，防止用例间定时器状态泄漏。
    beforeEach(() => {
      vi.useRealTimers();
    });

    const emptyStudioData = {
      people: [],
      assets: [],
      videos: [],
      projects: [],
      tasks: [],
      errors: [],
      loading: false,
      stats: null,
      analytics7: null,
      analytics30: null,
    };

    function restoredDraft() {
      const draft = createState("copy").draft;
      draft.script.title = "云端恢复的标题";
      draft.script.text = "云端恢复的文案内容";
      draft.script.confirmed = true;
      return draft;
    }

    async function openCopyPage() {
      fireEvent.click(screen.getByRole("button", { name: "文案工坊" }));
      await waitFor(() =>
        expect(screen.getByLabelText("二创文案")).toBeInTheDocument(),
      );
    }

    it("挂载时恢复云端草稿与我的文案列表", async () => {
      live.loadStudioData.mockResolvedValue(emptyStudioData);
      live.loadCloudDraft.mockResolvedValue({ draft: restoredDraft() });
      live.loadSavedScriptList.mockResolvedValue([
        {
          id: "saved-1",
          title: "已保存文案",
          original: "",
          text: "已保存的文本",
          version: 2,
          confirmed: false,
        },
      ]);
      render(<StudioWorkspace currentUser={reviewUser} />);

      await openCopyPage();
      // 恢复是异步 setState：等值到位，而不是等 textarea 出现。
      await waitFor(() =>
        expect(
          (screen.getByLabelText("二创文案") as HTMLTextAreaElement).value,
        ).toBe("云端恢复的文案内容"),
      );
      expect(screen.getByText("终稿 V1")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("tab", { name: "我的文案" }));
      expect(screen.getByText("已保存文案")).toBeInTheDocument();
      // 未做任何编辑时不触发自动保存。
      expect(live.persistCloudDraft).not.toHaveBeenCalled();
      expect(live.loadDraftMaterials).toHaveBeenCalledWith(
        expect.objectContaining({
          script: expect.objectContaining({ text: "云端恢复的文案内容" }),
        }),
      );
    });

    it("编辑二创文案后防抖自动保存到云端", async () => {
      live.loadStudioData.mockResolvedValue(emptyStudioData);
      live.loadCloudDraft.mockResolvedValue(undefined);
      render(<StudioWorkspace currentUser={reviewUser} />);

      // 用真实定时器完成渲染与导航（waitFor 依赖真实 setTimeout）。
      await openCopyPage();
      vi.useFakeTimers();
      try {
        fireEvent.change(screen.getByLabelText("二创文案"), {
          target: { value: "新的二创内容" },
        });
        expect(live.persistCloudDraft).not.toHaveBeenCalled();

        await act(async () => {
          await vi.advanceTimersByTimeAsync(2_000);
        });
        expect(live.persistCloudDraft).toHaveBeenCalledTimes(1);
        const savedDraft = live.persistCloudDraft.mock.calls[0][0] as {
          script: { text: string; confirmed: boolean };
        };
        expect(savedDraft.script.text).toBe("新的二创内容");
        expect(savedDraft.script.confirmed).toBe(false);
      } finally {
        vi.useRealTimers();
      }
    });

    it("保存版本写入云端我的文案", async () => {
      live.loadStudioData.mockResolvedValue(emptyStudioData);
      live.loadCloudDraft.mockResolvedValue(undefined);
      const state = createState("copy");
      state.draft.script.text = "要保存的文案";
      render(<StudioWorkspace currentUser={reviewUser} initialState={state} />);

      await openCopyPage();
      fireEvent.click(screen.getByRole("button", { name: "保存版本" }));
      await waitFor(() => expect(live.persistSavedScript).toHaveBeenCalled());
      const [script] = live.persistSavedScript.mock.calls[0] as unknown as [
        { text: string },
      ];
      expect(script.text).toBe("要保存的文案");
      expect(screen.getByText(/已保存到我的文案/)).toBeInTheDocument();
    });

    it("确认终稿立即持久化并带 projectId 时发布到项目脚本版本", async () => {
      live.loadStudioData.mockResolvedValue(emptyStudioData);
      live.loadCloudDraft.mockResolvedValue(undefined);
      const state = createState("copy");
      state.draft.projectId = "project-1";
      state.draft.script.text = "终稿内容";
      render(<StudioWorkspace currentUser={reviewUser} initialState={state} />);

      await openCopyPage();
      fireEvent.click(screen.getByRole("button", { name: "确认终稿" }));
      await waitFor(() =>
        expect(live.publishScriptVersion).toHaveBeenCalledWith(
          "project-1",
          "终稿内容",
        ),
      );
      expect(live.persistCloudDraft).toHaveBeenCalled();
      const savedDraft = live.persistCloudDraft.mock.calls[0][0] as unknown as {
        script: { confirmed: boolean };
      };
      expect(savedDraft.script.confirmed).toBe(true);
    });

    it("确认终稿无项目来源时不发布脚本版本", async () => {
      live.loadStudioData.mockResolvedValue(emptyStudioData);
      live.loadCloudDraft.mockResolvedValue(undefined);
      const state = createState("copy");
      state.draft.script.text = "无项目终稿";
      render(<StudioWorkspace currentUser={reviewUser} initialState={state} />);

      await openCopyPage();
      fireEvent.click(screen.getByRole("button", { name: "确认终稿" }));
      await waitFor(() => expect(live.persistCloudDraft).toHaveBeenCalled());
      expect(live.publishScriptVersion).not.toHaveBeenCalled();
    });

    it("提取文案成功后回填草稿并跳转文案工坊", async () => {
      live.loadStudioData.mockResolvedValue(emptyStudioData);
      live.loadCloudDraft.mockResolvedValue(undefined);
      live.extractScriptFromUpload.mockResolvedValue({
        text: "提取出的乡墅口播原文",
      });
      const state = createState("workbench");
      state.draft.projectId = "project-1";
      state.draft.sourceAssetId = "asset-1";
      render(<StudioWorkspace currentUser={reviewUser} initialState={state} />);

      fireEvent.click(screen.getByRole("button", { name: "提取文案" }));
      await waitFor(() =>
        expect(live.extractScriptFromUpload).toHaveBeenCalledWith(
          "project-1",
          "asset-1",
        ),
      );
      await waitFor(() =>
        expect(screen.getByLabelText("二创文案")).toBeInTheDocument(),
      );
      expect(screen.getByText(/文案已提取/)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("tab", { name: "文案改写" }));
      expect(
        (screen.getByLabelText("二创文案") as HTMLTextAreaElement).value,
      ).toBe("提取出的乡墅口播原文");
    });

    it("提取文案失败时保留工作区并提示服务端错误", async () => {
      live.loadStudioData.mockResolvedValue(emptyStudioData);
      live.loadCloudDraft.mockResolvedValue(undefined);
      live.extractScriptFromUpload.mockRejectedValue(
        new Error("语音转写服务返回错误（HTTP 500）"),
      );
      const state = createState("workbench");
      state.draft.projectId = "project-1";
      state.draft.sourceAssetId = "asset-1";
      render(<StudioWorkspace currentUser={reviewUser} initialState={state} />);

      fireEvent.click(screen.getByRole("button", { name: "提取文案" }));
      await waitFor(() =>
        expect(screen.getByText(/语音转写服务返回错误/)).toBeInTheDocument(),
      );
      expect(screen.queryByLabelText("二创文案")).not.toBeInTheDocument();
    });

    it("有项目来源但资产缺失时提取文案提示先上传", async () => {
      live.loadStudioData.mockResolvedValue(emptyStudioData);
      live.loadCloudDraft.mockResolvedValue(undefined);
      const state = createState("workbench");
      state.draft.sourceId = "proj-9";
      state.draft.projectId = "proj-9";
      render(<StudioWorkspace currentUser={reviewUser} initialState={state} />);

      fireEvent.click(screen.getByRole("button", { name: "提取文案" }));
      expect(screen.getByText(/请先上传视频来源/)).toBeInTheDocument();
      expect(live.extractScriptFromUpload).not.toHaveBeenCalled();
    });

    it("审核示例模式不触发任何云端草稿接口", async () => {
      render(
        <StudioWorkspace
          currentUser={reviewUser}
          reviewData={createReviewData()}
          initialState={createReviewState("copy")}
        />,
      );
      await openCopyPage();
      fireEvent.change(screen.getByLabelText("二创文案"), {
        target: { value: "审核模式编辑" },
      });
      await waitFor(() =>
        expect(
          screen.getByLabelText("二创文案") as HTMLTextAreaElement,
        ).toHaveValue("审核模式编辑"),
      );
      expect(live.loadCloudDraft).not.toHaveBeenCalled();
      expect(live.persistCloudDraft).not.toHaveBeenCalled();
      expect(live.loadSavedScriptList).not.toHaveBeenCalled();
    });
  });
});

describe("数字人口播提交", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState(null, "", "/#studio/workbench");
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    live.loadPersonAssets.mockResolvedValue({ assets: [], errors: [] });
    live.loadCloudDraft.mockResolvedValue(undefined);
    live.loadDraftMaterials.mockResolvedValue({
      assets: [],
      unavailableIds: [],
    });
    live.loadSavedScriptList.mockResolvedValue([]);
    api.createOralTask.mockReset();
    api.createMaterialUploadIntent.mockReset();
    api.uploadMaterial.mockReset();
    api.completeMaterialUpload.mockReset();
  });

  it("字幕参数进入请求，并发点击单飞且网络重试复用幂等键", async () => {
    const state = createReviewState("oral");
    state.draft.style = "standard";
    state.draft.subtitles = true;
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    let rejectFirst!: (reason: Error) => void;
    api.createOralTask.mockReturnValueOnce(
      new Promise((_resolve, reject) => {
        rejectFirst = reject;
      }),
    );

    render(<StudioWorkspace currentUser={reviewUser} initialState={state} />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "生成口播视频" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "生成口播视频" }));
    const submit = await screen.findByRole("button", {
      name: "确认费用并提交",
    });
    fireEvent.click(submit);
    fireEvent.click(submit);

    await waitFor(() => expect(api.createOralTask).toHaveBeenCalledTimes(1));
    const firstRequest = api.createOralTask.mock.calls[0][0];
    expect(firstRequest.subtitle).toEqual({ st_show: true });

    await act(async () => rejectFirst(new Error("network timeout")));
    api.createOralTask.mockResolvedValueOnce({
      id: "oral-task-1",
      status: "FAILED",
      estimated_cost_fen: 100,
      replayed: true,
    });
    fireEvent.click(submit);

    await waitFor(() => expect(api.createOralTask).toHaveBeenCalledTimes(2));
    expect(api.createOralTask.mock.calls[1][0].idempotencyKey).toBe(
      firstRequest.idempotencyKey,
    );

    api.createOralTask.mockResolvedValueOnce({
      id: "oral-task-2",
      status: "QUEUED",
      estimated_cost_fen: 100,
      replayed: false,
    });
    fireEvent.click(screen.getByRole("button", { name: "生成口播视频" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "确认费用并提交" }),
    );

    await waitFor(() => expect(api.createOralTask).toHaveBeenCalledTimes(3));
    expect(api.createOralTask.mock.calls[2][0].idempotencyKey).not.toBe(
      firstRequest.idempotencyKey,
    );
  });

  it("关闭字幕时明确提交 st_show=false", async () => {
    const state = createReviewState("oral");
    state.draft.subtitles = false;
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    api.createOralTask.mockResolvedValue({
      id: "oral-without-subtitles",
      status: "QUEUED",
      estimated_cost_fen: 100,
      replayed: false,
    });

    render(<StudioWorkspace currentUser={reviewUser} initialState={state} />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "生成口播视频" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "生成口播视频" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "确认费用并提交" }),
    );

    await waitFor(() => expect(api.createOralTask).toHaveBeenCalledOnce());
    expect(api.createOralTask.mock.calls[0][0].subtitle).toEqual({
      st_show: false,
    });
  });

  it("完整音频上传后回填真实 Studio 状态并允许提交 AUDIO", async () => {
    const state = createReviewState("oral-audio");
    state.draft.audioId = undefined;
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    api.createMaterialUploadIntent.mockResolvedValue({
      asset_id: "uploaded-speech",
      material_id: "asset:uploaded-speech",
    });
    api.uploadMaterial.mockResolvedValue(undefined);
    api.completeMaterialUpload.mockResolvedValue({
      id: "asset:uploaded-speech",
      owner_user_id: reviewUser.id,
      asset_id: "uploaded-speech",
      generation_task_id: null,
      project_id: null,
      person_id: null,
      title: "new-speech.mp3",
      group: "完整口播音频",
      media_type: "audio",
      source: "upload",
      status: "ready",
      delivery: "stored",
      content_type: "audio/mpeg",
      size_bytes: 5,
      duration_seconds: 42,
      created_at: "2026-09-07T10:00:00Z",
      hidden: false,
      saved: true,
      allowed_uses: ["oral_audio", "reference"],
      allowed_actions: ["preview", "download", "rename", "hide"],
    });

    render(<StudioWorkspace currentUser={reviewUser} initialState={state} />);
    await screen.findByText("张工 · 乡墅设计师");
    expect(screen.getByText("未选择完整口播音频")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("选择完整口播音频"), {
      target: {
        files: [new File(["audio"], "new-speech.mp3", { type: "audio/mpeg" })],
      },
    });

    await waitFor(() =>
      expect(api.createMaterialUploadIntent).toHaveBeenCalledOnce(),
    );
    expect(api.uploadMaterial).toHaveBeenCalledOnce();
    expect((api.uploadMaterial.mock.calls[0][3] as AbortSignal).aborted).toBe(
      false,
    );
    expect(api.completeMaterialUpload).toHaveBeenCalledWith(
      "uploaded-speech",
      expect.any(AbortSignal),
    );
    await expect(
      api.completeMaterialUpload.mock.results[0].value,
    ).resolves.toMatchObject({ title: "new-speech.mp3", media_type: "audio" });
    await screen.findByText("音频已上传并选中。");
    expect(await screen.findByText("new-speech.mp3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成口播视频" })).toBeEnabled();
    api.createOralTask.mockResolvedValue({
      id: "oral-from-audio",
      status: "QUEUED",
      estimated_cost_fen: 100,
      replayed: false,
    });
    fireEvent.click(screen.getByRole("button", { name: "生成口播视频" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "确认费用并提交" }),
    );

    await waitFor(() => expect(api.createOralTask).toHaveBeenCalledOnce());
    const request = api.createOralTask.mock.calls[0][0];
    expect(request.mode).toBe("AUDIO");
    expect(request.audioAssetId).toBe("uploaded-speech");
    expect(request.scriptText).toBeUndefined();
    expect(request.voiceId).toBeUndefined();
    expect(request.subtitle).toBeUndefined();
  });
});

describe("视频生成（C2 独立创作）", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  const emptyStudioData = {
    people: [],
    assets: [],
    materials: [],
    videos: [],
    projects: [],
    tasks: [],
    errors: [],
    loading: false,
    stats: null,
    analytics7: null,
    analytics30: null,
  };

  async function openVideoPage() {
    // 侧边栏「视频创作」进入复刻页签组，再切到「视频生成」。
    fireEvent.click(screen.getByRole("button", { name: "视频创作" }));
    fireEvent.click(screen.getByRole("tab", { name: "视频生成" }));
    await waitFor(() =>
      expect(screen.getByLabelText("提示词")).toBeInTheDocument(),
    );
  }

  it("T2V 扩展模式被门禁时不打开确认弹窗并提示等待供应商核对", async () => {
    api.getIndependentCapabilities.mockResolvedValue({
      extended_modes_enabled: false,
      t2v_enabled: false,
      i2v_enabled: true,
      r2v_enabled: false,
      last_frame_enabled: false,
      max_reference_images: 4,
      max_quantity: 4,
    });
    live.loadStudioData.mockResolvedValue(emptyStudioData);
    render(<StudioWorkspace currentUser={reviewUser} />);
    await openVideoPage();

    fireEvent.change(screen.getByLabelText("提示词"), {
      target: { value: "山间别墅延时" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成视频" }));

    expect(
      await screen.findByText("该模式需要完成供应商核对后开放，敬请期待。"),
    ).toBeInTheDocument();
    expect(screen.queryByText("生成确认 · 视频生成")).toBeNull();
    expect(api.createIndependentVideoTask).not.toHaveBeenCalled();
  });

  it("确认弹窗展示按秒报价并可提交任务、预览区进入进度视图", async () => {
    api.getIndependentCapabilities.mockResolvedValue({
      extended_modes_enabled: true,
      t2v_enabled: true,
      i2v_enabled: true,
      r2v_enabled: true,
      last_frame_enabled: true,
      max_reference_images: 4,
      max_quantity: 4,
    });
    const submittedBatch = {
      id: "batch-video-1",
      project_id: null,
      creation_kind: "independent",
      stale: false,
      progress: { total_count: 1, terminal_count: 0, progress_percent: 0 },
      tasks: [],
    };
    api.createIndependentVideoTask.mockResolvedValue(submittedBatch);
    const runningTask = {
      id: "batch-video-1",
      type: "视频生成",
      title: "视频生成",
      status: "running",
      progress: 40,
      submitted: "2026-09-06 12:00:00",
    };
    live.loadStudioData
      .mockResolvedValueOnce(emptyStudioData)
      .mockResolvedValue({
        ...emptyStudioData,
        tasks: [runningTask],
      });
    render(<StudioWorkspace currentUser={reviewUser} />);
    await openVideoPage();

    fireEvent.change(screen.getByLabelText("提示词"), {
      target: { value: "航拍乡墅庭院" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成视频" }));

    // 报价按秒折算：120 分/秒 × 8 秒 = 9.60 元。
    expect(await screen.findByText(/9\.60 元/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认费用并提交" }));
    await waitFor(() =>
      expect(api.createIndependentVideoTask).toHaveBeenCalledTimes(1),
    );
    const input = api.createIndependentVideoTask.mock.calls[0][0] as {
      mode: string;
      prompt_text: string;
      idempotency_key: string;
    };
    expect(input.mode).toBe("t2v");
    expect(input.prompt_text).toBe("航拍乡墅庭院");
    expect(input.idempotency_key).toBeTruthy();

    // 提交后留在本页：预览区出现阶段进度（数据来自任务轮询）。
    expect(await screen.findByText("生成中")).toBeInTheDocument();
    expect(
      screen.getByRole("progressbar", { name: "生成进度" }),
    ).toBeInTheDocument();
  });

  it("提示词导入：从我的提示词一键回填", async () => {
    api.listUserSavedPrompts.mockResolvedValue([
      {
        id: "sp-1",
        project_id: "project-a",
        name: "庭院黄昏",
        prompt_text: "黄昏光线下的庭院推进镜头",
        created_at: "2026-09-06 12:00:00",
      },
    ]);
    live.loadStudioData.mockResolvedValue(emptyStudioData);
    render(<StudioWorkspace currentUser={reviewUser} />);
    await openVideoPage();

    fireEvent.click(screen.getByRole("button", { name: "导入提示词" }));
    fireEvent.click(await screen.findByText("庭院黄昏"));

    expect((screen.getByLabelText("提示词") as HTMLTextAreaElement).value).toBe(
      "黄昏光线下的庭院推进镜头",
    );
  });
});
