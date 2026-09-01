import { type FormEvent, useState } from "react";

import {
  type ActivationBatchResult,
  type ActivationDownloadResult,
  type ActivationGenerateResult,
  AdminActivationError,
  adminActivationErrorMessage,
  createActivationCodeBatch,
  createIdempotencyKey,
  downloadActivationCodeExport,
  generateActivationCodes,
} from "../api.admin";

const MAX_CODES_PER_REQUEST = 100;

type GenerationPhase = "idle" | "creating" | "generating" | "retrieving";

type CompletedGeneration = {
  quantity: number;
  result: ActivationDownloadResult;
};

/**
 * A simple operator surface over the existing audited batch APIs.
 *
 * Batches remain the durable server-side audit boundary, but they are an
 * implementation detail here: one submission creates the hidden batch,
 * generates its codes and retrieves the one-time plaintext export.
 */
export function ActivationCodeBatchesPage({
  readOnly = false,
  onGenerated,
  onSessionExpired,
}: {
  readOnly?: boolean;
  onGenerated?: () => void;
  onSessionExpired?: () => void;
}) {
  const [quantity, setQuantity] = useState("1");
  const [phase, setPhase] = useState<GenerationPhase>("idle");
  const [error, setError] = useState("");
  const [copyNotice, setCopyNotice] = useState("");
  const [completed, setCompleted] = useState<CompletedGeneration | null>(null);

  // Preserve each write key and intermediate result across uncertain network
  // failures. A retry continues from the last confirmed stage instead of
  // minting another hidden batch or another set of codes.
  const [pendingBatch, setPendingBatch] =
    useState<ActivationBatchResult | null>(null);
  const [pendingExport, setPendingExport] =
    useState<ActivationGenerateResult | null>(null);
  const [createKey, setCreateKey] = useState<string | null>(null);
  const [generateKey, setGenerateKey] = useState<string | null>(null);
  const [downloadKey, setDownloadKey] = useState<string | null>(null);

  const parsedQuantity = Number(quantity);
  const actionLabel = phaseLabel(phase, parsedQuantity);
  const selectionLocked =
    phase !== "idle" ||
    pendingBatch !== null ||
    pendingExport !== null ||
    createKey !== null ||
    generateKey !== null ||
    downloadKey !== null;

  function handleFailure(cause: unknown, fallback: string) {
    if (cause instanceof AdminActivationError && cause.status === 401) {
      setError("会话已失效，请重新登录");
      onSessionExpired?.();
      return;
    }
    setError(adminActivationErrorMessage(cause, fallback));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setCopyNotice("");

    const validationError = validateGeneration(parsedQuantity);
    if (validationError) {
      setError(validationError);
      return;
    }

    const reason = `后台直接生成：${parsedQuantity} 个零初始额度激活码`;
    let batch = pendingBatch;
    let generated = pendingExport;
    let currentPhase: GenerationPhase = "creating";

    try {
      if (!batch) {
        setPhase("creating");
        const key = createKey ?? createIdempotencyKey();
        setCreateKey(key);
        batch = await createActivationCodeBatch(
          {
            name: createAutomaticBatchName(),
            face_value_fen: 0,
            credits: 0,
            quantity: parsedQuantity,
            activation_expires_at: oneYearFromNow(),
            reason,
          },
          key,
        );
        setPendingBatch(batch);
        setCreateKey(null);
      }

      currentPhase = "generating";
      if (!generated) {
        setPhase("generating");
        const key = generateKey ?? createIdempotencyKey();
        setGenerateKey(key);
        generated = await generateActivationCodes(
          batch.batch_id,
          parsedQuantity,
          reason,
          key,
          true,
        );
        setPendingExport(generated);
        setGenerateKey(null);
      }

      currentPhase = "retrieving";
      setPhase("retrieving");
      const key = downloadKey ?? createIdempotencyKey();
      setDownloadKey(key);
      const result = await downloadActivationCodeExport(
        generated.export_id,
        reason,
        key,
      );

      setCompleted({
        quantity: parsedQuantity,
        result,
      });
      setPendingBatch(null);
      setPendingExport(null);
      setCreateKey(null);
      setGenerateKey(null);
      setDownloadKey(null);
      onGenerated?.();
    } catch (cause) {
      handleFailure(cause, phaseErrorFallback(currentPhase));
      if (cause instanceof AdminActivationError && cause.status !== undefined) {
        // A server response is definitive. Clear the pipeline so a corrected
        // selection starts cleanly; only network/timeout failures retain the
        // intermediate state and idempotency keys for a safe retry.
        setPendingBatch(null);
        setPendingExport(null);
        setCreateKey(null);
        setGenerateKey(null);
        setDownloadKey(null);
      }
    } finally {
      setPhase("idle");
    }
  }

  async function copyAllCodes() {
    if (!completed) {
      return;
    }
    try {
      await navigator.clipboard.writeText(completed.result.codes.join("\n"));
      setCopyNotice("全部激活码已复制");
    } catch {
      setCopyNotice("复制失败，请手动选择激活码");
    }
  }

  return (
    <section className="activation-generator-page" aria-label="生成激活码">
      {readOnly ? (
        <p className="wallet-notice" role="status">
          当前为只读模式，不能生成激活码。
        </p>
      ) : null}
      {error ? (
        <p className="settings-error" role="alert">
          {error}
        </p>
      ) : null}

      <form className="activation-generator" onSubmit={submit}>
        <header className="activation-generator__header">
          <div>
            <p className="activation-generator__eyebrow">快速发码</p>
            <h2>直接生成激活码</h2>
          </div>
          <p>激活码仅开通账号，初始生成额度固定为 0；充值额度单独管理。</p>
        </header>

        <div className="activation-generator__field">
          <label htmlFor="activation-code-quantity">生成数量</label>
          <input
            aria-describedby="activation-code-quantity-hint"
            id="activation-code-quantity"
            inputMode="numeric"
            max={MAX_CODES_PER_REQUEST}
            min="1"
            step="1"
            type="number"
            value={quantity}
            disabled={selectionLocked}
            onChange={(event) => setQuantity(event.target.value)}
          />
          <span id="activation-code-quantity-hint">
            单次最多生成 {MAX_CODES_PER_REQUEST} 个
          </span>
        </div>

        <div className="activation-generator__summary" aria-live="polite">
          <span>每个激活码初始额度</span>
          <strong>0</strong>
          <span>
            激活后需要通过充值或后台调账获得生成额度 · 领取有效期 1 年
          </span>
        </div>

        <button
          className="activation-generator__submit"
          disabled={readOnly || phase !== "idle"}
          type="submit"
        >
          {actionLabel}
        </button>
      </form>

      {completed ? (
        <section className="activation-code-result" aria-label="新生成的激活码">
          <div className="activation-code-result__header">
            <div>
              <p className="activation-generator__eyebrow">生成成功</p>
              <h3>已生成 {completed.quantity} 个零初始额度激活码</h3>
            </div>
            <button type="button" onClick={copyAllCodes}>
              复制全部
            </button>
          </div>
          <p className="activation-code-result__warning">
            明文激活码仅在本页显示这一次，请立即复制并安全保存；列表页仅保留脱敏码。
          </p>
          <ul className="activation-code-result__list">
            {completed.result.codes.map((code) => (
              <li key={code}>
                <code>{code}</code>
              </li>
            ))}
          </ul>
          {copyNotice ? (
            <p className="wallet-notice" role="status">
              {copyNotice}
            </p>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}

function validateGeneration(quantity: number): string | null {
  if (
    !Number.isInteger(quantity) ||
    quantity < 1 ||
    quantity > MAX_CODES_PER_REQUEST
  ) {
    return `生成数量必须是 1 到 ${MAX_CODES_PER_REQUEST} 之间的整数`;
  }
  return null;
}

function oneYearFromNow(): string {
  const expiresAt = new Date();
  expiresAt.setUTCFullYear(expiresAt.getUTCFullYear() + 1);
  return expiresAt.toISOString();
}

function createAutomaticBatchName(): string {
  const stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 13);
  return `零额度授权码-${stamp}`;
}

function phaseLabel(phase: GenerationPhase, quantity: number): string {
  if (phase === "creating") {
    return "正在准备…";
  }
  if (phase === "generating") {
    return "正在生成…";
  }
  if (phase === "retrieving") {
    return "正在取回激活码…";
  }
  const count = Number.isInteger(quantity) && quantity > 0 ? quantity : 1;
  return `生成 ${count} 个激活码`;
}

function phaseErrorFallback(phase: GenerationPhase): string {
  if (phase === "creating") {
    return "准备激活码失败";
  }
  if (phase === "generating") {
    return "生成激活码失败";
  }
  return "读取明文激活码失败";
}
