import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createOralComposition: vi.fn(),
  downloadMaterialAsset: vi.fn(),
  getOralCompositionCapabilities: vi.fn(),
  listOralCompositions: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));

import { OralCompositionPanel } from "./OralCompositionPanel";

const capabilities = {
  available: true,
  reason: null,
  templates: [
    { id: "bottom_caption", title: "底部大字", description: "底部双行大字" },
    { id: "center_banner", title: "居中色带", description: "中部色带标题" },
    { id: "top_title", title: "顶部标题", description: "顶部封面标题" },
  ],
};

describe("口播成片后期模板", () => {
  beforeEach(() => {
    api.createOralComposition.mockReset();
    api.downloadMaterialAsset.mockReset();
    api.getOralCompositionCapabilities.mockReset();
    api.listOralCompositions.mockReset();
    api.getOralCompositionCapabilities.mockResolvedValue(capabilities);
    api.listOralCompositions.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("只在后端确认渲染能力后允许创建独立合成版本", async () => {
    api.createOralComposition.mockResolvedValue({
      id: "compose-1",
      oral_task_id: "oral-1",
      template: "center_banner",
      text: "一套好房子要先解决生活",
      status: "QUEUED",
      result_asset_id: null,
      is_active: false,
      error_message: null,
      created_at: "2026-09-07T10:00:00Z",
      updated_at: "2026-09-07T10:00:00Z",
      replayed: false,
    });

    render(<OralCompositionPanel oralTaskId="oral-1" defaultText="张工口播" />);

    expect(await screen.findByText("网感后期")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("后期模板"), {
      target: { value: "center_banner" },
    });
    fireEvent.change(screen.getByLabelText("后期文字"), {
      target: { value: "一套好房子要先解决生活" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成后期版本" }));

    await waitFor(() =>
      expect(api.createOralComposition).toHaveBeenCalledWith("oral-1", {
        template: "center_banner",
        text: "一套好房子要先解决生活",
        idempotencyKey: expect.stringMatching(/^oral-compose:/),
      }),
    );
    expect(await screen.findByText("排队中")).toBeInTheDocument();
  });

  it("不可用时显示后端原因且不提供伪生成入口", async () => {
    api.getOralCompositionCapabilities.mockResolvedValue({
      available: false,
      reason: "随包 FFmpeg 缺少 overlay 滤镜",
      templates: capabilities.templates,
    });

    render(<OralCompositionPanel oralTaskId="oral-1" defaultText="张工口播" />);

    expect(
      await screen.findByText("随包 FFmpeg 缺少 overlay 滤镜"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "生成后期版本" })).toBeNull();
  });

  it("下载的是激活后期版本，不覆盖原口播成片", async () => {
    api.listOralCompositions.mockResolvedValue([
      {
        id: "compose-ready",
        oral_task_id: "oral-1",
        template: "top_title",
        text: "自建房避坑指南",
        status: "SUCCEEDED",
        result_asset_id: "asset-composed",
        is_active: true,
        error_message: null,
        created_at: "2026-09-07T10:00:00Z",
        updated_at: "2026-09-07T10:01:00Z",
      },
    ]);
    api.downloadMaterialAsset.mockResolvedValue(undefined);

    render(<OralCompositionPanel oralTaskId="oral-1" defaultText="张工口播" />);

    fireEvent.click(
      await screen.findByRole("button", { name: "下载当前后期版本" }),
    );
    await waitFor(() =>
      expect(api.downloadMaterialAsset).toHaveBeenCalledWith(
        "asset-composed",
        "张工口播-顶部标题.mp4",
      ),
    );
  });

  it("网络丢失响应后重试复用同一幂等键", async () => {
    api.createOralComposition
      .mockRejectedValueOnce(new Error("网络超时"))
      .mockResolvedValueOnce({
        id: "compose-replayed",
        oral_task_id: "oral-1",
        template: "bottom_caption",
        text: "张工口播",
        status: "QUEUED",
        result_asset_id: null,
        is_active: false,
        error_message: null,
        created_at: "2026-09-07T10:00:00Z",
        updated_at: "2026-09-07T10:00:00Z",
        replayed: true,
      });

    render(<OralCompositionPanel oralTaskId="oral-1" defaultText="张工口播" />);

    const button = await screen.findByRole("button", {
      name: "生成后期版本",
    });
    fireEvent.click(button);
    expect(await screen.findByText("网络超时")).toBeInTheDocument();
    fireEvent.click(button);
    await screen.findByText("排队中");

    const firstKey = api.createOralComposition.mock.calls[0][1].idempotencyKey;
    const secondKey = api.createOralComposition.mock.calls[1][1].idempotencyKey;
    expect(secondKey).toBe(firstKey);
  });

  it("轮询排队中版本并在成功激活后通知工作台刷新", async () => {
    vi.useFakeTimers();
    const onActivated = vi.fn();
    api.listOralCompositions
      .mockResolvedValueOnce([
        {
          id: "compose-pending",
          oral_task_id: "oral-1",
          template: "top_title",
          text: "张工口播",
          status: "QUEUED",
          result_asset_id: null,
          is_active: false,
          error_message: null,
          created_at: "2026-09-07T10:00:00Z",
          updated_at: "2026-09-07T10:00:00Z",
        },
      ])
      .mockResolvedValueOnce([
        {
          id: "compose-pending",
          oral_task_id: "oral-1",
          template: "top_title",
          text: "张工口播",
          status: "SUCCEEDED",
          result_asset_id: "asset-composed",
          is_active: true,
          error_message: null,
          created_at: "2026-09-07T10:00:00Z",
          updated_at: "2026-09-07T10:01:00Z",
        },
      ]);

    render(
      <OralCompositionPanel
        oralTaskId="oral-1"
        defaultText="张工口播"
        onActivated={onActivated}
      />,
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText("排队中")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_500);
    });
    expect(screen.getByText("当前版本")).toBeInTheDocument();
    expect(onActivated).toHaveBeenCalledTimes(1);
  });
});
