# CW-005 — 历史数据盘点与 A/B/C 处置路线（框架与决议模板；实际盘点待真实环境执行）

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-005 盘点历史数据并签认处置路线 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-09）；Reviewer：独立复核子代理 + 待数据负责人/业务负责人签认 |
| 分支 / 基线 SHA | `feat/customer-v3-cw05-data-disposition` / 基线 `origin/main@b211095` |
| 上游规格段落 | V3 清单 §4 CW-005；CW-033—037 条件链 |
| 改动文件 | `docs/evidence/CW005-DATA-DISPOSITION.md`（新增） |
| 失败测试或回归锁定 | 不适用（决策与静态核验层）；导入/对账工具既有自动化（T07）继续有效 |
| 实现结果 | §1 位置线索、§2 路线定义、§3 工具边界、§4 盘点流程、§5 决议模板 |
| 验证命令与通过数 | 静态核对工具与配置存在性（依据列） |
| 证据层级 | 决策与静态核验（**实际数据盘点未执行**——需真实环境只读访问，见 §6） |
| 安全与可观测性 | 敏感实际数据不写入本文档/CSV/任务文件（红线） |
| 迁移与回滚 | 纯文档，可整体回退 |
| 外部授权记录 | 无；生产数据访问与处置执行需另行授权 |
| 未测试项 | 全部实际批次盘点（§6） |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 1. 预期数据批次位置清单（代码侧线索，供现场只读盘点起点）

| 批次线索 | 位置 | 依据 |
| --- | --- | --- |
| 内部 P0 业务库（SQLite） | `/var/lib/video-replica/app.db` | `deploy/internal-p0.env.example:4` |
| 内部 P0 本地资产存储 | `/var/lib/video-replica/storage` | `deploy/internal-p0.env.example:5` |
| 内部 SQLite 每日备份 | `/var/backups/video-replica`（`app.backup daily`） | `deploy/systemd/video-replica-backup.service`（ExecStart） |
| 客户生产 PG | `VIDEO_REPLICA_DATABASE_URL` 指向的 PG16（客户生产禁 DB_PATH/sqlite://，fail-closed） | `deploy/customer.env.example:2-8` |
| 客户生产对象存储 | 私有 COS bucket（active_storage_provider=cos） | `deploy/customer.env.example:8` |
| 历史部署审计记录 | **`data-deploy-audit.md` 不在本仓库基线 `origin/main` 中**（V3 清单引用之）——该文件存在于收敛分析分支 `codex/customer-cloud-convergence-analysis-20260908` 的 `outputs/customer-cloud-convergence-analysis-2026-09-08/` 下（d93c088 新增），可经 git 恢复，或由部署方提供；恢复动作与候选整合一并处理，不在本任务分支内执行 | `git ls-tree` 两分支均无此文件 |

> 上表仅为**预期位置**。实际批次以现场只读盘点为准；"无遗留数据"同样必须留存盘点证据（快照命令输出/管理端导出），不得口头跳过（V3 清单 CW-005 完工标准）。

## 2. A/B/C 路线定义（承接既有决策：数据库类型已定 PG，A/B/C 仅选择**数据处置方式**）

| 路线 | 定义 | 启用的条件任务 | 前置 |
| --- | --- | --- | --- |
| **A：保留客户 PG，归档内部数据** | 客户 PG 升级保留至冻结 head；内部 SQLite 封存归档（可恢复、不可续写）；证明内部数据无需合入 | CW-034 | CW-033 恢复演练 |
| **B：空 PG 导入选中批次** | 原件封存 → 隔离工作副本规范化 → T07 导入器导入空目标 PG → 全量对账 | CW-035 | CW-033、CW-060 operator 隔离制品 |
| **C：已有 PG 选择性合并** | 不覆盖已有客户的选择性合并（**能力未开发**，需新开发+独立复核） | CW-036 | CW-033 + 合并能力开发 |

**红线（全部路线通用）**：不得按用户名自动合户；原 SQLite 只读保护，规范化只写隔离副本；不得把空库导入工具当作已有客户库合并工具；每条路线最终业务库与验收库均为 PG。

## 3. 工具清单与能力边界（复用既有，本项不重复开发）

| 工具 | 能力 | 边界 |
| --- | --- | --- |
| `server/scripts/sqlite_to_postgres.py` | T07 一次性 fail-closed 导入：维护窗、PG advisory lock（`:52,165-176`）、源/目标同 head、空目标保护、单事务、重放判定、序列重置 | **只接受空目标**；非空不一致目标被拒 → 不能用于路线 C |
| `server/scripts/reconcile_customer_billing.py` | 账务核对（钱包/流水/订单差额、资产引用孤儿） | 对账用，不做写迁移 |
| `server/scripts/reconcile_dangling_billing_reservations.py` | 悬挂 RESERVE 安全终结 CLI | CW-038 复用 |
| `server/scripts/pitr_recovery_facts.py` | 恢复后 100 事实核验 | CW-033/048 复用 |
| `deploy/postgres/pitr-*.sh` | PG 物理备份/取回/隔离恢复演练 | CW-033/048 复用 |
| local→COS 历史资产遍历迁移工具 | **不存在**（仅 adapter 原语与孤儿扫描） | 若批次含 local 资产 → CW-037 开发差额（资产 ID 孤儿扫描在 `reconcile_customer_billing.py:959-989`） |

## 4. 盘点流程（现场执行口径；先只读，复制在隔离位置）

1. 对 §1 每个预期位置执行只读盘点：库文件大小、表清单、行数摘要、最近写入时间、激活码/用户/项目/任务/钱包计数（**脱敏**，不导出明文密钥/激活码/设备 token）。
2. 原件封存：SQLite 一致快照（停写检查 + writer fence + SHA-256，工具能力见 CW-033 复用清单）；PG 侧 PITR base backup + WAL 位点。
3. 每批次填写 §5 决议行 → 业务/数据负责人签认路线 → 才触发对应条件任务。
4. 盘点原始记录隔离保存；进入任务文档/CSV 的仅摘要与 hash。

## 5. 数据批次决议表（模板——实际行待现场盘点后填写）

| 批次ID | 来源（位置+hash） | 目标 | owner | 需保留业务 | 路线(A/B/C) | 签认人/日期 |
| --- | --- | --- | --- | --- | --- | --- |
| DB-?（待盘点） | — | — | — | — | — | — |
| ASSET-?（待盘点） | — | — | — | — | — | — |

## 6. 诚实边界：本项未完成部分

- **实际数据批次盘点未执行**：本会话无生产/实际环境访问权限。§1 仅代码侧位置线索；§5 无实际行。
- CW-033（快照恢复演练）、CW-034/035/036/037（条件路线）在 §5 签认前保持 conditional，不得预填路线或标 N/A。
- `data-deploy-audit.md` 缺失须现场补齐后才能声称"历史部署数据范围已知"。

## 7. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 数据负责人（盘点结果+路线建议） | 待签认（待实际盘点） | — |
| 业务负责人（批次保留业务确认） | 待签认（待实际盘点） | — |
