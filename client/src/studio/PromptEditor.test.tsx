import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PromptOptimizeResult } from "../api";
import {
  type FinalReplicaSnapshot,
  PromptEditor,
  ReplicaFinalPromptControls,
} from "./PromptEditor";
import { readAppliedOptimization } from "./usePromptOptimization";

const api = vi.hoisted(() => ({
  create: vi.fn(),
  get: vi.fn(),
  session: vi.fn(() => true),
  compile: vi.fn(),
  script: vi.fn(),
}));
vi.mock("../api", () => ({
  createPromptOptimization: api.create,
  getPromptOptimization: api.get,
  capturePromptSession: () => api.session,
  customerVisibleErrorMessage: (_error: unknown, fallback: string) => fallback,
  getLatestGenerationPrompt: vi.fn(async () => ({
    version: null,
    stale: false,
  })),
  getLatestProjectShotCards: vi.fn(async () => ({ id: "shots" })),
  createScriptVersion: api.script,
  compileGenerationPrompt: api.compile,
}));
function Harness({ scope = "user:project" }: { scope?: string }) {
  const [text, setText] = useState("原始提示词");
  return (
    <PromptEditor
      value={text}
      onChange={setText}
      scope={scope}
      context={{ route: "text_image", duration_seconds: 8 }}
    />
  );
}
const success: PromptOptimizeResult = {
  task_id: "task",
  status: "SUCCEEDED",
  mode: "T2VA",
  editor_revision: 0,
  context_hash: "hash",
  formatter_version: "v1",
  result: { prompt_text: "优化结果", warnings: [], validation_status: "valid" },
};

function FinalHarness({
  script = "新文案",
  frame = "frame",
  duration = 4,
}: {
  script?: string;
  frame?: string;
  duration?: number;
}) {
  const [text, setText] = useState("");
  const [snapshot, setSnapshot] = useState<FinalReplicaSnapshot | null>(null);
  return (
    <>
      <ReplicaFinalPromptControls
        input={{
          projectId: "project",
          scriptText: script,
          firstFrameAssetId: frame,
          duration,
          resolution: "768P",
          ratio: "adaptive",
          shotCardVersionId: "shots",
        }}
        value={text}
        onChange={setText}
        snapshot={snapshot}
        onPrepared={setSnapshot}
      />
      <textarea
        aria-label="最终正文"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
    </>
  );
}

it("keeps adopted optimization provenance scoped to the account and exact text", async () => {
  api.create.mockResolvedValue(success);
  render(<Harness scope="receipt-user:receipt-project" />);
  fireEvent.click(screen.getByRole("button", { name: "AI 优化提示词" }));
  await waitFor(() =>
    expect(screen.getByLabelText("提示词")).toHaveValue("优化结果"),
  );
  expect(
    readAppliedOptimization("receipt-user:receipt-project", "优化结果"),
  ).toEqual({
    source: "ai",
    optimization_task_id: "task",
    context_hash: "hash",
  });
  expect(
    readAppliedOptimization("other-user:receipt-project", "优化结果"),
  ).toEqual({});
  expect(
    readAppliedOptimization("receipt-user:receipt-project", "人工修改"),
  ).toEqual({});
});

describe("最终提示词后置", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.script.mockResolvedValue({ id: "script-final" });
    api.compile.mockResolvedValue({
      id: "final",
      payload: { prompt_text: "最终稿" },
    });
  });
  it("确认文案和首帧后才合成；改变时长使旧稿失效且保留编辑", async () => {
    const view = render(<FinalHarness frame="" />);
    fireEvent.click(screen.getByLabelText("确认采用以上文案"));
    expect(
      screen.getByRole("button", { name: "合成最终提示词" }),
    ).toBeDisabled();
    view.rerender(<FinalHarness />);
    fireEvent.click(screen.getByLabelText("确认采用以上文案"));
    fireEvent.click(screen.getByRole("button", { name: "合成最终提示词" }));
    await waitFor(() =>
      expect(screen.getByLabelText("最终正文")).toHaveValue("最终稿"),
    );
    expect(api.script).toHaveBeenCalledWith("project", {
      source: "custom",
      text: "新文案",
      shot_card_version_id: "shots",
    });
    fireEvent.change(screen.getByLabelText("最终正文"), {
      target: { value: "人工编辑" },
    });
    view.rerender(<FinalHarness duration={15} />);
    expect(screen.getByText(/最终稿待合成或更新/)).toBeInTheDocument();
    expect(screen.getByLabelText("最终正文")).toHaveValue("人工编辑");
    expect(api.compile).toHaveBeenCalledOnce();
  });
  it("明确无口播会保存空脚本，不把说明文字当作台词", async () => {
    render(<FinalHarness script="" />);
    fireEvent.click(screen.getByLabelText("确认本视频无口播"));
    fireEvent.click(screen.getByRole("button", { name: "合成最终提示词" }));
    await waitFor(() => expect(api.compile).toHaveBeenCalledOnce());
    expect(api.script).toHaveBeenCalledWith("project", {
      source: "no_narration",
      text: "",
      shot_card_version_id: "shots",
    });
  });
  it("迟到合成只作为候选展示，不能覆盖等待期间的人工修改", async () => {
    let finish: ((value: unknown) => void) | undefined;
    api.compile.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    render(<FinalHarness />);
    fireEvent.click(screen.getByLabelText("确认采用以上文案"));
    fireEvent.click(screen.getByRole("button", { name: "合成最终提示词" }));
    await waitFor(() => expect(api.compile).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByLabelText("最终正文"), {
      target: { value: "继续编辑" },
    });
    await act(async () => {
      finish?.({ id: "final", payload: { prompt_text: "迟到新稿" } });
    });
    expect(screen.getByLabelText("最终正文")).toHaveValue("继续编辑");
    fireEvent.click(screen.getByRole("button", { name: "采用这份最终稿" }));
    expect(screen.getByLabelText("最终正文")).toHaveValue("迟到新稿");
  });
});

describe("PromptEditor", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    api.session.mockReturnValue(true);
  });
  it("优化回填可撤销，继续手改后不能撤销覆盖新输入", async () => {
    api.create.mockResolvedValue(success);
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "AI 优化提示词" }));
    await waitFor(() =>
      expect(screen.getByLabelText("提示词")).toHaveValue("优化结果"),
    );
    fireEvent.click(screen.getByRole("button", { name: "撤销" }));
    expect(screen.getByLabelText("提示词")).toHaveValue("原始提示词");
    fireEvent.click(screen.getByRole("button", { name: "AI 优化提示词" }));
    await waitFor(() =>
      expect(screen.getByLabelText("提示词")).toHaveValue("优化结果"),
    );
    fireEvent.change(screen.getByLabelText("提示词"), {
      target: { value: "继续手改" },
    });
    expect(screen.queryByRole("button", { name: "撤销" })).toBeNull();
  });
  it("迟到结果不覆盖等待期间的编辑，可主动应用", async () => {
    let finish: ((value: PromptOptimizeResult) => void) | undefined;
    api.create.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "AI 优化提示词" }));
    fireEvent.change(screen.getByLabelText("提示词"), {
      target: { value: "新输入" },
    });
    await act(async () => finish?.(success));
    expect(screen.getByLabelText("提示词")).toHaveValue("新输入");
    fireEvent.click(screen.getByRole("button", { name: "应用此结果" }));
    expect(screen.getByLabelText("提示词")).toHaveValue("优化结果");
  });
  it.each(["project", "session"])("%s 变化后旧结果不回填", async (kind) => {
    let finish: ((value: PromptOptimizeResult) => void) | undefined;
    api.create.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const view = render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "AI 优化提示词" }));
    if (kind === "project") view.rerender(<Harness scope="other" />);
    else api.session.mockReturnValue(false);
    await act(async () => finish?.(success));
    expect(screen.getByLabelText("提示词")).toHaveValue("原始提示词");
    expect(screen.queryByRole("button", { name: "应用此结果" })).toBeNull();
  });
  it("失败保留原文，空白和超限时禁用按钮", async () => {
    api.create.mockRejectedValue(new Error("failed"));
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "AI 优化提示词" }));
    await screen.findByText("优化失败，原文已保留。");
    expect(screen.getByLabelText("提示词")).toHaveValue("原始提示词");
    fireEvent.change(screen.getByLabelText("提示词"), {
      target: { value: " " },
    });
    expect(
      screen.getByRole("button", { name: "AI 优化提示词" }),
    ).toBeDisabled();
    fireEvent.change(screen.getByLabelText("提示词"), {
      target: { value: "🎥".repeat(7000) },
    });
    expect(screen.getByRole("button", { name: "AI 优化提示词" })).toBeEnabled();
  });
  it("网络结果未知后重试沿用原请求，刷新后查询原任务", async () => {
    api.create
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(success);
    const view = render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "AI 优化提示词" }));
    await screen.findByText("优化失败，原文已保留。");
    const input = api.create.mock.calls[0][0];
    view.unmount();
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "AI 优化提示词" }));
    await waitFor(() =>
      expect(screen.getByLabelText("提示词")).toHaveValue("优化结果"),
    );
    expect(api.create.mock.calls[1][0]).toEqual(input);
  });
});
