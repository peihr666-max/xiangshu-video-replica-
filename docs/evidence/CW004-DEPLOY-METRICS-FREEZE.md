# CW-004 — 部署主线、PG 资源与验收指标冻结（已签认设计主线+验收目标基线，owner 2026-09-09；数值定标 defer GA/staging）

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-004 冻结实际部署、PG 资源与验收指标 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-09）；Reviewer：独立复核子代理 + 待运维负责人/QA 签认 |
| 分支 / 基线 SHA | `feat/customer-v3-cw04-deploy-metrics` / 基线 `origin/main@b211095` |
| 上游规格段落 | V3 清单 §4 CW-004、§8 可量化阈值；`docs/客户版测试与验收规格-V3.md` §5/§8/§9；`docs/客户版部署与灰度手册.md` §1/§4–§9 |
| 改动文件 | `docs/evidence/CW004-DEPLOY-METRICS-FREEZE.md`（新增） |
| 失败测试或回归锁定 | 不适用（决策与静态核验层） |
| 实现结果 | 见 §1–§6 |
| 验证命令与通过数 | 逐项静态核对部署资产与规格文档（依据列给出文件/行号） |
| 证据层级 | 决策与静态核验（签认前不得视为完成；未定参数不以文档示例冒充实测） |
| 安全与可观测性 | §5 指标/告警项沿用 T37 与规格 §8.3 |
| 迁移与回滚 | 纯文档，可整体回退 |
| 外部授权记录 | 无 |
| 未测试项 | 目标机实际容量/负载/阈值定标（§6 未定项清单） |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 1. 交付主线冻结（复用既有部署资产，本项不重写抽象方案）

正式交付主线 = **客户桌面包 + 云端后端**，类生产最小拓扑（`docs/客户版部署与灰度手册.md` §1 已定义，此处冻结为唯一主线）：

| 角色 | 归属 | 依据 |
| --- | --- | --- |
| TLS/LB 入口（标准 HTTPS 443） | `deploy/nginx/customer.conf.example` | 手册 §1 |
| API ×2（无状态） | `video-replica-api@8001`、`video-replica-api@8002`（systemd 模板） | `deploy/systemd/video-replica-api@.service` |
| Worker ×4 | `video-replica-worker@1..4` | `deploy/systemd/video-replica-worker@.service` |
| PostgreSQL 16 唯一读写主端点（HA） | `deploy/postgres/`（migrate + PITR 五件套） | `deploy/postgres/migrate.sh`、`pitr-*.sh` |
| 私有 COS bucket（禁公开读，短期签名仅服务端生成） | 应用配置（active_storage_provider=cos） | 手册 §1 |
| maintenance timer ×1（单实例防重复扫表） | `video-replica-maintenance.timer` | `deploy/systemd/` |
| 备份/PITR timer | `video-replica-pitr-backup.timer`（PG 物理备份 + 连续 WAL） | `deploy/systemd/`、`deploy/postgres/pitr-backup.sh`；注意 `video-replica-backup.timer` 为历史 SQLite 专用备份，**不属于交付主线**，正式部署 SQLite backup=0（CW-032 完工标准），其退役归 CW-040/CW-060 |
| 集中日志/指标/P1 告警 | T37 接入（手册 §4） | 手册 §4.1–4.3 |

- 发布方式：`deploy/customer-git-rollout.sh --commit <40位SHA>` 按 SHA 构建镜像。
- **已登记差额（归 CW-032）**：rollout 依赖 `/opt/video-replica-candidate/compose.yaml` 等仓库外主机文件，尚非空白环境可重建的唯一默认包；仓库仍保留 internal P0 systemd 与 SQLite backup 单元（`deploy/internal-p0.env.example`、`deploy/nginx/internal-p0.conf.example`、`video-replica-backup.*`），需从正式部署产物排除。
- 管理端：非独立后端服务；`client/dist` 含客户工作台与 `/admin` 路由，同一 HTTPS origin 静态部署（手册 §1；独立制品拆分归 CW-019）。

## 2. 环境隔离与 PG 资源

| 环境 | PG 实例 | 说明 |
| --- | --- | --- |
| 开发 | Docker PG16，宿主端口 5433 | `scripts/pg-fixture.sh start`（`HOST_PORT=5433`）；fixture 未启动时 PG 套件按 skip，不作为验收证据 |
| CI | GitHub Actions PG16 service | `.github/workflows/ci.yml` quality-linux job |
| staging / 生产 | 按 §1 拓扑独立 PG16 HA | **不同环境不共用业务库** |

连接池预算（当前代码实际值，`server/app/db_pg.py:36-59,199-222`）：

| 参数 | 值 |
| --- | --- |
| 每进程池默认 | min=1，max=8（`DEFAULT_POOL_MIN/MAX`） |
| 池硬上限 | 64（`POOL_MAX_CEILING`，超配自动封顶并告警日志） |
| max_lifetime / max_idle | 3600s / 600s |
| statement_timeout | 300,000 ms |
| idle_in_transaction_session_timeout | 60,000 ms |

**总连接预算（建议基线，待目标机定标）**：常驻 2 API + 4 Worker = 6 进程 × max 8 = **48**；迁移单次独占、备份/PITR 只读复制连接、maintenance ×1 各留余量 → 建议生产 `max_connections ≥ 100`（默认值起步）；**预算按 API/Worker 进程数合计计算，迁移锁必须覆盖多主机入口（PG advisory lock），不能只依赖单机 flock**。现状注明：advisory lock 迁移锁已有实现在 `server/scripts/sqlite_to_postgres.py:52,165-176`（T07 割接路径，`pg_try_advisory_xact_lock` fail-closed）；`deploy/postgres/migrate.sh:18,25` 目前仅单机 `flock`——多主机安全迁移锁在正式部署主线的落地归 CW-032。扩容进程数时按 `进程数 × pool_max ≤ max_connections × 0.6` 复算（建议系数，待定标）。

## 3. 验收指标冻结表（全部为**建议基线**，目标机规格冻结后定标；不允许测试失败后静默降低阈值）

| 项目 | 建议基线 | 采样/判定方式 |
| --- | --- | --- |
| 数据量 | 10,000 客户 / 10,000 ACTIVE 主码 / 20,000 设备；10,000 排队 + 100,000 历史任务 | CW-047 负载准备数据（规格 §8.1） |
| 普通 API | 100 并发 p95 < 300ms | 排除长视频处理请求；普通 API 名单须在 CW-047 前列明 |
| 登录 / heartbeat | 100 并发 p95 < 300ms | 同上 |
| 同码激活竞态 | 100 并发，2 秒内收敛为一个事实 | 唯一约束 + 幂等断言 |
| 队列领取 / 锁等待 | p95 < 200ms / p95 < 50ms | 按任务种类分别记录 |
| RTO / RPO | 数据库 RTO ≤ 5 分钟；已确认资金事务 RPO = 0 | PITR 演练逐笔核验（手册 §5/§6）；达不到须按正本显式评估，不得以日志正常替代 |
| 不变量 | 越权成功、重复入账/付费、双在线、旧 epoch 成功写、已确认数据丢失 = **0** | 出现即阻断/停止扩大（V3 §8） |
| PG 全面统一 | 业务 SQLite 路径/替代库 = 0；DB 测试未分类/无依据删测/缺 PG 跳过 = 0；受支持旧 PG head 升级覆盖 100%；旧用例映射 100% | PG-01—12 矩阵（CW-045 汇总） |

每格含数值、采样窗口、环境与责任的要求在 CW-047 执行前由运维/QA 复核补齐实际采样窗口。

## 4. 灰度参数（Gate D）

- 放大路径：内部账号（客户身份）→ 10 码 → 100 码（规格 §9 Gate D；手册 §9 灰度边界）。
- 未签名 Windows 包只能标 `UNSIGNED_INTERNAL_TEST`，**不得进入客户灰度**。
- **待冻结字段（签认前不得进入 CW-051）**：每级观察时长、样本量、错误/等待阈值、放行人、升级确认方式、回滚触发条件。当前仓库无实测值，不得以文档示例冒充。

## 5. 指标与告警责任（沿用 T37 与规格 §8.3）

激活/设备/会话/队列/钱包/PG/复制/备份指标与 P1（重复入账、双在线、旧设备迟到成功写、跨用户访问、账本不一致）由 T37 管道承载；P1 必须 fired/resolved 成对留痕（手册 §4.3 开放灰度前注入可回滚异常验证）。

## 6. 未定项清单（冻结前不得进入对应验收）

| 未定项 | 阻塞的后续任务 |
| --- | --- |
| 目标机节点规格（CPU/内存/磁盘）与故障域划分 | CW-047 负载验收、CW-048 故障演练 |
| PG HA 具体方案（流复制/托管主备）与切换时长实测 | CW-047/048、CW-051 |
| §3 采样窗口实际值、§4 灰度观察参数 | CW-047 负载判定、CW-051 灰度放行 |
| 空白环境可重建交付包（当前 rollout 依赖仓库外主机文件） | CW-032、CW-047 |

在上述未定项冻结前，**不得删除旧部署脚本**（含 internal P0 单元——其退役归 CW-040）或进入负载/灰度验收。

## 7. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 运维负责人（拓扑/资源/未定项） | 已签认（owner phlong026 代签）：冻结交付设计主线（客户 API×2 + Worker×4 + PG16）+ 环境隔离 + PG 资源框架（连接池 min1/max8/ceiling64）；节点规格/HA 方案/切换时长/可重建交付包等未定项 defer staging/GA，冻结前不删旧部署脚本（internal P0 退役归 CW-040） | 2026-09-09 |
| QA（指标/灰度参数） | 已签认（owner phlong026 代签）：§3 验收指标为目标基线（建议值、未在代码固化为常量）；实际采样窗口数值 + §4 灰度观察参数（Gate D）defer GA/staging 定标；与 CW-002 §8 代码现状机制分属两层不混写 | 2026-09-09 |
