# H3 提示词 v7：补齐拆解-生成链路的 Style/Audio/Scene/Subject 细节（2026-09-16）

## 背景与动机

用户反馈"拆解出来的提示词达不到复刻的深度"。排查确认根因不是拆解模型能力不足，而是拆解结果里相当一部分信息在进入生成链路前被丢弃或从未被要求填写：

- `analysis_instruction()` 要求模型返回 `theme`/`visual_style`/`pace`/`camera_language`，但 `create_shot_card_version()`（analysis.py）保存镜头卡时只搬运了 `duration_seconds`，这四个字段从未进入镜头卡 payload；`compile_prompt_text()`（generation.py）自然也从未使用过它们——即便拆解阶段填了，正式保存后也读不到。
- H3 六段模板（`H3_PROMPT_TEMPLATE_SPEC`）里 `outro` 段是写死常量，不是逐镜头拆解结果。
- `scene`/`subject` 两个字段的 schema 本身较浅：`scene` 无光线/陈设子项；v6（R44）出于防身份漂移的考虑，把 shot 段主体固定为"已确认首帧中的人物"，连非身份类的服装/姿态细节也一并舍弃。
- 对照 MiniMax H3 官方提示词指南（Subject + Action + Scene + Visual Style + Camera + Audio 六层公式），当前实现只有 Action（`motion` 结构化字段）和 Camera 做得扎实，Style 层名存实亡、Audio 层是常量占位、Scene/Subject 偏浅。

调研过程与外部依据见对话记录（可灵AI提示词公式、Google Veo 提示指南、video-notation-schema、MiniMax H3 官方指南等），未落盘为独立文档。

## 与 PR #125（PROMPT-OPTIMIZE）的关系

本任务与 #125 并行开发，变基到 #125 合并后的 main（`ba616f46`）时：字段定义（5 个镜头字段、`VideoAnalysis.color_tone`）、`camera_motion` 枚举扩展、`prompt_rules/analysis.txt` 中的新拆解指令均以 #125 为准；本任务保留的增量是 (1) 旧路径 `analysis_instruction()` 的同步指令更新，(2) `create_shot_card_version()` 把 theme/visual_style/pace/camera_language/color_tone 落进镜头卡 payload，(3) `compile_prompt_text()` 的 Style/Scene/Subject/Audio 子句，(4) 本文档与 MiniMax H3 官方指南参考资料。

## 改动内容

### `server/app/analysis.py`

- `ShotMotion.camera_motion` 枚举新增 `ORBIT`/`CRANE_UP`/`CRANE_DOWN`/`ZOOM_IN`/`ZOOM_OUT`（对齐 H3 官方运镜词表，原有 7 项不变）。
- `ShotCard` 新增 5 个可选字段（缺失时为空串，旧数据/旧 provider 响应缺失不报错；本任务原实现为 `str | None`，变基到 #125 后统一沿用其 `str = ""` 定义，`generation.py` 编译层用 `str(x or "").strip()` 判断，两种取值都兼容）：`scene_dressing`、`scene_lighting`、`wardrobe_pose_detail`（仅服装/配饰/姿态，指令明确禁止面部长相描述）、`ambient_sound`、`music_style_hint`。
- `VideoAnalysis` 新增可选字段 `color_tone`。
- `analysis_instruction()` 同步更新 JSON 结构声明、新增字段的中文填写要求与示例，新增第 4 条规则强制 `wardrobe_pose_detail` 不得含身份特征描述。
- `create_shot_card_version()` 补齐：把 `theme`/`visual_style`/`pace`/`camera_language`/`color_tone` 一并搬进镜头卡 payload（此前遗漏，是这条链路能打通的前提，不属于原计划但属必要修复）。

### `server/app/generation.py`

- `H3_PROMPT_TEMPLATE_VERSION`: `h3.prompt.v6` → `h3.prompt.v7`（hash 随 spec 内容自动重算）。
- `H3_PROMPT_TEMPLATE_SPEC` 新增 `style` 段（`build_style_clause()` 动态拼接 `visual_style`/`color_tone`/`pace`/`camera_language`，任一缺失跳过子句，全部缺失跳过整段，不留空行）。
- `shot` 段：主体子句追加 `wardrobe_clause`（来自 `wardrobe_pose_detail`）；`scene` 改用 `shot_scene_text()` 拼接 `scene_dressing`/`scene_lighting`；时间戳格式从 `{start:.1f}-{end:.1f}s` 改为 `MM:SS.mmm`（`_format_shot_timestamp()`），对齐 H3 官方指南格式。
- `outro` 更名为 `audio`：`build_audio_clause()` 汇总各镜头 `ambient_sound`/`music_style_hint`；旧镜头卡没有这些字段时退化为原固定文案，行为不劣化。
- `MOTION_CAMERA_MOTION_LABELS` 补齐新增枚举的中文映射。

## 已做的验证（范围有限，见下节边界）

- `ruff check app/generation.py app/analysis.py`：通过。
- `uv run mypy app/generation.py app/analysis.py`（strict）：通过。
- 手工构造"旧镜头卡"（不含任何新字段）与"新镜头卡"（含全部新字段）两组输入跑 `compile_prompt_text()`：旧输入行为与 v6 一致（仅时间戳格式变化），新输入能看到 style/wardrobe/scene/audio 子句按预期拼接、缺失字段按预期跳过。
- 仓库里唯一直接断言 `compile_prompt_text()` 输出的既有测试
  `tests/test_cw030_worker_pg_matrix.py::test_compiled_video_prompt_uses_confirmed_image_instead_of_source_appearance`
  本机跑通（需要 `PYTHONPATH=E:/migshield` 绕过 Windows 上 `pg_test_kit` 的 `fcntl` 导入问题，Linux CI 不受影响）。
- 确认前端 `GenerationComposer.test.tsx` 里出现的 `"h3.prompt.v1"` 是 mock 数据里的占位字符串，不来自后端常量、不依赖后端实际模板版本；`generated/api.ts` 里 `template_version`/`template_hash` 类型是 `string | null`，非字面量枚举，本次版本号变更不需要重新生成前端类型或改前端测试。

## 明确未验证 / 未完成（不冒称已完成）

- **没有跑完整测试门禁**：没有跑完整 PostgreSQL 四分片套件，没有跑前端 Vitest 全量套件，没有跑 Ruff/Mypy 全量文件门禁，只针对本次改动的两个文件做了检查。
- **没有真实调用 Gemini/Apilio 拆解一条真实素材**，不知道模型对新增的 `scene_dressing`/`wardrobe_pose_detail`/`ambient_sound`/`music_style_hint`/`color_tone` 的遵循度和真实产出质量；`analysis_instruction()` 的措辞是否需要根据真实产出再调整，未知。
- **没有真实调用秘塔/MiniMax H3 生成视频**，v7 模板编译出的 prompt 能否实际提升复刻效果（相对 v6），未做任何生成对比。
- **没有做人物身份安全回归**：`wardrobe_pose_detail` 是新引入的自由文本字段，理论上有被模型误填入身份特征的风险（指令层面已禁止，但没有做红队式测试验证模型是否会遵守）。
- 未提交 PR、未合并、未部署；线上镜头卡历史数据不会自动补齐新字段（新字段全部可选、无 backfill）。

## 结论

代码改动已就位、类型与静态检查通过、有限范围的单元验证通过；效果验证（模型遵循度、生成质量提升与否、身份安全回归）仍完全空白，是否继续投入取决于用户是否要跑一次真实拆解+生成的端到端对比。
