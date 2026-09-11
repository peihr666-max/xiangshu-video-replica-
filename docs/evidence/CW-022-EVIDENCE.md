# CW-022 — 复验原生凭据和旧版本设备身份兼容（W3 复验）

## Task Information

| Field | Value |
| --- | --- |
| **Task ID** | CW-022 / W3「复验原生凭据和旧版本设备身份兼容」 |
| **Owner** | 桌面负责人 + 安全复核（ZCode 会话 sess_0d6c74dc，用户授权流水线执行者） |
| **Reviewer** | CodeReview 自检（push 前）+ PR CI 三门禁 + owner 评审 |
| **Branch / Base SHA** | `feat/customer-v3-cw022-credential-identity-compat` / 开工基线 `origin/main@f193fa7382cebcc4`（＝CW-021 #21 squash 合并后） |
| **Worktree** | `E:/众墅之家爆款短视频创作/.worktrees/CW-022-credential-identity-compat-reverify`（claim: `.git/codex-task-claims/CW-022/claim.json`） |
| **Date** | 2026-09-11 |
| **Evidence Level** | `AUTOMATED_VERIFIED`（受支持旧版本签名包实机升级/重装证据由 CW-046 按原任务边界提供） |
| **前置** | CW-020（#18，identifier/app_data_dir 沿用已发命名空间）、CW-003（凭据命名空间冻结：0.1.12/0.1.13/0.1.15/0.1.16） |

复验任务说明：本任务**不新造凭据库**（剔除重做 DPAPI entropy、Keychain
service/account、注册表稳定 ID、原子同步写与相同目录重启 roundtrip——均已存在）。
复验按任务定义执行三件事：①让既有 OS 原生专项真正跑起来；②把命名空间冻结从
"文档约定"升级为"测试钉死"；③补齐损坏/迁移语义的回归锁。

## 复验发现与处置（RED→GREEN 或「无测试→有测试」）

### 1. Windows DPAPI 专项从未在任何 CI 执行（本任务最大发现，已修复）

`cargo test` 只存在于 ci.yml 的 Linux 质量门；`#[cfg(windows)]` 的 4 个 DPAPI
测试（roundtrip/无明文/clear_session/clear_all）在 Linux 上被编译剔除，在
Windows job 上无人执行——即既有证据"DPAPI 7/7"以来，这些测试**没有任何自动化
执行体**。处置：windows-nsis job 在「Check Tauri project (customer default)」
之后新增 `cargo test --manifest-path client/src-tauri/Cargo.toml --locked` 步骤
（crypt32/advapi32 FFI 在 runner 用户会话可执行）。守卫断言
（`test_build_contracts.py` CI 合同）先红（windows 段无 cargo test）后绿。

### 2. 注册表迁移路径（首次升级启动）无测试（已补）

`durable_device_instance_id` 承担"首次升级启动把既有 app-data 标识迁入 HKCU
注册表"的升级兼容语义，此前无任何测试。新增
`the_durable_identity_migrates_the_legacy_id_into_the_registry_once`（唯一触
注册表的测试，避免并行线程竞争）：备份→清空注册表值→验证
legacy id 迁移写入→重启/重装（丢弃 app-data）后仍从注册表取回同一标识（不新增
设备）→恢复测试前状态（`durable_identity::clear()` 为 test-only 助手，
`RegDeleteKeyValueW`，仅 `cargo test` 编译）。

### 3. 损坏信封 fail-closed 语义无回归锁（已补）

- `a_corrupted_envelope_fails_closed_and_keeps_the_device_identity`：截断+乱序
  DPAPI 信封 → `load` 显式 Err（不泄明文、不静默重置登录），稳定设备标识
  （独立文件存储）幸存，且损坏状态持续可见（vault 不静默替换为有效信封）。
- `an_empty_envelope_is_a_visible_error_not_a_login`：空信封 → 显式 Err；重存
  后 device 凭据可恢复且 session 保持 None（与 CW-017 清理矩阵衔接）。

### 4. 命名空间冻结从文档升级为测试（CW-003 §6 落实）

- `the_frozen_credential_file_namespace_is_stable`（跨平台）：
  `customer-credentials.bin` / `device-instance-id` 文件名钉死。
- `the_frozen_windows_identity_namespace_is_stable`（Windows）：
  `Software\Xiangshu\VideoReplicaCustomer` / `DeviceInstanceId` 钉死
  （两常量改 `pub(super)` 以供测试引用）。
- 已发 identifier `com.xiangshu.video-replica.customer` 的钉死由
  `test_customer_desktop_build_is_the_sole_default_target` 承载（CW-020 起即有），
  CW-021 删除本地后端未触碰凭据链路（`customer_credentials.rs` 在 #21 的 diff
  为零改动，本次复验核实）。

## 矩阵登记（自动化 vs 实机边界）

| 场景 | 承载 |
| --- | --- |
| 凭据 roundtrip（重启后可读） | DPAPI roundtrip 测试（新增 CI Windows 执行） |
| 存储无明文/无字段名泄漏 | `the_stored_file_is_never_plaintext`（同上） |
| logout/失效清理（session 清除保留设备凭据；revoked 清空但保留稳定 ID） | `clear_session_keeps_the_device_credential` + `clear_all_removes_the_envelope_entirely` + CW-017 前端清理矩阵（vitest 1296 用例内，见下） |
| 损坏（截断/空信封） | 本任务新增 2 测试 |
| 旧版本升级迁移（app-data 标识→注册表） | 本任务新增迁移测试 + `customer-installer-hooks.nsh` 旧内部版卸载迁移合同（`sole_default` 断言承载） |
| 重装后身份稳定（无 app-data，仅注册表） | 本任务新增迁移测试的 reinstalled 分支 |
| epoch/slot 单调不回退 | 服务端 fencing 契约（CW-009/026 既有服务端套件，随 CI Linux 门禁全量执行，本任务不重复开发） |
| 签名包实机升级/重装/卸载（0.1.12/13/15/16 → 当前） | **CW-046**（原任务边界：实机证据归实机任务；本任务提供其前置的命名空间/迁移自动化证据） |
| macOS Keychain（4 测试） | CW-002 已签认客户桌面仅 Windows 10/11 x64——Keychain 专项登记为超范围保留（测试随平台编译，不在支持矩阵内） |

## 前端衔接复验（无代码变更）

`useCustomerSession.ts` 的 logout/credential-clear 合同（CW-017 实现）由既有
client 套件承载：CW-021 期间本机 vitest 全绿 80 文件 1296 用例（含 customer
session/logout 矩阵）；本任务未改前端，CI Linux 门禁同一套件为准。

## 验证记录

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 守卫专项 | 三守卫文件 pytest | 15 passed（含新增 windows cargo test 契约断言） |
| ruff / secrets | `ruff check server` + `verify_no_secrets.sh` | push 前执行（结果见 PR CI 与提交记录） |
| cargo test（Linux 侧跨平台+fail-closed 测试） | CI Linux 质量门既有步骤 | CI 裁决 |
| cargo test（Windows 侧 DPAPI/注册表专项，本任务新增步骤） | CI windows-nsis job 新步骤 | **CI 裁决（首次真实执行 DPAPI 专项）** |
| 本地 cargo | 不可用（本机无 Rust 工具链，沿 CW-019/020/021 先例） | 以 CI 三门禁为准 |

## 未测试项（诚实披露）

- 本机无 Rust 工具链：新增 Rust 测试的编译与运行全部由 CI 三门禁裁决；若
  Windows DPAPI/注册表步骤在 runner 环境失败（如 DPAPI 用户密钥不可用），按
  CI 失败修复本任务，不以本地推断代替。
- 真实已发版本（0.1.12/13/15/16）安装包的原地升级与卸载重装的实机证据按原
  任务边界归 CW-046；本任务提供命名空间钉死与迁移语义的自动化前置。
- epoch/slot 服务端不变量复用 CW-009/026 既有自动化，本任务未新增服务端用例。

## 回退方式

PR squash 合并前：放弃分支即可。合并后：单提交 revert；新增测试均为增量
（不改既有断言语义），`clear()` 为 test-only 代码，无运行时行为变更、无数据
与迁移不可逆项。
