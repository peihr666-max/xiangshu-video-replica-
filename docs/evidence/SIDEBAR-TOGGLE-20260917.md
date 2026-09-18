# SIDEBAR-TOGGLE-20260917 · 工作台侧边栏折叠/展开开关

## 本次修改清单

用户反馈桌面端左侧栏"固定折叠"不可操作。现状：`studio.css` 在 `@media (min-width: 1100px)` 把 `--studio-sidebar` 写死为 88px 图标栏（纯 CSS，无开关），≤800px 已有抽屉开合（`menuOpen` 状态、遮罩、焦点管理、无障碍标注齐备），801–1099px 为 224px 展开态。对标 ChatGPT / Claude / Notion / Linear 等主流工作台的双态停靠栏模式（收起=图标窄栏、展开=带文字宽栏、明确切换按钮、选择持久化），把既有 88px 图标栏样式从"按屏宽强制"改为"class 驱动 + 用户开关"。

| 修改项 | 修改后的行为 | 主要文件 |
| --- | --- | --- |
| 折叠状态与记忆 | 新增 `sidebarCollapsed` state；初始读 `localStorage["studio.sidebar.collapsed"]`（try/catch 容错），切换时写回；设备级偏好，不上服务端 | `client/src/studio/StudioWorkspace.tsx` |
| 顶栏切换按钮 | 新增 `.studio-sidebar-toggle`（≥801px 显示，≤800px 隐藏）：收起时 aria-label="展开侧边栏"（› 图标），展开时="收起侧边栏"（‹ 图标）；`aria-expanded`/`aria-controls` 同既有无障碍标准。≤800px 抽屉逻辑（`menuOpen`）原样保留 | `client/src/studio/StudioWorkspace.tsx`、`studio.css` |
| class 驱动收起态 | 原 `@media (min-width: 1100px)` 的 88px 图标栏规则整体迁移到 `.studio-shell--sidebar-collapsed`（包裹于 `@media (min-width: 801px)`）；默认态恒为 224px 展开，不再随屏宽强制收窄 | `client/src/studio/studio.css` |
| 平滑过渡 | `.studio-sidebar` width 与 `.studio-main` margin-left 0.18s 过渡，包在 `prefers-reduced-motion: no-preference` 内 | `client/src/studio/studio.css` |
| 收起态悬停提示 | 折叠时导航按钮带 `title` 完整名称；展开态不加（避免冗余气泡） | `client/src/studio/StudioWorkspace.tsx` |
| 契约测试更新 | "宽屏自动收窄"契约测试改写为"默认展开、class 驱动 88px 收起态"新契约 | `client/src/studio/StudioWorkspace.test.tsx` |

不改变：≤800px 抽屉行为、客户中心（`studio-shell--center` 隐藏侧栏与顶栏，切换按钮随之隐藏）、任何服务端代码、数据库迁移、依赖。

## 测试与验证

- 测试先行（RED→GREEN）：先写 2 项新用例（默认展开+收起写入记忆、跨会话恢复+展开清除记忆）确认失败，实现后转绿。
- `src/studio/StudioWorkspace.test.tsx`：100 passed（含既有抽屉用例"展开导航后可直接关闭并恢复入口焦点"不变通过）。
- 前端全量：107 文件 / 1719 passed。
- 可视化验证（受控浏览器 `/review/v1.4`）：默认展开 → 点击收起为 88px 图标栏（任务角标保留、开关变 ›）→ 刷新后保持收起（localStorage 记忆）→ 点击展开完整恢复；四步全部通过，截图存档。
- 完整本地门禁（最终代码 `npm run check:sharded`）：静态门一次通过；分片段两次环境性失败后重跑通过——①占位日志目录未创建导致四分片未启动（REPLICA 证据已记录的同款坑，`mkdir` 后重跑），②另有一轮因并行会话启动的标准 PG fixture 占用 5433，改用 `CI_SHARD_BASE_PORT=5601` 隔离端口段；环境失败均未记为通过。
- 四分片结果：633 + 689 + 654 + 604 = 2580 passed / 1 既有 skipped，`GATE_EXIT=0`，容器已清理，日志 `/tmp/sidebar-shards/`。

## 边界、授权与回滚

- 无真实付费调用、无生产部署、无历史数据修改；用户 2026-09-17 已确认"默认展开并记忆选择"方案。
- 键盘快捷键（Cmd/Ctrl+B）未包含，留待用户后续要求再加。
- 回滚 = revert 单个前端提交；localStorage 键值无迁移语义，回滚后残留键无副作用。

## §14 任务证据

- 任务 / 工作包：用户截图反馈侧边栏固定折叠，要求提供可操作的开合开关并对标同行做法。
- Owner：Claude / 当前会话；Reviewer：执行者自检与 PR 门禁（不冒称独立评审）。
- 分支 / main 基线：`feat/sidebar-toggle-20260917` / `0ce6ed28`（GitHub API 核验与本地一致；直连 fetch 遇 HTTP2 错误）。
- worktree：`.worktrees/SIDEBAR-TOGGLE-20260917`；共享 claim 在 Git common dir `codex-task-claims/SIDEBAR-TOGGLE-20260917/claim.json`。
- 开工查重：`gh pr list` 无开放 PR；worktree/认领登记/共享 claim 无同题占用；改动文件与在制任务（含 `studio.css` 相关的 REPLICA-SUBJECT-LAYOUT 已合并件）无交集。
- 文件边界：仅 `StudioWorkspace.tsx`、`studio.css`、`StudioWorkspace.test.tsx` 与本任务账本/证据文件；无新业务模块、依赖、迁移。
