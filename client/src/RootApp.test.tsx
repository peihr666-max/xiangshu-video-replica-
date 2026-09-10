import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CUSTOMER_SESSION_REPLACED_EVENT } from "./api";
import { RootApp } from "./RootApp";

function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(),
    json: async () => payload,
  });
}

// The fake token fixtures live in named constants so the repo's secret
// scan (which flags `token:` followed by a quoted literal) stays quiet —
// same posture as customerApi.test.ts.
const deviceTokenText = "device-token-1";
const sessionTokenText = "session-token-1";

const customerActivationBody = {
  username: "user-1",
  user_id: "user-1",
  device_id: "device-1",
  device_token: deviceTokenText,
  session_token: sessionTokenText,
  session_epoch: 1,
  session_lease_expires_at: "2026-08-24T12:01:00Z",
  request_id: "req-1",
};

/** Fetch stub for the customer lane: the activation succeeds and the
 * workspace shell's internal-lane probes (health, projects) resolve benignly
 * so the workspace can mount — the customer business APIs arrive in later
 * tasks (T34+), not T29. The device list resolves to an empty two-slot
 * contract so the T31 device view can mount. */
function stubCustomerWorkspaceFetch() {
  return vi.fn((url: string) => {
    if (url.endsWith("/api/customer/activate")) {
      return jsonResponse(customerActivationBody, 201);
    }
    if (url.endsWith("/api/customer/devices")) {
      return jsonResponse({
        slots: [
          { slot_no: 1, device: null },
          { slot_no: 2, device: null },
        ],
        history: [],
        pending_pairings: [],
      });
    }
    if (url.endsWith("/health")) {
      return jsonResponse({ status: "ok", service: "video-replica-api" });
    }
    return jsonResponse([]);
  });
}

describe("RootApp", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
    window.history.replaceState(null, "", "/");
  });

  it.each(["/admin", "/admin/"])(
    "routes %s to the internal management page",
    (path) => {
      vi.stubGlobal(
        "fetch",
        vi.fn(() => jsonResponse({ items: [] })),
      );

      render(<RootApp path={path} />);

      expect(
        screen.getByRole("heading", { name: "运营管理后台" }),
      ).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "众墅之家" })).toBeNull();
    },
  );

  // CW-013 收敛正式客户入口 + 内部兜底删除：普通浏览器根路径不再进入内部 App，
  // 而是落到唯一的客户状态机；内部访问令牌壳在根入口结构上不可达。
  it("converges the browser root path to the customer state machine (internal fallback deleted)", async () => {
    const fetchMock = stubCustomerWorkspaceFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<RootApp path="/" />);

    expect(
      await screen.findByRole("heading", { name: "激活众墅之家 · AI 即创" }),
    ).toBeInTheDocument();
    // 内部兜底删除：根路径既不出现内部访问令牌输入，也不是管理后台。
    expect(screen.queryByLabelText("内部访问令牌（云端模式）")).toBeNull();
    expect(screen.queryByRole("heading", { name: "运营管理后台" })).toBeNull();
    // 身份隔离：客户入口从不发起内部身份探针 /api/auth/me。
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).endsWith("/api/auth/me"),
      ),
    ).toBe(false);
  });

  // 未认证的客户入口不得读写私有业务数据（V3 行 257/258）。
  it("issues no internal identity or private business call before authentication", async () => {
    const fetchMock = stubCustomerWorkspaceFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<RootApp path="/" />);
    await screen.findByRole("heading", { name: "激活众墅之家 · AI 即创" });

    const called = fetchMock.mock.calls.map(([url]) => String(url));
    expect(called.some((url) => url.endsWith("/api/auth/me"))).toBe(false);
    // 激活前不触达任何私有业务接口：唯一允许的 pre-auth 端点是激活/配对/登录，
    // 而激活屏挂载时它们都尚未被调用（浏览器无凭据 → 零 fetch）。收窄白名单，
    // 使 /api/customer/wallet|profile|devices 这类登录后私有接口在激活前被调用即失败。
    const preAuthAllowed = [
      "/api/customer/activate",
      "/api/customer/devices/enroll",
      "/api/customer/sessions/login",
    ];
    expect(
      called.some(
        (url) =>
          url.includes("/api/") &&
          !preAuthAllowed.some((endpoint) => url.endsWith(endpoint)),
      ),
    ).toBe(false);
  });

  // 历史内部 hash 深链接（如收藏夹里的 /#characters）不得借此重新进入内部 App。
  it("does not let a historical internal hash at the root re-enter the internal App", async () => {
    window.history.replaceState(null, "", "/#characters");
    const fetchMock = stubCustomerWorkspaceFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<RootApp />);

    expect(
      await screen.findByRole("heading", { name: "激活众墅之家 · AI 即创" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("内部访问令牌（云端模式）")).toBeNull();
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).endsWith("/api/auth/me"),
      ),
    ).toBe(false);
  });

  // 刷新/深链接：全新挂载时 RootApp 从真实 window.location 读取路径，客户路径留在客户域。
  it.each(["/", "/customer", "/customer/pairing"])(
    "re-reads window.location on a fresh mount so refresh/deep-link to %s stays in the customer lane",
    async (path) => {
      window.history.replaceState(null, "", path);
      const fetchMock = stubCustomerWorkspaceFetch();
      vi.stubGlobal("fetch", fetchMock);

      render(<RootApp />);

      const heading =
        path === "/customer/pairing"
          ? "添加已有账号设备"
          : "激活众墅之家 · AI 即创";
      expect(
        await screen.findByRole("heading", { name: heading }),
      ).toBeInTheDocument();
      expect(screen.queryByLabelText("内部访问令牌（云端模式）")).toBeNull();
      // 与其他身份隔离用例同等强度：深链接/刷新挂载也不得触发内部身份探针。
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).endsWith("/api/auth/me"),
        ),
      ).toBe(false);
    },
  );

  // 后退到根路径是一次全新挂载：仍落客户状态机，不回落到内部 App。
  // （RootApp 不订阅 popstate；跨路径后退在真实浏览器里是硬导航/整页重载，
  //  故用 unmount + remount 精确模拟，而非依赖软路由事件。）
  it("re-enters the customer lane (not the internal App) when navigating back to the root", async () => {
    vi.stubGlobal("fetch", stubCustomerWorkspaceFetch());
    window.history.replaceState(null, "", "/customer");
    const first = render(<RootApp />);
    await screen.findByRole("heading", { name: "激活众墅之家 · AI 即创" });
    first.unmount();

    window.history.replaceState(null, "", "/");
    render(<RootApp />);

    expect(
      await screen.findByRole("heading", { name: "激活众墅之家 · AI 即创" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("内部访问令牌（云端模式）")).toBeNull();
  });

  // 错误/未匹配路由不绕过身份验证：一律收敛到客户状态机（既非内部 App，也非管理后台）。
  it.each(["/some/unknown/route", "/internal", "/login"])(
    "routes the unmatched path %s to the customer state machine without bypassing authentication",
    async (path) => {
      const fetchMock = stubCustomerWorkspaceFetch();
      vi.stubGlobal("fetch", fetchMock);

      render(<RootApp path={path} />);

      expect(
        await screen.findByRole("heading", { name: "激活众墅之家 · AI 即创" }),
      ).toBeInTheDocument();
      expect(screen.queryByLabelText("内部访问令牌（云端模式）")).toBeNull();
      expect(
        screen.queryByRole("heading", { name: "运营管理后台" }),
      ).toBeNull();
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).endsWith("/api/auth/me"),
        ),
      ).toBe(false);
    },
  );

  it("routes the Tauri desktop root path to the customer activation flow", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      configurable: true,
      value: {
        invoke: vi.fn(async (command: string) => {
          if (command === "customer_load_credentials") {
            return null;
          }
          throw new Error(`unexpected Tauri command: ${command}`);
        }),
      },
    });
    vi.stubGlobal("fetch", stubCustomerWorkspaceFetch());

    render(<RootApp path="/" />);

    expect(
      await screen.findByRole("heading", { name: "激活众墅之家 · AI 即创" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("内部访问令牌（云端模式）")).toBeNull();
  });

  // CW-013: Tauri 桌面无 admin 通道——/admin* 在 Tauri 运行时也收敛到客户状态机。
  // 固化“!isTauriRuntime() 守卫 admin”这条产品红线，防止守卫被误挪或误删后
  // 桌面客户构建意外拉起管理后台。
  it.each(["/admin", "/admin/funds"])(
    "keeps the Tauri desktop on the customer lane even for the admin path %s (no admin lane in the desktop build)",
    async (path) => {
      Object.defineProperty(window, "__TAURI_INTERNALS__", {
        configurable: true,
        value: {
          invoke: vi.fn(async (command: string) => {
            if (command === "customer_load_credentials") {
              return null;
            }
            throw new Error(`unexpected Tauri command: ${command}`);
          }),
        },
      });
      vi.stubGlobal("fetch", stubCustomerWorkspaceFetch());

      render(<RootApp path={path} />);

      expect(
        await screen.findByRole("heading", { name: "激活众墅之家 · AI 即创" }),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("heading", { name: "运营管理后台" }),
      ).toBeNull();
      expect(screen.queryByLabelText("内部访问令牌（云端模式）")).toBeNull();
    },
  );

  it("routes the pairing URL to the explicit existing-account device flow", async () => {
    const fetchMock = stubCustomerWorkspaceFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<RootApp path="/customer/pairing" />);

    expect(
      await screen.findByRole("heading", { name: "添加已有账号设备" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("激活码")).toBeInTheDocument();
    expect(screen.queryByLabelText(/fingerprint|机器码/i)).toBeNull();
    expect(
      screen.getByRole("button", { name: "返回首次激活" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回首次激活" }));
    expect(
      await screen.findByRole("heading", { name: "激活众墅之家 · AI 即创" }),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([url]) => url.endsWith("/sessions/login")),
    ).toBe(false);
  });

  it.each([false, true])(
    "boots the saved paired credential into login (other device online: %s)",
    async (otherDeviceOnline) => {
      const workspaceFetch = stubCustomerWorkspaceFetch();
      const loginBody = {
        user_id: "user-1",
        device_id: "device-2",
        session_id: "session-2",
        session_token: sessionTokenText,
        session_epoch: 2,
        session_lease_expires_at: "2026-08-24T12:02:00Z",
        request_id: "req-paired-login",
      };
      const fetchMock = vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith("/api/customer/devices/enroll")) {
          return jsonResponse({ device_token: deviceTokenText }, 201);
        }
        if (url.endsWith("/api/customer/sessions/login")) {
          expect(new Headers(init?.headers).get("Authorization")).toBe(
            `Bearer ${deviceTokenText}`,
          );
          return otherDeviceOnline
            ? jsonResponse(
                {
                  detail: {
                    code: "OTHER_DEVICE_ONLINE",
                    message: "另一台设备在线",
                    online_device_name_masked: "主设备",
                    online_slot_no: 1,
                    lease_expires_at: "2026-08-24T12:05:00Z",
                  },
                },
                409,
              )
            : jsonResponse(loginBody, 201);
        }
        if (url.endsWith("/api/customer/sessions/switch")) {
          return jsonResponse(loginBody, 201);
        }
        return workspaceFetch(url);
      });
      vi.stubGlobal("fetch", fetchMock);

      render(<RootApp path="/customer/pairing" />);
      await screen.findByRole("heading", { name: "添加已有账号设备" });
      fireEvent.change(screen.getByLabelText("激活码"), {
        target: { value: "XS04-AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD" },
      });
      fireEvent.change(screen.getByLabelText("设备名称"), {
        target: { value: "第二台电脑" },
      });
      fireEvent.click(screen.getByRole("button", { name: "提交配对申请" }));
      await screen.findByRole("heading", { name: "配对成功" });
      expect(
        fetchMock.mock.calls.some(([url]) => url.endsWith("/sessions/login")),
      ).toBe(false);
      fireEvent.click(screen.getByRole("button", { name: "进入客户工作区" }));

      if (otherDeviceOnline) {
        await screen.findByRole("dialog", { name: "检测到会话冲突" });
        expect(
          fetchMock.mock.calls.some(([url]) =>
            url.endsWith("/sessions/switch"),
          ),
        ).toBe(false);
        fireEvent.click(screen.getByRole("button", { name: "切换到本设备" }));
      }
      expect(
        await screen.findByRole("heading", {
          name: "粘贴一条爆款乡墅视频链接，快速生成它的原创视频",
        }),
      ).toBeInTheDocument();
      expect(screen.queryByLabelText("激活码")).toBeNull();
      expect(
        fetchMock.mock.calls.filter(([url]) => url.endsWith("/sessions/login")),
      ).toHaveLength(1);
      expect(
        fetchMock.mock.calls.filter(([url]) =>
          url.endsWith("/sessions/switch"),
        ),
      ).toHaveLength(otherDeviceOnline ? 1 : 0);
    },
  );

  it("routes /customer to the activation screen without any internal-token field", async () => {
    vi.stubGlobal("fetch", stubCustomerWorkspaceFetch());

    render(<RootApp path="/customer" />);

    expect(
      await screen.findByRole("heading", { name: "激活众墅之家 · AI 即创" }),
    ).toBeInTheDocument();
    // FE-02 No-Go: the internal access-token input must never be the
    // customer's entry — the customer lane has its own activation flow.
    expect(screen.queryByLabelText("内部访问令牌（云端模式）")).toBeNull();
  });

  it("activates on /customer and lands in the workspace under the customer identity", async () => {
    vi.stubGlobal("fetch", stubCustomerWorkspaceFetch());

    render(<RootApp path="/customer" />);

    await screen.findByRole("heading", { name: "激活众墅之家 · AI 即创" });
    fireEvent.change(screen.getByLabelText("激活码"), {
      target: { value: "XS04-AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD" },
    });
    fireEvent.change(screen.getByLabelText("设备名称"), {
      target: { value: "工作电脑" },
    });
    fireEvent.click(screen.getByRole("button", { name: "激活并进入工作台" }));

    expect(
      await screen.findByRole("heading", {
        name: "粘贴一条爆款乡墅视频链接，快速生成它的原创视频",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "主要导航" }),
    ).toBeInTheDocument();
    // The compact account entry keeps identity details in the profile page.
    // The workspace stub does not serve /api/customer/wallet pricing, so the
    // wallet summary settles to the error label instead of a credit count.
    expect(
      await screen.findByRole("button", { name: "用户档案，积分 读取失败" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("内部访问令牌（云端模式）")).toBeNull();
  });

  it("logs out from the customer profile and keeps the device login available", async () => {
    const workspaceFetch = stubCustomerWorkspaceFetch();
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/customer/profile")) {
        return jsonResponse({
          user_id: "user-1",
          username: "user-1",
          display_name: "客户一号",
          joined_at: "2026-08-01T00:00:00Z",
          activation_code_masked: "XS04-ABCD••••WXYZ",
          activation_status: "ACTIVE",
          activated_at: "2026-08-02T00:00:00Z",
          device_slots_used: 1,
          device_slots_total: 2,
        });
      }
      if (url.endsWith("/api/customer/sessions/logout")) {
        expect(init?.method).toBe("POST");
        return jsonResponse(undefined, 204);
      }
      return workspaceFetch(url);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<RootApp path="/customer" />);
    await screen.findByRole("heading", { name: "激活众墅之家 · AI 即创" });
    fireEvent.change(screen.getByLabelText("激活码"), {
      target: { value: "XS04-AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD" },
    });
    fireEvent.change(screen.getByLabelText("设备名称"), {
      target: { value: "工作电脑" },
    });
    fireEvent.click(screen.getByRole("button", { name: "激活并进入工作台" }));
    fireEvent.click(await screen.findByRole("button", { name: /^用户档案$/ }));
    await screen.findByRole("heading", { name: "用户档案" });
    fireEvent.click(screen.getByRole("tab", { name: "设备管理" }));
    fireEvent.click(await screen.findByRole("button", { name: "退出登录" }));

    expect(
      await screen.findByRole("heading", { name: "欢迎回来" }),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(([url]) =>
        String(url).endsWith("/api/customer/sessions/logout"),
      ),
    ).toHaveLength(1);
  });

  it("ignores a delayed profile 401 from the session that already logged out", async () => {
    let resolveOldProfile:
      | ((value: Awaited<ReturnType<typeof jsonResponse>>) => void)
      | undefined;
    const oldProfile = new Promise<Awaited<ReturnType<typeof jsonResponse>>>(
      (resolve) => {
        resolveOldProfile = resolve;
      },
    );
    let profileCalls = 0;
    const workspaceFetch = stubCustomerWorkspaceFetch();
    const reloginBody = {
      user_id: "user-1",
      device_id: "device-1",
      session_id: "session-2",
      session_token: sessionTokenText,
      session_epoch: 2,
      session_lease_expires_at: "2026-09-07T13:00:00Z",
      request_id: "req-relogin",
    };
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/api/customer/profile")) {
        profileCalls += 1;
        return profileCalls === 1
          ? oldProfile
          : jsonResponse({
              user_id: "user-1",
              username: "user-1",
              display_name: "新会话客户",
              joined_at: "2026-08-01T00:00:00Z",
              activation_code_masked: "XS04-ABCD••••WXYZ",
              activation_status: "ACTIVE",
              activated_at: "2026-08-02T00:00:00Z",
              device_slots_used: 1,
              device_slots_total: 2,
            });
      }
      if (url.endsWith("/api/customer/sessions/logout")) {
        return jsonResponse(undefined, 204);
      }
      if (url.endsWith("/api/customer/sessions/login")) {
        return jsonResponse(reloginBody, 201);
      }
      return workspaceFetch(url);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<RootApp path="/customer" />);
    await screen.findByRole("heading", { name: "激活众墅之家 · AI 即创" });
    fireEvent.change(screen.getByLabelText("激活码"), {
      target: { value: "XS04-AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD" },
    });
    fireEvent.change(screen.getByLabelText("设备名称"), {
      target: { value: "工作电脑" },
    });
    fireEvent.click(screen.getByRole("button", { name: "激活并进入工作台" }));
    fireEvent.click(await screen.findByRole("button", { name: /^用户档案$/ }));
    await screen.findByRole("heading", { name: "用户档案" });
    fireEvent.click(screen.getByRole("tab", { name: "设备管理" }));
    fireEvent.click(await screen.findByRole("button", { name: "退出登录" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "使用本机设备登录" }),
    );
    await waitFor(() => {
      expect(profileCalls).toBe(2);
      expect(
        screen.getByRole("navigation", { name: "主要导航" }),
      ).toBeInTheDocument();
    });

    await act(async () => {
      resolveOldProfile?.(
        await jsonResponse(
          {
            detail: {
              code: "SESSION_EXPIRED",
              message: "旧会话已过期",
            },
          },
          401,
        ),
      );
    });

    await waitFor(() => {
      expect(
        screen.getByRole("navigation", { name: "主要导航" }),
      ).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "登录已过期" })).toBeNull();
    });
  });

  it("shows the displaced-session terminal screen when replaced mid-session (§4.2)", async () => {
    vi.stubGlobal("fetch", stubCustomerWorkspaceFetch());

    render(<RootApp path="/customer" />);
    await screen.findByRole("heading", { name: "激活众墅之家 · AI 即创" });
    fireEvent.change(screen.getByLabelText("激活码"), {
      target: { value: "XS04-AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD" },
    });
    fireEvent.change(screen.getByLabelText("设备名称"), {
      target: { value: "工作电脑" },
    });
    fireEvent.click(screen.getByRole("button", { name: "激活并进入工作台" }));
    await screen.findByRole("heading", {
      name: "粘贴一条爆款乡墅视频链接，快速生成它的原创视频",
    });

    window.dispatchEvent(new Event(CUSTOMER_SESSION_REPLACED_EVENT));

    expect(
      await screen.findByRole("heading", { name: "本设备已下线" }),
    ).toBeInTheDocument();
    // §4.2 red line: a displaced session must be reported as exactly that —
    // never as a balance, network, or generic service failure.
    expect(screen.getByText(/已在另一台设备上登录/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "重新登录" }),
    ).toBeInTheDocument();
  });
});
