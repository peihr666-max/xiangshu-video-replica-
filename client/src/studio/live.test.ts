import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  CurrentUser,
  GenerationBatch,
  GenerationBatchListPage,
  GenerationTask,
  OralTaskRecord,
  Project,
  SimpleLibraryEntry,
  SimpleSceneLook,
} from "../api";

const api = vi.hoisted(() => ({
  createGenerationResultPreviewUrl: vi.fn(),
  createGenerationTaskPreviewUrl: vi.fn(),
  getAssetDownloadUrl: vi.fn(),
  getCachedCharacterAssetUrl: vi.fn(),
  getGenerationBatch: vi.fn(),
  getLatestProjectAnalysis: vi.fn(),
  getStudioStats: vi.fn(async () => null),
  getLatestScriptVersion: vi.fn(),
  listCharacterSceneLooks: vi.fn(),
  listGenerationBatches: vi.fn(),
  listOralTasks: vi.fn(async (): Promise<OralTaskRecord[]> => []),
  listViralVideos: vi.fn(),
  listProjects: vi.fn(),
  listSimpleCharacterLibrary: vi.fn(),
  readAnalysisPayload: vi.fn(),
  cancelGenerationBatch: vi.fn(),
}));

vi.mock("../api", () => api);

import {
  cancelStudioTask,
  loadPersonAssets,
  loadProjectDraft,
  loadStudioData,
  loadTaskPreview,
} from "./live";
import type { StudioTask } from "./types";

const user: CurrentUser = {
  id: "user-1",
  username: "owner",
  display_name: "业主",
  role: "customer",
};

const project: Project = {
  id: "project-1",
  owner_user_id: "user-1",
  name: "三层新中式乡墅",
  status: "READY",
  reference_asset_id: "source-video-1",
  reference_upload_status: "READY",
  analysis_status: "READY",
};

const person: SimpleLibraryEntry = {
  identity_id: "person-1",
  display_name: "张工",
  owner_user_id: "user-1",
  status: "PUBLISHED",
  contact_sheet_asset_id: "sheet-1",
  generation_source: "image_provider",
  views: [
    { view_type: "FRONT_FACE", asset_id: "face-1" },
    { view_type: "FRONT_FULL", asset_id: "full-1" },
  ],
};

const batchPage = {
  next_cursor: null,
  items: [
    {
      id: "batch-1",
      project_id: "project-1",
      project_name: "三层新中式乡墅",
      created_by_user_id: "user-1",
      created_by_display_name: "业主",
      prompt_version_id: "prompt-1",
      status: "RUNNING",
      quantity: 2,
      created_at: "2026-09-05T09:30:00+08:00",
      updated_at: "2026-09-05T09:31:00+08:00",
      display_name: "庭院镜头生成",
      creation_kind: "replica",
      progress: {
        total_count: 2,
        terminal_count: 0,
        progress_percent: 37,
        counts: { RUNNING: 2 },
      },
      total_estimated_cost: null,
      total_actual_cost: null,
      needs_attention_count: 0,
      has_results: false,
      tasks: [],
    },
  ],
} as GenerationBatchListPage;

function generationTask(
  overrides: Partial<GenerationTask> = {},
): GenerationTask {
  return {
    id: "generation-task-1",
    status: "SUCCEEDED",
    archive_status: "ARCHIVED",
    quality_status: "PASSED",
    quality_issue_codes: [],
    result_asset_id: "result-1",
    direct_result_available: false,
    stage: "COMPLETED",
    provider: "minimax",
    model: "h3",
    provider_task_id_tail: "task-1",
    attempt: 1,
    archive_retry_count: 0,
    estimated_cost: null,
    actual_cost: null,
    error_code: null,
    error_message_redacted: null,
    submitted_at: "2026-09-05T09:30:00+08:00",
    started_at: "2026-09-05T09:30:10+08:00",
    completed_at: "2026-09-05T09:31:00+08:00",
    duration_seconds: 8,
    retry_of_task_id: null,
    superseded_by_task_id: null,
    superseded_at: null,
    retry_reason: null,
    retry_requested_at: null,
    available_actions: [],
    prompt_snapshot: null,
    ...overrides,
  };
}

function generationBatch(
  tasks: GenerationTask[],
  overrides: Partial<GenerationBatch> = {},
): GenerationBatch {
  return {
    id: "batch-1",
    project_id: "project-1",
    prompt_version_id: "prompt-1",
    status: "SUCCEEDED",
    quantity: tasks.length,
    stale: false,
    creation_kind: "replica",
    progress: {
      total_count: tasks.length,
      terminal_count: tasks.length,
      progress_percent: 100,
      counts: { succeeded: tasks.length },
    },
    tasks,
    ...overrides,
  };
}

const studioTask: StudioTask = {
  id: "batch-1",
  batchId: "batch-1",
  projectId: "project-1",
  title: "庭院镜头生成",
  type: "视频生成",
  status: "completed",
  submitted: "2026-09-05T09:30:00+08:00",
};

describe("真实 Studio 只读适配器", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.listProjects.mockResolvedValue([project]);
    api.listSimpleCharacterLibrary.mockResolvedValue([person]);
    api.listViralVideos.mockImplementation((platform: string) =>
      Promise.resolve({
        platform,
        sort: "hot",
        categories: [],
        items: [],
        fetchedAt: null,
      }),
    );
    api.listGenerationBatches.mockResolvedValue(batchPage);
    api.getAssetDownloadUrl.mockResolvedValue({ url: "https://signed/source" });
    api.getCachedCharacterAssetUrl.mockResolvedValue({
      url: "https://signed/character",
    });
    api.getLatestProjectAnalysis.mockResolvedValue({ id: "analysis-1" });
    api.createGenerationResultPreviewUrl.mockResolvedValue(
      "https://signed/result",
    );
    api.createGenerationTaskPreviewUrl.mockResolvedValue(
      "https://signed/direct",
    );
    api.readAnalysisPayload.mockReturnValue({
      summary: "预算拆解",
      duration_seconds: 42,
      original_script: "分析得到的原始口播。",
      shots: [],
    });
    api.getLatestScriptVersion.mockResolvedValue({
      stale: false,
      stale_reasons: [],
      version: {
        id: "script-version-3",
        project_id: "project-1",
        asset_id: null,
        kind: "script",
        version_number: 3,
        payload: { full_text: "已经保存的二创终稿。" },
        created_by_user_id: "user-1",
        created_at: "2026-09-05T09:00:00+08:00",
      },
    });
  });

  it("详情按需读取批次并优先预览成功的直出结果", async () => {
    api.getGenerationBatch.mockResolvedValue(
      generationBatch([
        generationTask({ id: "archived-first", result_asset_id: "asset-1" }),
        generationTask({
          id: "direct-second",
          result_asset_id: null,
          direct_result_available: true,
          archive_status: "NOT_ARCHIVED",
        }),
      ]),
    );

    const asset = await loadTaskPreview(studioTask);

    expect(api.getGenerationBatch).toHaveBeenCalledWith("batch-1");
    expect(api.createGenerationTaskPreviewUrl).toHaveBeenCalledWith(
      "direct-second",
    );
    expect(api.createGenerationResultPreviewUrl).not.toHaveBeenCalled();
    expect(asset).toEqual({
      id: "direct-task-direct-second",
      name: "庭院镜头生成 · 首个可用结果",
      kind: "video",
      url: "https://signed/direct",
      group: "任务结果",
      source: "任务中心",
      saved: false,
    });
  });

  it("没有直出结果时使用首个成功归档资产", async () => {
    api.getGenerationBatch.mockResolvedValue(
      generationBatch([
        generationTask({ status: "FAILED", result_asset_id: "failed-asset" }),
        generationTask({ id: "archived-ok", result_asset_id: "asset-ok" }),
      ]),
    );

    const asset = await loadTaskPreview(studioTask);

    expect(api.createGenerationResultPreviewUrl).toHaveBeenCalledWith(
      "asset-ok",
    );
    expect(api.createGenerationTaskPreviewUrl).not.toHaveBeenCalled();
    expect(asset).toMatchObject({
      id: "asset-ok",
      url: "https://signed/result",
      saved: true,
      source: "任务中心",
    });
  });

  it("无批次或批次无成功结果时返回空且不签发预览", async () => {
    await expect(
      loadTaskPreview({ ...studioTask, batchId: undefined }),
    ).resolves.toBeUndefined();
    expect(api.getGenerationBatch).not.toHaveBeenCalled();

    api.getGenerationBatch.mockResolvedValue(
      generationBatch([
        generationTask({
          status: "FAILED",
          result_asset_id: null,
          direct_result_available: false,
        }),
      ]),
    );
    await expect(loadTaskPreview(studioTask)).resolves.toBeUndefined();
    expect(api.createGenerationResultPreviewUrl).not.toHaveBeenCalled();
    expect(api.createGenerationTaskPreviewUrl).not.toHaveBeenCalled();
  });

  it("批次或签名请求失败时向上抛出以便界面明确重试", async () => {
    api.getGenerationBatch.mockRejectedValueOnce(new Error("batch timeout"));
    await expect(loadTaskPreview(studioTask)).rejects.toThrow("batch timeout");

    api.getGenerationBatch.mockResolvedValue(
      generationBatch([generationTask()]),
    );
    api.createGenerationResultPreviewUrl.mockRejectedValueOnce(
      new Error("sign timeout"),
    );
    await expect(loadTaskPreview(studioTask)).rejects.toThrow("sign timeout");
  });

  it("从真实分析与非过期脚本版本创建全新项目草稿", async () => {
    const result = await loadProjectDraft(project);

    expect(result.draft).toMatchObject({
      projectId: "project-1",
      sourceId: "source-video-1",
      script: {
        id: "script-version-3",
        title: "三层新中式乡墅",
        original: "分析得到的原始口播。",
        text: "已经保存的二创终稿。",
        version: 3,
        confirmed: false,
      },
    });
    expect(result.draft.id).toMatch(/^draft-/);
    expect(result.errors).toEqual([]);
  });

  it("没有保存版本时只把分析原文带入未确认的本地草稿", async () => {
    api.getLatestScriptVersion.mockResolvedValue({
      stale: false,
      stale_reasons: [],
      version: null,
    });

    const result = await loadProjectDraft(project);

    expect(result.draft.script).toMatchObject({
      title: "三层新中式乡墅",
      original: "分析得到的原始口播。",
      text: "分析得到的原始口播。",
      version: 1,
      confirmed: false,
    });
    expect(result.draft.script.id).toMatch(/^script-/);
  });

  it("分析未就绪时不请求无意义端点，脚本失败只返回新草稿和明确错误", async () => {
    api.getLatestScriptVersion.mockRejectedValue(new Error("script 404"));

    const result = await loadProjectDraft({
      ...project,
      analysis_status: "PENDING",
    });

    expect(api.getLatestProjectAnalysis).not.toHaveBeenCalled();
    expect(result.draft).toMatchObject({
      projectId: "project-1",
      sourceId: "source-video-1",
      script: { original: "", text: "", confirmed: false },
    });
    expect(result.errors).toEqual(["读取项目已保存文案失败：script 404"]);
  });

  it("过期或字段不明的脚本版本不作为终稿恢复", async () => {
    api.getLatestScriptVersion.mockResolvedValue({
      stale: true,
      stale_reasons: ["shot cards changed"],
      version: {
        id: "stale-script",
        version_number: 9,
        payload: { text: "不能猜成 full_text" },
      },
    });

    const result = await loadProjectDraft(project);

    expect(result.draft.script.id).toMatch(/^script-/);
    expect(result.draft.script).toMatchObject({
      original: "分析得到的原始口播。",
      text: "分析得到的原始口播。",
      version: 1,
      confirmed: false,
    });
  });

  it("映射项目、单张五视图合成图和真实批次进度", async () => {
    const data = await loadStudioData(user);

    expect(api.listGenerationBatches).toHaveBeenCalledWith({
      limit: 20,
    });
    expect(data.projects).toEqual([project]);
    expect(data.people).toHaveLength(1);
    expect(data.people[0]?.sheetId).toBe("sheet-1");
    expect(data.assets.filter((asset) => asset.composite)).toEqual([
      expect.objectContaining({
        id: "sheet-1",
        url: "https://signed/character",
      }),
    ]);
    expect(data.tasks).toEqual([
      expect.objectContaining({
        id: "batch-1",
        batchId: "batch-1",
        progress: 37,
        status: "running",
        title: "庭院镜头生成",
        type: "视频复刻",
      }),
    ]);
    expect(data.stats).toBeNull();
    expect(data.errors).toEqual([]);
  });

  it("基础工作区加载不等待爆款平台冷拉取", async () => {
    api.listViralVideos.mockReturnValue(new Promise(() => {}));

    const data = await loadStudioData(user);

    expect(data.projects).toEqual([project]);
    expect(data.loading).toBe(false);
    expect(data.videos).toEqual([]);
    expect(api.listViralVideos).not.toHaveBeenCalled();
  });

  it("部分成功且仍需处理的批次不会冒充已完成", async () => {
    api.listGenerationBatches.mockResolvedValue({
      ...batchPage,
      items: [
        {
          ...batchPage.items[0],
          status: "COMPLETED_WITH_FAILURES",
          needs_attention_count: 1,
          has_results: true,
          progress: {
            total_count: 2,
            terminal_count: 2,
            progress_percent: 100,
            counts: { SUCCEEDED: 1, FAILED: 1 },
          },
          tasks: [
            {
              id: "task-1",
              status: "SUCCEEDED",
              archive_status: "ARCHIVED",
              quality_status: "PASSED",
              quality_issue_codes: [],
              result_asset_id: "result-1",
              direct_result_available: true,
              stage: "COMPLETED",
              provider: "minimax",
              model: "h3",
              provider_task_id_tail: "task-1",
              attempt: 1,
              archive_retry_count: 0,
              estimated_cost: null,
              actual_cost: null,
              error_code: null,
              error_message_redacted: null,
              submitted_at: "2026-09-05T09:30:00+08:00",
              started_at: "2026-09-05T09:30:10+08:00",
              completed_at: "2026-09-05T09:31:00+08:00",
              duration_seconds: 8,
              retry_of_task_id: null,
              superseded_by_task_id: null,
              superseded_at: null,
              retry_reason: null,
              retry_requested_at: null,
              available_actions: [],
            },
          ],
        },
      ],
    } satisfies GenerationBatchListPage);

    const data = await loadStudioData(user);

    expect(data.tasks).toEqual([
      expect.objectContaining({
        id: "batch-1",
        status: "failed",
        progress: 100,
        resultId: "result-1",
      }),
    ]);
  });

  it("局部API失败时保留其他真实数据并记录明确错误", async () => {
    api.listProjects.mockRejectedValue(new Error("project timeout"));
    api.listGenerationBatches.mockRejectedValue(new Error("batch timeout"));

    const data = await loadStudioData(user);

    expect(data.projects).toEqual([]);
    expect(data.people).toHaveLength(1);
    expect(data.tasks).toEqual([]);
    expect(data.errors).toEqual([
      "读取项目失败：project timeout",
      "读取任务失败：batch timeout",
    ]);
  });

  it("所有主列表失败时返回可识别空态，不回退审核夹具", async () => {
    api.listProjects.mockRejectedValue(new Error("projects unavailable"));
    api.listSimpleCharacterLibrary.mockRejectedValue(
      new Error("people unavailable"),
    );
    api.listGenerationBatches.mockRejectedValue(new Error("tasks unavailable"));

    const data = await loadStudioData(user);

    expect(data).toMatchObject({
      projects: [],
      people: [],
      assets: [],
      tasks: [],
      videos: [],
      loading: false,
    });
    expect(data.errors).toHaveLength(3);
  });

  it("限制首页数量及签名预览请求，避免无界N+1", async () => {
    api.listProjects.mockResolvedValue(
      Array.from({ length: 30 }, (_, index) => ({
        ...project,
        id: `project-${index}`,
        name: `项目${index}`,
        reference_asset_id: `source-${index}`,
      })),
    );
    api.listSimpleCharacterLibrary.mockResolvedValue(
      Array.from({ length: 20 }, (_, index) => ({
        ...person,
        identity_id: `person-${index}`,
        display_name: `人物${index}`,
        contact_sheet_asset_id: `sheet-${index}`,
        views: [{ view_type: "FRONT_FACE", asset_id: `face-${index}` }],
      })),
    );

    const data = await loadStudioData(user);

    expect(data.projects).toHaveLength(24);
    expect(data.people).toHaveLength(8);
    expect(api.getAssetDownloadUrl).toHaveBeenCalledTimes(8);
    expect(api.getCachedCharacterAssetUrl).toHaveBeenCalledTimes(16);
  });

  it("场景形象照每个场景只取一张正面预览，不展开成五张", async () => {
    const scene: SimpleSceneLook = {
      identity_id: "person-1",
      persona_id: "persona-scene-1",
      character_version_id: "version-scene-1",
      scene_name: "设计室讲解",
      scene_description: "乡墅方案桌前讲解",
      costume_description: "深色西装",
      contact_sheet_asset_id: "scene-sheet-1",
      generation_source: "image_provider",
      views: [
        { view_type: "LEFT_SIDE", asset_id: "scene-left" },
        { view_type: "FRONT_FACE", asset_id: "scene-front" },
        { view_type: "FRONT_FULL", asset_id: "scene-full" },
      ],
    };
    api.listCharacterSceneLooks.mockResolvedValue([scene]);
    api.getCachedCharacterAssetUrl.mockResolvedValue({
      url: "https://signed/scene-front",
    });

    const result = await loadPersonAssets("person-1");

    expect(api.getCachedCharacterAssetUrl).toHaveBeenCalledTimes(1);
    expect(api.getCachedCharacterAssetUrl).toHaveBeenCalledWith("scene-front");
    expect(result.assets).toEqual([
      expect.objectContaining({
        id: "scene-front",
        name: "设计室讲解",
        composite: false,
        personId: "person-1",
        url: "https://signed/scene-front",
      }),
    ]);
    expect(result.errors).toEqual([]);
  });

  it("场景预览签名失败仍保留资产身份并报告错误", async () => {
    api.listCharacterSceneLooks.mockResolvedValue([
      {
        identity_id: "person-1",
        persona_id: "persona-1",
        character_version_id: "version-1",
        scene_name: "庭院讲解",
        scene_description: "庭院",
        costume_description: "西装",
        contact_sheet_asset_id: "scene-sheet",
        generation_source: "image_provider",
        views: [{ view_type: "FRONT_FACE", asset_id: "scene-front" }],
      } satisfies SimpleSceneLook,
    ]);
    api.getCachedCharacterAssetUrl.mockRejectedValue(new Error("sign failed"));

    const result = await loadPersonAssets("person-1");

    expect(result.assets).toEqual([
      expect.objectContaining({ id: "scene-front", url: undefined }),
    ]);
    expect(result.errors).toEqual(["读取场景图片“庭院讲解”失败：sign failed"]);
  });
});

describe("批次类型映射与取消", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.listProjects.mockResolvedValue([]);
    api.listSimpleCharacterLibrary.mockResolvedValue([]);
    api.listOralTasks.mockResolvedValue([]);
    api.getStudioStats.mockResolvedValue(null);
  });

  it("类型按 creation_kind 映射，未知通道回退视频生成", async () => {
    api.listGenerationBatches.mockResolvedValue({
      next_cursor: null,
      items: [
        { ...batchPage.items[0], creation_kind: "replica" },
        {
          ...batchPage.items[0],
          id: "batch-future",
          display_name: "未知通道批次",
          creation_kind: "future_kind",
        },
      ],
    });

    const data = await loadStudioData(user);

    expect(data.tasks.map((task) => task.type)).toEqual([
      "视频复刻",
      "视频生成",
    ]);
  });

  it("取消排队批次调用服务端取消接口", async () => {
    api.cancelGenerationBatch.mockResolvedValue(undefined);
    await cancelStudioTask({
      id: "batch-1",
      batchId: "batch-1",
      title: "排队批次",
      type: "视频复刻",
      status: "queued",
      submitted: "2026-09-06T09:32:00",
    });
    expect(api.cancelGenerationBatch).toHaveBeenCalledWith("batch-1");
  });

  it("口播排队任务明确不可取消且提交不确定映射为待确认", async () => {
    api.listGenerationBatches.mockResolvedValue({ ...batchPage, items: [] });
    api.listOralTasks.mockResolvedValue([
      {
        id: "oral-queued",
        status: "QUEUED",
        title: "排队口播",
        mode: "TTS",
        identity_id: "person-1",
        avatar_id: "avatar-1",
        voice_id: "voice-1",
        script_text: "建房预算讲解",
        audio_asset_id: null,
        result_asset_id: null,
        duration_sec: null,
        estimated_cost_fen: 100,
        created_at: "2026-09-06T09:32:00",
        updated_at: "2026-09-06T09:32:00",
      },
      {
        id: "oral-uncertain",
        status: "SUBMISSION_UNCERTAIN",
        title: "待核对口播",
        mode: "AUDIO",
        identity_id: "person-1",
        avatar_id: "avatar-1",
        voice_id: null,
        script_text: null,
        audio_asset_id: "audio-1",
        status_message: "供应商提交结果待核对",
        result_asset_id: null,
        duration_sec: null,
        estimated_cost_fen: 100,
        created_at: "2026-09-06T09:33:00",
        updated_at: "2026-09-06T09:33:00",
      },
    ]);

    const data = await loadStudioData(user);

    expect(data.tasks).toEqual([
      expect.objectContaining({
        id: "oral-oral-queued",
        status: "queued",
        cancelAllowed: false,
      }),
      expect.objectContaining({
        id: "oral-oral-uncertain",
        status: "uncertain",
        cancelAllowed: false,
      }),
    ]);
  });

  it("口播任务即使误触取消适配器也不会调用批次取消接口", async () => {
    await expect(
      cancelStudioTask({
        id: "oral-1",
        title: "排队口播",
        type: "数字人口播",
        status: "queued",
        cancelAllowed: false,
        submitted: "2026-09-06T09:32:00",
      }),
    ).rejects.toThrow("当前任务不支持取消");
    expect(api.cancelGenerationBatch).not.toHaveBeenCalled();
  });
});
