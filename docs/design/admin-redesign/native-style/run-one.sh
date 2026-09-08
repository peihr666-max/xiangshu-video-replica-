#!/usr/bin/env bash
# 用本地 Codex CLI 的 Image Gen 能力生成一页管理后台效果图（现有系统原样式版）
# 用法: bash run-one.sh <slug>   例: bash run-one.sh 01-overview
set -euo pipefail

SLUG="${1:?用法: bash run-one.sh <slug>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PROMPT_FILE="$HERE/prompts/${SLUG}.md"
OUT_PNG="$HERE/${SLUG}.png"

[ -f "$PROMPT_FILE" ] || { echo "缺少提示词文件: $PROMPT_FILE"; exit 1; }

# 组装最终提示词：任务指令 + 共享风格（原系统样式）+ 页面规格
{
  cat <<'WRAPPER'
你的唯一任务：调用你内置的图像生成工具（Image Gen），按下面【图像提示词】生成一张图片，然后把生成的 PNG 保存到当前工作目录，文件名必须严格等于下面指定的名字。要求：
1) 图片为宽幅横版（优先 1536x1024）。
2) 只做两件事：生成图片、保存文件；不要读取仓库其他文件、不要改任何代码、不要运行测试。
3) 如果工具产物在别的目录（如生成图片缓存目录），用复制的方式保存到当前目录并重命名。
4) 完成后最终回复只写一行：OK <实际保存的文件名>。

【图像提示词开始】
WRAPPER
  cat "$HERE/00-shared-style.md"
  echo
  cat "$PROMPT_FILE"
  echo
  echo "【图像提示词结束】"
  echo
  echo "保存文件名：${SLUG}.png"
} > "$HERE/prompts/.final-${SLUG}.txt"

codex exec \
  --skip-git-repo-check \
  -s workspace-write \
  -C "$HERE" \
  -c model_reasoning_effort='"low"' \
  -c project_doc_max_bytes=0 \
  - < "$HERE/prompts/.final-${SLUG}.txt"

if [ -f "$OUT_PNG" ]; then
  echo "=== 完成: $OUT_PNG ==="
else
  echo "=== 警告: 未找到 $OUT_PNG，请检查 codex 输出 ==="
  exit 3
fi
