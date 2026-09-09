# CW-009 — 保留路由安全要求矩阵（V3 规格 §6 requirement→test→method-path）

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-009 补齐保留路由的 PG 安全与 fencing 回归 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-09）；Reviewer：独立复核子代理 + PR review |
| 分支 / 基线 SHA | `feat/customer-v3-cw009-security-matrix`，叠放于 `feat/customer-v3-cw007-pg-test-foundation@96c77b1`（依赖其硬门与迁移成果；CW-007 合并后本 PR 改 base 即可独立评审） |
| 上游规格段落 | `docs/客户版测试与验收规格-V3.md` §6（9 条安全要求）；V3 清单 §4 CW-009 |
| 改动文件 | 新增 `server/tests/test_cw009_security_matrix_export.py`（已登记文件映射）、本矩阵文档、`docs/客户版代码开发清单-V3.md` CW-009 登记小节；追加 4 个缺口用例至 `test_security_contracts.py`、`test_admin_customer_routes.py`、`test_customer_devices.py`、`test_customer_sessions.py` |
| 失败测试或回归锁定 | 4 个新增用例即 S2/S4/S6 缺口的回归锁定；矩阵校验器锁定文档与测试套件的一致性 |
| 实现结果 | 9 条要求判定：8 FULL + S9 PARTIAL（缺口去向登记）；支付回调独立鉴权映射 FULL |
| 验证命令与通过数 | 新增用例 4/4 绿；矩阵校验 3/3 绿；受影响专项与全量门禁见 PR |
| 证据层级 | AUTOMATED_VERIFIED |
| 安全与可观测性 | 本矩阵即安全证据本体 |
| 迁移与回滚 | 纯测试与文档，revert 即回滚 |
| 外部授权记录 | 无 |
| 未测试项 | S4 材料措辞约束（流程项，归 CW-046/049 材料复核）；S9 Python 依赖审计（归 CW-044） |
| Lore 提交 SHA | 本 PR squash 后回填 |

> 机器可核销：本文件中所有 `文件::test_用例` 引用由 `server/tests/test_cw009_security_matrix_export.py`
> 自动校验真实存在——用例改名/删除而矩阵未同步时校验失败。判定口径：FULL=每个子项均有自动化断言；
> PARTIAL=有缺口（缺口行注明补偿或去向）。

## S1 激活码枚举/错误/过期/已激活近似响应与限流 — FULL

| 覆盖点 | 用例 | method-path |
| --- | --- | --- |
| 七类异常统一 400 不泄露子状态 | `test_activation_code_routes.py::test_activate_unavailable_is_unified` | POST `/api/customer/activate` |
| 429 + Retry-After | `test_customer_security.py::test_activate_returns_429_with_retry_after` | POST `/api/customer/activate` |
| 常量基线反枚举延迟 | `test_customer_security.py::test_anti_enumeration_delay_costs_a_constant_baseline`、`test_customer_security.py::test_unified_rejection_applies_anti_enumeration_delay` | POST `/api/customer/activate` |
| 码维度突发限流/IP 共享预算/幂等重放不耗预算/封锁 IP 不发计数行 | `test_customer_security.py::test_activate_code_dimension_blocks_code_burst`、`test_customer_security.py::test_malformed_requests_share_the_ip_budget`、`test_customer_security.py::test_idempotent_replay_spends_no_rate_limit_budget`、`test_customer_security.py::test_blocked_ip_mints_no_code_counter_rows` | POST `/api/customer/activate` |
| enroll 同样统一拒绝 | `test_customer_devices.py::test_enroll_rejects_unknown_code_unified`、`test_customer_devices.py::test_enroll_rejects_unactivated_code_unified` | POST `/api/customer/devices/enroll` |
| CORS 暴露 Retry-After | `test_customer_security.py::test_cors_exposes_retry_after` | OPTIONS/POST |

## S2 码/设备 token/session token 不进入日志、Sentry、CSV、dump、LocalStorage — FULL（本轮补齐）

| 介质 | 用例 | 说明 |
| --- | --- | --- |
| 日志 | `test_activation_code_routes.py::test_activate_never_logs_plaintext_code_or_credentials`、`test_admin_activation_routes.py::test_no_plaintext_code_in_logs_idempotency_snapshots_or_columns`、`test_customer_sessions.py::test_no_plaintext_credentials_in_session_events`、`test_customer_fencing.py::test_verify_never_leaks_the_token_or_digest`、`test_customer_security.py::test_failure_record_holds_no_plaintext_code`、`test_internal_access_tokens.py::test_issue_token_prints_raw_value_once_and_stores_only_digest`、`test_payments.py::test_zpay_query_client_never_logs_secret_or_request_url` | caplog/事件表/失败记录 |
| Sentry | `test_security_contracts.py::test_no_sentry_sdk_enters_the_server_runtime`（**CW-009 新增**） | 结构性缺席契约：无 SDK/无 DSN；引入即失败并强制补泄漏断言 |
| CSV | `test_admin_customer_routes.py::test_customer_code_materials_never_reach_control_csv_exports`（**CW-009 新增**）+ `test_internal_admin.py::test_control_reconciliation_and_csv_are_read_only` + `test_admin_customer_routes.py::test_customers_csv_export_is_audited_and_filtered` | 明文码与 digest 不得进入 customers.csv；merchant-secret 不进对账 CSV |
| 数据库 dump | `test_admin_activation_routes.py::test_no_plaintext_code_in_logs_idempotency_snapshots_or_columns`（DB 列介质）+ `test_customer_sessions.py::test_no_plaintext_credentials_in_session_events`（事件表） | dump 是存储行的重放：存储列只含 digest/token_digest 即等价覆盖 dump 介质 |
| LocalStorage | `client/src/customer/useCustomerSession.test.tsx`（"never writes a credential into Web Storage"） | 前端 vitest 套件 |

## S3 第二设备绑定候选摘要、批准不可转用 — FULL

| 覆盖点 | 用例 | method-path |
| --- | --- | --- |
| 批准绑定候选摘要、不可转用 | `test_customer_devices.py::test_pairing_approval_not_transferable` | POST `/api/customer/devices/enroll`、POST `/api/customer/device-pairings/{id}/approve` |
| 批准消费绑定 slot2/响应丢失重放 | `test_customer_devices.py::test_enroll_consumes_approved_pairing_binds_slot2`、`test_customer_devices.py::test_enroll_consume_response_loss_replays_credentials` | 同上 |
| 批准人记录/禁自批/未知或他人配对 404/中途吊销/消费后冲突/过期冲突/重复批准幂等 | `test_customer_devices.py::test_approve_happy_path_records_approver`、`test_customer_devices.py::test_approve_self_approval_rejected`、`test_customer_devices.py::test_approve_missing_or_foreign_pairing_not_found`、`test_customer_devices.py::test_approve_revoked_credential_mid_flight_rejected`、`test_customer_devices.py::test_approve_after_consumption_conflicts`、`test_customer_devices.py::test_approve_expired_conflicts`、`test_customer_devices.py::test_approve_repeated_returns_current_state` | POST `/api/customer/device-pairings/{id}/approve` |
| 非一设备拒绝批准 | `test_customer_devices.py::test_approve_rejects_non_first_device_while_first_bound`、`test_customer_devices.py::test_approve_rejects_slot2_after_first_device_unbound` | 同上 |
| 授权摘要证据持久化 | `test_customer_fencing.py::test_successful_project_owner_authorization_persists_digest_evidence` | 业务写路径 |

## S4 指纹重装/伪造被风控与审计捕获 — FULL（本轮补齐自动化；措辞约束为流程项）

| 覆盖点 | 用例 | method-path |
| --- | --- | --- |
| **伪造指纹被风控捕获** | `test_customer_devices.py::test_forged_fingerprint_is_caught_by_pairing_risk_control`（**CW-009 新增**） | POST `/api/customer/devices/enroll`：陌生指纹→独立 PENDING 配对（绑定候选摘要≠明文），BOUND 行数不变 |
| 同指纹重装恢复凭据、不重复扣费 | `test_customer_activation.py::test_active_code_same_fingerprint_recovers_credentials_without_duplicate_charge` | POST `/api/customer/activate` |
| 吊销后同指纹保持吊销 | `test_customer_activation.py::test_revoked_device_same_fingerprint_stays_revoked` | POST `/api/customer/activate` |
| 同指纹第二码冲突/轮换窗 | `test_activation_code_routes.py::test_activate_second_code_with_same_fingerprint_conflicts`、`test_activation_code_routes.py::test_fingerprint_rotation_window_blocks_second_activation`、`test_customer_activation.py::test_concurrent_second_code_same_fingerprint_one_success`、`test_customer_activation.py::test_rotation_window_cross_version_same_fingerprint_one_activation` | POST `/api/customer/activate` |
| 管理员换绑走审计 | `test_customer_devices.py::test_admin_replaces_bound_device_and_candidate_finishes_automatically`、`test_customer_devices.py::test_admin_device_events_append_only_and_no_truncate` | POST `/api/control/devices/{id}/replace` |

非自动化登记：验收材料措辞约束（不得宣称指纹为绝对物理设备证明）由规格 §2.1 条款 + CW-046/CW-049 验收材料复核承载，不设自动化断言。

## S5 CSRF、CORS、Host、Forwarded、cookie 属性、IDOR、跨用户 404 — FULL

| 覆盖点 | 用例 | method-path |
| --- | --- | --- |
| CSRF（缺/错 header 403） | `test_admin_auth.py::test_logout_requires_csrf_header`、`test_admin_activation_routes.py::test_write_rejects_missing_csrf_header`、`test_customer_devices.py::test_admin_write_contract_enforced`、`test_admin_session_routes.py::test_queue_mode_write_requires_write_contract` | DELETE `/api/control/admin/session`、POST `/api/control/activation-code-batches` 等 |
| cookie 属性（httponly/samesite=strict/path/Secure/digest 存储） | `test_admin_auth.py::test_exchange_issues_session_with_secure_cookie_shape`、`test_admin_auth.py::test_secure_cookie_in_customer_production` | POST `/api/control/admin/session/exchange` |
| Host/Forwarded 信任边界 | `test_customer_security.py::test_customer_ingress_accepts_only_trusted_single_forwarded_ip`、`test_customer_security.py::test_customer_ingress_rejects_untrusted_peer_even_with_spoofed_headers`、`test_customer_security.py::test_customer_ingress_rejects_missing_malformed_or_chained_forwarded_ip`、`test_customer_security.py::test_customer_ingress_rejects_wrong_host_or_forwarded_scheme`、`test_customer_security.py::test_customer_ingress_rejects_already_rewritten_asgi_peer`、`test_customer_security.py::test_customer_ingress_accepts_operational_loopback_sentinel` | 全部客户路由（ingress 中间件） |
| CORS allowlist | `test_customer_security.py::test_customer_public_origin_joins_exact_cors_allowlist`、`test_activation_code_routes.py::test_cors_preflight_permits_idempotency_headers` | OPTIONS |
| IDOR/跨用户 404 | `test_customer_fencing.py::test_other_customer_cannot_touch_a_foreign_project`、`test_customer_devices.py::test_delete_foreign_users_device_answers_not_found`、`test_customer_devices.py::test_unbind_replay_cannot_be_probed_without_the_owning_credential`、`test_payments.py::test_user_can_read_only_their_own_recharge_order` | DELETE `/api/customer/devices/{id}`、GET `/api/customer/recharge-orders` 等 |

## S6 session fixation、epoch 回退、token 重放、切换竞态、旧设备迟到写入 — FULL（本轮补齐 fixation）

| 覆盖点 | 用例 | method-path |
| --- | --- | --- |
| **session fixation（新增专项）** | `test_customer_sessions.py::test_session_fixation_injection_is_never_adopted`（**CW-009 新增**） | POST `/api/customer/sessions/{heartbeat,logout,login}`：自造 token 全部 401/403 且 0 状态行/0 事件；真实 login 只采纳服务端签发 token |
| token 重放/替换 | `test_customer_fencing.py::test_verify_rejects_the_replaced_token_after_a_switch`、`test_customer_fencing.py::test_verify_rejects_unknown_token`、`test_customer_sessions.py::test_heartbeat_rejects_forged_session_token`、`test_customer_sessions.py::test_login_lost_response_replays_same_token_and_epoch`、`test_customer_sessions.py::test_switch_lost_response_replays_same_token_and_epoch`、`test_customer_sessions.py::test_switch_replay_rejects_a_session_replaced_by_later_switch` | heartbeat/login/switch |
| epoch 回退 | `test_customer_fencing.py::test_verify_enforces_the_expected_epoch`、`test_customer_fencing.py::test_regressed_verifier_leaves_a_durable_committed_stale_write_fact`、`test_customer_fencing.py::test_request_scoped_pg_reads_persist_denials_after_dependency_rollback`、`test_customer_fencing.py::test_verify_judges_the_lease_on_the_post_lock_clock` | fenced 写路径 |
| 切换竞态 | `test_customer_sessions.py::test_concurrent_switches_from_both_devices_serialize`、`test_customer_sessions.py::test_hundred_concurrent_second_device_logins_all_409_while_first_online`、`test_customer_sessions.py::test_hundred_concurrent_logins_at_lease_expiry_leave_one_current_device`、`test_customer_sessions.py::test_concurrent_logins_from_lapsed_state_leave_one_current_device` | login/switch |
| 旧设备迟到写入 | `test_customer_sessions.py::test_late_logout_after_takeover_never_touches_the_new_session`、`test_customer_fencing.py::test_cluster_probe_detects_heartbeat_from_a_displaced_session_epoch`、`test_customer_fencing.py::test_verify_fences_a_lease_snapshot_that_changed`、`test_customer_fencing.py::test_fenced_transaction_fences_a_stale_snapshot_and_leaves_no_write` | heartbeat/logout/业务写 |

入口后切换 0 副作用（独立 PG 多连接）：由 `test_customer_fencing.py::test_fenced_transaction_fences_a_stale_snapshot_and_leaves_no_write`、`test_customer_fencing.py::test_regressed_verifier_leaves_a_durable_committed_stale_write_fact` 承载；多 Worker 不重复领取由 `test_customer_queue_fairness.py::test_concurrent_workers_do_not_double_claim` 佐证。

## S7 管理员解绑/强制下线/暂停码：actor、原因、二次确认、幂等键 — FULL

| 覆盖点 | 用例 | method-path |
| --- | --- | --- |
| 强制下线（confirm/reason/epoch/幂等重放；陈旧 epoch 409；auditor 403） | `test_admin_session_routes.py::test_revoke_session_keeps_device_and_replays_once`、`test_admin_session_routes.py::test_revoke_session_rejects_stale_epoch_and_auditor` | POST `/api/control/customer-sessions/{id}/revoke` |
| 暂停/恢复/吊销码（actor/reason/request_id 落审计） | `test_admin_activation_routes.py::test_suspend_and_resume_bound_code`、`test_admin_activation_routes.py::test_revoke_issued_code_records_reason`、`test_admin_activation_routes.py::test_revoke_idempotent_replay`、`test_admin_activation_routes.py::test_minting_audit_persists_reason_and_request_id` | POST `/api/control/activation-codes/{id}/{suspend,resume}` |
| 写合同（缺确认/空原因/缺幂等键拒绝） | `test_admin_activation_routes.py::test_write_rejects_missing_confirmation`、`test_admin_activation_routes.py::test_write_rejects_blank_reason`、`test_admin_activation_routes.py::test_write_rejects_missing_idempotency_key`、`test_admin_activation_routes.py::test_status_action_requires_write_contract` | control 写路由 |
| 管理员解绑（actor/reason 落 LOGOUT 事件；幂等重放/冲突） | `test_customer_devices.py::test_admin_unbind_releases_device_and_riding_session`、`test_customer_devices.py::test_admin_unbind_idempotent_replay_and_conflict`、`test_customer_devices.py::test_admin_unbind_outcomes` | POST `/api/control/devices/{id}/unbind` |

## S8 密钥轮换保留旧 key 验证窗 — FULL

| 覆盖点 | 用例 |
| --- | --- |
| 设备 key 轮换窗不掉线 | `test_customer_devices.py::test_authentication_accepts_retained_key_versions`、`test_customer_devices.py::test_enroll_consume_after_key_rotation_keeps_pairing_version` |
| 激活码 key 验证窗 | `test_activation_code_service.py::test_key_rotation_verification_window` |
| AEAD 双版本解析/退役 fail-closed | `test_customer_idempotency.py::test_aead_key_rotation_window_resolves_both_versions`、`test_customer_idempotency.py::test_retired_aead_key_version_fails_closed` |
| admin HMAC 版本化/仅 v2 启动 | `test_admin_auth.py::test_admin_hmac_key_versioned_env_resolution`、`test_admin_auth.py::test_security_gate_allows_startup_with_only_rotated_v2_key`、`test_admin_auth.py::test_security_gate_allows_only_rotated_v2_for_every_customer_key` |
| 信封恢复跨轮换 | `test_activation_code_routes.py::test_envelope_scope_recovery_survives_key_rotation` |

## S9 依赖审计、密钥扫描、专项 Code Review — PARTIAL（登记去向）

| 覆盖点 | 证据 | 判定 |
| --- | --- | --- |
| 密钥扫描 | `test_security_contracts.py::test_secret_scan_script_passes_on_repository_contract_surface` + CI secret-scan job（`ci.yml`） | FULL |
| JS 依赖审计 | CI `npm audit --audit-level=high`（`ci.yml`） | FULL |
| Python 依赖审计 | 仓库无 pip-audit/uv audit——**缺口登记给 CW-044（CI 收口）**补门禁 | 缺口（去向明确） |
| 认证/账务/并发专项 Code Review | 流程要求：由各 PR 独立 review 承载（CW-007/009 等增量均已执行独立子代理评审并留痕） | 流程项（非自动化） |

## 支付回调独立鉴权（CW-009 点名项）— FULL

- 实现：GET `/api/payments/zpay/notify` 为 MD5 验签（`hmac.compare_digest`）+ 来源摘要幂等；`/return` 纯展示无副作用；对账 sync 走 admin 写合同。
- 用例：`test_payments.py::test_valid_notify_credits_wallet_and_duplicate_notify_is_idempotent`、`test_payments.py::test_invalid_notify_never_credits_wallet`、`test_payments.py::test_notify_rejects_duplicate_query_parameters`、`test_payments.py::test_paid_order_rejects_a_different_provider_trade_number`、`test_payments.py::test_provider_trade_number_cannot_credit_two_orders`、`test_payments.py::test_concurrent_duplicate_notifies_credit_once`、`test_payments.py::test_return_page_is_display_only_even_with_valid_payment_fields`、`test_payments.py::test_control_sync_requires_write_contract_and_audits_the_attempt`、`test_payments.py::test_control_sync_rejects_missing_forged_or_business_identity`、`test_zpay.py::test_zpay_signature_matches_official_sorting_and_unencoded_values`。

## 结果汇总

9 条要求：S1/S2/S3/S4/S5/S6/S7/S8 = FULL（S2/S4/S6 缺口由本轮 4 个新增用例补齐），S9 = PARTIAL（Python 依赖审计缺口去向 CW-044；Code Review 为流程项）。失败=0、skip=0（全部用例在必需 TEST-PG 门禁下运行，CW-007 硬门保证缺库即失败）。
