# T46 — 人物库页面全链路收口证据

## 当前状态

- 状态：`AUTOMATED_VERIFIED`
- 基线：`7f08678`
- 分支：`feat/character-library-page-closure`
- 计划：`docs/人物库页面全链路收口计划-2026-09-07.md`
- 当前证据层级：`AUTOMATED_VERIFIED`
- 真实 Apilio、DeepSeek、Hifly、COS 和账务联合链未执行，仍归 T40。

## 工作包证据

| 工作包 | 失败测试/回归锁 | 实现结果 | 验证 | 状态 |
| --- | --- | --- | --- | --- |
| CL-00 | 冻结前不得改代码 | 固化范围、验收、No-Go、回滚与真实链边界 | 文档自审；`40b62e7` | 完成 |
| CL-01 | SQLite/PG 覆盖 UNKNOWN、槽位释放和双击提交 | 普通用户不能重提结果未知的付费口播；稳定幂等键与单飞提交；未知态释放队列槽但保留冻结账务 | 口播 SQLite 50、PG 槽位专项、前端 API/映射/详情 159；`50146b6` | 完成 |
| CL-02 | 损坏图片、错误 MIME、零尺寸与异常拼图先红 | Provider 图片统一解码、校验、转 PNG 后再裁切和发布；真实路径不再用确定性占位图兜底 | 人物素材 12、simple character 61；`9fb616e` | 完成 |
| CL-03 | 伪音频、空视频、HTML 响应与时长越界先红 | 复用 ffprobe 验证容器、媒体流、时长和 MIME；只有可播放媒体能确认、成功和结算 | oral 53、materials 12；`9fb616e` | 完成 |
| CL-04 | auditor mutation、删除数据库/存储失败顺序先红 | 人物和口播写入统一后端角色门；人物先提交数据库删除，再幂等清理对象 | character/oral 120；`263c4f2` | 完成 |
| CL-05 | 父页面跨人物迟到响应覆盖先红 | 人物 identity 从 IP 页面贯通 AnalysisWorkspace 和改写请求，并由任务保存不可变 IP 档案快照 | 前端跨页与后端改写专项；`9d222f4` | 完成 |
| CL-06 | 场景卡到分身页的真实选图交接先红 | 制作口播分身会写入当前场景资产；照片/视频来源类型保持真实 | 前端人物/创作/工作台跨页套件；`9d222f4` | 完成 |
| CL-07 | 音频直传、字幕开关与伪模板参数先红 | 音频复用素材三段式上传；标准口播下传 `subtitle.st_show`；移除未落地网感模板入口 | 前端创作页与 oral 路由专项；`9d222f4` | 完成 |
| CL-08 | 口播价格迁移、权限、掩码和请求字段先红 | 新增可逆迁移 `077_oral_unit_price`；管理设置增加 Hifly 与口播价格；OpenAPI/类型同步 | 服务端设置/迁移 64、前端设置 35；`dfb6feb` | 完成 |
| CL-09 | 第 9 人/第 13 场景、混类资产、UNKNOWN 展示与计数先红 | 新版人物页只嵌入真实 CharacterLibrary；取消静默截断；场景/分身分组；服务端真实计数；搜索并按 12 人分批加载；只加载可见预览；UNKNOWN 禁止普通重提 | 人物页、API、工作台专项；前端全量 990；`754cd93`、`3a3d51e` | 完成 |
| CL-10 | 全仓迁移 head、设置计价、夹具来源和动态签名契约回归 | 同步迁移 head 与所有测试契约；修复口播价格初始同步竞态；动态签名按媒体身份而非过期查询参数比较 | `npm run check`：前端 990、服务端 1930、密钥/E2E/Tauri/Ruff/format/Mypy 全绿；`f0b6abc`、`89ae7c6`、`16a1c45` | 完成 |

## 页面与后端联动结论

| 页面/动作 | 前端入口 | 后端闭环 | 结论 |
| --- | --- | --- | --- |
| 人物列表 | 新增、搜索、加载更多、改名、重生、删除、完整档案 | 人物列表/上传/任务/重命名/删除路由，owner 与 auditor 校验 | 自动化闭环 |
| 基础形象 | 单图上传、五视图拼图预览、下载、重新生成 | 三段式上传、异步人物任务、图片解码/拼图校验、资产发布 | 自动化闭环；真实 Apilio 待 T40 |
| 场景形象 | 场景/服装生成、第 13 条可达、制作口播分身 | scene-look 任务、人物绑定、场景资产计数与分组 | 自动化闭环；真实图像 Provider 待 T40 |
| IP 档案/二创 | 保存恢复、按 IP 二创、切换人物隔离结果 | identity/profile 持久化；script-rewrite 保存 profile snapshot | 自动化闭环；真实 DeepSeek 待 T40 |
| 口播分身 | 照片/视频来源、授权、状态、失败原因 | consent、avatar clone、媒体验证、UNKNOWN 状态 | 自动化闭环；真实 Hifly 待 T40 |
| 声音克隆 | 5–180 秒音频、授权、试听、确认 | voice sample/clone/confirm、ffprobe、状态持久化 | 自动化闭环；真实 Hifly 待 T40 |
| 数字人口播 | 文案/音频两模式、直传、字幕、单飞提交 | oral task、稳定幂等、队列、钱包 RESERVE/SETTLE/RELEASE、归档 | 自动化闭环；真实 Hifly/COS/账务对账待 T40 |
| 任务中心 | 取消、下载、归档重试、UNKNOWN 人工核对 | 任务状态机、恢复、归档和权限路由 | 自动化闭环；真实故障演练待 T39/T40 |
| 设置 | Hifly 密钥、连接测试、口播单价 | provider settings、掩码、管理员权限、`/api/oral/price`、迁移 077 | 自动化闭环；真实凭据连接待 T40 |

正式页面没有 API 失败后回退 mock 的路径。`review=true` 的设计评审夹具仍显式保留，不会在正式入口自动启用。未清空本机业务数据库：现有记录没有可靠的“模拟数据”标识，直接删除存在误删真实人物/任务的风险。

## 最终门禁

- PostgreSQL：`scripts/pg-fixture.sh start` 成功；门禁后 `stop` 并删除测试容器。
- 命令：`npm run check`。
- 密钥扫描：通过，无运行时契约硬编码密钥。
- 前端：Biome、TypeScript、Vitest 全绿，72 个文件、990 个用例通过。
- E2E 源码：Biome 14 个文件通过。
- Tauri：`cargo fmt --check` 与 `cargo check --locked` 通过。
- 服务端：Ruff 276 个文件、Mypy 100 个源文件通过。
- 服务端测试：1930/1930 通过；耗时 790.97 秒。
- 已知非阻断告警：既有 analytics CSS specificity 1 条、macOS 下 Windows 凭据常量 dead-code 2 条、Starlette TestClient 弃用告警 1 条。

## §14 任务证据记录

```text
任务/工作包：T46 / CL-00–CL-10
Owner / Reviewer：Codex / independent verifier
分支 / 基线 SHA：feat/character-library-page-closure / 7f08678
上游规格段落：客户版任务清单 V3 §12–§15；人物库页面全链路收口计划
改动文件：前端人物/创作/设置/API/状态模型；后端人物/素材/媒体探测/口播/设置；迁移 077；对应测试与本证据文档，共 60 个文件
失败测试或回归锁定：UNKNOWN 重提与槽位、图片/媒体伪成功、auditor 写入、删除顺序、IP/场景跨页、音频与字幕、计价迁移、第 13 人可达、输入同步竞态、动态签名跨秒
实现结果：CL-00–CL-10 全部完成；页面与后端代码链形成单一真实入口；正式运行不回退 review/mock
验证命令与通过数：`npm run check`；前端 990/990，后端 1930/1930，密钥/E2E/Tauri/Ruff/format/Mypy 全通过
证据层级：AUTOMATED_VERIFIED
安全与可观测性：真实凭据不得入库、日志、测试夹具或提交
迁移与回滚：新增可逆迁移 `077_oral_unit_price`；代码按 Lore 提交逐包 `git revert`
外部授权记录：未授权真实付费 Provider、生产 COS、支付和发布
未测试项：真实 Apilio/DeepSeek/Hifly/COS/钱包联合链
Lore 提交 SHA：`40b62e7`、`50146b6`、`9d222f4`、`9fb616e`、`263c4f2`、`dfb6feb`、`754cd93`、`f0b6abc`、`3a3d51e`、`89ae7c6`、`16a1c45`
```

## 仍未完成/未授权

1. CL-11：真实 Apilio 五视图/场景图、DeepSeek IP 改写、Hifly 分身/声音/口播、COS 归档和钱包对账，必须在 T40 经用户明确授权并使用同一候选 SHA 验证。
2. `oral-ip-agents-research` 中的网感后期模板（字幕、封面、BGM 合成）不属于 Hifly 生成参数，当前仓库没有模板渲染器，页面已停止展示伪生效入口。
3. 当前人物列表为服务端全量返回、前端搜索和每批 12 人加载；超大人物库的服务端游标分页是后续性能项，不影响当前人物可达性。
4. 尚未完成 staging、生产发布、真实角色 UAT、真实供应商余额/回执/媒体取回与生产告警演练，不得宣称 `REAL_CHAIN_VERIFIED` 或 `PRODUCTION_GO`。
