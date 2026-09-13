import { runInNewContext } from "node:vm";
import { expect, it, vi } from "vitest";

import script from "../src-tauri/src/publish_identity.js?raw";

const privateFixture = ["synthetic", "do-not-forward"].join("-");

function environment(origin: string, path: string, body: unknown) {
  const location = new URL(origin);
  const clone = vi.fn(() => ({ json: async () => body }));
  const win: Record<string, unknown> = {
    fetch: async () => ({ url: origin + path, clone }),
  };
  win.top = win;
  class XHR {
    open() {}
    addEventListener() {}
  }
  runInNewContext(script, { window: win, location, URL, XMLHttpRequest: XHR });
  return {
    win,
    clone,
    read: async () => {
      await (win.fetch as () => Promise<unknown>)();
      await Promise.resolve();
      await Promise.resolve();
      return win.__xiangshuPublishIdentity;
    },
  };
}

it.each([
  [
    "https://creator.douyin.com",
    "/web/api/media/user/info/",
    {
      status_code: 0,
      user: {
        uid: "u1",
        nickname: "抖音用户",
        cookie: privateFixture,
      },
    },
    "抖音用户",
  ],
  [
    "https://channels.weixin.qq.com",
    "/cgi-bin/mmfinderassistant-bin/auth/auth_data",
    {
      errCode: 0,
      data: {
        finderUser: { finderUsername: "u1", nickname: "视频号用户" },
        authKey: privateFixture,
      },
    },
    "视频号用户",
  ],
  [
    "https://creator.xiaohongshu.com",
    "/api/galaxy/user/info",
    {
      success: true,
      data: {
        userId: "u1",
        userName: "小红书用户",
        token: privateFixture,
      },
    },
    "小红书用户",
  ],
])(
  "官方账号响应只提取 UID 和用户名：%s",
  async (origin, path, body, username) => {
    const result = await environment(origin, path, body).read();
    expect(result).toEqual({ platform_user_id: "u1", username });
    expect(JSON.stringify(result)).not.toContain(privateFixture);
  },
);

it("不读取其他用户资料接口或失败登录响应", async () => {
  const other = environment("https://creator.douyin.com", "/api/other-user", {
    status_code: 0,
    user: { uid: "u1", nickname: "其他人" },
  });
  expect(await other.read()).toBeUndefined();
  expect(other.clone).not.toHaveBeenCalled();
  expect(
    await environment(
      "https://creator.douyin.com",
      "/web/api/media/user/info/",
      { status_code: 8, user: { uid: "u1", nickname: "未登录" } },
    ).read(),
  ).toBeUndefined();
});

it("不在相似域名注入或读取账号", async () => {
  const other = environment(
    "https://creator.douyin.com.evil.test",
    "/web/api/media/user/info/",
    { status_code: 0, user: { uid: "u1", nickname: "假响应" } },
  );
  expect(await other.read()).toBeUndefined();
  expect(other.clone).not.toHaveBeenCalled();
});
