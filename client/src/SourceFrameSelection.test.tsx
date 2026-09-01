import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  confirmSourceFrame,
  extractSourceFrames,
  getAssetDownloadUrl,
  getLatestProjectSourceFrameSelection,
  getLatestProjectSourceFrames,
  getLatestProjectSourceFrameTask,
  type SourceFrameTask,
  waitForSourceFrameTask,
} from "./api";
import { SourceFrameSelection } from "./SourceFrameSelection";

vi.mock("./api", () => ({
  confirmSourceFrame: vi.fn(),
  extractSourceFrames: vi.fn(),
  getAssetDownloadUrl: vi.fn(),
  getLatestProjectSourceFrameTask: vi.fn(),
  getLatestProjectSourceFrameSelection: vi.fn(),
  getLatestProjectSourceFrames: vi.fn(),
  readSourceFrameCandidates: vi.fn((version) => version.payload),
  waitForSourceFrameTask: vi.fn(),
}));

const candidatesVersion = {
  id: "source-candidates-1",
  project_id: "project-1",
  asset_id: "reference-1",
  kind: "source_frame_candidates",
  version_number: 1,
  payload: {
    requested_timestamps_seconds: [0.5, 1.5, 2.5],
    semantic_quality_status: "VERIFIED",
    candidates: [
      { asset_id: "source-1", timestamp_seconds: 1.5, score: 0.83 },
      { asset_id: "source-2", timestamp_seconds: 0.5, score: 0.52 },
    ],
  },
  created_by_user_id: "employee_1",
  created_at: "2030-01-01T00:00:00Z",
};

const sourceFrameTask = {
  id: "source-frame-task-1",
  project_id: "project-1",
  asset_id: "reference-1",
  timestamps_seconds: [0.5, 1.5, 2.5],
  status: "PENDING" as const,
  attempt: 0,
  result_version_id: null,
  error_code: null,
  error_message: null,
  retryable: false,
  created_at: "2030-01-01T00:00:00Z",
  updated_at: "2030-01-01T00:00:00Z",
  started_at: null,
  completed_at: null,
};

describe("SourceFrameSelection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getLatestProjectSourceFrames).mockResolvedValue(
      candidatesVersion,
    );
    vi.mocked(getLatestProjectSourceFrameSelection).mockResolvedValue({
      version: null,
      stale: false,
    });
    vi.mocked(getLatestProjectSourceFrameTask).mockResolvedValue(null);
    vi.mocked(getAssetDownloadUrl).mockImplementation(async (assetId) => ({
      url: `https://private.example/${assetId}.jpg`,
    }));
    vi.mocked(confirmSourceFrame).mockResolvedValue({
      ...candidatesVersion,
      id: "source-selection-1",
      kind: "source_frame_selection",
      payload: {
        source_frame_asset_id: "source-1",
        character_features: {
          orientation: "FRONT",
          shot_size: "HALF_BODY",
          face_visible: true,
          body_completeness: "UPPER_BODY",
        },
      },
    });
    vi.mocked(extractSourceFrames).mockResolvedValue(sourceFrameTask);
    vi.mocked(waitForSourceFrameTask).mockResolvedValue({
      ...sourceFrameTask,
      status: "SUCCEEDED",
      result_version_id: candidatesVersion.id,
    });
  });

  it("automatically confirms the best candidate and hides technical controls", async () => {
    render(
      <SourceFrameSelection
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    expect(await screen.findByText("源画面自动处理")).toBeInTheDocument();
    await waitFor(() =>
      expect(confirmSourceFrame).toHaveBeenCalledWith(
        "project-1",
        "source-1",
        null,
      ),
    );
    expect(
      await screen.findByText("已自动选择源画面，将保留原视频的构图与动作。"),
    ).toBeInTheDocument();
    expect(screen.getByAltText("候选源画面 1")).toHaveAttribute(
      "src",
      "https://private.example/source-1.jpg",
    );
    expect(screen.queryByText(/技术画质参考/)).toBeNull();
    expect(screen.queryByLabelText("人物朝向")).toBeNull();
    expect(screen.queryByLabelText("人物景别")).toBeNull();
    expect(screen.queryByLabelText("面部可见性")).toBeNull();
    expect(screen.queryByLabelText("身体完整度")).toBeNull();
  });

  it("keeps a manual recovery path when automatic confirmation fails", async () => {
    vi.mocked(confirmSourceFrame)
      .mockRejectedValueOnce(new Error("自动确认暂不可用"))
      .mockResolvedValueOnce({
        ...candidatesVersion,
        id: "source-selection-recovered",
        kind: "source_frame_selection",
        payload: { source_frame_asset_id: "source-1" },
      });

    render(
      <SourceFrameSelection
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    expect(await screen.findByText("自动确认暂不可用")).toBeInTheDocument();
    const useButton = screen.getByRole("button", { name: "使用所选画面" });
    await waitFor(() => expect(useButton).toBeEnabled());
    fireEvent.click(useButton);

    await waitFor(() => expect(confirmSourceFrame).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("已改用源画面 1。")).toBeInTheDocument();
  });

  it("re-extracts at adaptive timestamps without exposing technical inputs", async () => {
    render(
      <SourceFrameSelection
        projectId="project-1"
        referenceAssetId="reference-1"
        videoDurationSeconds={12}
      />,
    );

    await screen.findByAltText("候选源画面 1");
    fireEvent.click(screen.getByRole("button", { name: "重新自动取帧" }));

    await waitFor(() =>
      expect(extractSourceFrames).toHaveBeenCalledWith(
        "project-1",
        "reference-1",
        [1.2, 3.6, 6, 8.4, 10.8],
      ),
    );
    expect(screen.queryByLabelText("重新取帧时间点（秒）")).toBeNull();
  });

  it("keeps an unavailable preview out of the manual fallback", async () => {
    vi.mocked(getAssetDownloadUrl).mockRejectedValueOnce(
      new Error("签名 URL 不可用"),
    );
    render(
      <SourceFrameSelection
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    expect(await screen.findByText("预览加载失败")).toBeInTheDocument();
    expect(screen.getByDisplayValue("source-1")).toBeDisabled();
    expect(screen.getByRole("button", { name: "使用所选画面" })).toBeDisabled();
  });

  it("requires manual confirmation when semantic scoring is unavailable", async () => {
    vi.mocked(getLatestProjectSourceFrames).mockResolvedValue({
      ...candidatesVersion,
      payload: {
        ...candidatesVersion.payload,
        semantic_quality_status: "UNAVAILABLE",
      },
    });

    render(
      <SourceFrameSelection
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    expect(
      await screen.findByText("语义评分暂不可用，请查看候选画面后手动确认。"),
    ).toBeInTheDocument();
    expect(confirmSourceFrame).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "使用所选画面" }),
      ).toBeEnabled(),
    );
  });

  it("does not request protected preview downloads for a read-only auditor", async () => {
    render(
      <SourceFrameSelection
        projectId="project-1"
        readOnly
        referenceAssetId="reference-1"
      />,
    );

    expect(
      await screen.findByText(/只读身份不加载素材预览/),
    ).toBeInTheDocument();
    expect(getAssetDownloadUrl).not.toHaveBeenCalled();
  });

  it("accepts a legacy selection without character features", async () => {
    const onSelectionChange = vi.fn();
    vi.mocked(getLatestProjectSourceFrameSelection).mockResolvedValue({
      stale: false,
      version: {
        ...candidatesVersion,
        id: "source-selection-legacy",
        kind: "source_frame_selection",
        payload: { source_frame_asset_id: "source-1" },
      },
    });

    render(
      <SourceFrameSelection
        onSelectionChange={onSelectionChange}
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    expect(
      await screen.findByText("已自动选择源画面，将保留原视频的构图与动作。"),
    ).toBeInTheDocument();
    expect(onSelectionChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ id: "source-selection-legacy" }),
    );
    expect(confirmSourceFrame).not.toHaveBeenCalled();
  });

  it("locks candidate choice while confirmation is in flight", async () => {
    let resolveConfirmation: (() => void) | undefined;
    vi.mocked(confirmSourceFrame).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveConfirmation = () =>
            resolve({
              ...candidatesVersion,
              id: "source-selection-1",
              kind: "source_frame_selection",
              payload: {
                source_frame_asset_id: "source-1",
                character_features: {
                  orientation: "FRONT",
                  shot_size: "HALF_BODY",
                  face_visible: true,
                  body_completeness: "UPPER_BODY",
                },
              },
            });
        }),
    );
    const onBusyChange = vi.fn();
    render(
      <SourceFrameSelection
        onBusyChange={onBusyChange}
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    await waitFor(() => expect(confirmSourceFrame).toHaveBeenCalledOnce());
    expect(onBusyChange).toHaveBeenLastCalledWith(true);
    expect(screen.getByText("自动处理中")).toBeInTheDocument();
    expect(screen.getByDisplayValue("source-1")).toBeDisabled();
    expect(screen.getByDisplayValue("source-2")).toBeDisabled();

    resolveConfirmation?.();
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(false));
  });

  it("ignores a confirmation response after the project input changes", async () => {
    const savedSelection = {
      ...candidatesVersion,
      id: "source-selection-1",
      kind: "source_frame_selection",
      payload: {
        source_frame_asset_id: "source-1",
        character_features: {
          orientation: "FRONT",
          shot_size: "HALF_BODY",
          face_visible: true,
          body_completeness: "UPPER_BODY",
        },
      },
    };
    let resolveConfirmation:
      | ((selection: typeof savedSelection) => void)
      | undefined;
    const pendingConfirmation = new Promise<typeof savedSelection>(
      (resolve) => {
        resolveConfirmation = resolve;
      },
    );
    vi.mocked(confirmSourceFrame).mockReturnValue(pendingConfirmation);
    const onSelectionChange = vi.fn();
    const { rerender } = render(
      <SourceFrameSelection
        onSelectionChange={onSelectionChange}
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    await waitFor(() => expect(confirmSourceFrame).toHaveBeenCalledOnce());

    rerender(
      <SourceFrameSelection
        onSelectionChange={onSelectionChange}
        projectId="project-2"
        referenceAssetId="reference-2"
      />,
    );
    await act(async () => {
      resolveConfirmation?.(savedSelection);
      await pendingConfirmation;
    });

    expect(onSelectionChange).not.toHaveBeenCalledWith(savedSelection);
  });

  it("does not reload an old project after a stale extraction completes", async () => {
    let resolveExtraction: ((task: typeof sourceFrameTask) => void) | undefined;
    const pendingExtraction = new Promise<typeof sourceFrameTask>((resolve) => {
      resolveExtraction = resolve;
    });
    vi.mocked(extractSourceFrames).mockReturnValue(pendingExtraction);
    const { rerender } = render(
      <SourceFrameSelection
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    await screen.findByAltText("候选源画面 1");
    fireEvent.click(screen.getByRole("button", { name: "重新自动取帧" }));
    await waitFor(() => expect(extractSourceFrames).toHaveBeenCalledOnce());
    rerender(
      <SourceFrameSelection
        projectId="project-2"
        referenceAssetId="reference-2"
      />,
    );
    await waitFor(() =>
      expect(getLatestProjectSourceFrames).toHaveBeenCalledWith("project-2"),
    );
    const loadCount = vi.mocked(getLatestProjectSourceFrames).mock.calls.length;

    await act(async () => {
      resolveExtraction?.(sourceFrameTask);
      await pendingExtraction;
    });

    expect(getLatestProjectSourceFrames).toHaveBeenCalledTimes(loadCount);
  });

  it("releases workspace navigation after the durable extraction task is accepted", async () => {
    let resolveTask: ((task: SourceFrameTask) => void) | undefined;
    const pendingTask = new Promise<SourceFrameTask>((resolve) => {
      resolveTask = resolve;
    });
    vi.mocked(waitForSourceFrameTask).mockReturnValue(pendingTask);
    const onBusyChange = vi.fn();
    render(
      <SourceFrameSelection
        onBusyChange={onBusyChange}
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    await screen.findByAltText("候选源画面 1");
    fireEvent.click(screen.getByRole("button", { name: "重新自动取帧" }));

    await waitFor(() => expect(extractSourceFrames).toHaveBeenCalledOnce());
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(false));
    expect(
      screen.getByText("候选源画面正在后台提取，可离开本页继续其他操作。"),
    ).toBeInTheDocument();

    await act(async () => {
      resolveTask?.({
        ...sourceFrameTask,
        status: "SUCCEEDED",
        result_version_id: candidatesVersion.id,
      });
      await pendingTask;
    });
  });

  it("resumes a pending extraction task after remount without enqueueing again", async () => {
    vi.mocked(getLatestProjectSourceFrames)
      .mockResolvedValueOnce(null)
      .mockResolvedValue(candidatesVersion);
    vi.mocked(getLatestProjectSourceFrameTask).mockResolvedValueOnce(
      sourceFrameTask,
    );

    render(
      <SourceFrameSelection
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    expect(await screen.findByAltText("候选源画面 1")).toBeInTheDocument();
    expect(waitForSourceFrameTask).toHaveBeenCalledWith(sourceFrameTask.id);
    expect(extractSourceFrames).not.toHaveBeenCalled();
  });

  // P0-03-02：候选自动提取与特征预填（红灯先行）。

  it("auto-extracts default candidates when the project has none", async () => {
    vi.mocked(getLatestProjectSourceFrames).mockResolvedValueOnce(null);
    render(
      <SourceFrameSelection
        videoDurationSeconds={12}
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    await waitFor(() =>
      expect(extractSourceFrames).toHaveBeenCalledWith(
        "project-1",
        "reference-1",
        [1.2, 3.6, 6, 8.4, 10.8],
      ),
    );
    expect(await screen.findByAltText("候选源画面 1")).toBeInTheDocument();
  });

  it("automatically confirms after candidates are extracted", async () => {
    vi.mocked(getLatestProjectSourceFrames).mockResolvedValueOnce(null);
    render(
      <SourceFrameSelection
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    expect(await screen.findByAltText("候选源画面 1")).toBeInTheDocument();
    expect(
      await screen.findByText("已自动选择源画面，将保留原视频的构图与动作。"),
    ).toBeInTheDocument();
    expect(confirmSourceFrame).toHaveBeenCalledWith(
      "project-1",
      "source-1",
      null,
    );
  });

  it("does not auto-extract for a read-only auditor", async () => {
    vi.mocked(getLatestProjectSourceFrames).mockResolvedValueOnce(null);
    render(
      <SourceFrameSelection
        projectId="project-1"
        readOnly
        referenceAssetId="reference-1"
      />,
    );

    expect(await screen.findByText("尚未提取候选源画面。")).toBeInTheDocument();
    expect(extractSourceFrames).not.toHaveBeenCalled();
  });

  it("auto-extracts again after switching to another project without candidates", async () => {
    vi.mocked(getLatestProjectSourceFrames).mockResolvedValueOnce(null);
    const { rerender } = render(
      <SourceFrameSelection
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );
    await waitFor(() => expect(extractSourceFrames).toHaveBeenCalledOnce());

    vi.mocked(getLatestProjectSourceFrames).mockResolvedValueOnce(null);
    rerender(
      <SourceFrameSelection
        projectId="project-2"
        referenceAssetId="reference-2"
      />,
    );
    await waitFor(() =>
      expect(extractSourceFrames).toHaveBeenCalledWith(
        "project-2",
        "reference-2",
        [0.5, 1.5, 2.5],
      ),
    );
  });

  it("preselects the highest-scored candidate after loading", async () => {
    render(
      <SourceFrameSelection
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    await screen.findByAltText("候选源画面 1");
    expect(screen.getByDisplayValue("source-1")).toBeChecked();
    expect(screen.getByDisplayValue("source-2")).not.toBeChecked();
  });

  it("passes the latest visual suggestion to automatic confirmation", async () => {
    render(
      <SourceFrameSelection
        featureSuggestion={{
          body_completeness: "FACE_ONLY",
          face_visible: true,
          orientation: "FRONT",
          shot_size: "CLOSE_UP",
        }}
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    await waitFor(() =>
      expect(confirmSourceFrame).toHaveBeenCalledWith("project-1", "source-1", {
        body_completeness: "FACE_ONLY",
        face_visible: true,
        orientation: "FRONT",
        shot_size: "CLOSE_UP",
      }),
    );
    expect(screen.queryByLabelText("人物朝向")).toBeNull();
  });

  it("does not reload across parent re-renders with a changing busy callback", async () => {
    const { rerender } = render(
      <SourceFrameSelection
        featureSuggestion={{
          body_completeness: "UPPER_BODY",
          face_visible: true,
          orientation: "FRONT",
          shot_size: "HALF_BODY",
        }}
        onBusyChange={vi.fn()}
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    await screen.findByAltText("候选源画面 1");
    const initialLoadCount = vi.mocked(getLatestProjectSourceFrames).mock.calls
      .length;
    await waitFor(() => expect(confirmSourceFrame).toHaveBeenCalledOnce());

    rerender(
      <SourceFrameSelection
        featureSuggestion={{
          body_completeness: "UPPER_BODY",
          face_visible: true,
          orientation: "FRONT",
          shot_size: "HALF_BODY",
        }}
        onBusyChange={vi.fn()}
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    expect(getLatestProjectSourceFrames).toHaveBeenCalledTimes(
      initialLoadCount,
    );
    expect(confirmSourceFrame).toHaveBeenCalledOnce();
  });

  it("keeps an existing confirmed source frame over incoming suggestions", async () => {
    vi.mocked(getLatestProjectSourceFrameSelection).mockResolvedValue({
      stale: false,
      version: {
        ...candidatesVersion,
        id: "source-selection-1",
        kind: "source_frame_selection",
        payload: {
          source_frame_asset_id: "source-2",
          character_features: {
            orientation: "LEFT_45",
            shot_size: "HALF_BODY",
            face_visible: false,
            body_completeness: "UPPER_BODY",
          },
        },
      },
    });
    render(
      <SourceFrameSelection
        featureSuggestion={{
          body_completeness: "FULL_BODY",
          face_visible: true,
          orientation: "FRONT",
          shot_size: "FULL_BODY",
        }}
        projectId="project-1"
        referenceAssetId="reference-1"
      />,
    );

    expect(
      await screen.findByText("已自动选择源画面，将保留原视频的构图与动作。"),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("source-2")).toBeChecked();
    expect(confirmSourceFrame).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("人物朝向")).toBeNull();
  });
});
