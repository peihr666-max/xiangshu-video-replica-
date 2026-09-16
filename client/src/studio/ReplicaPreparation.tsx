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
import { Button, Field, Hint, Icon, Panel, Tabs } from "./ui";

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
