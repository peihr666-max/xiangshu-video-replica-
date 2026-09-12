# FIX-TESTREADY-20260912 — 组件就绪与草稿测试前置

## 第一部分：代码修复与自动验证

任务/工作包：独立前置 FIX-TESTREADY-20260912，修复 PR #87 首次 CI 暴露的测试准备缺口。

Owner / Reviewer：Codex（01a094e2-9d59-73e3-8b2d-280723c19e7e）/ 独立只读 review_w13，最终差异 PASS，未发现本次新增 P1/P2。

分支 / 基线 SHA：fix/test-ready-state-20260912；直接从当时最新 origin/main@791fd6646288c59a84dbed1f1ec26528e862a06d 创建独立 worktree。随后只合入已正常合并的主干 cd8bccf；验证代码提交 a44672a9dae35f735a5cdcffe78ca20ec9509acd。未从功能分支或未合并快照派生。

上游规格段落：用户第一部分代码开发及每任务本地质量门；测试不就绪阻断已完成代码的可靠验收，不属于人工联合调试。

改动文件：client/src/studio/StudioWorkspace.test.tsx、client/src/AnalysisWorkspace.test.tsx；本任务登记和证据。无产品实现、迁移、依赖或 CI 配置改动。

失败测试或回归锁定：PR #87 run34702683737 首轮 Linux 前端失败于 F06 本地草稿保存及卸载后的口播晚响应测试，未进入后端；原始日志 W19-ci-first-failure.log 保留。先前 W13 也出现按钮已存在但尚不可用时触发点击的同类等待缺口；其一次诊断复跑已通过，未据此声称根因消失。

实现结果：口播打开与报价确认等待 enabled 后才操作；连续两次点击仍紧邻且保留仅创建一次、请求体及幂等键断言，卸载前额外确认请求确实开始。草稿测试先等待服务端稿初始化，再选择自定义稿且确认编辑区可编辑；断言选择、输入、落盘 text/source、重挂载恢复及跨账号隔离，保存响应 fixture 与 custom 来源一致。没有延长超时、固定 sleep、删测试或弱化业务断言。

验证命令与通过数：专项 Studio83 passed、最终 Analysis34 passed。完整门在隔离 Linux 副本 /verify/fast-testready-final 执行 bash /evidence/run_static_bounded.sh 及 python /evidence/run_isolated_shard.py 0..3（各自独立 PostgreSQL 16，无主机端口，显式 PYTHONPATH 指向当前代码，manifest 全覆盖）。后端 2957 passed、1 个原有 TLS 跳过；前端 1350 passed；secret、Biome、TypeScript、e2e lint、Tauri fmt/check、ruff、format、mypy 全部通过；四片分别 784, 649, 745, 779 passed，全部退出 0。日志 TESTREADY-complete-static.log、TESTREADY-complete-shard-0..3.log 保存在工作区 outputs/remediation-20260912；专项计数有重叠，不与完整门累加。

证据层级：AUTOMATED_VERIFIED（本地）；PR、当前 SHA 远程三门禁与正常 squash 合并尚待完成。

安全与可观测性：仅使用合成账号及隔离 PG；不改变生产按钮、草稿或接口行为；不记录真实凭据或客户正文。测试数据库使用 tmpfs，默认同步配置保持开启，不据此作生产持久性或容量结论。

迁移与回滚：无迁移；正常 PR revert 可撤销测试与记录变更。

外部授权记录：用户明确授权独立主干 worktree、开发验证、只读子代理评审、PR 和合并。当前未调用真实 Provider、支付、COS 或部署。

未测试项：见第二部分。静态审查另发现上游快照可能覆盖短时编辑、恢复任务晚响应覆盖手动稿、显式保存后再次落草稿三项产品竞态，单独记录在工作区 F06产品竞态-独立只读发现.md，归第一部分后续与 W10/账号任务去重处理。本任务不宣称这些产品问题已解决；保存清除测试仅验证原有即时清除契约。

Lore 提交 SHA：不适用；代码 fc58211、主干整合 a44672a；PR 和 squash 结果在执行记录后续登记。

## 第二部分：人工联合调试

真实浏览器编辑/刷新/重登录、供应商长任务响应、跨设备与部署环境的人工联合调试均未执行，由用户团队按第二部分清单完成。
