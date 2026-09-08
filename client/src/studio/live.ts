import {
  type CurrentUser,
  cancelGenerationBatch,
  completeVideoUpload,
  createGenerationResultPreviewUrl,
  createGenerationTaskPreviewUrl,
  createProject,
  createScriptFromAudioTask,
  createScriptVersion,
  createVideoUploadIntent,
  type GenerationBatchListItem,
  getAssetDownloadUrl,
  getCachedCharacterAssetUrl,
  getGenerationBatch,
  getLatestProjectAnalysis,
  getLatestProjectShotCards,
  getLatestScriptVersion,
  getScriptFromAudioTask,
  getStudioDraft,
  getStudioStats,
  listCharacterSceneLooks,
  listGenerationBatches,
  listOralAvatars,
  listOralTasks,
  listOralVoices,
  listProjects,
  listSimpleCharacterLibrary,
  listStudioSavedScripts,
  type OralTaskRecord,
  type Project,
  readAnalysisPayload,
  type ScriptFromAudioTask,
  type SimpleLibraryEntry,
  type StudioDraftKind,
  type StudioSavedScriptInput,
  saveStudioDraft,
  saveStudioSavedScript,
  uploadReferenceVideo,
  type ViralVideoItem,
} from "../api";
import { createDraft } from "./state";
import type {
  StudioAsset,
  StudioData,
  StudioDraft,
  StudioPerson,
  StudioScript,
  StudioStats,
  StudioTask,
  StudioVideo,
} from "./types";

const projectLimit = 24;
const personLimit = 8;
const projectPreviewLimit = 8;
const sceneLimit = 12;

function errorText(error: unknown) {
  return error instanceof Error && error.message.trim()
    ? error.message.trim()
    : "未知错误";
}

export async function loadTaskPreview(
  task: StudioTask,
): Promise<StudioAsset | undefined> {
  // 数字人口播任务没有生成批次：成片按平台资产直取签名地址。
  if (!task.batchId && task.resultId) {
    const url = (await getAssetDownloadUrl(task.resultId)).url;
    return {
      id: task.resultId,
      name: `${task.title} · 成片`,
      kind: "video",
      url,
      group: "任务结果",
      source: "任务中心",
      saved: true,
    };
  }
  if (!task.batchId) return undefined;

  const batch = await getGenerationBatch(task.batchId);
  const successful = batch.tasks.filter(
    (result) =>
      result.status === "SUCCEEDED" &&
      (result.direct_result_available || Boolean(result.result_asset_id)),
  );
  const result =
    successful.find((candidate) => candidate.direct_result_available) ??
    successful[0];
  if (!result) return undefined;

  const direct = result.direct_result_available;
  const assetId = result.result_asset_id;
  const url = direct
    ? await createGenerationTaskPreviewUrl(result.id)
    : await createGenerationResultPreviewUrl(assetId as string);
  return {
    id: direct ? `direct-task-${result.id}` : (assetId as string),
    name: `${task.title} · 首个可用结果`,
    kind: "video",
    url,
    group: "任务结果",
    source: "任务中心",
    saved: !direct,
  };
}

export async function loadProjectDraft(
  project: Project,
): Promise<{ draft: StudioDraft; errors: string[] }> {
  const draft = createDraft();
  draft.projectId = project.id;
  draft.sourceId = project.reference_asset_id ?? undefined;
  draft.script.title = project.name;

  const [analysisResult, scriptResult] = await Promise.allSettled([
    project.analysis_status === "READY"
      ? getLatestProjectAnalysis(project.id)
      : Promise.resolve(undefined),
    getLatestScriptVersion(project.id),
  ]);
  const errors: string[] = [];
  let original = "";

  if (analysisResult.status === "rejected") {
    errors.push(`读取项目拆解结果失败：${errorText(analysisResult.reason)}`);
  } else if (analysisResult.value) {
    original = readAnalysisPayload(analysisResult.value)?.original_script ?? "";
  }

  draft.script.original = original;
  draft.script.text = original;
  if (scriptResult.status === "rejected") {
    errors.push(`读取项目已保存文案失败：${errorText(scriptResult.reason)}`);
  } else {
    const state = scriptResult.value;
    const fullText = state.version?.payload.full_text;
    if (!state.stale && state.version && typeof fullText === "string") {
      draft.script.id = state.version.id;
      draft.script.text = fullText;
      draft.script.version = state.version.version_number;
    }
  }
  draft.script.confirmed = false;

  return { draft, errors };
}

async function signedUrl(
  assetId: string,
  loader: (id: string) => Promise<{ url: string }>,
): Promise<string | undefined> {
  return (await loader(assetId)).url || undefined;
}

function projectAsset(project: Project, url?: string): StudioAsset | undefined {
  if (!project.reference_asset_id) return undefined;
  return {
    id: project.reference_asset_id,
    name: `${project.name} · 来源视频`,
    kind: "video",
    url,
    group: project.name,
    source: "项目上传",
    saved: project.reference_upload_status === "READY",
  };
}

async function loadProjects(): Promise<{
  projects: Project[];
  assets: StudioAsset[];
  errors: string[];
}> {
  const projects = (await listProjects()).slice(0, projectLimit);
  const previewProjects = projects
    .filter((project) => project.reference_asset_id)
    .slice(0, projectPreviewLimit);
  const previews = await Promise.allSettled(
    previewProjects.map(async (project) => ({
      project,
      url: await signedUrl(
        project.reference_asset_id as string,
        getAssetDownloadUrl,
      ),
    })),
  );
  const previewUrls = new Map<string, string | undefined>();
  const errors: string[] = [];
  previews.forEach((result, index) => {
    const project = previewProjects[index];
    if (!project?.reference_asset_id) return;
    if (result.status === "fulfilled") {
      previewUrls.set(project.reference_asset_id, result.value.url);
    } else {
      errors.push(
        `读取项目预览“${project.name}”失败：${errorText(result.reason)}`,
      );
    }
  });
  const assets = projects
    .map((project) =>
      projectAsset(
        project,
        project.reference_asset_id
          ? previewUrls.get(project.reference_asset_id)
          : undefined,
      ),
    )
    .filter((asset): asset is StudioAsset => Boolean(asset));
  return { projects, assets, errors };
}

function basePerson(
  entry: SimpleLibraryEntry,
  portrait?: string,
): StudioPerson {
  return {
    id: entry.identity_id,
    name: entry.display_name,
    role: "",
    portrait,
    version: 0,
    scope: "",
    audience: "",
    expression: "",
    sheetId: entry.contact_sheet_asset_id ?? undefined,
    photoIds: [],
    avatars: [],
    voices: [],
  };
}

async function loadPeople(): Promise<{
  people: StudioPerson[];
  assets: StudioAsset[];
  errors: string[];
}> {
  const entries = (await listSimpleCharacterLibrary()).slice(0, personLimit);
  const errors: string[] = [];
  const people: StudioPerson[] = [];
  const assets: StudioAsset[] = [];

  for (const entry of entries) {
    const face =
      entry.views.find((view) => view.view_type === "FRONT_FACE") ??
      entry.views[0];
    const requests = await Promise.allSettled([
      face
        ? signedUrl(face.asset_id, getCachedCharacterAssetUrl)
        : Promise.resolve(undefined),
      entry.contact_sheet_asset_id
        ? signedUrl(entry.contact_sheet_asset_id, getCachedCharacterAssetUrl)
        : Promise.resolve(undefined),
      listOralAvatars(entry.identity_id),
      listOralVoices(entry.identity_id),
    ]);
    const portrait =
      requests[0].status === "fulfilled" ? requests[0].value : undefined;
    const sheetUrl =
      requests[1].status === "fulfilled" ? requests[1].value : undefined;
    if (requests[0].status === "rejected") {
      errors.push(
        `读取人物头像“${entry.display_name}”失败：${errorText(requests[0].reason)}`,
      );
    }
    if (requests[1].status === "rejected") {
      errors.push(
        `读取人物五视图“${entry.display_name}”失败：${errorText(requests[1].reason)}`,
      );
    }
    const oralAvatars =
      requests[2].status === "fulfilled" ? requests[2].value : [];
    const oralVoices =
      requests[3].status === "fulfilled" ? requests[3].value : [];
    if (requests[2].status === "rejected") {
      errors.push(
        `读取人物分身“${entry.display_name}”失败：${errorText(requests[2].reason)}`,
      );
    }
    if (requests[3].status === "rejected") {
      errors.push(
        `读取人物声音“${entry.display_name}”失败：${errorText(requests[3].reason)}`,
      );
    }

    const previewIds = [
      ...oralAvatars.map((avatar) => avatar.source_asset_id),
      ...oralVoices.flatMap((voice) =>
        voice.demo_asset_id ? [voice.demo_asset_id] : [],
      ),
    ];
    const previewResults = await Promise.allSettled(
      previewIds.map((assetId) => signedUrl(assetId, getAssetDownloadUrl)),
    );
    const previewUrls = new Map<string, string>();
    previewIds.forEach((assetId, index) => {
      const result = previewResults[index];
      if (result?.status === "fulfilled" && result.value) {
        previewUrls.set(assetId, result.value);
      }
    });

    const person = basePerson(entry, portrait);
    person.avatars = oralAvatars.map((avatar) => ({
      id: avatar.id,
      name: avatar.title,
      imageId: avatar.source_asset_id,
      ready: avatar.status === "READY",
      origin: avatar.source_kind === "IMAGE" ? "照片制作" : "视频制作",
      duration: "",
    }));
    person.voices = oralVoices.map((voice, index) => ({
      id: voice.id,
      name: voice.title,
      confirmed:
        voice.status === "READY" &&
        Boolean(voice.demo_asset_id) &&
        Boolean(voice.confirmed),
      isDefault: index === 0 && Boolean(voice.confirmed),
      url: voice.demo_asset_id
        ? previewUrls.get(voice.demo_asset_id)
        : undefined,
    }));
    people.push(person);
    for (const avatar of oralAvatars) {
      assets.push({
        id: avatar.source_asset_id,
        name: `${avatar.title} · 分身预览`,
        kind: avatar.source_kind === "IMAGE" ? "image" : "video",
        url: previewUrls.get(avatar.source_asset_id),
        group: "口播分身",
        personId: entry.identity_id,
        source: "人物库",
        saved: true,
      });
    }
    for (const voice of oralVoices) {
      if (!voice.demo_asset_id) continue;
      assets.push({
        id: voice.demo_asset_id,
        name: `${voice.title} · 声音试听`,
        kind: "audio",
        url: previewUrls.get(voice.demo_asset_id),
        group: "口播声音",
        personId: entry.identity_id,
        source: "人物库",
        saved: true,
      });
    }
    if (entry.contact_sheet_asset_id) {
      assets.push({
        id: entry.contact_sheet_asset_id,
        name: `${entry.display_name} · 基础五视图`,
        kind: "image",
        url: sheetUrl,
        group: "基础五视图",
        personId: entry.identity_id,
        composite: true,
        source: "人物库",
        saved: entry.status === "PUBLISHED",
      });
    }
  }
  return { people, assets, errors };
}

function studioTaskStatus(
  batch: GenerationBatchListItem,
): StudioTask["status"] {
  const status = batch.status.toUpperCase();
  if (status === "SUBMISSION_UNCERTAIN") return "uncertain";
  if (status === "CANCELLED") return "cancelled";
  if (batch.needs_attention_count > 0) return "failed";
  if (status === "SUCCEEDED") return "completed";
  if (status === "COMPLETED_WITH_FAILURES") return "failed";
  if (status === "NEEDS_ATTENTION" || status === "FAILED") return "failed";
  if (status === "PENDING" || status === "QUEUED") return "queued";
  return "running";
}

/** 批次创作通道 → 任务中心类型页签文案（I13 类型保真）。
 * 服务端 058 起在 generation_batches.creation_kind 记录创建通道；
 * 未知通道回退到"视频生成"保持旧数据可见。 */
const CREATION_KIND_LABELS: Record<string, StudioTask["type"]> = {
  replica: "视频复刻",
  independent: "视频生成",
  replacement: "人物置换",
};

function studioTask(batch: GenerationBatchListItem): StudioTask {
  const status = studioTaskStatus(batch);
  return {
    id: batch.id,
    batchId: batch.id,
    projectId: batch.project_id,
    title: batch.display_name?.trim() || batch.project_name || batch.id,
    type: CREATION_KIND_LABELS[batch.creation_kind] ?? "视频生成",
    status,
    cancelAllowed: status === "queued",
    progress: batch.progress.progress_percent,
    submitted: batch.created_at,
    resultId:
      batch.tasks.find((task) => task.result_asset_id)?.result_asset_id ??
      undefined,
  };
}

/** 任务中心"取消任务"：仅服务端判定为仍可取消（全部任务未认领）的
 * 排队批次会成功，其余状态返回明确错误由调用方提示。 */
export async function cancelStudioTask(task: StudioTask): Promise<void> {
  if (task.cancelAllowed === false || !task.batchId) {
    throw new Error("当前任务不支持取消。");
  }
  await cancelGenerationBatch(task.batchId);
}

async function loadTasks(_currentUser: CurrentUser): Promise<StudioTask[]> {
  // The authenticated server scope includes delegated project tasks; filtering
  // by creator here would silently hide work the current customer can access.
  const page = await listGenerationBatches({ limit: 20 });
  return page.items.map(studioTask);
}

/** Re-read every task source used by the task center. Returning one complete
 * snapshot lets the shell replace stale rows, including oral tasks that have
 * completed or disappeared, without a full project/people reload. */
export async function reloadTasks(
  currentUser: CurrentUser,
): Promise<StudioTask[]> {
  const [generationTasks, oralTasks] = await Promise.all([
    loadTasks(currentUser),
    loadOralTasks(),
  ]);
  return [...generationTasks, ...oralTasks];
}

/** Workbench quick upload: create a project, PUT the raw video to cloud
 * storage through the presigned intent, and hand back the source identity so
 * 后续复刻/文案提取都拿这个来源继续，而不是把大视频当解析输入。 */
export async function uploadWorkbenchSourceVideo(
  file: File,
  onProgress: (percent: number) => void,
  signal?: AbortSignal,
): Promise<{ projectId: string; assetId: string }> {
  const base = file.name.replace(/\.(mp4|mov)$/i, "").trim();
  const project = await createProject((base || file.name).slice(0, 120));
  const intent = await createVideoUploadIntent(project.id, file);
  let assetId = intent.asset_id;
  if (intent.upload_required !== false) {
    await uploadReferenceVideo(intent, file, onProgress, signal);
    const completed = await completeVideoUpload(intent.asset_id);
    assetId = completed.asset_id;
  }
  return { projectId: project.id, assetId };
}

function oralTask(row: OralTaskRecord): StudioTask {
  const statusMap: Record<OralTaskRecord["status"], StudioTask["status"]> = {
    QUEUED: "queued",
    SUBMITTING: "running",
    RUNNING: "running",
    SUCCEEDED: "completed",
    FAILED: "failed",
    CANCELLED: "cancelled",
    SUBMISSION_UNCERTAIN: "uncertain",
  };
  return {
    id: `oral-${row.id}`,
    batchId: undefined,
    title: row.title,
    type: "数字人口播",
    status: statusMap[row.status] ?? "running",
    cancelAllowed: false,
    submitted: row.created_at,
    resultId: row.result_asset_id ?? undefined,
    driverMode: row.mode === "AUDIO" ? "audio" : "text",
    ipId: row.identity_id,
    avatarId: row.avatar_id,
    voiceId: row.voice_id ?? undefined,
    audioId: row.audio_asset_id ?? undefined,
  };
}

async function loadOralTasks(): Promise<StudioTask[]> {
  const rows = await listOralTasks(20);
  return rows.map(oralTask);
}

function formatViralDuration(durationMs: number): string {
  const totalSeconds = Math.max(0, Math.round(durationMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function studioVideoFromViral(item: ViralVideoItem): StudioVideo {
  return {
    id: `${item.platform}-${item.videoId}`,
    title: item.title,
    author: item.author,
    platform: item.platform === "douyin" ? "抖音" : "视频号",
    category: item.category,
    poster: item.coverUrl ?? "",
    duration: formatViralDuration(item.durationMs),
    likes: item.likes,
    collections: item.collects,
    shares: item.shares,
    description: item.title,
    platformKey: item.platform,
    nativeId: item.videoId,
    authorAvatar: item.authorAvatar,
    verified: item.verified,
    comments: item.comments,
    publishedAt: item.publishedAt,
    publishedDisplay: item.publishedDisplay,
    likeDisplay: item.likeDisplay,
    tags: item.tags,
    hasPlayableAudio: item.hasPlayableAudio,
    playUrl: item.playUrl,
  };
}

export async function loadStudioData(
  currentUser: CurrentUser,
): Promise<StudioData> {
  const [projectsResult, peopleResult, tasksResult, statsResult, oralResult] =
    await Promise.allSettled([
      loadProjects(),
      loadPeople(),
      loadTasks(currentUser),
      getStudioStats(),
      loadOralTasks(),
    ]);
  const errors: string[] = [];
  const projectData =
    projectsResult.status === "fulfilled"
      ? projectsResult.value
      : { projects: [], assets: [], errors: [] };
  const peopleData =
    peopleResult.status === "fulfilled"
      ? peopleResult.value
      : { people: [], assets: [], errors: [] };
  const tasks = [
    ...(tasksResult.status === "fulfilled" ? tasksResult.value : []),
    ...(oralResult.status === "fulfilled" ? oralResult.value : []),
  ];
  // 统计加载失败不打断工作区：指标卡回退为 "—"，重试路径会再次拉取。
  const stats = statsResult.status === "fulfilled" ? statsResult.value : null;

  if (projectsResult.status === "rejected") {
    errors.push(`读取项目失败：${errorText(projectsResult.reason)}`);
  }
  errors.push(...projectData.errors);
  if (peopleResult.status === "rejected") {
    errors.push(`读取人物失败：${errorText(peopleResult.reason)}`);
  }
  errors.push(...peopleData.errors);
  if (tasksResult.status === "rejected") {
    errors.push(`读取任务失败：${errorText(tasksResult.reason)}`);
  }
  if (oralResult.status === "rejected") {
    errors.push(`读取口播任务失败：${errorText(oralResult.reason)}`);
  }
  return {
    people: peopleData.people,
    assets: [...projectData.assets, ...peopleData.assets],
    videos: [],
    tasks,
    projects: projectData.projects,
    errors,
    loading: false,
    stats,
  };
}

/** 静默轮询用的统计刷新：失败返回 null，由调用方保留旧值。 */
export async function reloadStats(): Promise<StudioStats | null> {
  try {
    return await getStudioStats();
  } catch {
    return null;
  }
}

/** 云端草稿恢复结果：草稿 + 我的文案列表。 */
export type CloudDraftRestore = {
  draft: StudioDraft;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** 把云端 JSON payload 还原为 StudioDraft；结构不完整时返回 null 而不是抛错，
 * 云端草稿必须永远不阻塞工作区进入。 */
function draftFromPayload(payload: unknown): StudioDraft | null {
  if (!isRecord(payload)) return null;
  const script = payload.script;
  const base = createDraft();
  if (!isRecord(script) || typeof script.text !== "string") return null;
  const merged: StudioDraft = {
    ...base,
    ...(payload as Partial<StudioDraft>),
    script: {
      ...base.script,
      ...(script as Partial<StudioScript>),
    },
  };
  return merged;
}

/** 读取云端工作草稿（copy 工作区）。无草稿（404）返回 undefined，
 * 其余错误抛给调用方决定提示方式。 */
export async function loadCloudDraft(): Promise<CloudDraftRestore | undefined> {
  let record: Awaited<ReturnType<typeof getStudioDraft>>;
  try {
    record = await getStudioDraft("copy");
  } catch (cause: unknown) {
    if (
      cause &&
      typeof cause === "object" &&
      "status" in cause &&
      (cause as { status?: number }).status === 404
    ) {
      return undefined;
    }
    throw cause;
  }
  const draft = draftFromPayload(record.payload);
  if (!draft) return undefined;
  draft.script.confirmed = record.script_confirmed;
  return { draft };
}

/** 云端草稿自动保存（last-write-wins）。整个 StudioDraft 序列化上送，
 * 服务端按 (user, kind) 单行 upsert。 */
export async function persistCloudDraft(draft: StudioDraft): Promise<void> {
  await saveStudioDraft(
    "copy" satisfies StudioDraftKind,
    draft as unknown as Record<string, unknown>,
    draft.script.confirmed,
  );
}

/** 我的文案列表：云端记录 → StudioScript（confirmed 不持久化，回填后需重新确认终稿）。 */
function savedScriptFromRecord(record: {
  script_id: string;
  title: string;
  text: string;
  original: string | null;
  version: number;
}): StudioScript {
  return {
    id: record.script_id,
    title: record.title,
    original: record.original ?? "",
    text: record.text,
    version: record.version,
    confirmed: false,
  };
}

export async function loadSavedScriptList(): Promise<StudioScript[]> {
  const records = await listStudioSavedScripts();
  return records.map(savedScriptFromRecord);
}

export async function persistSavedScript(
  script: StudioScript,
  sourceProjectId?: string,
): Promise<void> {
  const input: StudioSavedScriptInput = {
    script_id: script.id,
    title: script.title || "未命名文案",
    text: script.text,
    original: script.original || null,
    version: script.version,
    ip_id: null,
    source_project_id: sourceProjectId ?? null,
    source_kind: sourceProjectId ? "project" : "upload",
  };
  await saveStudioSavedScript(input);
}

/** 终稿显式发布到项目脚本版本（C7 衔接点）：仅当草稿带 projectId 且项目已有
 * 镜头卡版本时可行（ScriptRequest 需要 shot_card_version_id）。任何失败都
 * 返回 false 由调用方软提示，绝不阻断"确认终稿"本身。 */
export async function publishScriptVersion(
  projectId: string,
  text: string,
): Promise<boolean> {
  try {
    const shotCards = await getLatestProjectShotCards(projectId);
    if (!shotCards) return false;
    await createScriptVersion(projectId, {
      source: "custom",
      text,
      shot_card_version_id: shotCards.id,
    });
    return true;
  } catch {
    return false;
  }
}

export type PersonAssetLoad = {
  assets: StudioAsset[];
  errors: string[];
};

export async function loadPersonAssets(
  identityId: string,
): Promise<PersonAssetLoad> {
  try {
    const scenes = (await listCharacterSceneLooks(identityId)).slice(
      0,
      sceneLimit,
    );
    const selected = scenes
      .map((scene) => ({
        scene,
        view:
          scene.views.find((view) => view.view_type === "FRONT_FACE") ??
          scene.views[0],
      }))
      .filter((item) => Boolean(item.view));
    const previews = await Promise.allSettled(
      selected.map(({ view }) =>
        signedUrl(view?.asset_id as string, getCachedCharacterAssetUrl),
      ),
    );
    const errors: string[] = [];
    const assets = selected.map(({ scene, view }, index): StudioAsset => {
      const preview = previews[index];
      let url: string | undefined;
      if (preview?.status === "fulfilled") {
        url = preview.value;
      } else if (preview?.status === "rejected") {
        errors.push(
          `读取场景图片“${scene.scene_name}”失败：${errorText(preview.reason)}`,
        );
      }
      return {
        id: view?.asset_id as string,
        name: scene.scene_name,
        kind: "image",
        url,
        group: "场景形象照",
        personId: identityId,
        composite: false,
        source: "人物库场景造型",
        saved: Boolean(scene.published_at),
      };
    });
    return { assets, errors };
  } catch (error) {
    return {
      assets: [],
      errors: [`读取人物场景形象照失败：${errorText(error)}`],
    };
  }
}

/** 提取文案管线（script-from-audio）：提交任务 → 每 2 秒轮询 → 终态返回。
 * 自动恢复的不确定任务继续轮询；需人工对账或失败时抛出明确错误。 */
type ScriptExtractionAttempt = {
  version: 1;
  accountId: string;
  projectId: string;
  assetId: string;
  idempotencyKey: string;
  taskId?: string;
};

const scriptExtractionFlights = new Map<string, Promise<{ text: string }>>();
const scriptExtractionAttempts = new Map<
  string,
  { attempt: ScriptExtractionAttempt; persisted: boolean }
>();
const removedScriptExtractionAttempts = new Set<string>();

function scriptExtractionStorageKey(
  accountId: string,
  projectId: string,
  assetId: string,
): string {
  return `studio.scriptFromAudioAttempt:${JSON.stringify([accountId, projectId, assetId])}`;
}

function readScriptExtractionAttempt(
  storageKey: string,
  accountId: string,
  projectId: string,
  assetId: string,
): ScriptExtractionAttempt | undefined {
  if (removedScriptExtractionAttempts.has(storageKey)) return undefined;
  const memory = scriptExtractionAttempts.get(storageKey);
  let saved: string | null;
  try {
    saved = window.localStorage.getItem(storageKey);
  } catch {
    if (memory) return memory.attempt;
    throw new Error("无法读取文案提取恢复状态，请检查浏览器存储权限后重试。");
  }
  if (!saved) {
    if (memory && !memory.persisted) return memory.attempt;
    scriptExtractionAttempts.delete(storageKey);
    return undefined;
  }
  try {
    const attempt = JSON.parse(saved) as Partial<ScriptExtractionAttempt>;
    if (
      attempt.version !== 1 ||
      attempt.accountId !== accountId ||
      attempt.projectId !== projectId ||
      attempt.assetId !== assetId ||
      typeof attempt.idempotencyKey !== "string" ||
      (attempt.taskId !== undefined && typeof attempt.taskId !== "string")
    ) {
      removeScriptExtractionAttempt(storageKey);
      return undefined;
    }
    const validAttempt = attempt as ScriptExtractionAttempt;
    if (memory && !memory.persisted) {
      return memory.attempt;
    }
    scriptExtractionAttempts.set(storageKey, {
      attempt: validAttempt,
      persisted: true,
    });
    return validAttempt;
  } catch {
    removeScriptExtractionAttempt(storageKey);
    return undefined;
  }
}

function writeScriptExtractionAttempt(
  storageKey: string,
  attempt: ScriptExtractionAttempt,
): void {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(attempt));
  } catch {
    throw new Error("无法保存文案提取恢复状态，请检查浏览器存储空间后重试。");
  }
  removedScriptExtractionAttempts.delete(storageKey);
  scriptExtractionAttempts.set(storageKey, { attempt, persisted: true });
}

function removeScriptExtractionAttempt(storageKey: string): void {
  scriptExtractionAttempts.delete(storageKey);
  try {
    window.localStorage.removeItem(storageKey);
    removedScriptExtractionAttempts.delete(storageKey);
  } catch {
    removedScriptExtractionAttempts.add(storageKey);
    // Keep a tombstone so a stale storage row cannot revive the terminal task.
  }
}

function isDefiniteClientRejection(cause: unknown): boolean {
  if (typeof cause !== "object" || cause === null) return false;
  const { status, retryable } = cause as {
    status?: unknown;
    retryable?: unknown;
  };
  if (typeof status !== "number") return false;
  if (status === 408 || status === 425 || status === 429) return false;
  return status >= 400 && status < 500 && retryable !== true;
}

function isDefiniteMissingTask(cause: unknown): boolean {
  if (typeof cause !== "object" || cause === null) return false;
  const { status, code } = cause as { status?: unknown; code?: unknown };
  return (
    status === 404 ||
    status === 410 ||
    code === "SCRIPT_FROM_AUDIO_TASK_NOT_FOUND"
  );
}

export function extractScriptFromUpload(
  accountId: string,
  projectId: string,
  assetId: string,
): Promise<{ text: string }> {
  const storageKey = scriptExtractionStorageKey(accountId, projectId, assetId);
  const existingFlight = scriptExtractionFlights.get(storageKey);
  if (existingFlight) return existingFlight;
  const flight = runScriptExtraction(storageKey, accountId, projectId, assetId);
  scriptExtractionFlights.set(storageKey, flight);
  const clearFlight = () => {
    if (scriptExtractionFlights.get(storageKey) === flight) {
      scriptExtractionFlights.delete(storageKey);
    }
  };
  void flight.then(clearFlight, clearFlight);
  return flight;
}

async function runScriptExtraction(
  storageKey: string,
  accountId: string,
  projectId: string,
  assetId: string,
): Promise<{ text: string }> {
  let attempt = readScriptExtractionAttempt(
    storageKey,
    accountId,
    projectId,
    assetId,
  );
  if (!attempt) {
    attempt = {
      version: 1,
      accountId,
      projectId,
      assetId,
      idempotencyKey: crypto.randomUUID(),
    };
    writeScriptExtractionAttempt(storageKey, attempt);
  }
  let taskId = attempt.taskId;
  if (!taskId) {
    try {
      const created = await createScriptFromAudioTask(
        projectId,
        assetId,
        attempt.idempotencyKey,
      );
      taskId = created.id;
      attempt = { ...attempt, taskId };
      writeScriptExtractionAttempt(storageKey, attempt);
    } catch (cause: unknown) {
      if (isDefiniteClientRejection(cause)) {
        removeScriptExtractionAttempt(storageKey);
      }
      throw cause;
    }
  }
  const maxAttempts = 150; // 2s × 150 = 5 分钟上限（长音频异步转写兜底）
  for (let pollAttempt = 0; pollAttempt < maxAttempts; pollAttempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 2000));
    let task: ScriptFromAudioTask;
    try {
      task = await getScriptFromAudioTask(taskId);
    } catch (cause: unknown) {
      if (isDefiniteMissingTask(cause)) {
        removeScriptExtractionAttempt(storageKey);
      }
      throw cause;
    }
    if (task.status === "SUCCEEDED" && task.result) {
      return { text: task.result.text };
    }
    if (
      task.status === "SUBMISSION_UNCERTAIN" &&
      task.recovery_mode === "AUTO"
    ) {
      continue;
    }
    if (
      task.status === "SUBMISSION_UNCERTAIN" &&
      task.recovery_mode === "ADMIN_REQUIRED"
    ) {
      throw new Error(
        task.error_message
          ? `文案提取需要管理员对账：${task.error_message}`
          : "文案提取需要管理员对账，请联系管理员处理。",
      );
    }
    if (task.status === "FAILED" || task.status === "SUBMISSION_UNCERTAIN") {
      if (task.status === "FAILED") {
        removeScriptExtractionAttempt(storageKey);
      }
      throw new Error(task.error_message || "文案提取失败，请稍后重试。");
    }
  }
  throw new Error("文案提取超时，请稍后在任务中心重试。");
}
