import { useCallback, useEffect, useRef, useState } from "react";
import {
  type AnalysisVersion,
  type CharacterReferenceSelection,
  createGenerationBatch,
  defaultBatchProvider,
  type GenerationBatch,
  type GenerationBatchInput,
  type GenerationPriceQuote,
  type GenerationRatio,
  getGenerationPriceQuote,
  getLatestGenerationPrompt,
  getLatestProjectAnalysis,
  getLatestScriptVersion,
  type Project,
  type ProjectMainCharacter,
  readAnalysisPayload,
  readFirstFrameSelectionPayload,
  saveGenerationPrompt,
  selectCharacterReferences,
} from "./api";
import { CharacterSelection } from "./CharacterSelection";
import { FirstFrameSelection } from "./FirstFrameSelection";
import { SourceFrameSelection } from "./SourceFrameSelection";
import {
  type FinalReplicaSnapshot,
  PromptEditor,
  ReplicaFinalPromptControls,
  replicaInputKey,
} from "./studio/PromptEditor";
import { readAppliedOptimization } from "./studio/usePromptOptimization";
import {
  clearIdempotencyRecord,
  restoreIdempotencyRecord,
  restoreOrCreateIdempotencyRecord,
} from "./useGenerationDrafts";

type ProjectDetailFlowProps = {
  currentUserId?: string;
  onBack: () => void;
  onBatchCreated: (batch: GenerationBatch) => void;
  onBusyChange?: (isBusy: boolean) => void;
  project: Project;
  readOnly: boolean;
  /** 余额不足时的充值引导动作（可选；内部 lane 缺省）。 */
  onRecharge?: () => void;
  /** 客户 lane 提供钱包余额读取，用于提交前的软预检（F-05）。 */
  walletProvider?: () => Promise<number | null>;
};

type GenerationPhase = "idle" | "running" | "done";
type QuoteStatus = "loading" | "ready" | "error";

type IdempotencyEnvelope = {
  request: GenerationBatchInput;
  sourceFingerprint: string;
};

const frozenDetailRequests = new Map<string, IdempotencyEnvelope>();

function detailRequestKey(project: Project, sourceFingerprint: string): string {
  return JSON.stringify([project.owner_user_id, project.id, sourceFingerprint]);
}

function newIdempotencyKey(): string {
  return typeof globalThis.crypto?.randomUUID === "function"
    ? globalThis.crypto.randomUUID()
    : `detail-flow-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// 项目详情流程页 = 「解析提示词 → 源画面与人物 → 人物置换首帧 → 自定义文案 → 提交生成」
// 五段自上而下滚动。人物参考在角色与源画面就绪后全自动匹配（无人工确认）；
// stale 级联（角色/源画面变 → 清参考与首帧）、幂等建批、付费红线全部沿用
// 快速生成动线的服务端语义。
export function ProjectDetailFlow({
  currentUserId,
  onBack,
  onBatchCreated,
  onBusyChange,
  onRecharge,
  project,
  readOnly,
}: ProjectDetailFlowProps) {
  const [analysisVersion, setAnalysisVersion] =
    useState<AnalysisVersion | null>(null);
  const [analysisError, setAnalysisError] = useState("");
  const [characterSelection, setCharacterSelection] =
    useState<ProjectMainCharacter | null>(null);
  const [sourceFrameSelection, setSourceFrameSelection] =
    useState<AnalysisVersion | null>(null);
  const [referenceSelection, setReferenceSelection] =
    useState<CharacterReferenceSelection | null>(null);
  const [referenceError, setReferenceError] = useState("");
  const [firstFrameSelection, setFirstFrameSelection] =
    useState<AnalysisVersion | null>(null);
  const [scriptText, setScriptText] = useState("");
  const scriptEdited = useRef(false);
  const restoredScript = useRef(false);
  const [firstFrameGenerationBusy, setFirstFrameGenerationBusy] =
    useState(false);
  const [generationPhase, setGenerationPhase] =
    useState<GenerationPhase>("idle");
  const [generationRatio, setGenerationRatio] =
    useState<GenerationRatio>("adaptive");
  const [generationDuration, setGenerationDuration] = useState<4 | 15>(15);
  const [generationQuantity, setGenerationQuantity] = useState<1 | 2 | 4>(1);
  const [priceQuote, setPriceQuote] = useState<GenerationPriceQuote | null>(
    null,
  );
  const [priceQuoteStatus, setPriceQuoteStatus] =
    useState<QuoteStatus>("loading");
  const [priceQuoteError, setPriceQuoteError] = useState("");
  const [priceQuoteRevision, setPriceQuoteRevision] = useState(0);
  const [generationError, setGenerationError] = useState("");
  const [insufficientBalance, setInsufficientBalance] = useState<{
    neededCredits: number | null;
    balanceCredits: number | null;
  } | null>(null);
  const [generationMessage, setGenerationMessage] = useState("");
  // 用户在第一段编辑并另存过的提示词文本。自定义文案未变时提交会复用；
  // 文案变化时必须让服务端重新编译，避免旧的完整 Prompt 覆盖新文案。
  const [revisedPromptText, setRevisedPromptText] = useState<string | null>(
    null,
  );
  const finalPromptText = revisedPromptText ?? "";
  const [finalSnapshot, setFinalSnapshot] =
    useState<FinalReplicaSnapshot | null>(null);

  const [referenceRetryCount, setReferenceRetryCount] = useState(0);
  const upstreamBusyRef = useRef<Set<string>>(new Set());
  const [, forceRender] = useState(0);
  // 只有完全相同的提交内容才复用幂等键。上一次请求响应丢失时可安全重试；
  // 用户修改文案、Prompt、首帧或生成参数后必须生成新键，避免服务端 409。
  const idempotencyEnvelopeRef = useRef<IdempotencyEnvelope | null>(null);
  const submissionBusyRef = useRef(false);
  const submissionOperationRef = useRef(0);
  const submissionContextRef = useRef("");
  const autoMatchAttemptedRef = useRef<Set<string>>(new Set());
  const firstFrameStepRef = useRef<HTMLFieldSetElement>(null);
  const onBusyChangeRef = useRef(onBusyChange);
  onBusyChangeRef.current = onBusyChange;

  const firstFramePayload = firstFrameSelection
    ? readFirstFrameSelectionPayload(firstFrameSelection)
    : null;
  const firstFrameAssetId = firstFramePayload?.first_frame_asset_id ?? null;
  const finalInput = {
    projectId: project.id,
    scriptText,
    firstFrameAssetId: firstFrameAssetId ?? "",
    duration: generationDuration,
    resolution: "768P" as const,
    ratio: generationRatio,
  };
  const finalReady = finalSnapshot?.inputKey === replicaInputKey(finalInput);
  const isUpstreamBusy = upstreamBusyRef.current.size > 0;
  const isBusy = generationPhase === "running" || isUpstreamBusy;
  submissionContextRef.current = JSON.stringify({
    projectId: project.id,
    firstFrameAssetId,
    generationDuration,
    generationQuantity,
    generationRatio,
    scriptText: scriptText.trim(),
    revisedPromptText: finalPromptText,
  });
  const priceQuoteReady = Boolean(
    priceQuoteStatus === "ready" &&
      priceQuote &&
      priceQuote.resolution === "768P" &&
      priceQuote.duration_seconds === generationDuration &&
      priceQuote.quantity === generationQuantity &&
      priceQuote.estimated_seconds === generationDuration * generationQuantity,
  );
  const canStart =
    Boolean(firstFrameAssetId) &&
    priceQuoteReady &&
    !isBusy &&
    !firstFrameGenerationBusy &&
    !readOnly &&
    generationPhase !== "done";

  useEffect(() => {
    onBusyChangeRef.current?.(isBusy);
  }, [isBusy]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: 切换项目必须显式失效正在进行的付费提交。
  useEffect(() => {
    submissionOperationRef.current += 1;
    submissionBusyRef.current = false;
    setGenerationPhase("idle");
    setGenerationError("");
    setGenerationMessage("");
    return () => {
      submissionOperationRef.current += 1;
    };
  }, [project.id]);

  const markUpstreamBusy = useCallback((key: string, busy: boolean) => {
    if (busy) {
      upstreamBusyRef.current.add(key);
    } else {
      upstreamBusyRef.current.delete(key);
    }
    forceRender((value) => value + 1);
  }, []);

  useEffect(() => {
    let active = true;
    getLatestProjectAnalysis(project.id)
      .then((version) => {
        if (active) {
          setAnalysisVersion(version);
          setAnalysisError("");
        }
      })
      .catch(() => {
        if (active) {
          setAnalysisError("该项目还没有可用的拆解结果，请先等待拆解完成。");
        }
      });
    return () => {
      active = false;
    };
  }, [project.id]);

  useEffect(() => {
    void priceQuoteRevision;
    let active = true;
    if (typeof getGenerationPriceQuote !== "function") return;
    const input = {
      resolution: "768P" as const,
      duration_seconds: generationDuration,
      quantity: generationQuantity,
    };
    setPriceQuote(null);
    setPriceQuoteStatus("loading");
    setPriceQuoteError("");
    getGenerationPriceQuote(input)
      .then((quote) => {
        if (!active) return;
        if (
          quote.resolution !== input.resolution ||
          quote.duration_seconds !== input.duration_seconds ||
          quote.quantity !== input.quantity ||
          quote.estimated_seconds !== input.duration_seconds * input.quantity
        ) {
          setPriceQuoteStatus("error");
          setPriceQuoteError("生成报价参数与当前生成参数不一致，请重新获取。");
          return;
        }
        setPriceQuote(quote);
        setPriceQuoteStatus("ready");
      })
      .catch((quoteError: unknown) => {
        if (active) {
          setPriceQuote(null);
          setPriceQuoteStatus("error");
          setPriceQuoteError(
            quoteError instanceof Error && quoteError.message.trim()
              ? quoteError.message
              : "读取生成费用失败，请稍后重试。",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [generationDuration, generationQuantity, priceQuoteRevision]);

  function retryPriceQuote() {
    setPriceQuoteRevision((value) => value + 1);
  }

  useEffect(() => {
    let active = true;
    scriptEdited.current = false;
    restoredScript.current = false;
    setScriptText("");
    void Promise.resolve()
      .then(() => getLatestScriptVersion(project.id))
      .then((state) => {
        if (active && state?.version && !state.stale && !scriptEdited.current) {
          restoredScript.current = true;
          setScriptText(String(state.version.payload.full_text ?? ""));
        }
      })
      .catch(() => {});
    setRevisedPromptText(null);
    setFinalSnapshot(null);
    void Promise.resolve()
      .then(() => getLatestGenerationPrompt(project.id))
      .then((state) => {
        if (
          active &&
          !state.stale &&
          state.version?.payload.final_composition
        ) {
          const text = String(state.version.payload.prompt_text ?? "");
          setRevisedPromptText((current) =>
            current === null ? text : current,
          );
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [project.id]);

  // 拆解就绪后把原文案直接带入自定义文案框，用户可在原内容上修改。
  // readAnalysisPayload 解包服务端落库的 payload.analysis 包装结构。
  useEffect(() => {
    if (!analysisVersion) {
      return;
    }
    const payload = readAnalysisPayload(analysisVersion);
    if (!scriptEdited.current && !restoredScript.current) {
      setScriptText(payload ? payload.original_script : "");
    }
  }, [analysisVersion]);

  // 人物参考全自动匹配：角色与源画面确认后服务端自动创建推荐集
  // （selected 省略 → 推荐集），无人工确认。每个「角色版本 × 源画面版本」
  // 组合只自动尝试一次，失败可手动重试。
  // biome-ignore lint/correctness/useExhaustiveDependencies(referenceRetryCount): 重试按钮递增该计数器以触发本 effect 重新匹配。
  useEffect(() => {
    if (
      readOnly ||
      !characterSelection ||
      !sourceFrameSelection ||
      referenceSelection
    ) {
      return;
    }
    const characterVersionId = characterSelection.character_version_id ?? "";
    const matchKey = `${project.id}:${characterVersionId}:${sourceFrameSelection.id}`;
    if (autoMatchAttemptedRef.current.has(matchKey)) {
      return;
    }
    autoMatchAttemptedRef.current.add(matchKey);
    let active = true;
    markUpstreamBusy("reference", true);
    selectCharacterReferences(project.id, {
      character_version_id: characterVersionId,
      source_frame_selection_version_id: sourceFrameSelection.id,
    })
      .then((selection) => {
        if (active) {
          setReferenceSelection(selection);
          setReferenceError("");
        }
      })
      .catch((matchError: unknown) => {
        if (active) {
          setReferenceError(
            matchError instanceof Error
              ? matchError.message
              : "自动匹配人物参考失败。",
          );
        }
      })
      .finally(() => {
        markUpstreamBusy("reference", false);
      });
    return () => {
      active = false;
    };
  }, [
    characterSelection,
    markUpstreamBusy,
    project.id,
    readOnly,
    referenceRetryCount,
    referenceSelection,
    sourceFrameSelection,
  ]);

  function retryReferenceMatch() {
    if (!characterSelection || !sourceFrameSelection) {
      return;
    }
    const characterVersionId = characterSelection.character_version_id ?? "";
    autoMatchAttemptedRef.current.delete(
      `${project.id}:${characterVersionId}:${sourceFrameSelection.id}`,
    );
    setReferenceError("");
    setReferenceRetryCount((count) => count + 1);
  }

  // stale 级联（本页顺序为源画面在前）：任一变化 → 清参考匹配与首帧；
  // 源画面确认本身不依赖角色，角色变化不清源画面。
  const handleCharacterChange = useCallback(
    (selection: ProjectMainCharacter | null) => {
      setCharacterSelection(selection);
      setReferenceSelection(null);
      setFirstFrameSelection(null);
    },
    [],
  );

  const handleSourceFrameChange = useCallback(
    (selection: AnalysisVersion | null) => {
      setSourceFrameSelection(selection);
      setReferenceSelection(null);
      setFirstFrameSelection(null);
    },
    [],
  );

  const handleFirstFrameChange = useCallback(
    (selection: AnalysisVersion | null) => {
      setFirstFrameSelection(selection);
    },
    [],
  );

  function sourceVideoDurationSeconds(): number {
    const raw = analysisVersion
      ? readAnalysisPayload(analysisVersion)?.duration_seconds
      : null;
    return typeof raw === "number" && Number.isFinite(raw) && raw > 0
      ? raw
      : 10;
  }

  async function handleStartGeneration() {
    if (
      submissionBusyRef.current ||
      !firstFrameAssetId ||
      isBusy ||
      firstFrameGenerationBusy ||
      readOnly
    ) {
      return;
    }
    if (!priceQuoteReady) {
      setGenerationError(
        priceQuoteError || "请先取得与当前参数一致的生成报价后再提交。",
      );
      return;
    }
    if (!finalReady || !finalSnapshot) {
      setGenerationError("请先确认文案与首帧并合成最终提示词。");
      return;
    }
    const operation = submissionOperationRef.current + 1;
    submissionOperationRef.current = operation;
    const sourceFingerprint = submissionContextRef.current;
    const isCurrent = () =>
      submissionOperationRef.current === operation &&
      submissionContextRef.current === sourceFingerprint;
    submissionBusyRef.current = true;
    setGenerationPhase("running");
    setGenerationError("");
    setGenerationMessage("");
    try {
      let envelope = idempotencyEnvelopeRef.current;
      const frozenRequestKey = `detail.submission/${currentUserId ?? project.owner_user_id}/${detailRequestKey(project, sourceFingerprint)}`;
      const persisted = restoreIdempotencyRecord(frozenRequestKey);
      if (!envelope || envelope.sourceFingerprint !== sourceFingerprint) {
        envelope =
          frozenDetailRequests.get(frozenRequestKey) ??
          (persisted
            ? { sourceFingerprint, request: persisted.request }
            : null);
        idempotencyEnvelopeRef.current = envelope;
      }
      if (!envelope || envelope.sourceFingerprint !== sourceFingerprint) {
        const finalText = finalPromptText;
        if (!finalText.trim()) throw new Error("请先填写提示词。");
        const duration = generationDuration;
        if (!isCurrent()) {
          throw new Error("生成参数已变化，请按最新报价重新提交。");
        }
        envelope = {
          sourceFingerprint,
          request: {
            quantity: generationQuantity,
            prompt_text: finalText,
            prompt_context: {
              source: "manual",
              ...readAppliedOptimization(
                `${currentUserId ?? project.owner_user_id}:${project.id}`,
                finalText,
                {
                  script_version_id: finalSnapshot.scriptVersionId,
                  shot_card_version_id: finalSnapshot.shotCardVersionId,
                },
              ),
              shot_card_version_id: finalSnapshot.shotCardVersionId,
              script_version_id: finalSnapshot.scriptVersionId,
              final_prompt_version_id: finalSnapshot.versionId,
            },
            first_frame_asset_id: firstFrameAssetId,
            output_duration_seconds: duration,
            resolution: "768P",
            ratio: generationRatio,
            provider: defaultBatchProvider(),
            fake_audio_quality: "ok",
            idempotency_key: newIdempotencyKey(),
          },
        };
        idempotencyEnvelopeRef.current = envelope;
        const { idempotency_key: key, ...body } = envelope.request;
        restoreOrCreateIdempotencyRecord(frozenRequestKey, body, null, key);
        frozenDetailRequests.set(frozenRequestKey, envelope);
      }
      if (!isCurrent()) {
        throw new Error("生成参数已变化，请按最新报价重新提交。");
      }
      // 扣分及免费资格由服务端按冻结报价校验，时长不能代表积分余额。
      const batch = await createGenerationBatch(project.id, envelope.request);
      if (idempotencyEnvelopeRef.current === envelope) {
        idempotencyEnvelopeRef.current = null;
      }
      if (frozenDetailRequests.get(frozenRequestKey) === envelope) {
        frozenDetailRequests.delete(frozenRequestKey);
      }
      const completed = restoreIdempotencyRecord(frozenRequestKey);
      if (completed?.key === envelope.request.idempotency_key)
        clearIdempotencyRecord(frozenRequestKey, completed);
      if (!isCurrent()) return;
      setGenerationPhase("done");
      setGenerationMessage("生成任务已创建，正在前往任务记录…");
      onBatchCreated(batch);
    } catch (error) {
      if (submissionOperationRef.current === operation) {
        setGenerationPhase("idle");
        setInsufficientBalance(
          (error as { code?: string })?.code === "INSUFFICIENT_CREDITS"
            ? {
                neededCredits: priceQuote?.estimated_credits ?? null,
                balanceCredits: null,
              }
            : null,
        );
        setGenerationError(
          error instanceof Error ? error.message : "创建生成任务失败，请重试。",
        );
      }
    } finally {
      if (submissionOperationRef.current === operation) {
        submissionBusyRef.current = false;
      }
    }
  }

  function renderPaidWarning() {
    return (
      <p className="flow-cost">
        预计消耗 {generationDuration * generationQuantity} 秒额度
        {priceQuoteReady && priceQuote
          ? priceQuote.estimated_credits !== undefined
            ? `，预计 ${priceQuote.estimated_credits} 积分（${priceQuote.unit_credits} 积分/秒）`
            : `，约 ¥${(priceQuote.estimated_price_fen / 100).toFixed(2)}（${priceQuote.unit_price_fen_per_second} 分/秒）`
          : ""}
        。
      </p>
    );
  }

  const referenceStatus = (() => {
    if (!characterSelection || !sourceFrameSelection) {
      return null;
    }
    if (referenceSelection) {
      return (
        <p className="setup-success" role="status">
          人物参考已匹配，可直接生成人物置换首帧。
        </p>
      );
    }
    if (referenceError) {
      return (
        <p className="settings-error" role="alert">
          {referenceError}{" "}
          <button
            className="secondary-button"
            onClick={retryReferenceMatch}
            type="button"
          >
            重试匹配
          </button>
        </p>
      );
    }
    return (
      <p className="status-note" role="status">
        源画面已确认，正在自动匹配人物五视图…
      </p>
    );
  })();
  const outputDurationSeconds = generationDuration;
  const sourceDurationSeconds = sourceVideoDurationSeconds();
  const scriptCharacterCount = countSpeechCharacters(scriptText);
  const suggestedScriptMin = outputDurationSeconds * 4;
  const suggestedScriptMax = outputDurationSeconds * 5;
  const scriptTooLong = scriptCharacterCount > suggestedScriptMax;

  return (
    <section aria-label={`生成流程 ${project.name}`} className="flow-page">
      <header className="flow-header">
        <div>
          <h2>生成流程</h2>
          <p className="flow-header__note">
            解析 → 源画面人物 → 人物置换首帧 → 自定义文案 → 提交生成
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={isBusy}
          onClick={onBack}
          type="button"
        >
          返回项目列表
        </button>
      </header>

      {analysisError ? (
        <p className="settings-error" role="alert">
          {analysisError}
        </p>
      ) : null}

      <fieldset className="flow-step">
        <legend>① 原片拆解</legend>
        <p>
          {analysisVersion
            ? readAnalysisPayload(analysisVersion)?.summary
            : "正在读取分析结果…"}
        </p>
      </fieldset>

      <fieldset
        className="flow-step"
        disabled={firstFrameGenerationBusy || generationPhase === "running"}
      >
        <legend>② 源画面与人物</legend>
        {firstFrameGenerationBusy ? (
          <p className="status-note">
            当前首帧正在使用这组源画面与人物，生成结束前暂不能更改。
          </p>
        ) : null}
        <CharacterSelection
          sceneOnly
          onBusyChange={(busy) => markUpstreamBusy("character", busy)}
          onVersionChange={handleCharacterChange}
          projectId={project.id}
          readOnly={readOnly}
          variant="inline"
        />
        <SourceFrameSelection
          onBusyChange={(busy) => markUpstreamBusy("source-frame", busy)}
          onConfirmed={() =>
            firstFrameStepRef.current?.scrollIntoView?.({
              behavior: "smooth",
              block: "start",
            })
          }
          onSelectionChange={handleSourceFrameChange}
          projectId={project.id}
          readOnly={readOnly}
          referenceAssetId={project.reference_asset_id}
          simplified
          videoDurationSeconds={sourceDurationSeconds}
        />
      </fieldset>

      <fieldset
        className="flow-step"
        disabled={generationPhase === "running"}
        ref={firstFrameStepRef}
      >
        <legend>③ 人物置换首帧</legend>
        {referenceStatus ? (
          referenceStatus
        ) : (
          <p className="flow-hint">确认源画面与角色后，即可生成首帧。</p>
        )}
        {sourceFrameSelection ? (
          <FirstFrameSelection
            onBusyChange={setFirstFrameGenerationBusy}
            onSelectionChange={handleFirstFrameChange}
            projectId={project.id}
            readOnly={readOnly}
            referenceSelection={referenceSelection}
            simplified
            sourceFrameSelectionId={sourceFrameSelection.id}
          />
        ) : null}
      </fieldset>

      <fieldset className="flow-step" disabled={generationPhase === "running"}>
        <legend>④ 自定义文案</legend>
        <div className="flow-script">
          <p className="flow-hint">
            已带入拆解原文，可直接修改。确认文案和首帧后，请在最后一步合成提示词并核对；提交时原样使用最终正文。
          </p>
          <textarea
            aria-label="自定义文案"
            disabled={readOnly || generationPhase === "running"}
            onChange={(event) => {
              scriptEdited.current = true;
              setScriptText(event.target.value);
            }}
            value={scriptText}
          />
          <p className="status-note">
            当前 {scriptCharacterCount} 字；{outputDurationSeconds} 秒成片建议约{" "}
            {suggestedScriptMin}–{suggestedScriptMax} 字（按每秒 4–5 字）。
          </p>
          {scriptTooLong ? (
            <p
              aria-label="文案时长警告"
              className="settings-error"
              role="alert"
            >
              当前文案已超过建议上限，口播可能无法在成片时长内完整表达；建议缩短后再提交。
            </p>
          ) : null}
        </div>
      </fieldset>

      {priceQuoteStatus === "error" ? (
        <div className="settings-error" role="alert">
          <p>{priceQuoteError}</p>
          <button
            className="secondary-button"
            onClick={retryPriceQuote}
            type="button"
          >
            重新获取生成报价
          </button>
        </div>
      ) : null}

      <fieldset
        className="flow-step"
        disabled={!firstFrameAssetId || generationPhase === "running"}
      >
        <legend>⑤ 提交生成</legend>
        {generationError ? (
          <p className="settings-error" role="alert">
            {generationError}
          </p>
        ) : null}
        {insufficientBalance && onRecharge ? (
          <div className="settings-error" role="alert">
            <button onClick={onRecharge} type="button">
              余额不足，去充值
            </button>
          </div>
        ) : null}
        {firstFrameAssetId ? (
          <>
            <div className="generation-parameter-grid">
              <label>
                画面比例
                <select
                  aria-label="画面比例"
                  onChange={(event) =>
                    setGenerationRatio(event.target.value as GenerationRatio)
                  }
                  value={generationRatio}
                >
                  <option value="adaptive">自动</option>
                  <option value="21:9">21:9</option>
                  <option value="16:9">16:9</option>
                  <option value="4:3">4:3</option>
                  <option value="1:1">1:1</option>
                  <option value="3:4">3:4</option>
                  <option value="9:16">9:16</option>
                </select>
              </label>
              <label>
                成片时长
                <select
                  aria-label="成片时长"
                  onChange={(event) =>
                    setGenerationDuration(Number(event.target.value) as 4 | 15)
                  }
                  value={generationDuration}
                >
                  <option value={4}>4 秒</option>
                  <option value={15}>15 秒</option>
                </select>
              </label>
              <label>
                生成数量
                <select
                  aria-label="生成数量"
                  onChange={(event) =>
                    setGenerationQuantity(
                      Number(event.target.value) as 1 | 2 | 4,
                    )
                  }
                  value={generationQuantity}
                >
                  <option value={1}>1</option>
                  <option value={2}>2</option>
                  <option value={4}>4</option>
                </select>
              </label>
            </div>
            <ReplicaFinalPromptControls
              input={finalInput}
              value={finalPromptText}
              snapshot={finalSnapshot}
              onPrepared={setFinalSnapshot}
              onChange={setRevisedPromptText}
              readOnly={readOnly || isBusy}
            />
            <PromptEditor
              scope={`${currentUserId ?? project.owner_user_id}:${project.id}`}
              value={finalPromptText}
              onChange={setRevisedPromptText}
              readOnly={readOnly || isBusy}
              context={{
                route: "replica",
                project_id: project.id,
                analysis_version_id: analysisVersion?.id,
                shot_card_version_id: finalSnapshot?.shotCardVersionId,
                script_version_id: finalSnapshot?.scriptVersionId,
                first_frame_asset_id: firstFrameAssetId ?? undefined,
                duration_seconds: generationDuration,
                ratio: generationRatio,
              }}
            />
            <button
              type="button"
              disabled={!finalReady || readOnly}
              onClick={() => {
                void saveGenerationPrompt(project.id, {
                  name: "复刻最终提示词",
                  prompt_text: finalPromptText,
                  base_prompt_version_id: finalSnapshot?.versionId,
                })
                  .then(() =>
                    setGenerationMessage("最终提示词已保存到我的提示词。"),
                  )
                  .catch((error: unknown) =>
                    setGenerationError(
                      error instanceof Error ? error.message : "保存失败",
                    ),
                  );
              }}
            >
              另存到我的提示词
            </button>
            {renderPaidWarning()}
            {generationMessage ? (
              <p className="setup-success" role="status">
                {generationMessage}
              </p>
            ) : null}
            <button
              disabled={!canStart || !finalReady}
              onClick={() => void handleStartGeneration()}
              type="button"
            >
              {generationPhase === "running"
                ? "正在创建生成任务"
                : `提交生成（${generationQuantity} 条）`}
            </button>
          </>
        ) : (
          <p className="flow-hint">确认首帧后即可提交生成。</p>
        )}
      </fieldset>
    </section>
  );
}

function countSpeechCharacters(value: string): number {
  return Array.from(value.replace(/\s+/g, "")).length;
}
