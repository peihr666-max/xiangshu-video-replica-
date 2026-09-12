import type { GenerationBatch } from "./api";
import { GenerationLauncher } from "./GenerationLauncher";
import type { GenerationDrafts } from "./useGenerationDrafts";

type GenerationComposerProps = {
  analysisVersionId: string;
  characterVersionId: string | null;
  drafts: GenerationDrafts;
  firstFrameAssetId: string;
  firstFrameSelectionVersionId: string;
  onBatchCreated: (batch: GenerationBatch) => void;
  /** 余额不足时的充值引导动作（客户 lane 打开充值弹窗，内部 lane 跳钱包页）。 */
  onRecharge?: () => void;
  readOnly?: boolean;
  referenceSelectionId: string | null;
  shotCardVersionId: string;
};

// P0-02-03：口播稿编辑（ScriptEditor）迁至标签页①，本组件瘦身为
// 标签页③的生成面板，消费工作区提升的 useGenerationDrafts 单一状态源。
export function GenerationComposer({
  analysisVersionId,
  characterVersionId,
  drafts,
  firstFrameAssetId,
  firstFrameSelectionVersionId,
  onBatchCreated,
  onRecharge,
  readOnly = false,
  referenceSelectionId,
  shotCardVersionId,
}: GenerationComposerProps) {
  if (drafts.isLoading) {
    return <p className="status-note">正在读取口播稿与 Prompt</p>;
  }

  return (
    <section
      className="generation-composer"
      aria-labelledby="generation-composer-title"
    >
      <div className="section-heading">
        <div>
          <h3 id="generation-composer-title">口播稿与 Prompt</h3>
        </div>
      </div>

      {drafts.error ? <p className="settings-error">{drafts.error}</p> : null}
      {drafts.insufficientBalance && onRecharge ? (
        <div className="settings-error" role="alert">
          <button onClick={onRecharge} type="button">
            余额不足，去充值
          </button>
        </div>
      ) : null}
      {drafts.message ? (
        <p className="setup-success">{drafts.message}</p>
      ) : null}

      <GenerationLauncher
        analysisVersionId={analysisVersionId}
        busyAction={drafts.busyAction}
        canCompile={drafts.canCompile}
        canCreateBatch={drafts.canCreateBatch}
        characterVersionId={characterVersionId}
        durationValid={drafts.durationValid}
        firstFrameAssetId={firstFrameAssetId}
        firstFrameSelectionVersionId={firstFrameSelectionVersionId}
        limits={drafts.limits}
        onCompilePrompt={drafts.compilePrompt}
        onCreateBatch={() => drafts.createBatch(onBatchCreated)}
        onDurationChange={drafts.setOutputDuration}
        onLockPrompt={drafts.lockPrompt}
        onPromptTextChange={drafts.setPromptText}
        onRetryPriceQuote={drafts.retryPriceQuote}
        onRatioChange={drafts.setRatio}
        onQuantityChange={drafts.setQuantityInput}
        onRecoverBatch={() => drafts.recoverBatch(onBatchCreated)}
        onResolutionChange={drafts.setResolution}
        onSavePromptRevision={drafts.savePromptRevision}
        onApplySavedPrompt={drafts.applySavedPrompt}
        outputDuration={drafts.outputDuration}
        promptDirty={drafts.promptDirty}
        promptParametersMatch={drafts.promptParametersMatch}
        promptStale={drafts.promptStale}
        promptText={drafts.promptText}
        promptVersion={drafts.promptVersion}
        priceQuote={drafts.priceQuote}
        priceQuoteError={drafts.priceQuoteError}
        priceQuoteStatus={drafts.priceQuoteStatus}
        quantity={drafts.quantity}
        quantityError={drafts.quantityError}
        quantityInput={drafts.quantityInput}
        readOnly={readOnly}
        recoveryRecord={drafts.recoveryRecord}
        recoveryRecordConflicts={drafts.recoveryRecordConflicts}
        referenceSelectionId={referenceSelectionId}
        resolution={drafts.resolution}
        ratio={drafts.ratio}
        savedPrompts={drafts.savedPrompts}
        savedPromptText={drafts.savedPromptText}
        scriptStale={drafts.scriptStale}
        shotCardVersionId={shotCardVersionId}
      />
    </section>
  );
}
