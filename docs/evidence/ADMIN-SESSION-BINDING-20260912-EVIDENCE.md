# ADMIN-SESSION-BINDING-20260912 证据

> 维护任务（非 CW 编号）：管理员会话上下文绑定收窄为"仅绑浏览器环境（UA）"（用户确认清单 B1·方案②）。
> 基线 `origin/main@2be7c3d`；分支 `chore/admin-session-ua-only-binding-20260912`。
> 安全语义变更依据：用户 2026-09-12 在问题修复清单中明确选择方案②（仅绑 UA、不绑 IP）。

## 1. 背景与决策

管理端综合排查（ADMIN-UI-AUDIT-20260911，PR #49）登记的 P2-4：`load_admin_session` 对创建时的 IP 与 UA 双绑定、任一变化即吊销会话（`ADMIN_SESSION_CONTEXT_CHANGED`）。办公网络出口 IP 漂移场景下表现为管理员频繁被登出。用户在修复确认清单中选择方案②：**仅绑 UA、不绑 IP**。

## 2. 行为变更

| 维度 | 变更前 | 变更后 |
| --- | --- | --- |
| UA（浏览器环境）变化 | 吊销会话 + 审计 `admin_session.security_rejected` | **不变**（仍吊销） |
| IP（网络出口）变化 | 吊销会话 + 审计 | **不再吊销**；`created_ip_digest` 仍照常落库供审计 |
| 登录限流 IP 维度（`_spend_admin_password_budget`） | 按 IP+账号计数 | **不变**（仅会话绑定阶段退出 IP 判定） |
| `load_admin_session` 签名 | `(token, *, client_ip=None, user_agent=None)` | 移除死参数 `client_ip`（唯一调用方 `get_admin_actor` 同步更新） |

服务端英文提示同步收窄："Admin session network or browser context changed" → "Admin session browser context changed"。错误码 `ADMIN_SESSION_CONTEXT_CHANGED` 保留（前端 AdminApp 已有中文映射；其文案"（网络或浏览器）"的收窄归 B3 前端任务，避免跨任务夹带）。

## 3. 先红后绿

- **RED**：新增 `test_admin_session_survives_client_ip_change`（同 UA、独立 ASGI peer `203.0.113.77` 的第二个 TestClient 复用会话 Cookie）——变更前实现下 401 吊销，断言 200 失败（本机隔离 PG 容器 `vs-pg-adminbind`:5446 实测 `1 failed`）。
- **GREEN**：实现收窄后 `tests/test_admin_auth.py` 全量 **90 passed**（含既有 UA 变化吊销用例 `test_admin_session_context_change_revokes_cookie_and_is_audited` 零改动保持绿——它继续钉住 UA 绑定不被本次放宽误伤）。
- 相邻专项：`test_admin_rate_routes.py` + `test_security_contracts.py` **11 passed**（登录限流 IP 维度不受影响）。

## 4. 影响面排查

- `ADMIN_SESSION_CONTEXT_CHANGED` / `created_ip_digest` / `context_changed` 全仓引用仅三处：`admin_auth_routes.py`（本次改动）、`test_postgres_migrations.py` 与 `test_sqlite_to_postgres.py`（仅列存在性断言，零改动）。
- docs 中命中项均为历史记录（T46 人物库 IP 绑定等），按"历史签认不改写"原则不动。
- 迁移文件零改动（`admin_sessions` 表结构不变，`created_ip_digest` 列保留）。

## 5. 验证命令与结果（macOS 本机）

| 检查 | 结果 |
| --- | --- |
| `uv run python -m pytest tests/test_admin_auth.py -q`（PG: vs-pg-adminbind:5446） | **90 passed** |
| `uv run python -m pytest tests/test_admin_rate_routes.py tests/test_security_contracts.py -q` | 11 passed |
| `uv run ruff check app/admin_auth_routes.py tests/test_admin_auth.py` | All checks passed |
| `uv run ruff format` | 已格式化 |
| `uv run mypy app` | Success: 104 source files |

全仓门禁：自托管 runner 离线（GitHub Actions runners 列表为空），按"本地门禁前置原则"提交前执行 `npm run check:sharded`（静态门 + 4 分片独立 PG 容器 pytest）：**4 片全过——844/608/569/592 passed 合计 2613 passed + 1 skipped，0 failed**，与顺序全量口径一致。

## 6. 边界与未测试项

- 真实多出口网络的行为验证（运营商级 NAT 漂移）未做——语义由单元/集成测试承载，实机验证归 CW-049 UAT / CW-050 真实链路。
- 审计面：`created_ip_digest` 的查询/导出消费方目前为零（仅落库）；如后续需在审计中心展示，属独立需求。
- 证据层级：CODE_PRESENT + 本机 AUTOMATED_VERIFIED；最终三门禁以 PR CI 为准。
