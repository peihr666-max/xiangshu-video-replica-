import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  CurrentUser,
  GenerationBatch,
  GenerationBatchListPage,
  GenerationTask,
  OralAvatarRecord,
  OralTaskRecord,
  OralVoiceRecord,
  Project,
  ScriptFromAudioTask,
  SimpleLibraryEntry,
  SimpleSceneLook,
} from "../api";

const api = vi.hoisted(() => ({
  createScriptFromAudioTask:
    vi.fn<
      (
        projectId: string,
        assetId: string,
        idempotencyKey: string,
      ) => Promise<ScriptFromAudioTask>
    >(),
  createGenerationResultPreviewUrl: vi.fn(),
  createGenerationTaskPreviewUrl: vi.fn(),
  getAssetDownloadUrl: vi.fn(),
  getCachedCharacterAssetUrl: vi.fn(),
  getGenerationBatch: vi.fn(),
  getLatestProjectAnalysis: vi.fn(),
  getStudioStats: vi.fn(async () => null),
  getLatestScriptVersion: vi.fn(),
  getLatestScriptFromAudioTask:
    vi.fn<() => Promise<ScriptFromAudioTask | null>>(),
  getScriptFromAudioTask: vi.fn<() => Promise<ScriptFromAudioTask>>(),
  listCharacterSceneLooks: vi.fn(),
  listGenerationBatches: vi.fn(),
  listOralAvatars: vi.fn<() => Promise<OralAvatarRecord[]>>(async () => []),
  listOralTasks: vi.fn(async (): Promise<OralTaskRecord[]> => []),
  listOralVoices: vi.fn<() => Promise<OralVoiceRecord[]>>(async () => []),
  listViralVideos: vi.fn(),
  listProjects: vi.fn(),
  listSimpleCharacterLibrary: vi.fn(),
  readAnalysisPayload: vi.fn(),
  cancelGenerationBatch: vi.fn(),
}));

vi.mock("../api", () => api);

import {
  cancelStudioTask,
  extractScriptFromUpload,
  loadPersonAssets,
  loadProjectDraft,
  loadStudioData,
  loadTaskPreview,
  reloadTasks,
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

function scriptFromAudioTask(
  overrides: Partial<ScriptFromAudioTask> = {},
): ScriptFromAudioTask {
  return {
    id: "script-task-own",
    project_id: "project-1",
    status: "PENDING",
    attempt: 0,
    result: null,
    error_code: null,
    error_message: null,
    retryable: false,
    recovery_mode: null,
    ...overrides,
  };
}

describe("真实 Studio 只读适配器", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.listProjects.mockResolvedValue([project]);
    api.listSimpleCharacterLibrary.mockResolvedValue([person]);
    api.listOralAvatars.mockResolvedValue([]);
    api.listOralVoices.mockResolvedValue([]);
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

  it("把当前账号人物的已归档口播分身和音色映射为可预览档案", async () => {
    api.listOralAvatars.mockResolvedValue([
      {
        id: "avatar-ready",
        identity_id: "person-1",
        title: "张工讲解分身",
        status: "READY",
        source_kind: "VIDEO",
        source_asset_id: "avatar-source-1",
      },
    ]);
    api.listOralVoices.mockResolvedValue([
      {
        id: "voice-ready",
        identity_id: "person-1",
        title: "张工本人音色",
        status: "READY",
        demo_asset_id: "voice-demo-1",
        confirmed: true,
      },
      {
        id: "voice-pending",
        identity_id: "person-1",
        title: "张工待确认音色",
        status: "READY",
        demo_asset_id: "voice-demo-2",
        confirmed: false,
      },
    ]);
    api.getAssetDownloadUrl.mockImplementation(async (assetId: string) => ({
      url: `https://signed/${assetId}`,
    }));

    const data = await loadStudioData(user);

    expect(api.listOralAvatars).toHaveBeenCalledWith("person-1");
    expect(api.listOralVoices).toHaveBeenCalledWith("person-1");
    expect(data.people[0]).toMatchObject({
      avatars: [
        {
          id: "avatar-ready",
          name: "张工讲解分身",
          imageId: "avatar-source-1",
          ready: true,
          origin: "视频制作",
        },
      ],
      voices: [
        {
          id: "voice-ready",
          name: "张工本人音色",
          confirmed: true,
          url: "https://signed/voice-demo-1",
        },
        {
          id: "voice-pending",
          name: "张工待确认音色",
          confirmed: false,
          url: "https://signed/voice-demo-2",
        },
      ],
    });
    expect(data.assets).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "avatar-source-1",
          personId: "person-1",
          kind: "video",
          url: "https://signed/avatar-source-1",
        }),
        expect.objectContaining({
          id: "voice-demo-1",
          personId: "person-1",
          kind: "audio",
          url: "https://signed/voice-demo-1",
        }),
        expect.objectContaining({
          id: "voice-demo-2",
          personId: "person-1",
          kind: "audio",
          url: "https://signed/voice-demo-2",
        }),
      ]),
    );
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
      {
        id: "oral-submitting",
        status: "SUBMITTING",
        title: "供应商提交中的口播",
        mode: "TTS",
        identity_id: "person-1",
        avatar_id: "avatar-1",
        voice_id: "voice-1",
        script_text: "建房成本讲解",
        audio_asset_id: null,
        status_message: "正在提交供应商",
        result_asset_id: null,
        duration_sec: null,
        estimated_cost_fen: 100,
        created_at: "2026-09-06T09:34:00",
        updated_at: "2026-09-06T09:34:00",
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
      expect.objectContaining({
        id: "oral-oral-submitting",
        status: "running",
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

  it("任务轮询同时返回生成批次与口播任务", async () => {
    api.listGenerationBatches.mockResolvedValue(batchPage);
    api.listOralTasks.mockResolvedValue([
      {
        id: "oral-poll-1",
        status: "RUNNING",
        title: "轮询口播",
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
        updated_at: "2026-09-06T09:33:00",
      },
    ]);

    const tasks = await reloadTasks(user);

    expect(tasks.map((task) => task.id)).toEqual([
      "batch-1",
      "oral-oral-poll-1",
    ]);
  });
});

describe("文案提取任务身份绑定", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    window.localStorage.clear();
    vi.spyOn(window, "setTimeout").mockImplementation((handler) => {
      if (typeof handler === "function") handler();
      return 1;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("另一标签页任务先完成时仍只读取本次创建任务的文案", async () => {
    const own = scriptFromAudioTask();
    const other = scriptFromAudioTask({
      id: "script-task-other",
      status: "SUCCEEDED",
      result: { text: "另一标签页文案", duration_sec: 12, language: "zh" },
    });
    api.createScriptFromAudioTask.mockResolvedValue(own);
    api.getLatestScriptFromAudioTask.mockResolvedValue(other);
    api.getScriptFromAudioTask.mockResolvedValueOnce(own).mockResolvedValueOnce(
      scriptFromAudioTask({
        status: "SUCCEEDED",
        result: { text: "本次草稿文案", duration_sec: 10, language: "zh" },
      }),
    );

    await expect(
      extractScriptFromUpload("user-1", "project-1", "asset-1"),
    ).resolves.toEqual({ text: "本次草稿文案" });
    expect(api.getScriptFromAudioTask).toHaveBeenCalledTimes(2);
    expect(api.getScriptFromAudioTask).toHaveBeenNthCalledWith(
      1,
      "script-task-own",
    );
    expect(api.getScriptFromAudioTask).toHaveBeenNthCalledWith(
      2,
      "script-task-own",
    );
    expect(api.getLatestScriptFromAudioTask).not.toHaveBeenCalled();
  });

  it("另一标签页任务失败时不会把它的错误写成本次任务错误", async () => {
    const own = scriptFromAudioTask();
    api.createScriptFromAudioTask.mockResolvedValue(own);
    api.getLatestScriptFromAudioTask.mockResolvedValue(
      scriptFromAudioTask({
        id: "script-task-other",
        status: "FAILED",
        error_message: "另一标签页失败",
      }),
    );
    api.getScriptFromAudioTask.mockResolvedValue(
      scriptFromAudioTask({
        status: "FAILED",
        error_message: "本次任务失败",
      }),
    );

    await expect(
      extractScriptFromUpload("user-1", "project-1", "asset-1"),
    ).rejects.toThrow("本次任务失败");
    expect(api.getScriptFromAudioTask).toHaveBeenCalledWith("script-task-own");
    expect(api.getLatestScriptFromAudioTask).not.toHaveBeenCalled();
  });

  it("自动恢复的提交不确定任务会继续轮询并应用最终文案", async () => {
    api.createScriptFromAudioTask.mockResolvedValue(scriptFromAudioTask());
    api.getScriptFromAudioTask
      .mockResolvedValueOnce(
        scriptFromAudioTask({
          status: "SUBMISSION_UNCERTAIN",
          recovery_mode: "AUTO",
          error_message: "正在自动核对供应商任务",
        }),
      )
      .mockResolvedValueOnce(
        scriptFromAudioTask({
          status: "SUCCEEDED",
          recovery_mode: null,
          result: {
            text: "自动恢复后的最终文案",
            duration_sec: 9,
            language: "zh",
          },
        }),
      );

    await expect(
      extractScriptFromUpload("user-1", "project-1", "asset-1"),
    ).resolves.toEqual({ text: "自动恢复后的最终文案" });
    expect(api.getScriptFromAudioTask).toHaveBeenCalledTimes(2);
  });

  it("需要人工对账的提交不确定任务停止轮询并给出明确提示", async () => {
    api.createScriptFromAudioTask.mockResolvedValue(scriptFromAudioTask());
    api.getScriptFromAudioTask.mockResolvedValue(
      scriptFromAudioTask({
        status: "SUBMISSION_UNCERTAIN",
        recovery_mode: "ADMIN_REQUIRED",
        error_message: "供应商任务身份无法自动确认",
      }),
    );

    await expect(
      extractScriptFromUpload("user-1", "project-1", "asset-1"),
    ).rejects.toThrow("需要管理员对账");
    expect(api.getScriptFromAudioTask).toHaveBeenCalledTimes(1);
  });

  it("提交响应丢失后重试复用持久化幂等键", async () => {
    api.createScriptFromAudioTask
      .mockRejectedValueOnce(new TypeError("network unavailable"))
      .mockResolvedValueOnce(scriptFromAudioTask());
    api.getScriptFromAudioTask.mockResolvedValue(
      scriptFromAudioTask({
        status: "SUCCEEDED",
        result: { text: "恢复后的文案", duration_sec: 8, language: "zh" },
      }),
    );

    await expect(
      extractScriptFromUpload("user-1", "project-1", "asset-1"),
    ).rejects.toThrow("network unavailable");
    await expect(
      extractScriptFromUpload("user-1", "project-1", "asset-1"),
    ).resolves.toEqual({ text: "恢复后的文案" });

    expect(api.createScriptFromAudioTask).toHaveBeenCalledTimes(2);
    expect(api.createScriptFromAudioTask.mock.calls[1]?.[2]).toBe(
      api.createScriptFromAudioTask.mock.calls[0]?.[2],
    );
  });

  it("页面重载后恢复存储不可读时阻止新建任务", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    await expect(
      extractScriptFromUpload("user-fresh-blocked", "project-1", "asset-1"),
    ).rejects.toThrow("无法读取文案提取恢复状态");
    expect(api.createScriptFromAudioTask).not.toHaveBeenCalled();
  });

  it("首次恢复记录持久化失败时不创建音频转文案任务", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });

    await expect(
      extractScriptFromUpload("user-quota-first", "project-1", "asset-1"),
    ).rejects.toThrow("无法保存文案提取恢复状态");
    expect(api.createScriptFromAudioTask).not.toHaveBeenCalled();
    expect(api.getScriptFromAudioTask).not.toHaveBeenCalled();
  });

  it("仅 removeItem 失败时终态仍允许下一次新建", async () => {
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    api.createScriptFromAudioTask
      .mockResolvedValueOnce(scriptFromAudioTask())
      .mockResolvedValueOnce(scriptFromAudioTask({ id: "remove-task-new" }));
    api.getScriptFromAudioTask
      .mockResolvedValueOnce(
        scriptFromAudioTask({ status: "FAILED", error_message: "音频无效" }),
      )
      .mockResolvedValueOnce(
        scriptFromAudioTask({
          id: "remove-task-new",
          status: "SUCCEEDED",
          result: {
            text: "删除失败后的新文案",
            duration_sec: 8,
            language: "zh",
          },
        }),
      );

    await expect(
      extractScriptFromUpload("user-remove-fail", "project-1", "asset-1"),
    ).rejects.toThrow("音频无效");
    await expect(
      extractScriptFromUpload("user-remove-fail", "project-1", "asset-1"),
    ).resolves.toEqual({ text: "删除失败后的新文案" });

    expect(api.createScriptFromAudioTask).toHaveBeenCalledTimes(2);
    expect(api.createScriptFromAudioTask.mock.calls[1]?.[2]).not.toBe(
      api.createScriptFromAudioTask.mock.calls[0]?.[2],
    );
  });

  it("页面重载留下任务 ID 时只恢复轮询而不重复提交", async () => {
    window.localStorage.setItem(
      'studio.scriptFromAudioAttempt:["user-1","project-1","asset-1"]',
      JSON.stringify({
        version: 1,
        accountId: "user-1",
        projectId: "project-1",
        assetId: "asset-1",
        idempotencyKey: "persisted-key",
        taskId: "persisted-task",
      }),
    );
    api.getScriptFromAudioTask.mockResolvedValue(
      scriptFromAudioTask({
        id: "persisted-task",
        status: "SUCCEEDED",
        result: { text: "重载恢复文案", duration_sec: 7, language: "zh" },
      }),
    );

    await expect(
      extractScriptFromUpload("user-1", "project-1", "asset-1"),
    ).resolves.toEqual({ text: "重载恢复文案" });

    expect(api.createScriptFromAudioTask).not.toHaveBeenCalled();
    expect(api.getScriptFromAudioTask).toHaveBeenCalledWith("persisted-task");
  });

  it("持久任务明确不存在时清除记录并允许下一次新建", async () => {
    window.localStorage.setItem(
      'studio.scriptFromAudioAttempt:["user-missing","project-1","asset-1"]',
      JSON.stringify({
        version: 1,
        accountId: "user-missing",
        projectId: "project-1",
        assetId: "asset-1",
        idempotencyKey: "missing-task-key",
        taskId: "missing-task",
      }),
    );
    api.getScriptFromAudioTask
      .mockRejectedValueOnce(
        Object.assign(new Error("提取任务不存在"), {
          status: 404,
          code: "SCRIPT_FROM_AUDIO_TASK_NOT_FOUND",
          retryable: false,
        }),
      )
      .mockResolvedValueOnce(
        scriptFromAudioTask({
          id: "replacement-task",
          status: "SUCCEEDED",
          result: { text: "新建任务文案", duration_sec: 7, language: "zh" },
        }),
      );
    api.createScriptFromAudioTask.mockResolvedValue(
      scriptFromAudioTask({ id: "replacement-task" }),
    );

    await expect(
      extractScriptFromUpload("user-missing", "project-1", "asset-1"),
    ).rejects.toThrow("提取任务不存在");
    await expect(
      extractScriptFromUpload("user-missing", "project-1", "asset-1"),
    ).resolves.toEqual({ text: "新建任务文案" });

    expect(api.createScriptFromAudioTask).toHaveBeenCalledTimes(1);
    expect(api.createScriptFromAudioTask.mock.calls[0]?.[2]).not.toBe(
      "missing-task-key",
    );
  });

  it.each([
    new TypeError("network unavailable"),
    Object.assign(new Error("request timeout"), { status: 408 }),
    Object.assign(new Error("too early"), { status: 425 }),
    Object.assign(new Error("rate limited"), { status: 429 }),
    Object.assign(new Error("gateway unavailable"), { status: 503 }),
  ])("持久任务轮询遇不确定错误时保留任务 ID", async (cause) => {
    window.localStorage.setItem(
      'studio.scriptFromAudioAttempt:["user-retry","project-1","asset-1"]',
      JSON.stringify({
        version: 1,
        accountId: "user-retry",
        projectId: "project-1",
        assetId: "asset-1",
        idempotencyKey: "retry-task-key",
        taskId: "retry-task",
      }),
    );
    api.getScriptFromAudioTask
      .mockRejectedValueOnce(cause)
      .mockResolvedValueOnce(
        scriptFromAudioTask({
          id: "retry-task",
          status: "SUCCEEDED",
          result: { text: "继续轮询文案", duration_sec: 7, language: "zh" },
        }),
      );

    await expect(
      extractScriptFromUpload("user-retry", "project-1", "asset-1"),
    ).rejects.toThrow();
    await expect(
      extractScriptFromUpload("user-retry", "project-1", "asset-1"),
    ).resolves.toEqual({ text: "继续轮询文案" });

    expect(api.createScriptFromAudioTask).not.toHaveBeenCalled();
    expect(api.getScriptFromAudioTask).toHaveBeenNthCalledWith(2, "retry-task");
  });

  it("轮询超时后再次点击继续读取原任务", async () => {
    api.createScriptFromAudioTask.mockResolvedValue(scriptFromAudioTask());
    api.getScriptFromAudioTask.mockResolvedValue(
      scriptFromAudioTask({ status: "RUNNING" }),
    );

    await expect(
      extractScriptFromUpload("user-1", "project-1", "asset-1"),
    ).rejects.toThrow("超时");
    api.getScriptFromAudioTask.mockResolvedValue(
      scriptFromAudioTask({
        status: "SUCCEEDED",
        result: { text: "超时后恢复", duration_sec: 9, language: "zh" },
      }),
    );
    await expect(
      extractScriptFromUpload("user-1", "project-1", "asset-1"),
    ).resolves.toEqual({ text: "超时后恢复" });

    expect(api.createScriptFromAudioTask).toHaveBeenCalledTimes(1);
    expect(api.getScriptFromAudioTask).toHaveBeenLastCalledWith(
      "script-task-own",
    );
  });

  it("明确失败后新尝试轮换幂等键", async () => {
    api.createScriptFromAudioTask
      .mockResolvedValueOnce(scriptFromAudioTask())
      .mockResolvedValueOnce(scriptFromAudioTask({ id: "script-task-new" }));
    api.getScriptFromAudioTask
      .mockResolvedValueOnce(
        scriptFromAudioTask({ status: "FAILED", error_message: "音频无效" }),
      )
      .mockResolvedValueOnce(
        scriptFromAudioTask({
          id: "script-task-new",
          status: "SUCCEEDED",
          result: { text: "新尝试文案", duration_sec: 6, language: "zh" },
        }),
      );

    await expect(
      extractScriptFromUpload("user-1", "project-1", "asset-1"),
    ).rejects.toThrow("音频无效");
    await expect(
      extractScriptFromUpload("user-1", "project-1", "asset-1"),
    ).resolves.toEqual({ text: "新尝试文案" });

    expect(api.createScriptFromAudioTask.mock.calls[1]?.[2]).not.toBe(
      api.createScriptFromAudioTask.mock.calls[0]?.[2],
    );
  });

  it("创建阶段明确未受理后新尝试轮换幂等键", async () => {
    api.createScriptFromAudioTask
      .mockRejectedValueOnce(
        Object.assign(new Error("素材不属于当前项目"), {
          status: 422,
          retryable: false,
        }),
      )
      .mockResolvedValueOnce(scriptFromAudioTask());
    api.getScriptFromAudioTask.mockResolvedValue(
      scriptFromAudioTask({
        status: "SUCCEEDED",
        result: { text: "修正后的文案", duration_sec: 6, language: "zh" },
      }),
    );

    await expect(
      extractScriptFromUpload("user-1", "project-1", "asset-1"),
    ).rejects.toThrow("素材不属于当前项目");
    await expect(
      extractScriptFromUpload("user-1", "project-1", "asset-1"),
    ).resolves.toEqual({ text: "修正后的文案" });

    expect(api.createScriptFromAudioTask.mock.calls[1]?.[2]).not.toBe(
      api.createScriptFromAudioTask.mock.calls[0]?.[2],
    );
  });

  it("不同账号对同一项目素材使用隔离的提取尝试", async () => {
    api.createScriptFromAudioTask
      .mockResolvedValueOnce(scriptFromAudioTask())
      .mockResolvedValueOnce(scriptFromAudioTask({ id: "task-user-2" }));
    api.getScriptFromAudioTask
      .mockResolvedValueOnce(
        scriptFromAudioTask({
          status: "SUCCEEDED",
          result: { text: "账号一文案", duration_sec: 5, language: "zh" },
        }),
      )
      .mockResolvedValueOnce(
        scriptFromAudioTask({
          id: "task-user-2",
          status: "SUCCEEDED",
          result: { text: "账号二文案", duration_sec: 5, language: "zh" },
        }),
      );

    await extractScriptFromUpload("user-1", "project-1", "asset-1");
    await extractScriptFromUpload("user-2", "project-1", "asset-1");

    expect(api.createScriptFromAudioTask).toHaveBeenCalledTimes(2);
    expect(api.createScriptFromAudioTask.mock.calls[1]?.[2]).not.toBe(
      api.createScriptFromAudioTask.mock.calls[0]?.[2],
    );
  });
});
