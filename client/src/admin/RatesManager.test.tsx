import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAdminCsrfToken } from "../api";
import { RatesManager } from "./RatesManager";

const ratesPayload = {
  rates: [
    {
      subject: "video_generation_768p",
      kind: "upstream_cost",
      unit: "second",
      resolution: "768P",
      unit_price_fen: 9,
      updated_at: "2026-09-05T10:00:00+00:00",
      updated_by_username: "admin",
    },
    {
      subject: "external_price_768p",
      kind: "external_price",
      unit: "second",
      resolution: "768P",
      unit_price_fen: 12,
      updated_at: "2026-09-05T10:00:00+00:00",
      updated_by_username: "admin",
    },
  ],
  history: [],
};

function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  });
}

function installFetch() {
  const fetchMock = vi.fn((url: string, options?: RequestInit) => {
    if (url.endsWith("/api/control/settings/rates") && !options?.method) {
      return jsonResponse(ratesPayload);
    }
    if (
      url.endsWith("/api/control/settings/rates") &&
      options?.method === "PUT"
    ) {
      return jsonResponse(ratesPayload);
    }
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  setAdminCsrfToken("csrf-test");
  vi.stubGlobal("URL", {
    createObjectURL: vi.fn(() => "blob:test"),
    revokeObjectURL: vi.fn(),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function upstreamAdjustButton() {
  const row = screen.getByText("视频生成 · 768P").closest("tr");
  if (!row) throw new Error("rate row not found");
  return within(row as HTMLElement).getByRole("button", { name: "调整" });
}

describe("RatesManager", () => {
  it("renders grouped rate tables with yuan-formatted prices", async () => {
    installFetch();
    render(<RatesManager />);

    expect(await screen.findByText("视频生成 · 768P")).toBeInTheDocument();
    expect(screen.getByText("0.09")).toBeInTheDocument();
    expect(screen.getByText("对外售价 · 768P")).toBeInTheDocument();
    expect(screen.getAllByText("0.12").length).toBeGreaterThan(0);
  });

  it("saves an adjustment with the write contract (reason + idempotency key)", async () => {
    const fetchMock = installFetch();
    render(<RatesManager />);

    await screen.findByText("视频生成 · 768P");
    fireEvent.click(upstreamAdjustButton());
    fireEvent.change(screen.getByLabelText(/新单价/), {
      target: { value: "0.10" },
    });
    fireEvent.change(screen.getByLabelText(/操作原因/), {
      target: { value: "上游小幅上调" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, options]) =>
            String(url).endsWith("/api/control/settings/rates") &&
            options?.method === "PUT",
        ),
      ).toBe(true);
    });
    const putCall = fetchMock.mock.calls.find(
      ([url, options]) =>
        String(url).endsWith("/api/control/settings/rates") &&
        options?.method === "PUT",
    );
    const body = JSON.parse(String(putCall?.[1]?.body));
    expect(body.updates).toEqual([
      { subject: "video_generation_768p", unit_price_fen: 10 },
    ]);
    expect(body.reason).toBe("上游小幅上调");
    expect(body.confirm).toBe(true);
  });

  it("blocks a >50% change until the operator acknowledges it", async () => {
    const fetchMock = installFetch();
    render(<RatesManager />);

    await screen.findByText("视频生成 · 768P");
    fireEvent.click(upstreamAdjustButton());
    // 0.09 → 0.20：超过 50% 涨幅。
    fireEvent.change(screen.getByLabelText(/新单价/), {
      target: { value: "0.20" },
    });
    fireEvent.change(screen.getByLabelText(/操作原因/), {
      target: { value: "上游大幅调价" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(
      await screen.findByText("本次变动超过 50%，请先勾选确认知晓影响"),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(
        ([url, options]) =>
          String(url).endsWith("/api/control/settings/rates") &&
          options?.method === "PUT",
      ),
    ).toBe(false);

    fireEvent.click(screen.getByLabelText(/确认知晓大幅调价/));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, options]) =>
            String(url).endsWith("/api/control/settings/rates") &&
            options?.method === "PUT",
        ),
      ).toBe(true);
    });
  });

  it("hides the adjust action in read-only mode", async () => {
    installFetch();
    render(<RatesManager readOnly />);

    await waitFor(() => {
      expect(screen.getByText("视频生成 · 768P")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: "调整" })).toBeNull();
  });
});
