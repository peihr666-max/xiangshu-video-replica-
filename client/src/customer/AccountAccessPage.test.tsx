import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AccountAccessPage } from "./AccountAccessPage";

describe("account gate", () => {
  it("uses the official logo and submits a six-character registration password", async () => {
    const submit = vi.fn().mockResolvedValue(undefined);
    render(<AccountAccessPage onSubmit={submit} onHome={vi.fn()} />);
    expect(screen.getByAltText("众墅之家")).toHaveAttribute(
      "src",
      "/studio/brand.png",
    );
    fireEvent.click(screen.getByRole("button", { name: "去注册" }));
    fireEvent.change(screen.getByLabelText("用户名"), {
      target: { value: "alice" },
    });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "abc123" },
    });
    fireEvent.change(screen.getByLabelText("确认密码"), {
      target: { value: "abc123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "注册并登录" }));
    await waitFor(() =>
      expect(submit).toHaveBeenCalledWith({
        mode: "register",
        username: "alice",
        password: "abc123",
      }),
    );
  });

  it("rejects mismatched confirmation without contacting the server", () => {
    const submit = vi.fn();
    render(<AccountAccessPage onSubmit={submit} onHome={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "去注册" }));
    fireEvent.change(screen.getByLabelText("用户名"), {
      target: { value: "alice" },
    });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "abc123" },
    });
    fireEvent.change(screen.getByLabelText("确认密码"), {
      target: { value: "abc456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "注册并登录" }));
    expect(screen.getByRole("alert")).toHaveTextContent("两次输入的密码不一致");
    expect(submit).not.toHaveBeenCalled();
  });
});
