import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createState } from "./state";
import type {
  StudioAsset,
  StudioContextValue,
  StudioData,
  StudioTask,
  StudioVideo,
} from "./types";

const {
  useStudio,
  loadTaskPreview,
  uploadWorkbenchSourceVideo,
  cancelStudioTask,
  downloadStudioTaskResult,
  retryStudioTask,
  loadPublishAccounts,
  connectPublishAccount,
  removePublishAccount,
  requestPublishAccountVerify,
} = vi.hoisted(() => ({
  useStudio: vi.fn<() => StudioContextValue>(),
  loadTaskPreview: vi.fn(),
  uploadWorkbenchSourceVideo: vi.fn(),
  cancelStudioTask: vi.fn(),
  downloadStudioTaskResult: vi.fn(),
  retryStudioTask: vi.fn(),
  loadPublishAccounts: vi.fn(),
  connectPublishAccount: vi.fn(),
  removePublishAccount: vi.fn(),
  requestPublishAccountVerify: vi.fn(),
}));

vi.mock("./context", () => ({ useStudio }));
vi.mock("./live", () => ({
  loadTaskPreview,
  uploadWorkbenchSourceVideo,
  cancelStudioTask,
  downloadStudioTaskResult,
  retryStudioTask,
  loadPublishAccounts,
  connectPublishAccount,
  removePublishAccount,
  requestPublishAccountVerify,
}));

import {
  ProfilePage,
  TaskDetailPage,
  TasksPage,
  WorkbenchPage,
} from "./MainPages";
import { formatTaskTime } from "./ui";

const taskA: StudioTask = {
  id: "task-a",
  title: "张工建房预算",
  type: "数字人口播",
  status: "completed",
  submitted: "2026-09-05 10:00",
  batchId: "batch-a",
};

const taskB: StudioTask = {
  ...taskA,
  id: "task-b",
  title: "李总项目巡检",
  batchId: "batch-b",
};

const runningTask: StudioTask = {
  id: "batch-9",
  batchId: "batch-9",
  title: "张工 · 建房预算",
  type: "数字人口播",
  status: "running",
  progress: 68,
  submitted: "2026-09-06T09:30:00",
};

function data(
  tasks: StudioTask[] = [taskA],
  videos: StudioVideo[] = [],
): StudioData {
  return {
    people: [],
    assets: [],
    videos,
    tasks,
    projects: [],
    errors: [],
    materials: [],
    loading: false,
    stats: null,
    analytics7: null,
    analytics30: null,
  };
}

function studio(
  selectedTaskId = taskA.id,
  overrides: Partial<StudioContextValue> = {},
): StudioContextValue {
  return {
    state: { ...createState("task-detail"), selectedTaskId },
    data: data(),
    review: false,
    user: {} as StudioContextValue["user"],
    navigate: vi.fn(),
    patchDraft: vi.fn(),
    patchState: vi.fn(),
    updateData: vi.fn(),
    notify: vi.fn(),
    openPicker: vi.fn(),
    openLive: vi.fn(),
    requestGeneration: vi.fn(),
    saveDraft: vi.fn(),
    confirmFinalDraft: vi.fn(),
    extractScriptFromUpload: vi.fn(),
    refresh: vi.fn(),
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("V1.4 任务详情真实成片预览", () => {
  beforeEach(() => {
    useStudio.mockReset();
    loadTaskPreview.mockReset();
    downloadStudioTaskResult.mockReset();
    retryStudioTask.mockReset();
  });

  it("仅在用户点击后按需加载，并只回填发起任务的结果", async () => {
    const pending = deferred<StudioAsset | undefined>();
    const value = studio(taskA.id, { data: data([taskA, taskB]) });
    useStudio.mockReturnValue(value);
    loadTaskPreview.mockReturnValue(pending.promise);
    render(<TaskDetailPage />);

    expect(loadTaskPreview).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "预览成片" }));
    expect(loadTaskPreview).toHaveBeenCalledWith(taskA);
    expect(
      screen.getByRole("button", { name: "正在加载预览…" }),
    ).toBeDisabled();

    const asset: StudioAsset = {
      id: "result-a",
      name: "张工建房预算 · 首个可用结果",
      kind: "video",
      url: "/signed/result-a",
      group: "任务结果",
      source: "任务中心",
      saved: true,
    };
    pending.resolve(asset);

    await waitFor(() => expect(value.updateData).toHaveBeenCalledOnce());
    const update = vi.mocked(value.updateData).mock.calls[0][0];
    const next = update(value.data);
    expect(next.assets).toContainEqual(asset);
    expect(next.tasks.find((item) => item.id === taskA.id)?.resultId).toBe(
      asset.id,
    );
    expect(next.tasks.find((item) => item.id === taskB.id)?.resultId).toBe(
      undefined,
    );
  });

  it("显示无结果状态，并允许重新尝试", async () => {
    const value = studio();
    useStudio.mockReturnValue(value);
    loadTaskPreview.mockResolvedValue(undefined);
    render(<TaskDetailPage />);

    fireEvent.click(screen.getByRole("button", { name: "预览成片" }));
    expect(
      await screen.findByText("该批次暂时没有可预览的成功结果。"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新尝试" }));
    expect(loadTaskPreview).toHaveBeenCalledTimes(2);
  });

  it("失败后显示错误并可重试", async () => {
    const value = studio();
    useStudio.mockReturnValue(value);
    loadTaskPreview.mockRejectedValue(new Error("preview unavailable"));
    render(<TaskDetailPage />);

    fireEvent.click(screen.getByRole("button", { name: "预览成片" }));
    expect(
      await screen.findByText("预览加载失败，请重试。"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试预览" }));
    expect(loadTaskPreview).toHaveBeenCalledTimes(2);
  });

  it("切换任务后忽略旧请求的异步结果", async () => {
    const pending = deferred<StudioAsset | undefined>();
    const updateData = vi.fn();
    let value = studio(taskA.id, {
      data: data([taskA, taskB]),
      updateData,
    });
    useStudio.mockImplementation(() => value);
    loadTaskPreview.mockReturnValue(pending.promise);
    const view = render(<TaskDetailPage />);

    fireEvent.click(screen.getByRole("button", { name: "预览成片" }));
    value = studio(taskB.id, {
      data: data([taskA, taskB]),
      updateData,
    });
    view.rerender(<TaskDetailPage />);
    expect(
      screen.getByRole("heading", { name: taskB.title }),
    ).toBeInTheDocument();

    pending.resolve({
      id: "stale-result",
      name: "旧任务结果",
      kind: "video",
      url: "/signed/stale",
      group: "任务结果",
      source: "任务中心",
      saved: true,
    });
    await pending.promise;
    await Promise.resolve();
    expect(updateData).not.toHaveBeenCalled();
  });

  it("审核示例不请求真实预览接口", () => {
    useStudio.mockReturnValue(studio(taskA.id, { review: true }));
    render(<TaskDetailPage />);

    expect(
      screen.queryByRole("button", { name: "预览成片" }),
    ).not.toBeInTheDocument();
    expect(loadTaskPreview).not.toHaveBeenCalled();
  });

  it("口播成片下载直接使用结果资产，不再打开旧任务面板", async () => {
    const oralTask: StudioTask = {
      ...taskA,
      id: "oral-visible-id",
      backendKind: "oral_task",
      backendId: "oral-backend-id",
      resultId: "oral-result-asset",
      batchId: undefined,
    };
    const value = studio(oralTask.id, { data: data([oralTask]) });
    useStudio.mockReturnValue(value);
    downloadStudioTaskResult.mockResolvedValue(undefined);
    render(<TaskDetailPage />);

    fireEvent.click(screen.getByRole("button", { name: "下载成片" }));

    await waitFor(() =>
      expect(downloadStudioTaskResult).toHaveBeenCalledWith(oralTask),
    );
    expect(value.openLive).not.toHaveBeenCalled();
  });

  it("只对后端允许的口播异常状态展示真实重试动作", async () => {
    const retryable: StudioTask = {
      ...taskA,
      id: "oral-uncertain",
      backendKind: "oral_task",
      backendId: "oral-uncertain",
      backendStatus: "SUBMISSION_UNCERTAIN",
      status: "uncertain",
      retryAction: "retry",
      resultId: undefined,
    };
    const value = studio(retryable.id, { data: data([retryable]) });
    useStudio.mockReturnValue(value);
    retryStudioTask.mockResolvedValue(undefined);
    render(<TaskDetailPage />);

    fireEvent.click(screen.getByRole("button", { name: "重试提交" }));

    await waitFor(() =>
      expect(retryStudioTask).toHaveBeenCalledWith(retryable),
    );
    expect(value.refresh).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole("button", { name: "重试归档" }),
    ).not.toBeInTheDocument();
  });
});

describe("V1.4 工作台正在进行行", () => {
  const clock = new Date("2026-09-06T10:00:00");

  beforeEach(() => {
    useStudio.mockReset();
    // Fake only the clock: waitFor relies on real timers.
    vi.useFakeTimers({ now: clock, toFake: ["Date"] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function workbench(
    overrides: Partial<StudioContextValue> = {},
  ): StudioContextValue {
    return studio(undefined, {
      state: { ...createState("workbench") },
      data: data([runningTask]),
      ...overrides,
    });
  }

  it("每行提供更多操作菜单：打开任务中心与复制任务编号", async () => {
    const value = workbench();
    useStudio.mockReturnValue(value);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    render(<WorkbenchPage />);

    const trigger = screen.getByRole("button", {
      name: "更多操作：张工 · 建房预算",
    });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(screen.getByRole("menuitem", { name: "打开任务中心" }));
    expect(value.navigate).toHaveBeenCalledWith("tasks");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("menuitem", { name: "复制任务编号" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("batch-9"));
    expect(value.notify).toHaveBeenCalledWith("任务编号已复制");
  });

  it("复制失败时给出可感知的失败提示", async () => {
    const value = workbench();
    useStudio.mockReturnValue(value);
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    render(<WorkbenchPage />);

    fireEvent.click(
      screen.getByRole("button", { name: "更多操作：张工 · 建房预算" }),
    );
    fireEvent.click(screen.getByRole("menuitem", { name: "复制任务编号" }));
    await waitFor(() =>
      expect(value.notify).toHaveBeenCalledWith(
        "复制失败，请手动复制任务编号。",
      ),
    );
    expect(writeText).toHaveBeenCalledWith("batch-9");
  });

  it("任务动态与正在进行行不显示原始 ISO 时间", () => {
    useStudio.mockReturnValue(workbench());
    render(<WorkbenchPage />);

    expect(screen.queryByText("2026-09-06T09:30:00")).not.toBeInTheDocument();
    expect(screen.getByText("今天 09:30")).toBeInTheDocument();
    expect(screen.getByText("68%")).toBeInTheDocument();
  });
});

describe("V1.4 工作台新版首页布局", () => {
  const videos: StudioVideo[] = Array.from({ length: 7 }, (_, index) => ({
    id: `video-${index + 1}`,
    title: `灵感视频 ${index + 1}`,
    author: `作者 ${index + 1}`,
    platform: index % 2 === 0 ? "抖音" : "视频号",
    category: "乡墅",
    poster: `/poster-${index + 1}.jpg`,
    duration: "00:56",
    likes: 128000 - index * 1000,
    collections: 100,
    shares: 20,
    description: "乡墅爆款案例",
  }));

  it("展示新版主标题、居中辅助文案、五个竖屏爆款与四个快捷入口", () => {
    const value = studio(undefined, {
      state: createState("workbench"),
      data: data([runningTask], videos),
    });
    useStudio.mockReturnValue(value);

    render(<WorkbenchPage />);

    expect(
      screen.getByRole("heading", {
        name: "粘贴一条爆款乡墅视频链接，快速生成它的原创视频",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("提取文案进入文案工坊，开始复刻进入分镜工作区。"),
    ).toHaveClass("studio-start-helper");
    expect(
      screen.getByRole("heading", { name: "爆款视频精选" }),
    ).toBeInTheDocument();
    expect(screen.getByText("灵感视频 5")).toBeInTheDocument();
    expect(screen.queryByText("灵感视频 6")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /用它复刻/ })).toHaveLength(5);
    expect(
      screen.getByRole("button", { name: "查看全部爆款" }),
    ).toBeInTheDocument();
    for (const name of ["文案工坊", "人物库", "素材库", "数据看板"]) {
      expect(
        screen.getByRole("button", { name: `快捷入口：${name}` }),
      ).toBeInTheDocument();
    }
  });

  it("从首页爆款卡片开始复刻时复用既有草稿与导航流程", () => {
    const value = studio(undefined, {
      state: createState("workbench"),
      data: data([], videos),
    });
    useStudio.mockReturnValue(value);

    render(<WorkbenchPage />);
    fireEvent.click(
      screen.getByRole("button", { name: "用它复刻：灵感视频 1" }),
    );

    expect(value.patchDraft).toHaveBeenCalledWith({ sourceId: "video-1" });
    expect(value.navigate).toHaveBeenCalledWith("replica", {
      selectedVideoId: "video-1",
      returnTo: "workbench",
    });
  });
});

describe("formatTaskTime", () => {
  const now = new Date("2026-09-06T10:00:00");

  it("当天显示“今天 HH:mm”", () => {
    expect(formatTaskTime("2026-09-06T09:30:00", now)).toBe("今天 09:30");
    expect(formatTaskTime("2026-09-06 00:05", now)).toBe("今天 00:05");
  });

  it("前一天显示“昨天 HH:mm”", () => {
    expect(formatTaskTime("2026-09-05T23:58:00", now)).toBe("昨天 23:58");
  });

  it("同年更早显示“MM-DD HH:mm”，跨年带年份", () => {
    expect(formatTaskTime("2026-09-03T14:00:00", now)).toBe("09-03 14:00");
    expect(formatTaskTime("2025-12-31T08:05:00", now)).toBe("2025-12-31 08:05");
  });

  it("无法解析或已是友好文案时原样返回", () => {
    expect(formatTaskTime("今天 09:30", now)).toBe("今天 09:30");
    expect(formatTaskTime("", now)).toBe("");
  });
});

describe("V1.4 工作台上传与创作入口", () => {
  beforeEach(() => {
    useStudio.mockReset();
    uploadWorkbenchSourceVideo.mockReset();
  });

  function workbench(
    overrides: Partial<StudioContextValue> = {},
  ): StudioContextValue {
    return studio(undefined, {
      state: { ...createState("workbench") },
      data: data([]),
      ...overrides,
    });
  }

  function changeFile(name: string) {
    const input = screen.getByLabelText("选择视频文件");
    fireEvent.change(input, {
      target: { files: [new File(["video"], name, { type: "video/mp4" })] },
    });
  }

  it("审核模式点击上传图标只提示，不进入真实上传", () => {
    const value = workbench({ review: true });
    useStudio.mockReturnValue(value);
    render(<WorkbenchPage />);

    fireEvent.click(screen.getByRole("button", { name: "上传视频" }));
    expect(value.notify).toHaveBeenCalledWith("审核示例不执行真实上传。");
    expect(uploadWorkbenchSourceVideo).not.toHaveBeenCalled();
  });

  it("非 MP4/MOV 文件被拒收并提示", () => {
    const value = workbench();
    useStudio.mockReturnValue(value);
    render(<WorkbenchPage />);

    changeFile("相册导出.avi");
    expect(value.notify).toHaveBeenCalledWith(
      "目前仅支持 MP4 / MOV 视频文件。",
    );
    expect(uploadWorkbenchSourceVideo).not.toHaveBeenCalled();
  });

  it("上传成功：展示进度与云存储状态，并把来源写入当前草稿", async () => {
    const value = workbench();
    useStudio.mockReturnValue(value);
    const pending: {
      resolve?: (value: { projectId: string; assetId: string }) => void;
    } = {};
    uploadWorkbenchSourceVideo.mockImplementation(
      (_file: File, onProgress: (percent: number) => void) =>
        new Promise<{ projectId: string; assetId: string }>((resolve) => {
          pending.resolve = resolve;
          onProgress(40);
        }),
    );
    render(<WorkbenchPage />);

    changeFile("乡墅案例.mp4");
    expect(uploadWorkbenchSourceVideo).toHaveBeenCalledOnce();
    expect(screen.getByText("正在上传 乡墅案例.mp4… 40%")).toBeInTheDocument();

    pending.resolve?.({ projectId: "proj-1", assetId: "asset-1" });
    await waitFor(() =>
      expect(value.patchDraft).toHaveBeenCalledWith({
        sourceId: "proj-1",
        sourceAssetId: "asset-1",
      }),
    );
    expect(screen.getByText("已上传云存储：乡墅案例.mp4")).toBeInTheDocument();
    expect(value.notify).toHaveBeenCalledWith(
      "视频已上传云存储，来源已加入当前创作。",
    );
  });

  it("上传完成后开始复刻直接进分镜工作区，不再打开项目面板", async () => {
    const value = workbench();
    useStudio.mockReturnValue(value);
    uploadWorkbenchSourceVideo.mockResolvedValue({
      projectId: "proj-1",
      assetId: "asset-1",
    });
    render(<WorkbenchPage />);

    changeFile("乡墅案例.mp4");
    await waitFor(() =>
      expect(value.patchDraft).toHaveBeenCalledWith({
        sourceId: "proj-1",
        sourceAssetId: "asset-1",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "开始复刻" }));
    expect(value.navigate).toHaveBeenCalledWith("replica");
    expect(value.openLive).not.toHaveBeenCalled();
  });

  it("上传后的提取文案走 script-from-audio 管线，不再打开旧项目面板", async () => {
    const value = workbench();
    useStudio.mockReturnValue(value);
    uploadWorkbenchSourceVideo.mockResolvedValue({
      projectId: "proj-1",
      assetId: "asset-1",
    });
    render(<WorkbenchPage />);

    changeFile("乡墅案例.mp4");
    await waitFor(() =>
      expect(value.patchDraft).toHaveBeenCalledWith({
        sourceId: "proj-1",
        sourceAssetId: "asset-1",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "提取文案" }));
    expect(value.extractScriptFromUpload).toHaveBeenCalledTimes(1);
    expect(value.openLive).not.toHaveBeenCalled();
    expect(value.navigate).not.toHaveBeenCalled();
  });

  it("已恢复草稿含来源时，提取文案同样走管线", () => {
    const state = createState("workbench");
    state.draft.sourceId = "proj-9";
    state.draft.projectId = "proj-9";
    const value = workbench({ state });
    useStudio.mockReturnValue(value);
    render(<WorkbenchPage />);

    fireEvent.click(screen.getByRole("button", { name: "提取文案" }));
    expect(value.extractScriptFromUpload).toHaveBeenCalledTimes(1);
    expect(value.openLive).not.toHaveBeenCalled();
  });
});

describe("V1.4 任务中心列表", () => {
  const clock = new Date("2026-09-06T10:00:00");
  const queuedTask: StudioTask = {
    id: "t-queued",
    batchId: "b-queued",
    title: "三层新中式乡墅",
    type: "视频复刻",
    status: "queued",
    submitted: "2026-09-06T09:32:00",
  };
  const failedTask: StudioTask = {
    id: "t-failed",
    batchId: "b-failed",
    title: "张工 · 庭院讲解首帧",
    type: "人物置换",
    status: "failed",
    submitted: "2026-09-06T09:28:00",
  };
  const doneTask: StudioTask = {
    id: "t-done",
    batchId: "b-done",
    title: "张工 · 建房预算-已确认版",
    type: "数字人口播",
    status: "completed",
    submitted: "2026-09-06T09:25:00",
  };

  beforeEach(() => {
    useStudio.mockReset();
    cancelStudioTask.mockReset();
    vi.useFakeTimers({ now: clock, toFake: ["Date"] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function tasksPage(
    overrides: Partial<StudioContextValue> = {},
  ): StudioContextValue {
    return studio(undefined, {
      state: { ...createState("tasks") },
      data: data([runningTask, queuedTask, failedTask, doneTask]),
      ...overrides,
    });
  }

  it("状态页签展示进行中/待处理计数", () => {
    useStudio.mockReturnValue(tasksPage());
    render(<TasksPage />);

    expect(screen.getByRole("tab", { name: "进行中 2" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "待处理 1" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "已完成" })).toBeInTheDocument();
  });

  it("状态列带子文案：排队中→等待开始、待处理→生成失败", () => {
    useStudio.mockReturnValue(tasksPage());
    render(<TasksPage />);

    expect(screen.getByText("等待开始")).toBeInTheDocument();
    expect(screen.getByText("生成失败")).toBeInTheDocument();
  });

  it("提交时间本地化，不显示原始 ISO 串", () => {
    useStudio.mockReturnValue(tasksPage());
    render(<TasksPage />);

    expect(screen.getByText("今天 09:32")).toBeInTheDocument();
    expect(screen.queryByText("2026-09-06T09:32:00")).not.toBeInTheDocument();
  });

  it("排队行提供取消任务：成功后提示并刷新列表", async () => {
    const value = tasksPage();
    useStudio.mockReturnValue(value);
    cancelStudioTask.mockResolvedValue({ billingStatus: "PENDING" });
    render(<TasksPage />);

    fireEvent.click(screen.getByRole("button", { name: "取消任务" }));
    expect(cancelStudioTask).toHaveBeenCalledWith(queuedTask);
    await waitFor(() =>
      expect(value.notify).toHaveBeenCalledWith(
        "任务已取消，计费状态处理中，请稍后刷新核对。",
      ),
    );
    expect(value.refresh).toHaveBeenCalledOnce();
  });

  it("取消失败时给出可感知的错误提示", async () => {
    const value = tasksPage();
    useStudio.mockReturnValue(value);
    cancelStudioTask.mockRejectedValue(new Error("任务已在提交中"));
    render(<TasksPage />);

    fireEvent.click(screen.getByRole("button", { name: "取消任务" }));
    await waitFor(() =>
      expect(value.notify).toHaveBeenCalledWith("任务已在提交中"),
    );
    expect(value.refresh).not.toHaveBeenCalled();
  });

  it("审核模式点击取消只提示，不调用接口", () => {
    const value = tasksPage({ review: true });
    useStudio.mockReturnValue(value);
    render(<TasksPage />);

    fireEvent.click(screen.getByRole("button", { name: "取消任务" }));
    expect(cancelStudioTask).not.toHaveBeenCalled();
    expect(value.notify).toHaveBeenCalledWith("审核示例不执行真实取消。");
  });

  it("非排队行不出现取消入口", () => {
    useStudio.mockReturnValue(tasksPage());
    render(<TasksPage />);

    expect(screen.getAllByRole("button", { name: "取消任务" })).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "查看结果" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "查看详情" })).toHaveLength(2);
  });

  it("口播任务只有后端 QUEUED 状态可取消", () => {
    const submittingOral: StudioTask = {
      ...queuedTask,
      id: "oral-submitting",
      backendKind: "oral_task",
      backendId: "oral-submitting",
      backendStatus: "SUBMITTING",
      type: "数字人口播",
    };
    useStudio.mockReturnValue(
      tasksPage({ data: data([submittingOral, queuedTask]) }),
    );
    render(<TasksPage />);

    expect(screen.getAllByRole("button", { name: "取消任务" })).toHaveLength(1);
  });

  it("类型筛选收进单行下拉，菜单项计数与状态筛选联动", () => {
    useStudio.mockReturnValue(tasksPage());
    render(<TasksPage />);

    expect(
      screen.queryByRole("tab", { name: "视频复刻" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "类型：全部类型" }));
    expect(
      screen.getByRole("option", { name: "✓ 全部类型 4" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "数字人口播 2" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "视频复刻 1" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "人物置换 1" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "视频生成 0" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "进行中 2" }));
    expect(
      screen.getByRole("option", { name: "数字人口播 1" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "视频复刻 1" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "人物置换 0" }),
    ).toBeInTheDocument();
  });

  it("选择类型后过滤表格、高亮触发按钮并更新结果计数", () => {
    useStudio.mockReturnValue(tasksPage());
    render(<TasksPage />);

    expect(screen.getByText("共 4 条任务")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "类型：全部类型" }));
    fireEvent.click(screen.getByRole("option", { name: "数字人口播 2" }));

    const trigger = screen.getByRole("button", { name: "类型：数字人口播" });
    expect(trigger).toHaveClass("is-active");
    expect(screen.getByText("共 2 条任务")).toBeInTheDocument();
    expect(screen.getByText("张工 · 建房预算")).toBeInTheDocument();
    expect(screen.queryByText("三层新中式乡墅")).not.toBeInTheDocument();
  });

  it("筛选无结果时提供清除筛选出口，一键复位两个维度", () => {
    useStudio.mockReturnValue(tasksPage());
    render(<TasksPage />);

    fireEvent.click(screen.getByRole("tab", { name: "待处理 1" }));
    fireEvent.click(screen.getByRole("button", { name: "类型：全部类型" }));
    fireEvent.click(screen.getByRole("option", { name: "视频复刻 0" }));

    expect(screen.getByText("当前筛选下暂无任务")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "清除筛选" }));

    expect(
      screen.getByRole("tab", { name: "全部", selected: true }),
    ).toBeInTheDocument();
    expect(screen.getByText("共 4 条任务")).toBeInTheDocument();
    expect(screen.getByText("三层新中式乡墅")).toBeInTheDocument();
  });

  it("类型下拉支持 Escape 与点选外部关闭", () => {
    useStudio.mockReturnValue(tasksPage());
    render(<TasksPage />);

    fireEvent.click(screen.getByRole("button", { name: "类型：全部类型" }));
    expect(screen.getByRole("listbox", { name: "类型" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      screen.queryByRole("listbox", { name: "类型" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "类型：全部类型" }));
    fireEvent.pointerDown(screen.getByRole("heading", { name: "任务中心" }));
    expect(
      screen.queryByRole("listbox", { name: "类型" }),
    ).not.toBeInTheDocument();
  });
});

describe("C5 发布账号管理（正式模式）", () => {
  beforeEach(() => {
    connectPublishAccount.mockClear();
    loadPublishAccounts.mockClear();
    removePublishAccount.mockClear();
    requestPublishAccountVerify.mockClear();
  });

  it("连接发布账号：填写 Cookie 后提交并回显列表", async () => {
    loadPublishAccounts.mockResolvedValue([]);
    connectPublishAccount.mockResolvedValue({
      id: "acc-9",
      platform: "douyin",
      displayName: "张工说乡墅",
      status: "connected",
      lastVerifiedAt: null,
      errorMessage: null,
      securitySdkRequired: true,
      createdAt: "2026-09-07 00:00:00",
    });
    const value = studio(undefined as unknown as string, { review: false });
    useStudio.mockReturnValue(value);
    render(<ProfilePage />);

    fireEvent.click(screen.getByText("发布账号"));
    fireEvent.change(screen.getByPlaceholderText("例如：张工说乡墅"), {
      target: { value: "张工说乡墅" },
    });
    fireEvent.change(
      screen.getByPlaceholderText("粘贴从浏览器复制的整段 Cookie"),
      { target: { value: "sessionid=test; ttwid=1" } },
    );
    fireEvent.change(
      screen.getByPlaceholderText(
        "粘贴浏览器 localStorage 中 security-sdk 对应的 JSON 内容",
      ),
      { target: { value: '{"key_version":3}' } },
    );
    fireEvent.click(screen.getByRole("button", { name: "连接发布账号" }));

    await waitFor(() =>
      expect(connectPublishAccount).toHaveBeenCalledWith({
        platform: "douyin",
        displayName: "张工说乡墅",
        cookie: "sessionid=test; ttwid=1",
        securitySdk: '{"key_version":3}',
      }),
    );
    await waitFor(() =>
      expect(value.notify).toHaveBeenCalledWith(
        "发布账号已连接，可点击“校验登录态”确认有效性。",
      ),
    );
    await waitFor(() =>
      expect(value.notify).toHaveBeenCalledWith(
        "发布账号已连接，可点击“校验登录态”确认有效性。",
      ),
    );
    expect(value.notify).toHaveBeenCalledWith(
      "发布账号已连接，可点击“校验登录态”确认有效性。",
    );
  });

  it("抖音未填 security_sdk 时给出明确提示", async () => {
    loadPublishAccounts.mockResolvedValue([]);
    const value = studio(undefined as unknown as string, { review: false });
    useStudio.mockReturnValue(value);
    render(<ProfilePage />);
    fireEvent.click(screen.getByText("发布账号"));
    fireEvent.change(screen.getByPlaceholderText("例如：张工说乡墅"), {
      target: { value: "张工说乡墅" },
    });
    fireEvent.change(
      screen.getByPlaceholderText("粘贴从浏览器复制的整段 Cookie"),
      { target: { value: "sessionid=test" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "连接发布账号" }));
    expect(value.notify).toHaveBeenCalledWith(
      "抖音需要同时粘贴 security_sdk 材料（浏览器 localStorage 导出）。",
    );
    expect(connectPublishAccount).not.toHaveBeenCalled();
  });
});
