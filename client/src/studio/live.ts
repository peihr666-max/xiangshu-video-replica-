import {
  type CurrentUser,
  createGenerationResultPreviewUrl,
  createGenerationTaskPreviewUrl,
  type GenerationBatchListItem,
  getAssetDownloadUrl,
  getCachedCharacterAssetUrl,
  getGenerationBatch,
  getLatestProjectAnalysis,
  getLatestScriptVersion,
  listCharacterSceneLooks,
  listGenerationBatches,
  listProjects,
  listSimpleCharacterLibrary,
  type Project,
  readAnalysisPayload,
  type SimpleLibraryEntry,
} from "../api";
import { createDraft } from "./state";
import type {
  StudioAsset,
  StudioData,
  StudioDraft,
  StudioPerson,
  StudioTask,
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
    people.push(basePerson(entry, portrait));
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

function studioTask(batch: GenerationBatchListItem): StudioTask {
  return {
    id: batch.id,
    batchId: batch.id,
    projectId: batch.project_id,
    title: batch.display_name?.trim() || batch.project_name || batch.id,
    type: "视频生成",
    status: studioTaskStatus(batch),
    progress: batch.progress.progress_percent,
    submitted: batch.created_at,
    resultId:
      batch.tasks.find((task) => task.result_asset_id)?.result_asset_id ??
      undefined,
  };
}

async function loadTasks(_currentUser: CurrentUser): Promise<StudioTask[]> {
  // The authenticated server scope includes delegated project tasks; filtering
  // by creator here would silently hide work the current customer can access.
  const page = await listGenerationBatches({ limit: 20 });
  return page.items.map(studioTask);
}

export async function loadStudioData(
  currentUser: CurrentUser,
): Promise<StudioData> {
  const [projectsResult, peopleResult, tasksResult] = await Promise.allSettled([
    loadProjects(),
    loadPeople(),
    loadTasks(currentUser),
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
  const tasks = tasksResult.status === "fulfilled" ? tasksResult.value : [];

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

  return {
    people: peopleData.people,
    assets: [...projectData.assets, ...peopleData.assets],
    videos: [],
    tasks,
    projects: projectData.projects,
    errors,
    loading: false,
  };
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
