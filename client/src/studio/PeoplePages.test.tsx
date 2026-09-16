import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PeoplePage, PersonPage } from "./PeoplePages";

const api = vi.hoisted(() => ({
  customerVisibleErrorMessage: vi.fn(
    (_cause: unknown, fallback: string) => fallback,
  ),
  completeMaterialUpload: vi.fn(),
  putMaterial: vi.fn(),
  confirmOralVoice: vi.fn(),
  createMaterialUploadIntent: vi.fn(),
  createOralAvatarClone: vi.fn(),
  createOralConsent: vi.fn(),
  createOralVoiceClone: vi.fn(),
  refreshOralAvatar: vi.fn(),
  refreshOralVoice: vi.fn(),
  updateSimpleCharacterProfile: vi.fn(),
  uploadMaterial: vi.fn(),
  getLatestSceneLookTask: vi.fn(async () => null),
  listCharacterSceneLooks: vi.fn(async () => []),
  createCharacterSceneLook: vi.fn(),
  waitForCharacterSheetTask: vi.fn(),
  getCachedCharacterAssetUrl: vi.fn(async () => ({ url: "/scene.png" })),
}));
const live = vi.hoisted(() => ({
  loadMorePeople: vi.fn(),
  loadPersonAssets: vi.fn(),
  readAudioDuration: vi.fn(async () => 30),
  uploadOralAudioMaterial: vi.fn(),
  validateOralAudioFile: vi.fn(),
}));

vi.mock("../api", () => api);
vi.mock("./live", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ...live,
}));
const oralLive = live;

const navigate = vi.fn();
const patchDraft = vi.fn();
const notify = vi.fn();
const refresh = vi.fn();
const updateData = vi.fn();
const openPicker = vi.fn();
const openLive = vi.fn();
let currentPage = "people";
let selectedPersonId: string | undefined = "p1";
let returnTo: string | undefined;
let review = true;
let currentRole: "customer" | "employee" | "auditor" = "customer";
let draft: Record<string, string | undefined> = {};
let pagination: Record<string, unknown> | undefined;
let voiceSourceUses: string[] | undefined = ["voice_clone"];

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
          sceneLookCount: 1,
          photoIds: ["scene"],
          avatars: [
            {
              id: "avatar-1",
              name: "测试分身",
              imageId: "avatar-image",
              ready: true,
              origin: "视频制作",
              duration: "00:30",
            },
            {
              id: "avatar-pending",
              name: "制作中分身",
              imageId: "avatar-image",
              ready: false,
              status: "PENDING",
              origin: "视频制作",
              duration: "制作中",
            },
            {
              id: "avatar-unknown",
              name: "待核对分身",
              imageId: "avatar-image",
              ready: false,
              status: "RUNNING",
              submissionState: "SUBMISSION_UNKNOWN",
              origin: "照片制作",
              duration: "提交结果待核对",
            },
          ],
          voices: [
            {
              id: "voice-ok",
              name: "已确认音色",
              confirmed: true,
            },
            {
              id: "voice-pending",
              name: "待确认音色",
              confirmed: false,
              status: "READY",
              url: "/voice-preview.mp3",
            },
            {
              id: "voice-running",
              name: "克隆中音色",
              confirmed: false,
              status: "RUNNING",
            },
            {
              id: "voice-archiving",
              name: "待归档音色",
              confirmed: false,
              status: "READY",
            },
            {
              id: "voice-unknown",
              name: "待核对音色",
              confirmed: false,
              status: "RUNNING",
              submissionState: "SUBMISSION_UNKNOWN",
            },
          ],
        },
        {
          id: "p2",
          name: "其他人物",
          role: "项目经理",
          portrait: "/people/other-person.png",
          version: 1,
          scope: "施工管理",
          audience: "在建家庭",
          expression: "清晰",
          sceneLookCount: 0,
          photoIds: ["other-scene"],
          avatars: [],
          voices: [],
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
          source: "人物库场景造型",
          saved: true,
        },
        {
          id: "other-scene",
          name: "其他人物场景照",
          kind: "image",
          url: "/other-scene.png",
          group: "人物素材",
          personId: "p2",
          source: "AI生成",
          saved: true,
        },
        {
          id: "voice-source",
          name: "张工录音样本",
          kind: "audio",
          url: "/voice-source.mp3",
          allowedUses: voiceSourceUses,
          group: "声音素材",
          personId: "p1",
          source: "用户上传",
          saved: true,
        },
      ],
      pagination,
      videos: [],
      tasks: [],
      projects: [],
    },
    review,
    user: {
      id: "current-user",
      username: "current-user",
      display_name: "Current User",
      role: currentRole,
    },
    navigate,
    patchDraft,
    patchState: vi.fn(),
    updateData,
    notify,
    openPicker,
    openLive,
    requestGeneration: vi.fn(),
    saveDraft: vi.fn(),
    refresh,
  }),
}));

describe("PeoplePages", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  beforeEach(() => {
    currentPage = "people";
    selectedPersonId = "p1";
    returnTo = undefined;
    review = true;
    currentRole = "customer";
    draft = {};
    voiceSourceUses = ["voice_clone"];
    pagination = undefined;
    navigate.mockClear();
    patchDraft.mockClear();
    notify.mockClear();
    refresh.mockClear();
    updateData.mockClear();
    openPicker.mockClear();
    openLive.mockClear();
    vi.clearAllMocks();
    oralLive.readAudioDuration.mockResolvedValue(30);
    oralLive.validateOralAudioFile.mockImplementation((file: File) =>
      file.name.toLowerCase().endsWith(".mp3")
        ? undefined
        : "仅支持 MP3 音频。",
    );
    oralLive.uploadOralAudioMaterial.mockResolvedValue({
      id: "audio-upload",
      name: "voice.mp3",
      kind: "audio",
      group: "声音克隆样本",
      source: "我的上传",
      saved: true,
      allowedUses: ["voice_clone"],
    });
    api.putMaterial.mockImplementation(
      async (intent, file, onProgress, signal) => {
        await api.uploadMaterial(intent, file, onProgress, signal);
        return api.completeMaterialUpload(intent.asset_id);
      },
    );
  });

  it("人物场景照片尚未读取时显示未知而不是零张", () => {
    review = false;
    render(<PeoplePage />);
    expect(screen.getAllByText("形象照片数量未知")).toHaveLength(2);
    expect(screen.queryByText("✓ 形象照片 0 张")).toBeNull();
  });

  it("人物定位长内容支持多行编辑且保留换行提交", async () => {
    currentPage = "person-ip";
    review = false;
    render(<PersonPage />);
    const scope = screen.getByLabelText("服务范围");
    expect(scope.tagName).toBe("TEXTAREA");
    fireEvent.change(scope, {
      target: { value: "方案设计\n施工管理\n交付验收" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存 IP 定位" }));
    await waitFor(() =>
      expect(api.updateSimpleCharacterProfile).toHaveBeenCalledWith(
        "p1",
        expect.objectContaining({
          service_scope: "方案设计\n施工管理\n交付验收",
        }),
      ),
    );
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

  it("形象照入口定位当前人物，AI 按钮直接展开场景参数而不返回列表", async () => {
    currentPage = "person-photos";
    review = false;
    render(<PersonPage />);
    fireEvent.click(screen.getByRole("button", { name: "管理形象照" }));
    expect(openLive).toHaveBeenCalledWith("characters", {
      identityId: "p1",
      tab: "base",
    });
    openLive.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "AI 生成场景照" }));
    expect(await screen.findByLabelText("场景名称")).toBeInTheDocument();
    expect(screen.getByLabelText("场景描述")).toBeInTheDocument();
    expect(screen.getByLabelText("服装描述")).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
    expect(openLive).not.toHaveBeenCalled();
    expect(api.createCharacterSceneLook).not.toHaveBeenCalled();
  });

  it("未知提交态明确警示且不提供普通刷新动作", () => {
    currentPage = "person-avatars";
    const avatarView = render(<PersonPage />);
    const avatar = screen.getByText("待核对分身").closest("article");
    expect(avatar).not.toBeNull();
    expect(
      within(avatar as HTMLElement).getByText(/禁止重复提交/),
    ).toBeInTheDocument();
    expect(
      within(avatar as HTMLElement).queryByRole("button", {
        name: "刷新制作状态",
      }),
    ).not.toBeInTheDocument();

    avatarView.unmount();
    currentPage = "person-voices";
    render(<PersonPage />);
    const voice = screen.getByText("待核对音色").closest("article");
    expect(voice).not.toBeNull();
    expect(
      within(voice as HTMLElement).getByText(/禁止重复提交/),
    ).toBeInTheDocument();
    expect(
      within(voice as HTMLElement).queryByRole("button", {
        name: "刷新克隆状态",
      }),
    ).not.toBeInTheDocument();
  });

  it("filters people by role", async () => {
    render(<PeoplePage />);
    await screen.getByRole("button", { name: "客户经理" }).click();
    expect(screen.queryByText("测试人物")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "人物库" })).toBeInTheDocument();
  });

  it("人物和场景分别按服务端 total 加载下一页", async () => {
    review = false;
    pagination = {
      people: { nextCursor: "people-next", total: 9 },
      scenes: { p1: { loaded: 1, total: 13 } },
    };
    live.loadMorePeople.mockResolvedValue({
      people: [],
      assets: [],
      errors: [],
      nextCursor: null,
      total: 9,
    });
    live.loadPersonAssets.mockResolvedValue({
      assets: [],
      errors: [],
      loaded: 13,
      total: 13,
    });

    const peopleView = render(<PeoplePage />);
    fireEvent.click(screen.getByRole("button", { name: "加载更多人物" }));
    expect(live.loadMorePeople).toHaveBeenCalledWith("people-next");
    peopleView.unmount();

    currentPage = "person-photos";
    render(<PersonPage />);
    fireEvent.click(screen.getByRole("button", { name: "加载更多场景" }));
    expect(live.loadPersonAssets).toHaveBeenCalledWith("p1", 1);
  });

  it("场景下一页失败后保留原计数并可重试追加末条", async () => {
    review = false;
    currentPage = "person-photos";
    pagination = { scenes: { p1: { loaded: 12, total: 13 } } };
    live.loadPersonAssets
      .mockRejectedValueOnce(new Error("scene page failed"))
      .mockResolvedValueOnce({
        assets: [
          {
            id: "scene-13",
            name: "第十三场景",
            kind: "image",
            group: "场景形象照",
            personId: "p1",
            source: "人物库场景造型",
            saved: true,
          },
        ],
        errors: [],
        loaded: 13,
        total: 13,
      });

    render(<PersonPage />);
    fireEvent.click(screen.getByRole("button", { name: "加载更多场景" }));
    await waitFor(() =>
      expect(notify).toHaveBeenCalledWith("加载更多场景失败，请重试。"),
    );
    expect(updateData).not.toHaveBeenCalled();
    expect(screen.getByText("已加载 12 / 13 套场景")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "加载更多场景" }));
    await waitFor(() => expect(updateData).toHaveBeenCalledOnce());
    const update = updateData.mock.calls[0]?.[0];
    const current = {
      assets: [],
      people: [{ id: "p1", photoIds: [] }],
      errors: [],
      pagination: { scenes: { p1: { loaded: 12, total: 13 } } },
    };
    const next = update(current);
    expect(
      next.assets.filter((asset: { id: string }) => asset.id === "scene-13"),
    ).toHaveLength(1);
    expect(next.pagination.scenes.p1).toEqual({ loaded: 13, total: 13 });
  });

  it("renders the IP tab without exposing authorization settings", () => {
    render(<PersonPage />);
    expect(
      screen.getByRole("heading", { name: "身份与业务" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("授权与状态")).not.toBeInTheDocument();
  });

  it("keeps the five views as one composite image and lists scene photos separately", () => {
    currentPage = "person-photos";
    render(<PersonPage />);
    expect(screen.getByAltText("五视图合成图")).toBeInTheDocument();
    expect(screen.getByText("基础五视图 · 1 张合成图")).toBeInTheDocument();
  });

  it("形象照片保留人物置换但不提供口播分身入口", () => {
    currentPage = "person-photos";
    render(<PersonPage />);
    expect(screen.queryByRole("button", { name: "制作口播分身" })).toBeNull();
    expect(screen.getByRole("button", { name: "用于人物置换" })).toBeEnabled();
  });

  it("视频分身创建不读取草稿中的照片", () => {
    currentPage = "person-avatars";
    draft = { ipId: "p1", imageId: "scene" };
    render(<PersonPage />);
    fireEvent.click(screen.getByRole("button", { name: "上传视频创建分身" }));
    expect(screen.queryByText("已选：场景形象")).toBeNull();
    expect(screen.queryByRole("button", { name: "用形象照片制作" })).toBeNull();
    expect(
      screen.getByRole("button", { name: "开始制作视频分身" }),
    ).toBeDisabled();
  });

  it("does not present an unconfirmed voice as selectable", () => {
    currentPage = "person-voices";
    render(<PersonPage />);
    const card = screen.getByText("待确认音色").closest("article");
    expect(card).not.toBeNull();
    expect(
      within(card as HTMLElement).getByText("待试听确认，暂不可选用"),
    ).toBeInTheDocument();
    expect(
      within(card as HTMLElement).getByRole("button", {
        name: "确认使用此声音",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "使用此分身" }),
    ).not.toBeInTheDocument();
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

  it("正式模式会把 IP 定位保存到后端", async () => {
    currentPage = "person-ip";
    review = false;
    api.updateSimpleCharacterProfile.mockResolvedValue({});

    render(<PersonPage />);
    screen.getByRole("button", { name: "保存 IP 定位" }).click();

    expect(api.updateSimpleCharacterProfile).toHaveBeenCalledWith("p1", {
      display_name: "测试人物",
      role: "乡墅设计师",
      service_scope: "乡墅方案",
      target_audience: "准备建房的家庭",
      expression_style: "专业",
      audience_needs: "",
      factual_background: "",
      sample_script: "",
      forbidden_claims: "",
    });
  });

  it.each([undefined, ["oral_audio"]])(
    "不把未验证为声音样本的历史音频带入克隆表单：%s",
    (allowedUses) => {
      currentPage = "person-voices";
      review = false;
      voiceSourceUses = allowedUses;
      draft = { ipId: "p1", audioId: "voice-source" };
      render(<PersonPage />);
      fireEvent.click(screen.getByRole("button", { name: "创建克隆声音" }));
      expect(screen.getByText("请先选择声音样本。")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "开始克隆声音" }),
      ).toBeDisabled();
      expect(api.createOralConsent).not.toHaveBeenCalled();
    },
  );

  it("用已选音频提交声音克隆", async () => {
    currentPage = "person-voices";
    review = false;
    draft = { ipId: "p1", audioId: "voice-source" };
    api.createOralVoiceClone.mockResolvedValue({
      id: "voice-new",
      status: "RUNNING",
    });
    api.createOralConsent.mockResolvedValue({ id: "consent-voice" });

    render(<PersonPage />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          currentPage === "person-avatars"
            ? "上传视频创建分身"
            : "创建克隆声音",
      }),
    );
    screen.getByRole("checkbox", { name: "确认声音克隆授权" }).click();
    screen.getByRole("button", { name: "开始克隆声音" }).click();

    expect(api.createOralConsent).toHaveBeenCalledWith({
      identityId: "p1",
      sourceAssetId: "voice-source",
      purpose: "VOICE",
    });
    await vi.waitFor(() =>
      expect(api.createOralVoiceClone).toHaveBeenCalledWith({
        identityId: "p1",
        title: "测试人物本人音色",
        sourceAssetId: "voice-source",
        consentId: "consent-voice",
        idempotencyKey: expect.any(String),
      }),
    );
    await vi.waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("声音克隆重试复用幂等键，标题变化后生成新键", async () => {
    currentPage = "person-voices";
    review = false;
    draft = { ipId: "p1", audioId: "voice-source" };
    api.createOralConsent
      .mockResolvedValueOnce({ id: "consent-1" })
      .mockResolvedValueOnce({ id: "consent-2" });
    api.createOralVoiceClone
      .mockRejectedValueOnce(new Error("network"))
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValue({ id: "voice-new", status: "RUNNING" });

    render(<PersonPage />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          currentPage === "person-avatars"
            ? "上传视频创建分身"
            : "创建克隆声音",
      }),
    );
    screen.getByRole("checkbox", { name: "确认声音克隆授权" }).click();
    const submit = screen.getByRole("button", { name: "开始克隆声音" });
    submit.click();
    await screen.findByRole("alert");
    submit.click();
    await vi.waitFor(() =>
      expect(api.createOralVoiceClone).toHaveBeenCalledTimes(2),
    );

    const firstKey = api.createOralVoiceClone.mock.calls[0]?.[0].idempotencyKey;
    const retryKey = api.createOralVoiceClone.mock.calls[1]?.[0].idempotencyKey;
    expect(firstKey).toEqual(expect.any(String));
    expect(retryKey).toBe(firstKey);
    expect(api.createOralConsent).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(submit).toBeEnabled());

    fireEvent.change(screen.getByLabelText("声音名称"), {
      target: { value: "测试人物本人音色 V2" },
    });
    submit.click();
    await vi.waitFor(() =>
      expect(api.createOralVoiceClone).toHaveBeenCalledTimes(3),
    );
    expect(api.createOralVoiceClone.mock.calls[2]?.[0].idempotencyKey).not.toBe(
      firstKey,
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

  it("上传本地视频后提交视频分身", async () => {
    currentPage = "person-avatars";
    review = false;
    api.createMaterialUploadIntent.mockResolvedValue({
      asset_id: "video-asset",
      material_id: "asset:video-asset",
    });
    api.uploadMaterial.mockImplementation(
      (_intent: unknown, _file: File, onProgress: (value: number) => void) => {
        onProgress(45);
        return Promise.resolve();
      },
    );
    api.completeMaterialUpload.mockResolvedValue({ asset_id: "video-asset" });
    api.createOralConsent.mockResolvedValue({ id: "consent-video" });
    api.createOralAvatarClone.mockResolvedValue({
      id: "avatar-video",
      status: "RUNNING",
    });
    render(<PersonPage />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          currentPage === "person-avatars"
            ? "上传视频创建分身"
            : "创建克隆声音",
      }),
    );

    fireEvent.change(screen.getByLabelText("选择人物视频"), {
      target: {
        files: [new File(["video"], "avatar.mp4", { type: "video/mp4" })],
      },
    });
    await screen.findByText("已上传：avatar.mp4");
    screen.getByRole("checkbox", { name: "确认分身克隆授权" }).click();
    screen.getByRole("button", { name: "开始制作视频分身" }).click();

    expect(api.putMaterial).toHaveBeenCalledWith(
      expect.objectContaining({ asset_id: "video-asset" }),
      expect.any(File),
      expect.any(Function),
      expect.any(AbortSignal),
    );
    await vi.waitFor(() =>
      expect(api.createOralAvatarClone).toHaveBeenCalledWith(
        expect.objectContaining({
          sourceAssetId: "video-asset",
          sourceKind: "VIDEO",
          consentId: "consent-video",
        }),
      ),
    );
  });

  it("上传本地 MP3 后提交声音克隆", async () => {
    currentPage = "person-voices";
    review = false;
    oralLive.uploadOralAudioMaterial.mockResolvedValue({
      id: "audio-asset",
      name: "voice.mp3",
      kind: "audio",
      group: "声音克隆样本",
      source: "我的上传",
      saved: true,
      allowedUses: ["voice_clone"],
    });
    api.createOralConsent.mockResolvedValue({ id: "consent-audio" });
    api.createOralVoiceClone.mockResolvedValue({
      id: "voice-new",
      status: "RUNNING",
    });
    render(<PersonPage />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          currentPage === "person-avatars"
            ? "上传视频创建分身"
            : "创建克隆声音",
      }),
    );

    fireEvent.change(screen.getByLabelText("选择声音样本"), {
      target: {
        files: [new File(["audio"], "voice.mp3", { type: "audio/mpeg" })],
      },
    });
    await screen.findByText("已上传：voice.mp3");
    screen.getByRole("checkbox", { name: "确认声音克隆授权" }).click();
    screen.getByRole("button", { name: "开始克隆声音" }).click();

    expect(oralLive.uploadOralAudioMaterial).toHaveBeenCalledWith(
      expect.any(File),
      "voice_clone",
      30,
      expect.any(Function),
      expect.any(AbortSignal),
    );
    await vi.waitFor(() =>
      expect(api.createOralVoiceClone).toHaveBeenCalledWith(
        expect.objectContaining({
          sourceAssetId: "audio-asset",
          consentId: "consent-audio",
        }),
      ),
    );
  });

  it("取消声音样本上传后中止请求并忽略迟到完成", async () => {
    currentPage = "person-voices";
    review = false;
    let finishUpload!: (asset: {
      id: string;
      name: string;
      kind: "audio";
      group: string;
      source: string;
      saved: boolean;
      allowedUses: string[];
    }) => void;
    oralLive.uploadOralAudioMaterial.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishUpload = resolve;
        }),
    );
    render(<PersonPage />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          currentPage === "person-avatars"
            ? "上传视频创建分身"
            : "创建克隆声音",
      }),
    );

    fireEvent.change(screen.getByLabelText("选择声音样本"), {
      target: {
        files: [new File(["ID3audio"], "voice.mp3", { type: "audio/mpeg" })],
      },
    });
    const cancel = await screen.findByRole("button", { name: "取消上传" });
    const signal = oralLive.uploadOralAudioMaterial.mock
      .calls[0][4] as AbortSignal;
    fireEvent.click(cancel);
    expect(signal.aborted).toBe(true);

    finishUpload({
      id: "late-voice-audio",
      name: "voice.mp3",
      kind: "audio",
      group: "声音克隆样本",
      source: "我的上传",
      saved: true,
      allowedUses: ["voice_clone"],
    });
    await Promise.resolve();

    expect(screen.queryByText("已上传：voice.mp3")).not.toBeInTheDocument();
    expect(api.createOralConsent).not.toHaveBeenCalled();
    expect(api.createOralVoiceClone).not.toHaveBeenCalled();
    expect(patchDraft).not.toHaveBeenCalled();
  });

  it("切换人物后忽略上一人物声音上传的迟到完成", async () => {
    currentPage = "person-voices";
    review = false;
    let finishUpload!: (asset: {
      id: string;
      name: string;
      kind: "audio";
      group: string;
      source: string;
      saved: boolean;
      allowedUses: string[];
    }) => void;
    oralLive.uploadOralAudioMaterial.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishUpload = resolve;
        }),
    );
    const view = render(<PersonPage />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          currentPage === "person-avatars"
            ? "上传视频创建分身"
            : "创建克隆声音",
      }),
    );
    fireEvent.change(screen.getByLabelText("选择声音样本"), {
      target: {
        files: [new File(["ID3audio"], "old.mp3", { type: "audio/mpeg" })],
      },
    });
    await vi.waitFor(() =>
      expect(oralLive.uploadOralAudioMaterial).toHaveBeenCalledOnce(),
    );

    selectedPersonId = "p2";
    view.rerender(<PersonPage />);
    finishUpload({
      id: "old-person-audio",
      name: "old.mp3",
      kind: "audio",
      group: "声音克隆样本",
      source: "我的上传",
      saved: true,
      allowedUses: ["voice_clone"],
    });
    await Promise.resolve();

    expect(screen.queryByText("已上传：old.mp3")).not.toBeInTheDocument();
    expect(api.createOralConsent).not.toHaveBeenCalled();
    expect(api.createOralVoiceClone).not.toHaveBeenCalled();
  });

  it("离开声音页时中止上传并隔离迟到完成", async () => {
    currentPage = "person-voices";
    review = false;
    let finishUpload!: (asset: {
      id: string;
      name: string;
      kind: "audio";
      group: string;
      source: string;
      saved: boolean;
      allowedUses: string[];
    }) => void;
    oralLive.uploadOralAudioMaterial.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishUpload = resolve;
        }),
    );
    const view = render(<PersonPage />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          currentPage === "person-avatars"
            ? "上传视频创建分身"
            : "创建克隆声音",
      }),
    );
    fireEvent.change(screen.getByLabelText("选择声音样本"), {
      target: {
        files: [new File(["ID3audio"], "leave.mp3", { type: "audio/mpeg" })],
      },
    });
    await vi.waitFor(() =>
      expect(oralLive.uploadOralAudioMaterial).toHaveBeenCalledOnce(),
    );
    const signal = oralLive.uploadOralAudioMaterial.mock
      .calls[0][4] as AbortSignal;

    view.unmount();
    expect(signal.aborted).toBe(true);
    finishUpload({
      id: "unmounted-audio",
      name: "leave.mp3",
      kind: "audio",
      group: "声音克隆样本",
      source: "我的上传",
      saved: true,
      allowedUses: ["voice_clone"],
    });
    await Promise.resolve();

    expect(api.createOralConsent).not.toHaveBeenCalled();
    expect(api.createOralVoiceClone).not.toHaveBeenCalled();
    expect(patchDraft).not.toHaveBeenCalled();
  });

  it("未授权不能提交克隆，且上传格式错误可见", () => {
    currentPage = "person-voices";
    review = false;
    draft = { ipId: "p1", audioId: "voice-source" };
    render(<PersonPage />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          currentPage === "person-avatars"
            ? "上传视频创建分身"
            : "创建克隆声音",
      }),
    );

    expect(screen.getByRole("button", { name: "开始克隆声音" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("选择声音样本"), {
      target: {
        files: [new File(["bad"], "voice.wav", { type: "audio/wav" })],
      },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("仅支持 MP3");
  });

  it("显示上传进度和服务端失败，并拒绝超大文件", async () => {
    currentPage = "person-avatars";
    review = false;
    let finishUpload: () => void = () => {};
    api.createMaterialUploadIntent.mockResolvedValue({
      asset_id: "video-asset",
      material_id: "asset:video-asset",
    });
    api.uploadMaterial.mockImplementation(
      (_intent: unknown, _file: File, onProgress: (value: number) => void) => {
        onProgress(45);
        return new Promise<void>((resolve) => {
          finishUpload = resolve;
        });
      },
    );
    api.completeMaterialUpload.mockRejectedValue(new Error("storage down"));
    render(<PersonPage />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          currentPage === "person-avatars"
            ? "上传视频创建分身"
            : "创建克隆声音",
      }),
    );

    fireEvent.change(screen.getByLabelText("选择人物视频"), {
      target: {
        files: [new File(["video"], "avatar.mp4", { type: "video/mp4" })],
      },
    });
    expect(await screen.findByText("上传中 45%")).toBeInTheDocument();
    finishUpload();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "人物视频上传失败",
    );

    const tooLarge = new File(["video"], "large.mp4", { type: "video/mp4" });
    Object.defineProperty(tooLarge, "size", { value: 50 * 1024 * 1024 + 1 });
    fireEvent.change(screen.getByLabelText("选择人物视频"), {
      target: { files: [tooLarge] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("不能超过 50 MB");
  });

  it("审核示例模式不上传人物视频", () => {
    currentPage = "person-avatars";
    render(<PersonPage />);

    fireEvent.click(screen.getByRole("button", { name: "上传视频创建分身" }));
    fireEvent.click(screen.getByRole("button", { name: /上传你的真人视频/ }));

    expect(api.createMaterialUploadIntent).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledWith("审核模式保留示例素材，不执行真实上传");
  });

  it("READY 声音可试听并通过后端确认使用", async () => {
    currentPage = "person-voices";
    review = false;
    api.confirmOralVoice.mockResolvedValue({
      id: "voice-pending",
      status: "READY",
      confirmed: true,
    });
    render(<PersonPage />);

    const card = screen.getByText("待确认音色").closest("article");
    expect(card).not.toBeNull();
    expect(
      within(card as HTMLElement).getByLabelText("待确认音色试听"),
    ).toHaveAttribute("src", "/voice-preview.mp3");
    within(card as HTMLElement)
      .getByRole("button", { name: "确认使用此声音" })
      .click();

    await vi.waitFor(() =>
      expect(api.confirmOralVoice).toHaveBeenCalledWith("voice-pending"),
    );
    expect(patchDraft).toHaveBeenCalledWith({
      ipId: "p1",
      voiceId: "voice-pending",
    });
  });

  it("READY 但试听样例未归档时不允许确认", () => {
    currentPage = "person-voices";
    review = false;
    render(<PersonPage />);

    const card = screen.getByText("待归档音色").closest("article");
    expect(card).not.toBeNull();
    expect(
      within(card as HTMLElement).getByText("试听样例归档中"),
    ).toBeInTheDocument();
    expect(
      within(card as HTMLElement).queryByRole("button", {
        name: "确认使用此声音",
      }),
    ).not.toBeInTheDocument();
  });

  it("声音样本明确限制为 5–180 秒 MP3 且不超过 20 MB", () => {
    currentPage = "person-voices";
    render(<PersonPage />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          currentPage === "person-avatars"
            ? "上传视频创建分身"
            : "创建克隆声音",
      }),
    );

    expect(screen.getByText(/5–180 秒（3 分钟）清晰干声/)).toBeInTheDocument();
    expect(
      screen.getByText(/MP3，时长 5–180 秒（3 分钟），上限 20 MB/),
    ).toBeInTheDocument();
  });

  it("声音克隆超过供应商 20 MB 上限时不上传也不探测", async () => {
    currentPage = "person-voices";
    review = false;
    render(<PersonPage />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          currentPage === "person-avatars"
            ? "上传视频创建分身"
            : "创建克隆声音",
      }),
    );
    const file = new File(["ID3audio"], "oversized.mp3", {
      type: "audio/mpeg",
    });
    Object.defineProperty(file, "size", { value: 20 * 1024 * 1024 + 1 });
    fireEvent.change(screen.getByLabelText("选择声音样本"), {
      target: { files: [file] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("20 MB");
    expect(oralLive.readAudioDuration).not.toHaveBeenCalled();
    expect(oralLive.uploadOralAudioMaterial).not.toHaveBeenCalled();
  });

  it("声音样本选择使用独立用途选择器", () => {
    currentPage = "person-voices";
    render(<PersonPage />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          currentPage === "person-avatars"
            ? "上传视频创建分身"
            : "创建克隆声音",
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "从素材选择声音样本" }));
    expect(openPicker).toHaveBeenCalledWith("voice-audio");
  });

  it("声音克隆样本超过 180 秒时在上传前拒绝", async () => {
    currentPage = "person-voices";
    review = false;
    oralLive.readAudioDuration.mockResolvedValue(181);
    render(<PersonPage />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          currentPage === "person-avatars"
            ? "上传视频创建分身"
            : "创建克隆声音",
      }),
    );

    fireEvent.change(screen.getByLabelText("选择声音样本"), {
      target: {
        files: [new File(["ID3audio"], "too-long.mp3", { type: "audio/mpeg" })],
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("5–180 秒");
    expect(oralLive.uploadOralAudioMaterial).not.toHaveBeenCalled();
  });

  it("切换声音素材后清空旧授权状态", () => {
    currentPage = "person-voices";
    review = false;
    draft = { ipId: "p1", audioId: "voice-source" };
    const view = render(<PersonPage />);
    fireEvent.click(
      screen.getByRole("button", {
        name:
          currentPage === "person-avatars"
            ? "上传视频创建分身"
            : "创建克隆声音",
      }),
    );
    const consent = screen.getByRole("checkbox", { name: "确认声音克隆授权" });
    consent.click();
    expect(consent).toBeChecked();

    draft = { ipId: "p1" };
    view.rerender(<PersonPage />);

    expect(consent).not.toBeChecked();
    expect(screen.getByRole("button", { name: "开始克隆声音" })).toBeDisabled();
  });

  it("正式模式自动刷新制作中分身，卸载后停止计时", async () => {
    vi.useFakeTimers();
    currentPage = "person-avatars";
    review = false;
    api.refreshOralAvatar.mockResolvedValue({ status: "RUNNING" });

    const view = render(<PersonPage />);
    await act(async () => vi.advanceTimersByTimeAsync(6_000));

    expect(api.refreshOralAvatar).toHaveBeenCalledWith("avatar-pending");
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("正式模式自动刷新声音克隆和样例归档，错误可见", async () => {
    vi.useFakeTimers();
    currentPage = "person-voices";
    review = false;
    api.refreshOralVoice.mockRejectedValue(new Error("provider timeout"));

    const view = render(<PersonPage />);
    await act(async () => vi.advanceTimersByTimeAsync(6_000));

    expect(api.refreshOralVoice).toHaveBeenCalledWith("voice-running");
    expect(api.refreshOralVoice).toHaveBeenCalledWith("voice-archiving");
    expect(screen.getByRole("alert")).toHaveTextContent("声音状态自动刷新失败");
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("审核模式不发起自动刷新", async () => {
    vi.useFakeTimers();
    currentPage = "person-voices";
    render(<PersonPage />);

    await act(async () => vi.advanceTimersByTimeAsync(12_000));

    expect(api.refreshOralVoice).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("审计员可继续分页读取人物和场景但不能新增人物", async () => {
    review = false;
    currentRole = "auditor";
    pagination = {
      people: { nextCursor: "next", total: 3 },
      scenes: { p1: { loaded: 1, total: 2 } },
    };
    live.loadMorePeople.mockResolvedValue({
      people: [],
      assets: [],
      errors: [],
      nextCursor: null,
      total: 3,
    });
    live.loadPersonAssets.mockResolvedValue({
      assets: [],
      errors: [],
      loaded: 2,
      total: 2,
    });
    const view = render(<PeoplePage />);

    expect(screen.getByText("测试人物")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "新增人物" }));
    fireEvent.click(screen.getByRole("button", { name: "加载更多人物" }));
    expect(openLive).not.toHaveBeenCalled();
    expect(live.loadMorePeople).toHaveBeenCalledWith("next");

    view.unmount();
    currentPage = "person-photos";
    render(<PersonPage />);
    expect(screen.queryByRole("button", { name: "制作口播分身" })).toBeNull();
    expect(screen.getByRole("button", { name: "用于人物置换" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "加载更多场景" }));
    expect(live.loadPersonAssets).toHaveBeenCalledWith("p1", 1);
  });

  it("审计员的人物资料与口播克隆控件保持只读且不发 API", async () => {
    review = false;
    currentRole = "auditor";
    currentPage = "person-ip";
    const view = render(<PersonPage />);

    expect(screen.getByLabelText("姓名")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "去文案工坊创作" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "保存 IP 定位" }));
    expect(api.updateSimpleCharacterProfile).not.toHaveBeenCalled();

    currentPage = "person-avatars";
    draft = { ipId: "p1", imageId: "scene" };
    view.rerender(<PersonPage />);
    expect(screen.getByRole("button", { name: "使用此分身" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "上传视频创建分身" }),
    ).toBeDisabled();

    currentPage = "person-voices";
    draft = { ipId: "p1", audioId: "voice-source" };
    view.rerender(<PersonPage />);
    expect(screen.getByRole("button", { name: "创建克隆声音" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "确认使用此声音" }),
    ).toBeDisabled();

    expect(api.createOralConsent).not.toHaveBeenCalled();
    expect(api.createOralAvatarClone).not.toHaveBeenCalled();
    expect(api.createOralVoiceClone).not.toHaveBeenCalled();
    expect(api.confirmOralVoice).not.toHaveBeenCalled();
  });

  it("does not silently switch to another person when the selected id is stale", () => {
    currentPage = "person-ip";
    selectedPersonId = "missing-person";
    render(<PersonPage />);
    expect(screen.getByText("未选择人物")).toBeInTheDocument();
    expect(screen.queryByText("测试人物")).not.toBeInTheDocument();
  });
  it.each(["cancel", "person", "unmount"])(
    "视频上传 %s 后中止并忽略迟到完成",
    async (action) => {
      currentPage = "person-avatars";
      review = false;
      api.createMaterialUploadIntent.mockResolvedValue({
        asset_id: "video-late",
      });
      let finish!: (item: { asset_id: string }) => void;
      api.putMaterial.mockImplementation(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      );
      const view = render(<PersonPage />);
      fireEvent.click(screen.getByRole("button", { name: "上传视频创建分身" }));
      fireEvent.change(screen.getByLabelText("选择人物视频"), {
        target: {
          files: [new File(["video"], "late.mp4", { type: "video/mp4" })],
        },
      });
      await waitFor(() => expect(api.putMaterial).toHaveBeenCalledTimes(1));
      const signal = api.putMaterial.mock.calls[0][3] as AbortSignal;
      if (action === "cancel")
        fireEvent.click(screen.getByRole("button", { name: "取消上传" }));
      else if (action === "person") {
        selectedPersonId = "p2";
        view.rerender(<PersonPage />);
      } else view.unmount();
      expect(signal.aborted).toBe(true);
      await act(async () => finish({ asset_id: "late-video" }));
      expect(screen.queryByText("已上传：late.mp4")).toBeNull();
      expect(api.createOralAvatarClone).not.toHaveBeenCalled();
    },
  );

  it("离开人物后迟到的视频授权不继续提交克隆", async () => {
    currentPage = "person-avatars";
    review = false;
    api.createMaterialUploadIntent.mockResolvedValue({ asset_id: "video" });
    api.putMaterial.mockResolvedValue({ asset_id: "video" });
    let finishConsent!: (value: { id: string }) => void;
    api.createOralConsent.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishConsent = resolve;
        }),
    );
    const view = render(<PersonPage />);
    fireEvent.click(screen.getByRole("button", { name: "上传视频创建分身" }));
    fireEvent.change(screen.getByLabelText("选择人物视频"), {
      target: {
        files: [new File(["video"], "own.mp4", { type: "video/mp4" })],
      },
    });
    await screen.findByText("已上传：own.mp4");
    fireEvent.click(screen.getByLabelText("确认分身克隆授权"));
    fireEvent.click(screen.getByRole("button", { name: "开始制作视频分身" }));
    await waitFor(() => expect(api.createOralConsent).toHaveBeenCalled());
    selectedPersonId = "p2";
    view.rerender(<PersonPage />);
    await act(async () => finishConsent({ id: "late-consent" }));
    expect(api.createOralAvatarClone).not.toHaveBeenCalled();
  });
});
