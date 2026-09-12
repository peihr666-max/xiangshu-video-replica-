# CW040-EVIDENCE — CW-040 pre-GA：内部发行/专属运维入口 fail-closed（2026-09-12）

> 任务：CW-040（pre-GA 范围按 owner 决策 `docs/evidence/COORD-W6-UNBLOCK-20260912.md` D2 / CW-001 §6 P1 落地）。
> 分支 `feat/customer-v3-w6-unblock`（W6 统一批次），基线 `origin/main@55220f7`。
> 本任务**零生产码改动**；交付为发行/运维面入口 fail-closed 契约测试 + 证据。物理删除（`packaging_tools/`、`deploy/internal-p0.*`、`deploy/nginx/internal-p0.conf.example`、`deploy/systemd/video-replica-backup.{service,timer}`、`scripts/p0_acceptance_evidence.py`）归 GA 后清理批次（退役条件不变：内部停写 CW-051 后归档）。

## 1. 入口面现状核验（`git grep` + 逐文件实测，2026-09-12 @55220f7）

| 内部制品 | 客户面可达性实测 | 结论 |
| --- | --- | --- |
| `packaging_tools/`（10 文件，完整内部发行工具链） | `ci.yml` 仅 L65 paths-filter（desktop 触发器）提及；root/client `package.json`、`scripts/release/build-customer-signed-release.ps1`（唯一签名发布通道）、`deploy/customer/**` 零引用 | 无执行入口，保留待清理 |
| `scripts/p0_acceptance_evidence.py`（内部 P0 遗留） | 同上全部客户面零引用 | 无执行入口 |
| `deploy/internal-p0.env.example` + `nginx/internal-p0.conf.example` | `deploy/customer/**` 零引用 | 无部署入口 |
| `deploy/systemd/video-replica-backup.{service,timer}` | `deploy/customer/**` 仅 README 的**排除声明**提及（「不属于本包」）；无 systemctl enable/start 接线 | 无部署入口 |
| `app/backup.py` CLI（与上述 systemd 单元配对的历史 SQLite 备份工具） | 客户构建已由 CW-060 rollout `rm -f backup.py` + 镜像实物扫描隔离；**主机上直跑 CLI 此前无生产守卫** → 本批次由 042-a 扼流点闭合 | 进程级 fail-closed（新增） |
| 客户 NSIS 安装包本地后端标记 | `ci.yml` windows-nsis 步骤 forbiddenNames/forbiddenExtensions/binaryMarkers 三重扫描（CW-021/024 交付） | 已闭合，本批次加契约锁防倒退 |

## 2. 本批次新增：`server/tests/test_cw040_internal_release_exit.py`（7 用例，全离线）

1. **`test_nsis_payload_scan_keeps_all_forbidden_markers`**：钉死 `ci.yml` NSIS 三重扫描的完整标记集（forbiddenNames 五项 / 禁止扩展名四项 / binaryMarkers 三项）与两条 throw 文案——防止后续 CI 编辑悄然削弱 CW-021/024 建立的安装包入口封闭（test_build_contracts 同款契约测试模式）。
2. **`test_packaging_tools_is_never_executed_by_ci`**：`ci.yml` 中 `packaging_tools` 只允许以 paths-filter 触发行形态出现；任何执行形态（bash/python/pwsh 调用）即失败。
3. **`test_npm_scripts_have_no_internal_toolchain_references`**：root + client 两个 package.json 对 `packaging_tools`/`p0_acceptance`/`internal-p0` 零引用。
4. **`test_signed_release_channel_has_no_internal_toolchain_references`**：唯一签名发布通道 `build-customer-signed-release.ps1` 对四类内部制品零引用。
5. **`test_customer_deploy_templates_have_no_internal_toolchain_references`**：`deploy/customer/**`（.sh/.md/.example/.service/.timer）对内部制品零功能性引用；systemctl 接线 backup 单元即失败（README 的排除声明不受影响）。
6. **`test_backup_cli_refuses_in_customer_production`**：历史备份 CLI 在客户生产抛 CW-042-a 固定 RuntimeError（真实 argparse 路径，源文件预置以越过 `backup_database` 的存在性检查直达守卫）。
7. **`test_backup_cli_still_serves_the_internal_lane`**：范围守卫——CW-051 内部停写之前，内部 lane 的 backup/restore 全链保持可用（initialize_database → backup 子命令端到端，产物文件存在断言）。

## 3. CI path-filter 联动说明（登记，不在本批次处置）

`packaging_tools/**` 位于 `ci.yml` 的 desktop path-filter 内（盘点 §2.2 观察点）。物理删除该目录时须同步从 filter 移除，否则 desktop 检测永远为 true 浪费 Windows 门资源——已在删除批次（GA 后）处置清单登记，本批次 filter 不动（目录仍在仓库）。

## 4. 验证与诚实边界

- 专项 **7 passed**（契约测试读取真实仓库文件；CLI 用例真实 argparse/sqlite3）。
- 诚实边界：①契约测试锁的是**当前静态引用面**，运行期防御由 042-a 扼流点 + NSIS 构建扫描承担，本任务未重复建设；②内部 systemd 单元的真实停用/归档在目标机执行，归 CW-051 后清理批次；③`packaging_tools` 内部工具链的可用性未验证也不应验证（无消费者，且其退役条件与 CW-051 绑定）。
