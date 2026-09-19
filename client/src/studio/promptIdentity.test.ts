import { describe, expect, it } from "vitest";
import { anchorReplicaPromptToFirstFrame } from "./promptIdentity";

const LEGACY_TEXT =
  "全片人物身份、服装和配饰以首帧为准，后续不得恢复源人物外观。";

describe("anchorReplicaPromptToFirstFrame", () => {
  it("rebinds source presenter labels to the confirmed first frame", () => {
    const prompt = [
      "For the target video, <Picture 1> is fully referenced.",
      "integrated_multimodal_description: [Shot 1]",
      "全片人物身份、服装和配饰以首帧为准，后续不得恢复源人物外观。",
      "camera_language: 从全景切入女主持人的中景口播",
      "composition: 女主持人位于中央，村民站在两侧",
      "动作：主持人拿着文件夹讲解",
      "overall_soundscape: 女主持人的清晰人声",
      "non_diegetic_music: N/A",
    ].join("\n");

    const anchored = anchorReplicaPromptToFirstFrame(prompt);

    expect(anchored).not.toContain("女主持人");
    expect(anchored).toContain("首帧中的主讲人位于中央");
    expect(anchored).toContain("<Picture 1> 中的主体是全片唯一主讲人身份参考");
    expect(anchored).toContain("村民等其他人物保持彼此独立");
    expect(anchored).not.toContain(LEGACY_TEXT);
  });

  it("does not duplicate the new server-side anchor", () => {
    const prompt =
      "integrated_multimodal_description: [Shot 1]\n主讲人绑定：<Picture 1> 中的主体是全片唯一主讲人身份参考。";

    expect(anchorReplicaPromptToFirstFrame(prompt)).toBe(prompt);
  });
});
