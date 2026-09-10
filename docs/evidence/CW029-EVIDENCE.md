# CW-029 证据 — 复用账务核心并核验扣费、支付差额（TEST-PG 多连接矩阵）

> 状态：`AUTOMATED_VERIFIED`（真实 PG 16.15 fixture 上执行；真实 ZPay/Provider 回调验收归 CW-050，不提升 `STAGING_VERIFIED`）。
> 分支 `feat/customer-v3-cw029-billing-pg-matrix`，基线 `origin/main@1ad1f31`（CW-022 #22 已合入；前置 CW-010、CW-026 #20、CW-016 均已入 main）。
> 本任务按规格「仅做剩余」复用账务核心（`internal_billing.py` 的 RESERVE/SETTLE/RELEASE + `billing_round` 幂等、`zpay_payments.py` 的回调确认）**零生产代码改动**，把支付/任务状态矩阵迁上 TEST-PG 多连接。

## 1. 任务与范围

- 任务/工作包：CW-029 / W4 代码与测试增量（账务负责人 + 独立复核）。
- 上游规格：V3 收敛清单 §CW-029；任务账本 §18；排班清单 §3—§7；AGENTS.md 标准工作流。
- 查重（2026-09-11 fetch 后）：无 cw029 分支/PR/认领目录，原子新建成功。
- 差额定位：既有 `tests/test_payments.py`（回调验签/重复/跨单 21 用例）仍跑在内部遗留 **SQLite** 通道；`tests/test_wallet_billing_service.py`（预留/结算/释放）已在 PG 但未覆盖支付回调面。CW-029 把两者合成的支付+任务状态矩阵迁上 **TEST-PG**（专用库 `cw029_billing_pg_test`，隔离容器 vs-pg-cw029:5439）。
- 剔除（按规格）：真实 ZPay/Provider 回调验收归 CW-050；客户端显示金额不构成裁决证据；历史 migration 不改写；其他分支成本账本/口播幂等修复不做整体 cherry-pick（口播侧由 CW-010 基线与 test_oral_domain 61 用例承载）。

## 2. 矩阵覆盖（7 用例，全部断言四套账差额）

| 场景 | 断言 |
| --- | --- |
| 支付成功 + 重复/乱序回调 | 首次 notify 按订单快照精确入账 10 条；重复同一签名回调 success 但账务行数不变；乱序（同单不同 trade_no）409 拒绝；四套账逐字节不变 |
| 伪造回调零副作用 | 坏签名/错 pid/非 SUCCESS 状态/金额不符/未启用渠道/未知订单 6 类全部 4xx failure；wallet 与 ledger 与基线逐字节相同，订单保持 PENDING |
| 跨用户订单 | 同一 provider_trade_no 绑第二用户订单 → 409 ZPAY_TRADE_ALREADY_BOUND；user_2 钱包 100、账务行 0 |
| 客户关闭（隐藏）订单 | CLOSED 订单不删行；迟到支付回调照常结算（PAID + 入账一次）——客户删除不抹对账证据 |
| 历史价格快照 | 下单后把 runtime_settings 单价 1000→5000，回调仍按订单自身 `charged_unit_price_fen_snapshot=1000` 入账 10 条，不按现价重算 |
| 任务结果重复/乱序 | 重复 finalize success 幂等（返回已记录 SETTLE、不新增账务行）；终态 SETTLE 之后再到的失败结果 no-op（不叠加 RELEASE）；SETTLE 后 available=98=100+ΣΔ、reserved 与 Σreserved_delta 双回零 |
| 取消 + 未知提交 | CANCELLED 释放一次（100/0，循环差额 0）、重复释放 no-op；RUNNING（未知提交）任务被 sweep 显式排除（scanned=0），预留冻结不被后台改动 |

## 3. 验证命令与通过数（本机 Windows + Docker PG 16.15 vs-pg-cw029:5439）

| 验证 | 结果 |
| --- | --- |
| `pytest tests/test_cw029_billing_pg_matrix.py` | 7 passed / 0 fail / 0 skip |
| `+ tests/test_wallet_billing_service.py + tests/test_internal_billing.py` | 35 passed（既有 PG 账务套件零回归） |
| `bash scripts/verify_no_secrets.sh` | exit 0 |
| `ruff check server` / `ruff format --check server` | All checks passed / 301 files already formatted |
| `mypy server/app` | Success: no issues found in 104 source files |
| main 全量门 | 由 CI 三门禁承载（本机无 cargo；ffmpeg 已装，oral 套件本机可跑） |

## 4. Section 14 Ledger Record

```text
任务/工作包：CW-029 / W4 代码与测试增量（复用账务核心并核验扣费、支付差额）
Owner / Reviewer：ZCode 全链路代理（用户 2026-09-11 指令授权 026→030 顺序开发与 PR squash 合并）/ 待 PR 独立评审 + CI 三门禁
分支 / 基线 SHA：feat/customer-v3-cw029-billing-pg-matrix / origin/main@1ad1f31（CW-022 合并提交）
上游规格段落：V3 收敛清单 CW-029 行；任务账本 §18；排班清单 §3—§7；AGENTS.md 标准工作流 1—6 条
改动文件：server/tests/test_cw029_billing_pg_matrix.py（新增 7 用例）；docs/evidence/CW029-EVIDENCE.md（新增）；docs/CUSTOMER-TASK-EVIDENCE-V3.md（登记）；docs/客户版任务清单-V3.md §18；docs/客户版代码开发清单-V3.md（新文件登记）
失败测试或回归锁定：矩阵每用例断言 available=初始+Σavailable_delta、终态轮次 reserved 与 Σreserved_delta 双回零、账务行数精确值；伪造回调以「账面逐字节不变」锁定零副作用；静态不变量使未来记账回归立即红灯
实现结果：支付回调验签/重复/乱序/跨用户/关闭单/价格快照 + 任务结果重复/乱序/取消/未知提交全部迁上 TEST-PG 多连接矩阵；账务核心零生产代码改动（纯复用）
验证命令与通过数：见 §3（新增 7 passed；wallet_billing+internal_billing 35 passed 零回归；静态门全绿）
证据层级：AUTOMATED_VERIFIED（真实 PG16 fixture；真实回调归 CW-050，不提升 STAGING）
安全与可观测性：无真实 secret 入代码/日志/夹具（商户密钥为测试值 MERCHANT_KEY 测试常量，Fernet 键运行时生成）；矩阵锁定「未验签回调零数据副作用」与「快照不可被现价改写」两条安全底线
迁移与回滚：无迁移；回滚 = revert 本分支单提交（纯测试+文档）
外部授权记录：用户指令授权本任务 PR 的创建与 squash 合并；未调用真实 ZPay/付费 Provider/生产 COS（CW-050 边界）
未测试项：真实 ZPay 回调与 Provider 链路（CW-050）；口播侧持久账单语义（test_oral_domain 61 用例 + CW-010 基线承载）；STAGING_VERIFIED 及以上层级
Lore 提交 SHA：见 claim.json 与 PR 登记
```
