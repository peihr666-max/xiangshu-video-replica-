import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PeoplePage, PersonPage } from "./PeoplePages";

const navigate = vi.fn();
const patchDraft = vi.fn();
const notify = vi.fn();
const updateData = vi.fn();
const refresh = vi.fn();
const openPicker = vi.fn();
const submitOralClone = vi.fn();
const api = vi.hoisted(() => ({
  confirmOralVoice: vi.fn(),
  customerVisibleErrorMessage: vi.fn((error: unknown, fallback: string) =>
    error instanceof Error && error.message ? error.message : fallback,
  ),
}));
vi.mock("../api", () => api);
let currentPage = "people";
let selectedPersonId: string | undefined = "p1";
let returnTo: string | undefined;
let review = true;
let userRole: "customer" | "auditor" = "customer";
let draft: Record<string, unknown> = {};

vi.mock("./context", () => ({
  useStudio: () => ({
    state: { page: currentPage, selectedPersonId, returnTo, draft },
    data: {
      loading: false,
      errors: [],
      people: [
        {
          id: "p1",
          name: "测试人物",
          role: "乡墅设计师",
          portrait: "/people/test-person.png",
          version: 1,
          scope: "乡墅方案",
          audience: "准备建房的家庭",
          expression: "专业",
          photoIds: ["scene"],
          avatars: [
            {
              id: "avatar-1",
              name: "测试分身",
              imageId: "avatar-image",
              ready: true,
              origin: "照片制作",
              duration: "00:30",
            },
          ],
          voices: [
            {
              id: "voice-ok",
              name: "已确认音色",
              confirmed: true,
              isDefault: true,
            },
            {
              id: "voice-pending",
              name: "待确认音色",
              confirmed: false,
              isDefault: false,
              url: "/voice-pending.mp3",
            },
          ],
        },
      ],
      assets: [
        {
          id: "avatar-image",
          name: "分身封面",
          kind: "image",
          url: "/avatar.png",
          group: "口播分身",
          source: "人物库",
          saved: true,
        },
        {
          id: "sheet",
          name: "基础五视图",
          kind: "image",
          url: "/five-views.png",
          group: "人物素材",
          personId: "p1",
          composite: true,
          source: "人物库",
          saved: true,
        },
        {
          id: "scene",
          name: "庭院讲解",
          kind: "image",
          url: "/scene.png",
          group: "人物素材",
          personId: "p1",
          source: "AI生成",
          saved: true,
        },
        {
          id: "voice-source",
          name: "本人声音样本",
          kind: "audio",
          url: "/voice-source.wav",
          group: "声音素材",
          personId: "p1",
          source: "本人上传",
          saved: true,
        },
      ],
      videos: [],
      tasks: [],
      projects: [],
    },
    review,
    user: { id: "user-1", role: userRole },
    navigate,
    patchDraft,
    patchState: vi.fn(),
    updateData,
    notify,
    openPicker,
    openLive: vi.fn(),
    requestGeneration: vi.fn(),
    saveDraft: vi.fn(),
    submitOralClone,
    refresh,
  }),
}));

describe("PeoplePages", () => {
  beforeEach(() => {
    currentPage = "people";
    selectedPersonId = "p1";
    returnTo = undefined;
    review = true;
    userRole = "customer";
    draft = {};
    navigate.mockClear();
    patchDraft.mockClear();
    notify.mockClear();
    updateData.mockClear();
    refresh.mockClear();
    openPicker.mockClear();
    submitOralClone.mockReset();
    submitOralClone.mockResolvedValue(undefined);
    api.confirmOralVoice.mockReset();
  });

  it("renders the people library and its primary empty-safe actions", () => {
    render(<PeoplePage />);
    expect(screen.getByRole("heading", { name: "人物库" })).toBeInTheDocument();
    expect(screen.getByText("测试人物")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "新增人物" }),
    ).toBeInTheDocument();
    expect(screen.getByAltText("测试人物形象")).toHaveAttribute(
      "src",
      "/people/test-person.png",
    );
  });

  it("filters people by role", async () => {
    render(<PeoplePage />);
    await screen.getByRole("button", { name: "客户经理" }).click();
    expect(screen.queryByText("测试人物")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "人物库" })).toBeInTheDocument();
  });

  it("renders the IP tab without exposing authorization settings", () => {
    render(<PersonPage />);
    expect(
      screen.getByRole("heading", { name: "人物定位" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("授权与状态")).not.toBeInTheDocument();
  });

  it("keeps the five views as one composite image and lists scene photos separately", () => {
    currentPage = "person-photos";
    render(<PersonPage />);
    expect(screen.getByAltText("五视图合成图")).toBeInTheDocument();
    expect(screen.getByText("基础五视图 · 1 张合成图")).toBeInTheDocument();
  });

  it("does not present an unconfirmed voice as selectable", () => {
    currentPage = "person-voices";
    render(<PersonPage />);
    expect(screen.getByText("待试听确认，暂不可选用")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "确认使用此声音" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "用于数字人口播" }),
    ).not.toBeInTheDocument();
  });

  it("未确认但已有样本的 READY 声音可以试听且不会被选择或确认", () => {
    currentPage = "person-voices";
    render(<PersonPage />);

    expect(screen.getByLabelText("待确认音色试听")).toHaveAttribute(
      "src",
      "/voice-pending.mp3",
    );
    fireEvent.click(screen.getAllByRole("button", { name: "试听" })[1]);
    expect(patchDraft).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
    expect(api.confirmOralVoice).not.toHaveBeenCalled();
  });

  it("生产工作区确认声音后选择该声音并返回原创作页", async () => {
    currentPage = "person-voices";
    returnTo = "oral-audio";
    review = false;
    api.confirmOralVoice.mockResolvedValue({
      id: "voice-pending",
      identity_id: "p1",
      title: "待确认音色",
      status: "READY",
      demo_asset_id: "demo-1",
      confirmed: true,
    });
    render(<PersonPage />);

    fireEvent.click(screen.getByRole("button", { name: "确认使用此声音" }));

    await waitFor(() =>
      expect(api.confirmOralVoice).toHaveBeenCalledWith("voice-pending"),
    );
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(patchDraft).toHaveBeenCalledWith({
      ipId: "p1",
      voiceId: "voice-pending",
    });
    expect(navigate).toHaveBeenCalledWith("oral-audio", {
      selectedPersonId: "p1",
      returnTo: undefined,
    });
  });

  it("生产工作区使用当前照片授权并创建人物分身", async () => {
    currentPage = "person-avatars";
    review = false;
    draft = { imageId: "scene" };
    render(<PersonPage />);

    fireEvent.click(screen.getByRole("button", { name: "开始制作" }));

    await waitFor(() =>
      expect(submitOralClone).toHaveBeenCalledWith({
        kind: "avatar",
        identityId: "p1",
        title: "测试人物口播分身",
        sourceAssetId: "scene",
        sourceKind: "IMAGE",
      }),
    );
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("生产工作区使用当前音频授权并创建克隆声音", async () => {
    currentPage = "person-voices";
    review = false;
    draft = { audioId: "voice-source" };
    render(<PersonPage />);

    fireEvent.click(screen.getByRole("button", { name: "开始克隆" }));

    await waitFor(() =>
      expect(submitOralClone).toHaveBeenCalledWith({
        kind: "voice",
        identityId: "p1",
        title: "测试人物克隆声音",
        sourceAssetId: "voice-source",
      }),
    );
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it.each([
    { label: "审核示例", reviewMode: true, role: "customer" as const },
    { label: "只读账号", reviewMode: false, role: "auditor" as const },
  ])("$label 不创建人物分身请求", ({ reviewMode, role }) => {
    currentPage = "person-avatars";
    review = reviewMode;
    userRole = role;
    draft = { imageId: "scene" };
    render(<PersonPage />);

    fireEvent.click(screen.getByRole("button", { name: "开始制作" }));

    expect(submitOralClone).not.toHaveBeenCalled();
  });

  it("确认声音响应失败时刷新服务端状态并保持重复点击保护", async () => {
    currentPage = "person-voices";
    review = false;
    let rejectConfirmation: ((reason?: unknown) => void) | undefined;
    api.confirmOralVoice.mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          rejectConfirmation = reject;
        }),
    );
    render(<PersonPage />);

    const confirm = screen.getByRole("button", {
      name: "确认使用此声音",
    });
    fireEvent.click(confirm);
    fireEvent.click(confirm);

    await waitFor(() => expect(api.confirmOralVoice).toHaveBeenCalledTimes(1));
    expect(confirm).toBeDisabled();
    rejectConfirmation?.(new TypeError("network unavailable"));

    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(notify).toHaveBeenCalledWith("network unavailable");
  });

  it("试听 does not select a confirmed voice, while 使用此声音 does", () => {
    currentPage = "person-voices";
    render(<PersonPage />);
    screen.getAllByRole("button", { name: "试听" })[0].click();
    expect(patchDraft).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
    screen.getByRole("button", { name: "使用此声音" }).click();
    expect(patchDraft).toHaveBeenCalledWith({
      ipId: "p1",
      voiceId: "voice-ok",
    });
    expect(navigate).toHaveBeenCalledWith("oral", {
      selectedPersonId: "p1",
      returnTo: undefined,
    });
  });

  it("returns to the originating creation page and clears the return context", () => {
    currentPage = "person-voices";
    returnTo = "oral-audio";
    render(<PersonPage />);
    screen.getByRole("button", { name: /返回创作/ }).click();
    expect(navigate).toHaveBeenCalledWith("oral-audio", {
      returnTo: undefined,
    });
  });

  it("renders each ready avatar from its linked asset URL", () => {
    currentPage = "person-avatars";
    render(<PersonPage />);
    expect(screen.getByAltText("测试分身")).toHaveAttribute(
      "src",
      "/avatar.png",
    );
  });

  it("carries a scene photo into replacement without overwriting the original frame contract", () => {
    currentPage = "person-photos";
    render(<PersonPage />);
    screen.getByRole("button", { name: "用于人物置换" }).click();
    expect(patchDraft).toHaveBeenCalledWith({
      ipId: "p1",
      imageId: "scene",
    });
  });

  it("does not treat an existing avatar as a video creation upload", () => {
    currentPage = "person-avatars";
    render(<PersonPage />);
    screen.getByRole("button", { name: "上传人物视频制作" }).click();
    expect(notify).toHaveBeenCalledWith(
      "人物视频上传制作接口尚未接通，当前不能把已有分身当作制作原料。",
    );
  });

  it("does not silently switch to another person when the selected id is stale", () => {
    currentPage = "person-ip";
    selectedPersonId = "missing-person";
    render(<PersonPage />);
    expect(screen.getByText("未选择人物")).toBeInTheDocument();
    expect(screen.queryByText("测试人物")).not.toBeInTheDocument();
  });
});
