# T43 — 账号隔离、设备安全、激活码复制与零初始额度证据

## 1. 结论

- 证据层级：`AUTOMATED_VERIFIED`。
- 实现提交：`dddfa70`（`feat/customer-v3-t43-isolation-security`，基线 `e084cf1`）。
- 本证据只证明本地代码、PostgreSQL 16 集成测试和桌面静态门禁；未执行 staging、真实支付/COS/Provider、灰度或生产发布。

## 2. 业务结果

1. 普通客户/员工的项目、任务批次、人物身份、人设、人物版本、人物素材和人物库按 owner 隔离；管理员和审计员保留控制面跨账户只读/管理视图。
2. 管理员明确授权给某个项目的人物归属于该项目 owner；人物详情再次校验项目访问权，不能只凭项目 ID 越权读取。
3. 已激活账号在陌生硬件上不能直接占用第二设备槽，必须进入配对审批；同一已知硬件重装仍可按指纹恢复。
4. 激活码重置要求有效在线 session，且仅首台设备可操作；设备 token 或第二设备均被拒绝。
5. 后台列表只返回掩码码；复制动作调用单码显式解密接口，要求管理员写权限、确认、原因和幂等键，并且只写一条不含明文的审计记录。
6. 正常新批次固定为零面值、零初始额度；激活创建零余额钱包但不创建伪 `PAID` 订单或 `CHARGE`。历史正额度码继续按原价值兼容，避免损失已发行权益。

## 3. 数据库迁移

- 新增 `050_activation_license_zero_credit`，从 `049_async_generation_reconcile` 接链。
- `activation_code_batches.face_value_fen` 与 `credits_snapshot` 允许为零，并以数据库 CHECK 强制二者同时为零或同时为正。
- `activation_code_activations.recharge_order_id` 改为可空，表示授权事实可以不关联充值事实。
- downgrade 在存在零额度批次或无充值单激活事实时 fail closed，不会静默丢弃现行数据语义。
- PostgreSQL 16.15 / UTC 的空库迁移、schema 约束和 head 合同均通过。

## 4. 失败测试与评审修复

- 跨用户人物库、人物身份/人设/版本、项目人物选择、人物素材下载和任务批次列表均增加或收紧回归锁。
- 100 个不同陌生设备并发使用同一已激活码时，仅首次激活设备成功，其余稳定返回 `PAIRING_APPROVAL_REQUIRED`。
- 零额度激活断言钱包为 0、充值单为 0、`CHARGE` 为 0；历史正额度激活回归保持。
- 管理列表无 `activation_code`/digest，单码 reveal 可复制、可幂等重放且审计只写一次，幂等快照不保存明文。
- 自评审修复：人物详情项目 IDOR、管理员授权人物 owner 推导、Windows 深目录缓存临时文件超长、旧配对路由断言、首帧 E2E 质检 fixture、050 冻结映射和未注册 `pytest.mark.pg`。
- 最终自评审没有遗留已知 Critical/High/Medium 问题；这不是独立第三方安全审计结论。

## 5. 验证结果

| 门禁 | 结果 |
| --- | --- |
| 密钥扫描 | `No hardcoded secrets detected in runtime contract surface.` |
| 客户端 | Biome、TypeScript、Vitest：50 个文件，592/592 通过 |
| E2E 格式 | `biome check e2e` 通过 |
| Tauri | `cargo fmt --check`、`cargo check --locked` 通过 |
| 服务端静态 | Ruff check/format 通过；Mypy 74 个模块通过 |
| PG16 关键专项 | 157/157 通过（迁移、schema、后台发码、激活、设备与人物详情） |
| 服务端全量 | 1416 通过、1 跳过、0 失败；跳过项为本机未安装 `ffmpeg` 的源帧外部工具用例 |
| pytest 标记复验 | 管理审计/会话 15/15 通过，`pg` 未注册警告已消除 |

保留的非阻断提示：FastAPI TestClient 依赖仍报告 Starlette/httpx 上游弃用警告，应在独立依赖升级任务处理。

## 6. 未测试与发布边界

- 未安装 `ffmpeg`，因此一个真实源帧外部工具用例未执行；不影响本次账号隔离、激活码、设备和额度修改的自动化结论，但正式桌面发布机仍应补跑。
- 未执行真实 ZPay、COS、付费 Provider、生产数据迁移、Windows 签名安装包、staging 双 API/四 Worker 或灰度流量。
- 生产部署前必须先备份 PostgreSQL，在目标 PostgreSQL 16 执行 Alembic 050，并验证零额度新码、历史正额度码和回滚阻断行为。
