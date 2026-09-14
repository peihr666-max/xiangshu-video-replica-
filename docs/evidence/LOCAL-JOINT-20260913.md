# LOCAL-JOINT-20260913 — 本地联合调试与管理操作调整

## 目标、授权与基线

用户在本地联合测试中连续提出：前后台品牌统一；增加积分自动生成单号、首步填写事由后直接确认；管理端取消设备绑定展示；API 端点成本与售价表格编辑；前台隐藏供应商及内部计费说明；侧栏一屏与响应式字体；管理员选择默认充值通道；删除指定费用科目和旧版兼容价格设置；使用支付宝、微信支付官方标识。上述为同一联调任务的持续范围，不创建重复 CW 任务。

基线 `origin/main@400bbaa3af7fd1290fad7e949b328df349ec8203`；独立分支 `chore/local-joint-admin-brand-20260913`；工作树为仓库上级 `.worktrees/LOCAL-JOINT-20260913`。Owner：Codex 当前任务；Reviewer：待 PR 评审，不宣称完成独立评审。开工时远程唯一开放 PR #96 为 API/session 适配器；本任务保留 `api.admin.ts`、`api.ts` 不变，新增支付写请求复用既有受保护 `adminWrite`。

## 实现与文件边界

- `AdminApp.tsx`、`admin-login.css`、`styles.css`、`vite.admin.config.ts`：两端共用 `public/studio/brand.png`；管理打包只复制该资源；侧栏删除当前模块区块并压缩导航，右侧统一字体，窄屏切换抽屉与单列表单。
- `CustomersPage`、`SessionsPage`：来源单号使用随机 UUID 自动生成；首步事由和积分校验，下一步只显示确认内容；模糊失败保留相同幂等键。后台充值权限及服务端审计契约保留。
- `CustomersManagementPage`、`OverviewPage`、`ActivationCodesPage`：移除设备列表、设备数量、绑定/解绑/替换/配对审批入口；原 `DevicesPage` 及其测试退役。客户管理仅显示客户列表；移除激活码列、设备与会话页签，客户详情不再读取会话和调账摘要。ID 旁增加图标复制、双击复制及结果提醒；充值核验与接口用量折叠，右上角重复身份删除，左下角显示头像。历史数据库记录不删除。
- `BillingRatesManager`、`SystemSettingsPage`：API 端点和价格表在选中行直接编辑成本、售价、收费开关与取整，事由由系统自动生成，保存保留版本/幂等控制；隐藏云存储、ZPay、质量检查和分析修复四个内部科目。
- `StudioWorkspace`、`ContentPages`、删除的 `BillingModulePrices`：客户页面移除供应商提示与内部价格说明。`billing_routes`、`customer_pricing_routes` 对客户响应过滤不允许收费的内部科目，管理员仍有完整后台数据。
- `PaymentSettingsSection`：删除“充值限制与旧版兼容价格”表单。显示默认通道 ZPay / 微信官方 Native；按选项展示商户配置，写操作需审计原因与确认。商户秘密输入留空保留旧值；响应只显示掩码。支付图标存于 `client/src/assets/payments/`，来源见其中 `SOURCES.md`，素材来自支付宝与微信支付官方网站。
- `account_admin_routes`、`settings`：加密保存微信商户 AppID/mchid/证书序列号/API v3 密钥/PEM 私钥；默认通道持久化。写接口使用管理员身份、CSRF、审计和幂等契约；未配置完整商户及 HTTPS 回调域名时拒绝启用。待支付微信订单存在时禁止换 AppID/mchid，创建订单与配置更新使用同一事务锁。
- `recharge_routes`、`wechat_native_provider`、`CustomerRechargeDialog`：新客户订单使用默认通道；重放和已有订单按原 provider；微信 Native 在本地订单提交后请求支付链接，缓存 code_url，并用新增 `qrcode[pil]==8.2` 输出 PNG。微信扫码提示替代跳转网页按钮；已有签名回调与网关补发按原通道核验。
- 新增迁移 `20260913T1800_payment_channels`，父节点 `20260913T1100_itemized_billing`；增加默认通道与微信配置支持，允许 Native 订单在取二维码前入库、兼容 Native 不返回 prepay_id。旧迁移文件不改；有微信业务数据时降级明确拒绝。同步迁移 manifest、head 契约和实测 schema 摘要。
- `H3AccountsManager`、`h3_account_pool`、`generation`、`generation_worker`：管理员维护加密账号与自定义正整数并发额度；原设置存在时首次保存将旧任务绑定原账号，之后按最近分配时间轮询空闲账号。账号额度独立于口播任务，暂停账号不阻塞其他账号接单；已提交任务查询和恢复使用绑定账号。相同密钥不能重复计入额度，已有任务的账号不能覆盖密钥，可新增账号并暂停旧账号。模糊提交保留账号额度直到核验终态，降低限额只影响新任务。
- 新增迁移 `20260913T1825_h3_account_pool`，父节点为上述支付迁移；建立加密账号表与任务绑定表。仅 PostgreSQL；含账号数据时拒绝破坏性降级。历史 SQLite 导入工具登记两个 PG 专属空表及 `runtime_settings.active_payment_provider`，保持导入/核对契约。
- `CustomerPricingManager` 只保留“每 1 元充值获得积分”输入，保存保留已有消费折扣与取整配置；移除历史余额策略、数字人口播价格及指定说明文本。`BillingEconomics` 的筛选在宽屏按四列、窄屏按两列/单列对齐。服务配置分 API 服务与运行控制。
- 对应既有组件/API 测试随行为更新。临时环境脚本、测试账号和运行日志只保存在工作区外层 `.dev-env/local-joint/` 与 `outputs/local-joint-20260913/`，不进入仓库。

## 联调环境与数据保留

| 服务 | 地址/资源 |
| --- | --- |
| 前端 | `http://127.0.0.1:5173/` |
| 管理端 | `http://127.0.0.1:5174/admin/` |
| API | `http://127.0.0.1:8000/` |
| PostgreSQL 16 | 专用 `zszj-local-joint-pg-20260913`，本机 5544，库 `zszj_local_joint` |
| Worker | 独立后台进程，与 API 共用专用联调库及 local 存储 |
| 持久化 | 专用 Docker volume，上传目录 `.dev-env/local-joint/storage/` |

两端同源 `/api` 代理到 8000；正常客户及管理员密码登录。旧兼容控制入口的开发代理凭据仅用于本机联调，不充当生产权限验收。私有目录 ACL 限当前用户、Administrators、SYSTEM；新账号及密钥首次生成，后续启动保留。停止前核对 PID 创建时间和源码工作树，不停止其他任务服务。

支付升级后的重启验证通过：3 个账号、3 个钱包、2 个客户会话、1 个管理员会话及全部钱包余额摘要一致；schema 升至 `20260913T1800_payment_channels`，凭据文件摘要不变，四服务均运行。重复启动不产生重复进程。证据 `payment-restart-results.json`；服务按 API 健康后再启动前端，避免启动瞬间代理失败。

## 验证证据

1. 初始品牌/环境范围完整本地 `npm run check`：1389 前端用例、1952 后端通过 / 1 原有跳过。后续用户扩大到支付迁移，最终范围另行执行完整门禁，不能把初始结果算作新支付验收。
2. 红绿测试：支付配置新增 UI 测试最初 5 失败 / 2 通过，实现后 7 通过；默认通道 API 测试先因缺字段失败，完成实现后通过。一次 PEM 换行断言失败已按规范化保存内容修正。价格客户响应过滤的旧断言已更新为客户可见科目。
3. 受影响 API 专项 68 项中初次 67 通过，唯一 PEM 断言修正后单项通过；覆盖模拟网关、微信秘密加密/掩码/留空保留、拒绝未配置通道、订单重放、原通道二维码、Native PNG 与缓存。新增非写角色拒绝和待支付订单商户身份保护纳入最终全量。
4. 最新完整 Linux 静态阶段已通过：Biome、TypeScript、前端测试、e2e lint、cargo fmt/check、Ruff/format 和 mypy。支付阶段全量为 1947 passed / 1 skipped / 6 failed；失败全部来自历史导入工具未登记新支付列，已修复并在 61 项通过的专项中验证导入回归。专项另 1 项仅为角色变更后会话失效返回 401 的断言修正。账号池首次全量 `pool-final-quality-v2.log` 为 1957 passed / 1 skipped / 1 failed，唯一失败是新增账号池测试未登记分片清单；已按原生成脚本补齐四片，未跳过或弱化检查。最终 `post-review-check.log` 通过：完整 Linux 静态门、前端 1382 项、后端受影响专项 32 项、迁移守卫；分片登记的失败已经真实复验通过。首次完整门在本任务初始范围为前端 1389 / 后端 1952 passed / 1 skipped；扩大范围的失败记录保留，不伪称后两次全量原日志全绿；原支付日志 `payment-quality.log`，独立容器/测试 PG，无并发共享 fixture。
5. 迁移守卫 `--check` 通过；账号池 head 在新空白 PG 实测 89 表、1052 列、290 check 约束，schema 摘要 `9cb4f76d0e9b074bb71e2f229a98b0dd473c399890555adc18d675396e01c2d9`。不使用旧测试辅助表污染的测量结果。
6. 手工浏览器：两端登录、正式共享 Logo、API 列表、表格行内编辑与取消、支付旧版设置不存在、两个官方图标加载成功、ZPay/微信表单切换。桌面侧栏 706px 视口内无需内部滚动；390px 窄屏全页无横向溢出，价格表内部横向滚动。临时视口模拟已清除，保留用户在用页面。
7. 新增账号池+公平队列专项 16 passed：6+12=18、并发工作进程不超额、暂停账号继续查询、密钥去重、乐观锁、旧任务归属。管理员账号接口覆盖 CSRF、身份、加密、审计脱敏、幂等重放和角色撤销；全量已通过该文件 20 项。复核补充不确定提交保留额度及超长密钥错误不回显；账号池、管理员 API、分片守卫共 32 项通过。
8. 手工页面确认：客户图标复制提示、双击后在筛选输入粘贴得到相同 ID；服务新账号额度为空；390px 视口输入框 318px、字体 14px、文档宽 375px，无全页横向溢出。所有模拟视口已恢复。
9. 账号池升级重启 `pool-restart-results.json` 通过，余额摘要 `6e741234229e28f2616db161e550af3a1004c8e3f65868ad20e424e77913d4c3` 前后一致。
10. 管理静态资源复制钩子单独验证通过，未本地执行仓库限定为 CI 的完整构建、cargo test、audit 或浏览器 E2E。

## 限制、回退与交付

仅 `AUTOMATED_VERIFIED` / 本地界面联调范围；未完成 staging、真实商户收款或公网回调验收，不标 `REAL_CHAIN_VERIFIED` / `PRODUCTION_GO`。本地未填写真实支付/AI/COS 密钥，支付测试全部使用本地合成凭据和模拟网关，没有真实扣款。

正式使用微信官方通道仍须由用户提供商户配置、服务器 HTTPS `PUBLIC_BASE_URL`，并单独完成真实回调联调。本任务不进行真实支付、生产 COS 变更、公网发布、合并或在用工作树清理。

代码通过本任务提交回退。迁移含微信业务数据时拒绝直接降级，应先核对业务数据；停止脚本保留数据库卷和上传文件。远程 PR、最终门禁及评审状态在执行后回填。

## 使用与调度边界

管理员在“系统设置 → 服务配置 → API 服务 → 视频生成 · 多账号”添加账号，填写名称、API Key 和该账号实际并发额度；已有密钥留空保留。总并发为启用账号额度之和，不推测供应商额度、不将 10 固定为默认值。供应商实际账号配额须与填写值相符，未进行真实付费压测。运行控制中的客户公平队列若开启，仍保留原有单客户公平调度规则；账号池不自动关闭该策略。

## §14 完整记录

```text
任务/工作包：LOCAL-JOINT-20260913 / 本地联调持续反馈
Owner / Reviewer：Codex 当前任务 / 待 PR 评审
分支 / 基线 SHA：chore/local-joint-admin-brand-20260913 / 400bbaa3af7fd1290fad7e949b328df349ec8203
上游规格段落：本任务用户逐项联调要求，最新并发按账号独立配置及管理界面精简指令
改动文件：上述文件边界、两项追加迁移、对应前后端测试、四份账本及本证据；api.ts/api.admin.ts 不改
失败测试或回归锁定：已有界面断言随删除入口更新；历史导入六项失败修复；账号池并发、持久归属、权限、复制成功/失败均有专项
实现结果：本地前后端和管理员环境运行，功能和布局已交付本地测试；不声明真实商户或付费 Provider 验收
验证命令与通过数：npm run check:static（前端 1382 passed）；四片独立 PG 的完整 pytest（1959 passed / 1 skipped）；专项 32 passed；迁移守卫通过
证据层级：AUTOMATED_VERIFIED（最终本地完整 Linux 质量门通过）；远程 CI 与独立评审待 PR
安全与可观测性：密钥 Fernet 加密、受保护管理员写入、幂等审计；账号任务绑定不含明文秘密；不确定任务保留账号槽位
迁移与回滚：1100→1800→1825 追加迁移，账号/微信数据存在时拒绝破坏性降级；重启保留用户数据
外部授权记录：本地联调、代码修改与按仓库规则提交；无真实支付/付费生成/生产存储/公网发布授权
未测试项：真实账号多并发压测、真实微信商户回调、staging/生产；CI 专属构建/安全依赖审计/Windows NSIS 待远程执行
Lore 提交 SHA：cc247c1（本地实现提交），未推送、未合并
```


最终交付前仅重启 API/Worker，前端进程保持原 PID，账户数 3、H3 配置数 0、余额摘要及 schema 均不变，见 `final-backend-restart.json`。账号池未填写真实凭据，未触发收费任务。自检已修复：暂停账号影响其他账号容量、模糊提交提前释放额度、超长密钥错误回显、历史导入列登记和新增测试分片登记。远程 Draft PR 与 CI 状态以 PR 为准。

最终提交前全量复验：官方分片清单覆盖 93 个测试文件，四个独立 PostgreSQL 16 容器各自执行一片，锁文件亦隔离。`final-shard-0.log`：556 passed；`final-shard-1.log`：432 passed；`final-shard-2.log`：457 passed；`final-shard-3.log`：514 passed / 1 skipped。合计 **1959 passed / 1 skipped**，四片及运行器退出码均为 0；结合 `post-review-check.log` 的完整静态门与前端 1382 passed，最终本地 Linux 质量门全绿。代码自补充复核后未再改动；前述失败日志为历史修复证据。

交付状态：实现提交 `cc247c1` 已保存在本地，工作树与联调服务保留。推送到既有 GitHub origin 的动作被自动审批拒绝，理由为尚未验证远程目的地及用户对此次代码发送的明确授权。未绕过拒绝，未创建 PR；待用户确认后再推送并创建 Draft PR，远程 CI 与独立评审尚未运行。

## 本轮管理端表格、积分单位与支付配置收尾

2026-09-13 继续本任务，完整实现与前后端分析见 [管理端分析报告](LOCAL-JOINT-20260913-ADMIN-REVIEW.md)。本轮新增客户表格/详情精简、查询响应保护、积分成本换算和版本锁、统一字体/响应式，修复支付默认通道与商户输入分开保存的问题，统一配置确认弹窗。无新增数据库迁移，不改变已存在的凭据、钱包余额、历史支付订单通道或 H3 任务归属。新增文件仅为账务金额换算/类型、对应前端测试和分析文档。

### 最新完整质量门

`admin-polish-static-final.log`：完整 Linux 静态门通过，前端 **1390 passed**，Biome、TypeScript、e2e lint、cargo fmt/check、Ruff/format、mypy 与秘密扫描均成功。支付修复第一次完整前端门有一项旧集成测试仍要求填写原因，更新为新的直接确认断言后真实复验通过；旧失败日志保留为 `admin-polish-static-old-dialog-failure.log`。本地不运行 CI 专属完整构建、cargo test、依赖审计或浏览器 E2E。

| 分片 | 本地日志 | passed | skipped | 退出码 |
| --- | --- | ---: | ---: | ---: |
| 0 | `admin-polish-shard-0.log` | 556 | 0 | 0 |
| 1 | `admin-polish-resumed-shard-1.log` | 432 | 0 | 0 |
| 2 | `admin-polish-resumed-shard-2.log` | 459 | 0 | 0 |
| 3 | `admin-polish-shard-3.log` | 514 | 1 | 0 |

后端合计 **1961 passed / 1 skipped**。0、3 分片在 Docker 中断前完成；未完成的 1、2 分片分别补跑，既有中断日志保持原样。比对代码内容确认没有后端变更，93 个测试文件由官方 manifests 完整覆盖，每片使用独立 PostgreSQL 16 及独立锁文件；不把中断结果或未运行的项目记作通过。汇总 `admin-polish-final-results.json`。

第 1 片首次恢复时数据库尚未接受连接，测试环境初始化失败，产生 238 个 setup error、194 passed；原日志 `admin-polish-shard-1-recovery-failure.log` 保留。确认 `pg_isready` 接受连接后重跑该片，结果以上表为准，未改变业务代码或跳过检查。

### 页面与环境核验

本地浏览器实际沿用用户已保存的 ZPay 配置，默认通道提交成功，确认弹窗无额外原因或勾选。此操作仅保存本地设置，没有真实支付请求。管理员之后自行填写了服务密钥；前面“未填写真实密钥”描述属于此前阶段记录，不能据此推定当前数据库仍为空。新增配置与现有账号、余额都保留。

API 成本/售价均显示积分，用户当前保存 1 元 = 100 积分；正文与表格 14px。390px 客户页面标签 13px、正文 14px，没有全页横向溢出。临时标签页与视口覆盖清理，用户页面不被切换或提交。仅重启本任务 API 的验证表明账号 3、费用配置 1、钱包摘要未变；环境停止后再次恢复四服务，保留现有配置与存储。

### §14 本轮增量记录

```text
任务/工作包：LOCAL-JOINT-20260913 / 管理端持续联调反馈收尾
Owner / Reviewer：当前 Codex 任务 / 待 PR 独立评审
分支 / 基线 SHA：chore/local-joint-admin-brand-20260913 / 400bbaa3af7fd1290fad7e949b328df349ec8203
上游规格段落：用户关于客户表格、积分单位、字体、前后端代码分析及配置弹窗的指令
改动文件：客户/费用/经营/支付/运行控制组件，金额换算与类型，billing/account/control 路由及测试，四份账本与分析报告
失败测试或回归锁定：支付 UI 红灯 5 项；API 旧响应字段断言 1 项；整页旧确认交互断言 1 项；修复后完整门通过
实现结果：本地功能和手工界面确认完成；成本兑换保持精度，默认支付事务保存，配置确认步骤精简
验证命令与通过数：npm run check:static，前端 1390 passed；官方四片完整 pytest，后端 1961 passed / 1 skipped
证据层级：AUTOMATED_VERIFIED（本地完整 Linux 质量门）；staging、生产、真实支付未验收
安全与可观测性：加密/掩码、角色/CSRF/幂等审计保留；费用写入校验换算版本；不泄漏凭据到报告与日志
迁移与回滚：本轮无新增迁移；代码通过本任务提交回退，保留现有数据库与上传存储
外部授权记录：本地联调与保存既有 ZPay 默认配置已授权；此前远程推送被自动审批拒绝，尚未收到明确发送授权
未测试项：真实商户回调、真实付费生成、生产性能基准、远程 CI 与独立评审
提交 SHA：c06dcde（本轮本地实现）；未推送、未合并
```

自检结论与未完成的进一步重构明确列于分析报告。最优先的后续事项是统一仪表盘与经营分析财务读取，而非直接删除历史核算表；八个不可达模块和重复查询可以分批退役。本轮不删除业务底账、不把隐藏设备界面扩大为删除鉴权数据。


## 报告建议第一阶段：核算读取统一

2026-09-13，用户批准按分析报告逐步修改。本阶段优先解决财务读取不一致，继续原联调任务。开工核对 main=f401a0b、PR #96 merged、开放 PR 为空；共用认领范围已更新，保留其他活跃人物/链接任务。GitHub 连接器曾返回 403，改以公开 GitHub REST 和 git fetch 核实，没有据连接器失败猜测 PR 状态。

实现：总览直接使用 billing_reports.statistics 的每日结果；成本计入每个有效尝试，收入仅取冻结的结算事实。待处理、缺成本、缺收入或旧记录无新版关联时保持待核对。历史成本和旧 SETTLE 仅标记覆盖缺口，不估价、不回填。关联的兼容镜像排除。日期边界使用上海时区，旧覆盖按日期/客户保守统计，不按无法确认的科目/提供商分配。统计路由采用 REPEATABLE READ，减少一次响应内读取快照不一致。

仪表盘删除设备、配对、激活码查询和字段；成本配置待办读取 billing_tariffs 并尊重零成本及免费配置。前端修复空成本卡片/图表误显示为零的问题，历史记录仅在存在时显示简短提醒。完整类型变更限于 DashboardSummary，保留已合并的请求适配边界。未添加数据库迁移，未删除用户或账务数据。

测试先行：`admin-report-p1-red.log` 后端 4 失败 / 3 通过；`admin-report-p1-front-red.log` 前端 2 失败 / 1 通过。实现后首次专项 30 通过 / 1 失败，发现 Decimal 输出字符串与仪表盘数字契约不符，已在展示边界转换数字并复验。最终专项 `admin-report-p1-targeted-final.log` 32 passed；OverviewPage/AnalyticsPage 4 项通过。首轮完整静态门仅因 billing_routes 混合换行格式失败，保留 `admin-report-p1-static-format-failure.log`；规范化后再次运行正式质量门，未将失败计作通过。

实际本地接口：已有管理员凭据只用于 localhost 登录；读取 summary 和 statistics 并逐项比对，账号数 3、tariff 数 1、钱包摘要保持相同，四项联调进程健康，见 `admin-report-p1-local-api.json`。初次 API 重启遇端口刚释放尚未可绑定，稍后恢复成功。临时浏览器页为登录态，浏览器文件读取不能访问受保护凭据，已关闭该页；本阶段不声称已完成登录后的浏览器手工验收。用户两个设置页未导航或重载。首次临时 HTTP 核验的注销头写错返回 403，凭据未记录或输出；正确 CSRF 头的复验成功并注销该次会话。未发起真实支付或付费生成。

### §14 第一阶段增量记录

```text
任务/工作包：LOCAL-JOINT-20260913 / 分析报告 P1 核算统一
Owner / Reviewer：当前 Codex 任务 / 代码自检，待 PR 独立评审
分支 / 基线 SHA：chore/local-joint-admin-brand-20260913 / 400bbaa3af7fd1290fad7e949b328df349ec8203
上游规格段落：用户批准按管理端前后端分析报告逐步修改
改动文件：admin_dashboard_routes、billing_reports、billing_routes；OverviewPage、BillingEconomics、DashboardSummary 与相关测试；四份账本及分析/阶段证据
失败测试或回归锁定：后台 4 项失败，前台 2 项失败；缺成本、历史覆盖、逐项核算及待配置来源
实现结果：共同财务读取、上海周期、已确认/待核对分离、旧账不重估、无用仪表盘查询删除
验证命令与通过数：专项后端 32、前端 4 通过；最终完整质量门见下文
证据层级：AUTOMATED_VERIFIED（本地完整 Linux 质量门）；无 staging 或生产证据
安全与可观测性：保留身份/CSRF、账务不可变记录、用户商户/服务配置；本次财务路由只读
迁移与回滚：无新增迁移；代码按本阶段提交回退，保留历史底账和持久化数据
外部授权记录：本地修改/验证已授权；此前远程推送自动审批拒绝未解除
未测试项：生产容量、真实支付/生成、远程 CI、独立评审、登录后的浏览器手工验收
提交 SHA：d9c746e364655c58fde760c012c7de1fe2371570（本地实现，未推送）
```


### 第一阶段最终完整质量门

完整 Linux 静态门与前端 **1391 passed**；后端四片 **1964 passed / 1 skipped**，93 个测试文件全部覆盖。

| 分片 | passed | skipped | 日志 |
| --- | ---: | ---: | --- |
| 0 | 556 | 0 | `admin-report-p1-shard-0.log` |
| 1 | 432 | 0 | `admin-report-p1-shard-1.log` |
| 2 | 462 | 0 | `admin-report-p1-shard-2.log` |
| 3 | 514 | 1 | `admin-report-p1-shard-3.log` |

四片各自使用 `local-joint-report-p1-pg-{0..3}-20260913` PostgreSQL 16 容器和独立锁文件，启动后核实 pg_isready。全部退出码 0，未因失败跳过任何测试；唯一 skip 为既有测试，详情保留原始日志。静态门 `admin-report-p1-static-final.log` 包含 Biome、TypeScript、前端、e2e lint、cargo fmt/check、Ruff/format、mypy 与秘密扫描。未在本地执行 CI 专属构建、cargo test、npm audit 或浏览器 E2E。

核对正在使用的 1069 个非文档源文件与最终测试快照 SHA256 完全相同。代码自检 `admin-report-p1-self-review.json`，汇总 `admin-report-p1-final-results.json`，实际服务核验 `admin-report-p1-local-api.json`。新增证据文件链接检查与秘密扫描通过后进行本地文档提交。远程仍待此前明确推送授权，不冒称 PR/远程 CI/独立评审完成。

四个本阶段临时 PostgreSQL 容器已在核对专属标签后删除；用户联调数据库继续运行，两个原有管理设置标签页保留。最终文档本地链接及秘密扫描已通过。
