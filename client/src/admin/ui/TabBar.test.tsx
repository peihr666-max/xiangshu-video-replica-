import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TabBar } from "./TabBar";

describe("TabBar", () => {
  it("uses a labelled button group and reports selection", () => {
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
  });
});
