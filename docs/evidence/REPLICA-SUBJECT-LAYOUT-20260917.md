# REPLICA-SUBJECT-LAYOUT-20260917 · 主体置换与工作区布局修复

## §14 任务证据

- 任务 / 工作包：同一批截图反馈及追加要求；多人视频主要人物置换、预览自适应、共用紧凑侧栏及移除创作页重复 Logo。
- Owner：Codex / 01a0ae08-ff4b-77a0-9854-aed665b96d00。
- Reviewer：独立 native agent 交叉评审，结果收尾追加。
- 分支 / main 基线：`fix/replica-subject-layout-20260917` / `41fc171d5daae909d515c9add1649bff948a70c6`。
- worktree：上级 `.worktrees/REPLICA-SUBJECT-LAYOUT-20260917`。共享 claim 在 Git common directory 的 `codex-task-claims/REPLICA-SUBJECT-LAYOUT-20260917/claim.json`。
- 开工查重：前置 #135 已合并，Secret / Linux / Windows 均通过；唯一开放 #138 是品牌修正，其共享 studio.css 仅第 122 行字号，与本次底部侧栏段无重叠。已读取登记、worktree、分支和本机 claim。默认 Git HTTPS fetch 超时，HTTP/1.1 重试成功；GitHub API 与 origin/main SHA 一致。
- 文件边界：见代码开发清单同名记录；无新业务模块、依赖、数据库迁移或 Provider 通道。

## 根因与修复规则

1. 首帧入口仍调用旧单人门禁，按全片任意 shot.person_count > 1 拒绝，而该计数包括背景工人。改为仅拒绝不可读/损坏分析结构；允许多人及旧分析缺少人数。无需因人数重新拆解已有项目。
2. 场景造型提示词仍写“唯一人物”。保留确认源帧所在 shot.subject，三种参考模式统一只重构主要人物；其他人身份、衣服、数量、位置、动作及遮挡保持，不能复制目标外观到旁人。
3. 图片 AI 质检已由 #130 取消，未恢复。候选仍单次生成三张、quality=None、人工选择；不增加自动补图或额外模型调用。旧记录保持可读。
4. 拆解页来源条继承 max-content / 720px 下限，超过所在网格列。移除这项旧宽度；实际媒体元数据决定左列，右列填余宽；长来源文字换行，窄屏纵向堆叠。
5. 用户追加：所有工作台页面复用创作页紧凑侧栏；创作内容页头移除重复 Logo，搜索/通知/用户入口沿用正常页头位置。不调整 #138 的品牌资产。

## 简化与回归计划

删除人数硬拒绝与过时注释；提取已有主要人物提示语供现有三分支共用，不新增人物识别服务；复用现有 VideoPreview 元数据和响应式侧栏样式。先以回归锁定问题再修改，不大规模清理仍被其他流程使用的质检模块。

- RED：前端 2 项新用例分别复现缺失比例回调、左右列不消费媒体比例；后端 6 项复现多人/旧数据及提示词缺口。
- 专项：前端预览 + 创作页 125 passed；后端 Apilio 57 passed；隔离 PG 5567 的多人/旧数据与人工确认 4 passed。
- 静态：前端完整 1677 passed、Biome / TypeScript / e2e lint / cargo fmt+check 通过；服务端 ruff / format / mypy 159 文件通过。初次总脚本在末段因 PATH 缺 uv 停止，已按相同命令补验服务端；追加侧栏变更后重验结果另记。
- 全量 PostgreSQL：2548 passed / 1 既有 skipped；4 个独立容器端口 5561—5564，均通过且已清理；日志 `/tmp/replica-subject-layout-shards/`。首次日志目录不存在导致未启动 pytest，创建目录后重跑，不能将环境失败记为通过。
- 浏览器：1440 / 1024 / 390，真实本地合成视频 9:16 / 16:9 / 1:1 及长文件名；检查比例、列边界和全页宽度。全部九组合通过。12 个工作区宽屏统一 88px 侧栏，无重复内容区 Logo，390px 手机打开导航后切换素材库通过。详见同目录下 `replica-subject-layout-20260917/` 测量与截图。

## 边界、授权与回滚

- 本次为普通代码修复、测试和远程 PR 交付；没有真实付费生成、生产部署、合并授权或数据更改。
- 主体选择依赖现有拆解 subject 和生成模型遵循指令；没有新增人脸框选/追踪，未验证真实多主体遮挡情况下的模型精度。
- 源画面候选的历史语义推荐评分与生成图片 AI 质检是不同路径；本次不恢复、不扩展任何质检调用。
- 正式出图效果和安装客户端必须在合并部署后单独核验。纯本地样例不代表用户该视频的真实供应商验收。
- 回滚：正常 PR revert；无 schema / 账务变更，保留全部历史版本与人工选择。
- 当前等级：AUTOMATED_VERIFIED（本地）；独立评审及远程 CI 收尾记录见后文；不宣称上线。

## 浏览器缓存补验

真实1秒合成样片复现 loadedmetadata 在 React handler 绑定前完成，videoWidth/videoHeight 已就绪但仍显示默认竖框。新增回归先失败，再在 effect 读取已就绪元数据并按 source/ratio 去重。补验前端专项 126 passed；九种浏览器画幅/窗口组合全过。没有以手动伪造 metadata 事件代替真实浏览器解码。

## 视觉交付

[竖屏原比例与右侧分镜](replica-subject-layout-20260917/1440-portrait.png)、[横屏自适应](replica-subject-layout-20260917/1440-landscape.png)、[手机布局](replica-subject-layout-20260917/390-landscape.png)、[工作台共用紧凑边栏](replica-subject-layout-20260917/shell-workbench.png)。截图使用本地合成视频与显式 DEV 样例，只用于布局验收。

## 最终本地门禁

`npm run check:static`（Node 24 + uv PATH）完整通过；最后缓存兜底后，前端 Biome + TypeScript + 107 文件 1680 项全过。服务端 Ruff / 373 文件格式 / Mypy 159 文件通过；四片 PostgreSQL 合计 633 + 688 + 648 + 579 = **2548 passed / 1 既有 skipped**。秘密扫描通过，无依赖变化；依赖审计与 Windows 安装包以 PR 的标准 CI 门禁为准。既有 Rust dead-code、CSS specificity、jsdom scrollTo、Starlette 弃用警告如实保留。

该任务未启动新的 AI 质检或付费图像调用。生成图片质量仍由人工选择；没有声称已经部署到用户当前客户端。

## 独立评审修复

独立 reviewer 首轮指出换源旧尺寸竞态与旧任务指纹未升级两项。前者新增 currentSrc=A / src=B 回归先红，补 `currentSrc === src` 后三文件 225 项通过，九种真实视频布局矩阵再次通过。后者为两条 appearance fingerprint 统一加入主要人物置换合同版本 3，确保新请求不会命中旧规则候选 checkpoint；历史资产不删除。首帧专项 58 passed、独立 PostgreSQL 5 passed，Ruff / format / Mypy 通过，容器已清理。复审结果见评审文件。

## 提交核验

已阅读完整代码差异；与任务目标逐文件核对，未增加依赖和付费调用。`git diff --check`、秘密扫描、任务文档链接检查通过；反向补丁 dry-run 通过，无数据迁移，正常 revert 可回退。远程提交前以 HTTP/1.1 fetch 核对 `origin/main..HEAD` 无外来任务提交。图片展示和品牌变更未混入另一任务 #138。

最终增量基于完整前端 1680 / 后端 2548（1既有skip）的全量基线；评审修复后另跑前端 225、后端 58 + PG 5，全过。最终远程 CI 将在同一 PR head 对完整集合重新取证。

独立复审：APPROVE，两项阻断已关闭，无剩余问题；见 [评审记录](replica-subject-layout-20260917/code-review.json)。
