# CW-002 — 平台与条件业务范围决议（草案，待责任人签认）

## 任务信息（§14 模板）

| 字段 | 值 |
| --- | --- |
| 任务/工作包 | CW-002 补齐平台与条件业务范围决议 |
| Owner / Reviewer | Owner：ZCode 代理（hlong026 会话，2026-09-09）；Reviewer：独立复核子代理 + 待产品负责人/架构负责人签认 |
| 分支 / 基线 SHA | `feat/customer-v3-cw02-platform-scope` / 基线 `origin/main@b211095` |
| 上游规格段落 | V3 清单 §4 CW-002；§5 客户业务验收矩阵；§8 可量化阈值 |
| 改动文件 | `docs/evidence/CW002-SCOPE-DECISIONS.md`（新增） |
| 失败测试或回归锁定 | 不适用（决策与静态核验层） |
| 实现结果 | 见下文范围表 |
| 验证命令与通过数 | 静态核对：`grep`/文件行号逐项核对（见各表"依据"列） |
| 证据层级 | 决策与静态核验（签认前不得视为完成） |
| 安全与可观测性 | 不适用 |
| 迁移与回滚 | 纯文档，可整体回退 |
| 外部授权记录 | 无 |
| 未测试项 | 签认字段 |
| Lore 提交 SHA | 本 PR squash 后回填 |

## 1. 已确认边界（沿用既有决策，本项不重选型）

- 产品形态：客户桌面端（Tauri）+ 云端后端服务；不再维护独立内部产品线（V3 清单 §1 规则 1）。
- 数据库：全环境 PostgreSQL（开发/测试/CI/staging/生产），历史 SQLite 仅按精确例外用于独立 operator 与受保护输入。已由用户确认，本项仅承接。
- 数据库行为测试一律真实 PG；UI、纯逻辑及外部服务可受控替代（V3 清单 §1 规则 3）。

## 2. 支持平台决议（建议值，待签认）

| 平台 | 决议 | 依据 |
| --- | --- | --- |
| 客户桌面 — Windows 10/11 x64 | **保留（唯一支持桌面平台）** | CI 唯一桌面构建门禁为 `windows-2025` NSIS（`.github/workflows/ci.yml:146-149`）；客户包配置 `tauri.customer.conf.json` 仅含 Windows NSIS bundler 与 `customer-installer-hooks.nsh` |
| 客户桌面 — macOS | **不支持（本轮）** | 无 macOS 构建/签名/公证流水；Tauri 客户配置无 dmg/targets 声明。如需支持须按 CW-002 追加决议并登记 CW-022/023/046 平台差额 |
| 客户桌面 — Linux | **不支持（本轮）** | 同上，无 AppImage/deb 目标 |
| 后端服务 — Linux x86-64 | **保留** | `deploy/systemd/`、`deploy/customer-git-rollout.sh`、`deploy/postgres/` 全部以 Linux systemd/容器为目标 |
| 管理网页 — 现代浏览器（Chromium/Firefox/Evergreen） | **保留** | `client/src/admin/` 独立 React 页面，随服务器静态部署（CW-019 拆分后归属后端部署） |
| 移动端 | **不支持** | 无任何移动构建目标或适配工作包 |

## 3. 保留功能范围 — F01–F12 映射（CW-018 自动化与 CW-049 UAT 共同最小覆盖）

页面枚举依据 `client/src/studio/types.ts:3-24`（`StudioPage` 21 个页面值）。

| ID | 业务 | 保留页面/入口 | 当前状态 | 范围结论 |
| --- | --- | --- | --- | --- |
| F01 | 激活、设备、会话和资料 | 客户状态机（`client/src/customer/`：激活/登录/冲突/失效/撤销/配对）+ `profile` | 已实现，整屏激活门禁 | 保留 |
| F02 | 工作台和项目 | `workbench` + 项目列表/详情 | 已实现（live.ts 接真实项目 API） | 保留 |
| F03 | 项目型视频复刻 | `replica`、`reference`（源帧/首帧/Prompt/批次） | 已实现 | 保留 |
| F04 | 独立视频创作 | `video` | 已实现（独立生成三模式） | 保留 |
| F05 | 人物、场景和首帧 | `people`、`person-ip`、`person-photos`、`person-avatars`、`person-voices`、`replacement` | 已实现 | 保留 |
| F06 | 口播与音频 | `oral`（文本）、`oral-audio`（音频） | 已实现 | 保留 |
| F07 | 文案提取与改写 | `copy` | 已实现 | 保留 |
| F08 | 素材库 | `materials` | 已实现 | 保留 |
| F09 | 爆款与收藏 | `viral`、`viral-detail` | 已实现（TikHub 真实数据） | 保留 |
| F10 | 任务和结果 | `tasks`、`task-detail` | 已实现 | 保留 |
| F11 | 钱包与充值 | `profile` 内客户钱包两个入口 | **已知缺陷**（两入口上下文不一致，CW-016 修复） | 保留（先红后绿） |
| F12 | 管理和经营看板 | `analytics`（客户仅本人）+ `client/src/admin/`（管理员） | 已实现 | 保留 |
| — | 发布管理（`publishing`） | `publishing` 页 | **未接通**：按钮为诚实提示"正式发布（接口未接通）"（`client/src/studio/ContentPages.tsx:1764-1768`）、"发布账号服务尚未接入"（`client/src/studio/MainPages.tsx:1220`） | **不纳入本轮完工口径**：保留诚实提示或按确认范围隐藏（V3 §5 发布管理条款）；若纳入须先补专用验收矩阵 |

## 4. 游客浏览门禁决议（CW-014 条件依据）

- **决议建议：不启用游客浏览，CW-014 登记为 N/A。**
- 依据：当前客户产品为整屏激活门禁——未激活/会话失效时仅渲染客户状态机（激活/配对/冲突/失效壳），身份建立成功后才挂载工作台；公开游客壳及"目标动作续接"从未实现；V3 清单 CW-014 明确"DEV ReviewWorkspace 不等同正式游客产品"。
- 影响：`publishing` 等未接通入口对未激活用户同样不可达，无需公开壳。
- 签认：待产品负责人确认。若改判启用，CW-014 转为开发项并补公开壳/私有动作门禁/一次续接全部用例。

## 5. 条件任务启用依据登记

| 条件任务 | 启用条件 | 当前事实 | 决议状态 |
| --- | --- | --- | --- |
| CW-014 游客激活门禁 | CW-002 明确保留游客浏览 | 整屏激活，无游客壳 | 建议 N/A（待签认，见 §4） |
| CW-034 保留客户PG（路线A） | 数据批次裁决选 A | 待 CW-005 真实数据盘点 | 保持 conditional |
| CW-035 空PG导入（路线B） | 数据批次裁决选 B | 待 CW-005；导入工具已存在（T07） | 保持 conditional |
| CW-036 选择性合并（路线C） | 数据批次裁决选 C | 待 CW-005；合并能力未开发 | 保持 conditional |
| CW-037 local 资产迁移 | 任一待保留数据存在 local/非共享持久对象 | 待 CW-031 收口后全量扫描 | 保持 conditional |
| CW-030 新增跨口播完整轮转 | CW-002 范围决定 | 现状：公平队列覆盖 H3/独立视频与口播（见 §6） | 本轮不新增公平能力，按现有限制验收（诚实登记限制） |
| 发布管理纳入 | CW-002 追加专用验收矩阵 | 未接通，诚实提示 | 不纳入（见 §3） |

## 6. 跨任务公平范围

当前代码实际覆盖（CW-030 按此范围逐类验证，未覆盖类别如实登记限制）：

- **H3/独立视频队列**：每用户 running≤1（`server/app/generation.py:4600,4644` 调度条件 `running_tasks_count = 0`，超限时 `LEAST(...,1)` 收敛）、全局并发上限 `max_concurrent_h3_tasks=100`（runtime seed，`server/tests/test_customer_queue_fairness.py:148`）、公平轮转 cursor（`server/app/generation.py:4491` 附近，轮次上限见 `test_customer_queue_fairness.py:544`）。
- **口播队列**：`server/app/oral_worker.py:178,306,940` 复用同一 `user_queue_cursors` 轮转与 running≤1 模式。
- **未纳入公平队列的类别**：图片生成（character_image_generation）、分析/文案/ASR（analysis、script_rewrite、script_from_audio）当前无公平队列租约/轮转代码——本轮不扩展，CW-030 验收时逐类登记"无公平机制"的现状限制，不得以 H3 覆盖冒充。
- V3 §8/CW-047 的"A=1000/B=100/C=10"为 staging 负载验收的**建议基线数值**（未在代码中固化为常量），与本节代码现状机制分属两层，不得混写。

## 7. 签认记录

| 角色 | 结论 | 日期 |
| --- | --- | --- |
| 产品负责人（平台/游客/发布范围） | 待签认 | — |
| 架构负责人（PG 范围/公平范围） | 待签认 | — |

> 本文档为决议草案。所有"待签认"字段由对应责任人确认后才可将 CW-002 在任务账本 §18 标记完成；签认前不得以本表替代 CW-018/CW-049 的逐项验收行。
