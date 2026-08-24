import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { CustomersPage } from "./CustomersPage";
import * as adminApi from "../api.admin";

// Mock the admin API module
vi.mock("../api.admin", () => ({
  listCustomers: vi.fn(),
  AdminCustomerError: class extends Error {
    constructor(message: string) {
      super(message);
      this.name = "AdminCustomerError";
    }
  },
}));

describe("CustomersPage (ADM-02 / T33)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders customer list with pagination", async () => {
    const mockCustomers = [
      {
        user_id: "user-1",
        email: "customer1@example.com",
        created_at: "2026-08-24T10:00:00Z",
        activation_code: "ABC-123",
        status: "active",
      },
      {
        user_id: "user-2",
        email: "customer2@example.com",
        created_at: "2026-08-24T11:00:00Z",
        activation_code: "DEF-456",
        status: "active",
      },
    ];

    vi.mocked(adminApi.listCustomers).mockResolvedValue({
      customers: mockCustomers,
      total: 2,
      page: 1,
      page_size: 20,
    });

    render(<CustomersPage />);

    await waitFor(() => {
      expect(screen.getByText("customer1@example.com")).toBeInTheDocument();
      expect(screen.getByText("customer2@example.com")).toBeInTheDocument();
    });

    expect(screen.getByText(/共 2 位客户/)).toBeInTheDocument();
  });

  it("shows loading state while fetching customers", () => {
    vi.mocked(adminApi.listCustomers).mockImplementation(
      () => new Promise(() => {}), // Never resolves
    );

    render(<CustomersPage />);

    expect(screen.getByText("加载中...")).toBeInTheDocument();
  });

  it("handles API error gracefully", async () => {
    vi.mocked(adminApi.listCustomers).mockRejectedValue(
      new adminApi.AdminCustomerError("网络错误"),
    );

    render(<CustomersPage />);

    await waitFor(() => {
      expect(screen.getByText("加载失败：网络错误")).toBeInTheDocument();
    });
  });

  it("supports pagination navigation", async () => {
    const mockCustomers = Array.from({ length: 20 }, (_, i) => ({
      user_id: `user-${i}`,
      email: `user${i}@example.com`,
      created_at: "2026-08-24T10:00:00Z",
      activation_code: `CODE-${i}`,
      status: "active",
    }));

    vi.mocked(adminApi.listCustomers).mockResolvedValue({
      customers: mockCustomers,
      total: 50,
      page: 1,
      page_size: 20,
    });

    render(<CustomersPage />);

    await waitFor(() => {
      expect(screen.getByText(/第 1 页/)).toBeInTheDocument();
    });

    const nextPageButton = screen.getByRole("button", { name: "下一页" });
    fireEvent.click(nextPageButton);

    expect(adminApi.listCustomers).toHaveBeenCalledWith({ page: 2, page_size: 20 });
  });

  it("supports filtering by email", async () => {
    vi.mocked(adminApi.listCustomers).mockResolvedValue({
      customers: [],
      total: 0,
      page: 1,
      page_size: 20,
    });

    render(<CustomersPage />);

    const filterInput = screen.getByPlaceholderText("按邮箱筛选");
    fireEvent.change(filterInput, { target: { value: "test@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "筛选" }));

    expect(adminApi.listCustomers).toHaveBeenCalledWith({
      page: 1,
      page_size: 20,
      email_filter: "test@example.com",
    });
  });

  it("disables write controls for auditor role", async () => {
    vi.mocked(adminApi.listCustomers).mockResolvedValue({
      customers: [],
      total: 0,
      page: 1,
      page_size: 20,
    });

    render(<CustomersPage readOnly={true} />);

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "新建调账" })).not.toBeInTheDocument();
    });
  });

  it("shows empty state when no customers exist", async () => {
    vi.mocked(adminApi.listCustomers).mockResolvedValue({
      customers: [],
      total: 0,
      page: 1,
      page_size: 20,
    });

    render(<CustomersPage />);

    await waitFor(() => {
      expect(screen.getByText("暂无客户数据")).toBeInTheDocument();
    });
  });

  it("displays customer status badges correctly", async () => {
    const mockCustomers = [
      {
        user_id: "user-1",
        email: "active@example.com",
        created_at: "2026-08-24T10:00:00Z",
        activation_code: "ABC-123",
        status: "active",
      },
      {
        user_id: "user-2",
        email: "suspended@example.com",
        created_at: "2026-08-24T11:00:00Z",
        activation_code: "DEF-456",
        status: "suspended",
      },
    ];

    vi.mocked(adminApi.listCustomers).mockResolvedValue({
      customers: mockCustomers,
      total: 2,
      page: 1,
      page_size: 20,
    });

    render(<CustomersPage />);

    await waitFor(() => {
      expect(screen.getByText("活跃")).toBeInTheDocument();
      expect(screen.getByText("已暂停")).toBeInTheDocument();
    });
  });
});
