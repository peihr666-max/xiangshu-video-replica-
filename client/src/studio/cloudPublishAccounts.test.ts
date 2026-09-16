import { waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  cancelLocalPublishLogin,
  checkLocalPublishLogin,
  listLocalPublishAccounts,
  startLocalPublishLogin,
} from "./localPublishAccounts";

const request = vi.hoisted(() => vi.fn());
vi.mock("../api", () => ({ publishBrowserRequest: request }));
vi.mock("@tauri-apps/api/core", () => ({
  isTauri: () => false,
  invoke: vi.fn(),
}));
afterEach(() => request.mockReset());

it("网页使用云端账号接口，不要求 Tauri", async () => {
  request.mockResolvedValue(new Response(JSON.stringify([{ id: "cloud-1" }])));
  expect(await listLocalPublishAccounts("owner")).toEqual([{ id: "cloud-1" }]);
  expect(request.mock.calls[0][0]).toBe("/api/studio/publish/browser/accounts");
});

it("网页按分块流接收二维码和账号，处理半个 JSON 数据包", async () => {
  const stream = new TransformStream<Uint8Array, Uint8Array>();
  const source = stream.writable.getWriter();
  request.mockResolvedValue(new Response(stream.readable));
  const id = await startLocalPublishLogin("owner", "wechat_channels");
  const encode = new TextEncoder();
  await source.write(
    encode.encode('{"phase":"qr_ready","image":"data:image/png;'),
  );
  await source.write(
    encode.encode('base64,cXI=","account":null,"login_id":"server-1"}\n'),
  );
  await waitFor(async () =>
    expect(await checkLocalPublishLogin("owner", id)).toMatchObject({
      phase: "qr_ready",
    }),
  );
  await source.write(
    encode.encode(
      `${JSON.stringify({
        phase: "connected",
        image: null,
        account: { id: "account-1" },
      })}\n`,
    ),
  );
  await source.close();
  await waitFor(async () =>
    expect(await checkLocalPublishLogin("owner", id)).toMatchObject({
      phase: "connected",
      account: { id: "account-1" },
    }),
  );
  await cancelLocalPublishLogin("owner", id);
});

it("扫码取消先通知服务器，再中止流，且不能访问其他用户会话", async () => {
  const stream = new TransformStream<Uint8Array, Uint8Array>();
  const source = stream.writable.getWriter();
  const aborted = vi.fn();
  request.mockImplementation(async (_path, init) => {
    if (init.method === "DELETE") return new Response("{}");
    init.signal.addEventListener("abort", () => {
      aborted();
      void source.abort(new DOMException("abort", "AbortError"));
    });
    return new Response(stream.readable);
  });
  const id = await startLocalPublishLogin("owner", "douyin");
  await source.write(
    new TextEncoder().encode(
      '{"phase":"loading","image":null,"account":null,"login_id":"server-2"}\n',
    ),
  );
  await waitFor(async () =>
    expect(await checkLocalPublishLogin("owner", id)).toMatchObject({
      phase: "loading",
    }),
  );
  expect(() => checkLocalPublishLogin("other", id)).toThrow("扫码会话不存在");
  await cancelLocalPublishLogin("owner", id);
  expect(aborted).toHaveBeenCalledOnce();
  expect(request).toHaveBeenCalledWith(
    "/api/studio/publish/browser/logins/server-2",
    expect.objectContaining({ method: "DELETE" }),
  );
});

it("扫码服务错误回到可重新获取状态", async () => {
  request.mockRejectedValue(new Error("扫码服务繁忙，请稍后重试。"));
  const id = await startLocalPublishLogin("owner", "xiaohongshu");
  await waitFor(async () =>
    expect(await checkLocalPublishLogin("owner", id)).toMatchObject({
      phase: "closed",
      message: "扫码服务繁忙，请稍后重试。",
    }),
  );
  await cancelLocalPublishLogin("owner", id);
});
