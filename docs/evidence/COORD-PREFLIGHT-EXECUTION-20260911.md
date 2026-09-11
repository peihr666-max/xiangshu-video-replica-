# 开工准备清单执行记录（2026-09-11）

任务：COORD-PREFLIGHT-EXECUTION-20260911。用户授权：“按照这个顺序执行，如果其他工作区在做，那就先跳过做没有在同步做的工作”。

本次完成占用复查、测试差额定位、044 材料接收、资源冲突核查及 worktree 分类；业务实现与独立验收仍由对应任务负责。基线 main 为 `dfe7711969f70a85a720aa62e93fc17609ce8058`。机器快照与测试函数清单见[JSON证据](COORD-PREFLIGHT-EXECUTION-20260911.json)。这是时点记录，后续开工必须重新 fetch。

## 1. 按原顺序执行的结果

| 顺序 | 本次执行结果 | 剩余动作与归属 |
| --- | --- | --- |
| 1 / CW-061 | 已核对原 worktree、claim、[PR #36](https://github.com/peihr666-max/xiangshu-video-replica-/pull/36)及当前 head 的 CI；已有 Owner，跳过实现和合并 | head `c53cf05` 的 Linux 检查失败在第12步 Run sharded PostgreSQL pytest。原 Owner 修复并完成实际验证；113/113 文件入清单只是静态覆盖，不能据此通过 |
| 2 / CW-059 | 已读取原分支 `6ebc237` 的三个矩阵与证据；claim=REVIEW，工作区 clean，查询时没有开放 PR；已有 Owner，跳过 | 原 Owner 继续提交/评审；33 passed 是其证据自报的专项结果，本次未重跑。该证据把专项与三门禁措辞混用，独立 Reviewer 必须核对实际全量/CI日志，不能把33专项当全仓全量 |
| 3 / 数据处置 | [PR #35](https://github.com/peihr666-max/xiangshu-video-replica-/pull/35)仍开放，head `fef686b`；跳过其文件 | 原 Owner 合入签认后再处理034～038；本次未将未合并内容写成main结论 |
| 4 / 账本同步 | 检出新 `docs/customer-v3-cw014-merged-backfill` 工作区，采集时已有1项修改；跳过正式账本和进度快照写入 | 014原工作区与数据决议PR正在写共享账本。进展报告PR #37刚合入main（`dfe7711`），仅为派生分析；各业务行由既有集成人回填 |
| 5 / 043缺口与承接 | 已定位六组旧测试，共111个test函数，并核对058/030/059对应成果；具体差额见§2 | 043正式复验仍WAITING：059未合入、061失败。已覆盖行为复用；缺口先由领域实现者补齐，之后交独立核销。未创建CW-043实现分支 |
| 6 / 044材料接收 | 已读取原分支 `d9b4cc4` 的CW044-INVENTORY，复用其§10/12/13/14/18，不重复编辑 | 044原Owner继续；本次明确适用前置与pre-GA边界，见§3 |
| 7 / 测试资源 | 已实际查询Docker、监听端口及脚本资源命名；本次不占PG、不启动测试容器 | 检出固定分片名与端口冲突，后续执行顺序见§4；没有通过修改CI规避门禁 |
| 8 / worktree清点 | 已逐个查13个worktree（含本次），核对对应PR、合入main关系、未提交和ignored文件；已归档本会话已合并进展任务的5个缓存文件并校验哈希 | 其余工作区保留。进展任务PR #37的main检查尚在运行，目录暂不删除；详见§5 |

“跳过”表示保留既有执行权，不解除原认领、不重复开同编号分支；不表示任务已验收。

## 2. 043可直接使用的差额交接

### 2.1 已核对的来源与计数口径

| 来源 | 固定版本 | 本次核对内容 |
| --- | --- | --- |
| main代码 | dfe7711 | 素材13、analytics 8、viral import 16、首帧38、源帧19、音频转文案17，共111个test函数 |
| CW-058 | main中的PR #33成果 | 内容/资产矩阵20个test函数；证据§7明确遗留上传路由、analytics/import，首帧/源帧/音频转文案交059 |
| CW-030 | main中的PR #29成果 | Worker矩阵29个test函数，可复用逐类claim/lease/恢复行为 |
| CW-059 | 尚未合入的6ebc237 | 账务12、任务14、RBAC 2个test函数；RBAC参数化展开为7例，原Owner自报专项共33例；没有把函数数量当执行例数 |

本次为AST与源码核对，没有运行上述业务测试。111不是待重写数量，也不是缺失用例数量；每个函数的确切路径、行号、参数化标记已写入JSON。保留业务的持久化不变量需要真实PG替代证据，纯计算单测可保留；历史机制应有精确退休依据，不能整文件一概标为已迁或N/A。

### 2.2 六组差额及处理顺序

下表使用已有函数作为定位锚点；“待补”表示在本次读取的替代矩阵和映射中尚未找到足以核销的证据，须先查既有PG套件再补，避免重复开发。

| 差额组 | 已有成果与定位锚点 | 开工前要交接的剩余差额 | 承接与关闭标准 |
| --- | --- | --- | --- |
| A. 素材上传 | `test_cw058_content_asset_pg_matrix.py::test_materials_pagination_hide_rename_and_audit_on_pg`已覆盖分页/隐藏/重命名/审计；素材上传旧断言位于`test_materials.py::test_upload_audio_to_storage_then_complete_and_list_it`等 | 上传intent→对象上传→complete→列表的路由级PG链路；purpose/时长不一致/内容类型或字节不符/跨用户complete拒绝。media上传矩阵走另一组入口，不能直接代替materials上传 | 内容/资产领域补漏，Owner待正式分配，058原Owner已有证据供复用；对应HTTP结果、持久化与拒绝无副作用在真实PG得到证据后，由043独立核销 |
| B. analytics | 正确旧文件名为`test_studio_analytics.py`；058的`test_studio_task_stats_scope_and_hidden_batch_on_real_pg`覆盖任务统计子集 | 北京日期完整窗口、跨午夜单次时钟、kind breakdown、recent works排序/作用域/20条上限、days边界、路由调用者隔离。锚点：`test_daily_series_covers_full_window_by_beijing_day`、`test_recent_works_cap_at_twenty` | 内容/统计领域补漏；逐组复用或补真实PG断言，不以一个stats用例关闭analytics全矩阵 |
| C. viral import | `test_viral_import.py`有16个函数；058的viral store/分页/收藏/refresh矩阵不能直接覆盖import任务 | 创建项目幂等、Owner变更拒绝、失败重试/终态重放、持久媒体准备去重、哈希不符、partial asset回滚、旧attempt不能发布；锚点`test_completion_rejects_project_owner_change`、`test_stale_attempt_cannot_publish_asset_even_with_same_worker_id` | 内容导入领域补漏；逐条区分保留客户导入行为与旧SQLite worker机制。禁止将普通客户viral导入直接归为历史数据库导入TEST-IMPORT |
| D. 首帧 | CW030的`test_first_frame_expired_with_checkpoint_resumes`、`test_first_frame_stale_lease_failure_is_a_noop`等可复用；059新增`test_pg_first_frame_tasks_status_enum_boundary`是DB枚举证明 | 旧`test_first_frames.py`的路由幂等/访问、输入变化、发布回滚、checkpoint来源、候选确认与版本失效逐组映射；纯提示词/图像计算断言单独归类 | 已交059原Owner；不新开重复任务。059的枚举约束不能代表38个函数的业务全覆盖；043核对映射后再决定真实差额 |
| E. 源帧 | CW030覆盖double-claim、过期人工恢复、worker缺质量配置处理；059新增`test_pg_source_frame_tasks_reject_uncertain_status` | 候选提取与确认、最新候选集限制、重新提取使旧选择失效、DB失败后已上传对象处理等；锚点`test_database_failure_removes_uploaded_candidate_frames`。ffmpeg/时间戳纯计算用例不机械改成PG | 已交059原Owner；行为与DB机制分开核销，保留源帧fail-closed到人工恢复的范围决定 |
| F. 音频转文案 | CW030的`test_script_from_audio_receipt_survives_retry`等覆盖claim/过期/提交隔离/receipt | enqueue/replay/Owner隔离/latest、重启清理持久音频、配置恢复、失败清理逐组映射。旧`test_pg_worker_consumes_audio_outside_transaction`虽名含pg，却在367～368行替换pg_transaction并把BusinessConnection.postgres指向SQLite，不算真实PG执行 | 已交059原Owner。复用真正PG的CW030矩阵；未覆盖的客户持久化与恢复行为补证据，不能按测试函数名认定PG |

A/B/C的补漏不在本次认领范围内；D/E/F已有059负责，按用户要求跳过。043保持独立复验，不能一边补实现一边把自己的实现核销通过。

### 2.3 分片与评审交接

- main：112个测试源文件，已提交清单99个，缺13个；无重复/失效条目。完整缺失列表保存在JSON。
- 061分支：113个源文件与113个清单条目对应，但[实际Linux执行失败](https://github.com/peihr666-max/xiangshu-video-replica-/actions/runs/34570087198/job/103170200044)。本次只确认失败步骤，没有在缺少日志时猜测失败根因。
- 059另新增3个测试文件。二者汇合后必须按合并候选重算清单并实际执行，不能继续固定使用“113”。
- 059证据§5的33例专项、静态检查与推测的CI路径过滤，不能证明全仓分片通过。独立Reviewer需要核对同head的实际CI记录与缺PG硬失败结果；旧SQLite回归绿不等于客户业务PG覆盖闭合。

## 3. 044现有盘点的接收边界

消费原Owner的CW044-INVENTORY@d9b4cc4，未另建第二份全仓盘点。

1. §18.2分片缺口已经由061独立承接，044后续消费其已合入成果，不重复改分片生成器。
2. §10/12/14.5的分类、缺库硬门和测试入口须以043核销表为输入；TEST-PG、TEST-IMPORT、TEST-HISTORY分别记录实际执行结果，不用新增标签冒充覆盖。
3. §13及尾部将040/041/042全部合入写成收口前置；本次对照main中的CW001已签认pre-GA规则：三项物理删除可延后，在线入口关闭/内部身份隔离/PG唯一入口的证据仍必需。最终由044原Owner在正式实施时按适用阶段调整，不能照旧盘点额外加全量物理删除门槛。
4. 复用已有024签名发布脚本、032交付包及其手册；README入口、受支持平台/版本、CI命令和空环境可执行说明由044统一收口。真正签名实机、恢复、多实例和真实链路仍留对应验收任务。
5. 043的独立覆盖核销、044的命令/分类/文档实施和045的同候选全门禁分别保留，不合并成“CI绿即全部完成”。

## 4. 测试资源实际核查与执行安排

本机Docker只读查询在普通sandbox中权限不足，使用获准的只读提升后成功。下表来源为运行中/已创建容器与宿主监听查询；未读取容器环境变量、凭据或数据库内容。

| 资源 | 当前状态 | 本次安排 |
| --- | --- | --- |
| 5432 / 开发PG | 已被现有开发容器占用 | 保留，不供本任务测试 |
| 5434 / vs-pg-dev | 运行 | 保留 |
| 5435 / vs-pg-cw056 | 运行 | 原Owner清理前不复用 |
| 5436 / vs-pg-cw031 | 运行 | 原Owner清理前不复用 |
| 5437 / vs-pg-cw059 | 运行；059证据登记billing/task/rbac三个专属库 | 059原任务继续使用；本任务不连接、不建删库 |
| 5440 / vs-pg-cw058 | 运行 | 合并不等于资源已释放，仍保留 |
| vs-pg-cw028 | 运行，但没有宿主发布端口 | 不能因端口未监听认定空闲 |
| customer-v3-pg-test-shard0 | Created，未运行 | 名称已占用，Owner未明确；不擅自stop/rm或复用 |

资源执行顺序：

- 061先解决当前分片执行失败及分片资源归属；本次只做无PG的文档/静态验证，可与059专属实例并行。
- 未隔离的全量分片由各Owner串行执行。当前脚本固定容器名`customer-v3-pg-test-shard0..3`，卷名由容器名派生，日志默认落同目录；只改端口不解决容器/卷/日志冲突。
- 默认分片端口5433～5436与已在运行的5434～5436重叠。后续全量执行者应先确认空闲端口段、固定容器及卷归属，并给出任务专用日志目录；未完成时不得直接启动默认分片。
- 059合入、061验证完成后，043的正式核销安排一次与候选对应的真实PG执行；044收口后045再对最终同一SHA执行适用全门禁。本次未提前启动这些依赖未满足的任务。
- 无Docker时的顺序回退仍须有独立PG资源与库清理边界；本次未把工具权限失败记成“没有Docker”。

未提前占用签名证书、staging或付费服务；这些资源在相应验收任务满足前置时，依据已有授权准备。

## 5. worktree分类与已完成归档

共13个：原仓库1个、已有linked worktree 11个、本次新建1个。

| 分类 | 对象 | 处置依据 |
| --- | --- | --- |
| 原始仓库 | 当前CW056分支，PR #15已合入 | 仍承载共享venv/node_modules及其他linked worktree；不作为清理对象 |
| 他人已合并的linked目录 | CW024/028/030/031/058 | 已核对PR #32/#28/#29/#17/#33合并SHA进入main；但仍有ignored成果，部分有活跃容器，Owner未交接，全部保留 |
| 本会话已合并目录 | COORD-PROGRESS-AUDIT，PR #37 | 已核对merged与main祖先关系；5个ignored缓存已归档，压缩包逐文件SHA256校验通过。采集时main Linux/Windows检查仍在运行，等待后再判断移除 |
| 未合并或正在写入 | COORD-PREFLIGHT PR #38、CW044、CW059、CW061 PR #36、CW014回填 | 保留；CW014工作区已有修改，其他clean状态不解除占用 |
| 本次任务 | COORD-PREFLIGHT-EXECUTION | 从最新main创建，完成后走独立PR；合并核验前保留 |

已完成归档位置：`E:/众墅之家爆款短视频创作/.worktree-archives/COORD-PROGRESS-AUDIT-20260911/`，内含`ignored-files.zip`和`manifest.json`。原目录未改动、未删除；回滚分支保留。其他工作区的.env、源码、日志、截图和缓存未代为归档或删除。

### 收尾增量复核

提交前fetch发现main前进到`d7a9a4052e4e962b439f537415facca00152fcec`：PR #38开工清单也已于2026-09-11 15:11:47（北京时间）合并。本次初始快照保留，不将历史“开放”记录覆写为当时已合并。新增成果不改变本次业务前置判断。

PR #37对应main上的Linux/Windows检查现为cancelled（秘密扫描success），不能记为通过。PR #37/#38目录均继续保留；已将两份本会话claim按实际回填MERGED/等待main检查，并额外归档COORD-PREFLIGHT-20260911的5个ignored缓存文件，逐文件SHA256核验通过，归档位于同一`.worktree-archives`根目录下的同名任务子目录。累计两目录、10个文件完成归档；本次移除worktree数为0。

## 6. 本任务开工与验证记录

- Owner：Codex / 01a08add-2977-7b60-a307-af86f90445dd；Reviewer待独立PR评审分配。
- 原子claim：原仓库.git/codex-task-claims/COORD-PREFLIGHT-EXECUTION-20260911/。
- 分支：`docs/customer-preflight-execution-20260911`；worktree：`E:/众墅之家爆款短视频创作/.worktrees/COORD-PREFLIGHT-EXECUTION-20260911`。
- 创建基线：origin/main@dfe7711969f70a85a720aa62e93fc17609ce8058；已取消自动跟踪origin/main，首次push显式设置同名远程分支。
- 文件范围：本记录、配套JSON、代码文件映射，共3个；未改正式业务账本、业务代码、测试实现、CI、他人工作区。
- 验证：所引test函数/模块、固定SHA的AST行号与计数、分片差集、相对链接和文件登记核对通过；既有文档合同测试9 passed（1条既有Starlette弃用警告）；仓库秘密扫描通过，git diff --check通过。PG业务专项、全量pytest及制品门禁本次未执行，纯文档的仓库级门禁交PR CI；没有用静态检查替代业务验收。本记录不声明业务AUTOMATED_VERIFIED，也不声明独立评审/合并完成。
