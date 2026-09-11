# CW-032 证据文件 — 补齐可重建后端交付包及配置检查

任务：CW-032（W4 · 代码与测试增量 · 运维负责人 + 后端负责人）
分支：`feat/customer-v3-cw032-rebuildable-backend-package`（独立 worktree `E:/众墅之家爆款短视频创作/.worktrees/CW-032-rebuildable-backend-package`，从 `origin/main@d49f851` 创建——该提交即 CW-060 #27 的 squash 合入）
前置核验（八项全部在 main）：CW-004（W0 签认）、CW-019（#12）、CW-025（#7）、CW-027（#23）、CW-031（#17）、CW-056（#15）、CW-057（#19 8ab85c7）、CW-060（#27 d49f851）。排班并行边界「等028释放settings/main」已满足（CW-028 #28 先行合入）；与 CW-024（桌面制品）、CW-058（测试/fixture）按既有分工零交集。
上游规格：V3 收敛清单「CW-032 补齐可重建后端交付包及配置检查」；PG-08（工具与备份）；PG-10（制品与运行证据，配合面）；审计 backend.json CW-032 条目（status=partial，remaining 三条）。

---

## 1. 交付差额（对审计 remaining 三条逐一收口）

| 审计 remaining | 本 PR 处置 |
| --- | --- |
| rollout 依赖 /opt/video-replica-candidate/compose.yaml 等仓库外主机文件，尚非空白环境可重建的唯一默认包 | ①新增 `deploy/customer/compose.yaml`——唯一默认部署包（登记制品）：db / migrate（唯一 schema DDL 角色，一次性）/ api-1、api-2 / worker-1..4，服务名与 rollout `SERVICES` 逐一对应；②rollout `COMPOSE` 默认指向库内制品（`$SOURCE/deploy/customer/compose.yaml`，旧主机文件仅剩 `CUSTOMER_COMPOSE=` 兼容通道）；③新增 `deploy/customer/bootstrap-base-image.sh`——空白宿主机首个镜像构建（干净 python:3.12-slim 基底 + 锁定依赖 `uv sync --locked` + 与 rollout 相同的镜像内检查），配合 README 的 `docker compose up -d` 序列实现"空白隔离目录仅使用登记制品重建"；④新增 `deploy/customer/README.md` 重建手册 |
| 仓库仍保留 internal P0 systemd 与 SQLite backup 单元，需从正式部署产物排除 | 正式包目录 `deploy/customer/` 清单封闭（compose.yaml/README.md/bootstrap-base-image.sh 三文件，机器断言）；包内任一文件出现 internal-P0/SQLite backup/operator 工具名仅允许出现在排除声明语句（机器断言）；SQLite backup timer 不进任何 compose/rollout/README 活动引用（继承 CW-057 客户链守卫并扩展至新目录）；internal 单元的物理退出仍归 CW-040/CW-042（本任务不越界删除） |
| 补齐应用/迁移/备份角色、全进程连接池预算、首次管理员、健康检查和制品哈希的可执行验收 | 角色=compose 四类服务+宿主 PITR（见 §2）；连接池预算公式进入 compose 注释+README §3+机器断言（6×`DEFAULT_POOL_MAX`=48+1 migrate+3 reserved ≤ `max_connections=120`，且默认值改动会使测试失败）；首次管理员=README §2 的 `provision-empty-customer --confirm-empty-database` 命令（与实现逐字一致）；健康检查=db `pg_isready` + api 容器内 urllib `/health` + rollout VERIFY 三层；制品哈希=镜像三标签 + `BACKUP-SHA256SUMS` + 新增 `compose.sha256`（rollout BACKUP 段新增） |

## 2. 角色（compose 与宿主分工）

| 角色 | 载体 | 说明 |
| --- | --- | --- |
| 数据 | compose `db`（postgres:16-alpine） | `max_connections=120` + `superuser_reserved_connections=3`；`pg_isready` 健康检查 |
| 迁移 | compose `migrate`（一次性） | 唯一执行 `alembic upgrade head` 的角色；api/worker `depends_on: service_completed_successfully` 后才启动——多实例不竞争改 schema；api/worker 服务块内无任何 alembic 字样（机器断言） |
| 应用 | compose `api-1`/`api-2` | `127.0.0.1:8001/8002` 与 nginx `customer.conf.example` upstream 逐一对应（交叉断言）；`/health` urllib 容器健康检查 |
| 任务 | compose `worker-1..4` | `python -m app.generation_worker`；等待 db healthy + migrate 完成 |
| 备份 | 宿主 `deploy/postgres/pitr-backup.sh` + `video-replica-pitr-backup.timer` | 轮换由归档平台不可变策略承担（与实际命令一致，本机不删已发布 base）；恢复=`pitr-restore-drill.sh` + `scripts/pitr_recovery_facts.py` |

## 3. 配置 fail-fast 矩阵（可执行验收登记）

机器断言（`test_fail_fast_matrix_targets_exist`）把每项依赖映射到既有可执行验收：

| 依赖缺失/错误 | 可执行验收落点 |
| --- | --- |
| 缺/错 PG DSN | `tests/test_bootstrap_all_env_pg_gate.py`（`resolve_database_config` fail-closed 矩阵，CW-025/057） |
| 缺根密钥（settings/admin/激活码等） | `tests/test_customer_ha_smoke.py`（`assert_customer_production_security`，3 处） |
| 缺私有 COS | `tests/test_customer_ha_smoke.py`（`check_customer_production_runtime_dependencies` → COS readiness） |
| 缺 ffprobe | `tests/test_customer_ha_smoke.py`（`customer_runtime_dependency_gate_requires_ffprobe`：无 ffprobe 时不得触探 PG） |
| ffmpeg 不可用 | `tests/test_script_from_audio.py`（`MediaToolUnavailable`） |

密钥不进客户包/日志：customer.env 模板仅占位符（secret 扫描覆盖 deploy/），密钥经 `/etc/video-replica/customer.env` 与密钥存储注入；rollout 日志只输出计数与路径。

## 4. 验证记录（本机 Windows）

- 新增专项 `tests/test_cw032_delivery_package.py`（8 用例，全离线 TEST-LOGIC）：拓扑服务集恰等于 rollout SERVICES ∪ {db, migrate}；migrate 唯一 DDL 角色且 api/worker 等待其完成；连接池预算按 `app/db_pg.py` 活值计算；api 端口/nginx/健康路由三方法一致；rollout 消费库内 compose + `compose.sha256` + bootstrap 脚本契约；正式包封闭清单与排除语句；README 覆盖重建/首管/备份/哈希；fail-fast 矩阵目标存在 → **8 passed**。
- 交叉回归：`test_customer_git_rollout.py`（CW-019 发布契约，rollout 修改后零回归）+ `test_internal_deployment.py` + `test_cw057_cli_pg_entry.py`（客户链守卫）+ `test_cw060_operator_isolation.py` + `test_bootstrap_all_env_pg_gate.py` + docs/HA/pitr 套件 → **161 passed, 1 skipped**。
- 静态门：ruff check 全过、ruff format 305 files 无修正、mypy --strict app 104 files 无问题、`verify_no_secrets.sh` EXIT=0。
- 无新增 PG 资源需求（契约测试离线；交叉套件复用 vs-pg-dev@5434）。

## 5. 诚实边界

- **空白环境重建与 rollout 全流程未在真实宿主机执行**：compose/bootstrap 脚本的契约以内容断言+既有发布测试兜底；"空白隔离目录重建 API/Worker/Admin" 的实物执行与真实多实例拓扑归 CW-047（本任务目标层级 AUTOMATED_VERIFIED 的命令契约面已闭合）。
- `bootstrap-base-image.sh` 的 `apt-get install ffmpeg` 在受网络限制的构建环境需镜像源配置（README 未展开，属安装现场事项）。
- customer.env.example 的 `VIDEO_REPLICA_DATABASE_URL` 指向 `db:5432` 的默认值、TLS（verify-full + CA）证书挂载属安装现场配置，手册已登记要点但不改变模板文件（避免越 CW-004 冻结的 DSN 约定）。
- 证据等级 `AUTOMATED_VERIFIED`；不宣称 STAGING 及以上。

## 6. 与相邻任务的边界

- **CW-024**：桌面制品（Tauri/NSIS）不在本包（backend-only）。
- **CW-058**：其测试 fixture 合同不受影响（本任务未动 server 测试基座）。
- **CW-047**：真实多实例/负载验收消费本包。
- **CW-040/042**：internal 单元退出与 SQLite 裁剪保持原排程，本任务仅在客户面完成排除与登记。
- **CW-060（#27）**：历史 operator 工具经其独立制品交付；客户镜像实物扫描在两处（rollout、bootstrap）均落位。
