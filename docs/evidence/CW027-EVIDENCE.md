# CW-027 证据 — 复用管理后台并收口权限差额（复验）

> 状态：`AUTOMATED_VERIFIED`（真实 PG 16.15 fixture 上执行；管理端真实 UAT 归 CW-049，不提升 `STAGING_VERIFIED`）。
> 分支 `feat/customer-v3-cw027-admin-console-permission-matrix`，基线 `origin/main@eea767e`（CW-026 #20 已合入；前置 CW-019 #12、CW-026 #20 均已入 main）。
> 本任务为**复验**：不重写后台鉴权；按保留操作清单核验全部写路由确实使用 AdminWriter/写合同，仅在发现漏接路由时修复。**核验结论：84 条管理 method-path 全部携带管理级权限，漏项=0，未发现漏接路由，零生产代码改动。**

## 1. 任务与范围

- 任务/工作包：CW-027 / W4 复验（管理后端负责人）。
- 上游规格：V3 收敛清单 §CW-027；任务账本 §18 CW-027 行；排班清单 §3—§7；AGENTS.md 标准工作流。
- 查重（2026-09-11 fetch 后）：无 cw027 本地/远程分支、无同编号 PR（开放 PR 仅 CW-021 #21 / CW-057 #19 / docs #16，均他人任务）、`.git/codex-task-claims/CW-027/` 原子新建成功。
- 剔除重复开发（按规格）：管理网页视觉与客户端制品隔离归前端/打包任务；真实生产角色 UAT 归 CW-047—050；收敛前内部 P0 proxy 兼容路径的物理删除归 CW-041/042。

## 2. 静态核销表（operation→route→AdminReader/AdminWriter，漏项=0）

84 条管理 method-path（/api/control/*、/api/admin/*、person-identities/character-assets/character-personas/character-versions 管理面）按读/写两轴核销：

| 核销类别 | 条数 | 说明 |
| --- | --- | --- |
| WRITE:get_admin_writer | 22 | 激活码/客户/设备/会话吊销/费率/运营位等管理写（auditor 403 AUDITOR_READ_ONLY） |
| WRITE:get_control_route_user | 6 | 客户生产下经 admin session + 写方法强制 AdminWriter；内部 lane 走 proxy 兼容（CW-041 退出） |
| WRITE:require_settings_admin | 7 | /api/admin/settings/*（业务身份 + admin 角色门；客户会话 403） |
| WRITE:get_character_admin | 15 | 人物资产/人格/版本管理写（同上，客户会话 403） |
| READ:get_admin_actor | 20 | 会话 cookie 读门（写方法自动叠加 CSRF 校验） |
| READ:get_control_route_user | 8 | control 只读（账单/流水/导出/生成记录） |
| READ:require_settings_admin | 2 | /api/admin/settings 只读 |
| READ:get_admin_writer | 1 | GET customers.csv（导出按写级把关，比规格更严，合规） |
| SELF_SCOPED(logout) | 1 | DELETE /api/control/admin/session：自作用域登出（actor.session_id），读级依赖即正确；auditor 可自助登出（动态钉住） |
| BOOTSTRAP | 2 | POST session/exchange、POST session/password：会话建立前入口，全表仅有的两条无依赖管理路由 |

完整逐条核销表见 §5；**静态矩阵测试** `test_every_admin_method_path_carries_an_admin_authority` 使「新增未分类管理路由」直接红灯（漏项≠0 即失败）。

## 3. 动态底线矩阵（TEST-PG，0 fail / 0 skip）

`tests/test_cw027_admin_permission_matrix.py`（8 用例，专用库 `cw027_admin_matrix_test`，隔离容器 vs-pg-cw027:5438）：

| 底线 | 用例与结果 |
| --- | --- |
| 管理写成功且 actor/reason 可追溯 | admin session + CSRF 下 POST adjustments → 201；admin_write_idempotency 记录真实 actor=admin_u；append-only admin_adjustments 行含 admin_user_id 与 reason（中文原因逐字落库） |
| 幂等重放不重复记账 | 同 Idempotency-Key 重放 → X-Idempotent-Replay: true，ADJ-% 订单与 CHARGE 账务行各恰 1 条 |
| 写合同三要素 | 缺 confirm → 400 CONFIRMATION_REQUIRED；空 reason → 400 REASON_REQUIRED；无会话+CSRF → 403 ADMIN_CSRF_REQUIRED |
| CSRF 缺失/错值 | 无头 403 ADMIN_CSRF_REQUIRED；错值 403 ADMIN_CSRF_INVALID |
| auditor 严格只读 | 读 200；写 403 AUDITOR_READ_ONLY；**auditor 自助登出允许**（豁免的动态验证），登出后原 cookie 立即 401 |
| 客户凭据无法管理写 | 客户会话 Bearer 打 session 门管理路由 → 401（非 cookie 凭据）；打角色门（settings admin）→ 403 |
| 过期/吊销会话 | 过期交换凭据 401 EXCHANGE_CREDENTIAL_INVALID；登出后会话复用 → 401（不可重放） |
| 旧 proxy 身份 lane 分裂 | 非客户生产：CONTROL_AUTH_INVALID 401（测试摘要不匹配即 fail-closed，lane 仍按 CW-041 前口径保留）；客户生产：proxy 头被完全忽略（无 cookie → 401 ADMIN_SESSION_INVALID），永不恢复共享管理员权限；生产唯一钥匙是逐操作者 admin session |

## 4. 验证命令与通过数（本机 Windows + Docker PG 16.15 vs-pg-cw027:5438）

| 验证 | 结果 |
| --- | --- |
| `pytest tests/test_cw027_admin_permission_matrix.py` | 8 passed |
| `pytest tests/test_cw027_admin_permission_matrix.py tests/test_admin_auth.py tests/test_admin_session_routes.py` | 113 passed（既有管理套件零回归） |
| `bash scripts/verify_no_secrets.sh` | exit 0 |
| `ruff check server` / `ruff format --check server` | All checks passed / 300 files already formatted |
| `mypy server/app` | Success: no issues found in 104 source files |
| 既有管理套件规模（main CI 全量已绿） | test_admin_auth 55 + admin_activation 55 + admin_customer 53 + admin_session 16 + admin_audit 13 + admin_profit 11 + admin_rate 7 + admin_dashboard 5 |

## 5. 逐条核销矩阵

| 方法 | 路径 | 权限核销 | 依赖 |
| --- | --- | --- | --- |
| `GET` | `/api/admin/settings` | READ:require_settings_admin | get_database, require_settings_admin |
| `PATCH` | `/api/admin/settings/billing` | WRITE:require_settings_admin | get_database, require_settings_admin |
| `GET` | `/api/admin/settings/diagnostic-reports/{report_id}/download` | READ:require_settings_admin | get_database, require_settings_admin |
| `POST` | `/api/admin/settings/diagnostic-test` | WRITE:require_settings_admin | get_database, require_settings_admin, get_provider_tester |
| `PUT` | `/api/admin/settings/providers/{provider}` | WRITE:require_settings_admin | get_database, require_settings_admin |
| `POST` | `/api/admin/settings/providers/{provider}/connection-test` | WRITE:require_settings_admin | get_database, require_settings_admin, get_provider_tester |
| `POST` | `/api/admin/settings/providers/{provider}/paid-test` | WRITE:require_settings_admin | get_database, require_settings_admin, get_provider_tester |
| `POST` | `/api/admin/settings/providers/{provider}/secrets/{field}/reveal` | WRITE:require_settings_admin | get_database, require_settings_admin |
| `PATCH` | `/api/admin/settings/runtime` | WRITE:require_settings_admin | get_database, require_settings_admin |
| `POST` | `/api/character-assets/{character_asset_id}/regenerate` | WRITE:get_character_admin | get_database, get_character_admin |
| `POST` | `/api/character-assets/{character_asset_id}/review` | WRITE:get_character_admin | get_database, get_character_admin |
| `DELETE` | `/api/character-personas/{persona_id}` | WRITE:get_character_admin | get_database, get_character_admin |
| `PATCH` | `/api/character-personas/{persona_id}` | WRITE:get_character_admin | get_database, get_character_admin |
| `POST` | `/api/character-personas/{persona_id}/versions` | WRITE:get_character_admin | get_database, get_character_admin |
| `POST` | `/api/character-versions/{version_id}/archive` | WRITE:get_character_admin | get_database, get_character_admin |
| `POST` | `/api/character-versions/{version_id}/generate-assets` | WRITE:get_character_admin | get_database, get_character_admin |
| `POST` | `/api/character-versions/{version_id}/publish` | WRITE:get_character_admin | get_database, get_character_admin, get_character_storage |
| `GET` | `/api/control/accounts` | READ:get_control_route_user | get_database, get_control_route_user |
| `POST` | `/api/control/activation-code-batches` | WRITE:get_admin_writer | get_admin_writer |
| `POST` | `/api/control/activation-code-batches/{batch_id}/generate` | WRITE:get_admin_writer | get_admin_writer |
| `POST` | `/api/control/activation-code-exports/{export_id}/download` | WRITE:get_admin_writer | get_admin_writer |
| `GET` | `/api/control/activation-codes` | READ:get_admin_actor | get_admin_actor |
| `POST` | `/api/control/activation-codes/{code_id}/archive` | WRITE:get_admin_writer | get_admin_writer |
| `POST` | `/api/control/activation-codes/{code_id}/deliver` | WRITE:get_admin_writer | get_admin_writer |
| `POST` | `/api/control/activation-codes/{code_id}/resume` | WRITE:get_admin_writer | get_admin_writer |
| `POST` | `/api/control/activation-codes/{code_id}/reveal` | WRITE:get_admin_writer | get_admin_writer |
| `POST` | `/api/control/activation-codes/{code_id}/revoke` | WRITE:get_admin_writer | get_admin_writer |
| `POST` | `/api/control/activation-codes/{code_id}/suspend` | WRITE:get_admin_writer | get_admin_writer |
| `GET` | `/api/control/adjustments` | READ:get_admin_actor | get_admin_actor |
| `PUT` | `/api/control/admin/password` | WRITE:get_admin_writer | get_admin_writer |
| `DELETE` | `/api/control/admin/session` | SELF_SCOPED(logout) | get_admin_actor |
| `GET` | `/api/control/admin/session` | READ:get_admin_actor | get_admin_actor |
| `POST` | `/api/control/admin/session/exchange` | BOOTSTRAP | — |
| `POST` | `/api/control/admin/session/password` | BOOTSTRAP | — |
| `GET` | `/api/control/audit-log` | READ:get_admin_actor | get_admin_actor |
| `GET` | `/api/control/billing-reconciliation` | READ:get_control_route_user | get_database, get_control_route_user |
| `GET` | `/api/control/customer-sessions/live` | READ:get_admin_actor | get_admin_actor |
| `POST` | `/api/control/customer-sessions/{session_id}/revoke` | WRITE:get_admin_writer | get_admin_writer |
| `GET` | `/api/control/customers` | READ:get_admin_actor | get_admin_actor |
| `GET` | `/api/control/customers.csv` | READ:get_admin_writer | get_admin_writer |
| `GET` | `/api/control/customers/{user_id}/adjustments` | READ:get_admin_actor | get_admin_actor |
| `POST` | `/api/control/customers/{user_id}/adjustments` | WRITE:get_admin_writer | get_admin_writer |
| `GET` | `/api/control/customers/{user_id}/sessions` | READ:get_admin_actor | get_admin_actor |
| `GET` | `/api/control/customers/{user_id}/unit-price` | READ:get_admin_actor | get_admin_actor |
| `PUT` | `/api/control/customers/{user_id}/unit-price` | WRITE:get_admin_writer | get_admin_writer |
| `GET` | `/api/control/dashboard/summary` | READ:get_admin_actor | get_admin_actor |
| `GET` | `/api/control/device-pairings/{pairing_id}` | READ:get_admin_actor | get_admin_actor |
| `POST` | `/api/control/device-pairings/{pairing_id}/approve` | WRITE:get_admin_writer | get_admin_writer |
| `POST` | `/api/control/device-pairings/{pairing_id}/replace-device` | WRITE:get_admin_writer | get_admin_writer |
| `GET` | `/api/control/devices` | READ:get_admin_actor | get_admin_actor |
| `POST` | `/api/control/devices/{device_id}/revoke-credential` | WRITE:get_admin_writer | get_admin_writer |
| `POST` | `/api/control/devices/{device_id}/unbind` | WRITE:get_admin_writer | get_admin_writer |
| `GET` | `/api/control/generation-records` | READ:get_control_route_user | get_database, get_control_route_user |
| `GET` | `/api/control/profit/costs` | READ:get_admin_actor | get_admin_actor |
| `GET` | `/api/control/profit/costs.csv` | READ:get_admin_actor | get_admin_actor |
| `PUT` | `/api/control/profit/daily-price` | WRITE:get_admin_writer | get_admin_writer |
| `GET` | `/api/control/profit/overview` | READ:get_admin_actor | get_admin_actor |
| `GET` | `/api/control/profit/overview.csv` | READ:get_admin_actor | get_admin_actor |
| `GET` | `/api/control/recharge-orders` | READ:get_control_route_user | get_database, get_control_route_user |
| `GET` | `/api/control/recharge-orders.csv` | READ:get_control_route_user | get_database, get_control_route_user |
| `POST` | `/api/control/recharge-orders/{order_no}/sync` | WRITE:get_control_route_user | get_database, get_control_route_user, get_zpay_order_query_client |
| `GET` | `/api/control/settings` | READ:get_control_route_user | get_database, get_control_route_user |
| `PATCH` | `/api/control/settings/billing` | WRITE:get_control_route_user | get_database, get_control_route_user |
| `PUT` | `/api/control/settings/providers/{provider}` | WRITE:get_control_route_user | get_database, get_control_route_user |
| `POST` | `/api/control/settings/providers/{provider}/connection-test` | WRITE:get_control_route_user | get_database, get_control_route_user, get_provider_tester |
| `GET` | `/api/control/settings/queue-mode` | READ:get_admin_actor | get_admin_actor |
| `PATCH` | `/api/control/settings/queue-mode` | WRITE:get_admin_writer | get_admin_writer |
| `GET` | `/api/control/settings/rates` | READ:get_admin_actor | get_admin_actor |
| `PUT` | `/api/control/settings/rates` | WRITE:get_admin_writer | get_admin_writer |
| `GET` | `/api/control/settings/rates/history` | READ:get_admin_actor | get_admin_actor |
| `PATCH` | `/api/control/settings/runtime` | WRITE:get_control_route_user | get_database, get_control_route_user |
| `GET` | `/api/control/settings/viral` | READ:get_admin_actor | get_admin_actor |
| `PATCH` | `/api/control/settings/viral` | WRITE:get_admin_writer | get_admin_writer |
| `PATCH` | `/api/control/settings/zpay` | WRITE:get_control_route_user | get_database, get_control_route_user |
| `PATCH` | `/api/control/viral/videos/{platform}/{video_id:path}/availability` | WRITE:get_admin_writer | get_admin_writer |
| `GET` | `/api/control/wallet-transactions` | READ:get_control_route_user | get_database, get_control_route_user |
| `GET` | `/api/control/wallet-transactions.csv` | READ:get_control_route_user | get_database, get_control_route_user |
| `POST` | `/api/person-identities` | WRITE:get_character_admin | get_database, get_character_admin |
| `PATCH` | `/api/person-identities/{identity_id}` | WRITE:get_character_admin | get_database, get_character_admin |
| `POST` | `/api/person-identities/{identity_id}/authorization-upload-complete` | WRITE:get_character_admin | get_database, get_character_admin, get_character_storage |
| `POST` | `/api/person-identities/{identity_id}/authorization-upload-intent` | WRITE:get_character_admin | get_database, get_character_admin, get_character_storage |
| `POST` | `/api/person-identities/{identity_id}/personas` | WRITE:get_character_admin | get_database, get_character_admin |
| `POST` | `/api/person-identities/{identity_id}/source-upload-complete` | WRITE:get_character_admin | get_database, get_character_admin, get_character_storage, get_source_image_inspector |
| `POST` | `/api/person-identities/{identity_id}/source-upload-intent` | WRITE:get_character_admin | get_database, get_character_admin, get_character_storage |

## 6. Section 14 Ledger Record

```text
任务/工作包：CW-027 / W4 复验（复用管理后台并收口权限差额）
Owner / Reviewer：ZCode 全链路代理（用户 2026-09-11 指令授权 026→030 顺序开发与 PR squash 合并）/ 待 PR 独立评审 + CI 三门禁
分支 / 基线 SHA：feat/customer-v3-cw027-admin-console-permission-matrix / origin/main@eea767e（CW-026 合并提交）
上游规格段落：V3 收敛清单 CW-027 行；任务账本 §18；排班清单 §3—§7；AGENTS.md 标准工作流 1—6 条
改动文件：server/tests/test_cw027_admin_permission_matrix.py（新增 8 用例：静态 84 条管理路由权限矩阵 + 动态底线网格）；docs/evidence/CW027-EVIDENCE.md（新增）；docs/CUSTOMER-TASK-EVIDENCE-V3.md（登记）；docs/客户版任务清单-V3.md §18；docs/客户版代码开发清单-V3.md（新文件登记）
失败测试或回归锁定：静态矩阵把「新增未分类管理路由」变成红灯；动态网格钉住 auditor 只读+自助登出豁免、CSRF/合同/幂等/过期吊销、客户凭据双 401/403、proxy 身份 lane 分裂
实现结果：核验结论——84 条管理 method-path 全部携带管理级权限，漏项=0，未发现漏接路由；按规格「若矩阵无漏接则以验收完成关闭，不另立重构」，零生产代码改动
验证命令与通过数：见 §4（新增 8 passed；既有管理套件 113 passed 零回归；静态门全绿；main 全量门由 CI 承载）
证据层级：AUTOMATED_VERIFIED（真实 PG16 fixture；真实生产角色 UAT 归 CW-049，不提升 STAGING）
安全与可观测性：无真实 secret 入代码/日志/夹具（测试密钥运行时生成，proxy 测试摘要为全零测试值并断言 fail-closed）；矩阵把未分类管理路由变成红灯
迁移与回滚：无迁移；回滚 = revert 本分支单提交（纯测试+文档）
外部授权记录：用户指令授权本任务 PR 的创建与 squash 合并；未触碰真实 ZPay/付费 Provider/生产 COS/发码/灰度/公网发布
未测试项：真实生产角色 UAT（CW-049）；管理网页视觉（前端任务）；cargo/npm audit/浏览器 E2E/npm build（本机无 cargo，交 CI 三门禁）；STAGING_VERIFIED 及以上层级
Lore 提交 SHA：见 claim.json 与 PR 登记
```
