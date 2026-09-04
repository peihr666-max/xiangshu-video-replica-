import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
    // 浏览器端联调：同源代理到本地后端，避免跨源凭据请求
    // （管理端 fetch 带 credentials: "include"，跨源时需要
    //  allow_credentials，开发期统一走同源代理更简单）。
    // 控制面路由（内部通道）依赖反代注入 X-Control-Proxy-Token，
    // 本地联调由该代理以开发令牌代为注入（须与后端
    // CONTROL_PROXY_TOKEN_DIGEST 配对）。
    proxy: {
      "/api": {
        target: process.env.VITE_DEV_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        headers: {
          "X-Control-Proxy-Token":
            process.env.VITE_DEV_CONTROL_PROXY_TOKEN ?? "dev-proxy-token-1234",
        },
      },
    },
  },
  envPrefix: ["VITE_", "TAURI_ENV_*"],
  build: {
    target:
      process.env.TAURI_ENV_PLATFORM === "windows" ? "chrome105" : "safari13",
    minify: process.env.TAURI_ENV_DEBUG ? false : "oxc",
    sourcemap: Boolean(process.env.TAURI_ENV_DEBUG),
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    restoreMocks: true,
    // Node >= 25 ships the Web Storage API enabled by default, and that
    // native globalThis.localStorage makes the jsdom environment skip
    // installing its own Storage (window keys already present on globalThis
    // are skipped), leaving tests with a method-less localStorage stub.
    // Disable the native implementation in test workers so jsdom's Storage
    // is used on every supported Node version; on Node 24 (CI) the flag is a
    // harmless no-op against an already-off default.
    execArgv: ["--no-experimental-webstorage"],
  },
});
