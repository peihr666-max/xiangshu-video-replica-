import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setAdminCsrfToken } from "../api";
import { H3ExtendedModesSection } from "./H3ExtendedModesSection";

function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  });
}

function installFetch(options?: { enabled?: boolean; patchFails?: boolean }) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith("/api/control/settings/h3-extended-modes")) {
      if (init?.method === "PATCH") {
        if (options?.patchFails) {
          return jsonResponse(
            {
              detail: {
                code: "RUNTIME_SETTINGS_SERVICE_UNAVAILABLE",
                message:
                  "Runtime settings writes require the PostgreSQL runtime.",
              },
            },
            503,
          );
        }
        return jsonResponse({ h3_extended_modes_enabled: true });
      }
      return jsonResponse({
        h3_extended_modes_enabled: options?.enabled ?? false,
      });
    }
    throw new Error(`unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("H3ExtendedModesSection", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setAdminCsrfToken("");
  });

  it("loads and displays the current H3 extended-modes gate", async () => {
    installFetch({ enabled: true });
    render(<H3ExtendedModesSection />);

    expect(await screen.findByText("已开启")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "关闭扩展模式" }),
    ).toBeInTheDocument();
  });

  it("switches the gate through the idempotent write contract", async () => {
    setAdminCsrfToken("csrf-token-1");
    const fetchMock = installFetch({ enabled: false });
    render(<H3ExtendedModesSection />);

    fireEvent.click(
      await screen.findByRole("button", { name: "开启扩展模式" }),
    );

    // CW-063：真实付费模式纳入统一管理端写契约——原因必填 + 幂等重放。
    await screen.findByRole("dialog", { name: "开启扩展模式" });
    fireEvent.click(screen.getByRole("button", { name: "确认开启" }));
    expect(await screen.findByText("请填写操作原因")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("操作原因"), {
      target: { value: "供应商付费探针核对通过" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认开启" }));

    expect(await screen.findByText("H3 扩展模式已开启。")).toBeInTheDocument();
    const patchCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === "PATCH",
    );
    expect(patchCall).toBeDefined();
    const [, init] = patchCall ?? [];
    const headers = ((init as RequestInit).headers ?? {}) as Record<
      string,
      string
    >;
    expect(headers["X-Admin-CSRF"]).toBe("csrf-token-1");
    expect(headers["Idempotency-Key"]).toMatch(/^idem-|^[0-9a-f-]{36}$/);
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      h3_extended_modes_enabled: true,
      confirm: true,
      reason: "供应商付费探针核对通过",
    });
  });

  it("stays read-only for auditors", async () => {
    installFetch();
    render(<H3ExtendedModesSection readOnly />);

    await screen.findByText("已关闭");
    expect(screen.queryByRole("button", { name: /扩展模式/ })).toBeNull();
    expect(screen.getByText(/审计员只读/)).toBeInTheDocument();
  });
});
