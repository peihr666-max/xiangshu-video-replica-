# REPLICA-SUBJECT-LAYOUT-20260917 · 主体置换与工作区布局修复

## 本次修改清单（提交前整理）

本次按同一会话的 7 组反馈交付，代码分成主要人物与工作区、声音克隆、创作素材交互三个逻辑提交。没有数据库迁移、新依赖、真实付费调用或生产部署。

| 修改项 | 修改后的行为 | 主要文件 |
| --- | --- | --- |
| 主要人物置换 | 不再因背景人物拦截首帧；三种参考模式只替换 shot.subject，保留旁人。更新合同指纹，避免复用旧规则候选。继续三张候选、人工确认，不恢复图片 AI 质检 | `server/app/first_frames.py`、相关首帧测试 |
| 自适应预览与公共布局 | 使用视频真实比例安排左右区域，长来源文字换行；窄屏上下排列。各页面统一紧凑侧栏，创作内容页头去掉重复 Logo | `VideoPreview.tsx`、`studio/CreationPages.tsx`、`studio/StudioWorkspace.tsx`、`studio/creation.css`、`studio/studio.css` |
| 文案与提示词输入 | 文案、脚本和提示词多行编辑区的原高度/行数翻倍，保留纵向拉伸；只读内容与单行标题不扩大 | `ScriptEditor.tsx`、`FirstFrameSelection.tsx`、`studio/PromptEditor.tsx`、`studio/ReplicaPreparation.tsx`、相关 CSS |
| 克隆声音格式 | 支持 MP3、M4A、WAV、WMA、WMV、AAC、FLAC、OGG、OPUS、AIFF/AIF、AMR；服务端校验有效音轨、5–180 秒和 20 MB，Worker 提取首音轨并转 MP3 | `studio/live.ts`、`studio/PeoplePages.tsx`、`api.ts`、`server/app/materials.py`、`server/app/media_tools.py`、`server/app/oral_worker.py` |
| 克隆结果稳定性 | 轮询只更新对应声音、忽略迟到旧结果；试听与操作区预留稳定尺寸，结果出现时卡片高度和滚动位置不变 | `studio/PeoplePages.tsx`、`studio/live.ts`、`studio/oral.css` |
| 文／图生视频素材 | 首尾帧显示更大的图片卡片；点“＋”选择素材库或本地上传，不再在卡片下另放上传按钮；可更换、移除 | `studio/CreationPages.tsx`、`studio/creation.css` |
| 参考生视频素材 | 添加区上置、已选素材下置；单击打开图片/视频/音频预览，关闭或 Escape 后返回原卡片焦点且不滚动 | `studio/CreationPages.tsx`、`studio/creation.css` |

验证结果：本地完整静态门通过；前端 107 文件 / 1716 项通过；后端四片 2580 项通过、1 项既有跳过；评审后 PostgreSQL 39 项及焦点专项 2 项补验通过。宽屏/中屏/手机布局、实际本地音视频播放及声音状态变化均已测量；独立最终评审 APPROVE，0 剩余问题。

交付边界：主要人物识别沿用现有拆解 subject，没有新建框选或追踪系统；真实多人遮挡场景的供应商出图精度尚未进行付费验收。WMV 按含音轨容器处理，无音轨文件明确拒绝。原口播及参考音频合同保持原有校验。新提交必须以 PR 当前 head 的 Secret / Linux / Windows 门禁为准；未合并、未部署。

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


## 同会话追加反馈：文案、声音与素材输入

1. 文案与提示词：共享 PromptEditor/ScriptEditor、首帧提示词、复刻准备、文案工坊、AI 视频、口播文案、发布描述按原有 rows/height/min-height 翻倍，保留纵向手动缩放。标题、人物资料、支付设置不变。
2. 声音格式：克隆入口接受 MP3、M4A、WAV、WMA、WMV、AAC、FLAC、OGG、OPUS、AIFF/AIF、AMR。浏览器无法探测时由服务端 complete 严验容器签名、有效音轨、5–180 秒与 20 MB；Worker 提取首音轨并转为 MP3 后提交既有 Hifly 接口。完整口播/参考音频仍沿用原合同。只模拟 Provider 接口，不发真实付费请求。
3. 结果跳动：VoicePanel 轮询原先每 6 秒触发全工作区和钱包重读，且播放控件替换按钮触发换行。改为只更新当前声音且内容未变保持原状态引用；每个声音独立请求序号隔离迟到结果。预留稳定试听/确认两槽，桌面 44px、窄屏两行100px；全局刷新保留用户提交/确认后的单次操作。
4. 文/图生视频：首尾帧桌面大卡片、窄屏单列，“＋”直接打开素材库或本地上传选择；上传成功在同位置显示大图，保留更换/移除。仍遵守原 T2V 开放能力与费用校验。
5. 参考生视频：添加区在上方，已添加素材在下方；单击预览图片/视频/音频。序号、用途与移除保持独立。

### 增量回归与视觉证据

- 声音格式前端 RED 24项失败；实现后 API/live/PeoplePages 279 passed。声音状态局部更新 RED 1失败；修复后 PeoplePages/live 118 passed。全量发现1项旧尾帧按钮入口断言，更新为“添加尾帧→从素材库选择”后 StudioWorkspace 98 passed。
- 声音布局第一次浏览器检查暴露通用 flex 规则覆盖新 grid，控件切换有4px高度差；修复 specificity 与44px控制槽后，1440/1024/390三档、6个声音卡片切换前后高度和scrollTop均相同（桌面166.39px、手机222.39px）。使用显式DEV数据注入，未修改业务数据。
- 输入框按实际浏览器几何验收，不保留只匹配CSS源码的镜像测试。发布页1024宽度发现旧双列最小宽度超出可用空间，增加响应式单列，保留1440双列。
- 后端先跑纯格式/容器、损坏文件、无音轨WMV、转码失败不触达Provider、旧MP3与PG上传合同专项；最新全量门禁结果在收尾补充。
- FFmpeg 输入限制依据[官方协议文档](https://ffmpeg.org/ffmpeg-protocols.html#Protocol-Options)，仅本次克隆输入显式限制本地协议；同一时间保留原媒体通道默认行为。参考[FFmpeg命令文档](https://ffmpeg.org/ffmpeg.html)执行音轨映射和转码。无新依赖。


### 追加反馈最终验证

- 最新 `npm run check:static` 完整通过：Biome、TypeScript、前端 **107 files / 1716 passed**、e2e lint、cargo fmt/check、Ruff、373 文件格式及 Mypy 159 文件。既有5条CSS specificity及5条Rust dead-code警告保留，无新增静态错误。
- 同次后端四片全量：**2580 passed / 1 既有 skipped**（633+689+654+604），独立5561–5564容器均自动清理；评审后删除上传完成阶段重复完整解码，另以独立5567专项复验 **CW058 26 passed + oral 13 passed**，容器清理。完整ffmpeg转换只在租约Worker执行一次，complete保留轻量校验。
- 独立评审指出旧测试未真实消费更新；现新增 useState harness 验证原位 READY、停止轮询、无关引用不变，deferred旧请求晚于新READY不能覆盖，单条状态仅为demo签URL；PeoplePages/live **120 passed**，并已纳入最终1716全量。
- 参考预览使用本地合成媒体实际解码播放：视频640×360、1秒，播放时间0.001→0.806；音频5秒，0.000→0.763。关闭后两类媒体均暂停、节点卸载，0控制台错误。没有用真实Provider或业务数据。
- 视觉：[输入区](replica-subject-layout-20260917/textarea/1440-copy.png)、[首尾帧大图卡片](replica-subject-layout-20260917/video-frame-cards/1440-video.png)、[参考素材上下布局](replica-subject-layout-20260917/reference-materials/1440-reference-materials.png)、[声音结果稳定布局](replica-subject-layout-20260917/voice/1440-ready.png)。各子目录含实际几何和交互JSON；[综合判定](replica-subject-layout-20260917/feedback-visual-verdict.json)通过。
- 已存在 PR：[#139](https://github.com/peihr666-max/xiangshu-video-replica-/pull/139)。首批 c687432 的 Secret/Linux/Windows 三门禁已通过；本次追加反馈提交后以新head的门禁结果为准，尚未合并、部署或运行付费验收。

边界补验：本地合成180秒WAV转为MP3通过，未因编码封装边界误拒绝上限样本。声音代码单独提交 `6973b2e`；UI布局和本批证据按独立逻辑提交。

最终交互补验：参考素材预览关闭按钮与 Escape 均将焦点返回原缩略卡，`preventScroll` 保持滚动位置；1440/390 两档无横向溢出或控制台错误。该评审 LOW 已修复，新增专项 2 passed，Biome 与 TypeScript 通过。

独立最终评审：**APPROVE，0 剩余问题**；追加反馈全范围及最后焦点修复均已复核，见 [评审记录](replica-subject-layout-20260917/feedback-code-review.json)。

## 当前主线同步与远程验证

最终功能提交 `b1117919` 的 [CI 35197192700](https://github.com/peihr666-max/xiangshu-video-replica-/actions/runs/35197192700) 全部通过：前端1716、PG2580/1既有skip、浏览器E2E 4、Linux Rust 20、Windows Rust 27，客户/管理端构建与Windows NSIS成功。秘密扫描通过；依赖审计按既有门禁阈值通过，但保留 Vitest / @vitest/mocker 共2项中等级告警（GHSA-82fw-gwwq-j7x9），本次没有依赖变化，不做跨范围强制升级。

验证期间品牌修正 #138 已进入 main `023da4a2`，同步到本分支。唯一冲突为任务账本头部与末尾的独立新增记录，逐条保留两任务真实历史；公共 studio.css 自动合并，品牌字号与本任务侧栏段互不覆盖。没有更改供应商或数据库行为。同步后重新核验静态门，远程最终head检查以PR实时状态为准。

同步后完整静态门全部通过，前端107文件/1717项；独立合并评审APPROVE、0问题。1440侧栏88px、390展开265px，品牌组件全页仅1处且内容区0处；两档参考素材上下顺序、单击预览和关闭焦点归还均通过，无溢出或控制台错误，见 [同步视觉复验](replica-subject-layout-20260917/main-sync/visual-verdict.json)。
