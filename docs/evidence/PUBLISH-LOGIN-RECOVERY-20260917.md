# 发布账号扫码恢复、macOS 路由与抖音身份确认修复

## 任务记录（任务账本 §14）

- 任务/工作包：PUBLISH-LOGIN-RECOVERY-20260917；个人中心发布账号维护增量。
- Owner / Reviewer：Codex 会话 `01a0ad0d-ffc8-7ef3-8c52-f2f3b92b85d5` / 独立原生代码评审代理及主执行者自检。
- 分支 / 基线 SHA：`fix/publish-login-recovery-20260917` / `3932d528ee4e3570ef40d2220b145eec0f5ae633`；从开工时最新 origin/main 建立独立同名 worktree。
- 上游规格段落：用户报告取不到二维码、官方窗口扫码后账号不回写且不关闭；既有《发布账号扫码部署与验收》与 PUBLISH-QR-REUSE-20260915。
- 改动文件：`client/src/studio/localPublishAccounts.ts`、`LocalPublishAccountsPanel.tsx` 及 `cloudPublishAccounts.test.ts`、`MainPages.test.tsx` 发布账号段；`server/app/publish_browser_engine.py` 和 `server/tests/test_publish_browser.py`；部署验收文档、代码映射、认领、任务账本、证据索引及本文。
- 失败测试或回归锁定：Mac Tauri 被误认为可调用 Windows 原生账号能力，新增用例先失败；连续读取失败暂停检测后点击官方窗口，新增用例先失败。各专项修复后通过，详见下文。
- 实现结果：Windows Tauri 保留原生命令；Mac 和其他非 Windows 环境复用现有认证云端扫码、加密保存接口。打开官方窗口成功后恢复当前会话轮询；会话 generation 与 login ID 隔离迟到响应。抖音兼容整数/字符串成功码，在同源创作者后台主动核验身份并防止迟到失败响应覆盖，只有有效身份才沿用既有加密保存流程。
- 验证命令与通过数：`npm run check:static` 成功（完整前端 1646 项）；评审补测后最终账号相关两文件 103 项通过；追加抖音修复后的最终完整 PostgreSQL 四分片 2508 passed / 1 既有 TLS skip。日志保存在 worktree 的 `.release/publish-login-recovery/`，不含真实平台登录状态。
- 证据层级：AUTOMATED_VERIFIED；不声明 STAGING_VERIFIED、REAL_CHAIN_VERIFIED 或 PRODUCTION_GO。
- 安全与可观测性：沿用当前 Bearer/Cookie 认证和服务端用户隔离；平台 UA 仅用于能力选择，Rust 的 Windows 能力门不变。无新依赖、凭据、后端接口或密文格式变化。开窗失败仍显示可重试错误。
- 迁移与回滚：无数据库迁移；可撤销本任务提交恢复原有前后端逻辑。回滚不会改写既有账号数据。
- 外部授权记录：用户授权排查、开源源码核对及 macOS 编译；本任务没有真实发布、付费调用、线上数据库或生产部署操作。
- 未测试项：抖音服务端补丁部署后的真实手机确认与账号保存、Windows WebView2 异常恢复后自动保存与关窗、重启及解绑的完整实机验收。同版 Mac 视频号添加成功由用户实测，不替代上述验收。
- Lore 提交 SHA：由本文件所在提交及 PR 的提交列表追溯；远程交付状态另记。

## 缺陷与验证边界

### 最新用户实测反馈

用户在 Mac 客户端手机确认抖音登录后，账号未保存，二维码位置变成白色页面片段；同一客户端的视频号两个账号已正常显示“云端已连接”。截图与用户确认仅记录这一真实范围，不复制账号 ID/昵称到仓库。这排除了普遍的云端持久化与客户端列表故障，但不代表抖音链路通过。已编译客户端的路由修复不足以处理该平台特有缺陷，同任务追加服务端修复与回归。

只读复现确认：抖音 `status_code="0"` 被现有解析器拒绝，而供应商发布器支持整数和字符串；身份监听的后到失败响应可以覆盖先前有效身份；没有收到匹配的官方身份请求时没有主动复核。源码缺陷已确定，是否为本次真实账号的具体响应形态仍需服务器修复后再验。

1. 原 `canUseLocalPublishAccounts()` 只检查 `isTauri()`；macOS 被路由到原生账号命令，但 Rust `official_window()` 明确拒绝非 Windows。修复复用已经存在的网页云端流，不增加 macOS Cookie 导出实现。
2. 原界面连续三次读状态失败后停止轮询；点击“打开官方窗口”只聚焦窗口，没有恢复检测。账号保存和关窗由后续 `check_local_publish_login` 触发，因此轮询停止后不会执行。
3. 平台 DOM、身份接口和额外验证仍依赖实站；这些修复不能证明用户遇到的每种平台故障都已消除。现有 Windows 登录态导出失败和服务端同步失败按现有错误/重试路径处理，不冒称本次补齐所有发布链路。
4. 抖音主动复核使用 Playwright `BrowserContext.request`（与扫码浏览器共享 Cookie），请求固定官方 user/info、5 秒超时、零重定向；3 秒限频，异源页面不探测，await 后重验当前来源。取消仍释放浏览器，APIResponse 始终 dispose。只记录固定阶段、HTTP 状态/异常类型或布尔诊断，不记录 URL 参数、响应体或登录状态。依据：[Playwright 官方说明](https://playwright.dev/python/docs/api/class-apirequestcontext)。
5. 独立诊断在当前公开 DOM 中确认首个 selector 和 `aria-label="二维码"` 是同一张实际二维码，未选中引导图，因此本次不改选择器。截图白卡和箭头的具体来源仍未实测，不将它作为根因；confirmed 后未导航的理论窗口、空昵称的既有契约留真实复验，不为未证实情形扩展登录判定。

## 复用源码核对（2026-09-17）

扫码来源是 MIT [dreammis/social-auto-upload](https://github.com/dreammis/social-auto-upload)，本仓固定提交与核查时 main 均为 `0012d2c355f88f683cc38dde2a2db209e14091bc`。

- [抖音扫码实现](https://github.com/dreammis/social-auto-upload/blob/0012d2c355f88f683cc38dde2a2db209e14091bc/uploader/douyin_uploader/main.py#L150-L330)：定位/保存二维码，通过 `qrcode_callback` 回传图片，等待登录成功，保存 `storage_state`，最后关闭浏览器。提取失败时仍允许在有头浏览器中扫码。
- [小红书扫码实现](https://github.com/dreammis/social-auto-upload/blob/0012d2c355f88f683cc38dde2a2db209e14091bc/uploader/xiaohongshu_uploader/main.py#L94-L312)：切换扫码面板、提取或截图二维码、回调图片、等待登录、保存并验证状态、关闭浏览器。
- 本仓 `publishers/vendor/social_auto_upload/VENDOR-NOTES.md` 明确只复用二维码定位和面板切换；身份确认、超时、隔离、加密及账号回写由本仓实现。上游保存状态文件不等于自动写入本仓账号表。
- 实际抖音发布器来源是另一个自有仓库 `phlong026/douyin_publisher`，接收既有凭据并检查/发布；当前内联文件没有二维码登录入口。小红书虽已有扫码账号管理，当前 `publish_delivery.deliver_via_api()` 没有小红书发布分支，不能据此宣称已接通自动发布。

以上是代码审阅证据，未运行第三方项目，也未因研究引入新依赖或整套发布器。

## 自动化日志

- `macos-red.log`：Mac 能力路由先红；`macos-green.log`：云端与 Windows 路由 9 项通过。
- `red-main-pages.log` → `green-focused.log`：暂停后开窗恢复先红后绿。
- `green-main-pages-file.log`：页面文件 92 项通过；独立评审另验两文件 101 项通过。
- `check-static.log`：完整静态门成功，前端 107 文件、1646 项通过；含 secret、Biome、TypeScript、E2E lint、Tauri fmt/check、ruff、format、mypy。
- `review-regressions.log`：补充两条评审用例后，账号段 17 项通过，Biome/TypeScript 通过；`final-frontend-targeted.log`：最终两个账号相关测试文件 103 项通过。
- `douyin-red.log`：4 failed / 1 passed；`douyin-race-red.log`：补充竞态及取消测试 3 failed。修复后 `douyin-green-targeted.log`：8 passed，`douyin-publish-browser-full.log`：完整账号浏览器专项 22 passed；独立真实 PG fixture 5561，结束已停止。`douyin-static.log`：Ruff、格式与完整 mypy 159 模块通过。新增服务端修复后另跑最终四分片，结果单独登记，先前全量不冒充最终代码证据。
- `pytest-shards-final.log` 与 `final-shards/`：用户新实机反馈触发抖音服务端增量后，最终再次全量验证；618 + 686 + 648 + 556 = **2508 passed / 1 既有 TLS skip**，四片全绿，fixture 正常清理。最终完整 Ruff/format/mypy 与秘密扫描再次通过。
- `pytest-shards.log`：完整 PostgreSQL 四分片成功，分别 618、679、648、556 passed，合计 2501 passed / 1 既有 TLS skip。使用原脚本的忽略目录副本，仅替换脚本定位与容器名前缀；原分片清单、覆盖门、测试命令不变。容器 `publish-login-recovery-20260917-shard0..3`，端口 5561–5564，与并行任务物理隔离，测试后正常关闭。
- 客户及管理前端构建通过，`verify:customer-bundle` 通过（客户禁止项 0 命中，管理阳性对照 6/6）。本地未运行 npm audit，遵循仓库约定交 PR CI；没有依赖文件变更。

## macOS 构建

`VITE_API_BASE_URL=https://video.zszhj.cn`，Tauri 使用 `--locked --no-default-features`、Apple Silicon arm64、临时 app/dmg 配置和 ad-hoc 签名。优化编译及 `.app` 打包成功，系统打包脚本在 DMG 界面定制阶段退出失败；保留失败日志，卸载本任务残留镜像后，使用 Apple `hdiutil create -srcfolder ... -format UDZO` 将已签名 `.app` 与 Applications 快捷方式打包为 DMG。未改变源代码、CI 或签名检查。

这是一份本地测试构建，未公证；不安装替换用户已有客户端。真实扫码与完整 macOS 功能支持范围仍按上述未测试项记录。

DMG SHA256 为 `a1a07b3803a9b77a1aa8d6f886fb764cd090abacdd13d8a5b3d23a6e19ba582c`，`codesign --verify --deep --strict` 与 `hdiutil verify` 均通过。用户自行安装后的 `/Applications` 可执行文件哈希与本次构建一致；随后由用户提供的视频号添加成功证据据此归到同一客户端，抖音服务端修复尚未部署。

## 独立评审

首次评审未发现生产逻辑缺陷，指出两项测试覆盖缺口：旧开窗响应抵达新扫码会话、不支持原生窗口时 action_required 隐藏开窗按钮。两项均补齐；独立复核重跑两条用例、Biome 和 diff 检查通过，最终 APPROVE。没有新增依赖、迁移、同步阻塞循环或扩大列表读取范围。

新增抖音服务端修复由另一独立只读代理复核：字符串/布尔成功码、被动/主动并发响应、异源导航、限频、取消及释放均通过，8 项专项、Ruff/Mypy/diff 检查通过，结论 APPROVE。视频号与小红书既有分支不变。当前实机证据仅视频号添加成功；抖音必须在服务端更新后由持有人再验。
