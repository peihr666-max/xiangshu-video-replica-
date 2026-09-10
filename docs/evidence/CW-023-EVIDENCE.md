# CW-023 — 补齐下载取消、失败与支持平台差额（W3 代码与测试增量）

## Task Information

| Field | Value |
| --- | --- |
| **Task ID** | CW-023 / W3「补齐下载取消、失败与支持平台差额」 |
| **Owner** | 桌面负责人 + 前端 QA（ZCode 会话 sess_0d6c74dc，用户授权流水线执行者） |
| **Reviewer** | CodeReview 自检（push 前）+ PR CI 三门禁 + owner 评审 |
| **Branch / Base SHA** | `feat/customer-v3-cw023-download-cancel-failure` / 开工基线 `origin/main@1ad1f31495`（＝CW-022 #22 squash 合并后） |
| **Worktree** | `E:/众墅之家爆款短视频创作/.worktrees/CW-023-download-cancel-failure`（claim: `.git/codex-task-claims/CW-023/claim.json`） |
| **Date** | 2026-09-11 |
| **Evidence Level** | `AUTOMATED_VERIFIED`（真实签名实机下载与断网/写盘故障实机场景由 CW-046 按原边界提供） |
| **前置** | CW-015（已合入）、CW-020（#18 已合入）；平台范围按 CW-002 已签认决议（客户桌面仅 Windows 10/11 x64） |

## 能力边界（DoD 要求的明确登记，不得默改）

| 能力 | 状态 | 承载 |
| --- | --- | --- |
| 保存框取消（弹框阶段用户取消） | **支持**：`choose_video_download` 返回 None → 前端 `{status:"cancelled"}`，不报成功、无任何文件落盘 | `video_downloads.rs` windows_dialog（code==0 → None）+ `api.ts` `if (!destination) return {status:"cancelled"}` |
| 下载中取消（写盘已开始） | **不支持（登记为能力边界）**：`cancel_video_download` 对已开始下载返回 Err「下载已开始，请等待下载完成」；前端仅在未开始（anchor click 失败等）时调用 cancel 清理授权 | `Registry::cancel`（started → Err，既有测试 `approved_download_is_one_use...` 锁定）+ `api.ts` catch 分支（`if (!started)`） |
| 原生保存/打开目录的平台范围 | **仅 Windows**（CW-002 签认：客户桌面仅 Windows 10/11 x64）：非 Windows 显式拒绝「此保存功能目前仅支持 Windows 桌面端」，不静默降级 | `choose_video_download` / `open_video_download_folder` 的 `#[cfg(not(windows))]` 分支 |
| 外部对象请求 | 携带 `credentials: "omit"`，不向供应商传递客户 Bearer（既有合同，复验保持） | `api.ts` `fetchGenerationResultBlob` |

## 本任务差额补齐（RED→GREEN）

**核心差额**：下载失败后残留文件无人清理——WebView 写盘失败（断网/磁盘满/中途
取消）或产出零字节文件时，用户选定的保存路径上留下损坏的"可播放外观"mp4。

实现（`video_downloads.rs` `Registry::finish`）：

1. **成功规则下沉到状态层**：`finish` 自身校验「真实存在 + 位于预留路径 + 非空」
   （原先非空校验只在 `on_download` 事件回调，状态层可被绕过）；规则与事件回调
   的检查形成防御纵深。
2. **失败残留清理**：`success=false` 且事件路径与预留路径一致时，尽力删除该残留
   （该路径由 WebView 为本次下载创建/覆写，用户已在保存框确认覆写语义）；删除
   失败（如被占用）不改变已上报的 `DOWNLOAD_FAILED` 结果，供用户手动处置。
3. **误报路径不误删**：路径不匹配的失败报告不删除任何文件（未知状态保守处理）。

测试（容器内真实 cargo test，先红后绿）：

- 新增 `a_failed_download_cleans_up_its_partial_residue`（真实临时文件夹具）：
  部分写入失败 → 残留被清理；零字节"成功" → 判失败并清理；真实成功 → 文件保留；
  路径误报 → 不删除任何文件。**RED 证明**：还原旧实现后该测试 FAILED
  （`panicked at src/video_downloads.rs:638`），新实现 GREEN。
- 既有 2 测试夹具升级（意图不变）：`approved_download_is_one_use...` 与
  `finished_status_survives_missing_event_delivery` 的成功分支改用真实非空
  临时文件（虚构路径在新成功规则下不再合法）。
- 容器内全量：`cargo test --locked --lib video_downloads` → **10 passed / 0 failed**
  （rust:1 + tauri Linux 系统依赖镜像；本机无 Rust 工具链）。

## 前端复验（零代码变更）

`TaskRecordsPanel.tsx` 下载链路复验确认既有确定性恢复完整：pending 锁防重复
点击（`pendingDownloadsRef`）、`cancelled/saved/started` 三态精确渲染、失败统一
「下载失败，请检查网络和保存位置后重试」、`VideoDownloadUnconfirmedError` 单独
文案。`api.ts` 上传通道（XHR 进度/abort/超时/401 会话失效）与外部对象
`credentials:"omit"` 均为既有合同，复验保持。`ContentPages.tsx` 经由共享 api
函数获得同一保障，无独立差额。

## 验证记录

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| Rust 专项 | 容器内 `cargo test --locked --lib video_downloads` | 10 passed / 0 failed（RED→GREEN 见上） |
| rustfmt | 容器内 `rustfmt --check`（rust:1 stable 组件） | 通过 |
| client 套件 | `npm run check --workspace client` | 本任务前端零变更；CI Linux 门禁同一套件为准 |
| secrets / ruff / mypy | 仓库脚本 | push 前执行（见提交记录） |
| Windows NSIS 制品构建与解包检测 | CI windows-nsis job | 以 CI 三门禁为准 |

## 未测试项（诚实披露）

- 真实 WebView2 下载中断（断网/磁盘满）到 `Finished{success:false}` 的端到端
  行为需要实机；本任务以状态层单元测试锁定清理语义，实机归 CW-046。
- 下载中取消仍为登记的能力边界（不支持），未实现中断写盘；如产品后续要求，
  须另立任务（涉及 WebView2 下载取消 API 与部分写入事务化）。

## 回退方式

PR squash 合并前：放弃分支。合并后：单提交 revert；行为变化仅为「失败残留被
清理」与「成功判定更严格（要求真实非空文件）」，无数据迁移与不可逆项。
