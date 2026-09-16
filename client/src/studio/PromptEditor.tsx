import { type ReactNode, useEffect, useRef, useState } from "react";
import {
  compileGenerationPrompt,
  createScriptVersion,
  type GenerationRatio,
  type GenerationVersion,
  getLatestGenerationPrompt,
  getLatestProjectShotCards,
  type PromptGenerationContext,
} from "../api";
import { Icon } from "./ui";
import { usePromptOptimization } from "./usePromptOptimization";
import "./prompt-editor.css";

export type FinalReplicaSnapshot = {
  promptVersion?: GenerationVersion;
  inputKey: string;
  versionId: string;
  scriptVersionId: string;
  shotCardVersionId: string;
};

export function replicaInputKey(input: {
  projectId: string;
  scriptText: string;
  firstFrameAssetId: string;
  duration: number;
  resolution: "768P" | "2K";
  ratio: GenerationRatio;
  shotCardVersionId?: string;
}) {
  return JSON.stringify(input);
}

/** Shared final step for all replica entry points; compilation is always explicit. */
export function ReplicaFinalPromptControls({
  input,
  value,
  onChange,
  snapshot,
  onPrepared,
  readOnly = false,
}: {
  input: Parameters<typeof replicaInputKey>[0];
  value: string;
  onChange: (text: string) => void;
  snapshot: FinalReplicaSnapshot | null;
  onPrepared: (snapshot: FinalReplicaSnapshot | null) => void;
  readOnly?: boolean;
}) {
  const key = replicaInputKey(input);
  const [confirmedKey, setConfirmedKey] = useState("");
  const [scale, setScale] = useState(false);
  const [openingAction, setOpeningAction] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState<{
    text: string;
    snapshot: FinalReplicaSnapshot;
  } | null>(null);
  const current = useRef({ key, value });
  current.current = { key, value };
  const operation = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const ready = snapshot?.inputKey === key;
  const preparedCallback = useRef(onPrepared);
  preparedCallback.current = onPrepared;
  useEffect(() => {
    let active = true;
    const revision = operation.current;
    if (!input.projectId || !input.firstFrameAssetId) return;
    void Promise.resolve()
      .then(() => getLatestGenerationPrompt(input.projectId))
      .then((state) => {
        const version = state.version;
        const payload = version?.payload;
        if (
          !active ||
          revision !== operation.current ||
          !version ||
          state.stale ||
          !payload?.final_composition
        )
          return;
        if (
          payload.confirmed_script_text !== input.scriptText.trim() ||
          payload.first_frame_asset_id !== input.firstFrameAssetId ||
          payload.output_duration_seconds !== input.duration ||
          payload.resolution !== input.resolution ||
          payload.ratio !== input.ratio ||
          (input.shotCardVersionId &&
            payload.shot_card_version_id !== input.shotCardVersionId)
        )
          return;
        setConfirmedKey(key);
        setScale(payload.timeline_policy === "scale_confirmed");
        setOpeningAction(String(payload.opening_action ?? ""));
        preparedCallback.current({
          inputKey: key,
          versionId: version.id,
          promptVersion: version,
          scriptVersionId: String(payload.script_version_id),
          shotCardVersionId: String(payload.shot_card_version_id),
        });
      })
      .catch(() => {
        /* Read recovery never starts another paid task. */
      });
    return () => {
      active = false;
    };
  }, [
    key,
    input.projectId,
    input.firstFrameAssetId,
    input.scriptText,
    input.duration,
    input.resolution,
    input.ratio,
    input.shotCardVersionId,
  ]);
  async function compose() {
    if (busy || readOnly || confirmedKey !== key || !input.firstFrameAssetId)
      return;
    operation.current += 1;
    setPending(null);
    setBusy(true);
    onPrepared(null);
    setMessage("");
    const start = { key, value };
    try {
      const shots =
        input.shotCardVersionId ||
        (await getLatestProjectShotCards(input.projectId))?.id;
      if (!shots) throw new Error("请先完成视频拆解和分镜准备。");
      if (!mounted.current || current.current.key !== start.key) return;
      const script = await createScriptVersion(input.projectId, {
        source: input.scriptText.trim() ? "custom" : "no_narration",
        text: input.scriptText,
        shot_card_version_id: shots,
      });
      if (!mounted.current || current.current.key !== start.key) return;
      const result = await compileGenerationPrompt(input.projectId, {
        script_version_id: script.id,
        shot_card_version_id: shots,
        first_frame_asset_id: input.firstFrameAssetId,
        output_duration_seconds: input.duration,
        resolution: input.resolution,
        ratio: input.ratio,
        timeline_policy: scale ? "scale_confirmed" : "preserve",
        opening_action: openingAction,
      });
      if (!mounted.current || current.current.key !== start.key) return;
      const text = String(result.payload.prompt_text ?? "");
      const prepared = {
        inputKey: key,
        versionId: result.id,
        promptVersion: result,
        scriptVersionId: script.id,
        shotCardVersionId: shots,
      };
      if (current.current.value !== start.value || start.value.trim()) {
        setPending({ text, snapshot: prepared });
        onPrepared(null);
        setMessage("新稿已就绪，当前正文保留；核对后采用新稿。");
      } else {
        onChange(text);
        onPrepared(prepared);
        setMessage("最终提示词已合成，请核对正文、首帧和费用后提交。");
      }
    } catch (error) {
      if (mounted.current)
        setMessage(error instanceof Error ? error.message : "最终合成失败");
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <section aria-label="最终提示词合成">
      <p>
        确认文案和首帧后合成最终提示词。更换文案、首帧、分镜、时长或画幅后需要重新合成，当前编辑会保留。
      </p>
      <pre>{input.scriptText || "无口播"}</pre>
      <label>
        <input
          type="checkbox"
          disabled={readOnly || busy}
          checked={confirmedKey === key}
          onChange={(event) => {
            setConfirmedKey(event.target.checked ? key : "");
            if (!event.target.checked) {
              operation.current += 1;
              onPrepared(null);
            }
          }}
        />
        {input.scriptText.trim() ? "确认采用以上文案" : "确认本视频无口播"}
      </label>
      <label>
        <input
          type="checkbox"
          disabled={readOnly || busy}
          checked={scale}
          onChange={(event) => {
            operation.current += 1;
            setPending(null);
            setScale(event.target.checked);
            onPrepared(null);
          }}
        />
        明确允许按目标时长调整动作节奏（不删减台词）
      </label>
      <label>
        中段首帧的开场衔接方案（选开场帧可留空）
        <textarea
          value={openingAction}
          disabled={readOnly || busy}
          onChange={(event) => {
            operation.current += 1;
            setPending(null);
            setOpeningAction(event.target.value);
            onPrepared(null);
          }}
        />
      </label>
      <button
        type="button"
        disabled={
          readOnly || busy || confirmedKey !== key || !input.firstFrameAssetId
        }
        onClick={() => void compose()}
      >
        {busy ? "正在合成…" : "合成最终提示词"}
      </button>
      <p role="status">
        {ready ? "最终稿来源已绑定" : "最终稿待合成或更新"}。{message}
      </p>
      {pending && (
        <details open>
          <summary>核对新稿（当前编辑保留）</summary>
          <pre>{pending.text}</pre>
          <button
            type="button"
            disabled={pending.snapshot.inputKey !== key || readOnly}
            onClick={() => {
              onChange(pending.text);
              onPrepared(pending.snapshot);
              setPending(null);
            }}
          >
            采用这份最终稿
          </button>
        </details>
      )}
    </section>
  );
}

type Props = {
  value: string;
  onChange: (value: string) => void;
  context: PromptGenerationContext;
  scope: string;
  label?: string;
  placeholder?: string;
  readOnly?: boolean;
  optimizationDisabled?: boolean;
  rows?: number;
  toolbarStart?: ReactNode;
  showToolbarLabel?: boolean;
  toolbarLabel?: ReactNode;
};

export function PromptEditor({
  value,
  onChange,
  context,
  scope,
  label = "提示词",
  placeholder,
  readOnly = false,
  optimizationDisabled = false,
  rows = 8,
  toolbarStart,
  showToolbarLabel = false,
  toolbarLabel = "画面描述",
}: Props) {
  const optimization = usePromptOptimization(value, context, onChange, scope);
  const count = Array.from(value).length;
  return (
    <div className="h3-prompt-editor">
      <div className="h3-prompt-tools">
        {showToolbarLabel && (
          <span className="h3-prompt-label">{toolbarLabel}</span>
        )}
        {toolbarStart}
        {optimization.canUndo && !readOnly && (
          <button type="button" onClick={optimization.undo}>
            撤销
          </button>
        )}
        <button
          type="button"
          aria-label="AI 优化提示词"
          title="按当前模式优化为 MiniMax-H3 格式"
          aria-busy={optimization.busy}
          disabled={
            readOnly ||
            optimizationDisabled ||
            optimization.busy ||
            !value.trim() ||
            count > 7000
          }
          onClick={() => void optimization.run()}
        >
          <Icon name={optimization.busy ? "refresh" : "sparkles"} size={16} />
          <span>{optimization.busy ? "正在优化…" : "AI 优化提示词"}</span>
        </button>
      </div>
      <textarea
        aria-label={label}
        className="creation-textarea"
        value={value}
        rows={rows}
        readOnly={readOnly}
        disabled={readOnly}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      <small>{count}/7000 字</small>
      {count > 7000 && <p role="alert">提示词超过 7000 字，请精简后提交。</p>}
      {optimization.message && <p role="status">{optimization.message}</p>}
      {optimization.pending && (
        <details>
          <summary>查看基于旧内容的优化结果</summary>
          <pre>{optimization.pending.text}</pre>
          <button
            type="button"
            disabled={readOnly}
            onClick={optimization.applyPending}
          >
            应用此结果
          </button>
        </details>
      )}
    </div>
  );
}
