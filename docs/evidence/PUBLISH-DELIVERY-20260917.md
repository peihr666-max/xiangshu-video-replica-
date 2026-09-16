# PUBLISH-DELIVERY-20260917：发布链路第二阶段 PR-A（立即/定时发布 · API 优先投递 · 桌面凭据上传）

## 请求与范围

用户 2026-09-17 决策（对话确认）：增加立即发布与定时发布；**协议（API）优先、Playwright 浏览器兜底**；桌面端 WebView2 扫码账号在登录成功后把 cookies + localStorage **加密上传服务端**统一进 `publish_browser_accounts`，本机 profile 保留用于手动发布；"发布后回收"= 回收发布结果（作品 ID/短链/审核状态）+ 回收作品数据（播放/点赞/评论/分享）；本期抖音 + 视频号，小红书预留字段随后；按 AGENTS.md 完整流程执行。

拆为两个顺序任务/PR：**PR-A（本证据）** 交付 `publish_records` 表与状态机、立即/定时排队、API 路径投递、桌面凭据导入、发布页正式动作、记录列表、首页「累计已发布」真实计数；**PR-B `PUBLISH-FALLBACK-SYNC`** 交付 Playwright 兜底上传器与结果/数据回收。PR-A 已预留 `delivery_mode / stats / stats_synced_at / sync_requested / platform_status` 列与 `deliver_via_browser` 接缝，PR-B 只加逻辑不改 DDL。

独立分支 `feat/publish-delivery-20260917`，worktree `.worktrees/PUBLISH-DELIVERY-20260917`，基线 `origin/main@d95a8db4`（#126）。开工核对：远程无同题分支，认领登记无同题任务，`git worktree list` 无同名目录；`gh` 在本机不可用，开放 PR 未能以 API 核对，以远程 heads 与登记为准。Owner 当前 Claude 会话；Reviewer 为执行者自检与 PR 门禁，不冒称独立评审。

## 实现

### 服务端

- 迁移 `20260917T1000_publish_records`（父 `20260916T2000_prompt_optimization_receipts`，raw SQL + PG 守卫）：新建 `publish_records`（jsonb `tags/options/stats`、timestamptz 时间、lease 三件套、`platform/status/delivery_mode/sync_requested/attempt_count` CHECK、4 个索引含 2 个 partial）；`publish_browser_accounts` 追加 `status/error_message/source`。
- `app/publish_records.py`：创建（账号归属与 `connected` 状态、平台可投递性、`asset:` 素材归属 + 上传完整性、封面须图片、`scheduled_at` 须带时区且提前 2 分钟至 30 天、同账号同视频活动记录去重）、列表/详情、取消（仅 queued）、重试（仅 failed）、删除（仅终态）、`request_sync`（仅 published，PR-B 消费）、汇总；worker 侧 `claim_publish_work`（`COALESCE(scheduled_at, created_at)` 到点、同账号 `NOT EXISTS publishing` 串行、`FOR UPDATE OF r SKIP LOCKED`）、过期 publishing 租约回 queued、账号解绑/失效的 queued 直接 failed、`finalize_publish_work` 围栏回写（published 写 item id/短链/`delivery_mode`；`account_invalid` 同时把账号置 invalid；瞬时失败 `attempt_count<3` 回 queued 并延后 5 分钟）。
- `app/publish_credentials.py`：storage_state → Cookie 头（按平台域名过滤）+ 抖音 `security-sdk` localStorage（精确键优先、兜底扫描完整 ticket-guard 材料）；dataclass `repr` 隐藏值。
- `app/publish_delivery.py`：`materialized_media` 流式落盘到临时目录并清理；`deliver` = API 适配器优先 → 非 `account_invalid` 的失败且 `VIDEO_REPLICA_PUBLISH_BROWSER_FALLBACK`（默认开）时调 `deliver_via_browser`（PR-A 为抛 `PublisherUnavailableError` 的桩）；抖音适配器新增 `visibility` 透传并接受 dict 形式 `security_sdk`。
- `app/publish_worker.py`：每轮除账号探针外再 claim 一条发布记录；解密 → `storage_for_asset` 短事务取存储 → 事务外落盘与投递 → 围栏 finalize；任何异常只记类型名，绝不输出 cookie/storage_state。
- `app/publish_record_routes.py`（`/api/studio/publish/records`）与 `publish_browser_routes.py` 新增 `POST /accounts/import`（桌面导出的 storage_state，形状校验、≤2MB、`source='desktop'`，同身份 upsert 并复位 `status`）；`save_login` 复用同一 `upsert_browser_account`。
- 部署：compose 新增 `worker-publish`（`app.publish_worker --idle-seconds 3`）、rollout 可选服务与回滚停机、基础镜像装 `nodejs` 并把 `app.publish_worker` 加入 import 冒烟、systemd `video-replica-publish-worker.service`；README §3 连接预算 8×8=64+1+3=68 ≤ 120。

### 桌面（Rust）

- `check_local_publish_login` 在 connected 瞬间通过 `ICoreWebView2CookieManager.GetCookies(origin)` + `localStorage` eval 组装 Playwright 形状 `storage_state` 随 `LoginStatus.storage_state` 一次性返回主窗口（`main_only` 校验）；导出失败返回 `null`，本机账号仍可手动发布。
- 新命令 `export_local_publish_account_state`：隐藏官方窗口重新观察身份端点（45 秒），身份一致才导出，用于"同步到服务端"重试。文件头注释改写：不再是"IPC never exports cookies"，而是仅 connected 时一次导出供加密上传、不落本机文件。

### 前端

- 账号面板：桌面端 connected 后调用 `POST /accounts/import`；列表显示"已同步服务端，可自动发布 / 服务端未同步 / 服务端登录态失效"，失败给出「同步到服务端」重试；解绑同时删除服务端副本。
- 发布页：账号选择改为服务端账号（两端一致，失效账号标注并禁发）；新增「发布时间」立即/定时 + `datetime-local`（本地时区 → ISO，前端预校验 2 分钟/30 天）；主按钮「立即发布/定时发布」→ `POST /records`；「前往官方发布」降为桌面端且有本机 profile 时可用；小红书提示"即将上线"且禁发；新增 `PublishRecordsPanel`（状态徽标、计划/发布时间、短链、错误、统计字段、取消/重试/同步/删除，活动记录 15 秒轮询）；首页「累计已发布」读 `GET /records/summary`。

## 验证

- 服务端专项：`test_publish_records.py` 19 passed（PG lane，专属库 `publish_records_test`）、`test_publish_credentials.py` 12、`test_publish_delivery.py` 17、`test_publish_browser.py` 13（含 4 项 import）、`test_publish_accounts.py` 16（A12 改为隐藏 records 表后验证 verify 只碰 accounts）、迁移矩阵 `test_cw056_supported_head_matrix.py`/`test_postgres_migrations.py`/`test_migration_dialect_contract.py` 40、交付包契约 `test_cw032_delivery_package.py`/`test_customer_git_rollout.py`/`test_customer_ha_smoke.py` 55。`ruff check` / `ruff format --check` / `mypy app`（159 文件）通过。
- 冻结矛阵：`HEAD_REVISION → 20260917T1000_publish_records`；`HEAD_SCHEMA_COUNTS` tables/primary_keys +1、columns +29、foreign_keys +4、check_constraints +7、jsonb_columns +3、partial_indexes +2、timestamptz_columns +6；`HEAD_SCHEMA_DIGEST = 0628591e…8c0c`；`server/migrations/manifest.json` 以 `migration_manifest.py --record` 重算，`--check` OK；分片清单以 `build-test-shards.py --shards 4` 重生成，`--check-coverage` OK（107 文件）。
- 桌面：`cargo fmt --check`、`cargo check --locked`、`cargo test --locked` 27 passed（含 cookie 域过滤与 Playwright 字段归一化新用例）。
- 前端：`npm run check --workspace client` = Biome + `tsc -b` + Vitest **105 文件 / 1617 passed**（新增 `PublishRecordsPanel.test.tsx` 6 项、发布页立即/定时/小红书 3 项、账号面板同步/解绑 2 项）。
- 全量 PostgreSQL 四分片：见本文末「全量结果」段（分片日志 `outputs/publish-delivery-20260917/ci-shard-*.log`）。
- 所有投递/探针用例均以 monkeypatch 假投递器与合成凭据运行，**不触网、不使用真实账号、未发布任何真实视频**。

## 安全、资源与交付

- 姿态变更（用户 2026-09-17 决策）：桌面 WebView2 profile 的 cookies + localStorage 在 connected 瞬间导出一次，经主窗口 → 已认证 HTTPS 接口 → 服务端 Fernet 密文入库；不落本机文件、不进日志（Rust 只返回给 `main_only` 的主窗口；服务端异常只记类型名；`PublishCredentials` repr 隐藏值）。云端扫码路径本就服务端保管，两端口径一致。
- 记录响应永不含凭据；账号删除时记录 `account_id` 置 NULL 并在下一轮 claim 中失败而非悬挂。
- 测试库：`publish_records_test` 登记在 `pg_test_kit.RECORDED_TEST_DATABASES`，用完即删；分片容器 `customer-v3-pg-test-shard0..3`（`CI_SHARD_BASE_PORT=5560`）由脚本 `--rm` 清理，结束核对 `docker ps -a --filter name=shard` 为空。
- 未合并、未部署、未真实发布；证据层级 **AUTOMATED_VERIFIED**。真实链路（一个测试账号、`visibility=2` 私密视频、API 路径回写 item id）需用户人工授权后另行登记 `REAL_CHAIN_VERIFIED`。

## 未测试项 / 已知边界

- 真实平台协议投递（Node 签名、TOS 分片上传、视频号 clip 等待）与真实账号 storage_state 中 `security-sdk` 的实际键名；Windows 安装包内的 WebView2 cookie 导出实机验证；远程三门禁以 PR 当前 head 为准。
- Playwright 兜底与结果/数据回收为 PR-B 范围，本 PR 只有接缝与列。
- 小红书：只保留 platform 值与登录，创建记录返回 422 `PUBLISH_PLATFORM_NOT_READY`。

## §14 证据模板

```text
任务/工作包：PUBLISH-DELIVERY-20260917 / 发布链路第二阶段 PR-A（records + 立即/定时 + API 投递 + 桌面凭据上传）
Owner / Reviewer：当前 Claude 会话 / 执行者自检 + PR 门禁
分支 / 基线 SHA：feat/publish-delivery-20260917 / d95a8db4（origin/main #126）
上游规格段落：CW002-SCOPE-DECISIONS §8.3；用户 2026-09-17 决策；AGENTS 标准工作流
改动文件：见客户版代码开发清单-V3.md「PUBLISH-DELIVERY-20260917 · 文件映射」
失败测试或回归锁定：先写 test_publish_records / credentials / delivery / browser import 与前端三处新用例（红），实现后绿；A12 改写为隐藏 records 表验证解耦
实现结果：publish_records 队列与状态机；立即/定时；API 优先 + 兜底接缝；桌面凭据一次导出并加密上传；发布页正式动作与记录面板；首页真实计数；publish worker 部署
验证命令与通过数：ruff/format/mypy 通过；专项见「验证」；client check 105 文件 1617 passed；cargo test 27；全量四分片见文末
证据层级：AUTOMATED_VERIFIED；未标真实平台链路、远程门禁、合并或部署
安全与可观测性：凭据不回传、Fernet 密文、围栏 finalize、日志只记异常类型、桌面导出仅主窗口一次性
迁移与回滚：追加 20260917T1000_publish_records；downgrade 删表并去除三列；旧应用可忽略新表
外部授权记录：用户决策见「请求与范围」；无公网部署或真实发布授权
未测试项：见上节
Lore 提交 SHA：见 PR Commits 列表；不伪造 PR 或合并状态
```

## 全量结果

Windows 本机、四个独立 PostgreSQL 容器（`CI_SHARD_BASE_PORT=5560`，`customer-v3-pg-test-shard0..3`，脚本自动 `--rm` 清理，结束后 `docker ps -a --filter name=shard` 为空）：

| 分片 | 结果 |
| --- | --- |
| 0 | 613 passed / 1 failed |
| 1 | 656 passed / 22 failed / 1 既有 skipped |
| 2 | 648 passed |
| 3 | 535 passed / 11 failed |
| 合计 | **2452 passed / 34 failed / 1 skipped**（107 个测试文件全覆盖） |

34 项失败全部为本机 Windows 环境既有失败、与本任务无关：`test_cw033_pitr_drill_validation`（21，驱动 bash 演练脚本）、`test_cw043_viral_import_pg::test_cached_local_media_moves_to_cos_*`（6 个参数化，`ViralMediaBusy`；在未改动的主检出 `xiangshu-video-replica-` 上以同一 fixture 复现同样 6 失败）、`test_cw009_security_matrix_export`（4）、`test_security_contracts::test_no_sentry_sdk_enters_the_server_runtime`（1）、`test_pg_test_kit::test_shared_suite_lock_is_exclusive`（1，Windows `fcntl` 垫片产物）。首轮全量曾暴露两项本任务引入的红：`test_cw057_cli_pg_entry::test_every_deployed_unit_is_classified`（新增 systemd 单元未分类）与 `test_sqlite_to_postgres` 6 项（`publish_records` 未登记 PG-only 表），均已修复并复验（70 passed）。原始日志：`outputs/publish-delivery-20260917/final/ci-shard-{0..3}.log`、`run-pytest-shards.log`；首轮日志同目录上一层。Linux 门禁以 PR CI 为准，本地 Windows 结果不替代。
