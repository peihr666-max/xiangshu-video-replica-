import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AdminApp } from "./AdminApp";

// CW-019: 管理端独立入口挂载文件。
// 与客户入口 main.tsx 物理分离：客户构建制品（client/dist）不含本文件，
// 管理构建制品（client/dist-admin）不含 main.tsx。断言由
// `scripts/verify_customer_bundle.mjs` 与 `client/src/entryContract.test.ts` 双层保证。
//
// 挂载点 id 与客户入口一致（root），复用同一套 nginx / Tauri 排障经验。

const root = document.getElementById("root");

if (!root) {
  throw new Error("找不到应用挂载节点");
}

createRoot(root).render(
  <StrictMode>
    <AdminApp />
  </StrictMode>,
);
