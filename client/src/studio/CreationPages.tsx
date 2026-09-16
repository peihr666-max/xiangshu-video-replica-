import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  type AnalysisVersion,
  type CharacterReferenceSelection,
  capturePromptSession,
  customerVisibleErrorMessage,
  type GenerationRatio,
  getAssetDownloadUrl,
  getLatestGenerationPrompt,
  getLatestProjectAnalysis,
  getLatestProjectShotCards,
  getLatestScriptRewriteTask,
  getLatestScriptVersion,
  getScriptRewriteTask,
  listUserSavedPrompts,
  type Project,
  type ProjectMainCharacter,
  readAnalysisH3Prompt,
  readAnalysisPayload,
  readFirstFrameSelectionPayload,
  rewriteProjectScript,
  type SavedPromptItem,
  type ScriptRewriteTask,
  ScriptRewriteTaskError,
  type ShotCard,
  type ShotCardPayload,
  saveGenerationPrompt,
  saveShotCards,
  selectCharacterReferences,
  startVideoAnalysis,
  waitForAnalysisTask,
  waitForScriptRewriteTask,
} from "../api";
import { CharacterSelection } from "../CharacterSelection";
import { FirstFrameSelection } from "../FirstFrameSelection";
import { SourceFrameSelection } from "../SourceFrameSelection";
import { CreationNavigation } from "./CreationNavigation";
import { useStudio } from "./context";
import {
  loadSavedScriptList,
  readAudioDuration,
  readVideoDuration,
  uploadOralAudioMaterial,
  uploadReferenceAudioMaterial,
  uploadVideoMaterial,
  uploadWorkbenchSourceVideo,
  validateOralAudioFile,
} from "./live";
import { PromptEditor } from "./PromptEditor";
import {
  ReplicaNarration,
  ReplicaPromptResult,
  ReplicaWorkflowNavigation,
  replicaPromptReady,
} from "./ReplicaPreparation";
import {
  clearScriptRewriteIdempotencyKey,
  resolvePendingRewrite,
  type ScriptRewriteScope,
  scriptRewriteIdempotencyKey,
  shouldClearScriptRewriteIdempotencyKey,
} from "./scriptRewrite";
import {
  buildReplicaPromptText,
  createDraft,
  DEFAULT_MAX_REFERENCE_AUDIOS,
  DEFAULT_MAX_REFERENCE_IMAGES,
  DEFAULT_MAX_REFERENCE_VIDEOS,
  hasCopyResult,
  MAX_REFERENCE_MEDIA_SECONDS,
  validateReferences,
} from "./state";
import type {
  StudioAsset,
  StudioDraft,
  StudioPerson,
  StudioScript,
  StudioTask,
  StudioVideo,
} from "./types";
import {
  Button,
  Empty,
  Field,
  Hint,
  Icon,
  Media,
  Panel,
  Tabs,
  Waveform,
} from "./ui";
import "./creation.css";

function findAsset(assets: StudioAsset[], id?: string) {
  return id ? assets.find((asset) => asset.id === id) : undefined;
}

async function getProjectAnalysisOrNull(
  projectId: string,
): Promise<AnalysisVersion | null> {
  try {
    return await getLatestProjectAnalysis(projectId);
  } catch (cause: unknown) {
    const error = cause as { code?: string; status?: number };
    if (error.status === 404 && error.code === "ANALYSIS_NOT_FOUND")
      return null;
    throw cause;
  }
}

function findSource(
  assets: StudioAsset[],
  videos: StudioVideo[],
  id?: string,
): StudioAsset | undefined {
  const asset = findAsset(assets, id);
  if (asset) return asset;
  const video = id ? videos.find((item) => item.id === id) : undefined;
  return video
    ? {
        id: video.id,
        name: video.title,
        kind: "video",
        poster: video.poster,
        duration: video.duration,
        group: video.category,
        source: video.platform,
        saved: true,
      }
    : undefined;
}

function activePerson(
  people: StudioPerson[],
  selectedId?: string,
): StudioPerson | undefined {
  return selectedId
    ? people.find((person) => person.id === selectedId)
    : undefined;
}

function SourceStrip({ source }: { source?: StudioAsset }) {
  return (
    <div className="creation-source-strip">
      <span className="creation-status-dot" />
      <span>
        来源：
        {source ? `${source.name} · ${source.source}` : "尚未选择来源视频"}
      </span>
    </div>
  );
}

function ControlGroup({
  label,
  children,
}: {
  label: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="studio-field">
      <span>{label}</span>
      {children}
    </div>
  );
}

function copyProfile(person?: StudioPerson) {
  if (!person) return "";
  return JSON.stringify({
    display_name: person.name.trim(),
    role: person.role.trim(),
    service_scope: person.scope.trim(),
    target_audience: person.audience.trim(),
    expression_style: person.expression.trim(),
    audience_needs: person.audience_needs?.trim() ?? "",
    factual_background: person.factual_background?.trim() ?? "",
    sample_script: person.sample_script?.trim() ?? "",
    forbidden_claims: person.forbidden_claims?.trim() ?? "",
  });
}
function taskProfileMatches(task: ScriptRewriteTask, fingerprint: string) {
  if (!task.identity_id) return !fingerprint;
  const snapshot = task.ip_profile_snapshot;
  if (!snapshot || !fingerprint) return false;
  const expected = JSON.parse(fingerprint) as Record<string, string>;
  return Object.entries(expected).every(
    ([key, value]) =>
      ((snapshot as unknown as Record<string, unknown>)[key] ?? "") === value,
  );
}
function pendingRewriteStorageKey(accountId: string) {
  return `studio:pending-copy:${accountId}`;
}
function readPendingRewrite(accountId: string): StudioDraft["pendingRewrite"] {
  try {
    const value = JSON.parse(
      sessionStorage.getItem(pendingRewriteStorageKey(accountId)) ?? "null",
    );
    return value &&
      typeof value.scopeKey === "string" &&
      typeof value.resultText === "string"
      ? value
      : undefined;
  } catch {
    return undefined;
  }
}
function storePendingRewrite(
  accountId: string,
  value: StudioDraft["pendingRewrite"],
) {
  try {
    if (value)
      sessionStorage.setItem(
        pendingRewriteStorageKey(accountId),
        JSON.stringify(value),
      );
    else sessionStorage.removeItem(pendingRewriteStorageKey(accountId));
  } catch {
    /* Cloud draft still persists recovery metadata. */
  }
}
function copySource(draft: StudioDraft) {
  return (
    draft.script.original || (draft.script.resultKind ? "" : draft.script.text)
  ).trim();
}
function copyInstructions(draft: StudioDraft) {
  return [
    draft.rewriteLength && draft.rewriteLength !== "original"
      ? `目标约 ${draft.rewriteLength === "custom" ? (draft.rewriteWordCount ?? "") : draft.rewriteLength} 字。`
      : "",
    draft.rewriteInstructions?.trim() ?? "",
  ]
    .filter(Boolean)
    .join("\n");
}

export function CopyPage() {
  const {
    state,
    data,
    patchDraft,
    navigate,
    saveDraft,
    confirmFinalDraft,
    openLive,
    openPicker,
    patchState,
    notify,
    review,
    user,
    draftSaveStatus,
  } = useStudio();
  const readOnly = user.role === "auditor";
  const method = state.draft.rewriteMethod ?? "ip";
  const hasResult = hasCopyResult(state.draft.script);
  const profileFingerprint =
    method === "custom"
      ? ""
      : copyProfile(data.people.find((item) => item.id === state.draft.ipId));
  const [rewriteError, setRewriteError] = useState("");
  const [tab, setTab] = useState<"rewrite" | "saved">("rewrite");
  const [rewriting, setRewriting] = useState(false);
  const [candidate, setCandidate] = useState(state.draft.rewriteCandidate);
  const [savedLoading, setSavedLoading] = useState(false);
  const [savedError, setSavedError] = useState("");
  const savedOperation = useRef(0);
  const current = useRef({ state, patchDraft, patchState, notify });
  current.current = { state, patchDraft, patchState, notify };
  const rewritePendingRef = useRef(false);
  const rewriteOperationRef = useRef(0);
  const scopeGenerationRef = useRef(0);
  const currentRef = useRef({ state, patchDraft, notify });
  currentRef.current = { state, patchDraft, notify };
  const rewriteScopeKey = JSON.stringify([
    user.id,
    state.draft.id,
    state.draft.projectId,
    state.draft.sourceId,
    state.draft.sourceAssetId,
    state.draft.ipId,
    state.draft.script.id,
    copySource(state.draft),
    method,
    copyInstructions(state.draft),
    profileFingerprint,
  ]);
  const activeScopeRef = useRef({ key: rewriteScopeKey, generation: 0 });
  if (activeScopeRef.current.key !== rewriteScopeKey) {
    activeScopeRef.current = {
      key: rewriteScopeKey,
      generation: ++scopeGenerationRef.current,
    };
  }
  const activeScope = activeScopeRef.current;

  const finishRewrite = useCallback(
    async (
      task: ScriptRewriteTask,
      expectedScope: { key: string; generation: number },
      operation: number,
      requestScope: ScriptRewriteScope,
      idempotencyKey: string,
    ) => {
      try {
        const completed =
          task.status === "PENDING" || task.status === "RUNNING"
            ? await waitForScriptRewriteTask(task.id)
            : task;
        if (
          rewriteOperationRef.current !== operation ||
          activeScopeRef.current !== expectedScope
        )
          return;
        const current = currentRef.current.state.draft;
        const rewritten = completed.result?.rewritten_text?.trim();
        const currentSourceAssetId = current.sourceAssetId ?? current.sourceId;
        if (
          completed.status !== "SUCCEEDED" ||
          completed.project_id !== current.projectId ||
          completed.identity_id !==
            (current.rewriteMethod === "custom" ? null : current.ipId) ||
          completed.source_asset_id !== currentSourceAssetId ||
          completed.source_text !== copySource(current) ||
          (completed.instructions ?? "") !== copyInstructions(current) ||
          !taskProfileMatches(
            completed,
            requestScope.profileFingerprint ?? "",
          ) ||
          !rewritten
        )
          throw completed.status === "FAILED" ||
            completed.status === "SUBMISSION_UNCERTAIN"
            ? new ScriptRewriteTaskError(completed)
            : new Error(
                completed.error_message || "改写未返回完整正文，请重试。",
              );
        clearScriptRewriteIdempotencyKey(requestScope, idempotencyKey);
        storePendingRewrite(requestScope.accountId, undefined);
        if (current.script.text !== requestScope.resultText) {
          // 改写期间用户手改了正文：保留人工稿，结果转候选待显式应用。
          const scopedCandidate = {
            scopeKey: expectedScope.key,
            text: rewritten,
          };
          setCandidate(scopedCandidate);
          currentRef.current.patchDraft({
            pendingRewrite: undefined,
            rewriteCandidate: scopedCandidate,
          });
          currentRef.current.notify(
            "改写已完成，当前正文保持不变；可对照后应用候选稿。",
          );
          return;
        }
        currentRef.current.patchDraft({
          pendingRewrite: undefined,
          rewriteCandidate: undefined,
          script: {
            ...current.script,
            text: rewritten,
            confirmed: false,
            resultKind: "rewritten",
            rewriteTaskId: completed.id,
          },
          scriptEdited: true,
        });
        currentRef.current.notify("改写已完成，请核对并保存当前版本。");
      } catch (cause) {
        if (shouldClearScriptRewriteIdempotencyKey(cause)) {
          clearScriptRewriteIdempotencyKey(requestScope, idempotencyKey);
          if (
            rewriteOperationRef.current === operation &&
            activeScopeRef.current === expectedScope
          ) {
            storePendingRewrite(requestScope.accountId, undefined);
            currentRef.current.patchDraft({ pendingRewrite: undefined });
          }
        }
        if (
          rewriteOperationRef.current === operation &&
          activeScopeRef.current === expectedScope
        ) {
          const message = customerVisibleErrorMessage(
            cause,
            "文案改写失败，请重试。",
          );
          setRewriteError(message);
          currentRef.current.notify(message);
        }
      } finally {
        if (
          rewriteOperationRef.current === operation &&
          activeScopeRef.current === expectedScope
        ) {
          rewritePendingRef.current = false;
          setRewriting(false);
        }
      }
    },
    [],
  );

  useEffect(() => {
    const operation = ++rewriteOperationRef.current;
    rewritePendingRef.current = false;
    setRewriting(false);
    const draft = currentRef.current.state.draft;
    setCandidate(
      draft.rewriteCandidate?.scopeKey === activeScope.key
        ? draft.rewriteCandidate
        : undefined,
    );
    setRewriteError("");
    const localPending = readPendingRewrite(user.id);
    const recoverPending = resolvePendingRewrite(
      activeScope.key,
      draft.pendingRewrite,
      localPending,
    );
    if (localPending && localPending.scopeKey !== activeScope.key)
      storePendingRewrite(user.id, undefined);
    if (
      !review &&
      user.role !== "auditor" &&
      draft.projectId &&
      draft.sourceId &&
      (draft.rewriteMethod === "custom" || draft.ipId) &&
      copySource(draft) &&
      (!recoverPending || recoverPending.taskId) &&
      (recoverPending || !hasCopyResult(draft.script))
    ) {
      const sourceAssetId = draft.sourceAssetId ?? draft.sourceId;
      const requestScope: ScriptRewriteScope = {
        accountId: user.id,
        projectId: draft.projectId,
        sourceAssetId,
        identityId: draft.rewriteMethod === "custom" ? "" : (draft.ipId ?? ""),
        scriptId: draft.script.id,
        scriptVersion: draft.script.version,
        text: copySource(draft),
        instructions: copyInstructions(draft),
        resultText: recoverPending?.resultText ?? draft.script.text,
        profileFingerprint,
      };
      const idempotencyKey = scriptRewriteIdempotencyKey(requestScope);
      void (
        recoverPending?.taskId
          ? getScriptRewriteTask(recoverPending.taskId)
          : getLatestScriptRewriteTask(
              draft.projectId,
              draft.rewriteMethod === "custom" ? null : draft.ipId,
              sourceAssetId,
            )
      )
        .then((task) => {
          if (
            rewriteOperationRef.current !== operation ||
            activeScopeRef.current !== activeScope ||
            !task ||
            task.source_asset_id !== sourceAssetId ||
            task.source_text !== copySource(draft) ||
            (task.instructions ?? "") !== copyInstructions(draft) ||
            !taskProfileMatches(task, profileFingerprint) ||
            task.id === draft.script.rewriteTaskId
          )
            return;
          rewritePendingRef.current = true;
          setRewriting(true);
          void finishRewrite(
            task,
            activeScope,
            operation,
            requestScope,
            idempotencyKey,
          );
        })
        .catch((cause) => {
          if (
            rewriteOperationRef.current === operation &&
            activeScopeRef.current === activeScope
          )
            currentRef.current.notify(
              customerVisibleErrorMessage(
                cause,
                "读取上次改写任务失败，可直接重新提交。",
              ),
            );
        });
    }
    return () => {
      rewriteOperationRef.current += 1;
    };
  }, [
    activeScope,
    finishRewrite,
    review,
    user.id,
    user.role,
    profileFingerprint,
  ]);

  const refreshSaved = useCallback(async () => {
    const operation = ++savedOperation.current;
    setSavedLoading(true);
    setSavedError("");
    try {
      const scripts = await loadSavedScriptList();
      if (savedOperation.current === operation)
        current.current.patchState({ savedScripts: scripts });
    } catch (cause) {
      if (savedOperation.current === operation)
        setSavedError(
          customerVisibleErrorMessage(cause, "读取文案失败，请重试。"),
        );
    } finally {
      if (savedOperation.current === operation) setSavedLoading(false);
    }
  }, []);
  useEffect(() => {
    if (tab === "saved" && !review) void refreshSaved();
    return () => {
      savedOperation.current += 1;
    };
  }, [tab, review, refreshSaved]);

  const customWordCountInvalid =
    state.draft.rewriteLength === "custom" &&
    (!Number.isInteger(state.draft.rewriteWordCount) ||
      (state.draft.rewriteWordCount ?? 0) < 1 ||
      (state.draft.rewriteWordCount ?? 0) > 5000);
  const rewriteUnavailableReason = customWordCountInvalid
    ? "请输入1至5000之间的整数文案字数。"
    : review
      ? "审核示例不调用业务接口。"
      : readOnly
        ? "当前账号为只读权限，不能改写文案。"
        : !state.draft.projectId
          ? "当前文案缺少来源项目。"
          : !state.draft.sourceId
            ? "当前文案缺少来源视频，请重新选择来源。"
            : method === "ip" && !state.draft.ipId
              ? "请先选择参与二创的人物 IP。"
              : !copySource(state.draft)
                ? "请先提取待改写正文。"
                : copySource(state.draft).length > 20000
                  ? "待改写正文不能超过 20000 字符。"
                  : copyInstructions(state.draft).length > 2000
                    ? "本次改写要求不能超过 2000 字符。"
                    : method === "custom" &&
                        !state.draft.rewriteInstructions?.trim()
                      ? "请填写本次改写要求，或选择一个快捷要求。"
                      : "";

  const rewrite = async () => {
    if (rewriteUnavailableReason || rewriting || rewritePendingRef.current)
      return;
    const draft = state.draft;
    const projectId = draft.projectId;
    const identityId = method === "custom" ? undefined : draft.ipId;
    const sourceAssetId = draft.sourceAssetId ?? draft.sourceId;
    if (!projectId || !sourceAssetId) return;
    const operation = ++rewriteOperationRef.current;
    const expectedScope = activeScopeRef.current;
    const retryPending = resolvePendingRewrite(
      expectedScope.key,
      draft.pendingRewrite,
      readPendingRewrite(user.id),
    );
    const requestScope: ScriptRewriteScope = {
      accountId: user.id,
      projectId,
      sourceAssetId,
      identityId: identityId ?? "",
      scriptId: draft.script.id,
      scriptVersion: draft.script.version,
      text: copySource(draft),
      instructions: copyInstructions(draft),
      resultText: retryPending?.resultText ?? draft.script.text,
      profileFingerprint,
    };
    const idempotencyKey =
      retryPending?.requestKey ?? scriptRewriteIdempotencyKey(requestScope);
    const pending = {
      scopeKey: expectedScope.key,
      resultText: requestScope.resultText ?? draft.script.text,
      requestKey: idempotencyKey,
      startedAt: retryPending?.startedAt ?? Date.now(),
    };
    storePendingRewrite(user.id, pending);
    patchDraft({ pendingRewrite: pending, rewriteCandidate: undefined });
    rewritePendingRef.current = true;
    setRewriteError("");
    setCandidate(undefined);
    setRewriting(true);
    try {
      const task = await rewriteProjectScript(
        projectId,
        copySource(draft),
        identityId,
        sourceAssetId,
        idempotencyKey,
        copyInstructions(draft),
      );
      if (
        rewriteOperationRef.current !== operation ||
        activeScopeRef.current !== expectedScope
      )
        return;
      const acceptedPending = { ...pending, taskId: task.id };
      storePendingRewrite(user.id, acceptedPending);
      currentRef.current.patchDraft({ pendingRewrite: acceptedPending });
      await finishRewrite(
        task,
        expectedScope,
        operation,
        requestScope,
        idempotencyKey,
      );
    } catch (cause) {
      if (shouldClearScriptRewriteIdempotencyKey(cause)) {
        clearScriptRewriteIdempotencyKey(requestScope, idempotencyKey);
        if (activeScopeRef.current === expectedScope) {
          storePendingRewrite(user.id, undefined);
          currentRef.current.patchDraft({ pendingRewrite: undefined });
        }
      }
      if (
        rewriteOperationRef.current === operation &&
        activeScopeRef.current === expectedScope
      ) {
        rewritePendingRef.current = false;
        setRewriting(false);
        const message = customerVisibleErrorMessage(
          cause,
          "提交文案改写失败，请重试。",
        );
        setRewriteError(message);
        notify(message);
      }
    }
  };
  const applySavedScript = (script: StudioScript) => {
    const project = data.projects.find(
      (item) => item.id === script.sourceProjectId,
    );
    patchDraft({
      ...createDraft(),
      projectId: script.sourceProjectId,
      ipId: script.ipId,
      sourceId: project?.reference_asset_id ?? undefined,
      sourceAssetId: project?.reference_asset_id ?? undefined,
      originalImageId: undefined,
      imageId: undefined,
      firstFrameId: undefined,
      firstFrameSelectionVersionId: undefined,
      tailFrameId: undefined,
      avatarId: undefined,
      voiceId: undefined,
      audioId: undefined,
      videoBatchId: undefined,
      script: { ...script, confirmed: false, resultKind: "manual" },
      scriptEdited: true,
    });
    patchState({
      selectedVideoId: undefined,
      selectedTaskId: undefined,
      selectedAssetId: undefined,
      selectedPersonId: script.ipId,
      returnTo: undefined,
    });
    setTab("rewrite");
  };
  const source = findSource(
    data.assets,
    data.videos,
    state.draft.sourceId ?? state.selectedVideoId,
  );
  const person = activePerson(data.people, state.draft.ipId);
  const saved = state.savedScripts;
  const oralLengthExceeded =
    state.draft.script.text.length > 10000 ||
    state.draft.script.title.length > 120;

  return (
    <section className="creation-page creation-copy">
      <header className="creation-heading">
        <h1>文案工坊</h1>
        <p>核对视频原文，设置二创要求，生成后编辑定稿</p>
        {state.returnTo && state.returnTo !== "copy" ? (
          <Button
            variant="quiet"
            onClick={() =>
              navigate(state.returnTo ?? "workbench", { returnTo: undefined })
            }
          >
            返回上一步
          </Button>
        ) : null}
      </header>
      <Tabs
        items={[
          { id: "rewrite", label: "文案改写" },
          { id: "saved", label: "我的文案" },
        ]}
        value={tab}
        onChange={(value) => setTab(value as "rewrite" | "saved")}
      />

      {tab === "saved" ? (
        <Panel className="creation-saved-list">
          {!review ? (
            <Button
              variant="outline"
              disabled={savedLoading}
              onClick={() => void refreshSaved()}
            >
              刷新文案
            </Button>
          ) : null}
          {savedLoading ? <Hint>正在读取文案…</Hint> : null}
          {savedError ? (
            <Empty
              title={savedError}
              action={
                <Button onClick={() => void refreshSaved()}>
                  重试读取文案
                </Button>
              }
            />
          ) : saved.length ? (
            saved.map((script) => (
              <button
                className="creation-script-row"
                disabled={readOnly}
                key={script.id}
                onClick={() => applySavedScript(script)}
                type="button"
              >
                <span>{script.title}</span>
                <small>{script.confirmed ? "已确认" : "草稿"}</small>
              </button>
            ))
          ) : !savedLoading ? (
            <Empty
              title="还没有保存的文案"
              description="保存当前稿后，文案会集中显示在这里；再次保存会更新同一篇。"
            />
          ) : null}
        </Panel>
      ) : (
        <>
          <SourceStrip source={source} />
          <p id="copy-resize-hint" className="creation-resize-hint">
            拖动文本框右下角可调整高度
          </p>

          <div className="creation-copy-grid">
            <Panel className="creation-copy-source">
              <h2 className="creation-panel-title">
                <span className="creation-step-number">01</span>
                原文（提取自来源）
              </h2>
              {state.draft.script.original ? (
                <textarea
                  aria-label="来源原文"
                  aria-describedby="copy-resize-hint"
                  className="creation-textarea creation-source-textarea"
                  readOnly
                  value={state.draft.script.original}
                />
              ) : (
                <Empty
                  title="尚未提取文案"
                  description="可先从爆款视频或视频来源进入文案工坊。"
                  action={
                    <Button
                      variant="outline"
                      onClick={() => openLive("analysis")}
                    >
                      打开来源分析
                    </Button>
                  }
                />
              )}
            </Panel>
            <Panel className="creation-copy-settings">
              <h2 className="creation-panel-title">
                <span className="creation-step-number">02</span>设置二创
              </h2>
              <fieldset
                className="copy-methods"
                disabled={readOnly || rewriting}
              >
                <legend>选择二创方式</legend>
                <label>
                  <input
                    type="radio"
                    name="copy-method"
                    checked={method === "ip"}
                    onChange={() => patchDraft({ rewriteMethod: "ip" })}
                  />
                  <strong>按人物 IP</strong>
                  <small>带入人物定位、受众和表达风格</small>
                </label>
                <label>
                  <input
                    type="radio"
                    name="copy-method"
                    checked={method === "custom"}
                    onChange={() => patchDraft({ rewriteMethod: "custom" })}
                  />
                  <strong>按要求二创</strong>
                  <small>直接描述这次想怎么改</small>
                </label>
              </fieldset>
              {method === "ip" ? (
                <div className="copy-person-summary">
                  <div>
                    <strong>
                      {person
                        ? `${person.name} · ${person.role}`
                        : "未选择人物 IP"}
                    </strong>
                    <p>
                      {person
                        ? `${person.audience} · ${person.expression}`
                        : "选择人物后自动带入已保存的 IP 档案。"}
                    </p>
                  </div>
                  <Button
                    disabled={readOnly || rewriting}
                    variant="outline"
                    onClick={() => openPicker("person")}
                  >
                    更换人物
                  </Button>
                  {person ? (
                    <Button
                      variant="quiet"
                      onClick={() =>
                        navigate("person-ip", {
                          selectedPersonId: person.id,
                          returnTo: "copy",
                        })
                      }
                    >
                      完善 IP 档案
                    </Button>
                  ) : null}
                </div>
              ) : null}
              <div className="copy-requirements">
                <label>
                  文案字数
                  <select
                    aria-label="文案字数"
                    disabled={readOnly || rewriting}
                    value={state.draft.rewriteLength ?? "original"}
                    onChange={(event) =>
                      patchDraft({
                        rewriteLength: event.target
                          .value as StudioDraft["rewriteLength"],
                      })
                    }
                  >
                    <option value="original">接近原文</option>
                    <option value="100">约100字</option>
                    <option value="200">约200字</option>
                    <option value="300">约300字</option>
                    <option value="custom">自定义字数</option>
                  </select>
                  {state.draft.rewriteLength === "custom" ? (
                    <input
                      aria-label="自定义文案字数"
                      aria-invalid={customWordCountInvalid}
                      className="creation-input"
                      type="number"
                      inputMode="numeric"
                      min={1}
                      max={5000}
                      step={1}
                      disabled={readOnly || rewriting}
                      placeholder="输入1–5000字"
                      value={state.draft.rewriteWordCount ?? ""}
                      onChange={(event) =>
                        patchDraft({
                          rewriteWordCount:
                            event.target.value === ""
                              ? undefined
                              : Number(event.target.value),
                        })
                      }
                    />
                  ) : null}
                  <small>生成字数为近似值，可在结果中调整。</small>
                </label>
                <label>
                  {method === "ip" ? "补充要求（选填）" : "本次改写要求"}
                  <textarea
                    aria-label="本次改写要求"
                    className="creation-textarea copy-instructions"
                    maxLength={1900}
                    disabled={readOnly || rewriting}
                    value={state.draft.rewriteInstructions ?? ""}
                    onChange={(event) =>
                      patchDraft({ rewriteInstructions: event.target.value })
                    }
                    placeholder="例如：面向准备回乡建房的家庭，语气朴实，先讲问题再给建议，不添加报价。"
                  />
                </label>
              </div>
              <div className="copy-quick-actions">
                {["更口语化", "精简内容", "知识讲解", "调整开头"].map(
                  (label) => (
                    <Button
                      key={label}
                      variant="outline"
                      disabled={readOnly || rewriting}
                      onClick={() =>
                        patchDraft({
                          rewriteInstructions: [
                            state.draft.rewriteInstructions?.trim(),
                            label,
                          ]
                            .filter(Boolean)
                            .join("；")
                            .slice(0, 1900),
                        })
                      }
                    >
                      {label}
                    </Button>
                  ),
                )}
              </div>
              <div className="copy-generate-row">
                <Hint>
                  保留原文信息，生成后可继续编辑；发布前请核对事实、案例与承诺。
                </Hint>
                <Button
                  variant="primary"
                  onClick={() => void rewrite()}
                  disabled={Boolean(rewriteUnavailableReason) || rewriting}
                >
                  {rewriting ? "正在生成…" : "生成二创文案"}
                </Button>
              </div>
              {rewriteUnavailableReason ? (
                <Hint>{rewriteUnavailableReason}</Hint>
              ) : null}
              {rewriteError ? <p role="alert">{rewriteError}</p> : null}
            </Panel>
            <Panel className="creation-copy-editor">
              <div className="creation-panel-title-row">
                <h2 className="creation-panel-title">
                  <span className="creation-step-number">03</span>
                  二创结果
                </h2>
                {hasResult ? (
                  <small>
                    {state.draft.script.confirmed ? "终稿" : "草稿"} V
                    {state.draft.script.version}
                  </small>
                ) : null}
              </div>
              {hasResult ? (
                <>
                  <input
                    aria-label="作品名称"
                    className="creation-input"
                    disabled={readOnly}
                    onChange={(event) =>
                      patchDraft({
                        script: {
                          ...state.draft.script,
                          title: event.target.value,
                          confirmed: false,
                        },
                      })
                    }
                    placeholder="作品名称"
                    value={state.draft.script.title}
                  />
                  <textarea
                    aria-label="二创文案"
                    aria-describedby="copy-resize-hint"
                    className="creation-textarea creation-copy-textarea"
                    disabled={readOnly}
                    onChange={(event) =>
                      patchDraft({
                        script: {
                          ...state.draft.script,
                          text: event.target.value,
                          confirmed: false,
                          resultKind: "manual",
                        },
                      })
                    }
                    placeholder="在这里编辑乡墅口播文案"
                    value={state.draft.script.text}
                  />
                  <div className="creation-saved-state" aria-live="polite">
                    {draftSaveStatus === "dirty"
                      ? "有未保存修改"
                      : draftSaveStatus === "saving"
                        ? "正在保存到云端…"
                        : draftSaveStatus === "saved"
                          ? "已保存到云端"
                          : draftSaveStatus === "error"
                            ? "云端保存失败，可点击保存版本重试"
                            : "内容变动后需重新确认终稿"}
                  </div>
                  <Hint>
                    实际字数：
                    {state.draft.script.text.replace(/\s/g, "").length}；
                    {state.draft.script.text.length} / 10000
                    字符（数字人口播上限）；标题{" "}
                    {state.draft.script.title.length} / 120 字符。AI 改写最多
                    20000 字符。
                  </Hint>
                </>
              ) : (
                <Empty
                  title={rewriting ? "正在生成二创文案" : "等待生成二创文案"}
                  description="在上方选择方式并点击生成，结果将在这里出现。"
                  action={
                    !state.draft.script.original && !rewriting ? (
                      <Button
                        variant="quiet"
                        disabled={readOnly}
                        onClick={() =>
                          patchDraft({
                            script: {
                              ...state.draft.script,
                              resultKind: "manual",
                              text: "",
                              confirmed: false,
                            },
                          })
                        }
                      >
                        手动写稿
                      </Button>
                    ) : undefined
                  }
                />
              )}
              {candidate?.scopeKey === activeScope.key ? (
                <Panel>
                  <p>{candidate.text}</p>
                  <Button
                    onClick={() => {
                      patchDraft({
                        rewriteCandidate: undefined,
                        pendingRewrite: undefined,
                        script: {
                          ...state.draft.script,
                          text: candidate.text,
                          confirmed: false,
                          resultKind: "rewritten",
                        },
                      });
                      setCandidate(undefined);
                    }}
                  >
                    应用候选稿
                  </Button>
                </Panel>
              ) : null}
            </Panel>
          </div>
          {hasResult ? (
            <footer className="creation-action-bar">
              <Button
                variant="primary"
                disabled={
                  readOnly ||
                  !state.draft.script.text.trim() ||
                  oralLengthExceeded
                }
                onClick={() => confirmFinalDraft()}
              >
                确认终稿
              </Button>
              <Button
                variant="outline"
                disabled={readOnly}
                onClick={() => {
                  if (readOnly) return;
                  saveDraft();
                }}
              >
                保存版本
              </Button>
              <Button
                variant="primary"
                disabled={
                  !state.draft.script.confirmed || !person || oralLengthExceeded
                }
                onClick={() => navigate("oral", { returnTo: "copy" })}
              >
                用于数字人口播
              </Button>
            </footer>
          ) : null}
        </>
      )}
    </section>
  );
}

type ReplicaStage = "source" | "analyzing" | "ready";

// 审核包样例分镜：仅 review 视觉演示，不参与真实拆解流程。
const REVIEW_SAMPLE_SHOTS: ShotCard[] = [
  {
    shot_id: "shot-1",
    start_time: 0,
    end_time: 8,
    shot_type: "中景",
    composition: "",
    camera_motion: "推进",
    subject: "院落",
    action: "镜头缓推庭院",
    scene: "乡墅庭院",
    spoken_text: "",
    transition: "切镜",
  },
  {
    shot_id: "shot-2",
    start_time: 8,
    end_time: 16,
    shot_type: "近景",
    composition: "",
    camera_motion: "固定",
    subject: "讲解人物",
    action: "人物出镜讲解",
    scene: "庭院",
    spoken_text: "这栋房子的采光设计",
    transition: "切镜",
  },
  {
    shot_id: "shot-3",
    start_time: 16,
    end_time: 24,
    shot_type: "特写",
    composition: "",
    camera_motion: "摇移",
    subject: "外立面",
    action: "外立面细节展示",
    scene: "建筑外立面",
    spoken_text: "",
    transition: "切镜",
  },
];

/** 客户档位归一：非 4/15 秒的时长映射到最近的客户可选档（≤9s→4s，>9s→15s）。 */
function normalizeCustomerDuration(seconds: number): 4 | 15 {
  return seconds === 4 || seconds === 15 ? seconds : seconds <= 9 ? 4 : 15;
}

export function ReplicaPage() {
  const {
    state,
    data,
    review,
    patchDraft,
    updateData,
    navigate,
    notify,
    saveDraft,
    user,
  } = useStudio();
  const readOnly = user.role === "auditor";
  const project = data.projects.find(
    (item) => item.id === state.draft.projectId,
  );
  const source = findSource(
    data.assets,
    data.videos,
    state.draft.sourceId ?? state.selectedVideoId,
  );
  const [stage, setStage] = useState<ReplicaStage>(() =>
    state.draft.projectId ? "ready" : "source",
  );
  const [shots, setShots] = useState<ShotCard[]>([]);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [promptText, setPromptText] = useState(
    state.draft.replicaSourcePrompt ?? state.draft.prompt,
  );
  const [promptNameOpen, setPromptNameOpen] = useState(false);
  const [promptName, setPromptName] = useState("");
  const [savingPrompt, setSavingPrompt] = useState(false);
  const [pendingAnalysisPrompt, setPendingAnalysisPrompt] = useState<{
    projectId: string;
    text: string;
  } | null>(null);
  const [restoreBusy, setRestoreBusy] = useState(false);
  const [restoreError, setRestoreError] = useState("");
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const uploadOperationRef = useRef(0);
  const uploadAbortRef = useRef<AbortController | null>(null);
  const restoreOperationRef = useRef(0);
  const restoredProjectIdRef = useRef<string | undefined>(undefined);
  const restoreSuppressedRef = useRef(false);
  const promptSaveOperationRef = useRef(0);
  const promptEditVersionRef = useRef(0);
  // 拆解完成回调用：比对发起时的项目，防止换视频后的旧结果覆盖新状态。
  const analysisProjectRef = useRef<string | undefined>(undefined);
  const analysisOperationRef = useRef(0);
  const promptTextRef = useRef(promptText);
  const promptEditedRef = useRef(
    state.draft.projectId === project?.id && state.draft.promptEdited === true,
  );
  const promptTypedThisMountRef = useRef(false);
  const latestDraftRef = useRef(state.draft);
  const patchDraftRef = useRef(patchDraft);
  if (
    !promptTypedThisMountRef.current &&
    state.draft.projectId === project?.id &&
    state.draft.promptEdited === true
  ) {
    promptTextRef.current =
      state.draft.replicaSourcePrompt ?? state.draft.prompt;
    promptEditedRef.current = true;
  } else {
    promptTextRef.current = promptText;
  }
  latestDraftRef.current = state.draft;
  patchDraftRef.current = patchDraft;
  useEffect(
    () => () => {
      analysisProjectRef.current = undefined;
      analysisOperationRef.current += 1;
      uploadOperationRef.current += 1;
      uploadAbortRef.current?.abort();
      restoreOperationRef.current += 1;
      promptSaveOperationRef.current += 1;
      restoredProjectIdRef.current = undefined;
      restoreSuppressedRef.current = false;
    },
    [],
  );

  const resetReplicaState = () => {
    setShots([]);
  };

  const restoreSavedProject = useCallback(
    async (target: Project, force = false) => {
      if (restoreSuppressedRef.current) return;
      if (!force && restoredProjectIdRef.current === target.id) return;
      const operation = ++restoreOperationRef.current;
      const promptVersionAtStart = promptEditVersionRef.current;
      restoredProjectIdRef.current = target.id;
      setRestoreBusy(true);
      setRestoreError("");
      try {
        const [shotVersion, analysisVersion, promptState, scriptState] =
          await Promise.all([
            getLatestProjectShotCards(target.id),
            getProjectAnalysisOrNull(target.id),
            getLatestGenerationPrompt(target.id),
            getLatestScriptVersion(target.id),
          ]);
        if (operation !== restoreOperationRef.current) return;

        const shotPayload = shotVersion
          ? (shotVersion.payload as ShotCardPayload)
          : null;
        const restoredShots = shotPayload?.shots ?? [];
        const analysis = analysisVersion
          ? readAnalysisPayload(analysisVersion)
          : null;
        const original = analysis?.original_script ?? "";
        const savedPromptText = promptState.version?.payload.prompt_text;
        const savedPrompt =
          !promptState.stale && typeof savedPromptText === "string"
            ? savedPromptText
            : "";
        const prompt =
          savedPrompt ||
          readAnalysisH3Prompt(analysisVersion) ||
          buildReplicaPromptText(restoredShots, original);
        const savedScriptText = scriptState.version?.payload.full_text;
        const savedScript =
          !scriptState.stale && typeof savedScriptText === "string"
            ? scriptState.version
            : null;
        const currentDraft = latestDraftRef.current;
        const keepLocalDraft = currentDraft.projectId === target.id;
        const keepLocalScript =
          keepLocalDraft && currentDraft.scriptEdited === true;
        const keepLocalPrompt =
          keepLocalDraft &&
          (currentDraft.promptEdited === true ||
            promptEditedRef.current ||
            promptEditVersionRef.current !== promptVersionAtStart);
        const promptStillEdited =
          keepLocalDraft &&
          (currentDraft.promptEdited === true || promptEditedRef.current);
        const blankScript = createDraft().script;
        const script = keepLocalScript
          ? currentDraft.script
          : {
              ...blankScript,
              id: savedScript?.id ?? blankScript.id,
              title: target.name,
              original,
              text: savedScript
                ? (savedScript.payload.full_text as string)
                : original,
              version: savedScript?.version_number ?? 1,
              confirmed: false,
            };
        const restoredPrompt =
          currentDraft.replicaSourcePrompt ??
          (keepLocalPrompt ? promptTextRef.current : prompt);

        setShots(restoredShots);
        setPromptText(restoredPrompt);
        promptTextRef.current = restoredPrompt;
        patchDraftRef.current({
          projectId: target.id,
          sourceId: target.reference_asset_id ?? undefined,
          sourceAssetId: target.reference_asset_id ?? undefined,
          prompt:
            keepLocalDraft && currentDraft.replicaPromptBasis
              ? currentDraft.prompt
              : restoredPrompt,
          replicaSourcePrompt: restoredPrompt,
          promptEdited: promptStillEdited,
          script,
          scriptEdited: keepLocalScript,
        });
        setStage("ready");
      } catch (cause: unknown) {
        if (operation !== restoreOperationRef.current) return;
        restoredProjectIdRef.current = undefined;
        setRestoreError(
          customerVisibleErrorMessage(cause, "历史分镜读取失败，请重试。"),
        );
      } finally {
        if (operation === restoreOperationRef.current) setRestoreBusy(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (
      promptTypedThisMountRef.current ||
      state.draft.projectId !== project?.id ||
      state.draft.promptEdited !== true
    )
      return;
    promptTextRef.current =
      state.draft.replicaSourcePrompt ?? state.draft.prompt;
    promptEditedRef.current = true;
    setPromptText(state.draft.replicaSourcePrompt ?? state.draft.prompt);
  }, [
    project?.id,
    state.draft.projectId,
    state.draft.prompt,
    state.draft.replicaSourcePrompt,
    state.draft.promptEdited,
  ]);

  useEffect(() => {
    if (review || !project) return;
    void restoreSavedProject(project);
  }, [project, restoreSavedProject, review]);

  const replicaDuration = normalizeCustomerDuration(state.draft.duration);

  const handleUpload = async (file: File) => {
    if (review || readOnly) {
      notify("审核示例不上传视频。");
      return;
    }
    analysisProjectRef.current = undefined;
    analysisOperationRef.current += 1;
    setAnalysisBusy(false);
    const operation = ++uploadOperationRef.current;
    promptSaveOperationRef.current += 1;
    setSavingPrompt(false);
    uploadAbortRef.current?.abort();
    restoreSuppressedRef.current = true;
    setRestoreError("");
    const abortController = new AbortController();
    uploadAbortRef.current = abortController;
    notify("正在上传参考视频…");
    try {
      const uploaded = await uploadWorkbenchSourceVideo(
        file,
        (percent) => {
          if (operation === uploadOperationRef.current)
            notify(`参考视频上传中 ${percent}%`);
        },
        abortController.signal,
      );
      if (operation !== uploadOperationRef.current) return;
      restoreOperationRef.current += 1;
      setRestoreBusy(false);
      resetReplicaState();
      setPromptText("");
      promptTextRef.current = "";
      promptEditedRef.current = false;
      promptTypedThisMountRef.current = false;
      const blankScript = {
        ...createDraft().script,
        title: uploaded.project?.name ?? file.name,
      };
      patchDraft({
        projectId: uploaded.projectId,
        sourceId: uploaded.assetId,
        sourceAssetId: uploaded.assetId,
        prompt: "",
        promptEdited: false,
        script: blankScript,
        scriptEdited: false,
      });
      if (uploaded.project || uploaded.asset) {
        updateData((current) => ({
          ...current,
          projects: uploaded.project
            ? [
                uploaded.project,
                ...current.projects.filter(
                  (project) => project.id !== uploaded.project?.id,
                ),
              ]
            : current.projects,
          assets: uploaded.asset
            ? [
                uploaded.asset,
                ...current.assets.filter(
                  (asset) => asset.id !== uploaded.asset?.id,
                ),
              ]
            : current.assets,
        }));
      }
      restoredProjectIdRef.current = uploaded.projectId;
      restoreSuppressedRef.current = false;
      setStage("ready");
      notify("参考视频已上传，点击「启动 AI 拆解」反推分镜与提示词。");
    } catch {
      if (operation !== uploadOperationRef.current) return;
      restoreSuppressedRef.current = false;
      notify("参考视频上传失败，请稍后重试。");
    }
  };

  const selectExistingProject = (selectedId: string) => {
    const selected = data.projects.find((item) => item.id === selectedId);
    if (!selected) {
      return;
    }
    analysisProjectRef.current = undefined;
    analysisOperationRef.current += 1;
    setAnalysisBusy(false);
    uploadOperationRef.current += 1;
    promptSaveOperationRef.current += 1;
    setSavingPrompt(false);
    uploadAbortRef.current?.abort();
    restoreSuppressedRef.current = false;
    restoreOperationRef.current += 1;
    restoredProjectIdRef.current = undefined;
    setRestoreBusy(false);
    resetReplicaState();
    setPromptText("");
    promptTextRef.current = "";
    promptEditedRef.current = false;
    promptTypedThisMountRef.current = false;
    setRestoreError("");
    const blankScript = { ...createDraft().script, title: selected.name };
    patchDraft({
      projectId: selected.id,
      sourceId: selected.reference_asset_id ?? undefined,
      sourceAssetId: selected.reference_asset_id ?? undefined,
      prompt: "",
      promptEdited: false,
      script: blankScript,
      scriptEdited: false,
    });
    setStage("ready");
    void restoreSavedProject(selected, true).then(() => {
      if (restoredProjectIdRef.current === selected.id)
        notify(`已载入项目「${selected.name}」的历史分镜，可继续编辑。`);
    });
  };

  const startAnalysis = async () => {
    if (review || readOnly || analysisBusy) {
      return;
    }
    const projectId = state.draft.projectId;
    const assetId =
      state.draft.sourceAssetId ?? project?.reference_asset_id ?? null;
    if (!projectId || !assetId) {
      notify("请先上传或选择来源视频。");
      return;
    }
    restoreOperationRef.current += 1;
    restoredProjectIdRef.current = projectId;
    restoreSuppressedRef.current = false;
    setRestoreBusy(false);
    setRestoreError("");
    analysisProjectRef.current = projectId;
    const operation = ++analysisOperationRef.current;
    const sessionCurrent = capturePromptSession();
    const isCurrentAnalysis = () =>
      operation === analysisOperationRef.current &&
      analysisProjectRef.current === projectId &&
      latestDraftRef.current.projectId === projectId &&
      sessionCurrent();
    setAnalysisBusy(true);
    setStage("analyzing");
    notify("AI 拆解进行中，约需一到数分钟，请保持页面打开…");
    try {
      const editAtAnalysisStart = promptEditVersionRef.current;
      const scriptAtAnalysisStart = latestDraftRef.current.script.text;
      const analysisTarget = JSON.stringify([
        state.draft.firstFrameId,
        state.draft.duration,
        state.draft.ratio,
      ]);
      const task = await startVideoAnalysis(projectId, assetId, {
        route: "replica",
        project_id: projectId,
        source_asset_id: assetId,
        first_frame_asset_id: state.draft.firstFrameId,
        duration_seconds: replicaDuration,
        ratio: state.draft.ratio as GenerationRatio,
      });
      await waitForAnalysisTask(task.id);
      if (!isCurrentAnalysis()) {
        return; // 等待期间用户更换了来源视频，丢弃旧项目的拆解结果。
      }
      const analysisVersion = await getLatestProjectAnalysis(projectId);
      if (!isCurrentAnalysis()) return;
      const analysisShots: ShotCard[] = analysisVersion
        ? (readAnalysisPayload(analysisVersion)?.shots ?? [])
        : [];
      const script = analysisVersion
        ? (readAnalysisPayload(analysisVersion)?.original_script ?? "")
        : "";
      // 拆解任务只写 analysis 版本；shot_card 版本由客户端落库（与成熟工作区一致）。
      let shotVersion = await getLatestProjectShotCards(projectId).catch(
        () => null,
      );
      const shotPayload = shotVersion
        ? (shotVersion.payload as ShotCardPayload)
        : null;
      const shotsFresh =
        shotPayload &&
        shotPayload.source_analysis_version_id === analysisVersion?.id;
      if (!isCurrentAnalysis()) return;
      if (!shotsFresh) {
        shotVersion = await saveShotCards(
          analysisVersion?.id ?? "",
          analysisShots,
        );
      }
      const finalShots = shotVersion
        ? ((shotVersion.payload as ShotCardPayload).shots ?? [])
        : analysisShots;
      if (!isCurrentAnalysis()) return;
      setShots(finalShots);
      if (latestDraftRef.current.script.text === scriptAtAnalysisStart)
        patchDraftRef.current({
          script: {
            ...latestDraftRef.current.script,
            original: script,
            text: script,
            confirmed: false,
          },
          scriptEdited: false,
        });
      const generationPrompt = analysisVersion?.payload.generation_prompt as
        | {
            status?: string;
            prompt_text?: string;
            issues?: { message: string }[];
          }
        | undefined;
      const text =
        generationPrompt?.status === "READY" && generationPrompt.prompt_text
          ? generationPrompt.prompt_text
          : buildReplicaPromptText(finalShots, script);
      if (
        !promptEditedRef.current &&
        promptEditVersionRef.current === editAtAnalysisStart &&
        analysisTarget ===
          JSON.stringify([
            latestDraftRef.current.firstFrameId,
            latestDraftRef.current.duration,
            latestDraftRef.current.ratio,
          ])
      ) {
        setPromptText(text);
        promptTextRef.current = text;
        patchDraft({
          replicaSourcePrompt: text,
          ...(latestDraftRef.current.replicaPromptBasis
            ? {}
            : { prompt: text, promptEdited: false }),
        });
      } else {
        setPendingAnalysisPrompt({ projectId, text });
      }
      setStage("ready");
      setAnalysisBusy(false);
      notify(
        generationPrompt?.status === "READY"
          ? "拆解完成，请核对口播和拆解内容，再生成新提示词。"
          : `分镜已保存。${generationPrompt?.issues?.map((issue) => issue.message).join("；") || "提示词待核对，可手动编辑或主动优化。"}`,
      );
    } catch (cause: unknown) {
      if (!isCurrentAnalysis()) return;
      setAnalysisBusy(false);
      setStage("ready");
      notify(customerVisibleErrorMessage(cause, "AI 拆解失败，请稍后重试。"));
    }
  };

  const saveAsCustomPrompt = async () => {
    if (review || readOnly) {
      notify("审核示例不调用真实接口。");
      return;
    }
    const projectId = state.draft.projectId;
    if (!projectId) {
      notify("请先上传或选择来源视频。");
      return;
    }
    setSavingPrompt(true);
    const operation = ++promptSaveOperationRef.current;
    const editVersion = promptEditVersionRef.current;
    const submittedPrompt = promptTextRef.current;
    try {
      await saveGenerationPrompt(projectId, {
        name:
          promptName.trim() ||
          `复刻提示词 ${new Date().toLocaleDateString("zh-CN")}`,
        prompt_text: submittedPrompt,
        generation_context: {
          route: "replica",
          project_id: projectId,
          source_asset_id: latestDraftRef.current.sourceAssetId,
          first_frame_asset_id: latestDraftRef.current.firstFrameId,
          duration_seconds: replicaDuration,
          ratio: latestDraftRef.current.ratio as GenerationRatio,
        },
      });
      const stillCurrent =
        operation === promptSaveOperationRef.current &&
        editVersion === promptEditVersionRef.current &&
        latestDraftRef.current.projectId === projectId &&
        promptTextRef.current === submittedPrompt;
      if (!stillCurrent) {
        if (latestDraftRef.current.projectId === projectId)
          notify("提交时的 Prompt 已保存，当前修改仍需再次保存。");
        return;
      }
      // Saving a reusable template does not revert the authoritative local draft.
      patchDraftRef.current({ replicaSourcePrompt: submittedPrompt });
      notify("已保存到我的提示词，视频生成页可直接导入。");
      setPromptNameOpen(false);
    } catch (cause: unknown) {
      if (operation === promptSaveOperationRef.current)
        notify(
          customerVisibleErrorMessage(
            cause,
            "保存自定义提示词失败，请稍后重试。",
          ),
        );
    } finally {
      if (operation === promptSaveOperationRef.current) setSavingPrompt(false);
    }
  };

  const displayShots =
    shots.length > 0
      ? shots
      : review && stage === "ready"
        ? REVIEW_SAMPLE_SHOTS
        : [];
  const hasShots = stage === "ready" && displayShots.length > 0;

  return (
    <section className="creation-page creation-replica">
      <CreationNavigation />
      <ReplicaWorkflowNavigation />
      {stage === "source" && !project ? (
        <Panel className="creation-empty-workspace">
          <Empty
            title="先导入参考视频"
            description="上传本地视频后由 AI 拆解分镜并反推提示词；也可以选择已有项目直接续作。"
            action={
              <div className="creation-upload-row">
                <Button
                  disabled={readOnly}
                  variant="primary"
                  onClick={() => uploadInputRef.current?.click()}
                >
                  上传参考视频
                </Button>
                {data.projects.length > 0 && (
                  <select
                    aria-label="选择已有项目"
                    className="creation-project-select"
                    defaultValue=""
                    disabled={readOnly}
                    onChange={(event) => {
                      if (event.target.value) {
                        selectExistingProject(event.target.value);
                      }
                    }}
                  >
                    <option value="" disabled>
                      选择已有项目
                    </option>
                    {data.projects.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            }
          />
        </Panel>
      ) : (
        <>
          <SourceStrip source={source} />
          <Panel className="creation-replica-analyze">
            <div className="creation-panel-title-row">
              <span>
                来源视频 ·{" "}
                {project?.name ?? state.draft.projectId ?? "未命名项目"}
              </span>
              {displayShots.length > 0 && (
                <small>已拆解 {displayShots.length} 个镜头</small>
              )}
            </div>
            <div className="creation-upload-row">
              <Button
                variant="primary"
                disabled={readOnly || analysisBusy}
                onClick={() => void startAnalysis()}
              >
                {analysisBusy
                  ? "AI 拆解进行中…"
                  : displayShots.length > 0
                    ? "重新拆解"
                    : "启动 AI 拆解"}
              </Button>
              <Button
                disabled={readOnly || analysisBusy}
                variant="outline"
                onClick={() => uploadInputRef.current?.click()}
              >
                更换来源视频
              </Button>
            </div>
            <Hint>
              拆解会反推分镜与提示词；上传新视频会创建新项目，历史任务不受影响。
            </Hint>
            <Hint>
              离开页面会保留当前工作区草稿；重新打开时会同时读取该项目已保存的版本。
            </Hint>
            {restoreBusy && <Hint>正在读取已保存的分镜、文案和 Prompt…</Hint>}
            {restoreError && (
              <div className="creation-inline-error" role="alert">
                <span>{restoreError}</span>
                <Button
                  variant="outline"
                  onClick={() => {
                    if (project) void restoreSavedProject(project, true);
                  }}
                >
                  重试读取历史分镜
                </Button>
              </div>
            )}
          </Panel>
          <ReplicaNarration />
          {hasShots && (
            <details className="creation-shot-list studio-panel">
              <summary>查看原视频分镜 · {displayShots.length} 个</summary>
              <div className="creation-panel-title">
                分镜（共 {displayShots.length} 个）
              </div>
              {displayShots.map((shot, index) => (
                <div className="creation-shot-row" key={shot.shot_id}>
                  <span className="creation-shot-index">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="creation-shot-body">
                    <strong>
                      {shot.start_time.toFixed(1)}s–{shot.end_time.toFixed(1)}s
                      · {shot.shot_type || "未标注景别"}
                    </strong>
                    <small>
                      {[
                        shot.subject && `主体：${shot.subject}`,
                        shot.action && `动作：${shot.action}`,
                        shot.spoken_text && `台词：${shot.spoken_text}`,
                      ]
                        .filter(Boolean)
                        .join(" ｜ ")}
                    </small>
                  </span>
                </div>
              ))}
            </details>
          )}
          <Panel className="creation-prompt-output">
            <div className="creation-panel-title-row">
              <span>
                <b className="creation-step-number">02</b> 视频拆解与复刻提示词
              </span>
              {displayShots.length === 0 && <small>完成拆解后自动生成</small>}
            </div>
            {pendingAnalysisPrompt &&
              pendingAnalysisPrompt.projectId === project?.id && (
                <details>
                  <summary>
                    查看拆解开始时的提示词（当前编辑与素材已保留）
                  </summary>
                  <pre>{pendingAnalysisPrompt.text}</pre>
                  <Button
                    disabled={readOnly}
                    onClick={() => {
                      const text = pendingAnalysisPrompt.text;
                      setPromptText(text);
                      promptTextRef.current = text;
                      promptEditVersionRef.current += 1;
                      promptEditedRef.current = true;
                      patchDraft({ replicaSourcePrompt: text });
                      setPendingAnalysisPrompt(null);
                    }}
                  >
                    应用拆解结果
                  </Button>
                </details>
              )}
            <PromptEditor
              label="拆解 Prompt"
              readOnly={readOnly}
              optimizationDisabled={review}
              scope={`${user.id}:${state.draft.projectId ?? ""}`}
              context={{
                route: "replica",
                project_id: state.draft.projectId,
                source_asset_id: state.draft.sourceAssetId,
                first_frame_asset_id: state.draft.firstFrameId,
                duration_seconds: replicaDuration,
                ratio: state.draft.ratio as GenerationRatio,
              }}
              onChange={(text) => {
                setPromptText(text);
                promptTextRef.current = text;
                promptEditedRef.current = true;
                promptTypedThisMountRef.current = true;
                promptEditVersionRef.current += 1;
                patchDraft({
                  replicaSourcePrompt: text,
                });
              }}
              placeholder="完成 AI 拆解后，这里会生成逐镜头的反推提示词；也可手动撰写。"
              rows={10}
              value={promptText}
            />
          </Panel>
          <div className="creation-upload-row">
            {promptNameOpen ? (
              <>
                <input
                  aria-label="自定义提示词名称"
                  className="creation-project-select"
                  disabled={readOnly}
                  onChange={(event) => setPromptName(event.target.value)}
                  placeholder="提示词名称"
                  value={promptName}
                />
                <Button
                  disabled={readOnly || savingPrompt}
                  onClick={() => void saveAsCustomPrompt()}
                  variant="primary"
                >
                  {savingPrompt ? "保存中…" : "确认保存"}
                </Button>
                <Button
                  onClick={() => setPromptNameOpen(false)}
                  variant="quiet"
                >
                  取消
                </Button>
              </>
            ) : (
              <Button
                disabled={readOnly}
                onClick={() => setPromptNameOpen(true)}
                variant="outline"
              >
                保存为自定义提示词
              </Button>
            )}
          </div>

          <ReplicaPromptResult />
        </>
      )}
      <footer className="creation-action-bar">
        <div>
          <strong>内容配置 → 首帧置换 → AI 视频</strong>
          <Hint>先生成新提示词，再准备要采用的新首图。</Hint>
        </div>
        <Button
          variant="outline"
          disabled={readOnly}
          onClick={() => {
            if (readOnly) return;
            saveDraft();
          }}
        >
          保存草稿
        </Button>
        <Button
          variant="primary"
          disabled={
            readOnly || analysisBusy || !replicaPromptReady(state.draft)
          }
          onClick={() => navigate("replacement")}
        >
          下一步：首帧置换
        </Button>
      </footer>
      <input
        accept="video/mp4,video/quicktime"
        aria-label="上传参考视频"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void handleUpload(file);
          event.target.value = "";
        }}
        ref={uploadInputRef}
        type="file"
      />
    </section>
  );
}

export function ReplacementPage() {
  const { state, data, review, patchDraft, navigate, notify, saveDraft, user } =
    useStudio();
  const readOnly = user.role === "auditor";
  const project = data.projects.find(
    (item) => item.id === state.draft.projectId,
  );
  const [characterSelection, setCharacterSelection] =
    useState<ProjectMainCharacter | null>(null);
  const [sourceFrameSelection, setSourceFrameSelection] =
    useState<AnalysisVersion | null>(null);
  const [referenceSelection, setReferenceSelection] =
    useState<CharacterReferenceSelection | null>(null);
  const [referenceError, setReferenceError] = useState("");
  const [referenceMatching, setReferenceMatching] = useState(false);
  const [referenceMatchRevision, setReferenceMatchRevision] = useState(0);
  const [referenceInputRevision, setReferenceInputRevision] = useState(0);
  const [firstFrameSelection, setFirstFrameSelection] =
    useState<AnalysisVersion | null>(null);
  const [leafBusy, setLeafBusy] = useState(false);
  const [sourceDurationSeconds, setSourceDurationSeconds] = useState<
    number | null
  >(null);
  const referenceMatchInFlightRef = useRef<string | undefined>(undefined);
  const referenceRetryScheduledRef = useRef(false);
  const readOnlyRef = useRef(readOnly);
  readOnlyRef.current = readOnly;
  const characterVersionIdRef = useRef<string | null | undefined>(undefined);
  const sourceFrameSelectionIdRef = useRef<string | undefined>(undefined);
  const referenceMatchPromiseRef = useRef<
    | {
        key: string;
        promise: ReturnType<typeof selectCharacterReferences>;
      }
    | undefined
  >(undefined);
  // patchDraft 每次壳层渲染都是新引用，effect 依赖一律走 ref，避免无限置位循环。
  const patchDraftRef = useRef(patchDraft);
  patchDraftRef.current = patchDraft;
  const confirmedSelectionKeyRef = useRef<string | undefined>(undefined);

  const firstFrameAssetId = firstFrameSelection
    ? (readFirstFrameSelectionPayload(firstFrameSelection)
        ?.first_frame_asset_id ?? null)
    : null;

  const clearConfirmedFirstFrame = useCallback(() => {
    if (readOnlyRef.current) return;
    confirmedSelectionKeyRef.current = undefined;
    patchDraftRef.current({
      firstFrameId: undefined,
      firstFrameSelectionVersionId: undefined,
      frameConfirmed: false,
    } as Partial<StudioDraft>);
  }, []);

  // 换项目时重置全部下游状态与草稿中的旧首帧。
  const projectId = project?.id;
  useEffect(() => {
    setCharacterSelection(null);
    setSourceFrameSelection(null);
    setReferenceSelection(null);
    setFirstFrameSelection(null);
    setReferenceError("");
    setReferenceMatching(false);
    referenceMatchInFlightRef.current = undefined;
    referenceRetryScheduledRef.current = false;
    characterVersionIdRef.current = undefined;
    sourceFrameSelectionIdRef.current = undefined;
    confirmedSelectionKeyRef.current = undefined;
    if (projectId && !readOnlyRef.current) {
      patchDraftRef.current({
        firstFrameId: undefined,
        firstFrameSelectionVersionId: undefined,
        frameConfirmed: false,
      } as Partial<StudioDraft>);
    }
  }, [projectId]);

  // 载入拆解时长供源画面取帧边界使用（缺省时叶子组件退化为固定前 2.5 秒）。
  useEffect(() => {
    if (review || !projectId) {
      setSourceDurationSeconds(null);
      return;
    }
    let active = true;
    void getLatestProjectAnalysis(projectId)
      .then((version) => {
        if (active) {
          setSourceDurationSeconds(
            readAnalysisPayload(version)?.duration_seconds ?? null,
          );
        }
      })
      .catch(() => {
        if (active) setSourceDurationSeconds(null);
      });
    return () => {
      active = false;
    };
  }, [review, projectId]);

  const characterVersionId = characterSelection?.character_version_id ?? "";
  const sourceFrameSelectionId = sourceFrameSelection?.id ?? "";
  const referenceSelectionId = referenceSelection?.id ?? "";

  // 人物参考自动匹配：仅业务输入或明确重试变化时重新请求。
  useEffect(() => {
    if (
      review ||
      readOnly ||
      !projectId ||
      !characterVersionId ||
      !sourceFrameSelectionId ||
      referenceSelectionId
    ) {
      setReferenceMatching(false);
      referenceRetryScheduledRef.current = false;
      return;
    }
    const matchKey = `${projectId}:${characterVersionId}:${sourceFrameSelectionId}`;
    const requestKey = `${matchKey}:${referenceInputRevision}:${referenceMatchRevision}`;
    let active = true;
    referenceMatchInFlightRef.current = requestKey;
    setReferenceMatching(true);
    const existing = referenceMatchPromiseRef.current;
    const promise =
      existing?.key === requestKey
        ? existing.promise
        : selectCharacterReferences(projectId, {
            character_version_id: characterVersionId,
            source_frame_selection_version_id: sourceFrameSelectionId,
          });
    referenceMatchPromiseRef.current = { key: requestKey, promise };
    promise
      .then((selection) => {
        if (active) {
          setReferenceSelection(selection);
          setReferenceError("");
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setReferenceError(
            cause instanceof Error ? cause.message : "自动匹配人物参考失败。",
          );
        }
      })
      .finally(() => {
        if (!active) return;
        if (referenceMatchInFlightRef.current === requestKey)
          referenceMatchInFlightRef.current = undefined;
        referenceRetryScheduledRef.current = false;
        setReferenceMatching(false);
      });
    return () => {
      active = false;
      if (referenceMatchInFlightRef.current === requestKey) {
        referenceMatchInFlightRef.current = undefined;
        referenceRetryScheduledRef.current = false;
      }
    };
  }, [
    review,
    readOnly,
    projectId,
    characterVersionId,
    sourceFrameSelectionId,
    referenceSelectionId,
    referenceInputRevision,
    referenceMatchRevision,
  ]);

  // 叶子组件的 effect 依赖回调身份：必须 useCallback 保持稳定，否则引发重取风暴。
  const handleCharacterChange = useCallback(
    (selection: ProjectMainCharacter | null) => {
      const nextVersionId = selection?.character_version_id;
      if (characterVersionIdRef.current === nextVersionId) return;
      characterVersionIdRef.current = nextVersionId;
      setCharacterSelection(selection);
      setReferenceInputRevision((revision) => revision + 1);
      setReferenceSelection(null);
      setReferenceError("");
      setFirstFrameSelection(null);
      clearConfirmedFirstFrame();
    },
    [clearConfirmedFirstFrame],
  );

  const handleSourceFrameChange = useCallback(
    (selection: AnalysisVersion | null) => {
      const nextSelectionId = selection?.id;
      if (sourceFrameSelectionIdRef.current === nextSelectionId) return;
      sourceFrameSelectionIdRef.current = nextSelectionId;
      setSourceFrameSelection(selection);
      setReferenceInputRevision((revision) => revision + 1);
      setReferenceSelection(null);
      setReferenceError("");
      setFirstFrameSelection(null);
      clearConfirmedFirstFrame();
    },
    [clearConfirmedFirstFrame],
  );

  const handleFirstFrameChange = useCallback(
    (selection: AnalysisVersion | null) => {
      setFirstFrameSelection(selection);
      if (readOnlyRef.current) return;
      if (!selection) {
        clearConfirmedFirstFrame();
        return;
      }
      const assetId =
        readFirstFrameSelectionPayload(selection)?.first_frame_asset_id;
      if (!assetId) {
        clearConfirmedFirstFrame();
        return;
      }
      const selectionKey = `${selection.id}:${assetId}`;
      if (confirmedSelectionKeyRef.current === selectionKey) return;
      confirmedSelectionKeyRef.current = selectionKey;
      patchDraftRef.current({
        firstFrameId: assetId,
        firstFrameSelectionVersionId: selection.id,
        frameConfirmed: true,
      });
    },
    [clearConfirmedFirstFrame],
  );

  const retryReferenceMatch = () => {
    if (
      readOnly ||
      referenceMatching ||
      referenceMatchInFlightRef.current ||
      referenceRetryScheduledRef.current
    )
      return;
    referenceRetryScheduledRef.current = true;
    setReferenceError("");
    setReferenceMatchRevision((revision) => revision + 1);
  };

  const firstFrameReady = Boolean(firstFrameAssetId);
  const promptReady = replicaPromptReady(state.draft);

  return (
    <section className="creation-page creation-replacement">
      <CreationNavigation />
      <ReplicaWorkflowNavigation />
      {!project ? (
        <Panel className="creation-empty-workspace">
          <Empty
            title="先在视频复刻中准备好项目"
            description="人物替换需要一个已完成 AI 拆解的项目：选择下方项目即可开始提取源画面并生成置换首帧。"
            action={
              data.projects.length > 0 ? (
                <select
                  aria-label="选择项目"
                  className="creation-project-select"
                  defaultValue=""
                  disabled={readOnly}
                  onChange={(event) => {
                    if (readOnly) return;
                    const selected = data.projects.find(
                      (item) => item.id === event.target.value,
                    );
                    if (selected) {
                      patchDraft({ projectId: selected.id });
                      notify(`已切换到项目「${selected.name}」。`);
                    }
                  }}
                >
                  <option value="" disabled>
                    选择已有项目
                  </option>
                  {data.projects
                    .filter((item) => item.analysis_status === "READY")
                    .map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                </select>
              ) : undefined
            }
          />
        </Panel>
      ) : review ? (
        <Panel className="creation-empty-workspace">
          <Empty
            title="人物替换（审核示例）"
            description="确认源画面 → 选择场景形象与图片画幅 → 生成并确认置换首帧。"
          />
        </Panel>
      ) : (
        <>
          <div className="creation-replacement-grid">
            <Panel className="creation-replacement-step">
              <div className="creation-panel-title">01 原视频首帧</div>
              <SourceFrameSelection
                onBusyChange={setLeafBusy}
                onSelectionChange={handleSourceFrameChange}
                projectId={project.id}
                readOnly={readOnly}
                referenceAssetId={project.reference_asset_id}
                simplified
                videoDurationSeconds={sourceDurationSeconds}
              />
            </Panel>
            <Panel className="creation-replacement-step">
              <div className="creation-panel-title">
                02 替换设置 · 人物与形象
              </div>
              <CharacterSelection
                sceneOnly
                onBusyChange={setLeafBusy}
                onVersionChange={handleCharacterChange}
                projectId={project.id}
                readOnly={readOnly}
                variant="inline"
              />
            </Panel>
            <Panel className="creation-replacement-step">
              <div className="creation-panel-title">03 新首图 · 生成与采用</div>
              {referenceError ? (
                <>
                  <p className="settings-error" role="alert">
                    {referenceError}
                  </p>
                  <Button
                    disabled={readOnly || referenceMatching}
                    onClick={retryReferenceMatch}
                    variant="outline"
                  >
                    重试匹配人物参考
                  </Button>
                </>
              ) : null}
              {characterSelection && sourceFrameSelection ? (
                <FirstFrameSelection
                  onBusyChange={setLeafBusy}
                  onSelectionChange={handleFirstFrameChange}
                  projectId={project.id}
                  readOnly={readOnly}
                  referenceSelection={referenceSelection}
                  simplified
                  sourceFrameSelectionId={sourceFrameSelection.id}
                />
              ) : (
                <Empty
                  title="等待前置步骤"
                  description="选择场景形象并确认源画面后，即可替换原视频中的人物。"
                />
              )}
            </Panel>
          </div>
          <Panel className="creation-handoff">
            <div>
              <strong>新的复刻提示词</strong>
              <Hint>
                {promptReady
                  ? "已就绪 · 来自最新口播与拆解"
                  : "请返回内容配置，生成最新提示词"}
              </Hint>
            </div>
            <div>
              <strong>采用的新首图</strong>
              <Hint>
                {firstFrameReady
                  ? "已确认 · 将作为图生视频首帧"
                  : "等待生成并采用新首图"}
              </Hint>
            </div>
            <Button
              variant="primary"
              disabled={
                readOnly ||
                leafBusy ||
                referenceMatching ||
                !promptReady ||
                !firstFrameReady
              }
              onClick={() => {
                if (readOnly || !promptReady || !firstFrameReady) return;
                patchDraft({
                  firstFrameId: firstFrameAssetId ?? undefined,
                  firstFrameSelectionVersionId: firstFrameSelection?.id,
                  frameConfirmed: true,
                  replicaPreparationPending: false,
                });
                navigate("video");
              }}
            >
              带入视频生成
            </Button>
          </Panel>
        </>
      )}
      <footer className="creation-action-bar">
        <div>
          <strong>源画面 + 场景形象 → 置换首帧</strong>
          <Hint>新提示词和已采用首帧一起传递，下一页设置参数。</Hint>
        </div>
        <Button
          variant="outline"
          disabled={readOnly}
          onClick={() => {
            if (readOnly) return;
            saveDraft();
          }}
        >
          保存草稿
        </Button>
      </footer>
    </section>
  );
}

const ratios = ["自动", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"];
const assetKindNames: Record<StudioAsset["kind"], string> = {
  image: "图片",
  video: "视频",
  audio: "音频",
};

function ParameterControls() {
  const { state, patchDraft, user } = useStudio();
  const readOnly = user.role === "auditor";
  const draft = state.draft;
  return (
    <div className="creation-parameters creation-parameters--inline">
      <Field label="分辨率">
        <select
          aria-label="分辨率"
          disabled={readOnly}
          value={draft.resolution}
          onChange={(event) => patchDraft({ resolution: event.target.value })}
        >
          <option value="768P">768P</option>
          <option value="2K">2K</option>
        </select>
      </Field>
      <Field label="时长">
        <select
          aria-label="时长"
          disabled={readOnly}
          value={draft.duration}
          onChange={(event) =>
            patchDraft({ duration: Number(event.target.value) })
          }
        >
          {Array.from({ length: 12 }, (_, i) => i + 4).map((seconds) => (
            <option key={seconds} value={seconds}>
              {seconds} 秒
            </option>
          ))}
        </select>
      </Field>
      <Field label="画面比例">
        <select
          aria-label="画面比例"
          disabled={readOnly}
          value={draft.ratio}
          onChange={(event) => patchDraft({ ratio: event.target.value })}
        >
          {ratios.map((ratio) => (
            <option key={ratio} value={ratio}>
              {ratio}
            </option>
          ))}
        </select>
      </Field>
      <Field label="生成数量">
        <select
          aria-label="生成数量"
          disabled={readOnly}
          value={draft.count}
          onChange={(event) =>
            patchDraft({ count: Number(event.target.value) })
          }
        >
          {[1, 2, 4].map((count) => (
            <option key={count} value={count}>
              {count} 个
            </option>
          ))}
        </select>
      </Field>
    </div>
  );
}

// 生成等待期的安抚文案：按阶段轮换，降低等待焦虑（不伪造进度）。
const REASSURANCE_COPY = [
  "AI 正在理解你的提示词与画面结构…",
  "视频生成通常需要 1–3 分钟，可以先去处理其他创作。",
  "任务已进入公平队列，关掉页面也不会丢失进度。",
  "生成完成后可以直接在下方预览成片。",
];

const VIDEO_STAGE_LABELS = ["已提交", "排队中", "生成中", "完成"] as const;

function videoStageIndex(status: StudioTask["status"]): number {
  if (status === "queued") return 1;
  if (status === "running") return 2;
  if (status === "completed") return 3;
  return 0;
}

function formatElapsed(from: string): string {
  // 只给无时区的服务端 UTC 文本补 Z，保留 ISO 时间已有的偏移量。
  const normalized = from.replace(" ", "T").replace(/([+-]\d{2})$/, "$1:00");
  const started = new Date(
    /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized) ? normalized : `${normalized}Z`,
  ).getTime();
  if (Number.isNaN(started)) return "";
  const seconds = Math.max(0, Math.round((Date.now() - started) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes} 分 ${seconds % 60} 秒` : `${seconds} 秒`;
}

/** 生成等待视图：阶段时间线 + 进度百分比 + 轮换安抚文案。 */
function VideoProgressView({ task }: { task: StudioTask }) {
  const [copyIndex, setCopyIndex] = useState(0);
  const [, setTick] = useState(0);
  const failed = task.status === "failed" || task.status === "uncertain";
  const completed = task.status === "completed";
  const cancelled = task.status === "cancelled";

  useEffect(() => {
    if (failed || completed || cancelled) return;
    const timer = window.setInterval(() => {
      setCopyIndex((value) => (value + 1) % REASSURANCE_COPY.length);
      setTick((value) => value + 1);
    }, 6000);
    return () => window.clearInterval(timer);
  }, [failed, completed, cancelled]);

  if (cancelled) {
    return (
      <div className="creation-progress" role="status">
        <div className="creation-progress-headline">任务已取消</div>
        <p className="creation-progress-copy">
          本次任务已结束，计费结果可在账户流水中查看。
        </p>
      </div>
    );
  }

  if (failed) {
    return (
      <div className="creation-progress failed" role="alert">
        <div className="creation-progress-headline">
          生成未完成{task.status === "uncertain" ? "（状态待确认）" : ""}
        </div>
        <p className="creation-progress-copy">
          积分未结算的失败不会扣费；可在任务中心重试或对账。
        </p>
        <Empty
          title="这条视频没有生成成功"
          description="可回到上方调整提示词或素材后重新生成。"
        />
      </div>
    );
  }

  const stageIndex = videoStageIndex(task.status);
  const progress = task.progress ?? 0;

  return (
    <div className="creation-progress" aria-live="polite">
      <ol className="creation-progress-stages">
        {VIDEO_STAGE_LABELS.map((label, index) => (
          <li
            key={label}
            className={
              index === stageIndex
                ? "is-active"
                : index < stageIndex
                  ? "is-done"
                  : ""
            }
          >
            {label}
          </li>
        ))}
      </ol>
      <progress
        aria-label="生成进度"
        className="creation-progress-bar"
        max={100}
        value={task.status === "completed" ? 100 : progress}
      />
      <div className="creation-progress-meta">
        <span>{task.status === "completed" ? "生成完成" : `${progress}%`}</span>
        {!completed && formatElapsed(task.submitted) ? (
          <span>已等待 {formatElapsed(task.submitted)}</span>
        ) : null}
      </div>
      <p className="creation-progress-copy">
        {completed
          ? "成片已生成，可以查看、播放或下载。"
          : REASSURANCE_COPY[copyIndex]}
      </p>
    </div>
  );
}

function SavedPromptImporter({
  onImport,
}: {
  onImport: (
    promptText: string,
    context?: SavedPromptItem["generation_context"],
  ) => void;
}) {
  const [open, setOpen] = useState(false);
  const [prompts, setPrompts] = useState<SavedPromptItem[]>();
  const [error, setError] = useState<string>();
  const { review, notify, user } = useStudio();
  const readOnly = user.role === "auditor";

  const toggle = () => {
    if (readOnly) return;
    const next = !open;
    setOpen(next);
    if (next && prompts === undefined && !error && !review) {
      void listUserSavedPrompts()
        .then(setPrompts)
        .catch(() => setError("我的提示词暂时读取失败，请稍后重试。"));
    }
  };

  return (
    <div className="creation-prompt-import">
      <Button variant="quiet" disabled={readOnly} onClick={toggle}>
        <Icon name="arrow" size={16} /> 导入提示词
      </Button>
      {open && (
        <div
          className="creation-prompt-list"
          role="listbox"
          aria-label="我的提示词"
        >
          {review ? (
            <p>审核示例不提供提示词库。</p>
          ) : error ? (
            <p>{error}</p>
          ) : prompts === undefined ? (
            <p>正在读取我的提示词…</p>
          ) : prompts.length === 0 ? (
            <p>
              还没有保存过提示词。在项目拆解中修订反推提示词并保存后会出现在这里。
            </p>
          ) : (
            prompts.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  onImport(item.prompt_text, item.generation_context);
                  notify(`已导入「${item.name}」，可继续修改。`);
                  setOpen(false);
                }}
              >
                <strong>{item.name}</strong>
                <small>{item.prompt_text.slice(0, 60)}</small>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

type UploadKind = "image" | "video" | "audio";

const UPLOAD_ACCEPT: Record<UploadKind, string[]> = {
  image: ["image/png", "image/jpeg"],
  video: ["video/mp4", "video/quicktime"],
  audio: ["audio/mpeg"],
};

function VideoMaterialUpload({
  disabled = false,
  dropzone = false,
  group,
  label,
  acceptKinds = ["image"],
  onUploaded,
}: {
  disabled?: boolean;
  dropzone?: boolean;
  group: string;
  label: string;
  acceptKinds?: UploadKind[];
  onUploaded: (asset: StudioAsset) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number>();
  const uploadingRef = useRef(false);
  const [dragOver, setDragOver] = useState(false);
  const { review, notify, user } = useStudio();
  const readOnly = user.role === "auditor";
  const onUploadedRef = useRef(onUploaded);
  const mountedRef = useRef(false);
  onUploadedRef.current = onUploaded;
  const acceptsMedia =
    acceptKinds.includes("video") || acceptKinds.includes("audio");

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const upload = async (file: File) => {
    if (readOnly || disabled || uploadingRef.current) return;
    const kind = acceptKinds.find((item) =>
      UPLOAD_ACCEPT[item].includes(file.type),
    );
    if (!kind) {
      notify(
        acceptsMedia
          ? "仅支持 PNG、JPEG 图片，MP4、MOV 视频或 MP3 音频。"
          : "仅支持 PNG 或 JPEG 图片。",
      );
      return;
    }
    if (review) {
      notify("审核示例不上传素材。");
      return;
    }
    uploadingRef.current = true;
    setProgress(0);
    try {
      let asset: StudioAsset;
      if (kind === "image") {
        asset = await uploadVideoMaterial(file, group, setProgress);
      } else {
        // 视频/音频参考上传前先探测时长，超过 15 秒直接拦截、不发上传请求。
        const duration =
          kind === "video"
            ? await readVideoDuration(file)
            : await readAudioDuration(file);
        if (duration > MAX_REFERENCE_MEDIA_SECONDS) {
          if (mountedRef.current)
            notify(
              kind === "video"
                ? "参考视频时长不能超过 15 秒，请裁剪后再上传。"
                : "参考音频时长不能超过 15 秒，请裁剪后再上传。",
            );
          return;
        }
        asset =
          kind === "video"
            ? await uploadVideoMaterial(file, group, setProgress)
            : await uploadReferenceAudioMaterial(file, duration, setProgress);
      }
      if (mountedRef.current) {
        onUploadedRef.current(asset);
        notify(`${label}「${file.name}」已上传到素材库。`);
      }
    } catch {
      if (mountedRef.current) notify("素材上传失败，请稍后重试。");
    } finally {
      uploadingRef.current = false;
      if (mountedRef.current) setProgress(undefined);
    }
  };

  return (
    <>
      <button
        className={
          dropzone
            ? `creation-upload-dropzone ${dragOver ? "is-dragging" : ""}`
            : "creation-upload-mini"
        }
        aria-label={dropzone ? "上传文件" : undefined}
        onDragOver={(event) => {
          if (!dropzone) return;
          event.preventDefault();
          if (!readOnly && !disabled) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(event) => {
          if (!dropzone) return;
          event.preventDefault();
          setDragOver(false);
          if (readOnly || disabled || uploadingRef.current) return;
          const files = event.dataTransfer.files;
          if (files.length !== 1) {
            notify("请每次添加一个文件，便于核对参考素材编号。");
            return;
          }
          void upload(files[0]);
        }}
        disabled={readOnly || disabled || progress !== undefined}
        onClick={() => inputRef.current?.click()}
        type="button"
      >
        {dropzone && <Icon name="plus" size={38} />}
        <span>
          {progress !== undefined
            ? `上传中 ${progress}%`
            : dropzone
              ? "上传文件"
              : "本机上传"}
        </span>
        {dropzone && <small>点击或拖拽添加</small>}
      </button>
      <input
        accept={acceptKinds.flatMap((item) => UPLOAD_ACCEPT[item]).join(",")}
        aria-label={`上传${label}`}
        disabled={readOnly || disabled}
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void upload(file);
          event.target.value = "";
        }}
        ref={inputRef}
        type="file"
      />
      {acceptsMedia && (
        <small className="creation-upload-hint">
          视频、音频各累计 ≤15 秒；参考合计 ≤12 项
        </small>
      )}
    </>
  );
}

export function VideoPage() {
  const {
    state,
    data,
    patchDraft,
    navigate,
    openPicker,
    saveDraft,
    requestGeneration,
    updateData,
    notify,
    review,
    videoCapabilities,
    videoCapabilitiesStatus,
    retryVideoCapabilities,
    referenceAssetsPending,
    referenceAssetsError,
    retryReferenceAssets,
    user,
  } = useStudio();
  const readOnly = user.role === "auditor";
  const [previewReferenceId, setPreviewReferenceId] = useState<string>();
  const referenceMode = state.page === "reference";
  const storedFirstFrame =
    findAsset(data.assets, state.draft.firstFrameId) ??
    findAsset(data.materials, state.draft.firstFrameId);
  const [resolvedFirstFrame, setResolvedFirstFrame] = useState<StudioAsset>();
  const [firstFrameLoading, setFirstFrameLoading] = useState(false);
  const [firstFrameError, setFirstFrameError] = useState("");
  const [firstFrameLoadAttempt, setFirstFrameLoadAttempt] = useState(0);
  const firstFrameRequestRef = useRef(0);
  const firstFramePromiseRef = useRef<
    | {
        key: string;
        promise: ReturnType<typeof getAssetDownloadUrl>;
      }
    | undefined
  >(undefined);
  const firstFrameId = state.draft.firstFrameId;
  const usableStoredFirstFrame =
    storedFirstFrame?.kind === "image" && storedFirstFrame.url
      ? storedFirstFrame
      : undefined;
  const firstFrame =
    usableStoredFirstFrame ??
    (resolvedFirstFrame?.id === firstFrameId ? resolvedFirstFrame : undefined);

  useEffect(() => {
    const requestId = ++firstFrameRequestRef.current;
    if (referenceMode || review || !firstFrameId || usableStoredFirstFrame) {
      setResolvedFirstFrame(undefined);
      setFirstFrameLoading(false);
      setFirstFrameError("");
      return;
    }

    setResolvedFirstFrame(undefined);
    setFirstFrameLoading(true);
    setFirstFrameError("");
    const key = `${firstFrameId}:${firstFrameLoadAttempt}`;
    const existing = firstFramePromiseRef.current;
    const promise =
      existing?.key === key
        ? existing.promise
        : getAssetDownloadUrl(firstFrameId);
    firstFramePromiseRef.current = { key, promise };

    void promise
      .then(({ url }) => {
        if (firstFrameRequestRef.current !== requestId) return;
        const asset: StudioAsset = {
          ...storedFirstFrame,
          id: firstFrameId,
          assetId: storedFirstFrame?.assetId ?? firstFrameId,
          name: storedFirstFrame?.name ?? "已确认置换首帧",
          kind: "image",
          url,
          group: storedFirstFrame?.group ?? "置换首帧",
          source: storedFirstFrame?.source ?? "人物置换",
          saved: true,
          delivery: storedFirstFrame?.delivery ?? "stored",
        };
        setResolvedFirstFrame(asset);
        setFirstFrameLoading(false);
        updateData((previous) => ({
          ...previous,
          assets: [
            asset,
            ...previous.assets.filter((item) => item.id !== asset.id),
          ],
        }));
      })
      .catch((cause: unknown) => {
        if (firstFrameRequestRef.current !== requestId) return;
        setFirstFrameLoading(false);
        setFirstFrameError(
          customerVisibleErrorMessage(cause, "首帧预览读取失败，请重试。"),
        );
      });

    return () => {
      if (firstFrameRequestRef.current === requestId)
        firstFrameRequestRef.current += 1;
    };
  }, [
    firstFrameId,
    firstFrameLoadAttempt,
    referenceMode,
    review,
    storedFirstFrame,
    updateData,
    usableStoredFirstFrame,
  ]);
  const tailFrame =
    findAsset(data.assets, state.draft.tailFrameId) ??
    findAsset(data.materials, state.draft.tailFrameId);
  const referenceValidation = validateReferences(
    state.draft.referenceIds,
    [...data.assets, ...data.materials],
    {
      maxReferenceImages:
        videoCapabilities?.max_reference_images ?? DEFAULT_MAX_REFERENCE_IMAGES,
      maxReferenceVideos:
        videoCapabilities?.max_reference_videos ?? DEFAULT_MAX_REFERENCE_VIDEOS,
      maxReferenceAudios:
        videoCapabilities?.max_reference_audios ?? DEFAULT_MAX_REFERENCE_AUDIOS,
    },
  );
  const references = referenceValidation.assets;
  const effectiveCapabilitiesStatus = review
    ? "ready"
    : (videoCapabilitiesStatus ?? (videoCapabilities ? "ready" : "loading"));
  const videoCapabilityPending =
    !referenceMode && effectiveCapabilitiesStatus === "loading";
  const videoCapabilityError =
    !referenceMode && effectiveCapabilitiesStatus === "error";
  const videoModeDisabled =
    !referenceMode &&
    !review &&
    (firstFrameId
      ? videoCapabilities?.i2v_enabled === false
      : videoCapabilities?.t2v_enabled === false);
  const referenceCapabilityPending =
    referenceMode && effectiveCapabilitiesStatus === "loading";
  const referenceCapabilityError =
    referenceMode && effectiveCapabilitiesStatus === "error";
  const referenceModeDisabled =
    referenceMode && !review && videoCapabilities?.r2v_enabled === false;
  const referenceHasIssues =
    !referenceAssetsPending &&
    !referenceAssetsError &&
    referenceValidation.issues.length > 0;
  const referenceAtLimit =
    !referenceHasIssues &&
    referenceValidation.imageCount >= referenceValidation.imageLimit &&
    referenceValidation.videoCount >= referenceValidation.videoLimit &&
    referenceValidation.audioCount >= referenceValidation.audioLimit;
  const ready =
    Boolean(state.draft.prompt.trim()) &&
    !state.draft.replicaPreparationPending &&
    (referenceMode
      ? references.length > 0 &&
        !referenceCapabilityPending &&
        !referenceCapabilityError &&
        !referenceModeDisabled &&
        !referenceHasIssues &&
        !referenceAssetsPending &&
        !referenceAssetsError
      : !videoCapabilityPending &&
        !videoCapabilityError &&
        !videoModeDisabled &&
        (!firstFrameId || Boolean(firstFrame)));
  const videoTask = state.draft.videoBatchId
    ? data.tasks.find((task) => task.id === state.draft.videoBatchId)
    : undefined;

  const appendMaterial = (asset: StudioAsset) => {
    updateData((previous) => ({
      ...previous,
      materials: [
        asset,
        ...previous.materials.filter((item) => item.id !== asset.id),
      ],
    }));
  };

  const addReference = (asset: StudioAsset) => {
    appendMaterial(asset);
    if (referenceHasIssues) {
      notify("请先整理旧草稿中的无效参考素材。");
      return;
    }
    if (state.draft.referenceIds.includes(asset.id)) {
      notify("该参考素材已选择，请勿重复添加。");
      return;
    }
    const atKindLimit =
      asset.kind === "image"
        ? referenceValidation.imageCount >= referenceValidation.imageLimit
        : asset.kind === "video"
          ? referenceValidation.videoCount >= referenceValidation.videoLimit
          : referenceValidation.audioCount >= referenceValidation.audioLimit;
    if (atKindLimit) {
      notify(
        asset.kind === "image"
          ? `当前最多选择 ${referenceValidation.imageLimit} 张参考图。`
          : asset.kind === "video"
            ? `当前最多选择 ${referenceValidation.videoLimit} 个参考视频。`
            : `当前最多选择 ${referenceValidation.audioLimit} 个参考音频。`,
      );
      return;
    }
    patchDraft({
      referenceIds: [...state.draft.referenceIds, asset.id],
    });
  };

  const generationActions = (
    <div className="creation-form-actions">
      <Button
        variant="outline"
        disabled={readOnly}
        onClick={() => !readOnly && saveDraft()}
      >
        保存草稿
      </Button>
      <Button
        variant="primary"
        disabled={readOnly || !ready}
        onClick={() => requestGeneration("视频生成")}
      >
        <Icon name="play" />
        生成视频
      </Button>
    </div>
  );

  return (
    <section
      className="creation-page creation-video-workspace creation-video-workspace--split"
      aria-label="AI 视频"
    >
      <CreationNavigation />
      <Tabs
        items={[
          { id: "video", label: "文/图生视频" },
          { id: "reference", label: "参考生视频" },
        ]}
        value={referenceMode ? "reference" : "video"}
        onChange={(value) =>
          navigate(value === "reference" ? "reference" : "video")
        }
      />
      <div
        className={`creation-video-grid ${referenceMode ? "reference" : ""}`}
      >
        <Panel className="creation-video-form">
          {referenceMode ? (
            <ControlGroup
              label={
                <>
                  <b className="creation-step-number">01</b> 参考素材
                </>
              }
            >
              <div className="creation-upload-row">
                <button
                  className="creation-upload"
                  disabled={
                    readOnly ||
                    referenceCapabilityPending ||
                    referenceCapabilityError ||
                    referenceModeDisabled ||
                    referenceHasIssues ||
                    referenceAssetsPending ||
                    referenceAssetsError ||
                    referenceAtLimit
                  }
                  onClick={() => openPicker("reference")}
                  type="button"
                >
                  <Icon name="upload" />
                  <span>从素材库选择</span>
                  <small>
                    {referenceAtLimit
                      ? "已达参考素材上限，需移除后才能继续添加。"
                      : `参考图 ${referenceValidation.imageCount}/${referenceValidation.imageLimit} · 视频 ${referenceValidation.videoCount}/${referenceValidation.videoLimit} · 音频 ${referenceValidation.audioCount}/${referenceValidation.audioLimit}`}
                  </small>
                </button>
              </div>
              {referenceCapabilityPending && (
                <p className="settings-error" role="status">
                  正在读取参考生视频能力，请稍候。
                </p>
              )}
              {referenceCapabilityError && (
                <div>
                  <p className="settings-error" role="alert">
                    视频生成能力读取失败，请重试。
                  </p>
                  <Button onClick={retryVideoCapabilities} variant="outline">
                    重试读取视频能力
                  </Button>
                </div>
              )}
              {referenceAssetsPending && (
                <p className="settings-error" role="status">
                  正在恢复草稿参考图，请稍候。
                </p>
              )}
              {referenceAssetsError && (
                <div>
                  <p className="settings-error" role="alert">
                    草稿参考图读取失败，请重试。
                  </p>
                  <Button onClick={retryReferenceAssets} variant="outline">
                    重试读取草稿参考图
                  </Button>
                </div>
              )}
              {referenceModeDisabled && (
                <div>
                  <p className="settings-error" role="alert">
                    参考生视频当前未开放，请等待能力开启后再提交。
                  </p>
                  <Button onClick={retryVideoCapabilities} variant="outline">
                    刷新开放状态
                  </Button>
                </div>
              )}
              {!referenceAssetsPending &&
                !referenceAssetsError &&
                referenceValidation.issues.map((issue) => (
                  <p className="settings-error" key={issue} role="alert">
                    {issue}
                  </p>
                ))}
              {referenceHasIssues && (
                <Button
                  disabled={readOnly}
                  onClick={() =>
                    !readOnly &&
                    patchDraft({ referenceIds: referenceValidation.repairIds })
                  }
                  variant="outline"
                >
                  整理参考素材
                </Button>
              )}
              <div className="creation-reference-materials">
                <div className="creation-reference-list">
                  {references.map((asset, index) => (
                    <div className="creation-reference-row" key={asset.id}>
                      <button
                        type="button"
                        className="creation-reference-preview-button"
                        aria-label={`预览 ${asset.name}`}
                        aria-pressed={previewReferenceId === asset.id}
                        onClick={() => setPreviewReferenceId(asset.id)}
                      >
                        <Media
                          asset={
                            asset.kind === "image"
                              ? asset
                              : asset.kind === "video" && asset.poster
                                ? { ...asset, kind: "image", url: asset.poster }
                                : undefined
                          }
                          aspectRatio={state.draft.ratio}
                          alt={asset.kind === "audio" ? "音频预览" : asset.name}
                        />
                      </button>
                      <span className="creation-reference-copy">
                        <strong>
                          @{index + 1} → &lt;
                          {asset.kind === "image"
                            ? "Picture"
                            : asset.kind === "video"
                              ? "Video"
                              : "Audio"}{" "}
                          {
                            references
                              .slice(0, index + 1)
                              .filter((item) => item.kind === asset.kind).length
                          }
                          &gt; {asset.name}
                        </strong>
                        <small>
                          {assetKindNames[asset.kind]} · {asset.source}
                        </small>
                      </span>
                      <input
                        aria-label={`${asset.name}的参考用途`}
                        placeholder="参考用途，如人物、服装、场景"
                        disabled={readOnly}
                        value={state.draft.referencePurposes?.[asset.id] ?? ""}
                        maxLength={200}
                        onChange={(event) =>
                          patchDraft({
                            referencePurposes: {
                              ...state.draft.referencePurposes,
                              [asset.id]: event.target.value,
                            },
                          })
                        }
                      />
                      <Button
                        aria-label={`移除 ${asset.name}`}
                        className="creation-reference-remove"
                        disabled={readOnly}
                        onClick={() =>
                          patchDraft({
                            referenceIds: state.draft.referenceIds.filter(
                              (id) => id !== asset.id,
                            ),
                          })
                        }
                        variant="quiet"
                      >
                        <Icon name="close" size={18} />
                      </Button>
                    </div>
                  ))}
                </div>
                <VideoMaterialUpload
                  key={`reference-upload-${state.draft.id}`}
                  disabled={
                    readOnly ||
                    referenceCapabilityPending ||
                    referenceCapabilityError ||
                    referenceModeDisabled ||
                    referenceHasIssues ||
                    referenceAssetsPending ||
                    referenceAssetsError ||
                    referenceAtLimit
                  }
                  acceptKinds={["image", "video", "audio"]}
                  dropzone
                  group="参考素材"
                  label="参考素材"
                  onUploaded={addReference}
                />
              </div>
            </ControlGroup>
          ) : (
            <ControlGroup
              label={
                <span className="creation-frame-heading">
                  <b className="creation-step-number">01</b> 首尾帧
                  <small>无首帧时文生视频；添加首帧后图生视频。</small>
                </span>
              }
            >
              {videoCapabilityPending && (
                <p role="status">正在读取视频生成能力，请稍候。</p>
              )}
              {videoCapabilityError && (
                <div>
                  <p className="settings-error" role="alert">
                    视频生成能力读取失败，请重试。
                  </p>
                  <Button onClick={retryVideoCapabilities} variant="outline">
                    重试读取视频能力
                  </Button>
                </div>
              )}
              {videoModeDisabled && !videoCapabilityError && (
                <div>
                  <p className="settings-error" role="alert">
                    {firstFrameId
                      ? "图生视频当前未开放，请等待能力开启后再提交。"
                      : "文生视频当前未开放，可添加首帧使用图生视频。"}
                  </p>
                  <Button onClick={retryVideoCapabilities} variant="outline">
                    刷新开放状态
                  </Button>
                </div>
              )}
              <div className="creation-frame-row">
                <div className="creation-frame-slot">
                  <button
                    disabled={readOnly}
                    onClick={() => openPicker("first-frame")}
                    type="button"
                  >
                    <Media
                      asset={firstFrame}
                      alt="首帧"
                      presentation="video"
                      aspectRatio={state.draft.ratio}
                    />
                    <span>首帧（选填）</span>
                  </button>
                  {firstFrameId && (
                    <Button
                      variant="quiet"
                      disabled={readOnly}
                      onClick={() => patchDraft({ firstFrameId: undefined })}
                    >
                      移除首帧
                    </Button>
                  )}
                  <VideoMaterialUpload
                    group="首帧素材"
                    label="首帧"
                    onUploaded={(asset) => {
                      appendMaterial(asset);
                      patchDraft({ firstFrameId: asset.id });
                    }}
                  />
                </div>
                <Icon name="arrow" />
                <div className="creation-frame-slot">
                  <button
                    disabled={readOnly}
                    onClick={() => openPicker("tail-frame")}
                    type="button"
                  >
                    <Media
                      asset={tailFrame}
                      alt="尾帧"
                      presentation="video"
                      aspectRatio={state.draft.ratio}
                    />
                    <span>尾帧（可选）</span>
                  </button>
                  {state.draft.tailFrameId && (
                    <Button
                      variant="quiet"
                      disabled={readOnly}
                      onClick={() => patchDraft({ tailFrameId: undefined })}
                    >
                      移除尾帧
                    </Button>
                  )}
                  <VideoMaterialUpload
                    group="尾帧素材"
                    label="尾帧"
                    onUploaded={(asset) => {
                      appendMaterial(asset);
                      patchDraft({ tailFrameId: asset.id });
                    }}
                  />
                </div>
              </div>
            </ControlGroup>
          )}
        </Panel>
        <Panel className="creation-video-composer">
          {state.draft.replicaPreparationPending && (
            <div role="status" className="creation-inline-error">
              <span>复刻准备尚未完成，请先交接新提示词与采用首帧。</span>
              <Button variant="outline" onClick={() => navigate("replica")}>
                返回复刻准备
              </Button>
            </div>
          )}
          <PromptEditor
            label="提示词"
            rows={5}
            showToolbarLabel
            toolbarLabel={
              <>
                <b className="creation-step-number">02</b> 画面描述
              </>
            }
            toolbarStart={
              <SavedPromptImporter
                onImport={(promptText, context) =>
                  patchDraft({
                    prompt: promptText,
                    importedPromptContext: context,
                    promptBindingsStale:
                      /<(Picture|Video|Audio)\s+\d+>|@\d+/.test(promptText),
                  })
                }
              />
            }
            value={state.draft.prompt}
            readOnly={readOnly}
            optimizationDisabled={review}
            scope={`${user.id}:${state.page}`}
            onChange={(text) =>
              patchDraft({ prompt: text, promptEdited: true })
            }
            placeholder="描述镜头、场景、运动与光线"
            context={{
              route: referenceMode ? "reference" : "text_image",
              duration_seconds: state.draft.duration,
              ratio: state.draft.ratio as GenerationRatio,
              first_frame_asset_id: referenceMode
                ? undefined
                : state.draft.firstFrameId,
              last_frame_asset_id: referenceMode
                ? undefined
                : state.draft.tailFrameId,
              references: referenceMode
                ? references.map((asset) => ({
                    asset_id: asset.assetId ?? asset.id,
                    purpose:
                      state.draft.referencePurposes?.[asset.id] ||
                      "unspecified",
                  }))
                : [],
            }}
          />
          {state.draft.promptBindingsStale && (
            <div role="alert">
              参考素材已变化，请核对提示词的素材编号。
              <Button
                onClick={() => patchDraft({ promptBindingsStale: false })}
                disabled={readOnly}
              >
                已核对当前素材绑定
              </Button>
            </div>
          )}
          {state.draft.importedPromptContext && (
            <small>
              模板模式：{state.draft.importedPromptContext.mode ?? "未记录"}。
              {(state.draft.importedPromptContext.generation_assets ?? [])
                .map((asset) => `${asset.label}：${asset.purpose}`)
                .join("；")}
              请按当前素材重新核对引用。
            </small>
          )}
        </Panel>

        <Panel className="creation-video-controls">
          <div className="creation-panel-title">
            <span className="creation-step-number">03</span> 生成参数
          </div>
          <ParameterControls />
        </Panel>
        <Panel className="creation-video-preview">
          <div className="creation-panel-title">
            {referenceMode ? "参考预览" : "首帧预览"}
            <small className="creation-preview-ratio">
              {state.draft.ratio === "adaptive" ? "自动" : state.draft.ratio}
            </small>
          </div>
          {!referenceMode && firstFrameLoading ? (
            <Empty
              title="正在加载首帧预览"
              description="正在读取已确认置换首帧的签名地址。"
            />
          ) : !referenceMode && firstFrameError ? (
            <Empty
              title="首帧预览加载失败"
              description={firstFrameError}
              action={
                <Button
                  variant="outline"
                  onClick={() =>
                    setFirstFrameLoadAttempt((attempt) => attempt + 1)
                  }
                >
                  重试加载首帧
                </Button>
              }
            />
          ) : videoTask ? (
            <>
              <VideoProgressView task={videoTask} />
              {videoTask.status === "completed" ? (
                <Button
                  variant="primary"
                  onClick={() =>
                    navigate("task-detail", {
                      selectedTaskId: videoTask.id,
                      selectedTaskKind: videoTask.backendKind,
                      selectedTaskBackendId:
                        videoTask.backendId ??
                        videoTask.batchId ??
                        videoTask.id,
                      returnTo: state.page,
                    })
                  }
                >
                  查看成片
                </Button>
              ) : null}
            </>
          ) : referenceMode ? (
            references.length ? (
              <Media
                asset={
                  references.find((asset) => asset.id === previewReferenceId) ??
                  references[0]
                }
                alt="参考画布"
                className="creation-preview-media"
                aspectRatio={state.draft.ratio}
                presentation="video"
              />
            ) : (
              <Media
                alt="还没有参考素材"
                className="creation-preview-media"
                aspectRatio={state.draft.ratio}
                fallback={
                  <Empty
                    title="还没有参考素材"
                    description="设置参考素材与参数后再生成视频。"
                  />
                }
              />
            )
          ) : firstFrame ? (
            <Media
              asset={firstFrame}
              alt="首帧预览"
              className="creation-preview-media"
              aspectRatio={state.draft.ratio}
              presentation="video"
            />
          ) : (
            <Media
              alt="当前为文生视频"
              className="creation-preview-media"
              aspectRatio={state.draft.ratio}
              fallback={
                <Empty
                  title="当前为文生视频"
                  description="添加首帧后会在这里显示图生预览。"
                />
              }
            />
          )}
          {videoTask && (
            <Hint>成片与历史进度可在任务中心查看，任务记录不会丢失。</Hint>
          )}
          <div className="creation-preview-footer">
            <Hint>生成后可在此查看视频</Hint>
            <Button variant="quiet" onClick={() => navigate("tasks")}>
              前往任务中心 <Icon name="arrow" />
            </Button>
          </div>
        </Panel>
      </div>
      <div className="creation-video-bottom-bar">
        <div>
          <strong>
            {referenceMode
              ? "参考生视频"
              : firstFrameId
                ? "图生视频"
                : "文生视频"}{" "}
            · {state.draft.resolution} · {state.draft.duration} 秒 ·{" "}
            {state.draft.ratio === "adaptive" ? "自动" : state.draft.ratio}
          </strong>
          <Hint>提交前确认费用；生成结果进入任务中心。</Hint>
        </div>
        {generationActions}
      </div>
    </section>
  );
}

function PersonIdentity({ person }: { person?: StudioPerson }) {
  const { openPicker, user } = useStudio();
  const readOnly = user.role === "auditor";
  return (
    <div className="creation-identity-row">
      <span>人物 IP</span>
      <strong>{person ? `${person.name} · ${person.role}` : "未选择"}</strong>
      <Button
        variant="outline"
        disabled={readOnly}
        onClick={() => openPicker("person")}
      >
        更换 IP
      </Button>
    </div>
  );
}

function avatarDisplayName(person: StudioPerson | undefined, name: string) {
  if (!person || name.startsWith(person.name)) return name;
  return `${person.name} · ${name}`;
}

export function OralPage() {
  const {
    state,
    data,
    patchDraft,
    updateData,
    navigate,
    openPicker,
    saveDraft,
    requestGeneration,
    notify,
    review,
    user,
  } = useStudio();
  const readOnly = user.role === "auditor";
  const audioUploadInputRef = useRef<HTMLInputElement>(null);
  const audioUploadAbortRef = useRef<AbortController | undefined>(undefined);
  const audioUploadOperationRef = useRef(0);
  const [audioUploadProgress, setAudioUploadProgress] = useState<number>();
  const audioMode = state.page === "oral-audio";
  const person = activePerson(data.people, state.draft.ipId);
  const avatar = person?.avatars.find(
    (item) => item.id === state.draft.avatarId && item.ready,
  );
  const voice = person?.voices.find(
    (item) => item.id === state.draft.voiceId && item.confirmed,
  );
  const audio = findAsset(data.assets, state.draft.audioId);
  const speechAudio =
    audio?.kind === "audio" &&
    (!audio.allowedUses || audio.allowedUses.includes("oral_audio"))
      ? audio
      : undefined;
  const avatarImage = findAsset(data.assets, avatar?.imageId);
  const ready = audioMode
    ? Boolean(person && avatar && speechAudio)
    : Boolean(
        person &&
          avatar &&
          voice &&
          state.draft.script.confirmed &&
          state.draft.script.text.trim(),
      );

  useEffect(() => {
    if (audioMode) return;
    audioUploadOperationRef.current += 1;
    audioUploadAbortRef.current?.abort();
    audioUploadAbortRef.current = undefined;
    setAudioUploadProgress(undefined);
  }, [audioMode]);

  useEffect(
    () => () => {
      audioUploadOperationRef.current += 1;
      audioUploadAbortRef.current?.abort();
    },
    [],
  );

  const cancelAudioUpload = () => {
    audioUploadOperationRef.current += 1;
    audioUploadAbortRef.current?.abort();
    audioUploadAbortRef.current = undefined;
    setAudioUploadProgress(undefined);
    notify("口播音频上传已取消");
  };

  const uploadSpeechAudio = async (file: File) => {
    if (review || readOnly) {
      notify("审核模式不执行真实上传");
      return;
    }
    const validationError = validateOralAudioFile(file);
    if (validationError) {
      notify(validationError);
      return;
    }
    const operation = ++audioUploadOperationRef.current;
    audioUploadAbortRef.current?.abort();
    const controller = new AbortController();
    audioUploadAbortRef.current = controller;
    setAudioUploadProgress(0);
    try {
      const duration = await readAudioDuration(file);
      if (operation !== audioUploadOperationRef.current) return;
      const uploaded = await uploadOralAudioMaterial(
        file,
        "oral_audio",
        duration,
        (progress) => {
          if (operation === audioUploadOperationRef.current)
            setAudioUploadProgress(progress);
        },
        controller.signal,
      );
      if (operation !== audioUploadOperationRef.current) return;
      updateData((current) => ({
        ...current,
        assets: [
          uploaded,
          ...current.assets.filter((item) => item.id !== uploaded.id),
        ],
      }));
      patchDraft({ audioId: uploaded.id, voiceId: undefined });
      notify(`音频“${uploaded.name}”已上传并永久保存`);
    } catch (cause) {
      if (operation !== audioUploadOperationRef.current) return;
      notify(customerVisibleErrorMessage(cause, "上传口播音频失败"));
    } finally {
      if (operation === audioUploadOperationRef.current) {
        audioUploadAbortRef.current = undefined;
        setAudioUploadProgress(undefined);
        if (audioUploadInputRef.current) audioUploadInputRef.current.value = "";
      }
    }
  };

  return (
    <section className="creation-page creation-oral">
      <header className="creation-heading creation-heading-back">
        <Button
          variant="quiet"
          onClick={() => navigate(state.returnTo ?? "workbench")}
        >
          ← 返回
        </Button>
        <div>
          <h1>{audioMode ? "数字人口播 - 用已有音频生成" : "数字人口播"}</h1>
        </div>
      </header>
      <CreationNavigation />
      <div className="creation-oral-grid">
        <div className="creation-oral-left">
          <Tabs
            items={[
              { id: "oral", label: "用文案生成" },
              { id: "oral-audio", label: "用已有音频生成" },
            ]}
            value={audioMode ? "oral-audio" : "oral"}
            onChange={(value) =>
              navigate(value === "oral-audio" ? "oral-audio" : "oral")
            }
          />
          <Panel className="creation-oral-inputs">
            {audioMode ? (
              <ControlGroup label="口播音频">
                {speechAudio ? (
                  <div className="creation-audio-card">
                    <div className="creation-audio-title">
                      <Icon name="audio" />
                      <span>
                        <strong>{speechAudio.name}</strong>
                        <small>
                          {speechAudio.source} ·{" "}
                          {speechAudio.duration ?? "时长未知"}
                        </small>
                      </span>
                    </div>
                    <Waveform />
                  </div>
                ) : (
                  <Empty
                    title="未选择完整口播音频"
                    description="使用录音原声直接驱动口型。"
                  />
                )}
                <div className="creation-inline-actions">
                  <Button
                    variant="outline"
                    disabled={readOnly}
                    onClick={() => openPicker("audio")}
                  >
                    从素材库选择
                  </Button>
                  <input
                    accept=".mp3,audio/mpeg"
                    aria-label="选择口播音频"
                    disabled={readOnly}
                    hidden
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) void uploadSpeechAudio(file);
                    }}
                    ref={audioUploadInputRef}
                    type="file"
                  />
                  <Button
                    disabled={readOnly || audioUploadProgress !== undefined}
                    variant="outline"
                    onClick={() => audioUploadInputRef.current?.click()}
                  >
                    {audioUploadProgress === undefined
                      ? "上传音频"
                      : `上传中 ${audioUploadProgress}%`}
                  </Button>
                  {audioUploadProgress !== undefined && (
                    <Button variant="quiet" onClick={cancelAudioUpload}>
                      取消上传
                    </Button>
                  )}
                </div>
                <Hint>使用音频中的原声直接驱动口型，无需另选克隆声音。</Hint>
              </ControlGroup>
            ) : (
              <>
                <ControlGroup label="口播文案">
                  <div className="creation-readonly-script">
                    <div>
                      <span>来源：文案工坊</span>
                      <strong>
                        {state.draft.script.confirmed ? "终稿" : "待确认"} V
                        {state.draft.script.version}
                      </strong>
                    </div>
                    <h3>{state.draft.script.title || "未命名作品"}</h3>
                    <p>{state.draft.script.text || "尚未带入已确认终稿。"}</p>
                    <button
                      onClick={() => navigate("copy", { returnTo: "oral" })}
                      type="button"
                    >
                      去文案工坊修改
                    </button>
                  </div>
                </ControlGroup>
                <ControlGroup label="声音">
                  <div className="creation-voice-row">
                    <span>{voice?.name ?? "未选择已确认声音"}</span>
                    <small>{voice ? "已就绪" : "需在人物库试听确认"}</small>
                    <Button
                      variant="outline"
                      disabled={readOnly}
                      onClick={() => openPicker("voice")}
                    >
                      更换
                    </Button>
                  </div>
                  <button
                    className="creation-text-link"
                    onClick={() =>
                      navigate("person-voices", {
                        returnTo: state.page,
                        selectedPersonId: state.draft.ipId,
                      })
                    }
                    type="button"
                  >
                    管理声音
                  </button>
                </ControlGroup>
              </>
            )}
          </Panel>
        </div>
        <Panel className="creation-oral-avatar">
          <PersonIdentity person={person} />
          <div className="creation-panel-title-row">
            <span>口播分身{audioMode ? "预览" : ""}</span>
            <Button
              variant="outline"
              disabled={readOnly}
              onClick={() => openPicker("avatar")}
            >
              更换分身
            </Button>
          </div>
          {avatar ? (
            <>
              <Media
                asset={avatarImage}
                alt={avatar.name}
                className="creation-avatar-preview"
                presentation="video"
              />
              <div className="creation-avatar-meta">
                <strong>{avatarDisplayName(person, avatar.name)}</strong>
                <small>已就绪 · 来源：人物库</small>
              </div>
              <button
                className="creation-text-link"
                onClick={() =>
                  navigate("person-avatars", {
                    returnTo: state.page,
                    selectedPersonId: state.draft.ipId,
                  })
                }
                type="button"
              >
                去人物库管理口播分身
              </button>
            </>
          ) : (
            <Empty
              title="还没有可用口播分身"
              description="请先在当前人物下制作并完成分身。"
              action={
                <Button
                  variant="outline"
                  onClick={() =>
                    navigate("person-avatars", {
                      returnTo: state.page,
                      selectedPersonId: state.draft.ipId,
                    })
                  }
                >
                  去人物库制作口播分身
                </Button>
              }
            />
          )}
        </Panel>
      </div>
      <footer className="creation-action-bar">
        {!audioMode && (
          <div className="creation-style-controls">
            <span>成片样式</span>
            <Button
              disabled={readOnly}
              variant={state.draft.style === "standard" ? "outline" : "quiet"}
              onClick={() => patchDraft({ style: "standard" })}
            >
              标准口播
            </Button>
            <span>字幕</span>
            <Button
              disabled={readOnly}
              variant={!state.draft.subtitles ? "outline" : "quiet"}
              onClick={() => patchDraft({ subtitles: false })}
            >
              不添加
            </Button>
            <Button
              disabled={readOnly}
              variant={state.draft.subtitles ? "outline" : "quiet"}
              onClick={() => patchDraft({ subtitles: true })}
            >
              添加
            </Button>
          </div>
        )}
        <Button
          variant="outline"
          disabled={readOnly}
          onClick={() => {
            if (readOnly) return;
            saveDraft();
          }}
        >
          保存草稿
        </Button>
        <Button
          variant="primary"
          disabled={readOnly || !ready}
          onClick={() => requestGeneration("数字人口播")}
        >
          生成口播视频
        </Button>
      </footer>
      <Hint>
        确认费用后提交；数字人服务未配置时会明确提示，不会生成伪造成片。
      </Hint>
    </section>
  );
}
