# FIX-TESTBASE-20260912 — 独立前置：日期敏感测试夹具

任务/工作包：独立前置：日期敏感测试夹具。

Owner / Reviewer：Codex（01a094e2-9d59-73e3-8b2d-280723c19e7e）/ review_w13（只读独立评审 PASS）。

分支 / 基线 SHA：fix/test-baseline-fixtures-20260912；最新 origin/main@55220f7e5a84b06e748f98324bfed141f2e6fb94。独立 worktree 从主分支创建，未从其他任务分支派生。

上游规格段落：主分支固定发布时间在 2026-09-12 超出最近七天窗口，导致既有爆款视频路由测试失败；本项不计入首组五个业务任务。

改动文件：server/tests/test_viral_routes.py；本任务账本和证据。

失败测试或回归锁定：origin/main@55220f7 原夹具聚合结果为 0，既有断言期望 8；没有删除或放宽生产过滤条件。

实现结果：测试样本时间改为当前前一天；新增过期八天和未来一天的样本，断言正常八条保留、两类越界样本被排除。生产代码、真实外部调用均无改动。

验证命令与通过数：独立评审 PASS；完整本地静态门通过（全量前端、TypeScript、Biome、Tauri、ruff、format、mypy）；服务端分片完整覆盖检查通过，全量运行中。此前磁盘同步过慢的分片被中断，保留中断日志，不记作通过。新分片使用独占 PG16 临时内存盘，fsync 和 synchronous_commit 保持默认开启，SQLite 仅沿用已有兼容测试。

证据层级：AUTOMATED_VERIFIED（本地代码质量门）；远程 PR CI 与合并待验证。未提升到人工联调或生产验收。

安全与可观测性：没有真实密钥、用户数据或外部生产操作。remediation-fast-quality + vs-pg-fix-fastbase-0..3；无主机端口；每分片独占PG。

迁移与回滚：无数据库迁移和依赖变更；通过正常 PR revert 回滚代码，保留既有数据。

外部授权记录：用户已授权独立 worktree、每五个任务一组开发、独立只读子代理评审、提交 PR 及合并；生产和真实服务联合调试由用户团队执行。

未测试项：仅修复可重复执行的测试基线，不构成真实供应商或产品上线验收。

Lore 提交 SHA：不适用；提交、PR 和最终 squash SHA 后续回填。

## 完整本地质量门

2026-09-12：完整静态门通过，前端 82 文件 1344 passed；TypeScript、Biome、e2e lint、Tauri cargo fmt/check、ruff、format 和 mypy 均通过。服务端四个独占 PG16 分片分别为 794、616、674、761 passed，合计 2845 passed、1 skipped，各退出码为 0；测试文件覆盖检查通过。跳过项为原有 `test_bootstrap_accepts_valid_pg_all_environments[production]`，原因是普通测试 PG 未配置生产 TLS，相关严格 TLS 配置断言由 `test_db_pg.py` 覆盖；不将跳过记为通过。

日期夹具专项 49 passed。原慢速分片中断日志保留、不算通过；最终完整证据为工作区 `outputs/remediation-20260912/TESTBASE-fast-shard-0.log` 至 `TESTBASE-fast-shard-3.log` 和 `TESTBASE-static.log`。本次临时 PG 使用内存盘，保持 PostgreSQL 默认事务与同步配置；不代表持久性、灾备或生产容量验收。

独立评审 review_w13：PASS，无阻塞问题；确认仅变更测试夹具，生产时间过滤与过期/未来过滤语义均保留。
