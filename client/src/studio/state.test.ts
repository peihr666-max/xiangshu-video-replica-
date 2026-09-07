import { describe, expect, it } from "vitest";
import {
  buildOralInput,
  createDraft,
  createState,
  draftFromTask,
  patchStudioDraft,
  routeFromHash,
  withImportedProject,
} from "./state";
import type { StudioAsset } from "./types";

const oralAudio: StudioAsset = {
  id: "speech",
  name: "完整口播.mp3",
  kind: "audio",
  group: "我的上传",
  source: "素材库",
  saved: true,
  allowedUses: ["oral_audio"],
};

describe("V1.4 交接合同", () => {
  it("同项目返回保留人物和未保存终稿，不回退到旧版本", () => {
    const state = createState("copy");
    state.draft = {
      ...state.draft,
      projectId: "p1",
      ipId: "zhang",
      voiceId: "voice",
      imageId: "photo",
      script: {
        ...state.draft.script,
        id: "script",
        text: "本地终稿",
        version: 3,
      },
    };
    const imported = {
      ...createDraft(),
      projectId: "p1",
      script: { ...state.draft.script, text: "旧版本", version: 2 },
    };
    const next = withImportedProject(state, imported);
    expect(next.draft.id).toBe(state.draft.id);
    expect(next.draft.ipId).toBe("zhang");
    expect(next.draft.voiceId).toBe("voice");
    expect(next.draft.imageId).toBe("photo");
    expect(next.draft.script.text).toBe("本地终稿");
  });
  it("切换项目清除上一项目的选择和返回上下文", () => {
    const state = {
      ...createState(),
      selectedTaskId: "old-task",
      selectedAssetId: "old-audio",
      selectedPersonId: "old-ip",
      selectedVideoId: "old-video",
      returnTo: "oral" as const,
    };
    const imported = { ...createDraft(), projectId: "new-project" };
    const next = withImportedProject(state, imported);
    expect(next.draft).toEqual(imported);
    for (const key of [
      "selectedTaskId",
      "selectedAssetId",
      "selectedPersonId",
      "selectedVideoId",
      "returnTo",
    ] as const)
      expect(next[key]).toBeUndefined();
  });
  it("历史任务再创作使用独立草稿，不把成片当上游视频", () => {
    const original = createDraft();
    original.sourceId = "source-original";
    original.script = {
      ...original.script,
      text: "旧任务的脚本",
      confirmed: true,
    };
    const next = draftFromTask({
      id: "task",
      title: "任务",
      type: "数字人口播",
      status: "completed",
      submitted: "today",
      driverMode: "audio",
      audioId: "speech-original",
      resultId: "final-video",
      ipId: "person-original",
      draftSnapshot: original,
    });
    expect(next.id).not.toBe(original.id);
    expect(next.sourceId).toBe("source-original");
    expect(next.audioId).toBe("speech-original");
    expect(next.voiceId).toBeUndefined();
    expect(next.script.confirmed).toBe(false);
    expect(next.script.text).toBe("旧任务的脚本");
  });
  it("首页默认工作台，旧路由有确定映射", () => {
    expect(routeFromHash("")).toBe("workbench");
    expect(routeFromHash("#projects")).toBe("replica");
    expect(routeFromHash("#studio/oral-audio")).toBe("oral-audio");
    expect(routeFromHash("#admin")).toBe("workbench");
  });
  it("更换IP清除旧分身与声音并使报价失效", () => {
    const draft = {
      ...createDraft(),
      ipId: "a",
      avatarId: "avatar-a",
      voiceId: "voice-a",
    };
    const next = patchStudioDraft(draft, { ipId: "b" });
    expect(next.avatarId).toBeUndefined();
    expect(next.voiceId).toBeUndefined();
    expect(next.quoteRevision).toBe(draft.quoteRevision + 1);
    expect(next.id).toBe(draft.id);
  });
  it("照片带入仅修改目标，不覆盖原始画面与选中镜头", () => {
    const draft = {
      ...createDraft(),
      originalImageId: "original",
      selectedShotId: "shot-2",
    };
    const next = patchStudioDraft(draft, { imageId: "target" });
    expect(next.originalImageId).toBe("original");
    expect(next.selectedShotId).toBe("shot-2");
  });
  it("音频驱动不携带文案/TTS/声音/模板字段", () => {
    const draft = {
      ...createDraft(),
      audioId: "speech",
      avatarId: "avatar",
      voiceId: "voice",
      ipId: "ip",
    };
    expect(buildOralInput(draft, "audio", [oralAudio])).toEqual({
      draftId: draft.id,
      mode: "audio",
      ipId: "ip",
      avatarId: "avatar",
      audioAssetId: "speech",
    });
  });
  it.each([
    { saved: false, allowedUses: ["oral_audio"] },
    { saved: true, allowedUses: [] },
    { saved: true, allowedUses: undefined },
  ])("音频提交拒绝未就绪或不允许口播的资产 %j", (patch) => {
    const draft = {
      ...createDraft(),
      audioId: oralAudio.id,
      ipId: "ip",
      avatarId: "avatar",
    };
    expect(() =>
      buildOralInput(draft, "audio", [{ ...oralAudio, ...patch }]),
    ).toThrow("音频");
  });
  it("文案模式需要已确认终稿和声音，不提交音频", () => {
    const draft = createDraft();
    expect(() => buildOralInput(draft, "text")).toThrow("终稿");
    const ready = {
      ...draft,
      ipId: "ip",
      avatarId: "avatar",
      voiceId: "voice",
      audioId: "irrelevant",
      script: { ...draft.script, confirmed: true, text: "我是张工" },
    };
    const input = buildOralInput(ready, "text");
    expect(input).not.toHaveProperty("audioAssetId");
    expect(input).toHaveProperty("scriptVersion", ready.script.version);
  });
});
