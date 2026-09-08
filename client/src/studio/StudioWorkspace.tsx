import {
  type ComponentProps,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { WorkspaceShell } from "../App";
import {
  createOralAvatarClone,
  createOralCloneConsent,
  createOralTask,
  createOralVoiceClone,
  customerVisibleErrorMessage,
  type GenerationBatch,
  getGenerationBatch,
  getOralPrice,
  type OralTaskRequest,
  type Project,
} from "../api";
import { AnalyticsPage } from "./AnalyticsPage";
import {
  MaterialsPage,
  PublishPage,
  ViralDetailPage,
  ViralPage,
} from "./ContentPages";
import {
  CopyPage,
  OralPage,
  ReplacementPage,
  ReplicaPage,
  VideoPage,
} from "./CreationPages";
import { StudioContext, useStudio } from "./context";
import { LiveWorkspacePanel } from "./LiveWorkspacePanel";
import {
  extractScriptFromUpload as extractScriptFromUploadLive,
  loadCloudDraft,
  loadPersonAssets,
  loadProjectDraft,
  loadSavedScriptList,
  loadStudioData,
  persistCloudDraft,
  persistSavedScript,
  publishScriptVersion,
  reloadStats,
  reloadTasks,
} from "./live";
import {
  ProfilePage,
  TaskDetailPage,
  TasksPage,
  WorkbenchPage,
} from "./MainPages";
import { PeoplePage, PersonPage } from "./PeoplePages";
import {
  buildOralInput,
  createDraft,
  createState,
  pageTitles,
  patchStudioDraft,
  routeFromHash,
  withImportedProject,
} from "./state";
import type {
  LivePanel,
  PickerKind,
  StudioContextValue,
  StudioData,
  StudioDraft,
  StudioOralCloneRequest,
  StudioPage,
  StudioState,
  StudioTask,
} from "./types";
import { Button, Empty, Hint, Icon, Media } from "./ui";
import "./studio.css";

type Props = ComponentProps<typeof WorkspaceShell> & {
  reviewData?: StudioData;
  initialState?: StudioState;
};
const emptyData: StudioData = {
  people: [],
  assets: [],
  videos: [],
  tasks: [],
  projects: [],
  errors: [],
  loading: true,
  stats: null,
};
const TASKS_POLL_INTERVAL_MS = 20_000;
const creationPages = new Set<StudioPage>([
  "replica",
  "replacement",
  "video",
  "reference",
  "oral",
  "oral-audio",
]);
const navGroups: {
  label?: string;
  pages: { id: StudioPage; title: string; icon: string }[];
}[] = [
  {
    pages: [
      { id: "workbench", title: "工作台", icon: "home" },
      { id: "tasks", title: "任务中心", icon: "tasks" },
    ],
  },
  {
    label: "创作",
    pages: [
      { id: "viral", title: "爆款视频", icon: "fire" },
      { id: "copy", title: "文案工坊", icon: "pen" },
      { id: "replica", title: "视频创作", icon: "video" },
    ],
  },
  {
    label: "资产",
    pages: [
      { id: "people", title: "人物库", icon: "person" },
      { id: "materials", title: "素材库", icon: "folder" },
    ],
  },
  {
    label: "分发",
    pages: [
      { id: "publishing", title: "发布管理", icon: "upload" },
      { id: "analytics", title: "数据看板", icon: "chart" },
    ],
  },
];

function isDefiniteSubmissionRejection(cause: unknown): boolean {
  if (typeof cause !== "object" || cause === null) return false;
  const { status, retryable } = cause as {
    status?: unknown;
    retryable?: unknown;
  };
  if (typeof status !== "number") return false;
  if (status === 408 || status === 425 || status === 429) return false;
  return status >= 400 && status < 500 && retryable !== true;
}

type StoredWorkspaceAttempt<T> = {
  version: 1;
  accountId: string;
  resourceKey: string;
  request: T;
};

type StoredCloneRequest = {
  input: StudioOralCloneRequest;
  consentId?: string;
  idempotencyKey: string;
};

const workspaceAttemptMemory = new Map<
  string,
  { attempt: StoredWorkspaceAttempt<unknown>; persisted: boolean }
>();
const removedWorkspaceAttempts = new Set<string>();
const cloneAttemptFlights = new Map<string, Promise<void>>();

function workspaceAttemptKey(
  kind: "oral" | "clone",
  accountId: string,
  resourceKey: string,
): string {
  return `studio.pendingAttempt:${kind}:${JSON.stringify([accountId, resourceKey])}`;
}

function readWorkspaceAttempt<T>(
  storageKey: string,
  accountId: string,
  resourceKey: string,
  isRequest: (value: unknown) => value is T,
): StoredWorkspaceAttempt<T> | undefined {
  if (removedWorkspaceAttempts.has(storageKey)) return undefined;
  const memory = workspaceAttemptMemory.get(storageKey);
  let saved: string | null;
  try {
    saved = window.localStorage.getItem(storageKey);
  } catch {
    if (memory && isRequest(memory.attempt.request)) {
      return memory.attempt as StoredWorkspaceAttempt<T>;
    }
    throw new Error("无法读取待提交任务恢复状态，请检查浏览器存储权限后重试。");
  }
  if (!saved) {
    if (memory && !memory.persisted && isRequest(memory.attempt.request)) {
      return memory.attempt as StoredWorkspaceAttempt<T>;
    }
    workspaceAttemptMemory.delete(storageKey);
    return undefined;
  }
  try {
    const attempt = JSON.parse(saved) as Partial<StoredWorkspaceAttempt<T>>;
    if (
      attempt.version !== 1 ||
      attempt.accountId !== accountId ||
      attempt.resourceKey !== resourceKey ||
      !isRequest(attempt.request)
    ) {
      removeWorkspaceAttempt(storageKey);
      return undefined;
    }
    if (memory && !memory.persisted && isRequest(memory.attempt.request)) {
      return memory.attempt as StoredWorkspaceAttempt<T>;
    }
    const validAttempt = attempt as StoredWorkspaceAttempt<T>;
    workspaceAttemptMemory.set(storageKey, {
      attempt: validAttempt,
      persisted: true,
    });
    return validAttempt;
  } catch {
    removeWorkspaceAttempt(storageKey);
    return undefined;
  }
}

function writeWorkspaceAttempt<T>(
  storageKey: string,
  attempt: StoredWorkspaceAttempt<T>,
): void {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(attempt));
  } catch {
    throw new Error("无法保存待提交任务恢复状态，请检查浏览器存储空间后重试。");
  }
  removedWorkspaceAttempts.delete(storageKey);
  workspaceAttemptMemory.set(storageKey, { attempt, persisted: true });
}

function removeWorkspaceAttempt(storageKey: string): void {
  workspaceAttemptMemory.delete(storageKey);
  try {
    window.localStorage.removeItem(storageKey);
    removedWorkspaceAttempts.delete(storageKey);
  } catch {
    removedWorkspaceAttempts.add(storageKey);
  }
}

function isOralTaskRequest(value: unknown): value is OralTaskRequest {
  if (typeof value !== "object" || value === null) return false;
  const request = value as Partial<OralTaskRequest>;
  const common =
    typeof request.identityId === "string" &&
    typeof request.avatarId === "string" &&
    (request.mode === "TTS" || request.mode === "AUDIO") &&
    typeof request.title === "string" &&
    typeof request.idempotencyKey === "string" &&
    (request.projectId === undefined || typeof request.projectId === "string");
  if (!common) return false;
  return request.mode === "TTS"
    ? typeof request.voiceId === "string" &&
        typeof request.scriptText === "string"
    : typeof request.audioAssetId === "string";
}

function isStoredCloneRequest(value: unknown): value is StoredCloneRequest {
  if (typeof value !== "object" || value === null) return false;
  const request = value as Partial<StoredCloneRequest>;
  const input = request.input;
  const common =
    typeof request.idempotencyKey === "string" &&
    (request.consentId === undefined ||
      typeof request.consentId === "string") &&
    typeof input === "object" &&
    input !== null &&
    (input.kind === "avatar" || input.kind === "voice") &&
    typeof input.identityId === "string" &&
    typeof input.title === "string" &&
    typeof input.sourceAssetId === "string";
  if (!common) return false;
  return (
    input.kind === "voice" ||
    input.sourceKind === "VIDEO" ||
    input.sourceKind === "IMAGE"
  );
}

function WorkspaceUserAvatar({
  currentUser,
  review,
}: {
  currentUser: Props["currentUser"];
  review: boolean;
}) {
  if (review) {
    return <img className="studio-user-avatar" src="/studio/li.png" alt="" />;
  }
  return (
    <span className="studio-user-initial">
      {currentUser.display_name?.slice(0, 1) ||
        currentUser.username?.slice(0, 1) ||
        "我"}
    </span>
  );
}

export function StudioWorkspace({ currentUser, ...props }: Props) {
  return (
    <StudioWorkspaceSession
      key={`${currentUser.id}:${currentUser.role}`}
      currentUser={currentUser}
      {...props}
    />
  );
}

function StudioWorkspaceSession({
  currentUser,
  customerAccount,
  customerWallet,
  reviewData,
  initialState,
}: Props) {
  // Review is an explicit development entry; failed requests never enable it.
  const review = Boolean(import.meta.env.DEV && reviewData);
  const [state, setState] = useState<StudioState>(
    () => initialState || createState(routeFromHash(window.location.hash)),
  );
  const [data, setData] = useState<StudioData>(() =>
    review && reviewData ? reviewData : emptyData,
  );
  const [revision, setRevision] = useState(0);
  const [notice, setNotice] = useState("");
  const [picker, setPicker] = useState<PickerKind>();
  const [livePanel, setLivePanel] = useState<LivePanel>();
  const [liveProject, setLiveProject] = useState<Project>();
  const [handoffBatch, setHandoffBatch] = useState<GenerationBatch | null>(
    null,
  );
  const [generation, setGeneration] = useState<StudioTask["type"]>();
  const [newCreation, setNewCreation] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [showSearch, setShowSearch] = useState(false);
  const [oralPriceFen, setOralPriceFen] = useState<number | null>(null);
  const [oralPriceLoading, setOralPriceLoading] = useState(false);
  const [oralPriceError, setOralPriceError] = useState("");
  const [oralSubmitting, setOralSubmitting] = useState(false);
  const oralPriceRequestRef = useRef(0);
  const cloneActiveRef = useRef(true);
  const oralSubmittingRef = useRef(false);
  const busyRef = useRef(false);
  const operationRef = useRef(0);
  const loadedPeopleRef = useRef(new Set<string>());
  const loadUserRef = useRef(currentUser);
  if (
    loadUserRef.current.id !== currentUser.id ||
    loadUserRef.current.role !== currentUser.role
  ) {
    loadUserRef.current = currentUser;
  }
  const loadUser = loadUserRef.current;
  const notify = useCallback((message: string) => setNotice(message), []);

  useEffect(() => {
    cloneActiveRef.current = true;
    return () => {
      cloneActiveRef.current = false;
    };
  }, []);

  // ---- 云端草稿（C7）----
  // 编辑后防抖自动保存；恢复只在用户尚未做任何编辑时生效，绝不覆盖进行中的输入。
  const DRAFT_AUTOSAVE_DELAY_MS = 2000;
  const latestDraftRef = useRef(state.draft);
  const draftTouchedRef = useRef(false);
  const draftSaveTimerRef = useRef<number | undefined>(undefined);
  const scheduleDraftSave = useCallback(() => {
    if (review) return;
    window.clearTimeout(draftSaveTimerRef.current);
    draftSaveTimerRef.current = window.setTimeout(() => {
      void persistCloudDraft(latestDraftRef.current).catch(() => {
        notify("云端草稿保存失败，内容仍在本机，请稍后继续编辑。");
      });
    }, DRAFT_AUTOSAVE_DELAY_MS);
  }, [review, notify]);
  // 挂载时恢复云端草稿与我的文案；失败静默（只读路径，不阻塞工作区）。
  const cloudUser = loadUser;
  useEffect(() => {
    if (review || !cloudUser.id) return;
    let active = true;
    void loadCloudDraft()
      .then(async (restore) => {
        const saved = await loadSavedScriptList().catch(() => []);
        if (!active) return;
        if (saved.length)
          setState((previous) => ({ ...previous, savedScripts: saved }));
        if (restore && !draftTouchedRef.current) {
          latestDraftRef.current = restore.draft;
          setState((previous) => ({ ...previous, draft: restore.draft }));
          notify("已恢复上次云端草稿，请核对内容并确认终稿。");
        }
      })
      .catch(() => {});
    return () => {
      active = false;
      window.clearTimeout(draftSaveTimerRef.current);
    };
  }, [review, cloudUser, notify]);
  // 自动保存始终跟随最新草稿：导入项目、任务快照回填等不经 patchDraft 的
  // 路径也在这里并入追踪。
  useEffect(() => {
    latestDraftRef.current = state.draft;
  }, [state.draft]);
  const reloadOralPrice = useCallback(async () => {
    const request = ++oralPriceRequestRef.current;
    setOralPriceFen(null);
    setOralPriceError("");
    setOralPriceLoading(true);
    try {
      const price = await getOralPrice();
      if (request === oralPriceRequestRef.current) {
        setOralPriceFen(price.unit_price_fen);
      }
    } catch {
      if (request === oralPriceRequestRef.current) {
        setOralPriceError("口播报价读取失败，请重新获取报价后再提交。");
      }
    } finally {
      if (request === oralPriceRequestRef.current) setOralPriceLoading(false);
    }
  }, []);

  // 数字人口播提交前拉取单价（元/条）；报价不可用时保持提交门禁。
  useEffect(() => {
    if (review || generation !== "数字人口播") {
      oralPriceRequestRef.current += 1;
      setOralPriceFen(null);
      setOralPriceError("");
      setOralPriceLoading(false);
      return;
    }
    void reloadOralPrice();
    return () => {
      oralPriceRequestRef.current += 1;
    };
  }, [review, generation, reloadOralPrice]);

  const submitOralTask = async () => {
    if (currentUser.role === "auditor") {
      notify("当前账号为只读权限，不能提交生成。");
      return;
    }
    if (oralPriceFen === null) {
      notify("请先获取口播报价，报价成功后才能提交。");
      return;
    }
    if (oralSubmittingRef.current) return;
    oralSubmittingRef.current = true;
    setOralSubmitting(true);
    let storageKey: string | undefined;
    try {
      const mode = state.page === "oral-audio" ? "audio" : "text";
      const input = buildOralInput(state.draft, mode);
      const resourceKey = JSON.stringify([
        state.draft.projectId ?? null,
        input.ipId,
        input.avatarId,
        mode,
        input.voiceId ?? null,
        input.audioAssetId ?? null,
      ]);
      storageKey = workspaceAttemptKey("oral", currentUser.id, resourceKey);
      const stored = readWorkspaceAttempt(
        storageKey,
        currentUser.id,
        resourceKey,
        isOralTaskRequest,
      );
      const request =
        stored?.request ??
        ({
          projectId: state.draft.projectId,
          identityId: input.ipId,
          avatarId: input.avatarId,
          voiceId: input.voiceId,
          mode: mode === "audio" ? "AUDIO" : "TTS",
          title: state.draft.script.title || "未命名口播",
          scriptText: state.draft.script.text,
          audioAssetId: input.audioAssetId,
          subtitle:
            "subtitles" in input ? { st_show: input.subtitles } : undefined,
          idempotencyKey: crypto.randomUUID(),
        } satisfies OralTaskRequest);
      if (!stored) {
        writeWorkspaceAttempt(storageKey, {
          version: 1,
          accountId: currentUser.id,
          resourceKey,
          request,
        });
      }
      const result = await createOralTask(request);
      if (result.status !== "SUBMISSION_UNCERTAIN") {
        removeWorkspaceAttempt(storageKey);
      }
      setGeneration(undefined);
      if (result.status === "FAILED") {
        notify("口播任务提交未成功，请核对素材后重试。");
      } else {
        notify("口播任务已提交，可在任务中心查看进度。");
        navigate("tasks");
        refresh();
      }
    } catch (cause: unknown) {
      if (storageKey && isDefiniteSubmissionRejection(cause)) {
        removeWorkspaceAttempt(storageKey);
      }
      notify(
        customerVisibleErrorMessage(cause, "口播任务提交失败，请稍后重试。"),
      );
    } finally {
      oralSubmittingRef.current = false;
      setOralSubmitting(false);
    }
  };
  const refresh = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    if (review) return;
    // The explicit refresh key intentionally reruns the same read-only requests.
    if (revision > 0) loadedPeopleRef.current.clear();
    let active = true;
    setData((previous) => ({ ...previous, loading: true }));
    void loadStudioData(loadUser)
      .then((result) => {
        if (!active) return;
        setData(result);
      })
      .catch((cause: unknown) => {
        if (active)
          setData({
            ...emptyData,
            loading: false,
            errors: [
              customerVisibleErrorMessage(cause, "工作区暂不可用，请重试。"),
            ],
          });
      });
    return () => {
      active = false;
    };
  }, [review, loadUser, revision]);

  // Silent tasks poll: the shell reads everything once on entry, so a batch
  // that finishes while the customer watches would otherwise stay "running"
  // until a manual refresh. Only the tasks slice updates, failures stay
  // quiet (the next tick retries; the explicit 重试加载 path reports errors),
  // and the poll pauses while the tab is hidden or a live panel is busy.
  useEffect(() => {
    if (review) return;
    let active = true;
    const pollUserId = loadUser.id;
    const isCurrent = () => active && loadUserRef.current.id === pollUserId;
    const timer = window.setInterval(() => {
      if (document.hidden || busyRef.current) return;
      void reloadTasks(loadUser)
        .then((tasks) => {
          if (!isCurrent()) return;
          setData((previous) => ({ ...previous, tasks }));
        })
        .catch(() => {});
      void reloadStats().then((stats) => {
        if (stats && isCurrent())
          setData((previous) => ({ ...previous, stats }));
      });
    }, TASKS_POLL_INTERVAL_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [review, loadUser]);

  const personToLoad = state.page.startsWith("person-")
    ? state.selectedPersonId
    : state.draft.ipId;
  useEffect(() => {
    if (
      review ||
      data.loading ||
      !personToLoad ||
      loadedPeopleRef.current.has(personToLoad)
    )
      return;
    let active = true;
    loadedPeopleRef.current.add(personToLoad);
    void loadPersonAssets(personToLoad)
      .then((result) => {
        if (!active) {
          loadedPeopleRef.current.delete(personToLoad);
          return;
        }
        setData((previous) => ({
          ...previous,
          assets: [
            ...previous.assets.filter(
              (asset) => !result.assets.some((item) => item.id === asset.id),
            ),
            ...result.assets,
          ],
          people: previous.people.map((person) =>
            person.id === personToLoad
              ? {
                  ...person,
                  photoIds: result.assets
                    .filter((asset) => !asset.composite)
                    .map((asset) => asset.id),
                }
              : person,
          ),
          errors: [...previous.errors, ...result.errors],
        }));
        if (result.errors.length) loadedPeopleRef.current.delete(personToLoad);
      })
      .catch((cause: unknown) => {
        loadedPeopleRef.current.delete(personToLoad);
        if (active)
          notify(customerVisibleErrorMessage(cause, "人物场景照片暂不可用"));
      });
    return () => {
      active = false;
    };
  }, [review, data.loading, personToLoad, notify]);

  useEffect(() => {
    const onHashChange = () => {
      if (busyRef.current) {
        notify("当前操作正在处理中，请等待完成后切换页面。");
        return;
      }
      setState((previous) => ({
        ...previous,
        page: routeFromHash(window.location.hash),
      }));
      setLivePanel(undefined);
    };
    window.addEventListener("hashchange", onHashChange);
    window.addEventListener("popstate", onHashChange);
    return () => {
      window.removeEventListener("hashchange", onHashChange);
      window.removeEventListener("popstate", onHashChange);
    };
  }, [notify]);

  const navigate: StudioContextValue["navigate"] = (page, patch = {}) => {
    if (busyRef.current) {
      notify("当前操作正在处理中，请等待完成后切换页面。");
      return;
    }
    operationRef.current += 1;
    setState((previous) => ({ ...previous, ...patch, page }));
    window.history.pushState(null, "", `#studio/${page}`);
    setMenuOpen(false);
    setShowSearch(false);
    setLivePanel(undefined);
    window.scrollTo?.({ top: 0 });
  };
  const patchDraft = (patch: Partial<StudioDraft>) => {
    if (Object.hasOwn(patch, "ipId") && patch.ipId !== state.draft.ipId)
      notify(
        "人物已更换，请重新选择该人物的分身和声音，并核对文案中的自我介绍。",
      );
    draftTouchedRef.current = true;
    setState((previous) => {
      const next = patchStudioDraft(previous.draft, patch);
      if (patch.ipId && patch.ipId !== previous.draft.ipId) {
        const owner = data.people.find((person) => person.id === patch.ipId);
        // Explicit handoffs may select an asset together with its verified owner.
        if (
          patch.avatarId &&
          owner?.avatars.some(
            (avatar) => avatar.id === patch.avatarId && avatar.ready,
          )
        )
          next.avatarId = patch.avatarId;
        if (
          patch.voiceId &&
          owner?.voices.some(
            (voice) => voice.id === patch.voiceId && voice.confirmed,
          )
        )
          next.voiceId = patch.voiceId;
        next.script = { ...next.script, confirmed: false };
      }
      return { ...previous, draft: next };
    });
    scheduleDraftSave();
  };
  const openLive = (panel: LivePanel) => {
    if (review) {
      notify(
        "当前为示例审核。此入口在正式登录后打开已实现的上传、分析、人物或账户功能，不调用真实业务接口。",
      );
      return;
    }
    const selectedTask =
      state.page === "task-detail"
        ? data.tasks.find((task) => task.id === state.selectedTaskId)
        : undefined;
    if (panel === "tasks" && selectedTask?.batchId) {
      const operation = ++operationRef.current;
      void getGenerationBatch(selectedTask.batchId)
        .then((batch) => {
          if (operation !== operationRef.current) return;
          setHandoffBatch(batch);
          setLivePanel("tasks");
        })
        .catch((cause: unknown) => {
          if (operation === operationRef.current)
            notify(
              customerVisibleErrorMessage(cause, "无法读取这条任务，请重试。"),
            );
        });
      return;
    }
    if (panel === "analysis")
      setLiveProject(
        data.projects.find((project) => project.id === state.draft.projectId),
      );
    setLivePanel(panel);
  };
  const importProject = async (project: Project) => {
    const operation = ++operationRef.current;
    setLiveProject(project);
    try {
      const imported = await loadProjectDraft(project);
      if (operation !== operationRef.current) return;
      setState((previous) => withImportedProject(previous, imported.draft));
      if (imported.errors.length) notify(imported.errors.join("；"));
      else notify("已带入项目来源与已保存文案。请核对内容并确认终稿。");
    } catch (cause) {
      if (operation === operationRef.current)
        notify(customerVisibleErrorMessage(cause, "无法带入项目内容"));
    }
  };
  const requestGeneration = (kind: StudioTask["type"]) => {
    if (currentUser.role === "auditor") {
      notify("当前账号为只读权限，不能提交生成。");
      return;
    }
    try {
      if (kind === "数字人口播") {
        const input = buildOralInput(
          state.draft,
          state.page === "oral-audio" ? "audio" : "text",
        );
        const person = data.people.find((item) => item.id === input.ipId);
        if (
          !person?.avatars.some(
            (avatar) => avatar.id === input.avatarId && avatar.ready,
          )
        )
          throw new Error("请选择当前人物已就绪的口播分身");
        if (
          input.mode === "text" &&
          !person.voices.some(
            (voice) => voice.id === input.voiceId && voice.confirmed,
          )
        )
          throw new Error("请选择当前人物已确认的声音");
        if (
          input.mode === "audio" &&
          !data.assets.some(
            (asset) =>
              asset.id === input.audioAssetId && asset.kind === "audio",
          )
        )
          throw new Error("完整口播音频已失效，请重新选择");
      }
      setGeneration(kind);
    } catch (cause) {
      notify(cause instanceof Error ? cause.message : "请检查生成原材料");
    }
  };
  const submitOralClone = useCallback(
    (input: StudioOralCloneRequest): Promise<void> => {
      if (review) {
        return Promise.reject(
          new Error("当前为示例审核，不会提交真实口播克隆任务。"),
        );
      }
      if (currentUser.role === "auditor") {
        return Promise.reject(
          new Error("当前账号为只读权限，不能提交口播克隆任务。"),
        );
      }
      const resourceKey = JSON.stringify([
        input.kind,
        input.identityId,
        input.sourceAssetId,
      ]);
      const key = workspaceAttemptKey("clone", currentUser.id, resourceKey);
      const existingFlight = cloneAttemptFlights.get(key);
      if (existingFlight) return existingFlight;
      let stored: StoredWorkspaceAttempt<StoredCloneRequest> | undefined;
      try {
        stored = readWorkspaceAttempt(
          key,
          currentUser.id,
          resourceKey,
          isStoredCloneRequest,
        );
      } catch (cause: unknown) {
        return Promise.reject(cause);
      }
      let pending =
        stored?.request ??
        ({
          input: { ...input },
          idempotencyKey: crypto.randomUUID(),
        } satisfies StoredCloneRequest);
      if (!stored) {
        writeWorkspaceAttempt(key, {
          version: 1,
          accountId: currentUser.id,
          resourceKey,
          request: pending,
        });
      }
      const flight = (async () => {
        try {
          if (!pending.consentId) {
            const consent = await createOralCloneConsent({
              identityId: pending.input.identityId,
              sourceAssetId: pending.input.sourceAssetId,
              purpose:
                pending.input.kind === "avatar"
                  ? "oral_avatar_clone"
                  : "oral_voice_clone",
            });
            pending = { ...pending, consentId: consent.consent_id };
            writeWorkspaceAttempt(key, {
              version: 1,
              accountId: currentUser.id,
              resourceKey,
              request: pending,
            });
            if (!cloneActiveRef.current) {
              throw new Error("页面已切换，请重新提交以继续。");
            }
          }
          if (!cloneActiveRef.current) {
            throw new Error("页面已切换，请重新提交以继续。");
          }
          const consentId = pending.consentId;
          if (!consentId) {
            throw new Error("克隆授权状态无效，请重新提交。");
          }
          if (pending.input.kind === "avatar") {
            await createOralAvatarClone({
              identityId: pending.input.identityId,
              title: pending.input.title,
              sourceAssetId: pending.input.sourceAssetId,
              sourceKind: pending.input.sourceKind,
              consentId,
              idempotencyKey: pending.idempotencyKey,
            });
          } else {
            await createOralVoiceClone({
              identityId: pending.input.identityId,
              title: pending.input.title,
              sourceAssetId: pending.input.sourceAssetId,
              consentId,
              idempotencyKey: pending.idempotencyKey,
            });
          }
          removeWorkspaceAttempt(key);
        } catch (cause: unknown) {
          if (isDefiniteSubmissionRejection(cause)) {
            removeWorkspaceAttempt(key);
          }
          throw cause;
        } finally {
          cloneAttemptFlights.delete(key);
        }
      })();
      cloneAttemptFlights.set(key, flight);
      return flight;
    },
    [review, currentUser.role, currentUser.id],
  );
  const saveDraft = () => {
    if (
      !state.draft.script.text.trim() &&
      !state.draft.prompt.trim() &&
      !state.draft.sourceId
    ) {
      notify("请先填写创作内容。");
      return;
    }
    const script = { ...state.draft.script };
    setState((previous) => ({
      ...previous,
      savedScripts: [
        ...previous.savedScripts.filter(
          (item) => item.id !== previous.draft.script.id,
        ),
        script,
      ],
    }));
    if (review) {
      notify("已保留在本次工作区，可继续切换页面。");
      return;
    }
    void persistSavedScript(script, state.draft.projectId)
      .then(() => notify("已保存到我的文案，换设备登录也能找回。"))
      .catch(() => notify("云端保存失败，本次仅保留在工作区，请稍后重试。"));
    void persistCloudDraft({ ...state.draft, script }).catch(() => {});
  };
  const confirmFinalDraft = () => {
    const script = { ...state.draft.script, confirmed: true };
    patchDraft({ script });
    if (review) return;
    // 立即持久化终稿（不等防抖），并软发布到项目脚本版本。
    void persistCloudDraft({ ...state.draft, script }).catch(() => {});
    if (!state.draft.projectId) return;
    void publishScriptVersion(state.draft.projectId, script.text).then(
      (published) => {
        if (!published)
          notify(
            "终稿已确认，但同步到项目脚本版本未成功，可稍后在来源分析中重试。",
          );
      },
    );
  };
  const extractingRef = useRef(false);
  const extractScriptFromUpload = () => {
    if (review) {
      notify("审核示例不调用真实接口。");
      return;
    }
    if (currentUser.role === "auditor") {
      notify("当前账号为只读权限，不能提交生成。");
      return;
    }
    if (extractingRef.current) return;
    const projectId = state.draft.projectId ?? state.draft.sourceId;
    const assetId =
      state.draft.sourceAssetId ??
      data.projects.find((project) => project.id === projectId)
        ?.reference_asset_id ??
      undefined;
    if (!projectId || !assetId) {
      notify("请先上传视频来源，再提取文案。");
      openLive("projects");
      return;
    }
    extractingRef.current = true;
    notify("正在提取音频并转写文案，预计一到两分钟，请勿关闭页面…");
    void extractScriptFromUploadLive(currentUser.id, projectId, assetId)
      .then(({ text }) => {
        extractingRef.current = false;
        const currentScript = latestDraftRef.current.script;
        patchDraft({
          sourceId: projectId,
          sourceAssetId: assetId,
          script: {
            ...currentScript,
            original: text,
            text: currentScript.text.trim() ? currentScript.text : text,
            confirmed: false,
          },
        });
        navigate("copy", { returnTo: "workbench" });
        notify("文案已提取，请在文案工坊核对内容并确认终稿。");
      })
      .catch((cause: unknown) => {
        extractingRef.current = false;
        notify(
          customerVisibleErrorMessage(cause, "文案提取失败，请稍后重试。"),
        );
      });
  };
  const context: StudioContextValue = {
    state,
    data,
    review,
    user: currentUser,
    navigate,
    patchDraft,
    patchState: (patch) => setState((previous) => ({ ...previous, ...patch })),
    updateData: setData,
    notify,
    openPicker: setPicker,
    openLive,
    requestGeneration,
    submitOralClone,
    saveDraft,
    confirmFinalDraft,
    extractScriptFromUpload,
    refresh,
  };
  const activeNav = state.page.startsWith("person-")
    ? "people"
    : state.page === "viral-detail"
      ? "viral"
      : state.page === "task-detail"
        ? "tasks"
        : creationPages.has(state.page)
          ? "replica"
          : state.page;
  const activeCount = data.tasks.filter((task) =>
    ["running", "queued"].includes(task.status),
  ).length;
  const closeLive = () => {
    if (busyRef.current) {
      notify("操作尚未结束，请稍候。");
      return;
    }
    operationRef.current += 1;
    setLiveProject(undefined);
    setLivePanel(undefined);
    refresh();
  };
  const searchPages = Object.entries(pageTitles).filter(([, title]) =>
    title.includes(search.trim()),
  );

  return (
    <StudioContext.Provider value={context}>
      <div
        className={`studio-shell ${menuOpen ? "studio-shell--menu-open" : ""}`}
      >
        <aside className="studio-sidebar">
          <button
            type="button"
            className="studio-brand"
            onClick={() => {
              navigate("workbench");
            }}
          >
            <span>
              <img src="/studio/brand.png" alt="众墅之家" />
              <b>｜ AI 即创</b>
            </span>
            <small>乡墅爆款视频创作平台</small>
          </button>
          <Button
            variant="primary"
            className="studio-new-button"
            onClick={() => setNewCreation(true)}
          >
            <Icon name="plus" />
            新建创作
          </Button>
          <nav aria-label="主要导航">
            {navGroups.map((group, index) => (
              <div
                className="studio-nav-group"
                key={group.label || `main-${index}`}
              >
                {group.label && (
                  <span className="studio-nav-label">{group.label}</span>
                )}
                {group.pages.map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    aria-current={activeNav === item.id ? "page" : undefined}
                    className={activeNav === item.id ? "is-active" : ""}
                    onClick={() => navigate(item.id)}
                  >
                    <Icon name={item.icon} />
                    <span>{item.title}</span>
                    {item.id === "tasks" && activeCount > 0 && (
                      <small>{activeCount}</small>
                    )}
                  </button>
                ))}
              </div>
            ))}
          </nav>
          <button
            type="button"
            className={`studio-account-entry ${state.page === "profile" ? "is-active" : ""}`}
            aria-label={`用户档案，积分 ${review ? "2680" : "—"}`}
            onClick={() => navigate("profile")}
          >
            <WorkspaceUserAvatar currentUser={currentUser} review={review} />
            <span className="studio-account-points">
              <small>积分</small>
              <strong>{review ? "2680" : "—"}</strong>
            </span>
          </button>
        </aside>
        <main className={`studio-main studio-route-${state.page}`}>
          <div className="studio-topbar">
            <button
              type="button"
              aria-label="展开导航"
              className="studio-menu-button"
              onClick={() => setMenuOpen((value) => !value)}
            >
              <Icon name="more" />
            </button>
            <form
              className="studio-global-search"
              onSubmit={(event) => {
                event.preventDefault();
                setShowSearch(true);
              }}
            >
              <input
                aria-label="搜索工作区"
                placeholder="搜索乡墅视频、文案、人物、素材"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <button type="submit" aria-label="搜索">
                <Icon name="search" />
              </button>
            </form>
            <button
              type="button"
              className="studio-notifications"
              aria-label="查看任务动态"
              onClick={() => navigate("tasks")}
            >
              <Icon name="bell" size={28} />
              {activeCount > 0 && <small>{activeCount}</small>}
            </button>
            <button
              type="button"
              aria-label="用户档案"
              className="studio-top-avatar"
              onClick={() => navigate("profile")}
            >
              <WorkspaceUserAvatar currentUser={currentUser} review={review} />
            </button>
          </div>
          <div className="studio-stage">
            {data.errors.length > 0 && (
              <div className="studio-errors" role="alert">
                {data.errors.join("；")}
                <Button variant="quiet" onClick={refresh}>
                  重试加载
                </Button>
              </div>
            )}
            {livePanel ? (
              <LiveWorkspacePanel
                panel={livePanel}
                currentUser={currentUser}
                customerAccount={customerAccount}
                customerWallet={customerWallet}
                project={liveProject}
                handoffBatch={handoffBatch}
                onClose={closeLive}
                onBusyChange={(busy) => {
                  busyRef.current = busy;
                }}
                onBatchCreated={(batch) => {
                  setHandoffBatch(batch);
                  setLivePanel("tasks");
                  refresh();
                }}
                onHandoffConsumed={() => {
                  setHandoffBatch(null);
                  refresh();
                }}
                onProjectSelected={(project) => {
                  void importProject(project);
                }}
                onRefresh={refresh}
              />
            ) : (
              <StudioPageContent page={state.page} />
            )}
          </div>
          <footer className="studio-version">
            V1.4 · {review ? "示例审核 · 不调用业务接口" : "创作工作区"}
          </footer>
        </main>
        {notice && (
          <div className="studio-toast" role="status">
            <Icon name="info" />
            <span>{notice}</span>
            <button
              type="button"
              aria-label="关闭提示"
              onClick={() => setNotice("")}
            >
              <Icon name="close" />
            </button>
          </div>
        )}
        {picker && (
          <StudioPicker kind={picker} onClose={() => setPicker(undefined)} />
        )}
        {newCreation && (
          <StudioDialog title="新建创作" onClose={() => setNewCreation(false)}>
            <p>选择创作方式。当前文案和素材会保留，可继续复用。</p>
            <div className="studio-new-options">
              {(
                ["replica", "replacement", "video", "oral"] as StudioPage[]
              ).map((page) => (
                <Button
                  key={page}
                  onClick={() => {
                    navigate(page);
                    setNewCreation(false);
                  }}
                >
                  {pageTitles[page]}
                  <Icon name="arrow" />
                </Button>
              ))}
            </div>
            <Button
              variant="quiet"
              onClick={() => {
                setState((previous) => ({ ...previous, draft: createDraft() }));
                navigate("workbench");
                setNewCreation(false);
              }}
            >
              从空白创作开始
            </Button>
          </StudioDialog>
        )}
        {generation && (
          <StudioDialog
            title={`生成确认 · ${generation}`}
            onClose={() => setGeneration(undefined)}
          >
            <Hint>
              {review
                ? "当前为效果审核，不会创建真实生成任务，也不会扣费。"
                : generation === "数字人口播"
                  ? "将创建一条数字人口播任务，提交前请核对文案与声音。"
                  : "此独立创作接口尚未接入。现有项目复刻可通过已实现的生成流程报价与提交。"}
            </Hint>
            <dl className="studio-details">
              <div>
                <dt>作品</dt>
                <dd>{state.draft.script.title || "未命名创作"}</dd>
              </div>
              <div>
                <dt>费用</dt>
                <dd>
                  {generation === "数字人口播" && oralPriceFen !== null
                    ? `${(oralPriceFen / 100).toFixed(2)} 元/条`
                    : "待服务端报价"}
                </dd>
              </div>
              <div>
                <dt>提交状态</dt>
                <dd>尚未提交 · 未扣费</dd>
              </div>
            </dl>
            {!review && generation === "数字人口播" && oralPriceError ? (
              <Hint>
                {oralPriceError}
                <Button
                  variant="outline"
                  disabled={oralPriceLoading}
                  onClick={() => void reloadOralPrice()}
                >
                  {oralPriceLoading ? "正在获取报价" : "重新获取报价"}
                </Button>
              </Hint>
            ) : null}
            {review || generation !== "数字人口播" ? (
              <Button variant="primary" disabled>
                确认费用并提交
              </Button>
            ) : (
              <Button
                variant="primary"
                disabled={
                  oralSubmitting || oralPriceLoading || oralPriceFen === null
                }
                onClick={() => void submitOralTask()}
              >
                {oralSubmitting ? "正在提交" : "确认费用并提交"}
              </Button>
            )}
            {!review && generation !== "数字人口播" && (
              <Button
                onClick={() => {
                  setGeneration(undefined);
                  openLive("analysis");
                }}
              >
                进入项目生成流程
              </Button>
            )}
          </StudioDialog>
        )}
        {showSearch && (
          <StudioDialog title="搜索工作区" onClose={() => setShowSearch(false)}>
            <p>
              {search.trim() ? `与“${search}”相关的页面与人物` : "快速前往"}
            </p>
            <div className="studio-search-results">
              {searchPages.map(([id, title]) => (
                <Button key={id} onClick={() => navigate(id as StudioPage)}>
                  {title}
                  <Icon name="arrow" />
                </Button>
              ))}
              {data.people
                .filter((person) => person.name.includes(search))
                .map((person) => (
                  <Button
                    key={person.id}
                    onClick={() =>
                      navigate("person-ip", { selectedPersonId: person.id })
                    }
                  >
                    {person.name} · {person.role}
                  </Button>
                ))}
            </div>
            {searchPages.length === 0 &&
              !data.people.some((person) => person.name.includes(search)) && (
                <Empty
                  title="没有匹配结果"
                  description="目前支持页面名称与已加载人物搜索"
                />
              )}
          </StudioDialog>
        )}
      </div>
    </StudioContext.Provider>
  );
}

function StudioPageContent({ page }: { page: StudioPage }) {
  switch (page) {
    case "workbench":
      return <WorkbenchPage />;
    case "viral":
      return <ViralPage />;
    case "viral-detail":
      return <ViralDetailPage />;
    case "copy":
      return <CopyPage />;
    case "replica":
      return <ReplicaPage />;
    case "replacement":
      return <ReplacementPage />;
    case "video":
    case "reference":
      return <VideoPage />;
    case "oral":
    case "oral-audio":
      return <OralPage />;
    case "tasks":
      return <TasksPage />;
    case "task-detail":
      return <TaskDetailPage />;
    case "people":
      return <PeoplePage />;
    case "person-ip":
    case "person-photos":
    case "person-avatars":
    case "person-voices":
      return <PersonPage />;
    case "materials":
      return <MaterialsPage />;
    case "publishing":
      return <PublishPage />;
    case "analytics":
      return <AnalyticsPage />;
    case "profile":
      return <ProfilePage />;
  }
}

export function StudioDialog({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (typeof dialog?.showModal === "function") dialog.showModal();
    else dialog?.setAttribute("open", "");
    return () => {
      if (typeof dialog?.close === "function") dialog.close();
    };
  }, []);
  return (
    <dialog
      ref={dialogRef}
      className="studio-dialog"
      aria-label={title}
      onCancel={onClose}
    >
      <header>
        <h2>{title}</h2>
        <button type="button" aria-label="关闭" onClick={onClose}>
          <Icon name="close" />
        </button>
      </header>
      {children}
    </dialog>
  );
}

function StudioPicker({
  kind,
  onClose,
}: {
  kind: PickerKind;
  onClose: () => void;
}) {
  const { state, data, patchDraft, navigate, notify } = useStudio();
  const person = data.people.find((item) => item.id === state.draft.ipId);
  const title: Record<PickerKind, string> = {
    person: "选择人物 IP",
    image: "选择人物形象照片",
    "original-frame": "选择原始画面",
    "first-frame": "选择起始帧",
    "tail-frame": "选择结束帧",
    reference: "选择参考素材",
    avatar: "选择口播分身",
    voice: "选择已确认声音",
    audio: "选择完整口播音频",
    "avatar-photo": "选择单张照片制作分身",
  };
  const select = (patch: Partial<StudioDraft>) => {
    patchDraft(patch);
    onClose();
  };
  const assets = data.assets.filter((asset) =>
    kind === "audio"
      ? asset.kind === "audio"
      : kind === "reference"
        ? true
        : asset.kind === "image" &&
          !asset.composite &&
          ((kind !== "image" && kind !== "avatar-photo") ||
            !person ||
            asset.personId === person.id),
  );
  return (
    <StudioDialog title={title[kind]} onClose={onClose}>
      <p>只带入本次需要的素材，取消不会修改当前创作。</p>
      <div className="studio-picker-grid">
        {kind === "person"
          ? data.people.map((item) => (
              <button
                type="button"
                key={item.id}
                onClick={() => select({ ipId: item.id })}
              >
                {item.portrait ? (
                  <img src={item.portrait} alt="" />
                ) : (
                  <Icon name="person" size={48} />
                )}
                <strong>{item.name}</strong>
                <small>{item.role}</small>
              </button>
            ))
          : kind === "voice"
            ? person?.voices
                .filter((voice) => voice.confirmed)
                .map((voice) => (
                  <button
                    type="button"
                    key={voice.id}
                    onClick={() => select({ voiceId: voice.id })}
                  >
                    <Icon name="audio" size={36} />
                    <strong>{voice.name}</strong>
                    <small>已确认{voice.isDefault ? " · 默认" : ""}</small>
                  </button>
                ))
            : kind === "avatar"
              ? person?.avatars
                  .filter((avatar) => avatar.ready)
                  .map((avatar) => (
                    <button
                      type="button"
                      key={avatar.id}
                      onClick={() => select({ avatarId: avatar.id })}
                    >
                      <Media
                        asset={data.assets.find(
                          (asset) => asset.id === avatar.imageId,
                        )}
                        alt={avatar.name}
                      />
                      <strong>{avatar.name}</strong>
                      <small>{avatar.origin} · 可用于口播</small>
                    </button>
                  ))
              : assets.map((asset) => (
                  <button
                    type="button"
                    key={asset.id}
                    onClick={() => {
                      if (kind === "avatar-photo") {
                        select({ imageId: asset.id });
                        navigate("person-avatars", {
                          selectedPersonId: person?.id,
                          returnTo: state.page,
                        });
                        notify(
                          "已选择单张照片作为制作原料。照片尚不是口播分身，需完成制作后才能使用。",
                        );
                      } else
                        select(
                          kind === "image"
                            ? { imageId: asset.id }
                            : kind === "original-frame"
                              ? {
                                  originalImageId: asset.id,
                                  frameConfirmed: false,
                                }
                              : kind === "first-frame"
                                ? { firstFrameId: asset.id }
                                : kind === "tail-frame"
                                  ? { tailFrameId: asset.id }
                                  : kind === "audio"
                                    ? { audioId: asset.id, voiceId: undefined }
                                    : {
                                        referenceIds: [
                                          ...new Set([
                                            ...state.draft.referenceIds,
                                            asset.id,
                                          ]),
                                        ],
                                      },
                        );
                    }}
                  >
                    {asset.kind === "audio" ? (
                      <Icon name="audio" size={40} />
                    ) : (
                      <Media asset={asset} alt={asset.name} />
                    )}
                    <strong>{asset.name}</strong>
                    <small>{asset.source}</small>
                  </button>
                ))}
      </div>
      {((kind === "voice" &&
        !person?.voices.some((voice) => voice.confirmed)) ||
        (kind === "avatar" &&
          !person?.avatars.some((avatar) => avatar.ready)) ||
        (kind === "person" && !data.people.length)) && (
        <Empty
          title="没有可选的已就绪资产"
          description="请先在人物库中准备该人物的素材"
          action={
            <Button
              onClick={() => {
                onClose();
                navigate(
                  kind === "voice"
                    ? "person-voices"
                    : kind === "avatar"
                      ? "person-avatars"
                      : "people",
                  { selectedPersonId: person?.id, returnTo: state.page },
                );
              }}
            >
              前往人物库
            </Button>
          }
        />
      )}
    </StudioDialog>
  );
}
