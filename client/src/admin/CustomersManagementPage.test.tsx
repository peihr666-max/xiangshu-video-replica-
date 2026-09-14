import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { CustomersManagementPage } from "./CustomersManagementPage";

vi.mock("./CustomersPage", () => ({ CustomersPage: () => <p>客户列表</p> }));
test("customer management exposes only the customer list", () => {
  render(<CustomersManagementPage />);
  expect(screen.getByText("客户列表")).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "激活码" })).not.toBeInTheDocument();
  expect(
    screen.queryByRole("tab", { name: "在线会话" }),
  ).not.toBeInTheDocument();
});
