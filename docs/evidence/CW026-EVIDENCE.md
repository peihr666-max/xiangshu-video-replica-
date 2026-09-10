# CW-026 证据 — 退出内部认证并复验客户 fencing

> 状态：`AUTOMATED_VERIFIED`（真实 PG 16.15 fixture 上执行；未过真实链路，不提升 `STAGING_VERIFIED`）。
> 分支 `feat/customer-v3-cw026-exit-internal-auth-fencing`，基线 `origin/main@e829ad1a6d859a51ae804a7cd31cc5513b393cb9`（CW-055 #13 + CW-054 #14 + CW-019 #12 已合入）。
> 本文件按任务账本 §14 模板记录；业务完成状态以 `docs/客户版任务清单-V3.md` §18 为唯一真源。

## 1. 任务与范围

- 任务/工作包：CW-026 / W4 代码与测试增量（认证负责人 + 独立安全复核）。
- 上游规格：V3 收敛清单 §CW-026（`outputs/customer-cloud-convergence-analysis-2026-09-08/v3/客户版收敛剩余任务清单与验收完工标准-V3.md`）；任务账本 §18 CW-026 行；排班与 Worktree 协作清单 §3/§4/§5/§6；AGENTS.md 标准工作流。
- 前置核验（2026-09-11 fetch 后）：CW-025（#7 已合入）、CW-009（#108 已合入）、CW-003（W0 批次 #107 已合入，`26e596c` 为 origin/main 祖先）、CW-055（#13 已合入）——四项前置全部满足。
- 查重（五项检查）：`git fetch origin --prune` 后无 `cw026` 本地/远程分支、无同编号开放/近期 PR（GitHub API 实查仅 CW-056 一项开放）、`git worktree list` 无同编号目录、`.git/codex-task-claims/CW-026/` 原子新建成功。

## 2. 仅做剩余（对照 V3 规格）

| 规格要求 | 本任务落地 |
| --- | --- |
| 收敛后所有环境移除 internal Bearer | 删除 `authenticate_request` 中「非客户生产 PG 仍接受 internal access token」的 A1 豁免分支：PG 通道一律按客户会话解析 Bearer（`server/app/auth.py`） |
| 移除 X-Dev-User-Id | PG 通道缺少 Authorization 时直接 401 `SESSION_TOKEN_REQUIRED`，不再落入 `identity_user_id` 的 dev header 解析；开发头在收敛通道不可达 |
| 移除固定桌面身份旁路 | `VIDEO_REPLICA_DESKTOP_USER_ID`/`VIDEO_REPLICA_ALLOW_DEV_IDENTITY_HEADER`/`VIDEO_REPLICA_AUTH_MODE=desktop\|development` 组合在 PG 通道全部不可达（只作用于 SQLite 内部遗留通道） |
| 逐个保留业务路由证明 read owner 与 write fenced transaction 覆盖 | `tests/test_cw026_converged_auth.py::test_every_business_method_path_is_classified_zero_misses`：271 条 method-path 全分类（READ_OWNER 88 / WRITE_FENCE 67 / ADMIN_SESSION 84 / SESSION_LIFECYCLE 19 / PUBLIC_SIGNED 7 / PAYMENT_CALLBACK 2 / PUBLIC_INFRA 4），未分类=0；完整矩阵见 §6 |
| 入口后切换写入 0 副作用 | `test_switch_after_snapshot_fences_late_write_with_zero_deltas`（epoch 切换 / lease 回拉 / 注销三变体）：快照后第二条连接提交切换，迟到写被 401 拒绝，projects/wallet_transactions/customer_fencing_write_evidence 增量均为 0 |
| 幂等重放重新执行授权 | `test_idempotent_replay_reauthorizes_after_session_switch`：同 Idempotency-Key 重放在 fenced 事务内先重验会话——旧令牌被替换后重放 401 `SESSION_REPLACED` 且不新增订单、封存信封完好；新令牌重放拿到 `X-Idempotent-Replay: true` 的封存响应 |
| 剔除重复开发（管理员 session/CSRF 归 CW-027；旧路由最终取消注册归 CW-041） | 未触碰 admin/control 路由鉴权；SQLite 内部遗留通道（`DB_PATH`）按 CW-021/040/041 排期保留，由 `test_legacy_sqlite_lane_keeps_internal_and_dev_identity` 反向钉住未越界 |

## 3. 失败测试（RED）与实现（GREEN）

- RED（`origin/main` 版 `server/app/auth.py` + 本分支新测试）：`5 failed, 16 passed`——`test_internal_bearer_refused_on_converged_lane_without_customer_flag`、`test_dev_identity_header_unreachable_on_converged_lane`、`test_desktop_identity_bypass_unreachable_on_converged_lane`、`test_internal_bearer_with_desktop_pin_still_fences_on_converged_lane`、`test_internal_access_tokens.py::test_customer_production_lane_refuses_internal_bearer_on_business_routes[false]` 全部精确落在被移除的豁免行为上。
- GREEN：`tests/test_cw026_converged_auth.py` 14 passed；`test_internal_access_tokens.py` 更新后双参数化分支均断言拒绝。
- 迁移的既有测试（因收敛行为变化而更新认证方式，断言语义不变）：
  - `tests/test_independent_creation.py::test_saved_prompts_aggregate_across_projects`：X-Dev-User-Id → 种子客户会话 Bearer（owner 过滤 / limit 钳制 / 坏 JSON 跳过断言不变）。
  - `tests/test_oral_domain.py` 3 个路由级用例：X-Dev-User-Id → `get_current_user` 依赖覆盖（业务行为断言不变；认证层由本任务专项覆盖）。

## 4. 验证命令与通过数（本机 Windows + Docker PG 16.15，容器 `vs-pg-cw026` 端口 5437 / 分片 5500-5503，与 5435（CW-056）/5436（CW-031）/5434（vs-pg-dev）全部隔离）

| 验证 | 结果 |
| --- | --- |
| `pytest tests/test_cw026_converged_auth.py` | 14 passed |
| `pytest tests/test_customer_fencing.py tests/test_customer_recharge.py tests/test_customer_sessions.py` | 148 passed |
| `pytest tests/test_independent_creation.py tests/test_customer_security.py tests/test_customer_devices.py tests/test_customer_activation.py` | 142 passed（含迁移用例修复后） |
| `pytest tests/test_rbac.py tests/test_customer_chain_e2e.py tests/test_wallet_routes.py` + fencing 写路由矩阵抽查 | 78 passed |
| `bash scripts/verify_no_secrets.sh` | exit 0 |
| `ruff check server` | All checks passed |
| `ruff format --check server` | 297 files already formatted |
| `mypy server/app` | Success: no issues found in 104 source files |
| 顺序全量 `pytest tests -q`（隔离容器 vs-pg-cw026:5437，一次性收尾全量） | `28 failed, 2292 passed, 2 skipped, 38 errors`（59:41）；28 failed = 22 cw033 POSIX 子进程 WinError2 + 6 simple_character 本机图像工具缺失（与 CW-054 登记的环境基线逐文件一致，还原 auth.py 对照可复现同类）；38 errors 全为 ffmpeg 缺失；本任务触碰的全部测试文件（cw026_converged_auth/internal_access_tokens/independent_creation/customer_fencing/customer_recharge/oral_domain 迁移用例）在 FAILED/ERROR 清单零出现 |

环境性豁免（与基线一致，非本任务引入）：本机无 ffmpeg（38 errors 在还原 `auth.py` 的对照运行中逐字节同数复现）；无 cargo/gh（tauri/audit 门禁交 CI）；`test_cw033_pitr_drill_validation.py` 子进程调 `.sh` 的 `WinError 2` 与 simple_character 本机图像校验工具缺失沿用 CW-054/055 已登记归因。以上由 CI Linux 门禁承载。并行分片说明：本机另一会话（CW-057）与本次收尾同时启动同名分片脚本（固定容器名 `customer-v3-pg-test-shardN` + 共享 /tmp 日志），两组运行互相污染，按「共享 PG 全量串行」规则停止分片路径，改为上述隔离容器顺序全量（等价路径 A），未与任何其他任务争用 PG。

## 5. 安全复核记录（独立视角自检）

- 旧身份不可达性：probe app 直接挂 `get_current_user`（读通道唯一入口），矩阵覆盖 internal Bearer、dev header、desktop pin、legacy auth mode 四类旧身份与组合，均在 PG 通道 401。
- 失败开放面核查：`customer_session_snapshot` 无 PG 时返回 None 的分支仅作用于 SQLite 内部遗留通道（收敛通道 PG 恒配置）；`BusinessDb.write` 在 PG+无快照时 503（既有），未被本任务放松。
- 未决项：无。CW-026 完工标准「旧身份与开发头在收敛运行方式不可达」由自动化测试承载；管理员 session/CSRF 矩阵归 CW-027 复验。

## 6. 全部保留业务 method-path 授权矩阵（漏项=0）

类别说明：READ_OWNER = `get_database`+`get_current_user`（收敛通道上解析为客户会话，读仅限本人）；WRITE_FENCE = `get_business_db`（fenced 事务内重验会话）；ADMIN_SESSION = admin/control/character-admin 会话依赖（CW-027 复验范围）；SESSION_LIFECYCLE = `/api/customer/*` 在处理器内自验设备/会话凭据的引导端点（CW-016/017 线）；PAYMENT_CALLBACK = ZPay 回调/跳转（验签即授权）；PUBLIC_SIGNED = 公开或 HMAC 签名对象路由（依据见代码内注释与本文件 §2）；PUBLIC_INFRA = `/health` `/ready` `/live` `/metrics` 等。

| 方法 | 路径 | 类别 | 认证依赖 |
| --- | --- | --- | --- |
| `GET` | `/api/admin/settings` | ADMIN_SESSION | get_database, require_settings_admin |
| `PATCH` | `/api/admin/settings/billing` | ADMIN_SESSION | get_database, require_settings_admin |
| `GET` | `/api/admin/settings/diagnostic-reports/{report_id}/download` | ADMIN_SESSION | get_database, require_settings_admin |
| `POST` | `/api/admin/settings/diagnostic-test` | ADMIN_SESSION | get_database, require_settings_admin, get_provider_tester |
| `PUT` | `/api/admin/settings/providers/{provider}` | ADMIN_SESSION | get_database, require_settings_admin |
| `POST` | `/api/admin/settings/providers/{provider}/connection-test` | ADMIN_SESSION | get_database, require_settings_admin, get_provider_tester |
| `POST` | `/api/admin/settings/providers/{provider}/paid-test` | ADMIN_SESSION | get_database, require_settings_admin, get_provider_tester |
| `POST` | `/api/admin/settings/providers/{provider}/secrets/{field}/reveal` | ADMIN_SESSION | get_database, require_settings_admin |
| `PATCH` | `/api/admin/settings/runtime` | ADMIN_SESSION | get_database, require_settings_admin |
| `GET` | `/api/analysis-tasks/{task_id}` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/analysis/{analysis_id}` | READ_OWNER | get_database, get_current_user |
| `PUT` | `/api/analysis/{analysis_id}/shots` | WRITE_FENCE | get_business_db |
| `GET` | `/api/assets/character-cache/{cache_name}` | PUBLIC_SIGNED | — |
| `GET` | `/api/assets/local-objects/{object_key:path}` | PUBLIC_SIGNED | get_database, get_media_storage |
| `PUT` | `/api/assets/local-objects/{object_key:path}` | READ_OWNER | get_database, get_current_user, get_media_storage |
| `GET` | `/api/assets/signed-objects/{object_key:path}` | PUBLIC_SIGNED | — |
| `POST` | `/api/assets/upload-intent` | WRITE_FENCE | get_business_db, get_media_storage |
| `GET` | `/api/assets/{asset_id}` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/assets/{asset_id}/cached-url` | WRITE_FENCE | get_business_db |
| `POST` | `/api/assets/{asset_id}/complete` | WRITE_FENCE | get_business_db, get_media_storage, get_video_probe |
| `POST` | `/api/assets/{asset_id}/download-url` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/audit-logs` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/auth/me` | READ_OWNER | get_database |
| `POST` | `/api/character-assets/{character_asset_id}/regenerate` | ADMIN_SESSION | get_database, get_character_admin |
| `POST` | `/api/character-assets/{character_asset_id}/review` | ADMIN_SESSION | get_database, get_character_admin |
| `GET` | `/api/character-assets/{character_asset_id}/reviews` | READ_OWNER | get_database, get_current_user |
| `DELETE` | `/api/character-personas/{persona_id}` | ADMIN_SESSION | get_database, get_character_admin |
| `GET` | `/api/character-personas/{persona_id}` | READ_OWNER | get_database, get_current_user |
| `PATCH` | `/api/character-personas/{persona_id}` | ADMIN_SESSION | get_database, get_character_admin |
| `GET` | `/api/character-personas/{persona_id}/versions` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/character-personas/{persona_id}/versions` | ADMIN_SESSION | get_database, get_character_admin |
| `GET` | `/api/character-versions/{version_id}` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/character-versions/{version_id}/archive` | ADMIN_SESSION | get_database, get_character_admin |
| `GET` | `/api/character-versions/{version_id}/assets` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/character-versions/{version_id}/generate-assets` | ADMIN_SESSION | get_database, get_character_admin |
| `GET` | `/api/character-versions/{version_id}/generation-tasks` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/character-versions/{version_id}/publish` | ADMIN_SESSION | get_database, get_character_admin, get_character_storage |
| `GET` | `/api/characters` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/characters` | READ_OWNER | get_database, get_current_user |
| `DELETE` | `/api/characters/{character_id}` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/characters/{character_id}` | READ_OWNER | get_database, get_current_user |
| `PATCH` | `/api/characters/{character_id}` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/control/accounts` | ADMIN_SESSION | get_database, get_control_route_user |
| `POST` | `/api/control/activation-code-batches` | ADMIN_SESSION | get_admin_writer |
| `POST` | `/api/control/activation-code-batches/{batch_id}/generate` | ADMIN_SESSION | get_admin_writer |
| `POST` | `/api/control/activation-code-exports/{export_id}/download` | ADMIN_SESSION | get_admin_writer |
| `GET` | `/api/control/activation-codes` | ADMIN_SESSION | get_admin_actor |
| `POST` | `/api/control/activation-codes/{code_id}/archive` | ADMIN_SESSION | get_admin_writer |
| `POST` | `/api/control/activation-codes/{code_id}/deliver` | ADMIN_SESSION | get_admin_writer |
| `POST` | `/api/control/activation-codes/{code_id}/resume` | ADMIN_SESSION | get_admin_writer |
| `POST` | `/api/control/activation-codes/{code_id}/reveal` | ADMIN_SESSION | get_admin_writer |
| `POST` | `/api/control/activation-codes/{code_id}/revoke` | ADMIN_SESSION | get_admin_writer |
| `POST` | `/api/control/activation-codes/{code_id}/suspend` | ADMIN_SESSION | get_admin_writer |
| `GET` | `/api/control/adjustments` | ADMIN_SESSION | get_admin_actor |
| `PUT` | `/api/control/admin/password` | ADMIN_SESSION | get_admin_writer |
| `DELETE` | `/api/control/admin/session` | ADMIN_SESSION | get_admin_actor |
| `GET` | `/api/control/admin/session` | ADMIN_SESSION | get_admin_actor |
| `POST` | `/api/control/admin/session/exchange` | ADMIN_SESSION | — |
| `POST` | `/api/control/admin/session/password` | ADMIN_SESSION | — |
| `GET` | `/api/control/audit-log` | ADMIN_SESSION | get_admin_actor |
| `GET` | `/api/control/billing-reconciliation` | ADMIN_SESSION | get_database, get_control_route_user |
| `GET` | `/api/control/customer-sessions/live` | ADMIN_SESSION | get_admin_actor |
| `POST` | `/api/control/customer-sessions/{session_id}/revoke` | ADMIN_SESSION | get_admin_writer |
| `GET` | `/api/control/customers` | ADMIN_SESSION | get_admin_actor |
| `GET` | `/api/control/customers.csv` | ADMIN_SESSION | get_admin_writer |
| `GET` | `/api/control/customers/{user_id}/adjustments` | ADMIN_SESSION | get_admin_actor |
| `POST` | `/api/control/customers/{user_id}/adjustments` | ADMIN_SESSION | get_admin_writer |
| `GET` | `/api/control/customers/{user_id}/sessions` | ADMIN_SESSION | get_admin_actor |
| `GET` | `/api/control/customers/{user_id}/unit-price` | ADMIN_SESSION | get_admin_actor |
| `PUT` | `/api/control/customers/{user_id}/unit-price` | ADMIN_SESSION | get_admin_writer |
| `GET` | `/api/control/dashboard/summary` | ADMIN_SESSION | get_admin_actor |
| `GET` | `/api/control/device-pairings/{pairing_id}` | ADMIN_SESSION | get_admin_actor |
| `POST` | `/api/control/device-pairings/{pairing_id}/approve` | ADMIN_SESSION | get_admin_writer |
| `POST` | `/api/control/device-pairings/{pairing_id}/replace-device` | ADMIN_SESSION | get_admin_writer |
| `GET` | `/api/control/devices` | ADMIN_SESSION | get_admin_actor |
| `POST` | `/api/control/devices/{device_id}/revoke-credential` | ADMIN_SESSION | get_admin_writer |
| `POST` | `/api/control/devices/{device_id}/unbind` | ADMIN_SESSION | get_admin_writer |
| `GET` | `/api/control/generation-records` | ADMIN_SESSION | get_database, get_control_route_user |
| `GET` | `/api/control/profit/costs` | ADMIN_SESSION | get_admin_actor |
| `GET` | `/api/control/profit/costs.csv` | ADMIN_SESSION | get_admin_actor |
| `PUT` | `/api/control/profit/daily-price` | ADMIN_SESSION | get_admin_writer |
| `GET` | `/api/control/profit/overview` | ADMIN_SESSION | get_admin_actor |
| `GET` | `/api/control/profit/overview.csv` | ADMIN_SESSION | get_admin_actor |
| `GET` | `/api/control/recharge-orders` | ADMIN_SESSION | get_database, get_control_route_user |
| `GET` | `/api/control/recharge-orders.csv` | ADMIN_SESSION | get_database, get_control_route_user |
| `POST` | `/api/control/recharge-orders/{order_no}/sync` | ADMIN_SESSION | get_database, get_control_route_user, get_zpay_order_query_client |
| `GET` | `/api/control/settings` | ADMIN_SESSION | get_database, get_control_route_user |
| `PATCH` | `/api/control/settings/billing` | ADMIN_SESSION | get_database, get_control_route_user |
| `PUT` | `/api/control/settings/providers/{provider}` | ADMIN_SESSION | get_database, get_control_route_user |
| `POST` | `/api/control/settings/providers/{provider}/connection-test` | ADMIN_SESSION | get_database, get_control_route_user, get_provider_tester |
| `GET` | `/api/control/settings/queue-mode` | ADMIN_SESSION | get_admin_actor |
| `PATCH` | `/api/control/settings/queue-mode` | ADMIN_SESSION | get_admin_writer |
| `GET` | `/api/control/settings/rates` | ADMIN_SESSION | get_admin_actor |
| `PUT` | `/api/control/settings/rates` | ADMIN_SESSION | get_admin_writer |
| `GET` | `/api/control/settings/rates/history` | ADMIN_SESSION | get_admin_actor |
| `PATCH` | `/api/control/settings/runtime` | ADMIN_SESSION | get_database, get_control_route_user |
| `GET` | `/api/control/settings/viral` | ADMIN_SESSION | get_admin_actor |
| `PATCH` | `/api/control/settings/viral` | ADMIN_SESSION | get_admin_writer |
| `PATCH` | `/api/control/settings/zpay` | ADMIN_SESSION | get_database, get_control_route_user |
| `PATCH` | `/api/control/viral/videos/{platform}/{video_id:path}/availability` | ADMIN_SESSION | get_admin_writer |
| `GET` | `/api/control/wallet-transactions` | ADMIN_SESSION | get_database, get_control_route_user |
| `GET` | `/api/control/wallet-transactions.csv` | ADMIN_SESSION | get_database, get_control_route_user |
| `POST` | `/api/customer/activate` | SESSION_LIFECYCLE | — |
| `POST` | `/api/customer/activation-code/reset` | SESSION_LIFECYCLE | — |
| `DELETE` | `/api/customer/device-pairings/{pairing_id}` | SESSION_LIFECYCLE | — |
| `POST` | `/api/customer/device-pairings/{pairing_id}/approve` | SESSION_LIFECYCLE | — |
| `GET` | `/api/customer/devices` | SESSION_LIFECYCLE | — |
| `POST` | `/api/customer/devices/enroll` | SESSION_LIFECYCLE | — |
| `DELETE` | `/api/customer/devices/{device_id}` | SESSION_LIFECYCLE | — |
| `GET` | `/api/customer/profile` | SESSION_LIFECYCLE | — |
| `PATCH` | `/api/customer/profile` | SESSION_LIFECYCLE | — |
| `GET` | `/api/customer/recharge-orders` | SESSION_LIFECYCLE | — |
| `POST` | `/api/customer/recharge-orders` | WRITE_FENCE | get_business_db |
| `DELETE` | `/api/customer/recharge-orders/{order_no}` | SESSION_LIFECYCLE | — |
| `GET` | `/api/customer/recharge-orders/{order_no}` | SESSION_LIFECYCLE | — |
| `POST` | `/api/customer/recharge-orders/{order_no}/payment-code` | SESSION_LIFECYCLE | get_zpay_payment_code_client |
| `POST` | `/api/customer/sessions/heartbeat` | SESSION_LIFECYCLE | — |
| `POST` | `/api/customer/sessions/login` | SESSION_LIFECYCLE | — |
| `POST` | `/api/customer/sessions/logout` | SESSION_LIFECYCLE | — |
| `POST` | `/api/customer/sessions/switch` | SESSION_LIFECYCLE | — |
| `GET` | `/api/customer/wallet` | SESSION_LIFECYCLE | — |
| `GET` | `/api/customer/wallet/transactions` | SESSION_LIFECYCLE | — |
| `GET` | `/api/first-frame-tasks/{task_id}` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/generation-batches` | READ_OWNER | get_database, get_current_user |
| `DELETE` | `/api/generation-batches/{batch_id}` | WRITE_FENCE | get_business_db |
| `GET` | `/api/generation-batches/{batch_id}` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/generation-batches/{batch_id}/cancel` | WRITE_FENCE | get_business_db |
| `PATCH` | `/api/generation-batches/{batch_id}/name` | WRITE_FENCE | get_business_db |
| `POST` | `/api/generation-batches/{batch_id}/regenerate` | WRITE_FENCE | get_business_db |
| `GET` | `/api/generation-reconcile-operations/{operation_id}` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/generation-tasks/{task_id}/confirm-not-charged` | WRITE_FENCE | get_business_db |
| `GET` | `/api/generation-tasks/{task_id}/preview-url` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/generation-tasks/{task_id}/reconcile` | WRITE_FENCE | get_business_db |
| `GET` | `/api/generation-tasks/{task_id}/reconcile/latest` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/generation-tasks/{task_id}/regenerate` | WRITE_FENCE | get_business_db |
| `POST` | `/api/generation-tasks/{task_id}/retry` | WRITE_FENCE | get_business_db |
| `GET` | `/api/generation/price-quote` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/generation/runtime-limits` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/independent/capabilities` | PUBLIC_SIGNED | get_database |
| `POST` | `/api/independent/video-tasks` | WRITE_FENCE | get_business_db |
| `GET` | `/api/oral/avatars` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/oral/avatars` | WRITE_FENCE | get_business_db |
| `POST` | `/api/oral/avatars/{avatar_id}/refresh` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/oral/consents` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/oral/consents` | WRITE_FENCE | get_business_db |
| `GET` | `/api/oral/price` | PUBLIC_SIGNED | get_database |
| `GET` | `/api/oral/tasks` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/oral/tasks` | WRITE_FENCE | get_business_db |
| `GET` | `/api/oral/tasks/{task_id}` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/oral/tasks/{task_id}/archive-retry` | WRITE_FENCE | get_business_db |
| `POST` | `/api/oral/tasks/{task_id}/billing-reconcile` | WRITE_FENCE | get_business_db |
| `POST` | `/api/oral/tasks/{task_id}/cancel` | WRITE_FENCE | get_business_db |
| `POST` | `/api/oral/tasks/{task_id}/refresh` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/oral/voices` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/oral/voices` | WRITE_FENCE | get_business_db |
| `POST` | `/api/oral/voices/{voice_id}/confirm` | WRITE_FENCE | get_business_db |
| `POST` | `/api/oral/voices/{voice_id}/refresh` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/payments/zpay/notify` | PAYMENT_CALLBACK | get_database |
| `GET` | `/api/payments/zpay/return` | PAYMENT_CALLBACK | — |
| `GET` | `/api/person-identities` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/person-identities` | ADMIN_SESSION | get_database, get_character_admin |
| `GET` | `/api/person-identities/{identity_id}` | READ_OWNER | get_database, get_current_user |
| `PATCH` | `/api/person-identities/{identity_id}` | ADMIN_SESSION | get_database, get_character_admin |
| `POST` | `/api/person-identities/{identity_id}/authorization-upload-complete` | ADMIN_SESSION | get_database, get_character_admin, get_character_storage |
| `POST` | `/api/person-identities/{identity_id}/authorization-upload-intent` | ADMIN_SESSION | get_database, get_character_admin, get_character_storage |
| `GET` | `/api/person-identities/{identity_id}/personas` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/person-identities/{identity_id}/personas` | ADMIN_SESSION | get_database, get_character_admin |
| `POST` | `/api/person-identities/{identity_id}/source-upload-complete` | ADMIN_SESSION | get_database, get_character_admin, get_character_storage, get_source_image_inspector |
| `POST` | `/api/person-identities/{identity_id}/source-upload-intent` | ADMIN_SESSION | get_database, get_character_admin, get_character_storage |
| `GET` | `/api/projects` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/projects` | WRITE_FENCE | get_business_db |
| `DELETE` | `/api/projects/{project_id}` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/projects/{project_id}` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/projects/{project_id}/analysis` | WRITE_FENCE | require_async_analysis_route, get_business_db |
| `POST` | `/api/projects/{project_id}/analysis-tasks` | WRITE_FENCE | get_business_db |
| `GET` | `/api/projects/{project_id}/analysis/latest` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/projects/{project_id}/character-reference-recommendation` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/projects/{project_id}/character-reference-selection` | WRITE_FENCE | get_business_db |
| `GET` | `/api/projects/{project_id}/character-reference-selection/latest` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/projects/{project_id}/character-versions/available` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/projects/{project_id}/first-frame-tasks` | WRITE_FENCE | get_business_db |
| `GET` | `/api/projects/{project_id}/first-frame-tasks/active-or-latest` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/projects/{project_id}/first-frames/confirm` | WRITE_FENCE | get_business_db |
| `POST` | `/api/projects/{project_id}/first-frames/generate` | WRITE_FENCE | require_async_first_frame_route, get_media_storage, get_image_provider, get_first_frame_quality_inspector, get_business_db |
| `GET` | `/api/projects/{project_id}/first-frames/history` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/projects/{project_id}/first-frames/latest` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/projects/{project_id}/first-frames/selection/latest` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/projects/{project_id}/generation-batches` | WRITE_FENCE | get_business_db, get_h3_provider |
| `GET` | `/api/projects/{project_id}/main-character` | READ_OWNER | get_database, get_current_user |
| `PUT` | `/api/projects/{project_id}/main-character` | WRITE_FENCE | get_business_db |
| `PATCH` | `/api/projects/{project_id}/name` | WRITE_FENCE | get_business_db |
| `POST` | `/api/projects/{project_id}/prompts/compile` | WRITE_FENCE | get_business_db |
| `GET` | `/api/projects/{project_id}/prompts/latest` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/projects/{project_id}/prompts/preview` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/projects/{project_id}/prompts/revise` | WRITE_FENCE | get_business_db |
| `POST` | `/api/projects/{project_id}/prompts/{prompt_version_id}/lock` | WRITE_FENCE | get_business_db |
| `GET` | `/api/projects/{project_id}/saved-prompts` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/projects/{project_id}/saved-prompts` | WRITE_FENCE | get_business_db |
| `POST` | `/api/projects/{project_id}/saved-prompts/{saved_prompt_id}/apply` | WRITE_FENCE | get_business_db |
| `POST` | `/api/projects/{project_id}/script-from-audio` | WRITE_FENCE | get_business_db |
| `GET` | `/api/projects/{project_id}/script-from-audio-tasks/latest` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/projects/{project_id}/script-rewrite` | WRITE_FENCE | get_business_db |
| `GET` | `/api/projects/{project_id}/script-rewrite-tasks/latest` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/projects/{project_id}/scripts` | WRITE_FENCE | get_business_db |
| `GET` | `/api/projects/{project_id}/scripts/latest` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/projects/{project_id}/shot-cards/latest` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/projects/{project_id}/source-frame-tasks/latest` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/projects/{project_id}/source-frames/confirm` | WRITE_FENCE | get_business_db |
| `POST` | `/api/projects/{project_id}/source-frames/extract` | WRITE_FENCE | get_business_db |
| `GET` | `/api/projects/{project_id}/source-frames/latest` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/projects/{project_id}/source-frames/selection/latest` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/recharge-orders` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/recharge-orders` | WRITE_FENCE | get_business_db |
| `GET` | `/api/recharge-orders/{order_no}` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/script-from-audio-tasks/{task_id}` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/script-rewrite-tasks/{task_id}` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/simple-characters/generate` | WRITE_FENCE | require_async_global_character_route, get_character_storage, get_image_provider, get_business_db |
| `DELETE` | `/api/simple-characters/identities/{identity_id}` | WRITE_FENCE | get_business_db |
| `PATCH` | `/api/simple-characters/identities/{identity_id}/name` | WRITE_FENCE | get_business_db |
| `PATCH` | `/api/simple-characters/identities/{identity_id}/profile` | WRITE_FENCE | get_business_db |
| `POST` | `/api/simple-characters/identities/{identity_id}/regenerate-contact-sheet` | WRITE_FENCE | require_async_character_regeneration_route, get_character_storage, get_image_provider, get_business_db |
| `POST` | `/api/simple-characters/identities/{identity_id}/regenerate-contact-sheet-task` | WRITE_FENCE | get_business_db |
| `GET` | `/api/simple-characters/identities/{identity_id}/scene-looks` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/simple-characters/identities/{identity_id}/scene-looks/tasks/active-or-latest` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/simple-characters/identities/{identity_id}/scene-looks/tasks/generate` | WRITE_FENCE | get_business_db |
| `GET` | `/api/simple-characters/library` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/simple-characters/task-status/{task_id}` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/simple-characters/tasks/active-or-latest` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/simple-characters/tasks/generate` | WRITE_FENCE | get_character_storage, get_business_db |
| `POST` | `/api/simple-characters/tasks/{project_id}/generate` | WRITE_FENCE | get_character_storage, get_business_db |
| `POST` | `/api/simple-characters/upload-intent` | READ_OWNER | get_current_user |
| `POST` | `/api/simple-characters/{project_id}/generate` | WRITE_FENCE | require_async_project_character_route, get_character_storage, get_image_provider, get_business_db |
| `GET` | `/api/source-frame-tasks/{task_id}` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/source-frame-tasks/{task_id}/cancel` | WRITE_FENCE | get_business_db |
| `GET` | `/api/studio/analytics` | READ_OWNER | get_database, get_current_user |
| `DELETE` | `/api/studio/drafts/{draft_kind}` | WRITE_FENCE | get_business_db |
| `GET` | `/api/studio/drafts/{draft_kind}` | READ_OWNER | get_database, get_current_user |
| `PUT` | `/api/studio/drafts/{draft_kind}` | WRITE_FENCE | get_business_db |
| `GET` | `/api/studio/materials` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/studio/materials/resolve` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/studio/materials/upload-intent` | WRITE_FENCE | get_business_db, get_media_storage |
| `POST` | `/api/studio/materials/uploads/{asset_id}/complete` | WRITE_FENCE | get_business_db, get_media_storage |
| `PUT` | `/api/studio/materials/uploads/{asset_id}/content` | READ_OWNER | get_database, get_current_user, get_media_storage |
| `DELETE` | `/api/studio/materials/{material_id}` | WRITE_FENCE | get_business_db |
| `PATCH` | `/api/studio/materials/{material_id}` | WRITE_FENCE | get_business_db |
| `GET` | `/api/studio/notification-preferences` | READ_OWNER | get_database, get_current_user |
| `PUT` | `/api/studio/notification-preferences` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/studio/saved-prompts` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/studio/saved-scripts` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/studio/saved-scripts` | WRITE_FENCE | get_business_db |
| `DELETE` | `/api/studio/saved-scripts/{script_id}` | WRITE_FENCE | get_business_db |
| `GET` | `/api/studio/stats` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/viral/covers/{platform}/{video_id:path}` | PUBLIC_SIGNED | get_database |
| `GET` | `/api/viral/favorites` | READ_OWNER | get_database, get_current_user |
| `DELETE` | `/api/viral/favorites/{platform}/{video_id:path}` | WRITE_FENCE | get_business_db |
| `PUT` | `/api/viral/favorites/{platform}/{video_id:path}` | WRITE_FENCE | get_business_db |
| `POST` | `/api/viral/import-tasks` | WRITE_FENCE | get_business_db |
| `GET` | `/api/viral/import-tasks/{task_id}` | READ_OWNER | get_database, get_current_user |
| `POST` | `/api/viral/link-resolutions` | WRITE_FENCE | get_business_db |
| `GET` | `/api/viral/videos` | READ_OWNER | get_database, get_current_user, get_viral_source_client |
| `POST` | `/api/viral/videos/import-tasks` | WRITE_FENCE | get_business_db |
| `POST` | `/api/viral/videos/media` | READ_OWNER | get_database, get_current_user, get_viral_source_client |
| `GET` | `/api/viral/videos/media/file` | PUBLIC_SIGNED | get_database |
| `POST` | `/api/viral/videos/statistics` | READ_OWNER | get_database, get_current_user, get_viral_source_client |
| `GET` | `/api/viral/videos/{platform}/{video_id:path}` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/wallet` | READ_OWNER | get_database, get_current_user |
| `GET` | `/api/wallet/transactions` | READ_OWNER | get_database, get_current_user |
| `GET` | `/health` | PUBLIC_INFRA | — |
| `GET` | `/live` | PUBLIC_INFRA | — |
| `GET` | `/metrics` | PUBLIC_INFRA | — |
| `GET` | `/ready` | PUBLIC_INFRA | — |

## 7. Section 14 Ledger Record

```text
任务/工作包：CW-026 / W4 代码与测试增量（退出内部认证并复验客户fencing）
Owner / Reviewer：ZCode 全链路代理（用户 2026-09-11 指令授权 026→030 顺序开发与 PR squash 合并）/ 待 PR 独立评审 + CI 三门禁
分支 / 基线 SHA：feat/customer-v3-cw026-exit-internal-auth-fencing / origin/main@e829ad1a6d859a51ae804a7cd31cc5513b393cb9
上游规格段落：V3 收敛清单 CW-026 行（remaining_work/acceptance_delta/retained_acceptance/completion_delta）；任务账本 §18；排班清单 §3—§7；AGENTS.md 标准工作流 1—6 条
改动文件：server/app/auth.py（authenticate_request 收敛 PG 通道、删除 _customer_production_lane 豁免）；server/tests/test_cw026_converged_auth.py（新增 14 用例：身份矩阵/遗留通道护栏/读 owner/迟到写三变体/幂等重放再授权/路由分类矩阵）；server/tests/test_internal_access_tokens.py（false 分支改为断言拒绝）；server/tests/test_independent_creation.py（1 用例迁客户会话）；server/tests/test_oral_domain.py（3 用例迁依赖覆盖）；docs/客户版任务清单-V3.md §18；docs/CUSTOMER-TASK-EVIDENCE-V3.md；docs/客户版代码开发清单-V3.md；本文件
失败测试或回归锁定：RED 5 failed（还原 auth.py 后精确复现旧豁免行为）；新增 test_legacy_sqlite_lane_keeps_internal_and_dev_identity 反向钉住 CW-026 未越界到内部遗留通道；test_every_business_method_path_is_classified_zero_misses 钉住「新增未分类路由即失败」
实现结果：收敛 PG 通道在全部环境仅接受客户会话 Bearer；internal Bearer/X-Dev-User-Id/桌面身份在收敛运行方式不可达；fencing 迟到写 0 副作用；幂等重放再授权
验证命令与通过数：见 §4 表（专项 14+148+142+78 passed；静态门 secret/ruff/format/mypy 全绿；分片全量见 §7 记录）
证据层级：AUTOMATED_VERIFIED（真实 PG16 fixture；真实链路验收归 CW-050，不提升 STAGING）
安全与可观测性：无真实 secret 入代码/日志/夹具（测试密钥均 secrets.token_urlsafe 运行时生成）；矩阵测试把「未分类新路由」变成红灯；7 个 PUBLIC_SIGNED 豁免逐一登记依据
迁移与回滚：无迁移改动（迁移文件名冻结红线未触碰）；回滚 = revert 本分支单提交
外部授权记录：用户指令授权本任务 PR 的创建与 squash 合并；未触碰真实 ZPay/付费 Provider/生产 COS/发码/灰度/公网发布
未测试项：客户浏览器 E2E、cargo test、npm audit、npm run build（本机无 cargo；CI 三门禁承载）；STAGING_VERIFIED 及以上层级
Lore 提交 SHA：见 claim.json 与 PR 登记（不写入本文件，防自指过期）
```
