# ADMIN-BUNDLE-CSS-CONTRACT-20260912 证据

> 维护任务（非 CW 编号）：verify_customer_bundle.mjs 增加"管理制品必须包含基础样式表"产物级包含向断言（用户确认清单 C1）。
> 基线 `origin/main@2be7c3d`；分支 `chore/admin-bundle-css-contract-20260912`。

## 1. 背景与目标

ADMIN-UI-AUDIT-20260911（PR #49）修复的 P0（管理端产物缺失整份 `styles.css` 基础样式表）之所以能漏网：现有产物合同只有**排除向**断言（客户制品不含管理代码），没有**包含向**断言（管理制品含自身基础依赖）。本任务把包含向补进产物层，与源码级契约（`client/src/entryContract.test.ts`，#49 已加）构成双向完整覆盖。

## 2. 实现

- `scripts/verify_customer_bundle.mjs`：
  - 新增 `ADMIN_BASE_STYLESHEET_NEEDLES = [".admin-shell{", "--admin-bg"]`——两个在 CSS 压缩后仍字面存活的最小标记（壳层选择器 + 令牌定义）；
  - 新增 `runAdminBaseStylesheetControl()`：扫描 `client/dist-admin/**/*.css`，任一标记 0 命中即 `exit 1`，并给出指向 `admin-main.tsx` styles 导入与源码级契约的处理提示；
  - 主流程在阳性对照之后、排除断言之前调用（最严重的现场回归最早失败）；
  - 头部合同说明补第 6 条。
- `server/tests/test_build_contracts.py`：新增静态契约 `test_verify_customer_bundle_asserts_admin_base_stylesheet_marker`，钉住函数存在、两个标记字面量、且调用点在主流程排除断言之前（防"定义了但没接线"静默失效）。

## 3. 先红后绿与产物级验证

- **RED**：`test_verify_customer_bundle_asserts_admin_base_stylesheet_marker` 首跑 `1 failed`（脚本无 `runAdminBaseStylesheetControl`）。
- **GREEN**：实现后 `tests/test_build_contracts.py` **8 passed**。期间一处测试锚点修正：排序断言原用 `checkForbiddenFileNames(relPaths)` 首个命中落在函数定义处（char 7267 < 调用点），改为主流程唯一调用形态 `const nameHits = ...`。
- **产物级负向验证（关键证据）**：在基线 2be7c3d（**尚未含 #49 修复**）上 `npm run build:all` 后实跑脚本，新断言当场失败并精确报出：
  `".admin-shell{" 在 client/dist-admin/**/*.css 中 0 命中` / `"--admin-bg" … 0 命中`——既证明断言有效（阳性对照意义上的"自证"），也再次实证 P0 回归确实存在于当时的 main。
- **产物级正向验证**：待 PR #49 合入 main 后 rebase 本分支，在含修复的树上重新 `build:all` + 实跑脚本全绿，再转正式评审（见 §5）。

## 4. 边界

- 不改 `ci.yml` 工作流结构（verify 步骤保持 `desktop` 门控）；不触碰 client 源码与 server 生产代码。
- 合并顺序依赖：**必须晚于 PR #49 合并**，否则任何触发 build+verify 的 PR 都会在缺修复的树上正确地红（这是断言在正确工作，但会让本 PR 的 CI 无法全绿）。

## 5. 验证命令

| 检查 | 结果 |
| --- | --- |
| `uv run python -m pytest tests/test_build_contracts.py -q`（实现前） | 1 failed / 7 passed（RED） |
| 同上（实现后） | **8 passed**（GREEN） |
| `node --check scripts/verify_customer_bundle.mjs` | 语法通过 |
| 基线树上 `build:all` + `node scripts/verify_customer_bundle.mjs` | ❌ 按预期失败（负向验证，见 §3） |
| 含 #49 的树上重建 + 实跑 | 待 rebase 后补登 |
| `node --check` + secret 扫描 | 随 PR CI |
