# PUBLISH-QR-REUSE-20260915：个人中心双端扫码添加

## 任务与授权

用户要求从 GitHub 查找并复用实现，确认 Windows 客户端登录状态留本机、网页端无需安装客户端且登录状态加密保存服务器。基线 `6de015ce7473daa327e6db732f0604d6a5dd7ba1`；独立分支 `fix/publish-qr-reuse-20260915`。Owner 当前 Codex 任务；Reviewer 待 PR，当前为执行者自检。

## 根因与实现

原个人中心只打开桌面官方窗口，没有二维码回传；浏览器路径禁用。抖音、小红书扫码面板需要新版 DOM 定位；视频号已使用微信跨域 `qrconnect` iframe，实测发现旧 `img.qrcode` 隐藏而新版 `img.js_qrcode_img` 可见。

复用 MIT [Social Auto Upload 固定提交](https://github.com/dreammis/social-auto-upload/tree/0012d2c355f88f683cc38dde2a2db209e14091bc)。完整许可证、源路径与改动说明在 [VENDOR-NOTES](../../server/app/publishers/vendor/social_auto_upload/VENDOR-NOTES.md)。使用标准 Playwright，不导入上游反检测补丁。

Windows 在官方框架内提取已加载图片，跨域消息校验父页面、来源、frame 和图片类型；Rust 只返回受限图片/状态和已验证账号元数据，Cookie 留本机。原取消、解绑与独立账号 WebView2 资料目录设计保留。

网页通过认证 POST NDJSON 接收短期二维码，连接负责浏览器生命周期。PostgreSQL 协调全局 4 个/每用户 1 个/5 分钟名额；保存前重新检查原工作台会话、账号归属和有效扫码名额。只有平台返回账号 ID、昵称才保存 Fernet 加密状态，列表和流不暴露状态内容。重复同平台账号更新，重登不同账号拒绝覆盖；取消与解绑按用户隔离。

## 验证记录

| 检查 | 结果 |
| --- | --- |
| Linux `npm run check:static` 原命令，独立源码快照 | PASS；102 前端文件 / 1465 测试；Biome、TS、秘密扫描、E2E lint、cargo fmt/check、Ruff/format、mypy 150 文件全部通过 |
| `pytest server/tests/test_publish_browser.py -q`，真实专用 PG | 11 passed；覆盖加密、不回传、去重、隔离、取消迟到写、重登错误账号、变更属主、名额过期 |
| 全量 PostgreSQL 回归 | 首次 2168 passed / 18 failed / 1 既有 skip；修复后受影响模块分组复验 121、27、42 passed，覆盖全部 18 个失败；最终唯一覆盖 2186 passed / 1 既有 skip，不把首次全量写成全绿 |
| 服务端真实官方取码 | 抖音 28202、视频号 12894、小红书 9042 字符 PNG Data URL；仅记录长度，不保存二维码或凭据 |
| 桌面 JS 在 Chromium 官方页面和 iframe 中运行 | 三平台 `qr_ready`，图片长度分别 2898 / 75510 / 4850；不是 WebView2 安装包验收 |
| 分片覆盖清单 | 99 个测试模块全部覆盖，新模块与共用 fixture 的账号测试同 shard-1 |
| 查重后的网页认证兼容 | Biome、TypeScript 通过；API/二维码脚本/流/个人中心 4 文件 196 passed，含新增 2 个会话请求测试 |
| 远程 CI、Windows NSIS、手机扫码确认 | 未执行，不能记作通过 |

本地日志归档位置：仓库上级 `outputs/publish-qr-reuse-20260915/validation/` 中的 `publish-qr-linux-static.log`、`publish-qr-pytest-full.log`、`publish-qr-recheck.log`、`publish-qr-accounts-recheck.log`、`publish-qr-archive-recheck.log`。Linux 检查快照源由 `git ls-files` 枚举当前任务源码而创建，避开 Windows worktree `.git` 路径和宿主 node_modules 链接，使用相同包/锁文件；未修改检查规则。开发过程曾遇到 Docker 重启和系统库误选，恢复独立容器并选择已登记 `customer_v3_test` 后专项通过。前端新增测试的 fixture ID 断言已修正；旧隐藏微信二维码定位问题有回归测试。

全量失败修复：许可证改随前端公共资产打包以满足桌面资源约束；追加迁移遵循既有仅 PG 守卫；新 head 的 CW056 真实 schema 指纹同步；历史导入工具允许新增的空 PG 专用表且继续拒绝非空状态覆盖；旧发布 Worker 守卫限定原协议表。依赖 Git 的测试使用保留原文件执行位的独立 Linux 快照复验。未放宽测试或重复运行第二次全量。

## 工作区重复检查

用户追加要求核对并避免重复工作。检查 10 个 worktree、共享认领、未提交文件、公开 PR 及改动内容：当前唯一开放 PR 为 [#109](https://github.com/peihr666-max/xiangshu-video-replica-/pull/109)，负责会话、参考视频和成片联调；本工作区负责个人中心扫码。公共 API、测试和账本文档存在交叉，具体业务改动不同。查出联调分支新增 `web-session:` 认证标记，因此扫码请求补齐相同 `X-Customer-Web` 请求头及双模式回归，不复制其会话实现。

细滚动条是本任务较早完成的独立样式分支，仅入口和共享 CSS，与扫码或 PR #109 无重复。历史整改、照片授权、账务等交付已有合并 PR #108、#106、#103、#107、#102；旧目录保留不是继续开发证据，不重复推送。扫码保持此唯一在制工作区，未移动或覆盖另一工作区独有改动。

## 部署与回滚

新增 revision `20260915T1200_browser_accounts`，只新增云账号与扫码名额表；旧账号/发布协议不变。Chromium 和系统依赖由基础镜像脚本安装，本次 Python 依赖变更需走基础镜像发布，不能绕过现有 rollout 的依赖检查。详见[部署与验收](../发布账号扫码部署与验收.md)。未对当前在用客户端或公网服务部署。

应用回滚可保留新增表；downgrade 会删除新增加密账号，须明确确认数据可删除。真实手机登录和状态复用须由账号持有人在实际运行环境验证。

## §14 证据模板

```text
任务/工作包：PUBLISH-QR-REUSE-20260915 / 个人中心双端扫码维护增量
Owner / Reviewer：当前 Codex 任务 / 待 PR 评审
分支 / 基线 SHA：fix/publish-qr-reuse-20260915 / 6de015ce7473daa327e6db732f0604d6a5dd7ba1
上游规格段落：用户本任务连续指令；Windows 本机保存和网页服务端加密保存确认；AGENTS 标准工作流
改动文件：见客户版代码开发清单-V3.md 的本任务冻结文件边界
失败测试或回归锁定：原无二维码接口与旧选择器；新增 DOM、流协议、PG 账号隔离测试；可见微信图片回归
实现结果：双端扫码 UI；三平台官方取码；加密云账号；取消/去重/重新登录与用户隔离
验证命令与通过数：Linux check:static 1465；全量加受影响模块修复复验唯一覆盖 2186 passed / 1 既有 skip；详见上表原始结果
证据层级：AUTOMATED_VERIFIED；未标真实手机登录链路或远程门禁完成
安全与可观测性：凭据不回传、Fernet 密文入库、相同事务会话围栏、异常不输出浏览器凭据/URL
迁移与回滚：追加 20260915T1200_browser_accounts；旧应用可忽略新增表；删除表会清除新增账号
外部授权记录：用户要求 GitHub 复用及双端扫码；没有公网部署或真实发视频授权
未测试项：手机确认、真实账号状态重启复用、Windows NSIS、远程三门禁、部署网络下额外平台验证
Lore 提交 SHA：待本任务实现提交；不伪造 PR 或合并状态
```
