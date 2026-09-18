import { useCallback, useEffect, useRef, useState } from "react";
import {
  type AnalysisVersion,
  type CharacterReferenceSelection,
  confirmFirstFrame,
  type FirstFrameCandidate,
  type FirstFrameModel,
  type FirstFrameTask,
  type GenerateFirstFramesInput,
  generateFirstFrames,
  getAssetDownloadUrl,
  getLatestFirstFrameTask,
  getLatestProjectFirstFrameSelection,
  getLatestProjectFirstFrames,
  getProjectFirstFrameHistory,
  getWorkspacePricing,
  readFirstFrameCandidates,
  readFirstFrameSelectionPayload,
  resumeFirstFrameGeneration,
} from "./api";
import { VideoPreview } from "./VideoPreview";

const DEFAULT_PROMPT =
  "保留原图的镜头位置、人物姿态、动作、场景、构图、道具、光线与色调，只将原人物身份替换为角色库人物；保持自然皮肤、正确肢体和真实透视；不得增加或删除主体。";

type PendingFirstFrameGeneration = {
  promise: Promise<AnalysisVersion>;
  startedAt: number;
};

export function FirstFrameSelection({
  banded = false,
  legacyCharacterSelected = false,
  onBusyChange,
  onSelectionChange,
  projectId,
  readOnly = false,
  referenceSelection,
  simplified = false,
  sourceFrameSelectionId,
}: {
  /** 三带布局（控制带 / 媒体带 / 操作带）：供复刻页第 2 节与左栏媒体框对齐。 */
  banded?: boolean;
  legacyCharacterSelected?: boolean;
  onBusyChange?: (isBusy: boolean) => void;
  onSelectionChange?: (selection: AnalysisVersion | null) => void;
  projectId: string;
  readOnly?: boolean;
  referenceSelection: CharacterReferenceSelection | null;
  // 详情页简化模式：模型固定 gpt-image-2（Nano 仅保留为后端备选）、
  // 隐藏编辑提示词，生成参数全部走内置默认值。
  simplified?: boolean;
  sourceFrameSelectionId: string | null;
}) {
  const [version, setVersion] = useState<AnalysisVersion | null>(null);
  const [latestVersionId, setLatestVersionId] = useState("");
  const [history, setHistory] = useState<AnalysisVersion[]>([]);
  const [previewUrls, setPreviewUrls] = useState<Record<string, string>>({});
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [model, setModel] = useState<FirstFrameModel>("gpt-image-2");
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const quantity = 1;
  const [batchCredits, setBatchCredits] = useState<number | null>(null);
  const [pricingError, setPricingError] = useState("");
  useEffect(() => {
    let active = true;
    if (!readOnly) {
      void getWorkspacePricing()
        .then((pricing) => {
          const price = pricing.prices.find(
            (item) => item.subject === "first_frame",
          );
          if (active && price) setBatchCredits(price.unit_credits * quantity);
          else if (active) setPricingError("首帧报价暂不可用，请刷新后重试。");
        })
        .catch(() => {
          if (active) setPricingError("首帧报价暂不可用，请刷新后重试。");
        });
    }
    return () => {
      active = false;
    };
  }, [readOnly]);
  const [replaceScene, setReplaceScene] = useState(false);
  const [aspectRatio, setAspectRatio] = useState<
    NonNullable<GenerateFirstFramesInput["aspect_ratio"]> | "source"
  >("source");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [generationStartedAt, setGenerationStartedAt] = useState<number | null>(
    null,
  );
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [generationTask, setGenerationTask] = useState<FirstFrameTask | null>(
    null,
  );
  const loadRequestId = useRef(0);
  const currentCandidateVersionId = useRef<string | null>(null);
  const previewRetryCounts = useRef(new Map<string, number>());
  const generationWatchId = useRef(0);
  const confirmationLifecycleId = useRef(0);
  const onBusyChangeRef = useRef(onBusyChange);
  onBusyChangeRef.current = onBusyChange;
  const referenceSelectionId = referenceSelection?.id ?? "";
  const inputContext = [
    projectId,
    sourceFrameSelectionId ?? "",
    referenceSelectionId,
    legacyCharacterSelected ? "legacy" : "versioned",
  ].join("\0");
  const [loadedInputContext, setLoadedInputContext] = useState(inputContext);
  const [versionInputContext, setVersionInputContext] = useState(inputContext);
  const confirmationInputContextRef = useRef(inputContext);
  const contextLoading = isLoading || loadedInputContext !== inputContext;
  const materialReady = versionInputContext === inputContext;
  const confirmationBindingKey = [
    projectId,
    sourceFrameSelectionId ?? "",
    referenceSelectionId,
    legacyCharacterSelected ? "legacy" : "versioned",
    version?.id ?? "",
    selectedAssetId,
    aspectRatio,
    String(replaceScene),
  ].join("\0");
  const confirmationBindingKeyRef = useRef(confirmationBindingKey);
  confirmationBindingKeyRef.current = confirmationBindingKey;
  const canGenerate =
    Boolean(sourceFrameSelectionId) &&
    Boolean(referenceSelection || legacyCharacterSelected);

  const load = useCallback(
    async (
      preferredVersion?: AnalysisVersion,
      // P0-03-04：仅生成完成后的重载自动预选第一张候选（确认压缩为一次
      // 点击）；进入页面/切历史版本仍保持人工选择，stale 语义不变。
      autoSelectFirstCandidate = false,
    ) => {
      const requestId = loadRequestId.current + 1;
      loadRequestId.current = requestId;
      const isCurrentRequest = () => requestId === loadRequestId.current;
      setIsLoading(true);
      setError("");
      try {
        const [latestState, selection, versions] = await Promise.all([
          getLatestProjectFirstFrames(projectId),
          getLatestProjectFirstFrameSelection(projectId),
          getProjectFirstFrameHistory(projectId),
        ]);
        if (!isCurrentRequest()) {
          return;
        }
        setVersionInputContext(inputContext);
        const latest = latestState.version;
        currentCandidateVersionId.current = latestState.stale
          ? null
          : (latest?.id ?? null);
        const displayVersion = preferredVersion ?? latest;
        const latestPayload = latest ? readFirstFrameCandidates(latest) : null;
        const confirmedSelection = selection.version
          ? readFirstFrameSelectionPayload(selection.version)
          : null;
        const confirmedAssetId = confirmedSelection?.first_frame_asset_id;
        const currentSelection =
          !latestState.stale &&
          !selection.stale &&
          latest &&
          latestPayload &&
          confirmedSelection?.first_frame_candidates_version_id === latest.id &&
          typeof confirmedAssetId === "string" &&
          latestPayload.candidates.some(
            (candidate) => candidate.asset_id === confirmedAssetId,
          )
            ? selection.version
            : null;
        onSelectionChange?.(currentSelection);
        setLatestVersionId(latest?.id ?? "");
        setHistory(versions);
        setVersion(displayVersion);
        setPreviewUrls({});
        previewRetryCounts.current.clear();
        // 换版本后，未完成的两段式覆盖确认必须重新开始。
        if (!displayVersion) {
          setSelectedAssetId("");
          setStatus(
            latestState.stale || selection.stale
              ? "上游输入已更新，请重新生成人物置换首帧。"
              : !sourceFrameSelectionId
                ? "请先确认当前源画面；已有首帧历史仍可查看。"
                : referenceSelectionId
                  ? "人物参考图已确认，可以生成人物置换首帧。"
                  : legacyCharacterSelected
                    ? "历史兼容人物已恢复，可以继续生成首帧。"
                    : "请先确认人物参考图；已有首帧历史仍可查看。",
          );
          return;
        }
        const payload = readFirstFrameCandidates(displayVersion);
        if (!payload) {
          setSelectedAssetId("");
          setError("首帧候选数据格式无效，请重新生成。");
          return;
        }
        setModel(payload.model);
        setAspectRatio(payload.aspect_ratio ?? "source");
        setReplaceScene(Boolean(payload.replace_scene));
        if (!simplified) {
          setPrompt(payload.prompt);
        }
        // P0-03-04：预选仅是建议，确认仍为人工动作；候选生成的付费语义
        // 不变（仍由用户显式点击触发）。
        // 三带布局把候选列表收进折叠区，必须默认预选最新候选，确认按钮才有对象。
        const canAutoSelect =
          (autoSelectFirstCandidate || banded) &&
          !(latestState.stale || selection.stale) &&
          displayVersion.id === latest?.id &&
          !currentSelection;
        const canPreserveSelection =
          !(latestState.stale || selection.stale) &&
          displayVersion.id === latest?.id;
        setSelectedAssetId((currentAssetId) => {
          if (canAutoSelect) {
            // 单张流：最新生成的候选排在最后，默认预选它供用户查看确认。
            return (
              payload.candidates[payload.candidates.length - 1]?.asset_id ?? ""
            );
          }
          return canPreserveSelection &&
            payload.candidates.some(
              (candidate) => candidate.asset_id === currentAssetId,
            )
            ? currentAssetId
            : "";
        });
        if (latestState.stale || selection.stale) {
          setStatus("上游输入已更新，请重新生成人物置换首帧。");
        } else if (displayVersion.id !== latest?.id) {
          setStatus("正在查看历史版本；仅最新候选可确认用于视频生成。");
        } else if (currentSelection && typeof confirmedAssetId === "string") {
          setSelectedAssetId(confirmedAssetId);
          setStatus(
            "当前候选首帧已确认，将作为后续视频生成提示词的唯一首帧输入。",
          );
        } else if (selection.version) {
          setStatus("已确认首帧与当前候选不一致，请重新确认最新候选。");
        } else if (canAutoSelect) {
          setStatus("已自动预选最新生成的候选，请查看后单击确认。");
        } else {
          setStatus("");
        }
        const previews = await Promise.allSettled(
          [
            ...new Set([
              ...payload.candidates.map((candidate) => candidate.asset_id),
              ...(payload.review_mode === "HUMAN_CONFIRMATION"
                ? [
                    payload.source_frame_asset_id,
                    ...(payload.character_reference_asset_ids ?? []),
                  ].filter((id): id is string => Boolean(id))
                : []),
            ]),
          ].map(async (assetId) => {
            const download = await getAssetDownloadUrl(assetId);
            return [assetId, download.url] as const;
          }),
        );
        if (!isCurrentRequest()) {
          return;
        }
        setPreviewUrls(
          Object.fromEntries(
            previews.flatMap((result) =>
              result.status === "fulfilled" ? [result.value] : [],
            ),
          ),
        );
      } catch (requestError) {
        if (isCurrentRequest()) {
          onSelectionChange?.(null);
          setError(
            requestError instanceof Error
              ? requestError.message
              : "读取人物置换首帧失败。",
          );
        }
      } finally {
        if (isCurrentRequest()) {
          setLoadedInputContext(inputContext);
          setIsLoading(false);
        }
      }
    },
    [
      legacyCharacterSelected,
      inputContext,
      onSelectionChange,
      projectId,
      referenceSelectionId,
      simplified,
      sourceFrameSelectionId,
      banded,
    ],
  );

  const followGeneration = useCallback(
    async (pending: PendingFirstFrameGeneration) => {
      const watchId = generationWatchId.current + 1;
      generationWatchId.current = watchId;
      onBusyChangeRef.current?.(true);
      setIsSubmitting(true);
      setGenerationStartedAt(pending.startedAt);
      setElapsedSeconds(
        Math.max(0, Math.floor((Date.now() - pending.startedAt) / 1000)),
      );
      setError("");
      setStatus("");
      try {
        const generated = await pending.promise;
        if (watchId !== generationWatchId.current) {
          return;
        }
        setStatus("候选首帧已更新，正在读取候选…");
        await load(generated, true);
      } catch (requestError) {
        if (watchId !== generationWatchId.current) {
          return;
        }
        setError(
          requestError instanceof Error
            ? requestError.message
            : "生成人物置换首帧失败。",
        );
      } finally {
        if (watchId === generationWatchId.current) {
          setIsSubmitting(false);
          setGenerationStartedAt(null);
          onBusyChangeRef.current?.(false);
        }
      }
    },
    [load],
  );

  useEffect(() => {
    if (confirmationInputContextRef.current === inputContext) {
      return;
    }
    confirmationInputContextRef.current = inputContext;
    confirmationLifecycleId.current += 1;
    setIsSubmitting(false);
  }, [inputContext]);

  useEffect(() => {
    let cancelled = false;
    currentCandidateVersionId.current = null;
    onBusyChangeRef.current?.(false);
    void (async () => {
      await load();
      if (cancelled) return;
      try {
        const task = await getLatestFirstFrameTask(projectId);
        if (cancelled) return;
        if (task && (task.status === "PENDING" || task.status === "RUNNING")) {
          setGenerationTask(task);
          void followGeneration({
            promise: resumeFirstFrameGeneration(
              projectId,
              task.id,
              setGenerationTask,
            ),
            startedAt: Date.parse(task.started_at ?? task.created_at),
          });
        } else if (
          task?.status === "SUCCEEDED" &&
          task.result_version_id !== null &&
          task.result_version_id === currentCandidateVersionId.current
        ) {
          // Restore the selection suggestion without toggling upstream inputs
          // read-only; that toggle reloads their bindings and restarts this effect.
          await load(undefined, true);
        } else if (
          task &&
          (task.status === "FAILED" || task.status === "SUBMISSION_UNCERTAIN")
        ) {
          setError(
            task.error_message ??
              (task.status === "SUBMISSION_UNCERTAIN"
                ? "云端任务状态需要确认，请重试。"
                : "云端首帧生成失败，请重试。"),
          );
        }
      } catch {
        // The normal page load already reports API availability. A separate
        // recovery probe must not replace valid candidate/history content.
      }
    })();
    return () => {
      cancelled = true;
      loadRequestId.current += 1;
      generationWatchId.current += 1;
    };
  }, [followGeneration, load, projectId]);

  useEffect(
    () => () => {
      confirmationLifecycleId.current += 1;
      onBusyChangeRef.current?.(false);
    },
    [],
  );

  useEffect(() => {
    if (generationStartedAt === null) {
      return;
    }
    const updateElapsed = () => {
      setElapsedSeconds(
        Math.max(0, Math.floor((Date.now() - generationStartedAt) / 1000)),
      );
    };
    updateElapsed();
    const intervalId = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(intervalId);
  }, [generationStartedAt]);

  const payload =
    materialReady && version ? readFirstFrameCandidates(version) : null;
  const aspectMatchesVersion =
    (payload?.aspect_ratio ?? "source") === aspectRatio &&
    Boolean(payload?.replace_scene) === replaceScene;
  const isHistoryVersion = Boolean(version && version.id !== latestVersionId);
  const selectedPreview = previewUrls[selectedAssetId];
  const comparisonReady =
    payload?.review_mode !== "HUMAN_CONFIRMATION" ||
    Boolean(
      payload.source_frame_asset_id &&
        previewUrls[payload.source_frame_asset_id] &&
        payload.character_reference_asset_ids?.length &&
        payload.character_reference_asset_ids.every((id) => previewUrls[id]),
    );

  async function handlePreviewError(assetId: string) {
    setPreviewUrls((current) =>
      Object.fromEntries(
        Object.entries(current).filter(([currentId]) => currentId !== assetId),
      ),
    );
    const retries = previewRetryCounts.current.get(assetId) ?? 0;
    if (retries >= 1) {
      return;
    }
    previewRetryCounts.current.set(assetId, retries + 1);
    try {
      const download = await getAssetDownloadUrl(assetId);
      setPreviewUrls((current) => ({ ...current, [assetId]: download.url }));
    } catch {
      // Leave the preview absent after the single bounded re-sign attempt.
    }
  }

  async function handleGenerate() {
    if (readOnly || contextLoading || !materialReady) {
      return;
    }
    if (!canGenerate) {
      setError("请先确认当前源画面和人物参考图，再生成新的置换首帧。");
      return;
    }
    const binding = referenceSelection
      ? {
          character_version_id: referenceSelection.character_version_id,
          character_reference_selection_id: referenceSelection.id,
        }
      : {};
    const pending: PendingFirstFrameGeneration = {
      startedAt: Date.now(),
      promise: generateFirstFrames(
        projectId,
        {
          model: simplified ? "gpt-image-2" : model,
          // In simplified mode the server owns the stable business template.
          // Sending the UI placeholder here previously bypassed the stronger
          // contact-sheet/reference-role prompt assembly on the server.
          prompt: simplified ? undefined : prompt,
          quantity,
          ...(replaceScene ? { replace_scene: true } : {}),
          ...(aspectRatio === "source" ? {} : { aspect_ratio: aspectRatio }),
          ...binding,
        },
        setGenerationTask,
      ),
    };
    await followGeneration(pending);
  }

  async function handleConfirm() {
    if (readOnly || contextLoading || !materialReady) {
      return;
    }
    if (
      !selectedAssetId ||
      !selectedPreview ||
      !comparisonReady ||
      !aspectMatchesVersion ||
      isHistoryVersion
    ) {
      setError("请先加载并查看最新候选首帧预览，再进行确认。");
      return;
    }
    const submittedBindingKey = confirmationBindingKey;
    const submittedLifecycleId = confirmationLifecycleId.current;
    const isCurrentConfirmation = () =>
      submittedLifecycleId === confirmationLifecycleId.current &&
      submittedBindingKey === confirmationBindingKeyRef.current;
    onBusyChangeRef.current?.(true);
    setIsSubmitting(true);
    setError("");
    try {
      const selection = await confirmFirstFrame(projectId, selectedAssetId);
      if (!isCurrentConfirmation()) {
        return;
      }
      const selectedIndex = payload?.candidates.findIndex(
        (candidate) => candidate.asset_id === selectedAssetId,
      );
      setStatus(
        `已确认首帧候选 ${(selectedIndex ?? 0) + 1}。可继续编辑文案并生成视频。`,
      );
      onSelectionChange?.(selection);
    } catch (requestError) {
      if (!isCurrentConfirmation()) {
        return;
      }
      setError(
        requestError instanceof Error ? requestError.message : "确认首帧失败。",
      );
    } finally {
      if (isCurrentConfirmation()) {
        setIsSubmitting(false);
        onBusyChangeRef.current?.(false);
      }
    }
  }

  // 下列片段同时供常规布局与 banded（复刻页第 2 节三带）布局使用：
  // 两套布局的禁用条件、交互语义必须完全一致，只能有一份实现。
  const sceneSettings = simplified ? (
    <label>
      场景设置
      <select
        aria-label="场景设置"
        disabled={
          readOnly ||
          contextLoading ||
          !materialReady ||
          isSubmitting ||
          !canGenerate
        }
        value={replaceScene ? "replace" : "preserve"}
        onChange={(event) => {
          setReplaceScene(event.target.value === "replace");
          onSelectionChange?.(null);
        }}
      >
        <option value="preserve">保留原场景</option>
        <option value="replace">使用人物场景背景</option>
      </select>
    </label>
  ) : null;
  const aspectSettings = (
    <label>
      图片画幅
      <select
        aria-label="图片画幅"
        value={aspectRatio}
        disabled={
          readOnly ||
          contextLoading ||
          !materialReady ||
          isSubmitting ||
          !canGenerate
        }
        onChange={(event) => {
          setAspectRatio(event.target.value as typeof aspectRatio);
          onSelectionChange?.(null);
        }}
      >
        <option value="source">跟随原视频</option>
        <option value="9:16">9:16 · 竖屏</option>
        <option value="16:9">16:9 · 横屏</option>
        <option value="1:1">1:1 · 方图</option>
        <option value="3:4">3:4 · 竖图</option>
        <option value="4:3">4:3 · 横图</option>
      </select>
    </label>
  );
  const generateButton = (
    <button
      disabled={
        readOnly ||
        contextLoading ||
        !materialReady ||
        isSubmitting ||
        !canGenerate ||
        batchCredits === null
      }
      onClick={handleGenerate}
      type="button"
    >
      {isSubmitting
        ? "正在生成"
        : payload
          ? banded
            ? "重新生成候选"
            : "再生成1张"
          : banded
            ? "生成候选首帧"
            : "生成1张首帧"}
    </button>
  );
  const confirmButton = (
    <button
      className="secondary-button"
      disabled={
        readOnly ||
        contextLoading ||
        !materialReady ||
        isSubmitting ||
        !selectedAssetId ||
        !selectedPreview ||
        !comparisonReady ||
        !aspectMatchesVersion ||
        isHistoryVersion
      }
      onClick={handleConfirm}
      type="button"
    >
      {banded ? "确认此首帧" : "使用这张首帧"}
    </button>
  );
  const aspectChangedNote =
    !contextLoading && payload && !aspectMatchesVersion && !isSubmitting ? (
      <p className="status-note">画幅或场景已更改，请重新生成后确认首帧。</p>
    ) : null;
  const progressBlock =
    generationStartedAt !== null ? (
      <div className="first-frame-generation-progress" role="status">
        <div className="first-frame-generation-progress__heading">
          <strong>{firstFrameTaskStageLabel(generationTask)}</strong>
          <span>已等待 {elapsedSeconds} 秒</span>
        </div>
        <progress aria-label="人物置换首帧生成进度" />
        {generationTask && !simplified ? (
          <p>
            任务 {generationTask.id} · 第 {Math.max(1, generationTask.attempt)}{" "}
            次执行
          </p>
        ) : !generationTask ? (
          <p>正在提交…</p>
        ) : null}
        <p>可离开页面，返回后继续查看。</p>
      </div>
    ) : null;
  const fakeProviderNote =
    payload?.provider === "fake" ? (
      <p className="settings-error">模拟输出：尚未调用正式图像生成服务。</p>
    ) : null;
  const comparisonBlock =
    payload?.review_mode === "HUMAN_CONFIRMATION" ? (
      <details className="first-frame-comparison" open={!simplified}>
        <summary>查看原图与人物参考</summary>
        <section aria-label="首帧对照确认" className="first-frame-options">
          <p>
            {payload.replace_scene
              ? "核对人物、背景和动作是否自然。"
              : "核对人物已替换，原场景和动作保持一致。"}
          </p>
          {[
            { id: payload.source_frame_asset_id, label: "原视频源画面" },
            ...(payload.character_reference_asset_ids ?? []).map((id) => ({
              id,
              label: "所选场景形象",
            })),
          ].map(({ id, label }) =>
            id ? (
              <figure key={id}>
                {previewUrls[id] ? (
                  <img
                    src={previewUrls[id]}
                    alt={label}
                    style={{
                      maxWidth: "100%",
                      maxHeight: 360,
                      objectFit: "contain",
                    }}
                    onError={() => void handlePreviewError(id)}
                  />
                ) : (
                  <p>{label}预览暂不可用，请刷新重试。</p>
                )}
                <figcaption>{label}</figcaption>
              </figure>
            ) : null,
          )}
        </section>
      </details>
    ) : null;
  const currentPreview =
    simplified && selectedPreview ? (
      <VideoPreview
        className="first-frame-current"
        frameRatio="adaptive"
        alt="当前首帧预览"
        poster={selectedPreview}
        onPosterError={() => void handlePreviewError(selectedAssetId)}
      />
    ) : null;
  const candidatesFieldset = payload ? (
    <fieldset className="first-frame-options">
      <legend>
        {readOnly
          ? "候选记录（素材预览需要下载权限）"
          : simplified
            ? "选择一张"
            : "查看候选效果，选择一张作为已确认首帧"}
      </legend>
      {payload.candidates.map((candidate, index) => (
        <FirstFrameOption
          candidate={candidate}
          checked={selectedAssetId === candidate.asset_id}
          disabled={
            readOnly ||
            contextLoading ||
            isSubmitting ||
            !previewUrls[candidate.asset_id] ||
            isHistoryVersion
          }
          index={index}
          key={candidate.asset_id}
          onSelect={() => {
            setSelectedAssetId(candidate.asset_id);
            // 换候选后，未完成的两段式覆盖确认必须重新开始。
          }}
          onPreviewError={() => void handlePreviewError(candidate.asset_id)}
          previewUrl={previewUrls[candidate.asset_id]}
          readOnly={readOnly}
        />
      ))}
    </fieldset>
  ) : null;
  const historyBlock =
    !contextLoading && materialReady ? (
      <details
        open={!simplified}
        className="first-frame-history"
        aria-labelledby="first-frame-history-title"
      >
        <summary id="first-frame-history-title">历史版本</summary>
        {readOnly ? (
          <p className="status-note">只读身份不能生成或确认首帧。</p>
        ) : null}
        {history.length === 0 ? (
          <p className="file-note">暂无历史版本。</p>
        ) : null}
        <div className="first-frame-history-list">
          {history.map((historyVersion) => (
            <button
              className={
                historyVersion.id === version?.id
                  ? "history-version history-version--active"
                  : "history-version"
              }
              key={historyVersion.id}
              disabled={contextLoading || isSubmitting}
              onClick={() => void load(historyVersion)}
              type="button"
            >
              版本 #{historyVersion.version_number}
            </button>
          ))}
        </div>
      </details>
    ) : null; // 历史版本始终渲染，常规布局展开、简化布局折叠。

  /**
   * 三带布局（复刻页第 2 节右栏）：控制带 / 媒体带 / 操作带与左栏等位，
   * 两侧媒体框因此同尺寸且上下边对齐。候选与历史收进折叠区，
   * 避免它们撑高媒体带、破坏左右对齐。
   */
  if (banded) {
    return (
      <section
        className="first-frame-selection first-frame-selection--compact first-frame-selection--banded"
        aria-labelledby="first-frame-title"
      >
        <div>
          <h3 id="first-frame-title">人物置换首帧</h3>
        </div>
        <div className="band-ctrl">
          {sceneSettings}
          {aspectSettings}
        </div>
        <div className="media-frame">
          {currentPreview ?? (
            <p className="file-note">
              {isSubmitting ? "正在生成首帧…" : "生成后在此预览并确认。"}
            </p>
          )}
        </div>
        <div className="band-act center">
          {confirmButton}
          {generateButton}
        </div>
        <p className="file-note">
          {batchCredits === null
            ? pricingError || "正在读取本批费用…"
            : `本次预计 ${batchCredits} 积分；再次生成按新一次计费。`}
        </p>
        {aspectChangedNote}
        {fakeProviderNote}
        {contextLoading ? (
          <p className="status-note">正在读取首帧候选</p>
        ) : null}
        {!contextLoading && error ? (
          <p className="settings-error">{error}</p>
        ) : null}
        {!contextLoading && status ? (
          <p className="setup-success">{status}</p>
        ) : null}
        {progressBlock}
        <details className="first-frame-band-extras">
          <summary>候选与历史</summary>
          {comparisonBlock}
          {candidatesFieldset}
          {historyBlock}
        </details>
      </section>
    );
  }

  return (
    <section
      className={
        simplified
          ? "first-frame-selection first-frame-selection--compact"
          : "first-frame-selection"
      }
      aria-labelledby="first-frame-title"
    >
      <div>
        <h3 id="first-frame-title">人物置换首帧</h3>
        {!simplified ? (
          <p>
            {legacyCharacterSelected
              ? "历史兼容人物 · 沿用冻结的人物快照。"
              : "由已确认的源画面与角色参考生成。"}
          </p>
        ) : null}
      </div>
      {!simplified ? (
        <div className="first-frame-controls">
          <label>
            首帧生成模式
            <select
              aria-label="首帧生成模式"
              disabled={
                readOnly ||
                contextLoading ||
                !materialReady ||
                isSubmitting ||
                !canGenerate
              }
              onChange={(event) =>
                setModel(event.target.value as FirstFrameModel)
              }
              value={model}
            >
              <option value="gpt-image-2">标准图像（默认）</option>
              <option value="nano-banana-pro-2k">高清图像</option>
            </select>
          </label>
          <label>
            候选数量
            <input
              aria-label="候选数量"
              disabled={readOnly || isSubmitting || !canGenerate}
              max="3"
              min="1"
              readOnly
              type="number"
              value={quantity}
            />
          </label>
        </div>
      ) : null}
      {!simplified ? (
        <label className="first-frame-prompt">
          首帧编辑提示词
          <textarea
            aria-label="首帧编辑提示词"
            disabled={
              readOnly ||
              contextLoading ||
              !materialReady ||
              isSubmitting ||
              !canGenerate
            }
            onChange={(event) => setPrompt(event.target.value)}
            rows={10}
            value={prompt}
          />
        </label>
      ) : null}
      <div className="source-frame-actions">
        <p>每次生成1张；选定1张用于视频合成。</p>
        <p>
          {batchCredits === null
            ? pricingError || "正在读取本批费用…"
            : `本次预计 ${batchCredits} 积分；再次生成按新一次计费。`}
        </p>
        {sceneSettings}
        {aspectSettings}
        {generateButton}
        {confirmButton}
      </div>
      {aspectChangedNote}
      {progressBlock}
      {contextLoading ? <p className="status-note">正在读取首帧候选</p> : null}
      {!contextLoading && error ? (
        <p className="settings-error">{error}</p>
      ) : null}
      {!contextLoading && status ? (
        <p className="setup-success">{status}</p>
      ) : null}
      {!contextLoading && materialReady && payload ? (
        <>
          {payload.project_appearance && !simplified ? (
            <aside
              className="project-appearance-summary"
              aria-label="本项目人物造型"
            >
              <div>
                <strong>本项目人物造型</strong>
                <span>
                  {payload.project_appearance.category === "SCENE_LOOK"
                    ? "所选场景形象"
                    : "后台自动匹配"}
                </span>
              </div>
              <p>{payload.project_appearance.outfit_description}</p>
              <small>{payload.project_appearance.selection_reason}</small>
            </aside>
          ) : null}
          {!simplified ? (
            <p className="file-note">
              当前模式：{modelLabel(payload.model)} ·{" "}
              {payload.provider === "fake" ? "测试模式" : "正式服务"}
            </p>
          ) : null}
          {fakeProviderNote}
          {comparisonBlock}
          {currentPreview}
          {candidatesFieldset}
        </>
      ) : null}
      {historyBlock}
    </section>
  );
}

function firstFrameTaskStageLabel(task: FirstFrameTask | null): string {
  switch (task?.stage) {
    case "QUEUED":
      return "正在排队";
    case "PREPARING":
      return "正在读取画面与人物";
    case "GENERATING":
      return "正在生成首帧";
    case "VERIFYING":
      return "正在准备预览";
    case "SUCCEEDED":
      return "首帧已生成，正在加载结果";
    case "FAILED":
      return "首帧生成失败";
    case "NEEDS_REVIEW":
      return "生成结果需要人工核对";
    default:
      return "正在提交人物置换首帧任务";
  }
}

function FirstFrameOption({
  candidate,
  checked,
  disabled,
  index,
  onSelect,
  onPreviewError,
  previewUrl,
  readOnly,
}: {
  candidate: FirstFrameCandidate;
  checked: boolean;
  disabled: boolean;
  index: number;
  onSelect: () => void;
  onPreviewError: () => void;
  previewUrl: string | undefined;
  readOnly: boolean;
}) {
  return (
    <label
      className={
        checked
          ? "source-frame-option source-frame-option--selected"
          : "source-frame-option"
      }
    >
      <input
        checked={checked}
        disabled={disabled}
        name="first-frame"
        onChange={onSelect}
        type="radio"
        value={candidate.asset_id}
      />
      <VideoPreview
        frameRatio="adaptive"
        alt={`首帧候选 ${index + 1}`}
        onPosterError={onPreviewError}
        poster={previewUrl}
        fallback={readOnly ? "预览不可用" : "预览加载失败，请重新生成"}
      />
      <span>
        <strong>首帧候选 {index + 1}</strong>
        <small>检查人物、服装和肢体。</small>
      </span>
    </label>
  );
}

function modelLabel(model: FirstFrameModel) {
  return model === "gpt-image-2" ? "标准图像" : "高清图像";
}
