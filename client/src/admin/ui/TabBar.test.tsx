import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TabBar } from "./TabBar";

describe("TabBar", () => {
  it("marks the active tab and reports selection", () => {
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

    expect(screen.getByRole("tab", { name: "甲" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    fireEvent.click(screen.getByRole("tab", { name: "乙" }));
    expect(onChange).toHaveBeenCalledWith("b");
  });
});
