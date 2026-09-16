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
import { PromptEditor } from "./PromptEditor";

const api = vi.hoisted(() => ({
  create: vi.fn(),
  get: vi.fn(),
  session: vi.fn(() => true),
}));
vi.mock("../api", () => ({
  createPromptOptimization: api.create,
  getPromptOptimization: api.get,
  capturePromptSession: () => api.session,
  customerVisibleErrorMessage: (_error: unknown, fallback: string) => fallback,
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
