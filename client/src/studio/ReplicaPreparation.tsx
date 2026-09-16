import { useEffect, useRef, useState } from "react";
import {
  capturePromptSession,
  customerVisibleErrorMessage,
  rewriteProjectScript,
  waitForScriptRewriteTask,
} from "../api";
import { useStudio } from "./context";
import {
  clearScriptRewriteIdempotencyKey,
  scriptRewriteIdempotencyKey,
  shouldClearScriptRewriteIdempotencyKey,
} from "./scriptRewrite";
import type { StudioDraft } from "./types";
import { Button, Field, Hint, Icon, Panel, Tabs } from "./ui";
import { usePromptOptimization } from "./usePromptOptimization";

export function replicaPromptBasis(draft: StudioDraft) {
  return JSON.stringify([
    draft.projectId,
    draft.sourceAssetId,
    draft.script.text,
    draft.replicaSourcePrompt ?? "",
  ]);
}

export function replicaPromptReady(draft: StudioDraft) {
  return Boolean(
    draft.prompt.trim() &&
      draft.replicaPromptBasis === replicaPromptBasis(draft),
  );
}

export function ReplicaWorkflowNavigation() {
  const { state, navigate } = useStudio();
  return (
    <Tabs
      value={state.page}
      items={[
        { id: "replica", label: "01 内容配置" },
        { id: "replacement", label: "02 首帧置换" },
      ]}
      onChange={(page) => navigate(page as "replica" | "replacement")}
    />
  );
}

export function ReplicaNarration() {
  const { state, user, review, patchDraft } = useStudio();
  const draft = state.draft;
  const readOnly = user.role === "auditor";
  const key = JSON.stringify([
    user.id,
    draft.id,
    draft.projectId,
    draft.sourceAssetId,
    draft.ipId,
  ]);
  const latest = useRef({
    key,
    text: draft.script.text,
    revision: 0,
    draft,
    patchDraft,
    readOnly,
  });
  const revision =
    latest.current.revision +
    Number(
      latest.current.key !== key || latest.current.text !== draft.script.text,
    );
  latest.current = {
    key,
    text: draft.script.text,
    revision,
    draft,
    patchDraft,
    readOnly,
  };
  const mounted = useRef(true);
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [undo, setUndo] = useState<{
    key: string;
    before: string;
    after: string;
  } | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const rewrite = async () => {
    if (
      review ||
      readOnly ||
      inFlight.current ||
      !draft.projectId ||
      !draft.script.text.trim()
    )
      return;
    const started = { ...latest.current };
    const sessionCurrent = capturePromptSession();
    const current = () =>
      mounted.current &&
      sessionCurrent() &&
      latest.current.key === started.key &&
      !latest.current.readOnly;
    const scope = {
      accountId: user.id,
      projectId: draft.projectId,
      sourceAssetId: draft.sourceAssetId ?? "",
      identityId: draft.ipId ?? "",
      scriptId: draft.script.id,
      scriptVersion: draft.script.version,
      text: draft.script.text,
    };
    const requestKey = scriptRewriteIdempotencyKey(scope);
    inFlight.current = true;
    setBusy(true);
    setMessage("");
    try {
      const task = await rewriteProjectScript(
        draft.projectId,
        draft.script.text,
        draft.ipId,
        draft.sourceAssetId,
        requestKey,
      );
      const result = await waitForScriptRewriteTask(task.id);
      if (
        result.status !== "SUCCEEDED" ||
        !result.result?.rewritten_text?.trim()
      )
        throw new Error(
          result.error_message || "AI 改写未完成，当前文案已保留。",
        );
      clearScriptRewriteIdempotencyKey(scope, requestKey);
      if (!current()) return;
      if (latest.current.revision !== started.revision) {
        setMessage("文案已修改，迟到的改写结果未覆盖当前内容。");
        return;
      }
      const text = result.result.rewritten_text;
      setUndo({ key, before: started.text, after: text });
      latest.current.patchDraft({
        script: { ...latest.current.draft.script, text, confirmed: false },
        scriptEdited: true,
      });
      setMessage("AI 改写已完成，可继续编辑");
    } catch (cause) {
      if (shouldClearScriptRewriteIdempotencyKey(cause))
        clearScriptRewriteIdempotencyKey(scope, requestKey);
      if (current())
        setMessage(
          customerVisibleErrorMessage(cause, "AI 改写失败，当前文案已保留。"),
        );
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  };
  return (
    <Panel className="creation-replica-narration">
      <div className="creation-panel-title-row">
        <span>
          <b className="creation-step-number">01</b> 提取文案与修改口播
        </span>
        <Button
          variant="outline"
          disabled={
            readOnly ||
            review ||
            busy ||
            !draft.projectId ||
            !draft.script.text.trim()
          }
          onClick={() => void rewrite()}
        >
          <Icon name="sparkles" />
          {busy ? "AI 改写中…" : "AI 改写"}
        </Button>
      </div>
      <Field label="口播文案 · 可直接编辑">
        <textarea
          aria-label="口播文案"
          className="creation-textarea"
          rows={5}
          readOnly={readOnly}
          value={draft.script.text}
          onChange={(event) => {
            if (!readOnly)
              patchDraft({
                script: {
                  ...draft.script,
                  text: event.target.value,
                  confirmed: false,
                },
                scriptEdited: true,
              });
          }}
          placeholder="完成拆解后，原视频口播文案会出现在这里。"
        />
      </Field>
      <div className="creation-panel-title-row">
        <Hint>
          {message || "提取原文后在此编辑，AI 改写完成后直接替换框内文案。"}
        </Hint>
        {undo?.key === key && undo.after === draft.script.text && (
          <Button
            variant="quiet"
            disabled={readOnly || busy}
            onClick={() => {
              patchDraft({
                script: {
                  ...draft.script,
                  text: undo.before,
                  confirmed: false,
                },
                scriptEdited: true,
              });
              setUndo(null);
              setMessage("已撤销上次改写");
            }}
          >
            撤销上次改写
          </Button>
        )}
      </div>
    </Panel>
  );
}

export function ReplicaPromptResult() {
  const { state, user, review, patchDraft } = useStudio();
  const draft = state.draft;
  const basis = replicaPromptBasis(draft);
  const readOnly = user.role === "auditor";
  const input = `当前口播文案（唯一有效台词，替换拆解中的全部旧台词）：\n${draft.script.text}\n\n视频拆解与运镜依据：\n${draft.replicaSourcePrompt ?? ""}`;
  const optimizer = usePromptOptimization(
    input,
    {
      route: "replica",
      project_id: draft.projectId,
      source_asset_id: draft.sourceAssetId,
      duration_seconds: draft.duration,
      instructions:
        "根据当前口播与视频拆解生成新的复刻提示词。当前口播是唯一有效台词，原拆解旧台词不可沿用。保留动作、运镜、节奏；人物外貌、服装与场景以随后提供的新首图为准，不锁定原人物或原背景。此阶段只准备提示词，不生成视频。",
    },
    (prompt) =>
      patchDraft({ prompt, promptEdited: true, replicaPromptBasis: basis }),
    `${user.id}:${user.role}:${draft.id}:${basis}`,
  );
  const ready = replicaPromptReady(draft);
  const basisFresh = draft.replicaPromptBasis === basis;
  return (
    <Panel className="creation-replica-result">
      <div className="creation-panel-title-row">
        <span>
          <b className="creation-step-number">03</b> 新的复刻提示词
        </span>
        <Button
          variant="primary"
          disabled={
            readOnly ||
            review ||
            optimizer.busy ||
            !draft.script.text.trim() ||
            !draft.replicaSourcePrompt?.trim()
          }
          onClick={() => void optimizer.run()}
        >
          {optimizer.busy ? "正在生成新提示词…" : "生成新提示词"}
        </Button>
      </div>
      <Hint>
        使用上方最新口播与拆解内容；人物、服装和场景以随后采用的新首图为准。
      </Hint>
      {draft.replicaPromptBasis && !ready && (
        <p role="status" className="creation-inline-error">
          文案或拆解已修改，请重新生成新提示词。
        </p>
      )}
      <textarea
        className="creation-textarea"
        aria-label="新的复刻提示词"
        rows={7}
        readOnly={readOnly || !basisFresh}
        value={draft.replicaPromptBasis ? draft.prompt : ""}
        placeholder="生成后在这里核对新提示词，再进入首帧置换。"
        onChange={(event) => {
          if (!readOnly && basisFresh)
            patchDraft({ prompt: event.target.value, promptEdited: true });
        }}
      />
      <Hint>
        {optimizer.message || (ready ? "新提示词已就绪" : "等待生成新提示词")}
      </Hint>
    </Panel>
  );
}
