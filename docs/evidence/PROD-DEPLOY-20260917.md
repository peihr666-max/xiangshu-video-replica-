# PROD-DEPLOY-20260917 生产部署证据

状态：现有生产环境版本升级完成；完整业务生产验收等级不变。

用户于 2026-09-17 明确授权通过已打开的宝塔服务器终端部署服务端并切换生产环境。

- 发布基线：`origin/main@80fee758da1632d86dfaaad566c3ac3fa9290f8a`。
- 主线 CI：[35185566959](https://github.com/peihr666-max/xiangshu-video-replica-/actions/runs/35185566959)，Secret scan、Linux quality gate、Windows Tauri and NSIS 全部成功。
- 开工查重：远程开放 PR 仅 #137 桌面安装包；未发现本次部署任务占用。独立分支 `chore/production-deploy-20260917`、独立 worktree 和同仓共享 claim 已建立。
- 部署前版本：`e57e1d81f5f1e07461de21ebcb66840d6901f7ec`，现网配置已经启用 `VIDEO_REPLICA_CUSTOMER_PRODUCTION=true`。
- 现网入口：`https://video.zszhj.cn`；部署前 `/health` 返回正常、`/admin/` HTTP 200，TLS 校验通过。
- 升级差额：后端代码和客户/管理页面更新；无新增 migration、Python 依赖或生产环境变量。
- 发布路径：现有 Compose 拓扑和 `deploy/customer-git-rollout.sh`；保留数据库、配置、备份、原镜像，滚动更新双 API 与六个 Worker。
- 网络处理：服务器直连 GitHub 未完成，使用已在本地独立克隆验证的完整 Git bundle，经宝塔上传，服务器 SHA256 校验通过。源码完整 Git 对象保留，采用 sparse checkout 仅展开部署所需目录；本次上传中转包在校验、克隆完成后删除。
- 发布包 SHA256：`cd47826771a831602f99392c563c8fd142b6b76f81c1d645525d0a68a0de0231`。
- 空间处理：只清理两份旧 release 及本次构建完成后可由锁文件重建的 node_modules；不清理数据库、备份、用户文件或回滚镜像。

## 现场结果

- 发布时间标识：`20260917-054547`（UTC），生产脚本状态 `SUCCESS`，外层退出码 `0`。
- 新镜像：`video-replica-rehearsal-app:80fee75-git`；旧镜像 `video-replica-rehearsal-app:e57e1d8-git` 保留。镜像历史命名含 rehearsal，不代表运行环境；实际生产开关为 true。
- 源码树：`e9c6e7b90548ddacae4a267cc3880fee9746b7c9`。
- 数据库迁移 head 前后均为 `20260917T1000_publish_records`；应用 DSN 的 `sslmode=verify-full`。
- `api-1`、`api-2`、`worker-1..4`、`worker-viral-1`、`worker-publish-1` 共八个应用容器 revision 均等于完整发布 SHA，状态 running，现场重启计数均为 0。
- 双 API 经宿主 `18001` / `18002` 端口逐一通过 `/ready`，HTTP 200，返回 `database=postgresql`、`storage=cos`。
- 默认容器 loopback 探针返回 `UNTRUSTED_PROXY`：现网仅信任既有 Docker 网关 `172.31.100.1/32`。改用实际已授权代理链检查后通过，未扩大白名单，也未关闭校验。
- 公网 `/health`、`/live`、`/customer`、`/admin/` 均 HTTP 200；客户和管理 JS/CSS 均 HTTP 200、Content-Type 正确，TLS 正常校验。
- 客户 JS：`assets/index-DbF0fPqR.js`；CSS：`assets/index-DSCjDw7C.css`。
- 管理 JS：`assets/admin-Bn4JYszX.js`；CSS：`assets/admin-BI4gRw6w.css`。管理代码无本次差异，构建指纹保持一致是预期结果。
- 未登录管理 API `/api/control/customer-sessions/live` 返回 401；生产管理登录页实机浏览器加载正常，无观测到的浏览器 error/warn。
- 已打开生产管理入口，未修改管理员密码、未签发激活码、未执行付费生成或支付交易。

## 服务器证据与回退

- 完整发布日志：`/opt/video-replica-candidate/prod-80fee758-rollout.log`。
- 退出码文件：`/opt/video-replica-candidate/prod-80fee758-rollout.exit`。
- 发布状态：`/opt/video-replica-candidate/deploy-git-80fee75-20260917-054547.status`。
- 备份目录：`/opt/video-replica-candidate/backups/git-80fee75-20260917-054547/`。
- 数据库备份 `database-before.dump` 已通过 pg_restore 目录读取；它与客户站点、管理站点归档均通过 `BACKUP-SHA256SUMS` 复核。
- 原 Compose、原镜像覆盖配置、数据库和静态站点备份全部保留。迁移 head 未变；如需回退，恢复备份中的镜像覆盖和两份静态站点，再逐服务检查就绪；不得用旧数据库覆盖上线后业务数据。
- 本次仅新增部署证据和账本记录，无业务源码、生产密钥或 CI 修改。文档回退为正常 git revert，不影响现网版本。

## 验证边界

本次是现有生产环境的版本升级。部署验证不等于已完成全部客户 UAT、真实支付/Provider 调用、PG HA、PITR 演练或整体 PRODUCTION_GO；这些状态不由一次部署自动核销。

磁盘构建缓存清理后约 4.2 GiB 可用、使用率约 89%；未删除历史备份或旧镜像。部署前的 maintenance service 故障已按下节修复并独立复验。

## 既有维护定时任务修复

部署前现场已有 `video-replica-maintenance.service` 失败，日志为 `ModuleNotFoundError: No module named scripts`。旧单元直接使用 Compose 默认镜像，既未加载本次镜像覆盖文件，也未提供已从客户镜像排除的维护脚本。

- 从本次已通过 CI 的精确源码复制四个既有脚本：`purge_idempotency_envelopes.py`、`purge_expired_export_ciphertexts.py`、`purge_stale_rate_limit_counters.py`、`reconcile_dangling_billing_reservations.py`；逐文件 cmp 一致，无源码改写。
- 脚本仅部署到 `/opt/video-replica-candidate/maintenance-tools-80fee75/scripts/`，在一次性维护容器中只读挂载；未将 SQLite 历史迁移或备份工具加入客户镜像。
- 四项 `--dry-run` 均成功：过期幂等 envelope 12，过期导出密文 0，过期限流计数 27，终态待核对账务 0。随后按既有定时维护策略恢复执行。
- 原服务配置备份到发布备份目录的 `maintenance-service-before.service`。新增宿主 drop-in：`/etc/systemd/system/video-replica-maintenance.service.d/90-release-80fee75.conf`。
- drop-in 保留原安全与重试设置，仅重置四条 ExecStart：Compose 显式加载 `/etc/video-replica/compose.env`、既有 `compose.yaml` 及 `app-image.override.json`；`run --rm --no-deps`，挂载上述四脚本目录到 `/opt/video-replica/server/scripts:ro`，使用镜像的 `/opt/video-replica/server/.venv/bin/python -m scripts.<name>`。
- `systemd-analyze verify` 退出 0，仅提示其他既有主机单元的兼容警告；daemon-reload 后维护正式执行成功，`Result=success`、`ExecMainStatus=0`，oneshot 完成后 inactive 为正常状态；原 timer active；下次调度为 2026-09-18 04:19:23 CST。实际清理过期 envelope 12、导出密文 0、过期限流计数 25；终态账务 scanned/settled/released/failed 均为 0。限流计数在只读演练与正式执行间由正常请求更新，因此实际值与候选数不同。
- 后续发布须将此四个维护脚本与目标应用版本一并核对更新；回退本次宿主配置时移除本次新增 drop-in 并 daemon-reload，原服务文件未改写。日常维护已完成的正常过期清理不会因配置回退逆转，禁止为回退该配置而恢复旧数据库。

## 用户现场管理员登录反馈

用户随后反馈管理员登录失败。已观察到生产页面“管理员账号或密码错误”，两实例登录接口均返回 401；服务、数据库与页面正常。只读核对现有两个管理员均启用且已设置密码，密码校验器自检和存储格式检查通过，本次版本差异未改管理员认证代码或密码表。当前尚未取得用户本次使用的账号来源/名称，不能判定具体不匹配原因，也未验证实际账号登录成功；不得用页面加载或校验器自检替代登录验收。未输出密码/摘要，未重置密码或修改账号。
