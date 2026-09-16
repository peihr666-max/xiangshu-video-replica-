# PRELAUNCH-REMEDIATION-20260917 上线评审逐项修复证据

## 请求、范围与基线

用户要求按上线联合评审建议逐项修复，完成后提交 PR。复核 feature `f15cf0c6` 与
main 后，从 `origin/main@1f1c1989` 创建唯一任务分支，再快进到 `e3a8b874`（#129），最后在同分支合入 `6922298b`（#130，集成提交 `aed51fd8`）。
没有把已由 #127 合入的 feature 重复合并，也没有从其他未合 PR 派生。

Owner：Codex / 01a0ab89-d665-77c0-aeb6-5e4abab382df。
Reviewer：执行者代码自检及 PR 门禁；独立人工评审待 PR，不宣称独立复审通过。
分支：`fix/prelaunch-deployment-20260917`；worktree：`.worktrees/PRELAUNCH-REMEDIATION-20260917`。
共享 claim：`PRELAUNCH-REMEDIATION-20260917`。占用检查发现 #130 正在处理 R01，因此复用；该 PR 随后已合并，已整合到本分支。

## 问题闭环

| 原编号 | 处理与验证 | 交付归属 |
| --- | --- | --- |
| R01 首帧/提示词循环依赖 | #130 将确认文案/首帧放在确定性最终提示词合成之前，准备页可以先进入首帧制作；有确认前隐藏最终框、确认后合成的回归。核验代码及既有测试证据，不修改该任务。 | [PR #130](https://github.com/peihr666-max/xiangshu-video-replica-/pull/130)，已合并 main `6922298b`，三门禁通过 |
| R02 配置及文件不可见 | 应用 env_file 使用 `/etc/video-replica/customer.env`；只读挂载 CA/token，缺失源文件拒绝创建目录；一次性引导显式挂载 COS JSON。compose 插值配置独立于候选 SHA。 | 本 PR |
| R03 PG TLS 不匹配 | PG 显式启用 TLS/cert/key，hba 拒绝非 TLS TCP；手册规定 SAN=db、私钥属组/权限、verify-full CA。 | 本 PR |
| R04 健康检查/反代 | API 禁用 Uvicorn 转发头改写；容器通过 Host/HTTPS/单 IP 请求 `/ready`，不绕过安全中间件；bridge gateway 固定且仅信任 /32。 | 本 PR |
| R05 新 SHA 尚不存在 | 使用脚本所在已安装交付包的 compose，候选源码单独 clone；不再在 clone 前要求新 SHA 目录里的 compose 存在。 | 本 PR |
| R06 镜像替换/首镜像标签 | 持久 JSON override 覆盖应用服务/migrate，原模板和密钥文件不变；备份/恢复旧 override，检查恢复就绪。首镜像包含完整 SHA/tree/head，并在构建内核验唯一 head。 | 本 PR |
| R07 发布 Worker 缺失 | #129 已合入，提供 worker-publish、Node、Worker 导入/启动校验及测试；继续保留。 | [PR #129](https://github.com/peihr666-max/xiangshu-video-replica-/pull/129)，main `e3a8b874` |
| R08 复用音频丢失可信时长 | 主线 #126 已保留探测时长、已验证标记与 purpose 校验；不带回旧 feature 实现。 | [PR #126](https://github.com/peihr666-max/xiangshu-video-replica-/pull/126) |

## 实现与回滚说明

部署包与应用 SHA 分开管理：拓扑/TLS/网络变更需先审核安装交付包，应用滚动升级不隐式
改动运行拓扑。稳定 compose env 为 `/etc/video-replica/compose.env`，应用镜像 override
为 `/opt/video-replica-candidate/app-image.override.json`；手工运维也需加载该 override。
升级串行锁防止两轮互相覆盖。旧有可选 Worker 在回滚时恢复，新引入角色保持停止；
恢复服务未就绪则标 `FAILED_ROLLBACK_INCOMPLETE`。数据库回滚仍要求前向兼容，保留 pg_dump。

新文件已登记代码开发清单；没有修改已发布 migration、依赖锁或 CI 门禁。探针脚本从部署包只读挂载，避免旧应用镜像缺少新模块导致回滚失败；升级镜像同时检查 Node，旧基底缺 Node 时需先按手册重建基底。

## 验证记录

- RED：新增 5 项回归全部失败，既有 15 项通过，分别覆盖配置/TLS、探针、候选目录、镜像覆盖与 bootstrap 标签。
- GREEN：Shell 语法检查与扩展部署专项 25 passed；包括 4 种回滚恢复状态，真实 HTTP 探针请求，生产入口拒绝错误 Host/不可信 peer，依赖不可用返回 503。
- 实际 Docker Compose v2 解析成功，确认 10 个角色、应用环境解析、CA/token 只读挂载、PG TLS 命令、探针和固定 gateway。
- 隔离 PostgreSQL 16 实测：CA + 匹配 db 主机名的 verify-full 成功；sslmode=disable 和错误证书主机名均被拒绝。测试证书短期生成，仅用于离线隔离容器。
- 后端唯一一次全量四片结果：617 passed；684 passed / 2 环境失败 / 1 既有 skipped；647 passed / 1 环境失败；548 passed。共 2496 passed / 3 failed / 1 skipped。三个失败均是容器子进程找不到 alembic/app；补齐容器 site-packages 路径后原样补验全部失败 + 最终部署专项 + 音频可信时长回归共 31 passed。既有 skip 为 production 环境 bootstrap 参数化分支，原测试注明 TLS 配置另由 test_db_pg 覆盖；本任务另做了真实 TLS 成功/拒绝实验。唯一覆盖为 2499 passed / 1 既有 skipped，未重复运行完整后端。每片使用独立 PG 物理实例，不共享 fixture。
- Linux 静态门：前端全量 107 文件 / 1634 passed，Biome/TypeScript/E2E lint 通过；Python Ruff、format、mypy（160 个模块）通过；Rust fmt/check 通过（3 条既有 unused 警告）；主线整合后的 Ruff/format/mypy 159 个模块全部通过。探针移至交付包后单独 Ruff/format 及 25 项部署专项再次通过。
- 合入 #130 后：TypeScript 与准备/创作/提示词页面 121 passed；部署/H3 提示词/优化器 50 passed。#130 原提交 `527d76c4` 的三门禁全部通过；主线合并仅一处账本追加冲突，保留双方记录。
- Bootstrap 行为补验：在真实干净 checkout 执行原脚本，以 Docker build 替身捕获构建参数，确认完整 SHA/tree/head 和 head 构建校验参数；未将此替身声明为完整镜像重建。
- 原始本机日志：`outputs/prelaunch-fix-20260917/`；无真实供应商调用、无生产配置或密钥归档。

## §14 交付与限制

- 实现结果：R02—R06 代码及专项验证完成；R01/R07/R08 按问题表复用已有任务成果。
- 验证命令与通过数：见上；不把未执行、跳过、失败门禁记为通过。
- 证据层级：AUTOMATED_VERIFIED（本地全量及失败项补验、主线整合专项）；不提升 staging 或生产等级。
- 安全与可观测性：无入口豁免、无明文 PG TCP 回退；不输出 env 内容/真实凭据；回滚恢复失败有独立状态。
- 数据迁移与回滚：无新增业务迁移，代码通过正常 PR revert 回滚；部署脚本保留前向兼容 DB 策略。
- 外部授权：仅修复、验证和提交 PR；未操作生产、未调用付费 Provider/COS/ZPay，未合并 PR。
- 未测试项：实际 Linux 宿主 Nginx 原始 peer、真实私有 COS/PG HA、完整首装/灰度/故障切换。
  默认单宿主 Compose 与离线 TLS 测试不能替代 staging/真实链路，更不代表 PRODUCTION_GO。
- 提交/PR：实现提交 `8bbf6759`、主线集成 `aed51fd8`；[PR #131](https://github.com/peihr666-max/xiangshu-video-replica-/pull/131) 已提交 Draft，远程三门禁完成后转正式评审。
- 资源清理：本任务容器均 `--rm`；测试容器及其匿名卷已清理，无任务命名卷；未操作其他任务资源。编译产物/缓存均在 E 盘。


```text
任务/工作包：PRELAUNCH-REMEDIATION-20260917 / CW-032 上线评审 R02—R06
Owner / Reviewer：Codex 本任务 / 执行者自检、PR 门禁；独立评审待完成
分支 / 基线 SHA：fix/prelaunch-deployment-20260917 / e3a8b874（初始 1f1c1989 后快进）
上游规格段落：任务账本 §12.7；CW-032 交付包；PostgreSQL 唯一数据库实施与验收规范
改动文件：见代码开发清单同名文件边界与本 PR diff
失败测试或回归锁定：RED 5 failed / 15 passed；GREEN 25 passed；真实 TLS/Compose 验证
实现结果：见问题闭环表；复用 #126/#129/#130，未重复开发在制功能
验证命令与通过数：见验证记录，后端唯一覆盖 2499 passed / 1 既有 skipped；前端全量 1634 passed；主线整合 UI 121 / 后端 50 passed；静态门通过
证据层级：AUTOMATED_VERIFIED（本地全量、失败补验及主线整合专项）
安全与可观测性：TLS-only、入口原始 peer、只读 CA/token、回滚未就绪独立状态
迁移与回滚：无新迁移；代码可通过正常 PR revert；数据库只支持前向兼容回滚
外部授权记录：用户授权修复后提交 PR；未操作真实付费链路或生产
未测试项：生产/HA/COS/实际宿主反代/完整首装与故障演练
Lore 提交 SHA：不适用；实现 8bbf6759，主线集成 aed51fd8；PR #131 已提交，远程检查以当前 head 为准
```


## PR 自检补充：物理备份 TLS 通道

PostgreSQL 的 HBA `all` 数据库关键字不匹配物理复制连接。新增回归先失败，随后显式增加
TLS replication 入口和非 TLS replication 拒绝规则，保留 PITR/pg_basebackup 通道；
HBA 不授予 REPLICATION 权限，仍要求专用备份角色。真实隔离 PG 的 IDENTIFY_SYSTEM
在 verify-full 下成功，明文 replication 被拒绝；普通 SQL 的正确 CA/错误主机名/明文
验证再次通过。最终部署专项增至 26 passed，Ruff/format 通过。这是全量之后新增的 1 项
回归，不计入此前 2499 的全量唯一覆盖数字。随同一 PR 交付，未重复全量后端。
