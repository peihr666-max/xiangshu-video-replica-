import { useEffect, useRef, useState } from "react";
import {
  createOralComposition,
  downloadMaterialAsset,
  getOralCompositionCapabilities,
  listOralCompositions,
  type OralCompositionCapabilities,
  type OralCompositionRecord,
  type OralCompositionTemplate,
} from "../api";
import { Button, Field, Hint, Panel } from "./ui";

const STATUS_LABELS: Record<OralCompositionRecord["status"], string> = {
  QUEUED: "排队中",
  RUNNING: "合成中",
  SUCCEEDED: "已完成",
  FAILED: "合成失败",
  CANCELLED: "已取消",
};

function templateTitle(
  capabilities: OralCompositionCapabilities,
  template: OralCompositionTemplate,
) {
  return (
    capabilities.templates.find((item) => item.id === template)?.title ??
    template
  );
}

export function OralCompositionPanel({
  oralTaskId,
  defaultText,
  onActivated,
}: {
  oralTaskId: string;
  defaultText: string;
  onActivated?: () => void;
}) {
  const [capabilities, setCapabilities] =
    useState<OralCompositionCapabilities>();
  const [items, setItems] = useState<OralCompositionRecord[]>([]);
  const [template, setTemplate] =
    useState<OralCompositionTemplate>("bottom_caption");
  const [text, setText] = useState(defaultText);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const pendingRequestRef = useRef<
    | {
        signature: string;
        idempotencyKey: string;
      }
    | undefined
  >(undefined);
  const activeResultRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getOralCompositionCapabilities(),
      listOralCompositions(oralTaskId),
    ])
      .then(([nextCapabilities, nextItems]) => {
        if (cancelled) return;
        setCapabilities(nextCapabilities);
        setItems(nextItems);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setStatus(
            cause instanceof Error && cause.message.trim()
              ? cause.message
              : "读取后期版本失败",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [oralTaskId]);

  const hasPending = items.some(
    (item) => item.status === "QUEUED" || item.status === "RUNNING",
  );

  useEffect(() => {
    if (!hasPending) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      listOralCompositions(oralTaskId)
        .then((nextItems) => {
          if (cancelled) return;
          setItems(nextItems);
        })
        .catch((cause: unknown) => {
          if (!cancelled) {
            setStatus(
              cause instanceof Error && cause.message.trim()
                ? cause.message
                : "刷新后期版本失败",
            );
          }
        });
    }, 2_500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [hasPending, oralTaskId]);

  useEffect(() => {
    const result = items.find(
      (item) =>
        item.is_active && item.status === "SUCCEEDED" && item.result_asset_id,
    )?.result_asset_id;
    if (!result || activeResultRef.current === result) return;
    activeResultRef.current = result;
    onActivated?.();
  }, [items, onActivated]);

  async function createVersion() {
    const normalizedText = text.trim();
    if (!normalizedText || busy) return;
    setBusy(true);
    setStatus("");
    const signature = JSON.stringify({ template, text: normalizedText });
    if (pendingRequestRef.current?.signature !== signature) {
      pendingRequestRef.current = {
        signature,
        idempotencyKey: `oral-compose:${oralTaskId}:${crypto.randomUUID()}`,
      };
    }
    try {
      const created = await createOralComposition(oralTaskId, {
        template,
        text: normalizedText,
        idempotencyKey: pendingRequestRef.current.idempotencyKey,
      });
      pendingRequestRef.current = undefined;
      setItems((current) => [
        created,
        ...current.filter((item) => item.id !== created.id),
      ]);
      setStatus("已创建独立后期版本，原口播成片保持不变。");
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "创建后期版本失败");
    } finally {
      setBusy(false);
    }
  }

  if (!capabilities) {
    return (
      <Panel className="studio-oral-composition">
        <h2>网感后期</h2>
        <Hint>{status || "正在读取后期合成能力…"}</Hint>
      </Panel>
    );
  }

  if (!capabilities.available) {
    return (
      <Panel className="studio-oral-composition">
        <h2>网感后期</h2>
        <Hint>{capabilities.reason || "当前环境不支持后期合成。"}</Hint>
      </Panel>
    );
  }

  const active = items.find(
    (item) =>
      item.is_active && item.status === "SUCCEEDED" && item.result_asset_id,
  );
  return (
    <Panel className="studio-oral-composition">
      <h2>网感后期</h2>
      <Hint>每次生成新版本，不覆盖 Hifly 原始成片，也不再次扣费。</Hint>
      <Field label="后期模板">
        <select
          value={template}
          onChange={(event) =>
            setTemplate(event.target.value as OralCompositionTemplate)
          }
        >
          {capabilities.templates.map((item) => (
            <option key={item.id} value={item.id}>
              {item.title}
            </option>
          ))}
        </select>
      </Field>
      <Field label="后期文字">
        <textarea
          rows={3}
          maxLength={120}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      </Field>
      <div className="studio-compose-actions">
        <Button
          variant="primary"
          disabled={busy || !text.trim()}
          onClick={() => void createVersion()}
        >
          {busy ? "正在创建…" : "生成后期版本"}
        </Button>
        {active?.result_asset_id ? (
          <Button
            onClick={() =>
              void downloadMaterialAsset(
                active.result_asset_id as string,
                `${defaultText}-${templateTitle(capabilities, active.template)}.mp4`,
              )
            }
          >
            下载当前后期版本
          </Button>
        ) : null}
      </div>
      {status ? <p role="status">{status}</p> : null}
      {items.length ? (
        <ul className="studio-compose-versions">
          {items.map((item) => (
            <li key={item.id}>
              <b>{templateTitle(capabilities, item.template)}</b>
              <span>{STATUS_LABELS[item.status]}</span>
              {item.is_active ? <small>当前版本</small> : null}
              {item.error_message ? <small>{item.error_message}</small> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p>尚未生成后期版本。</p>
      )}
    </Panel>
  );
}
