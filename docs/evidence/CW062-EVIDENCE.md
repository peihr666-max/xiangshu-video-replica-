# CW-062 证据文件 — main CI Linux 门红双炸弹的定位、独立修复与并行碰撞仲裁（运行时验证 + 登记）

任务：CW-062（编号外 · 代码与测试增量 → 收口为验证与登记；测试修复本体经并行协作已由 PR #45 合入 main）
分支：`feat/customer-v3-cw062-storage-test-session-auth`（独立 worktree `/Users/honor.pei/Documents/订单项目/.worktrees/CW-062-storage-test-session-auth`；初版从 `origin/main@a093f61` 创建，碰撞仲裁后重建于 `origin/main@ad19e52`）
来源：main@a093f61 自 CW-061（PR #36）合并后 CI Linux 质量门持续红，阻塞一切 PR 的 Linux 门（含在制 PR #46 CW-043、PR #48 CW-063）。CW-024 证据曾登记归因不修，PR #46 正文 Option A 路由 CW-026/CW-031 owner；经 2026-09-11 深夜占用清查（远程分支/开放 PR/认领登记/issue 四路零命中，CW-031=MERGED+CLEANED、CW-026=AUTOMATED_VERIFIED 均 closed），无人认领，本会话（用户指令"修复 PR46 和 PR48 的问题"）原子认领 CW-062 承接。

---

## 1. 根因（本会话定位，两个独立门红炸弹）

### 1.1 storage×3：CW-031 测试未适配 CW-026 收敛认证

- `server/tests/test_storage_cross_instance.py` 由 CW-031（PR #17，f5e24c9）创建后零改动；CW-026（PR #20，eea767e）改 `server/app/auth.py`：**收敛 PG 通道在全部环境仅接受客户会话 Bearer**——`authenticate_request` 在 `conn.is_postgres` 时缺 `Authorization` 头直接 401 `SESSION_TOKEN_REQUIRED`（auth.py:101-110），`X-Dev-User-Id` 内部身份在 PG 通道不可达。
- 该文件 3 个用例（`test_local_object_endpoints_fail_closed_without_cos` / `..._keep_404_when_cos_is_configured` / `..._put_is_not_fenced_on_the_desktop_lane`）经 `media_client` fixture（只挂媒体路由、无激活/会话路由）+ `X-Dev-User-Id` 头调 `PUT /api/assets/local-objects/...`；`put_local_object` 的 `actor: AuthenticatedUser` 依赖在 storage 依赖之前解析 → 401 抢在预期 503/404 之前。确定性、平台无关；GET 路由无 `actor` 依赖不受影响，3 例均败在 PUT 断言。
- **本机复现（RED）**：专用 PG16 容器 `vs-pg-cw062`（postgres:16-alpine，端口 5445，独立卷）上 `tests/test_storage_cross_instance.py` → **3 failed / 24 passed**，失败信息逐字为 `assert 401 == 404/503` + `SESSION_TOKEN_REQUIRED`，与 CI（PR #46 run 34604723609 shard-0、PR #48 run 34615706985）完全一致。

### 1.2 analytics 日期炸弹：路由级测试读真实时钟而种子日期硬编码

- `test_studio_analytics.py::test_analytics_route_scopes_by_caller` 经 `TestClient` 走真实 HTTP 路由（`studio_analytics` 的 `now=None` → `datetime.now(tz=UTC)`），种子场景却把边界日期钉死在 2026-09-05/06（`_YESTERDAY_BEIJING` = 北京 09-05 23:59 设计为"昨天"）；窗口起点 `start_day = 北京日期(now) − 6`（studio_routes.py:220）。**北京时间 2026-09-12 00:00 起 7 天窗口滑出该边界行 → `range_completed` 5→4**。当天早些时候的 CI（09-11 21:47 CST）尚在窗口内故绿——典型日期定时炸弹，与任何代码改动无关。
- 本会话首轮分片全量（北京 09-12 00:14–00:20，炸弹引爆 14 分钟后）shard-3 唯一失败即此例（774 passed / 1 failed），与本会话改动零共享状态（该测试用独立 SQLite tmp 库）。不修它，storage×3 修完后 Linux 门依旧红。

## 2. 本会话修复实施（已在独立分支完成并全绿，后经仲裁让位，见 §3）

- storage×3 → 迁移到既有 `customer_lane` fixture + `_activated_customer` + `_business_login` + `_bearer(session_token)`（与同文件 C 组 upload-intent 用例同款），业务断言一字未动，删除失去消费者的 `media_client` fixture。GREEN：**27 passed**（真实 PG，含既有 24 例零回归）。
- analytics → 按文件内既有 `MidnightClock` 模式（`datetime` 子类 + `monkeypatch.setattr(studio_routes, "datetime", ...)`）冻结路由时钟到种子锚点 `_NOW`，种子与断言一字未动。GREEN：**8 passed**；两文件按 shard-3 清单顺序合跑 **35 passed**（邻接无互扰）。
- 静态门（首树）：`npm run check:static` exit 0；ruff/format/mypy 全绿。
- 分片全量（首树，4×独立 PG 容器）：**4/4 分片 PASS，658+662+505+775 = 2600 passed / 1 skipped / 0 failed**。

## 3. 并行碰撞与仲裁（诚实登记）

- 本会话收尾 push 前核对时发现 **origin/main 已于 00:34（+0800）前进到 `ad19e52`**（PR #45 合并）：巡查自动化（COORD-STATUS-AUTO，每小时例行）在其标题为纯文档的 PR #45 分支上**中途追加了同意图的两个测试修复**（storage 迁移 customer_lane+Bearer、analytics 冻结路由时钟），随文档一同合入 main。
- 本会话开工时的四路占用清查（分支名/PR 标题/认领登记/issue）当时确实零命中——PR #45 当时只有文档提交；测试改动系会话中途追加，清查方法论对"在制 PR 中途换轨"存在盲区，此局限如实登记（改进建议归 COORD 排班清单维护方：在制 PR 的 head 提交级监控）。
- **仲裁原则：保全先合入 main 的成果，避免同一修复双版本竞争**。本会话放弃自己的测试文件版本（内容与 main 版意图一致、实现略异），将 CW-062 收口为：对 main 版修复的**运行时验证**（巡查侧本机无 Docker/PG，仅 `--collect-only` 验证；其 CI 分片 pytest 步骤因路径过滤未执行——ad19e52 的测试修复在合入时点无任何运行时证据）+ 账本/认领登记收口。
- **运行时验证（本会话提供，真实 PG16@5445）**：ad19e52 版本的两测试文件合跑 → **35 passed**（含 storage×3 迁移版与 analytics 冻结版全部用例）。
- **main 树完整门禁（ad19e52，本会话补齐巡查缺失的证据）**：`npm run check:static` exit 0 + 分片全量 4/4 PASS（0 failed）——计数详见 §6。
- 本 PR 变更集：仅 `docs/`（本证据、账本 §18 CW-062 行、认领登记行）+ 本机共享 claim（`.git/codex-task-claims/CW-062/claim.json`，不入库）。**零代码变更**。

## 4. 与相邻任务的边界

- **PR #45（COORD-STATUS-AUTO）**：测试修复本体的作者归属与合并记录归其所有；本任务提供其缺失的运行时验证证据并登记碰撞事实，无代码重叠。
- **PR #46（CW-043）/ PR #48（CW-063）**：不触碰其分支。解阻路径：main（ad19e52+）Linux 门转绿后，两 PR 从最新 main 更新分支（rebase）或重跑 CI 即绿——其红因（storage×3 + analytics 日期炸弹）均已在 main 修复并经本任务运行时验证。
- **CW-026/CW-031**：零触碰交付物；storage 修复是对 CW-026 收敛认证决策的回归适配，CW-031 围栏业务语义断言原样保留。

## 5. 诚实边界

- 同类"日期硬编码 + 真实时钟"风险不排除还有未引爆实例（同一时刻全量仅暴露此 1 例）；周期性排查建议归 CW-044（CI 收口）/ CW-045（最终候选全量复验）。
- 证据层级：AUTOMATED_VERIFIED（自动化验证）；不涉及 staging/真实链路，不提升层级。
- 方法论教训：认领清查需包含在制 PR 的 commit 级差异监控；纯标题判断在长寿命巡查分支上不可靠。

## 6. 验证记录汇总（真实 PG16 容器 vs-pg-cw062@5445 + 4 分片独立容器）

| 项 | 树 | 结果 |
| --- | --- | --- |
| storage 文件 RED（复现 CI） | a093f61 + 本会话修复前 | 3 failed / 24 passed（逐字同 CI） |
| storage 文件 GREEN | 本会话修复 | 27 passed |
| analytics 文件 GREEN | 本会话修复 | 8 passed |
| 两文件 shard-3 顺序合跑 | 本会话修复 | 35 passed |
| 分片全量 4/4 PASS | 本会话修复树 | 2600 passed / 1 skipped / 0 failed |
| 两文件合跑（main 版本运行时验证） | ad19e52 | 35 passed |
| check:static + 分片全量 | **ad19e52（main）** | 全绿（详见 PR 描述计数） |
