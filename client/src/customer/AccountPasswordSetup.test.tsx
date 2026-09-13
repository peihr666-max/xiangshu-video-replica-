import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AccountPasswordSetup } from "./AccountPasswordSetup";

vi.mock("../api", () => ({
  customerPasswordState: vi.fn().mockResolvedValue({
    user_id: "u",
    username: "legacy",
    has_password: false,
  }),
  customerSetInitialPassword: vi.fn(),
}));
it("shows initial password setup only for credential-less accounts", async () => {
  render(
    <AccountPasswordSetup
      credential={async () => ({ kind: "session", token: "local" })}
      onComplete={() => {}}
    />,
  );
  expect(await screen.findByLabelText("登录用户名")).toHaveValue("legacy");
  expect(screen.getByLabelText("设置登录密码")).toHaveAttribute(
    "minlength",
    "6",
  );
});
