# BRAND-CORRECTION-20260917 横排品牌和黑底打包图标

## 请求与修复

用户以三张截图明确纠正：页面保持原横排“Logo 众墅之家｜AI 即创”，仅第一排整体放大20%，副标题保持原样；个人中心一致。软件打包图标使用图3现有图案，仅将透明背景改为纯黑。

欢迎页巨图的直接原因是 `CustomerWelcomePage` 仍使用旧 `brand.png` 结构，而上一轮已移除 `.studio-brand img` 的尺寸约束。修复为复用 `BrandIdentity`，并给图片补充固有宽高。共享组件改回横排，覆盖欢迎页、工作台侧栏、创作页顶栏、个人中心。

| 项目 | 原基线 `2f3815e` | 本次 |
| --- | ---: | ---: |
| Logo 图片盒 | 42×36px | 50.4×43.2px |
| 公司及软件名字号 | 13px | 15.6px |
| 图文间距 | 3px | 3.6px |
| 副标题字号 | 12px | 12px |

桌面 SVG 仅新增一个 `#000` 全画布矩形；Logo、文字路径、渐变和布局均未改动。15个桌面PNG与ICO/ICNS从同一SVG重新生成。图3与原128px图标可见内容的像素差为0，详见[图标验证](brand-correction-20260917/icon-validation.md)。不新增依赖，不改变安装身份、业务和数据。

## 开工与文件边界

Owner：Codex / 01a0ad96-8b14-70b3-be6d-2b1eb7316338。Reviewer：独立原生 `correction_review`，APPROVE，零待处理问题。

- 从最新 `origin/main@80fee758` 创建 `fix/brand-correction-20260917` 与独立 `.worktrees/BRAND-CORRECTION-20260917`；已核对远程、worktree、共享claim、PR #136已合并与 #137打包任务的不同文件边界。
- #137合入后保全本任务WIP，快进至 `41fc171d`；两处文档登记冲突逐条保留双方记录。已验证前端及图标修改与此前测试版本完全一致；新增构建合同另跑专项。
- 预览端口5237；本任务完整PG分片隔离端口5561—5564，结束后容器已停止。用户要求打开预览，保留本任务Vite服务和浏览器预览。
- 修改文件为 `BrandIdentity.tsx`、`brand-identity.css`、`CustomerWelcomePage.tsx`、`studio.css`、`RootApp.test.tsx`，以及桌面图标与任务证据。公共账本仅追加本任务记录。

## 验证证据

1. RED：登录前后品牌回归在旧实现失败，欢迎页实际仍为 `/studio/brand.png`。
2. GREEN：RootApp及个人中心36项通过，包含欢迎页图片尺寸与登录后保持一致。
3. `npm run check:static`通过：前端107文件/1676项，Biome、TypeScript、E2E lint、Cargo fmt/check、Ruff/format、mypy。CSS特异性与macOS条件编译dead-code为原有警告。
4. 完整PG四分片通过：633+686+648+560=2527 passed，1项既有skip。使用Node24、uv、Cargo及四个独立PG实例。
5. 独立评审APPROVE；秘密扫描、全差异自检、反向补丁检查通过。新主线构建合同21项专项通过。依赖无变更，依赖审计及Windows安装包以本任务CI结果为准。

## 页面与图标证据

- [工作台](brand-correction-20260917/workbench.png)、[首排局部](brand-correction-20260917/brand-header.png)、[手机导航](brand-correction-20260917/mobile-navigation.png)。
- [个人中心](brand-correction-20260917/customer-center.png)、[手机个人中心](brand-correction-20260917/customer-center-mobile.png)：真实组件、模拟账户；390px视口没有横向溢出。
- [1280px创作页](brand-correction-20260917/creation-1280.png)、[960px创作页](brand-correction-20260917/creation-960.png)：顶部品牌横排，收窄侧栏按原有规则仅显示Logo。
- [DOM尺寸记录](brand-correction-20260917/layout-measurements.json)、[视觉判定](brand-correction-20260917/visual-verdict.json)、[评审结论](brand-correction-20260917/code-review.json)。`visual-verdict` skill未安装，使用原生浏览器截图与DOM实测，并在 `.omx/state/brand-correction-20260917/ralph-progress.json` 保留逐轮判定。
- 个人中心预览使用拦截fetch的模拟账户；[复现页面](brand-correction-20260917/customer-center-preview.html.txt)为纯文本证据，临时client入口已移除。复现时需在开发服务器配置本地 `VITE_API_BASE_URL`，不读取真实账户。

## 交付和回退

当前为本地 `AUTOMATED_VERIFIED`，提交远程后核对本任务CI与桌面构建。未合并、部署或覆盖安装；不将截图或打包成功作为实机升级验收。

没有迁移、数据更改或配置身份变化，可用 `git revert` 回滚本任务提交。源码和图标均保留Git历史。
