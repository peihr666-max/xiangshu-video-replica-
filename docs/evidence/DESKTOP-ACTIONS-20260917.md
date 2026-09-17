# GitHub Windows 与 macOS 自动打包

## 任务记录（任务账本 §14）

- 任务/工作包：DESKTOP-ACTIONS-20260917；用户要求在 GitHub 自动编译 Windows 与 macOS 桌面应用。
- Owner / Reviewer：Codex `01a0ad0d-ffc8-7ef3-8c52-f2f3b92b85d5` / 原生代理 `publish_frontend_diagnosis` 独立复核 APPROVE。
- 分支 / 基线 SHA：`feat/desktop-actions-20260917` / 最新 `origin/main@2f3815e0650852981333d8d62d548cc83cc717fc`；独立同名 worktree。
- 上游规格：用户此次构建请求；CW-020 客户制品边界、CW-024 内测签名渠道与现有三门禁。
- 改动文件：`.github/workflows/desktop-build.yml`、`client/src-tauri/tauri.macos.conf.json`、`scripts/release/collect-desktop-artifacts.mjs`、既有 `server/tests/test_build_contracts.py`、README 与任务账本。
- 失败测试或回归锁定：归档脚本、workflow 与 macOS overlay 缺失时新增正向测试失败；拒绝路径另检查具体原因与没有产物，禁止以无关运行错误冒充通过。
- 实现结果：三个原生 runner 构建 Windows x64 / Mac arm64 / Mac x64；上传单一安装包及 SHA256、实际 Git SHA、API 地址、版本、签名渠道清单。缺包、多包、空包或无效输入拒绝归档。
- 验证命令与结果：见下文；未完成的远程构建不记为通过。
- 证据层级：AUTOMATED_VERIFIED（本地完整门禁）；GitHub 三平台实际构建待执行。
- 安全与可观测性：只读 contents 权限、固定 Action SHA、checkout 不保留凭据；输入经环境变量和既有校验传入；产物只包含指定安装包和元数据，不上传工作区或签名材料。
- 迁移与回滚：无数据库或业务配置迁移；撤销本任务提交可移除新工作流和覆盖配置，原 `ci.yml` 三门禁保持不变。
- 外部授权记录：本次 GitHub 构建和下载产物属用户请求；没有合并 PR、公开 Release 或部署服务端。
- 未测试项：GitHub 实际构建与下载待执行；真实 Windows / Intel Mac 安装与业务账号验收不由编译通过替代。
- Lore 提交 SHA：由所在提交及 PR 列表追溯，GitHub 构建 manifest 记录实际检出的源 SHA。

## 开工证据与差额

已成功 fetch --prune；远程开放 PR 只有品牌 #136，不与打包文件交叠。原 main CI 只生成连接 `staging.example.invalid` 的 Windows 合同安装包，保存于临时 runner 目录，没有可下载 Artifact；本次新增独立分发工作流，保留原有质量门及签名发行入口。

远程确认扫码修复 #134 已于 2026-09-17 03:19:36 UTC 合并为 `7a328513`；本次最新 main 已包含它。主线之后又合入复刻流程 #135。本任务没有执行上述合并，源码合并记录不证明对应服务端已经部署。

## 工作流行为

- `workflow_dispatch` 可填写 API HTTPS 根地址，默认 `https://video.zszhj.cn`；首次工作流尚未进入 main 时通过本任务分支 push 运行。
- 合入 main 后，main 的桌面源码与构建配置变更触发新包。只改文档不重复打包；没有 PR 与 push 双重触发。
- 使用固定 `windows-2025`、`macos-15`、`macos-15-intel`；显式 Rust target，三平台互不取消。
- 直接调用既有 Tauri CLI，无新增项目依赖。Windows 使用原客户 installer hooks；Mac overlay 提供 app/DMG、icns 与 ad-hoc 签名，随后检查代码签名完整性、Mach-O 架构和 DMG。
- Artifact 保存 7 天，缺文件视为失败，名称含平台/运行编号/重试编号。GitHub 权限与配额失败应真实报告，不静默改为不可下载的临时归档。
- `manifest.json` 记录版本、平台、Git SHA、API 地址与测试签名渠道；SHA256 用于用户下载后核验。原应用标识、数据目录和服务端均不修改。

## 验证记录

开发期日志保存在忽略目录 `.release/desktop-actions/`。

- `npm run check:static` 通过：秘密扫描、前端 Biome/类型检查、107 个文件的 1674 项测试、E2E lint、Tauri 格式与编译检查、Ruff、373 个文件格式检查、159 个文件 mypy。
- 完整 PostgreSQL 四片测试通过：633 + 686 + 648 + 573 = 2540 passed，1 项既有 TLS skip；任务独立端口 5591–5594，测试后已正常清理容器。日志 `pytest-shards.log` 与 `shards/ci-shard-*.log`。
- 构建合同专项 21 passed；新增行为先红后绿，归档测试实际运行 Node 与临时安装包。
- 官方 actionlint v1.7.12 校验新增工作流通过；新增归档脚本 Node 语法和 Biome 检查通过；文档相对链接与 `git diff --check` 通过。
- 原生代理 `publish_frontend_diagnosis` 完整独立评审 APPROVE：无阻断项，实际 GitHub runner 构建与安装体验仍需单独验证。
- 远程运行 URL、Artifact ID、下载校验及三门禁状态在本任务 PR 按实际运行结果登记；本提交不预先宣称远程通过。

官方参考：[Runner 标签](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job)、[macOS 签名](https://v2.tauri.app/distribute/sign/macos/)、[Artifact Action](https://github.com/actions/upload-artifact)、[手动运行要求](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)。
