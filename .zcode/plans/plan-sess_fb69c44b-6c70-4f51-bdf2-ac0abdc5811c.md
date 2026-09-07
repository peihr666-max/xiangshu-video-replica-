# 设置界面参数补全 + 新增 API 费用设置

## 现状结论（已逐行核实）

**参数缺口**（`client/src/SettingsPanel.tsx:41-99`，管理后台与工作台共用此组件）：
| Provider | 现状 | 缺口 |
|---|---|---|
| hifly（飞影数字人） | **完全没有表单**，前端 `ProviderName` 枚举只有 7 个，快照里有 hifly 也被静默丢弃 | 必须新增（api_key） |
| dashscope | 只有 api_key | 服务端实际消费 9 个键（`asr.py:294-336`）：workspace_id、region、base_url、model、flash_model、flash_threshold_sec、poll_interval_sec、poll_max_attempts 全部无 UI |
| deepseek | 只有 api_key | 代码实际接受 base_url/model 覆盖（`script_rewrite.py:264-266`），但 `settings.py:36-38` 注释说"服务端固定"——注释与代码不一致，一并修正 |
| douyidou | app_id/app_secret 表单已有 | 仅缺提示：C3 链接解析后端未开发，配置暂不生效 |
| metaso / apilio / tikhub / cos | 已完整 | 无 |

**费用设置断链（核心发现）**：`oral.py:59-71` 已经预留读取 `oral_unit_price_fen`（docstring 写明 "admin-configurable via billing"），但 `settings.py:322-338` 的 `read_billing_settings` 永远不返回这个键 → 口播报价恒为常量 1000 分。**存储在 `runtime_settings` 表列**（迁移 022 模式），新增需要迁移 067。

## 改动清单

### A. 服务端（测试先行）
1. **迁移 `067_oral_unit_price.py`**：`runtime_settings` 加列 `oral_unit_price_fen INTEGER NOT NULL server_default "1000"`（仿迁移 022 写法，sqlite/PG 通用）；downgrade 删列。**同步 bump head 断言**：`tests/test_db.py`（5 处 066→067）+ `tests/test_postgres_migrations.py:28` HEAD_REVISION。
2. **`settings.py`**：`DEFAULT_BILLING_SETTINGS` 加 `oral_unit_price_fen=1000`；`read_billing_settings` SELECT 并返回该键；`save_billing_settings` 接收并持久化；`validate_billing_settings` 校验（整数、1~2147483647，不参与 min/step 整除规则）；修正 deepseek 的过时注释。
3. **`settings_routes.py`**：`BillingSettingsRequest` 加 `oral_unit_price_fen: StrictInt`，PATCH 透传（workspace lane）。
4. **`control_routes.py`**：`BillingSettingsUpdate` 同步加字段（管理 lane，含 confirm/reason 契约不变）。
5. `oral.py` / `internal_billing.py` **零改动**（读取端已预留；扣费仍 1 credit/条，fen 为价格快照——与现有 credit 模型一致）。

### B. 前端
1. **`api.ts`**：`ProviderName` 加 `"hifly"`；`BillingSettings` 加 `oral_unit_price_fen`；`updateControlBillingSettings` 参数补字段。
2. **`SettingsPanel.tsx`**：PROVIDER_FORMS/ORDER 加 hifly 卡片（api_key，标题"数字人口播"）；dashscope 补 8 个可选字段（placeholder 显示服务端默认值，留空=回落默认）；deepseek 补 base_url/model 可选字段；douyidou note 加"链接解析能力上线后生效"。
3. **`PaymentSettingsSection.tsx`**：内部价格表单加"口播单价（分/条）"输入 + 提交 payload 带 4 字段。

### C. 测试（红→绿）
- server：`test_settings.py` 计费默认值/PATCH 精确断言改 5 键；参数化类型拒绝用例覆盖新字段；新增"改 oral_unit_price_fen → GET /api/oral/price 与 create_oral_task 的 estimated_cost_fen 快照跟随"用例（贴 `test_oral_domain.py` 现有 seed 模式）；dashscope 可选字段保存/掩码保留回读用例。
- client：`SettingsPanel.test.tsx` 加 hifly 卡片渲染与 dashscope 多字段保存断言；`AdminApp.test.tsx` billing mock 补键、PATCH body 断言 4 字段。

## 明确不做（边界）
- **douyidou 消费端**（C3 url_resolver/客户端）不在此任务，配了也不生效——UI 加提示说明。
- **真实付费连接测试**不扩展：非 cos provider 的"测试连接"保持 configured_only 语义（真实调外部付费 API 需按红线单独授权）。
- **credit 折算模型**不变：口播仍 1 credit/条，单价 fen 用于报价/快照展示。

## 工作区与验证
- 在联调 worktree（`乡墅爆款短视频复刻-人物IP口播联调`，分支 `codex/character-ip-oral-completion` @69496ac，工作树干净）直接实施，沿该线现有惯例分逻辑提交。
- 验证：`uv run pytest tests/test_settings.py tests/test_oral_domain.py tests/test_db.py -q` + ruff/mypy；client `vitest` 相关文件 + biome + `tsc -b`；PG 迁移用例需 `scripts/pg-fixture.sh start` 后跑 `test_postgres_migrations.py`。全量 `npm run check` 留到提 PR 前统一跑一次。