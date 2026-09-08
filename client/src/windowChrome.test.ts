import { describe, expect, it } from "vitest";
import indexHtml from "../index.html?raw";
import tauriConfig from "../src-tauri/tauri.conf.json";

describe("desktop window chrome", () => {
  it("keeps the native title bar unnamed", () => {
    expect(tauriConfig.app.windows[0]?.title).toBe("");
  });

  it("uses the Zhongshu brand for the desktop package", () => {
    expect(tauriConfig.productName).toBe("众墅之家");
    expect(tauriConfig.bundle.publisher).toBe("众墅之家");
    expect(tauriConfig.bundle.shortDescription).toBe(
      "众墅之家 · AI 视频创作平台",
    );
    expect(tauriConfig.bundle.windows?.nsis?.startMenuFolder).toBe("众墅之家");
  });

  it("keeps the Zhongshu browser title", () => {
    expect(indexHtml).toContain("<title>众墅之家 | AI 即创</title>");
  });
});
