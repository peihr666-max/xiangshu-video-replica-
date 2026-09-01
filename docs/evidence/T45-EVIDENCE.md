# T45 — 安全纵深防御收口证据

## 1. 当前结论

- 证据层级：`CODE_PRESENT`。
- 分支：`feat/customer-v3-t45-defense-in-depth`，基线
  `92bace869c413d4403372e324530d7ff1052804b`。
- 已验证实现提交：`cc563a54eadf9c746b1683fd15d89b2e530dbe7e`。
- T45 工单中的会话/幂等、支付、签名 URL、限流、状态机、404 防枚举、管理端
  SoD、审计和发布检查项均已实现并建立回归锁。
- 产品决策保持：simple 人物无需管理员审核，系统自动批准后直接生成/发布；
  同机重装输入完整原激活码并匹配指纹后直接恢复，也不需要管理员审核。
- 本机没有 Docker、`psql` 或可访问的 `localhost:5433` PostgreSQL fixture，
  PG 专项按测试合同跳过，因此不得提升为 `AUTOMATED_VERIFIED`。
- 未连接或修改生产数据库、服务器、ZPay、COS、Provider，未发码、灰度或发布。

## 2. 逐项关闭结果

| 编号 | 结果 | 回归边界 |
| --- | --- | --- |
| S-1 | login/switch 重放重新校验设备、激活码状态和活 session/epoch | 挂起码不重放 201；switch 后旧 key 不返回死 token |
| S-2 | 客户幂等 key 改版本化 keyed HMAC；解绑先匹配凭据，再使用账号+目标 scope | 跨账号/无凭据不能探测 sealed 204；已解绑目标凭据仍可恢复本人丢失响应 |
| D-1 | CLOSED 订单的合法迟到回调可幂等结算并写 notify 摘要/账本 | 回调返回 success，不再无限 409；金额仍严格匹配 |
| D-2 | 渠道校验改为系统允许且商户启用集合 | 收银台切换已启用渠道可入账，禁用渠道仍拒绝 |
| A-1 | URL HMAC 使用 HKDF 子密钥并绑定 object/user/asset/session epoch；本地和 COS 都走应用签名代理并即时复核 | 参数篡改、会话替换、授权/资产失效均拒绝；超长 expires 为 400；安全响应头齐全 |
| S-3 | login/switch 增加 per-device 桶，IP 只拦未知凭据的辅助流量 | 同 NAT 合法设备不因共享 IP 桶耗尽被连坐；单设备爆破独立受限 |
| S-4 | heartbeat/logout/device 管理在 HMAC/业务事务前消费独立预认证 IP 桶 | 未认证高频请求在固定预算后 429 |
| S-5 | fencing 拒绝按 session 事实窗口去重，并用 PG advisory xact lock 串行化并发检查 | 同 token 重复/并发拒绝不再线性增长永久行 |
| S-7 | 激活码重置加入 AEAD 幂等信封、IP/设备预算，并按激活码 scope 加事务锁阻止恢复窗口内换 key 二次重置 | 同 key 返回同一新码；异 key/过期信封冲突 |
| D-4 | 设备槽及激活相关唯一冲突映射为稳定 409 `DEVICE_SLOTS_FULL` | 并发第三槽落败不再 500 |
| D-5 | customer 的 `/api/wallet` 响应剥离内部价格字段 | 内部角色契约保持，客户看不到基础价/最低充值/步进 |
| C-2 | 外来项目、任务、版本、素材、人物和生成批次操作统一成与不存在字节级相同的 404 | 路由矩阵、分析/首帧/抽帧、同步/异步人物任务、批次删除和 optional state 均锁定同型；PG 延迟拒绝审计不丢失 |
| A-2 | 内部和客户 lane 共用管理写 `confirm/reason/Idempotency-Key` 契约 | 内部 lane 缺字段时 4xx 且无业务写 |
| A-3 | 管理 session 增加默认 30 分钟空闲超时；IP/UA 摘要变化撤销并审计 | 超时 cookie 401；上下文变化写告警事实并要求重登 |
| S-6 | 删除空码指纹恢复；同机重装必须完整原码+同指纹；开户/设备归属错误统一 | 指纹泄漏不能单独换取凭证；无需管理员审核 |
| A-4 | 删除无调用方的 `create_minimal_task` 生产写原语，测试数据改由测试夹具显式创建 | 生产 repository 不再静默造 user/project owner |
| A-5 | customer 上传 intent/completion 不返回 `storage_key`/`storage_uri` | 客户响应不含桶名和内部拓扑 |
| A-6 | 管理员自调账/自改价拒绝，并在同一幂等事务提交 `security.admin_self_service_denied` | 两类自助操作均 403 且各有审计 |
| A-7 | retry/regenerate 统一向来源批次 owner 计费；审计分别记录 billed/requested user | admin 代操作不会扣 admin，自助/代操作均可追溯 |
| C-3 | 保留 auditor 全局资产元数据读取策略，每次详情读取写 `auditor.asset_metadata.read` | auditor 仍不能写、下载或使用人物缓存 |
| B-2 | 激活码 reveal 幂等重放写独立 `admin.activation_code.revealed_replay` | 二次复制可追溯且审计不含明文 |
| B-3 | 发布说明冻结“先客户端、后服务端”；空码旧客户端只提示升级和输入完整码 | 不建立管理员审核兼容旁路 |
| E-1 | 新增生产 env 可执行预检，拒绝 dev auth/header/desktop identity | 错误配置在迁移/启动前 fail closed，输出不含配置值 |
| E-2 | 同一预检要求 metrics token 绝对路径、普通文件、至少 32 字符、POSIX 0600 类权限和 service owner | 弱 token、错误 owner/权限或缺文件均阻断 |

## 3. 验证结果

| 门禁 | 结果 |
| --- | --- |
| 密钥扫描 | `No hardcoded secrets detected in runtime contract surface.` |
| 客户端 | Biome、TypeScript、Vitest：50 个文件，592/592 通过 |
| E2E 格式 | Biome：14 个文件通过 |
| Tauri | `cargo fmt --check`、`cargo check --locked` 通过 |
| 服务端静态 | Ruff check、Ruff format check 通过；Mypy 74 个模块通过 |
| 受影响专项 | 292 通过；发现 1 个测试夹具缺签名 key，修复后相关 3/3 通过 |
| 404 旧锁复验 | 旧 403 断言升级为不存在同型后 9/9 通过 |
| 全量门禁 | Python 3.12.13；服务端 943 通过、504 跳过、0 失败，耗时 16 分 08 秒 |

保留 1 条非阻断上游提示：FastAPI TestClient 的 Starlette/httpx 弃用警告。

## 4. 上线 No-Go

- 必须在 PostgreSQL 16 fixture/隔离 staging 补跑所有跳过的 session、设备、限流、
  管理写、迁移和并发用例；完成前证据仍是 `CODE_PRESENT`。
- 必须先发布新桌面客户端，再发布 T45 服务端；确认旧客户端空码恢复提示符合发布说明。
- 生产迁移/重启前必须运行 `scripts/customer_release_preflight.py` 并得到
  `T45_PREFLIGHT_OK`；建议固定到 systemd `ExecStartPre`。
- 必须在同一候选 SHA 完成真实 ZPay 已关闭订单迟到付款、已启用渠道切换、私有 COS
  签名代理的大文件读取/吊销、Provider 和双 API 会话切换联测。
- 未完成备份、回滚演练、告警接收和上述真实链路前，不得标记
  `STAGING_VERIFIED`、`REAL_CHAIN_VERIFIED` 或 `PRODUCTION_GO`。
