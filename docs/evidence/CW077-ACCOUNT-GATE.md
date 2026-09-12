# CW-077 账号登录门禁与注册页面

## 授权与范围

2026-09-12 用户选定左右分栏黑金设计，要求客户密码不少于 6 位；软件可直接打开，进入业务操作页面需要登录，无账号可注册；统一使用项目正式众墅之家 Logo。该明确新指令替代此前 CW-002 不开放游客入口、客户密码至少 12 位的相关范围。游客只访问公开入口，不能读取客户数据或提交业务请求。

基线：origin/main@89d0ba4（CW-076 注册端点已合并）。Owner：本任务 Codex；Reviewer：待 PR 评审。独立分支：feat/customer-v3-cw077-account-login-gate。

## 文件与接口冻结

- 前端新增：client/src/customer/AccountAccessPage.tsx、AccountAccessPage.test.tsx、account-access.css、CustomerWelcomePage.tsx；复用 CustomerAccessBrand 和真实 StudioWorkspace，不用 reviewData 作为游客业务数据。
- 前端修改：RootApp.tsx 及测试、customer/useCustomerSession.ts 及测试、api.ts、CustomerWorkspace.tsx；必要导航及正式 Logo 共用组件。
- 服务端：customer_auth_routes.py 注册/密码登录，password_hashing.py 最低 6 位；customer_auth.py、customer_device_service.py、customer_session_service.py、customer_session_routes.py 支持不依赖激活码的合法注册客户会话。
- 数据库：新增 20260912T1900_password_customer_sessions，接在 20260912T1400_customer_registration_credentials 之后；只允许设备/会话/事件的 activation_code_id 为空，保留用户/设备外键、每设备独立 epoch、租约与审计约束；下迁前拒绝已有无激活码会话数据。
- 验证：现有 test_customer_registration.py 增加六位密码、登录、真实 PG 写门禁、停用、退出、会话切换及幂等；迁移 manifest 与受支持 head 矩阵同步。

## 验收目标

公开首页 → 业务入口 → 账号登录 → 无账号注册 → 注册成功自动登录 → 返回主界面。直接业务深链接同样经过门禁；退出/过期后不可操作。密码只在注册或登录请求中传输，使用 scrypt 哈希，浏览器不持久化密码，设备凭据继续使用既有存储机制。后台管理员密码策略不改。

## 当前状态

实施中；尚未声明验证、PR 或上线完成。独立测试资源：前端 5181、API 18081、PG 5547 / vs-pg-cw077。未使用真实付费 Provider、支付、生产 COS 或生产数据库。

## 后续用户决议

本记录保留原开工来源，当前开发已迁入从 main@55220f7 创建的 UC-BATCH-01。最新权威增量见 [批次记录](UC-BATCH01-ACCOUNT-ACCESS.md)：不限制设备数量，允许多台设备同时在线，登录成功始终返回主界面。管理员设备审计兼容无激活码账号，个人中心前端与后端必须完整联调后一起交付。
