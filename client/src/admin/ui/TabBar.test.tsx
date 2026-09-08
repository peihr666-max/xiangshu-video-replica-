import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TabBar } from "./TabBar";

describe("TabBar", () => {
<<<<<<< main
  it("renders items, marks the active tab, and reports selection", () => {
=======
  it("uses a labelled button group and reports selection", () => {
>>>>>>> codex/local-main-brand-shell-20260908
    const onChange = vi.fn();
    render(
      <TabBar
        active="a"
        ariaLabel="测试页签"
        items={[
          { id: "a", label: "甲" },
          { id: "b", label: "乙" },
        ]}
        onChange={onChange}
      />,
    );

<<<<<<< main
    expect(screen.getByRole("tab", { name: "甲" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "乙" })).toHaveAttribute(
      "aria-selected",
      "false",
    );

    fireEvent.click(screen.getByRole("tab", { name: "乙" }));
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("renders the optional actions slot", () => {
    render(
      <TabBar
        active="a"
        actions={<button type="button">动作按钮</button>}
        ariaLabel="测试页签"
        items={[{ id: "a", label: "甲" }]}
        onChange={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "动作按钮" }),
    ).toBeInTheDocument();
=======
    expect(screen.getByRole("group", { name: "测试页签" })).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "甲" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "乙" }));
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("keeps every option keyboard-focusable as a native button", () => {
    render(
      <TabBar
        active="a"
        ariaLabel="键盘页签"
        items={[
          { id: "a", label: "甲" },
          { id: "b", label: "乙" },
        ]}
        onChange={() => {}}
      />,
    );

    const second = screen.getByRole("button", { name: "乙" });
    second.focus();

    expect(second).toHaveFocus();
    expect(second).not.toHaveAttribute("tabindex", "-1");
>>>>>>> codex/local-main-brand-shell-20260908
  });
});
