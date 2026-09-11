# ADMIN-LOGIN-POLISH-20260912 证据

> 维护任务（非 CW 编号）：管理端登录门打磨（用户确认清单 B3）+ 会话绑定文案与 B1·方案② 同步。
> 基线 `origin/main@7190f2e`（含 #49 登录门重构）；分支 `chore/admin-login-polish-20260912`。
> 前置依赖 #49 已满足；与 #53（B1）为文案语义配套、无代码依赖。

## 1. 变更

1. **恢复凭据输入打磨（B3）**：
   - 输入框下新增常驻格式提示「凭据以 ASX1. 开头。」；
   - 粘贴/输入含首尾空白的内容时，动态显示「已自动忽略首尾空白。」反馈（`recoveryTrimmed` 状态，提交时既有 `.trim()` 行为不变）；会话过期与凭据验证成功后反馈复位。
2. **会话绑定文案同步（配套 #53 方案②）**：
   - 错误映射 `ADMIN_SESSION_CONTEXT_CHANGED` →「检测到浏览器环境变化，请重新登录。」（去掉"网络"语义，与 #53 后端行为一致）；
   - 登录页品牌区安全要点 →「会话绑定当前浏览器环境，更换浏览器后需重新登录」。

## 2. 先红后绿

- **RED**：文案断言用例（改后文本）与新增「恢复凭据表单提供格式提示并对粘贴空白给出忽略反馈」用例首跑 **2 failed / 22 passed**。
- **GREEN**：实现后 `AdminApp.test.tsx` 24 passed；客户端全量 `npm run check`（biome + tsc -b + vitest）**80 文件 1302 passed**（7190f2e 基线 1301 + 新增 1，零回归）。

## 3. 边界与未测试项

- 仅碰 `client/src/AdminApp.tsx`、`client/src/AdminApp.test.tsx`、docs/**；服务端与 `api.admin.ts` 全局映射零改动。
- 文案语义与 #53 的时序：若 #53 未先合，管理员触发 UA 变化时看到的仍是中文提示（文本与后端行为稍有措辞差，无功能影响）；两 PR 均合后完全一致。
- `cargo test` / `npm audit` / 浏览器 E2E / Windows NSIS 以 CI 为准；回退 = 单提交 revert。
