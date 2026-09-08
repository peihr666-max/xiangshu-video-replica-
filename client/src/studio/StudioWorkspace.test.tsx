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
    window.localStorage.clear();
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
    });
    render(<StudioWorkspace currentUser={reviewUser} />);
    await waitFor(() => expect(live.loadStudioData).toHaveBeenCalled());
    expect(screen.getByText(/人物库暂不可用/)).toBeInTheDocument();
    expect(screen.queryByText("张工")).not.toBeInTheDocument();
    expect(screen.queryByText(/示例审核/)).not.toBeInTheDocument();
  });

  it("父组件传入同账号的新对象时不重复加载基础数据", async () => {
    live.loadStudioData.mockResolvedValue({
      people: [],
      assets: [],
      videos: [],
      tasks: [],
      projects: [],
      errors: [] as string[],
      loading: false,
      stats: null,
    });
    const firstUser = { ...reviewUser };
    const view = render(<StudioWorkspace currentUser={firstUser} />);
    await waitFor(() => expect(live.loadStudioData).toHaveBeenCalledOnce());

    view.rerender(<StudioWorkspace currentUser={{ ...firstUser }} />);
    await Promise.resolve();

    expect(live.loadStudioData).toHaveBeenCalledOnce();
  });

  it("账号切换立即清空旧数据并忽略旧账号迟到响应", async () => {
    const oldData = {
      ...createReviewData(),
      videos: [
        {
          ...createReviewData().videos[0],
          id: "old-video",
          title: "旧账号私有爆款",
        },
      ],
      loading: false,
    };
    const emptyResult = {
      people: [],
      assets: [],
      videos: [],
      tasks: [],
      projects: [],
      errors: [] as string[],
      loading: false,
      stats: null,
    };
    const resolvers = new Map<string, (value: typeof emptyResult) => void>();
    live.loadStudioData.mockImplementation(
      (user: { id: string }) =>
        new Promise((resolve) => {
          resolvers.set(user.id, resolve);
        }),
    );
    const user1 = { ...reviewUser, id: "account-1" };
    const user2 = { ...reviewUser, id: "account-2" };
    const user3 = { ...reviewUser, id: "account-3" };
    const view = render(<StudioWorkspace currentUser={user1} />);
    resolvers.get("account-1")?.(oldData as typeof emptyResult);
    expect(await screen.findByText("旧账号私有爆款")).toBeInTheDocument();

    view.rerender(<StudioWorkspace currentUser={user2} />);
    expect(screen.queryByText("旧账号私有爆款")).not.toBeInTheDocument();
    view.rerender(<StudioWorkspace currentUser={user3} />);
    resolvers.get("account-2")?.({
      ...emptyResult,
      errors: ["旧账号迟到数据"],
    });
    resolvers.get("account-3")?.({
      ...emptyResult,
      errors: ["新账号数据"],
    });

    expect(await screen.findByText(/新账号数据/)).toBeInTheDocument();
    expect(screen.queryByText(/旧账号迟到数据/)).toBeNull();
  });

  it("同账号角色降级的首个提交即隐藏原权限数据", async () => {
    const privilegedData = {
      ...createReviewData(),
      videos: [
        {
          ...createReviewData().videos[0],
          id: "privileged-video",
          title: "原角色可见内容",
        },
      ],
      loading: false,
    };
    live.loadStudioData
      .mockResolvedValueOnce(privilegedData)
      .mockReturnValueOnce(new Promise(() => {}));
    const customer = {
      ...reviewUser,
      id: "same-account",
      role: "customer" as const,
    };
    const view = render(<StudioWorkspace currentUser={customer} />);
    expect(await screen.findByText("原角色可见内容")).toBeInTheDocument();

    view.rerender(
      <StudioWorkspace
        currentUser={{ ...customer, role: "auditor" as const }}
      />,
    );

    expect(screen.queryByText("原角色可见内容")).toBeNull();
    expect(live.loadStudioData).toHaveBeenCalledTimes(2);
  });

  it("账号切换后口播请求只携带新账号当前项目", async () => {
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, _init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/oral/price")) {
          return { ok: true, json: async () => ({ unit_price_fen: 100 }) };
        }
        if (url.endsWith("/api/oral/tasks")) {
          return {
            ok: true,
            json: async () => ({
              id: "oral-1",
              status: "QUEUED",
              estimated_cost_fen: 100,
              replayed: false,
            }),
          };
        }
        throw new Error(`unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const oldState = createReviewState("oral");
    oldState.draft.projectId = "project-old";
    const newState = createReviewState("oral");
    newState.draft.projectId = "project-new";
    const view = render(
      <StudioWorkspace
        currentUser={{ ...reviewUser, id: "account-old" }}
        initialState={oldState}
      />,
    );
    expect(
      await screen.findByRole("button", { name: "生成口播视频" }),
    ).toBeEnabled();

    view.rerender(
      <StudioWorkspace
        currentUser={{ ...reviewUser, id: "account-new" }}
        initialState={newState}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "生成口播视频" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "确认费用并提交" }),
    );

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input, init]) => {
          if (!String(input).endsWith("/api/oral/tasks")) return false;
          return JSON.parse(String(init?.body)).project_id === "project-new";
        }),
      ).toBe(true),
    );
    expect(
      fetchMock.mock.calls.some(([input, init]) => {
        if (!String(input).endsWith("/api/oral/tasks")) return false;
        return JSON.parse(String(init?.body)).project_id === "project-old";
      }),
    ).toBe(false);
    const newAccountCall = fetchMock.mock.calls.find(([input, init]) => {
      if (!String(input).endsWith("/api/oral/tasks")) return false;
      return JSON.parse(String(init?.body)).project_id === "project-new";
    });
    expect(JSON.parse(String(newAccountCall?.[1]?.body)).subtitle).toEqual({
      st_show: false,
    });
    vi.unstubAllGlobals();
  });

  it("口播报价失败时阻止提交，并可重试报价后恢复提交", async () => {
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    let priceCalls = 0;
    let oralCalls = 0;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, _init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/oral/price")) {
          priceCalls += 1;
          if (priceCalls === 1) throw new TypeError("price offline");
          return { ok: true, json: async () => ({ unit_price_fen: 100 }) };
        }
        if (url.endsWith("/api/oral/tasks")) {
          oralCalls += 1;
          return {
            ok: true,
            json: async () => ({
              id: "oral-after-price",
              status: "QUEUED",
              estimated_cost_fen: 100,
              replayed: false,
            }),
          };
        }
        throw new Error(`unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <StudioWorkspace
        currentUser={reviewUser}
        initialState={createReviewState("oral")}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "生成口播视频" }),
    );
    const confirm = await screen.findByRole("button", {
      name: "确认费用并提交",
    });
    expect(confirm).toBeDisabled();
    expect(oralCalls).toBe(0);

    fireEvent.click(
      await screen.findByRole("button", { name: "重新获取报价" }),
    );
    await screen.findByText("1.00 元/条");
    expect(confirm).toBeEnabled();

    fireEvent.click(confirm);
    await waitFor(() => expect(oralCalls).toBe(1));
    vi.unstubAllGlobals();
  });

  it.each([408, 425, 429, 503])(
    "人物分身请求遇到 %s 后跨页面重挂载仍复用完整请求",
    async (status) => {
      live.loadStudioData.mockResolvedValue({
        ...createReviewData(),
        loading: false,
      });
      let avatarCalls = 0;
      const fetchMock = vi.fn(
        async (input: RequestInfo | URL, _init?: RequestInit) => {
          const url = String(input);
          if (url.endsWith("/api/oral/clone-consents")) {
            return new Response(
              JSON.stringify({
                consent_id: "consent-avatar-1",
                identity_id: "zhang",
                source_asset_id: "zhang-courtyard",
                source_sha256: "fixture-sha256",
                purpose: "oral_avatar_clone",
              }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            );
          }
          if (url.endsWith("/api/oral/avatars")) {
            avatarCalls += 1;
            if (avatarCalls === 1) {
              return new Response(
                JSON.stringify({
                  detail: {
                    code: "UPSTREAM_UNAVAILABLE",
                    message: "gateway unavailable",
                    retryable: false,
                  },
                }),
                {
                  status,
                  headers: { "Content-Type": "application/json" },
                },
              );
            }
            return new Response(
              JSON.stringify({
                id: `avatar-${avatarCalls}`,
                status: "PENDING",
              }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            );
          }
          throw new Error(`unexpected request: ${url}`);
        },
      );
      vi.stubGlobal("fetch", fetchMock);
      const view = render(
        <StudioWorkspace
          currentUser={reviewUser}
          initialState={createReviewState("person-avatars")}
        />,
      );

      const firstSubmit = await screen.findByRole("button", {
        name: "开始制作",
      });
      fireEvent.change(screen.getByLabelText("分身名称"), {
        target: { value: "首次冻结的庭院分身" },
      });
      fireEvent.click(firstSubmit);
      await waitFor(() => expect(firstSubmit).toBeEnabled());
      view.unmount();
      render(
        <StudioWorkspace
          currentUser={reviewUser}
          initialState={createReviewState("person-avatars")}
        />,
      );
      fireEvent.click(await screen.findByRole("button", { name: "开始制作" }));
      await waitFor(() => expect(avatarCalls).toBe(2));

      const avatarBodies = fetchMock.mock.calls
        .filter(([input]) => String(input).endsWith("/api/oral/avatars"))
        .map(([, init]) => JSON.parse(String(init?.body)));
      expect(avatarBodies[1]).toEqual(avatarBodies[0]);
      expect(avatarBodies[0].title).toBe("首次冻结的庭院分身");
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          String(input).endsWith("/api/oral/clone-consents"),
        ),
      ).toHaveLength(1);
      vi.unstubAllGlobals();
    },
  );

  it("账号切换后隔离人物分身待重试请求并生成新幂等键", async () => {
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    let avatarCalls = 0;
    let consentCalls = 0;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, _init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/oral/clone-consents")) {
          consentCalls += 1;
          return new Response(
            JSON.stringify({
              consent_id: `consent-${consentCalls}`,
              identity_id: "zhang",
              source_asset_id: "zhang-courtyard",
              source_sha256: "fixture-sha256",
              purpose: "oral_avatar_clone",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.endsWith("/api/oral/avatars")) {
          avatarCalls += 1;
          if (avatarCalls === 1) {
            return new Response(
              JSON.stringify({
                detail: {
                  code: "UPSTREAM_UNAVAILABLE",
                  message: "gateway unavailable",
                  retryable: false,
                },
              }),
              {
                status: 503,
                headers: { "Content-Type": "application/json" },
              },
            );
          }
          return new Response(
            JSON.stringify({ id: "avatar-new", status: "PENDING" }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        throw new Error(`unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const state = createReviewState("person-avatars");
    const view = render(
      <StudioWorkspace
        currentUser={{ ...reviewUser, id: "account-old" }}
        initialState={state}
      />,
    );

    const firstSubmit = await screen.findByRole("button", {
      name: "开始制作",
    });
    fireEvent.click(firstSubmit);
    await waitFor(() => expect(firstSubmit).toBeEnabled());
    view.rerender(
      <StudioWorkspace
        currentUser={{ ...reviewUser, id: "account-new" }}
        initialState={state}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "开始制作" }));
    await waitFor(() => expect(avatarCalls).toBe(2));

    const avatarBodies = fetchMock.mock.calls
      .filter(([input]) => String(input).endsWith("/api/oral/avatars"))
      .map(([, init]) => JSON.parse(String(init?.body)));
    expect(avatarBodies[1]).toMatchObject({
      identity_id: avatarBodies[0].identity_id,
      source_asset_id: avatarBodies[0].source_asset_id,
      title: avatarBodies[0].title,
    });
    expect(avatarBodies[1].idempotency_key).not.toBe(
      avatarBodies[0].idempotency_key,
    );
    expect(consentCalls).toBe(2);
    vi.unstubAllGlobals();
  });

  it("声音克隆明确未受理后清除待重试请求", async () => {
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    let voiceCalls = 0;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, _init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/oral/clone-consents")) {
          return new Response(
            JSON.stringify({
              consent_id: `consent-${voiceCalls + 1}`,
              identity_id: "zhang",
              source_asset_id: "speech",
              source_sha256: "fixture-sha256",
              purpose: "oral_voice_clone",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.endsWith("/api/oral/voices")) {
          voiceCalls += 1;
          if (voiceCalls === 1) {
            return new Response(
              JSON.stringify({
                detail: {
                  code: "ORAL_INPUT_INVALID",
                  message: "invalid voice input",
                  retryable: false,
                },
              }),
              {
                status: 422,
                headers: { "Content-Type": "application/json" },
              },
            );
          }
          return new Response(
            JSON.stringify({ id: "voice-new", status: "PENDING" }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        throw new Error(`unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <StudioWorkspace
        currentUser={reviewUser}
        initialState={createReviewState("person-voices")}
      />,
    );

    const submit = await screen.findByRole("button", { name: "开始克隆" });
    fireEvent.click(submit);
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    await waitFor(() => expect(voiceCalls).toBe(2));

    const voiceBodies = fetchMock.mock.calls
      .filter(([input]) => String(input).endsWith("/api/oral/voices"))
      .map(([, init]) => JSON.parse(String(init?.body)));
    expect(voiceBodies[1].idempotency_key).not.toBe(
      voiceBodies[0].idempotency_key,
    );
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        String(input).endsWith("/api/oral/clone-consents"),
      ),
    ).toHaveLength(2);
    vi.unstubAllGlobals();
  });

  it("同一次口播提交阻止并发双击并在所有不确定响应后完整复用请求", async () => {
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    let rejectFirst: ((reason?: unknown) => void) | undefined;
    const firstSubmission = new Promise<Response>((_resolve, reject) => {
      rejectFirst = reject;
    });
    const uncertainStatuses = [408, 425, 429, 502, 503, 504];
    let oralCalls = 0;
    const fetchMock = vi.fn(
      (input: RequestInfo | URL, _init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url.endsWith("/api/oral/price")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ unit_price_fen: 100 }),
          } as Response);
        }
        if (url.endsWith("/api/oral/tasks")) {
          oralCalls += 1;
          if (oralCalls === 1) return firstSubmission;
          const uncertainStatus = uncertainStatuses[oralCalls - 2];
          if (uncertainStatus !== undefined) {
            return Promise.resolve({
              ok: false,
              status: uncertainStatus,
              headers: new Headers(),
              json: async () => ({
                detail: {
                  code: "UPSTREAM_UNAVAILABLE",
                  message: "gateway unavailable",
                  retryable: false,
                },
              }),
            } as Response);
          }
          return Promise.resolve({
            ok: true,
            json: async () => ({
              id: `oral-${oralCalls}`,
              status: "QUEUED",
              estimated_cost_fen: 100,
              replayed: false,
            }),
          } as Response);
        }
        throw new Error(`unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const state = createReviewState("oral");
    state.draft.projectId = "project-oral";
    state.draft.subtitles = true;
    render(<StudioWorkspace currentUser={reviewUser} initialState={state} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "生成口播视频" }),
    );
    const confirm = await screen.findByRole("button", {
      name: "确认费用并提交",
    });
    await waitFor(() => expect(confirm).toBeEnabled());
    fireEvent.click(confirm);
    fireEvent.click(confirm);

    await waitFor(() => expect(oralCalls).toBe(1));
    expect(confirm).toBeDisabled();
    rejectFirst?.(new TypeError("network unavailable"));
    await waitFor(() => expect(confirm).toBeEnabled());

    for (const expectedCalls of [2, 3, 4, 5, 6, 7]) {
      fireEvent.click(confirm);
      await waitFor(() => expect(oralCalls).toBe(expectedCalls));
      await waitFor(() => expect(confirm).toBeEnabled());
    }
    fireEvent.click(confirm);
    await waitFor(() => expect(oralCalls).toBe(8));

    fireEvent.click(screen.getByRole("button", { name: "新建创作" }));
    fireEvent.click(await screen.findByRole("button", { name: "数字人口播" }));
    const generateAgain = await screen.findByRole("button", {
      name: "生成口播视频",
    });
    fireEvent.click(generateAgain);
    fireEvent.click(
      await screen.findByRole("button", { name: "确认费用并提交" }),
    );
    await waitFor(() => expect(oralCalls).toBe(9));

    const bodies = fetchMock.mock.calls
      .filter(([input]) => String(input).endsWith("/api/oral/tasks"))
      .map(([, init]) => JSON.parse(String(init?.body)));
    expect(bodies.slice(0, 8)).toEqual(Array(8).fill(bodies[0]));
    expect(bodies[8].idempotency_key).not.toBe(bodies[0].idempotency_key);
    expect(bodies[0]).toMatchObject({
      project_id: "project-oral",
      identity_id: state.draft.ipId,
      avatar_id: state.draft.avatarId,
      voice_id: state.draft.voiceId,
      mode: "TTS",
      script_text: state.draft.script.text,
      subtitle: { st_show: true },
    });
    vi.unstubAllGlobals();
  });

  it("无项目且云草稿延迟时，口播响应丢失后 fresh state 仍复用完整请求", async () => {
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    live.loadCloudDraft.mockImplementation(() => new Promise(() => {}));
    let oralCalls = 0;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, _init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/oral/price")) {
          return { ok: true, json: async () => ({ unit_price_fen: 100 }) };
        }
        if (url.endsWith("/api/oral/tasks")) {
          oralCalls += 1;
          if (oralCalls === 1) throw new TypeError("network unavailable");
          return {
            ok: true,
            json: async () => ({
              id: "oral-restored",
              status: "QUEUED",
              estimated_cost_fen: 100,
              replayed: true,
            }),
          };
        }
        throw new Error(`unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const state = createReviewState("oral");
    state.draft.projectId = undefined;
    const firstView = render(
      <StudioWorkspace currentUser={reviewUser} initialState={state} />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "生成口播视频" }),
    );
    const firstConfirm = await screen.findByRole("button", {
      name: "确认费用并提交",
    });
    fireEvent.click(firstConfirm);
    await waitFor(() => expect(firstConfirm).toBeEnabled());
    firstView.unmount();
    const reloadedState = createState("oral");
    reloadedState.draft = {
      ...reloadedState.draft,
      projectId: undefined,
      ipId: state.draft.ipId,
      avatarId: state.draft.avatarId,
      voiceId: state.draft.voiceId,
      script: {
        ...state.draft.script,
        title: "刷新后修改的标题",
        text: "刷新后修改的脚本不应覆盖待恢复请求",
      },
      subtitles: !state.draft.subtitles,
    };
    expect(reloadedState.draft.id).not.toBe(state.draft.id);
    render(
      <StudioWorkspace currentUser={reviewUser} initialState={reloadedState} />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "生成口播视频" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "确认费用并提交" }),
    );
    await waitFor(() => expect(oralCalls).toBe(2));

    const bodies = fetchMock.mock.calls
      .filter(([input]) => String(input).endsWith("/api/oral/tasks"))
      .map(([, init]) => JSON.parse(String(init?.body)));
    expect(bodies[1]).toEqual(bodies[0]);
    expect(bodies[1]).toMatchObject({
      title: state.draft.script.title,
      script_text: state.draft.script.text,
      subtitle: { st_show: state.draft.subtitles },
    });
    vi.unstubAllGlobals();
  });

  it("首次恢复记录持久化失败时口播与克隆均不发送业务 POST", async () => {
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new DOMException("full", "QuotaExceededError");
      });
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, _init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/oral/price")) {
          return { ok: true, json: async () => ({ unit_price_fen: 100 }) };
        }
        throw new Error(`unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const oralView = render(
      <StudioWorkspace
        currentUser={{ ...reviewUser, id: "quota-oral" }}
        initialState={createReviewState("oral")}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "生成口播视频" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "确认费用并提交" }),
    );
    await screen.findByText(/无法保存待提交任务恢复状态/);
    oralView.unmount();
    render(
      <StudioWorkspace
        currentUser={{ ...reviewUser, id: "quota-clone" }}
        initialState={createReviewState("person-avatars")}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "开始制作" }));
    await screen.findByText(/无法保存待提交任务恢复状态/);

    expect(
      fetchMock.mock.calls.filter(([input]) =>
        [
          "/api/oral/tasks",
          "/api/oral/clone-consents",
          "/api/oral/avatars",
        ].some((path) => String(input).endsWith(path)),
      ),
    ).toHaveLength(0);
    setItem.mockRestore();
    vi.unstubAllGlobals();
  });

  it("克隆授权记录更新失败时不创建克隆并用原幂等键重新授权", async () => {
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    const nativeSetItem = Storage.prototype.setItem;
    let storageWrites = 0;
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(function (this: Storage, key: string, value: string) {
        storageWrites += 1;
        if (storageWrites === 2) {
          throw new DOMException("full", "QuotaExceededError");
        }
        nativeSetItem.call(this, key, value);
      });
    let consentCalls = 0;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, _init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/oral/clone-consents")) {
          consentCalls += 1;
          return new Response(
            JSON.stringify({
              consent_id: `consent-${consentCalls}`,
              identity_id: "zhang",
              source_asset_id: "zhang-courtyard",
              source_sha256: "fixture-sha256",
              purpose: "oral_avatar_clone",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.endsWith("/api/oral/avatars")) {
          return new Response(
            JSON.stringify({ id: "avatar-retried", status: "PENDING" }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        throw new Error(`unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <StudioWorkspace
        currentUser={{ ...reviewUser, id: "consent-write-fail" }}
        initialState={createReviewState("person-avatars")}
      />,
    );

    const submit = await screen.findByRole("button", { name: "开始制作" });
    fireEvent.click(submit);
    await screen.findByText(/无法保存待提交任务恢复状态/);
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        String(input).endsWith("/api/oral/avatars"),
      ),
    ).toHaveLength(0);
    const storageKey = Object.keys(window.localStorage).find((key) =>
      key.includes("consent-write-fail"),
    );
    expect(storageKey).toBeDefined();
    const persisted = JSON.parse(
      window.localStorage.getItem(storageKey || "") || "{}",
    );
    expect(persisted.request.consentId).toBeUndefined();
    setItem.mockRestore();
    fireEvent.click(submit);
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          String(input).endsWith("/api/oral/avatars"),
        ),
      ).toHaveLength(1),
    );
    const cloneBody = JSON.parse(
      String(
        fetchMock.mock.calls.find(([input]) =>
          String(input).endsWith("/api/oral/avatars"),
        )?.[1]?.body,
      ),
    );
    expect(cloneBody.idempotency_key).toBe(persisted.request.idempotencyKey);
    expect(consentCalls).toBe(2);
    vi.unstubAllGlobals();
  });

  it("fresh 页面恢复存储不可读时口播与克隆均保持零 POST", async () => {
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    const getItem = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new DOMException("blocked", "SecurityError");
      });
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, _init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/oral/price")) {
          return { ok: true, json: async () => ({ unit_price_fen: 100 }) };
        }
        throw new Error(`unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const oralView = render(
      <StudioWorkspace
        currentUser={{ ...reviewUser, id: "fresh-storage-oral" }}
        initialState={createReviewState("oral")}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "生成口播视频" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "确认费用并提交" }),
    );
    await screen.findByText(/无法读取待提交任务恢复状态/);
    oralView.unmount();
    render(
      <StudioWorkspace
        currentUser={{ ...reviewUser, id: "fresh-storage-clone" }}
        initialState={createReviewState("person-avatars")}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "开始制作" }));
    await screen.findByText(/无法读取待提交任务恢复状态/);

    expect(
      fetchMock.mock.calls.filter(([input]) =>
        ["/api/oral/tasks", "/api/oral/clone-consents"].some((path) =>
          String(input).endsWith(path),
        ),
      ),
    ).toHaveLength(0);
    getItem.mockRestore();
    vi.unstubAllGlobals();
  });

  it("确定未受理的客户端错误允许下一次提交使用新幂等键", async () => {
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    let oralCalls = 0;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, _init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/oral/price")) {
          return { ok: true, json: async () => ({ unit_price_fen: 100 }) };
        }
        if (url.endsWith("/api/oral/tasks")) {
          oralCalls += 1;
          if (oralCalls === 1) {
            return {
              ok: false,
              status: 422,
              headers: new Headers(),
              json: async () => ({
                detail: {
                  code: "ORAL_INPUT_INVALID",
                  message: "invalid input",
                  retryable: false,
                },
              }),
            };
          }
          return {
            ok: true,
            json: async () => ({
              id: "oral-valid",
              status: "QUEUED",
              estimated_cost_fen: 100,
              replayed: false,
            }),
          };
        }
        throw new Error(`unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const state = createReviewState("oral");
    const firstView = render(
      <StudioWorkspace currentUser={reviewUser} initialState={state} />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "生成口播视频" }),
    );
    const confirm = await screen.findByRole("button", {
      name: "确认费用并提交",
    });
    fireEvent.click(confirm);
    await waitFor(() => expect(oralCalls).toBe(1));
    firstView.unmount();
    render(<StudioWorkspace currentUser={reviewUser} initialState={state} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "生成口播视频" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "确认费用并提交" }),
    );
    await waitFor(() => expect(oralCalls).toBe(2));

    const bodies = fetchMock.mock.calls
      .filter(([input]) => String(input).endsWith("/api/oral/tasks"))
      .map(([, init]) => JSON.parse(String(init?.body)));
    expect(bodies[1].idempotency_key).not.toBe(bodies[0].idempotency_key);
    vi.unstubAllGlobals();
  });

  it("服务端明确返回 FAILED 后清理恢复记录并允许新尝试", async () => {
    live.loadStudioData.mockResolvedValue({
      ...createReviewData(),
      loading: false,
    });
    let oralCalls = 0;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, _init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/oral/price")) {
          return { ok: true, json: async () => ({ unit_price_fen: 100 }) };
        }
        if (url.endsWith("/api/oral/tasks")) {
          oralCalls += 1;
          return {
            ok: true,
            json: async () => ({
              id: `oral-terminal-${oralCalls}`,
              status: oralCalls === 1 ? "FAILED" : "QUEUED",
              estimated_cost_fen: 100,
              replayed: false,
            }),
          };
        }
        throw new Error(`unexpected request: ${url}`);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const state = createReviewState("oral");
    const firstView = render(
      <StudioWorkspace currentUser={reviewUser} initialState={state} />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "生成口播视频" }),
    );
    const confirm = await screen.findByRole("button", {
      name: "确认费用并提交",
    });
    fireEvent.click(confirm);
    await waitFor(() => expect(oralCalls).toBe(1));
    firstView.unmount();
    render(<StudioWorkspace currentUser={reviewUser} initialState={state} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "生成口播视频" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "确认费用并提交" }),
    );
    await waitFor(() => expect(oralCalls).toBe(2));

    const bodies = fetchMock.mock.calls
      .filter(([input]) => String(input).endsWith("/api/oral/tasks"))
      .map(([, init]) => JSON.parse(String(init?.body)));
    expect(bodies[1].idempotency_key).not.toBe(bodies[0].idempotency_key);
    vi.unstubAllGlobals();
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

  it("keeps oral and generation tasks current across multiple polls", async () => {
    vi.useFakeTimers();
    const generationTask = {
      id: "batch-poll",
      batchId: "batch-poll",
      title: "持续刷新的生成批次",
      type: "视频生成" as const,
      status: "queued" as const,
      progress: 0,
      submitted: "2026-09-06T09:00:00Z",
    };
    const oralTask = {
      id: "oral-poll",
      title: "持续刷新的口播",
      type: "数字人口播" as const,
      status: "queued" as const,
      cancelAllowed: false,
      submitted: "2026-09-06T09:01:00Z",
    };
    live.loadStudioData.mockResolvedValue({
      people: [],
      assets: [],
      videos: [],
      projects: [],
      errors: [],
      loading: false,
      stats: null,
      tasks: [generationTask, oralTask],
    });
    live.reloadTasks
      .mockResolvedValueOnce([
        { ...generationTask, status: "running" as const, progress: 36 },
        { ...oralTask, status: "running" as const },
      ])
      .mockResolvedValueOnce([
        { ...generationTask, status: "completed" as const, progress: 100 },
        {
          ...oralTask,
          status: "completed" as const,
          resultId: "oral-result-1",
        },
      ]);

    render(
      <StudioWorkspace
        currentUser={reviewUser}
        initialState={createState("tasks")}
      />,
    );
    await vi.waitFor(() =>
      expect(screen.getByText("持续刷新的口播")).toBeInTheDocument(),
    );
    expect(screen.getAllByText("排队中")).toHaveLength(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(screen.getByText("生成中 36%")).toBeInTheDocument();
    expect(screen.getByText("持续刷新的口播")).toBeInTheDocument();
    expect(screen.getAllByText("生成中")).toHaveLength(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(screen.getByText("持续刷新的生成批次")).toBeInTheDocument();
    expect(screen.getByText("持续刷新的口播")).toBeInTheDocument();
    expect(screen.getAllByText("已完成")).toHaveLength(3);
    vi.useRealTimers();
  });

  it("账号切换后忽略不得写入旧账号迟到的轮询结果", async () => {
    vi.useFakeTimers();
    let resolveTasks: ((value: unknown[]) => void) | undefined;
    let resolveStats: ((value: unknown) => void) | undefined;
    live.loadStudioData.mockResolvedValue({
      people: [],
      assets: [],
      videos: [],
      projects: [],
      tasks: [],
      errors: [],
      loading: false,
      stats: null,
    });
    live.reloadTasks.mockReturnValue(
      new Promise((resolve) => {
        resolveTasks = resolve;
      }),
    );
    live.reloadStats.mockReturnValue(
      new Promise((resolve) => {
        resolveStats = resolve;
      }),
    );
    const user1 = { ...reviewUser, id: "poll-user-1" };
    const user2 = { ...reviewUser, id: "poll-user-2" };
    const view = render(<StudioWorkspace currentUser={user1} />);
    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(live.reloadTasks).toHaveBeenCalledWith(user1);

    view.rerender(<StudioWorkspace currentUser={user2} />);
    await act(async () => {
      resolveTasks?.([
        {
          id: "oral-old-poll-task",
          title: "旧账号口播轮询任务",
          type: "数字人口播",
          status: "running",
          cancelAllowed: false,
          submitted: "2026-09-08T10:00:00Z",
        },
      ]);
      resolveStats?.({
        today_completed: 99,
        running: 1,
        queued: 0,
        needs_attention: 0,
        total_completed: 99,
      });
      await Promise.resolve();
    });

    expect(screen.queryByText("旧账号口播轮询任务")).toBeNull();
    expect(screen.queryByText("99")).toBeNull();
    vi.useRealTimers();
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
          reviewUser.id,
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
