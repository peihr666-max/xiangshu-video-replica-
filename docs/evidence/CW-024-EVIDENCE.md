# CW-024 证据记录 — 补齐安全升级和唯一签名发布流程

> 证据层级：`AUTOMATED_VERIFIED`。真实签名实机验收归 CW-046；真实存量旧数据切换归 CW-051。本文件不声明实机升级、签名发布或数据迁移已完成。

```text
任务/工作包：CW-024 补齐安全升级和唯一签名发布流程（W3·代码与测试增量；发布负责人）
Owner / Reviewer：ZCode agent（GLM-5.3-Flash，host PC-202609071434）/ Reviewer 待 PR 分配（合并授权归用户）
分支 / 基线 SHA：feat/customer-v3-cw024-signed-release-secure-upgrade / origin/main@ca438b9（＝CW-023 PR #25 squash 后）
上游规格段落：outputs/customer-cloud-convergence-analysis-2026-09-08/v3/客户版收敛剩余任务清单与验收完工标准-V3.md §CW-024；
  docs/客户云版开发顺序排班与Worktree协作清单.md §2 序 7；承接 CW-011 安装升级合同、CW-003 支持版本冻结、CW-021 卸载钩子与 CI 归档复用项
改动文件：改 client/src-tauri/customer-installer-hooks.nsh、.github/workflows/ci.yml、package.json、
  docs/客户版任务清单-V3.md、docs/CUSTOMER-TASK-EVIDENCE-V3.md、docs/客户版代码开发清单-V3.md；
  新增 server/tests/test_cw024_signed_release_upgrade_contracts.py、scripts/release/build-customer-signed-release.ps1、
  docs/客户版桌面升级与签名发布手册.md、docs/evidence/CW-024-EVIDENCE.md（均先登记后创建，见代码开发清单 CW-024 节）
失败测试或回归锁定：见下「先红后绿」
实现结果：见下「三项差额」
验证命令与通过数：见下「验证记录」
证据层级：AUTOMATED_VERIFIED
安全与可观测性：签名材料（证书 thumbprint/私钥）永不入库、不入 CI、不入 PR（release 脚本仅经环境变量与临时 overlay
  接收，构建后即删）；CI workflow 合同断言零签名材料；备份清单 LEGACY-BACKUP-MANIFEST.txt 与发布清单
  release-manifest.json 提供升级/发行可追溯记录
迁移与回滚：升级回滚矩阵成文于 docs/客户版桌面升级与签名发布手册.md §3/§4；hook 五步失败分支全部 Abort 且
  备份先于卸载产生；未取得用户授权前不执行任何真实对外发布（§15 授权动作）
外部授权记录：无（本任务未触发真实签名/发布/生产变更；Windows 代码签名证书采购为 §16 人工待办，归 DESK-04/CW-046 输入）
未测试项：真实 NSIS 编译（本机无 makensis，以 CI windows-nsis 门承载）；真实 Authenticode 签名构建与
  Get-AuthenticodeSignature 判定（无证书，脚本 fail-closed 路径经合同断言覆盖）；实机升级/卸载/恢复
  （隔离测试机演练与实机矩阵归 CW-046）；cargo test/npm audit/客户浏览器 E2E 以 CI 三门禁为准
Lore 提交 SHA：见本 PR head
```

## 1. 开工检查与认领

2026-09-11 `git fetch origin --prune`，origin/main `ca438b9`。五项检查：§18 CW-024 行 `[ ] 待实施与验收`；`.git/codex-task-claims/` 无 CW-024 目录；本地/远程无 cw024 分支、无同名 worktree；开放 PR 仅 #27（CW-060）/ #28（CW-028）/ #26（COORD-STATUS），与本任务无交集。前置核验（均入 main）：CW-021=PR #21（f193fa7）、CW-022=PR #22（1ad1f31）、CW-023=PR #25、CW-003 决策已签认（2026-09-09，支持版本 0.1.12/0.1.13/0.1.15/0.1.16 + 凭据命名空间冻结）、CW-005 框架已签认（实际批次盘点为 GA 触发，非代码前置）。原子认领 `.git/codex-task-claims/CW-024/`（PowerShell `New-Item` 无 -Force），worktree `E:/众墅之家爆款短视频创作/.worktrees/CW-024-signed-release-secure-upgrade` 从 origin/main ca438b9 创建。

## 2. 复用现有 / 剔除重复开发（按规格逐条）

- **复用**：CW-021 交付的客户 NSIS hook 失败阻断语义（ExecWait 同步卸载 + 退出码/执行错误即 Abort）、CI 无签名客户包构建 + 启动器/本地后端排除检测 + SHA 归档（`LOCAL_ARTIFACT_ROOT`/`SHA256SUMS.txt`）、CW-022 的凭据命名空间冻结事实。本任务**未**从零重建 hook、未重建卸载失败阻断、未重建基础 SHA/包归档。
- **剔除**：tauri updater 自动更新（CW-003 冻结口径为无 updater 的手动安装升级）、Windows 证书采购与实机签名（§16 人工待办 + CW-046）、真实旧数据迁移（CW-051）。

## 3. 仅做剩余：三项差额的实现

### 3.1 差额一：旧安装路径全覆盖 + 数据保护前置（hook 重写）

规格指出的缺口：原 hook「在单一固定路径自动卸载且没有归档/迁移证明前置」。两条旧安装路径的史实依据（写入合同测试 docstring 与运行手册 §2）：

| 代次 | 版本 | 证据提交 | productName | NSIS installMode | 安装目录 |
| --- | --- | --- | --- | --- | --- |
| 生成 1 | 0.1.12/0.1.13/0.1.15/0.1.16(#92) | 81f153a、d9a5576、bc0248e、80a8e40、59e10ed | 短视频复刻工作台 | currentUser | `$LOCALAPPDATA\短视频复刻工作台` |
| 生成 2 | 0.1.16（品牌替换版） | 1fb997a（2026-09-05 W1） | 众墅之家 | currentUser | `$LOCALAPPDATA\众墅之家` |

`customer-installer-hooks.nsh` 对每条路径独立执行：①存在检测；②运行实例守卫——写模式 `FileOpen` 旧版 `uninstall.exe`（Windows 锁定运行中可执行映像，写打开失败即运行中/被占用）→ 弹窗 Abort，**零改动**；③`CopyFiles /SILENT` 整目录归档到 `$LOCALAPPDATA\短视频复刻客户云工作台\legacy-backup\<旧版名>\`；④`IfFileExists` 校验备份内 `uninstall.exe` 存在 + 写 `LEGACY-BACKUP-MANIFEST.txt`（旧版标识/来源路径/覆盖版本/归档者）；⑤前四步全部通过才 `ExecWait '"…\uninstall.exe" /S'` + 退出码校验；归档/校验/写清单/卸载任一失败均 Abort 且提示备份位置（失败可恢复旧客户或保留可读数据）。备份根目录位于客户 app data 树内（与安装同卷）。凭据保护：CW-003 冻结的 DPAPI 信封与注册表镜像（`Software\Xiangshu\VideoReplicaCustomer`）均在安装目录之外，hook 合同断言 `$APPDATA`/`HKCU\Software`/`com.internal.video-replica` 零出现——hook 只动 `$LOCALAPPDATA` 下旧安装目录本身。

### 3.2 差额二：唯一签名发布流程（fail-closed）

新增 `scripts/release/build-customer-signed-release.ps1`（`package.json` `release:customer` 入口）：缺 `VIDEO_REPLICA_RELEASE_SIGN_THUMBPRINT` 或 `VITE_API_BASE_URL` 直接 throw；六处版本一致性门（tauri.conf.json / package.json / client/package.json / package-lock.json 根与 packages.client / Cargo.toml [package] / pyproject.toml [project]）；签名输入仅经 BOM-free 临时 overlay 注入 `certificateThumbprint`/`digestAlgorithm='sha256'`/`timestampUrl`（`[System.IO.File]::WriteAllText`，构建后 finally 删除，不入库不入 CI）；`require:customer-api-base` 先行校验 origin 可路由非回环；构建后 `Get-AuthenticodeSignature` 状态必须 `Valid`（可选 `VIDEO_REPLICA_RELEASE_EXPECTED_SIGNER` 主体包含校验）否则中止且**不产出未签名发行物**；产出 `dist-release/customer-cloud/<版本>/`：安装包 + `SHA256SUMS.txt` + `release-manifest.json`（`channel='signed-release'`、`version`、`platform='windows-x86_64'`、`artifact`、`sha256`、`signature{status/subject/thumbprint/timestampUrl}`、`generatedAt`）——满足「唯一客户制品含版本、平台、签名和 SHA 记录」。PowerShell 5.1 语法经 `PSParser::Tokenize` 本地解析零错误。

### 3.3 差额三：未签名包只能标内部测试

`.github/workflows/ci.yml` 归档步骤：目录 `${{ github.sha }}\customer-cloud` → `customer-cloud-internal-test-unsigned`，并写 `RELEASE-CHANNEL.txt`（值 `internal-test-unsigned`）。合同断言 workflow 内 `TAURI_SIGNING_PRIVATE_KEY`/`certificateThumbprint`/`signtool` 零出现（CI 永不持有签名材料），`package.json tauri:build` 保持 `--no-sign`（CI 制品天生无签名）。`server/tests/test_build_contracts.py` 全部计数断言（`LOCAL_ARTIFACT_ROOT`=4、`SHA256SUMS.txt`=1、归档 step 名、5 job fork guard、pin 哈希计数等）零破坏——**本任务未改动该守卫文件**。

## 4. 先红后绿（合同测试）

新增 `server/tests/test_cw024_signed_release_upgrade_contracts.py`，9 用例纯静态断言（无 PG 依赖，文件级合同）：

| # | 用例 | 锁定内容 |
| --- | --- | --- |
| 1 | test_hook_covers_every_supported_legacy_install_path | 两条旧路径的存在检测 + 静默卸载 |
| 2 | test_hook_uninstall_is_gated_on_running_guard_and_verified_archive | 存在检测→运行守卫→归档→校验→清单→卸载的顺序合同 |
| 3 | test_hook_fails_closed_on_every_step | 运行/归档/卸载失败分支 + Abort + 恢复提示 |
| 4 | test_hook_preserves_frozen_credential_namespaces | 凭据命名空间零触碰（RED 期即为绿：现状本就不触碰） |
| 5 | test_ci_unsigned_artifacts_are_labeled_internal_test_only | CI 渠道标注 + 零签名材料 + --no-sign |
| 6 | test_signed_release_flow_exists_and_fails_closed | 发布脚本 fail-closed 门 + 签名校验 + manifest 字段 |
| 7 | test_signed_release_flow_is_the_only_release_entrypoint | release:customer 唯一入口 + 手册含可执行命令 |
| 8 | test_upgrade_and_recovery_runbook_is_registered_and_executable | 手册矩阵/回滚/凭据/边界/标注成文 |
| 9 | test_cw024_files_are_registered_in_the_frozen_file_map | 新文件先登记后创建 |

- **RED**（实现前，树＝ca438b9+测试文件）：`8 failed, 1 passed in 0.08s`，失败项＝#1/2/3/5/6/7/8/9，通过项＝#4（凭据命名空间，现状本就不触碰）。
- **GREEN**（实现后）：`23 passed`（本文件 9 + test_build_contracts 12 + test_desktop_artifact_no_pg_dsn 2? 见 §5 验证记录实际命令与计数）。
- 既有合同保持：`test_customer_ha_smoke.py::test_customer_desktop_build_is_the_sole_default_target`（CW-021 hook 字符串合同：`$LOCALAPPDATA\短视频复刻工作台\uninstall.exe`、`ExecWait '"$LOCALAPPDATA\短视频复刻工作台\uninstall.exe" /S'`、`IfErrors legacy_internal_failed`、`IntCmp $0 0 legacy_internal_done`、`Abort`）1 passed——hook 重写保留全部既有字面量。

## 5. 验证记录（本地，host PC-202609071434，2026-09-11）

| 门 | 命令 | 结果 |
| --- | --- | --- |
| 合同专项（RED） | `uv run --project server --locked python -m pytest server/tests/test_cw024_signed_release_upgrade_contracts.py -v` | 8 failed / 1 passed（预期红） |
| 合同专项（GREEN） | 同上 + test_build_contracts.py + test_desktop_artifact_no_pg_dsn.py | 23 passed |
| 既有 hook 合同 | `pytest test_customer_ha_smoke.py::test_customer_desktop_build_is_the_sole_default_target` | 1 passed |
| Lint/类型 | `ruff check server` / `ruff format --check server` / `mypy --config-file server/pyproject.toml server/app` | All checks passed / 303 formatted（1 文件为本任务测试文件 reformat）/ Success: no issues in 104 source files |
| 秘密扫描 | `bash scripts/verify_no_secrets.sh` | EXIT=0 |
| ci.yml 语法 | pyyaml safe_load | YAML-OK |
| 发布脚本语法 | `PSParser::Tokenize` | 零语法错误 |
| client 段 | `npm run check --workspace client`（biome + tsc + vitest） | 80 文件 1296 passed |
| check:e2e 段 | `npm run check:e2e`（biome e2e） | EXIT=0 |
| check:tauri 段 | cargo fmt/check | 本机无 Rust 工具链，以 CI 三门禁为准 |
| 收尾全量 pytest | `pg-fixture.sh start`（隔离容器 customer-v3-pg-test@5433）+ server 目录顺序全量 | 34m24s：**2392 passed / 2 skipped / 31 failed / 38 errors**，归因见 §6 |

## 6. 收尾全量门禁归因（基线对照）

对照 2026-09-11 已登记的 Windows 环境类基线（28F/2319P/2S/38E）：

| 组 | 数量 | 归因 | 与基线关系 |
| --- | --- | --- | --- |
| test_cw033_pitr_drill_validation | 22 failed | pitr drill `.sh` 子进程 Windows `WinError 2`（环境类） | 与基线逐一相同 |
| test_simple_character | 6 failed | 缺 ffmpeg（环境类） | 与基线逐一相同 |
| test_oral_domain | 38 errors | setup `MediaToolUnavailable`（缺 ffmpeg，环境类） | 与基线逐一相同 |
| **test_storage_cross_instance** | **3 failed** | `test_local_object_endpoints_*`/`test_local_object_put_*` 期待 503 `STORAGE_PROVIDER_FORBIDDEN`，实得 401 `SESSION_TOKEN_REQUIRED`——CW-031 的 local-object 用例以 `X-Dev-User-Id` 访问端点，而 CW-026（#20）已把内部身份旁路移出收敛 PG 通道。**main 侧既有问题，非本任务造成**：本任务对 `server/` 的 diff 仅新增合同测试文件（+226 行，零运行时触碰），且在干净 `ca438b9` scratch worktree 复跑同文件得**完全相同的 3 failed / 24 passed**。按 CW-055/057 flake 归因先例登记，不越界修复（属 CW-031/CW-026 任务域），交集成人决断 | 基线外新增，已举证非本任务回归 |
| 其余 | 2392 passed / 2 skipped | 含本任务 9 个合同用例 | 通过数较基线 +73（并入 CW-026/027/029 等新增用例） |

全量绿最终判定权归 CI；本机不追 ffmpeg/`.sh` 环境类与 main 侧既有项的绿。

## 7. 未测试项与上游边界（如实登记）

- 本机无 makensis：hook 的真实 NSIS 编译由 CI windows-nsis 门承载（该门以 `npm run tauri:build:customer` 编译含本 hook 的安装包，语法错误会使门失败）。
- 无签名证书：release 脚本的签名成功路径未真跑；fail-closed 分支（缺 thumbprint/缺 origin/签名无效）由合同断言覆盖。证书采购为 §16 人工待办（DESK-04）。
- 实机升级/卸载/恢复演练（「本任务先在隔离测试机演练」的实机部分）与签名安装/升级/重装/失败恢复实机矩阵归 **CW-046**（配合 CW-003 兼容矩阵与 CW-022 凭据路径）。
- 真实存量旧数据切换归 **CW-051**；切换完成前 `legacy-backup` 目录必须保留（运行手册 §7）。
- `cargo test`/`npm audit`/客户浏览器 E2E 以 CI 三门禁为准。
