# CW-003 — 已发版本清单与兼容退出窗口冻结（已签认，owner 2026-09-09）

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-003 冻结已发版本和兼容退出窗口 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-09）；Reviewer：独立复核子代理 + 待桌面负责人/后端负责人签认 |
| 分支 / 基线 SHA | `feat/customer-v3-cw03-compat-window` / 基线 `origin/main@b211095` |
| 上游规格段落 | V3 清单 §4 CW-003；§1 规则（不整体搬入未审分叉） |
| 改动文件 | `docs/evidence/CW003-COMPATIBILITY-WINDOW.md`（新增） |
| 失败测试或回归锁定 | 不适用（决策与静态核验层；删除旧接口时的回归由承接任务 CW-015/020/021/041 先红后绿） |
| 实现结果 | 见 §1–§5 |
| 验证命令与通过数 | `git log --follow`、`grep` 逐项静态核对（依据列给出行号/SHA） |
| 证据层级 | 决策与静态核验（签认前不得视为完成） |
| 安全与可观测性 | §4 登记版本观测差额 |
| 迁移与回滚 | 纯文档，可整体回退 |
| 外部授权记录 | 无（删除旧接口属签认后动作） |
| 未测试项 | 实际分发数量（仓库不可证明，见 §4） |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 1. 已发版本清单（git 证据可追溯部分）

客户桌面配置 `client/src-tauri/tauri.customer.conf.json` 于 **2026-08-26 (bb545ca)** 首次引入。`git log --follow` 给出的正式版本发布提交：

| 版本 | 发布提交 | 日期 | 备注 |
| --- | --- | --- | --- |
| （staging 试发，无独立版本号） | bb545ca→bad8a03 | 2026-08-26 ~ 08-31 | version 继承主配置；b126bab 发布整合、33d8ed0 异步发布标识、dd9bfa1 单人复刻生产安全、bad8a03 升级可区分 |
| 0.1.12 | d9a5576 | 2026-09-02 | 恢复激活码换机链路、长任务可靠性（受支持） |
| 0.1.13 | bc0248e | 2026-09-03 | （受支持） |
| （0.1.14） | — | — | **跳过，无发布记录** |
| 0.1.15 | 80a8e40 | 2026-09-03 | 视频播放与下载修复（受支持） |
| **0.1.16（当前）** | 59e10ed | 2026-09-04 | PR #92 已合并 main；视频直链、桌面下载、任务记录（受支持，基线 b211095 同版本号） |

- 仓库**不能证明**各版本实际分发数量与在用设备数（无自动更新回传，见 §4）。
- 版本号四处一致：`tauri.conf.json`、`tauri.customer.conf.json`、`package.json`、`client/package.json` 均为 `0.1.16`。
- 交付通道：CI Windows NSIS `--no-sign`（`.github/workflows/ci.yml` windows-nsis job），无 `tauri updater` 自动更新配置（两份 tauri 配置与 Cargo.toml 均无 updater 段）→ 升级为手动安装。

## 2. 客户端接口消费者清单（受支持版本 0.1.12–0.1.16）

客户包前端消费的端点组（`client/src/customer/` 全量 grep `"/api/..."` 去重）：

| 端点组 | 消费者文件 | 服务端提供方（当前 main） |
| --- | --- | --- |
| `/api/customer/activate` | `useCustomerSession.ts`、`ActivationPage.tsx` | `activation_code_routes.py:801`（router prefix `/api/customer`，`main.py` 注册为 customer_activation_router） |
| `/api/customer/sessions/{login,logout,heartbeat,switch}` | `useCustomerSession.ts`、`LoginPage.tsx` | `customer_session_routes.py`（prefix `/api/customer/sessions`）、`customer_auth.py`、`customer_session_service.py` |
| `/api/customer/devices`、`/api/customer/device-pairings/*`（含 approve） | `DeviceManagementPage.tsx`、`CustomerPairingFlow.tsx`、`DevicePairingPage.tsx` | `customer_device_routes.py`、`customer_device_service.py` |
| `/api/customer/profile`（GET/PATCH） | `CustomerProfilePanel.tsx`（经 `api.ts:5161/5172` 客户函数） | `recharge_routes.py:784/791`（prefix `/api`） |
| `/api/customer/wallet`、`/api/customer/wallet/transactions`、`/api/customer/recharge-orders*`（含 `/payment-code`） | `CustomerWalletPanel.tsx`、`CustomerRechargeDialog.tsx`（经 `api.ts` 客户函数） | `recharge_routes.py`（客户分支：wallet `:830`、transactions `:880`、充值订单 `:935` 一带）；注意 `wallet_routes.py` 服务的是 `/api/wallet` 共享面，并非客户钱包端点提供方 |
| 共享业务：`/api/projects`、`/api/generation/price-quote` 及任务/素材/文案等 | `api.ts`（客户会话经 `customerSessionToken` 附带 Bearer） | 各业务路由（CW-028 做端点级消费者清单） |

**约束**：0.1.12 依赖的"激活码换机恢复"链路端点自 d9a5576 起即为受支持客户契约；任何删除任务（CW-021/028/041/042）不得触及 §2 允许清单内端点，除非 §5 退出判据满足并经签认。

## 3. 凭据命名空间清单（CW-020 改默认配置前必须沿用）

| 项目 | 值 | 依据 |
| --- | --- | --- |
| macOS Keychain service | `video-replica-customer-credentials` | `client/src-tauri/src/customer_credentials.rs:583` |
| macOS Keychain account | 由 app_data 目录派生（`account_for(dir)`，与 production app-data dir 绑定命名空间） | 同文件 `:562`、`:700-708` |
| Windows 凭据 | DPAPI 加密文件 + 注册表镜像 identifier（首次升级启动写入当前用户注册表） | 同文件 `:33`、`:67`、`:85` 注释 |
| device-instance-id | 稳定标识，**非凭据**（clear_all 不删除） | 同文件 `:884` 注释 |
| 客户 identifier | `com.xiangshu.video-replica.customer` | `tauri.customer.conf.json:5` |

## 4. 兼容矩阵与已知差额

| 组合 | 结论 |
| --- | --- |
| 0.1.12–0.1.15 → 当前候选后端（含未审分叉整合后） | **必须兼容**：§2 全部端点契约不变；服务端字段只增不删（客户 JSON 解析按未知字段容忍策略） |
| 0.1.16 → 上一兼容后端（0.1.15 时代服务端） | 客户端仅消费 §2 端点组；新增端点（如后续客户功能）在旧后端缺席时客户端须给出明确升级提示而非崩溃（现状由 api.ts 错误分类承载） |
| 不兼容组合 | 返回明确升级结果，**禁止回退内部身份**（`workspaceAccessToken = internalAccessToken ?? customerSessionToken`，`api.ts:1225-1227` 的内部 token 优先回退由 CW-015 移除） |
| **差额：版本观测缺失** | 心跳/激活请求**不携带客户端版本号**（client/server grep `client_version|app_version` 均无命中）→ 服务端无法观测版本分布。修复（客户端上报 + 服务端记录）登记为 CW-015 合同附加项；修复前版本退出只能依赖 §5 的分发确认手段 |

## 5. 兼容退出窗口与判据（建议值，待签认）

因无自动更新、版本上报缺失：

1. **允许清单**：§2 端点组为受支持客户兼容面；删除类任务受本清单约束（承接 CW-011 合并责任）。
2. **退出判据（须同时满足 a+b）**：
   - a. 目标版本发布后其替代版本已在 ≥ 最短支持窗口（建议 **90 天**，自替代版发布日起）稳定运行；
   - b. 业务侧向全部已知客户完成升级公告并取得分发确认（人工确认记录），或版本观测差额（§4）修复后服务端观测证明目标版本建议 30 天零请求。
3. **禁止判据**：不得仅凭"新包已生成、懒加载未触发或未观测到请求"宣布旧端点无人使用（V3 清单 CW-003 保留验收底线原文）。
4. 删除旧接口前须：签认（下表）→ 承接任务先红后绿回归 → PR 由所有者 squash 合并。

## 6. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 桌面负责人（版本清单/凭据命名空间） | 已签认（owner phlong026 代签）：受支持版本 0.1.12/0.1.13/0.1.15/0.1.16（0.1.14 跳过无发布）；交付 Windows NSIS --no-sign 手动安装、无 tauri updater 自动更新；凭据命名空间冻结（Keychain/DPAPI/identifier/device-instance-id），CW-020 改默认配置前必须沿用 | 2026-09-09 |
| 后端负责人（兼容矩阵/退出判据） | 已签认（owner phlong026 代签）：§2 端点组为受支持兼容面、服务端字段只增不删、禁止回退内部身份（api.ts 内部 token 回退由 CW-015 移除）；§4 版本观测差额 + §5 退出判据（90/30 天建议值）pre-GA N/A（无真实分发/观测）、GA 触发；删除类任务 CW-021/028/041/042 受本清单约束 | 2026-09-09 |
