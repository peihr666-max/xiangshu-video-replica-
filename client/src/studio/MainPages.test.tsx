import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createState } from "./state";
import type {
  StudioAsset,
  StudioContextValue,
  StudioData,
  StudioTask,
} from "./types";

const { useStudio, loadTaskPreview } = vi.hoisted(() => ({
  useStudio: vi.fn<() => StudioContextValue>(),
  loadTaskPreview: vi.fn(),
}));

vi.mock("./context", () => ({ useStudio }));
vi.mock("./live", () => ({ loadTaskPreview }));

import { TaskDetailPage } from "./MainPages";

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

function data(tasks: StudioTask[] = [taskA]): StudioData {
  return {
    people: [],
    assets: [],
    videos: [],
    tasks,
    projects: [],
    errors: [],
    loading: false,
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
});
