# 客户版唯一默认部署包（CW-032）

本目录是空白环境可重建的客户后端唯一默认交付包：`compose.yaml` +
`bootstrap-base-image.sh` + 本手册。除本目录与 `deploy/postgres/`、
`deploy/nginx/customer.conf.example`、`deploy/customer.env.example` 之外，
部署不再依赖任何未登记的主机文件（旧 `/opt/video-replica-candidate/compose.yaml`
由 `customer-git-rollout.sh` 的 `CUSTOMER_COMPOSE` 覆盖通道兼容，但不再是必需品）。

正式部署产物排除项（PG-08/PG-09）：internal P0 systemd 单元
（`deploy/systemd/video-replica-api*.service` 等内部单元）与 SQLite backup
timer（`video-replica-backup.*`）不属于本包；历史 operator 工具由 CW-060 的
独立制品交付（`deploy/operator/`），同样不在客户镜像内（构建期实物扫描强制）。

## 0. 前置

- Docker Engine + Compose v2；两份受控配置文件（不入 Git）：
  - `deploy/customer/.env`：`APP_IMAGE`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_DB`
  - `/etc/video-replica/customer.env`：应用配置（模板 `deploy/customer.env.example`；
    `VIDEO_REPLICA_DATABASE_URL` 默认指向本 compose 网络的 `db:5432`）
- nginx 反代（模板 `deploy/nginx/customer.conf.example`）：upstream 即本包 api-1/api-2
  的 `127.0.0.1:8001` / `127.0.0.1:8002`。

## 1. 空白环境重建（API/Worker/Admin）

```bash
# 1) 首个应用镜像（干净基底 + 锁定依赖 + 与 rollout 相同的镜像内检查）
deploy/customer/bootstrap-base-image.sh <git-short-sha>

# 2) 写 deploy/customer/.env（APP_IMAGE=video-replica-rehearsal-app:<sha> …）
# 3) 一键拉起：db(healthy) → migrate(一次性 alembic upgrade head) → api/worker
docker compose -f deploy/customer/compose.yaml up -d
```

`migrate` 是唯一执行 schema DDL 的角色（一次性容器）；api/worker 通过
`depends_on: service_completed_successfully` 等待其完成后才启动，自身不运行
alembic——多实例不会竞争改 schema。后续发版沿用 `deploy/customer-git-rollout.sh`
（灰度、健康检查、回滚均按既有脚本执行，其迁移步骤同样是单次执行）。

Admin 页面（`client/dist-admin`）由 `customer-git-rollout.sh` 的 SITE 步骤发布到
nginx 的 `/admin/`；空白环境首装时先按手册构建前端制品后再执行该脚本。

## 2. 首次管理员（first admin）

迁移完成后、对空库执行一次性开通（命令与实现一致，重复执行会被
pristine 检查拒绝）：

```bash
docker compose -f deploy/customer/compose.yaml run --rm --no-deps api-1 \
  sh -lc 'cd /opt/video-replica/server && python -m app.bootstrap \
  provision-empty-customer --admin-username <ops-admin> \
  --admin-display-name "<显示名>" --cos-config-file /etc/video-replica/cos-bootstrap.json \
  --confirm-empty-database'
```

输出的单次 exchange credential 按运维手册写入 root-only 文件，不进终端回滚历史。

## 3. 连接池预算（全进程）

| 进程 | 数量 | 每进程池上限 |
| --- | --- | --- |
| api-1/api-2 | 2 | `VIDEO_REPLICA_PG_POOL_MAX`，默认 8（硬顶 64，`server/app/db_pg.py`） |
| worker-1..4 | 4 | 同上 |
| migrate | 一次性 | 短连接 |
| 合计 | — | 6×8=48 + 1 + 3（superuser_reserved）= 52 ≤ `max_connections=120`（compose db command） |

上调任一 `VIDEO_REPLICA_PG_POOL_MAX` 前必须复核上式（契约测试：
`server/tests/test_cw032_delivery_package.py`）。

## 4. 备份与恢复（backup 角色）

- 物理备份：宿主机 `deploy/postgres/pitr-backup.sh`（pg_basebackup + WAL，
  `video-replica-pitr-backup.timer`），归档加密/跨区/不可变由
  `VIDEO_REPLICA_PG_PITR_ARCHIVE_HELPER` 平台承担——轮换即平台保留策略，
  本机不删除已发布 base（与实际命令一致）。
- 恢复演练：`deploy/postgres/pitr-restore-drill.sh` + `scripts/pitr_recovery_facts.py`。
- SQLite backup timer 不属于本包（PG-08：正式部署中 SQLite backup=0）。

## 5. 健康检查与发布验证

- 容器级：db `pg_isready`；api `GET /health`（容器内 urllib）。
- 发布级：`customer-git-rollout.sh` VERIFY——镜像 revision 标签逐容器比对、
  前端/admin 资产指纹、`/health?release=<sha>`、OpenAPI 路径存在性。
- 配置 fail-fast（每项独立、可定位）：缺/错 PG DSN、缺 settings/admin/激活码等
  Fernet/HMAC 根密钥、缺私有 COS、缺 ffmpeg/ffprobe —— 均在启动或就绪检查中
  拒绝启动（可执行验收见 `server/tests/test_cw032_delivery_package.py` 的矩阵，
  其 executable 落点为既有 bootstrap/安全门测试套件）。

## 6. 制品哈希

- 镜像标签：`org.opencontainers.image.revision`（release SHA）、
  `org.opencontainers.image.source-tree`、`video-replica.database-head`。
- 发布备份：`$ROOT/backups/<...>/BACKUP-SHA256SUMS`（站点包 + pg_dump）；
  rollout 从本目录取 compose 后会把 `compose.sha256` 一并写入。
- 锁定依赖：`server/pyproject.toml` + `server/uv.lock`（镜像内 `uv sync --locked`）。
