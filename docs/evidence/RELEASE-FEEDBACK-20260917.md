# RELEASE-FEEDBACK-20260917 生产升级记录

状态：部署成功，运行检查通过；完整业务 UAT 和整体生产验收等级不变。

## 授权、版本与范围

用户于 2026-09-17 明确要求通过已打开的宝塔终端，从项目 Git 仓库拉取代码并部署。Owner 为 Codex 会话 `01a0ae08-ff4b-77a0-9854-aed665b96d00`；独立 native reviewer 对发布差异、任务排空、回调放行和恢复顺序进行了只读复核。

- 原线上版本：`80fee758da1632d86dfaaad566c3ac3fa9290f8a`。
- 本次版本：`9ec6f566199a8b93cae9c7df51572dd5a25c1ffc`，源码树 `1d8b8f001a75467f854d9520e45b1f369cdee074`。
- [PR #139](https://github.com/peihr666-max/xiangshu-video-replica-/pull/139) 已于 `2026-09-17T08:56:05Z` 合并。
- 精确版本的 [主线 CI](https://github.com/peihr666-max/xiangshu-video-replica-/actions/runs/35202368413) 和 [桌面构建](https://github.com/peihr666-max/xiangshu-video-replica-/actions/runs/35202368324) 均成功；Secret scan、Linux quality gate、Windows Tauri and NSIS 均成功。
- 本批业务改动与验证详见 [截图反馈证据](REPLICA-SUBJECT-LAYOUT-20260917.md)。此次部署包含主要人物置换、响应式布局、侧栏与 Logo、输入框高度、声音格式和克隆结果稳定性、首尾帧加号卡片及参考素材预览等已合并修改。
- 相比原线上版本，没有数据库迁移、Python 依赖、锁文件、部署脚本或维护脚本变更。
- 本记录在最新 `origin/main@9ec6f566` 创建的独立 worktree / 分支 `RELEASE-FEEDBACK-20260917` / `chore/release-feedback-20260917` 维护。开工核对远程 PR、分支、worktree 和共享 claim；旧生产部署固定于 80fee75 且已成功，不重复接管其管理员登录验收。

## 发布保护与执行

服务器直接从公开 GitHub 仓库拉取本次 commit。遇到 TLS 中断和完整检出超时后，以 HTTP/1.1 重试，并通过硬链接复用原版本的不可变 Git 对象；从 GitHub 补齐本次差异，最终 HEAD、tree 和干净工作区均核对一致。未使用第三方镜像或未经验证的压缩包。

旧 e57e1d8 源码目录改为 `server/client/scripts/deploy` sparse checkout，释放不参与运行的已跟踪资料；Git 对象、旧源码历史、数据库、用户素材、备份及回退镜像保留。新源码同样按需检出。构建完成后只移除本次可由锁文件重建的 `node_modules`，最终磁盘可用 `4319280 KiB`，使用率 89%。

部署使用已审阅且未改动的 `deploy/customer-git-rollout.sh`，SHA256 为 `45d98debe814eec7235e6b0dcce74af1816f28dd521e3e498bf0c465dc5652c7`；显式指定服务器现有 `/opt/video-replica-candidate/compose.yaml` 及原环境配置，保留当前服务拓扑。

部署前、冻结后、停止 Worker 后三次活动检查均通过：生成、声音/数字人克隆、分析、文案、提示词、采集、导入、发布及未来 120 分钟内定时采集/发布和采集重试的运行阻断计数为 0。另有 5 条历史首帧 `SUBMISSION_UNCERTAIN`，无有效租约，PENDING/RUNNING 为 0；代码确认它们不会被 Worker 自动执行，未重试、删除或改写这些记录。

在已备份的本站 Nginx 配置中临时冻结 API 写请求，返回 503 和 Retry-After；GET/HEAD/OPTIONS 及 WeChat 支付通知精确路径放行，ZPay GET 回调保持可用。语法检查通过后 reload，等待排空，停止此前正在运行的六个 Worker。外层恢复脚本负责重新启动这些 Worker，避免原发布脚本遗漏已停止的 optional roles。发布完成后恢复原 vhost，逐字节比较一致，语法复验及 reload 成功；无持久维护开关或代理信任配置变更。

## 现场验证

- 发布时间标识：`20260917-094324` UTC；发布脚本 `SUCCESS`，外层退出码 `0`，`WRITE_FREEZE_REMOVED`。
- 新镜像：`video-replica-rehearsal-app:9ec6f56-git`。名称沿用历史，不代表运行环境。
- `api-1`、`api-2`、`worker-1..4`、`worker-viral-1`、`worker-publish-1` 共八个应用容器 revision 全部等于完整发布 SHA；全部 running，重启计数 0；两个 API 均 healthy。
- 双 API 经宿主 18001 / 18002 和既有可信代理链检查 `/ready`，均返回 `status=ready, database=postgresql, storage=cos`。未扩大信任代理名单。
- 数据库 head 前后均为 `20260917T1000_publish_records`。
- 公网 `/health`、`/live`、`/customer`、`/admin/` 均 HTTP 200，TLS 正常校验。
- 客户 JS `/assets/index-CHp1YDhP.js`、CSS `/assets/index-nyfPVjce.css` 均 HTTP 200 且 Content-Type 正确。
- 管理 JS `/admin/assets/admin-Bn4JYszX.js`、CSS `/admin/assets/admin-BI4gRw6w.css` 均 HTTP 200 且 Content-Type 正确。管理源码未改，本次仍从同一源码版本构建。
- 冻结解除后，无副作用的不存在 API 路径 POST 探针恢复 HTTP 404，未继续返回维护 503。
- 在新 Worker 中用 FFmpeg 生成 6 秒合成 M4A/WMA/WAV/WMV 样本，调用实际 `normalize_audio_to_mp3`，四种均成功生成并校验 MP3；临时样本自动清理。未调用声音供应商或付费 API。
- 浏览器真实打开客户工作台及登录入口正常，无观测到的 error/warn。未登录访问创作页按既有规则进入登录页；登录后的创作与付费业务 UAT 未执行。
- 既有维护 service `Result=success, ExecMainStatus=0`，timer active；维护脚本本次无差异，未更改配置或重跑清理。
- 数据库 dump 经发布脚本 `pg_restore --list` 检验；数据库、客户站点、管理站点三份备份 SHA256 现场复验全部 OK。

## 服务器证据与回退

- 发布日志：`/opt/video-replica-candidate/deploy-git-9ec6f56-20260917-094324.log`。
- 发布状态：同目录 `deploy-git-9ec6f56-20260917-094324.status`。
- 包装脚本、日志、退出码：同目录 `release-9ec6f56-wrapper.sh`、`.log`、`.exit`。
- 只读活动 SQL 及最后聚合结果：同目录 `release-9ec6f56-activity.sql`、`release-9ec6f56-activity-latest.json`，不包含业务 ID。
- Nginx 原件及校验：同目录 `nginx-before-9ec6f56.conf`、`nginx-before-9ec6f56.sha256`。
- 完整备份：`/opt/video-replica-candidate/backups/git-9ec6f56-20260917-094324/`，含原 Compose、镜像覆盖、原镜像名、迁移 head、数据库 dump 及两套站点归档。
- 旧镜像 `video-replica-rehearsal-app:80fee75-git` 保留。回退应在排空任务后恢复备份中的镜像覆盖和静态站点，再逐服务验证；数据库结构未变，不得用部署前 dump 覆盖上线后的业务数据。

## 验证边界与文档交付

本次服务端和网页发布完成。已安装桌面客户端的前端资源仍需安装对应新版客户端，不会因服务端升级自动替换。没有执行真实支付、付费生成、真实声音克隆或账号凭据修改；管理员登录的既有反馈不在本次范围内，完整业务 UAT 与整体 PRODUCTION_GO 不自动核销。

精确业务版本已通过主线全量门禁；本任务只新增部署记录及账本链接，不修改业务、依赖、迁移或 CI。文档仅做链接、差异和秘密检查，后续文档 PR 门禁据实登记；已有两项 moderate 开发依赖告警未因本次发布被修复，不声明依赖零漏洞。文档可用正常 git revert 撤销，不改变现网版本。

文档交付自检：新增本地证据链接存在，差异格式检查、运行面秘密扫描和新增文档凭据模式扫描通过；完整暂存补丁的反向 apply 检查通过。独立评审发现的 §12 摘要缺项已补齐，并更新任务账本头部发布状态；无剩余文档阻断。
