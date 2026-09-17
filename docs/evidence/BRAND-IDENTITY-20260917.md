# BRAND-IDENTITY-20260917 品牌尺寸与桌面图标

## 请求与实现

按用户截图放大 Logo/公司名，桌面图标加入 Logo 与两行“众墅之家”“AI 即创”，个人中心统一使用前端的金色 Logo。

工作台侧栏、创作页头部和用户中心共用 `BrandIdentity`：Logo 64×64，公司名 24px，软件名 18px。侧栏原为 42×36、名称 13px。移除三处重复尺寸规则。桌面 SVG 精确复用现有品牌路径，文字转为矢量路径，PNG/ICO/ICNS 从同一源生成。无新依赖，不修改产品安装名、标识符或数据路径。

## 占用、基线与边界

Owner：Codex / 01a0ad96-8b14-70b3-be6d-2b1eb7316338；Reviewer：独立原生 `brand_review`。

- 分支 `fix/brand-identity-20260917`，worktree `/Users/honor.pei/Documents/订单项目/.worktrees/BRAND-IDENTITY-20260917`。
- 查重覆盖本地/远程分支、worktree、共享 claim、开放 PR #135 与近期合并 #134；无重复品牌任务。首次 fetch 网络失败，GitHub API 核验 main `7a328513`，后续 fetch 成功。
- #135 正式合入 main 后保全 WIP，快进至 `2f3815e0650852981333d8d62d548cc83cc717fc`。品牌 JSX 自动合并；代码清单的两份独立登记均保留。没有带入其他任务提交。
- 预览 5237，PG 分片 5561—5564；没有真实 Provider、支付、云写入、发码或部署。

## 验证

1. RED：新增用户中心回归测试，旧实现实际使用 `/studio/brand.png`，期望 `/studio/logo-mark.svg`，失败已复现。
2. GREEN：用户中心、Studio 与构建入口专项 120/120。
3. 新 main 基线 `npm run check:static` PASS：前端 107 文件 / 1675 项，Biome、TypeScript、E2E lint、Cargo fmt/check、Ruff check/format、mypy 通过。保留原有 CSS 警告和 macOS 条件编译下的 Rust dead-code 警告。
4. 旧基线 PG 四分片 2508 passed / 1 既有 skip；新基线四分片全部通过：633 + 686 + 648 + 560 = 2527 passed，1 既有 skip。
5. 秘密扫描、`git diff --check` 通过。依赖未变；依赖审计、客户构建及 Windows 安装包按仓库规则由 PR CI 验证。
6. 独立评审 APPROVE：42 个文件，0 个待处理问题。前端融合及布局 PASS；桌面文字放大并加细描边，可读性问题关闭，8 个最终资产 SHA 与证据一致。

初轮前端全量出现 CharacterLibrary 场景恢复及 AnalysisWorkspace F-06 失败，单项均可通过；F-06 在旧 main 临时副本整文件也复现。未越界修改在制复刻模块；#135 正式合入后完整静态门已通过。命令使用已安装 Node 24、uv、Cargo、ffmpeg。

## 视觉证据

- [工作台](brand-identity-20260917/workbench.png)、[390px 导航](brand-identity-20260917/mobile-navigation.png)。
- [用户中心](brand-identity-20260917/customer-center.png)、[390px 用户中心](brand-identity-20260917/customer-center-mobile.png)：真实组件、模拟账户；内容宽度等于 390px，无横向溢出。
- [960px 创作窗口](brand-identity-20260917/creation-960.png)、[1280px 创作窗口](brand-identity-20260917/creation-1280.png)：无裁切、无覆盖控件；88px 导航隐藏文字并保留图形。
- [视觉判定](brand-identity-20260917/visual-verdict.json)、[图标生成记录](brand-identity-20260917/icon-build.md)。`visual-verdict` Skill 未安装，以浏览器截图和 DOM 尺寸人工判定；同份 JSON 保存在 `.omx/state/brand-identity-20260917/ralph-progress.json`。
- 用户中心 QA 拦截 fetch，不涉及真实账户；临时入口已移出 client，保留[纯文本复现页](brand-identity-20260917/customer-center-preview.html.txt)，不会进入产品。

## 状态与回滚

AUTOMATED_VERIFIED（本地）：实现、静态检查、前端与 PG 全量及独立评审完成，远程 PR/CI 待回填。未合并、部署或覆盖已安装客户端。桌面图标需随重新构建的安装包更新；源图完成不等于实机安装验收。

无数据迁移和业务状态变更，回滚使用本任务提交的 `git revert`；提交前检查反向补丁能干净应用。
