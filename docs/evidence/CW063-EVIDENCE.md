# CW-063 证据文件 — 管理端 h3_extended_modes_enabled 开关（缺口 4b 控制面补齐）

任务：CW-063（代码与测试增量 · 管理端控制面 · 纯工程，默认关状态下上线零风险）
分支：`feat/customer-v3-cw063-h3-extended-modes-toggle`（独立 worktree `E:/众墅之家爆款短视频创作/.worktrees/CW-063-h3-extended-modes-toggle`，从 `origin/main@a093f61` 创建，开工即最新、无需 rebase）
Owner / Reviewer：Qoder session 代 honor.pei（用户 2026-09-11 决策：4b 纯工程先补齐控制面）／Reviewer 待 PR 分配
来源：`docs/视频生成独立创作-设计与实施-2026-09-07.md` §五.1 扩展模式探针——设计文档明确「P1 上线前重新核对当时供应商 API」「通过后管理端打开 `h3_extended_modes_enabled` 即全量放开 T2V/R2V/尾帧」，但**管理端开关（端点 + UI）从未实施**。
上游规格：缺口 **4b（控制面）** = 本任务；缺口 **4a（供应商 H3 扩展模式付费探针）** 属账本 §15「必须保留人工授权的动作」（真实付费 Provider 提交，包括 H3），需真实 metaso key + 预算授权 + 人工执行，**不由本任务声称**。

---

## 1. 交付差额（缺口 4b：控制面从未实施）

| 面 | 设计要求 | origin/main 现状 | 本 PR 处置 |
| --- | --- | --- | --- |
| 数据列 | `runtime_settings.h3_extended_modes_enabled` 门控 H3 扩展形态付费提交 | **已存在**（迁移 `075_independent_creation`，`Boolean NOT NULL server_default FALSE`） | 零迁移改动（PG-09 禁改已发布 revision） |
| 消费逻辑 | 独立创作通道按该列决定是否放开 T2V/R2V/尾帧 | **已存在**（`server/app/independent.py:108-112` 读该列） | 零触碰（属 CW-056 在制文件域） |
| 管理端读 | GET 当前开关态供 UI 展示 | **缺失** | 新增 `GET /api/control/settings/h3-extended-modes`（AdminReader） |
| 管理端写 | 管理员显式填 reason 后翻转开关并留审计 | **缺失** | 新增 `PATCH /api/control/settings/h3-extended-modes`（AdminWriter + 写契约 + 幂等 + upsert 兜底 + audit_logs） |
| 管理端 UI | services tab 内可视化开关 + 只读态 + 确认对话框 | **缺失** | 新增 `H3ExtendedModesSection.tsx`（镜像 `QueueModeSection.tsx`）挂载 SystemSettingsPage |

**结论**：数据列与消费逻辑在基线已就绪，唯独控制面（读/写端点 + UI）从未实施——本任务补齐这一段，使 4a 付费探针通过后管理员可在一处显式、可审计地放开 H3 扩展形态。

## 2. 后端端点（`server/app/admin_runtime_routes.py` +144，文件 415→559 行）

- **Pydantic 模型**（:61-91）：
  - `H3ExtendedModesResponse`（:61-76）：`h3_extended_modes_enabled: bool`，`model_config extra="forbid"`；
  - `H3ExtendedModesUpdateRequest(AdminWriteContract)`（:78-91）：继承共享写契约（`confirm` + `reason`），加 `h3_extended_modes_enabled: bool`，`extra="forbid"`。
- **GET `/settings/h3-extended-modes`**（:451-467）：依赖 `AdminReader`（无 session→401、auditor 可读），`SELECT h3_extended_modes_enabled FROM runtime_settings WHERE id=1`，空行回落 `False`。
- **PATCH `/settings/h3-extended-modes`**（:470-547）：依赖 `AdminWriter`（auditor→403），经 `write_with_idempotency` 包裹业务函数：
  - `UPDATE runtime_settings SET h3_extended_modes_enabled=%s, updated_by_user_id=%s, updated_at=CURRENT_TIMESTAMP WHERE id=1`；
  - `rowcount==0` 时 **upsert 兜底** `INSERT`（12 列，其余列取 `DEFAULT_RUNTIME_SETTINGS`/`DEFAULT_BILLING_SETTINGS` + `fair_queue_enabled=False`），保证空表也可首次写入；
  - 写 `audit_logs`（`action='runtime_settings.update'`、`entity_type='runtime_settings'`、`entity_id='1'`、`metadata_json` 含 `h3_extended_modes_enabled`/`reason`/`request_id`/`setting='h3_extended_modes'`）；
  - `success_status=200`、`unavailable_code=RUNTIME_SETTINGS_SERVICE_UNAVAILABLE`（PG 不可用 fail-closed 503）。
- **完全复用 queue-mode 模板**（同文件相邻的 `read_queue_mode`/`update_queue_mode`），共享 `AdminReader`/`AdminWriter`/`write_with_idempotency` 语义，无新造鉴权或幂等机制。

## 3. 前端 UI（3 文件）

- **`client/src/admin/H3ExtendedModesSection.tsx`（新增 121 行）**：镜像 `QueueModeSection.tsx`——`useState`(enabled/loading/error/notice/confirmOpen/saving) + `load`/`useEffect` + `toggle(reason)`（401→「会话已失效，请重新登录」）；`StatusBadge`（已开启/已关闭/未知）；`ConfirmDialog level="reason"`（开启/关闭均需填 reason）；`readOnly` 时提示「审计员只读，不能切换扩展模式。」；开启态警示条提示放开真实付费提交前须完成供应商核对。
- **`client/src/api.admin.ts`（+39）**：`fetchH3ExtendedModes()`（GET，`parseActivationError` 失败映射）+ `updateH3ExtendedModes(enabled, reason, idempotencyKey?)`（复用 `adminWrite<T>` PATCH，注入 CSRF + Idempotency-Key header），镜像 `fetchQueueMode`/`updateQueueMode`。
- **`client/src/admin/SystemSettingsPage.tsx`（+2）**：import + services tab 内挂载 `<H3ExtendedModesSection readOnly={readOnly} />`（插在 `QueueModeSection` 与 `ViralRuntimeSection` 之间）。

## 4. 失败测试与回归锁定（TDD 红→绿）

- **后端 RED**：`test_admin_h3_extended_modes.py`（新专项，镜像 `test_admin_rate_routes.py` 的专属 PG 模式）首跑因端点/模型缺失失败 → 实现后转绿。
- **前端 RED**：`H3ExtendedModesSection.test.tsx`（3 用例）首跑 `Failed to resolve import "./H3ExtendedModesSection"` → 实现组件后 3 passed。
- **真实 PG 首跑暴露 4 处测试自身缺陷（非生产代码问题），逐项根因修复**：
  1. `enables_with_write_contract` / `idempotent_replay`：helper `_audit_rows` 用 `metadata_json->>'setting'` 查询，但 `audit_logs.metadata_json` 是 `sa.Text()`（迁移 001）非 jsonb → `psycopg.errors.UndefinedFunction: operator does not exist: text ->> unknown`。修为按 `action` 查询 + Python 侧 `json.loads` 解析 TEXT 并按 `setting` 过滤（生产码写 `json.dumps(...)` 入 TEXT 列本就正确）。
  2. `requires_reason` / `requires_confirm`：断言期望 422，但共享 `require_write_contract`（`admin_write_contract.py:77-87`）对空 reason / `confirm=false` 抛 `http_error(400, ...)`；参考测试 `test_admin_rate_routes.py:167/175` 同样断言 400（`CONFIRMATION_REQUIRED`/`REASON_REQUIRED`）。修断言为 400 并加 `detail.code` 精确校验（对齐参考测试严谨度）。
  - 修复后 **10 passed**；`idempotent_replay` 的 `len(audits)==1` 语义经 `write_with_idempotency`（:255-279）核实正确——同键重放走 snapshot 返回、不重跑 `business()`，审计不重复写。

## 5. 验证命令与通过数（本机 Windows，真实 PG16 容器）

- **后端 pytest（真实 PG）**：`vs-pg-cw063@5442`（postgres:16.15-alpine，专属库 `cw063_h3_extended_modes_test`，alembic upgrade head + admin_u/auditor_u 种子），`fcntl` shim 仓外注入 `PYTHONPATH`：
  - `uv run pytest tests/test_admin_h3_extended_modes.py -v` → **10 passed**（GET 无 session 401／GET 默认关／GET 读开／PATCH 开启写契约+审计／PATCH 关闭／auditor 403／幂等重放审计不重复／upsert 兜底空表／空 reason 400／confirm=false 400）。
- **后端静态门**：`ruff check app/admin_runtime_routes.py tests/test_admin_h3_extended_modes.py` All checks passed；`ruff format --check` 2 files already formatted；`mypy app/admin_runtime_routes.py` Success（no issues）。
- **前端**：`vitest run src/admin` → **22 文件 141 passed**（含新增 `H3ExtendedModesSection.test.tsx` 3 + 回归 `QueueModeSection.test.tsx` 3 + SystemSettingsPage/AdminApp 集成）；`biome check`（4 文件）No fixes applied；`tsc -b` rc=0。
- **pg_test_kit 登记**：`server/tests/pg_test_kit.py` +5——`cw063_h3_extended_modes_test` 加入 `RECORDED_TEST_DATABASES` allowlist（纯增量，`create_test_database` 前置；与 CW-056/058/059 同款登记）。

## 6. §14 任务认领与证据记录模板（逐字段）

| 字段 | 内容 |
| --- | --- |
| 任务/工作包 | CW-063 · 管理端 `h3_extended_modes_enabled` 开关（端点 + UI）· 缺口 4b 控制面补齐 |
| Owner / Reviewer | Qoder session 代 honor.pei / Reviewer 待 PR 分配 |
| 分支 / 基线 SHA | `feat/customer-v3-cw063-h3-extended-modes-toggle` / `origin/main@a093f61`（开工即最新，`merge-base --is-ancestor` rc=0，无需 rebase） |
| 上游规格段落 | `docs/视频生成独立创作-设计与实施-2026-09-07.md` §五.1；缺口 4b（控制面）；4a（付费探针）属 §15 人工授权 |
| 改动文件 | 新增 3（`test_admin_h3_extended_modes.py` 355 行 / `H3ExtendedModesSection.tsx` 121 行 / `H3ExtendedModesSection.test.tsx` 106 行）；改 5（`admin_runtime_routes.py` +144 / `api.admin.ts` +39 / `SystemSettingsPage.tsx` +2 / `pg_test_kit.py` +5 allowlist / 本账本 §18 + 认领登记各 +1）；另新增本证据文件 |
| 失败测试或回归锁定 | 后端 RED（端点缺失）→GREEN 10 passed；前端 RED（import 未解析）→GREEN 3 passed；真实 PG 首跑 4 failed 全为测试自身缺陷（`->>` 用于 TEXT 列 / 422→400 契约码），根因修复后 10 passed |
| 实现结果 | GET/PATCH 端点 + Pydantic 模型 + upsert 兜底 + 审计；前端 UI 段 + api helper + 挂载；默认关不改 |
| 验证命令与通过数 | 见 §5：后端 pytest 10 passed（真实 PG16）+ ruff/mypy 绿；前端 vitest 141 passed + biome/tsc 绿 |
| 证据层级 | **AUTOMATED_VERIFIED**（真实 PG16 容器 pytest 全绿 + 前端全绿；未过真实付费链路，不到 STAGING/REAL_CHAIN） |
| 安全与可观测性 | AdminReader/AdminWriter 读写分离；auditor PATCH→403、无 session→401；写契约（confirm + 非空 reason + Idempotency-Key + X-Admin-CSRF）；幂等重放不重复写审计；每次翻转写 `audit_logs`（actor/action/entity/reason/request_id/setting）；PG 不可用 fail-closed 503 |
| 迁移与回滚 | **零迁移改动**（列由 075 已建、`server_default FALSE`）；默认关不变；回滚 = 管理员经同一 PATCH 填 reason 关回，或部署回退本分支（端点/UI 移除后列与消费逻辑仍在基线，不影响其他功能） |
| 外部授权记录 | 无——4a 真实付费 H3 探针未执行（§15 人工授权，需真实 metaso key + 预算 + 人工）；本任务只交付控制面，默认关上线零风险 |
| 未测试项 | 真实付费 H3 扩展形态提交（4a，人工授权）；CI 三门禁（secret/Linux 质量门/Windows NSIS）最终以 push 后 CI 为准；本会话仅跑受影响专项 + 静态门 |
| Lore 提交 SHA | 本分支为原子开发提交（代码/测试/证据同提交，见本 PR commits）；最终 main SHA 由 PR squash-merge 生成，按 CW-014/CW-031 惯例于合并后回填 |

## 7. 与相邻任务的边界

- **CW-056（PG 升级矩阵 / independent.py R2V 扩展，在制）**：文件**零重叠**——CW-056 改 `server/app/independent.py`/`generation.py`/`test_independent_creation.py`（独立创作校验层），CW-063 改 `admin_runtime_routes.py` + 3 前端文件 + `pg_test_kit.py`（管理端控制面）。CW-063 依赖的 `h3_extended_modes_enabled` 列（075 迁移）与 `independent.py:108-112` 读逻辑在 `origin/main` 上已存在，不受 CW-056 未提交改动影响。
- **缺口 4a**：真实付费探针属 §15 人工授权动作，本任务不声称、不自动调用；4b 控制面上线后，4a 通过时由管理员在本 UI 显式开启即全量放开。
- **缺口 5（工作室快捷入口/侧栏）**：等 CW-019 合入后另立 CW-064，本任务零触碰 `MainPages.tsx`/`StudioWorkspace.tsx`。
- **PG 资源隔离**：`vs-pg-cw063@5442` 本任务独占，不触碰他任务在用端口（5432/5434-5441）；专属库经 allowlist 建/删。

## 8. 诚实边界

- **4a 付费探针未执行**：`h3_extended_modes_enabled` 只交付了「可被管理员显式、可审计地开启」的控制面；开启前置（供应商 H3 扩展形态真实付费核对）属 §15 人工授权，本任务不代替、不声称已完成。
- **默认关不变**：列 `server_default FALSE`，本任务不改默认值；上线后 UI 显示「已关闭」，管理员必须显式填 reason 才能开启。
- **专项范围**：本机仅跑本任务受影响专项（后端 10 + 前端 src/admin 141）+ 静态门；全量 pytest 与三门禁最终判定权归 push 后 CI。
- **测试文件偏差登记**：claim.json `file_boundary.owned` 原写测试落 `test_admin_runtime_routes.py`，实际按 `test_admin_rate_routes.py` 先例新建独立文件 `test_admin_h3_extended_modes.py`（专属 PG fixture 隔离更清晰），属合理偏差，特此登记。
- **`pg_test_kit.py` 共享文件增量**：+5 行仅 CW-063 专属库 allowlist 登记（`create_test_database` 前置），纯增量、无跨任务污染，与 CW-056/058/059 同款手法。
- **Lore 提交 SHA**：证据文件随代码同提交，本分支为原子开发提交；最终 main SHA 由 PR squash-merge 生成，按 CW-014/CW-031 惯例于合并后由协调者回填本行与 §18。
- 证据等级 **AUTOMATED_VERIFIED**（本地真实 PG 自动化，未到真实付费链路）。
