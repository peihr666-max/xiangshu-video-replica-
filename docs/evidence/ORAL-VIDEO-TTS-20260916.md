# ORAL-VIDEO-TTS-20260916：视频分身 + 克隆声音 + 文案

## §14 任务记录

```text
任务/工作包：ORAL-VIDEO-TTS-20260916；口播方案收敛及分身库/声音档案视觉重设计
Owner / Reviewer：Codex（本任务执行者）/ 执行者自检；独立 PR 评审待完成
分支 / 基线 SHA：feat/oral-video-tts-20260916 / f0b45b2b2558487adb8981635153cc7afb5da925
上游规格段落：用户本会话选择第二张分身库视觉稿；仅取消数字人口播的照片流程；声音档案保持独立、统一样式
改动文件：PeoplePages、CreationPages、StudioWorkspace、OralJourney、oral.css、api、live、state、review fixtures；materials.py、oral_routes.py 及对应测试
失败测试或回归锁定：音频 CAS 复用缺少可信探测标记、跨用途复用未重验时长的 3 项测试先红后绿；新增上传取消/人物切换/迟到授权/视频唯一来源/旧音频样本隔离回归
实现结果：库优先分身页、上传视频弹窗、独立声音档案；口播固定 TTS；修正素材秒传、可信音频时长及取消后的异步回写
验证命令与通过数：前端 1565 passed；全量原始 2388 passed / 5 failed / 1 skipped，5 项 Git 挂载环境失败全部原样补验通过，唯一测试覆盖合计 2393 passed / 1 既有 skip
证据层级：AUTOMATED_VERIFIED（本任务代码与本地检查）；未作真实供应商链路验收
安全与可观测性：本人/已授权素材确认仍绑定来源；审计员只读；UNKNOWN 保留人工核对提示；不重复自动提交付费任务
迁移与回滚：无数据库迁移；通过本任务 PR 的 revert 回退。历史 IMAGE/AUDIO 任务的领域与 worker 处理保留
外部授权记录：用户授权开发及页面调整；仓库规约授权远程提交/PR；未新增付费供应商、生产部署、合并或发布授权
未测试项：真实上传 COS → 飞影训练 → 克隆声音 → TTS 成片与实际计费；真实音色相似度/唇形质量；Windows 安装包门禁由 CI 验证
Lore 提交 SHA：使用本证据所在 PR 的 head，提交后登记于共享 claim
```

## 交付范围

- 口播分身只允许 MP4/MOV 真人视频创建，最大 50 MB。已就绪的视频分身作为卡片展示，上传/命名/素材授权集中在弹窗中。
- 声音档案保持独立标签。我的声音、试听、确认、使用、创建克隆声音的流程保留，视觉和口播分身统一。声音样本仍为 MP3、5–180 秒、最大 20 MB。
- 数字人口播统一为已就绪视频分身 + 已确认克隆声音 + 已确认文案，复用既有 TTS/create_by_tts 调用链。旧 `oral-audio` 路由进入相同创作页；不再提供直接上传整段音频的口播 UI。
- 仅取消口播中的照片分身入口。形象照片、五视图、场景照、人物置换、首帧与独立 AI 微视频功能保留。
- 口播页面不限制在微视频的 4–15 秒范围内。实际成片时长仍受文案、供应商与既有服务约束，不承诺无限长。

## 上传问题及修正

原口播视频和声音上传函数无条件执行 PUT 与 complete。当 `/resolve` 命中已上传内容并返回 `upload_required:false` 时，应直接使用就绪资产；本任务统一调用 `putMaterial`。

后端音频复用原来沿用客户端时长，并丢失 `audio_duration_verified`，可能使合法样本不可用，也可能用伪造短时长把长音频重新标成声音样本。现在优先选择同一内容对象的可信探测元数据，按真实时长验证新用途；未知/无效探测信息回落到上传探测流程。校验通过后再增加引用计数。

前端使用 AbortSignal 和上下文标记忽略已取消、已切换人物或已卸载组件的迟到响应。重试相同来源与标题沿用幂等键，改变创建内容时生成新键。声音样本仅接受服务端已声明 `voice_clone` 用途的素材。

## 验证

| 检查 | 结果 |
| --- | --- |
| 前端 `npm run check --workspace client`（Biome、TypeScript、Vitest） | 103 文件，1565 passed |
| 最后提示文案调整后的 PeoplePages 专项 | 47 passed |
| 后端口播、素材、CAS 专项 | 205 passed；新增的视频唯一来源模型断言随后由全量覆盖 |
| PostgreSQL 顺序全量 | 2394 项；原始 2388 passed / 5 failed / 1 skipped，耗时 56 分钟；5 项失败均为 Git 元数据挂载问题，原样补验 1 + 3 + 1 passed，详见下文 |
| Ruff check / format | passed，356 文件 |
| mypy app | passed，151 文件 |
| Tauri cargo fmt/check | passed |
| E2E 文件静态检查 | passed，15 文件；未声称浏览器 E2E 全量已跑 |
| Secret scan / git diff --check | passed |
| 浏览器视觉及核心导航 | passed，详见 [视觉报告](oral-video-tts/visual-review.md)（本地根目录 design-qa.md 同步保留）；控制台 error 0 |

全量服务端测试只运行一次，使用隔离 PG16 容器 `oral-tts-pg` 和质量容器 `oral-tts-quality`，均 `--rm`，没有命名卷、没有新建镜像；未占用其他任务 PG。前端预览端口 5216，保留供用户查看。

原始 [JUnit 报告](oral-video-tts/full-backend-tests.xml) 保留 5 项环境失败，没有篡改为全绿。唯一跳过项是原有 `test_bootstrap_accepts_valid_pg_all_environments[production]`，原因是生产 TLS 要求由 `test_db_pg.py` 的纯配置测试覆盖。没有新增跳过，也没有未解决的测试失败。原始前端/后端日志归档到本机 `outputs/oral-video-tts-20260916/`。

### 全量运行中的环境修复

`test_customer_pitr.py::test_pitr_shell_entry_points_are_committed_as_executables` 在全量容器中失败：Windows worktree 的 `.git` 文件包含宿主机路径，Linux 容器无法解析该路径。宿主机真实 Git index 中四个 PITR shell 文件均为 `100755`。没有修改断言或脚本权限；在断网、`--rm` 临时容器 `oral-tts-git-check` 中只读挂载同一源码及主仓库真实 `.git`，通过 `GIT_DIR` / `GIT_COMMON_DIR` / `GIT_WORK_TREE` 指向相同 worktree 元数据，原失败用例复验 **1 passed in 0.45s**。该检查不使用数据库，没有并发第二套 PG 测试；临时容器已自动删除。全量原始结果和补验分别记录，不能将原失败隐藏。

随后 `test_cw060_operator_isolation.py` 的 `test_operator_package_is_reproducible`、`test_operator_manifest_binds_commit_and_single_head`、`test_operator_package_contains_no_business_surface` 也因同一 Git 元数据路径缺失失败。使用相同只读挂载方式原样补验 **3 passed in 54.04s**；没有改源码、测试或运维打包逻辑，临时容器自动删除。

`test_security_contracts.py::test_secret_scan_script_passes_on_repository_contract_surface` 同样依赖 Git 文件列表，在正确挂载中原样补验 **1 passed in 4.90s**；宿主机秘密扫描也通过。五项环境失败分别完成补验，未修改任何业务实现或测试断言。

## 视觉证据

- [分身库桌面](oral-video-tts/avatar-desktop.png)、[分身库局部](oral-video-tts/avatar-region.png)、[视频创建弹窗](oral-video-tts/avatar-create-dialog.png)。
- [独立声音档案](oral-video-tts/voice-desktop.png)、[声音创建弹窗](oral-video-tts/voice-create-dialog.png)。
- [口播创作](oral-video-tts/oral-composer-desktop.png)。
- [手机分身库](oral-video-tts/avatar-mobile.png)、[手机上传弹窗](oral-video-tts/avatar-dialog-mobile.png)、[手机声音页](oral-video-tts/voice-mobile.png)、[手机口播创作](oral-video-tts/oral-composer-mobile.png)。
- [分身空态](oral-video-tts/avatar-empty.png)、[声音空态](oral-video-tts/voice-empty.png)。

两张人物讲解图片是根据所选设计方向生成的 review 示例，仅由 fixtures 引用，真实账号不注入示例分身。截图内状态是 review 测试数据，不代表供应商训练或成片成功。

## 集成与评审

开工时已核对任务登记、共享 claim、worktree、远程分支和开放 PR，从最新 origin/main 建立唯一任务分支。首次提交前 origin/main 为基线 f0b45b2。PR #126 创建后 main 合入 #123（3e120752），本任务在原分支合并该 main；仅两份公共任务记录发生追加位置冲突，已逐项保留双方记录，没有覆盖其他任务成果。

UI-TYPOGRAPHY-BRAND / PROMPT-OPTIMIZE 并行任务涉及同名大文件，本任务仅修改口播相关函数，增加独立 oral.css；未修改其分支、全局排版、提示词编辑器、生成 worker 或计费逻辑。公共业务总账由集成人按真实 PR 状态回填，本证据不把其他工作包改为完成。

本地实现和证据已推送到唯一任务分支，对应 [PR #126](https://github.com/peihr666-max/xiangshu-video-replica-/pull/126)。GitHub 连接器不可用，但指定仓库与所有者后成功使用现有 Git Credential Manager 凭据完成 push 与 GitHub REST 核验，远程认证阻塞已解除。CI 三门禁与独立评审待核验；[PR 正文存档](oral-video-tts/PR-DRAFT.md) 保留实现和验证边界。未合并、部署或对外发布。


收尾资源核验：本任务 PostgreSQL 与质量容器已停止并自动删除；所有补验容器均已自动删除。最终 docker ps / volume 按 oral-tts 前缀检查为空。未删除复用镜像、其他任务容器或其他 worktree；5216 预览服务继续保留。

合并 main #123 后追加复验：前端 Biome、TypeScript 与 103 个测试文件全部通过（1572 passed，25.35s）；秘密扫描、git diff --check 和证据内部链接检查通过。此次主分支增量未改动服务端，沿用本任务已完成的全量服务端证据，不重复执行全量 PG。
