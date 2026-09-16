import type { PromptGenerationContext } from "../api";
import { usePromptOptimization } from "./usePromptOptimization";
import "./prompt-editor.css";

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
}: Props) {
  const optimization = usePromptOptimization(value, context, onChange, scope);
  const count = Array.from(value).length;
  return (
    <div className="h3-prompt-editor">
      <div className="h3-prompt-tools">
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
          {optimization.busy ? "◌" : "✦"}
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
