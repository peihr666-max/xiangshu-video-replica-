const LEGACY_ALL_PEOPLE_ANCHOR =
  "全片人物身份、服装和配饰以首帧为准，后续不得恢复源人物外观。";

const FIRST_FRAME_PRESENTER_ANCHOR = [
  "主讲人绑定：<Picture 1> 中的主体是全片唯一主讲人身份参考；所有分镜里的主持人、主讲人、讲解者和口播者均指首帧中的主讲人。",
  "首帧中的主讲人，其性别、面部、发型、身形、服装和配饰只能取自 <Picture 1>；不得恢复源视频主持人的外观、性别或音色。",
  "陪衬人物规则：村民等其他人物保持彼此独立，不得复制 <Picture 1> 主讲人的脸、服装或身份。",
].join("\n");

const PRESENTER_ROLE_PATTERN =
  /(?:女性|男性|女|男)?(?:主持人|主讲人|讲解员|出镜人)/g;

/**
 * Compatibility guard for prompts compiled by an older cloud API.
 *
 * A replacement first frame can show a different person from the source
 * presenter. Retained source labels such as “女主持人” then contradict
 * Picture 1 and can make H3 restore the source identity. Keep the source
 * action and composition while rebinding the performer to Picture 1.
 */
export function anchorReplicaPromptToFirstFrame(prompt: string): string {
  if (!prompt.trim() || prompt.includes("主讲人绑定：<Picture 1>")) {
    return prompt;
  }

  const protectedRole = "__FIRST_FRAME_PRESENTER__";
  let anchored = prompt
    .replaceAll("首帧中的主讲人", protectedRole)
    .replace(PRESENTER_ROLE_PATTERN, protectedRole)
    .replaceAll(protectedRole, "首帧中的主讲人");

  if (anchored.includes(LEGACY_ALL_PEOPLE_ANCHOR)) {
    return anchored.replace(
      LEGACY_ALL_PEOPLE_ANCHOR,
      FIRST_FRAME_PRESENTER_ANCHOR,
    );
  }

  const sectionStart = "integrated_multimodal_description: [Shot 1]";
  if (anchored.includes(sectionStart)) {
    anchored = anchored.replace(
      sectionStart,
      `${sectionStart}\n${FIRST_FRAME_PRESENTER_ANCHOR}`,
    );
  }
  return anchored;
}
