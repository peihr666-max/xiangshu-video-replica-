#!/usr/bin/env bash
# 精简 LGPL Windows 构建 ffmpeg/ffprobe（决策 #5，C7/ASR 文案链路）。
# 产出静态 PE32+ exe，覆盖抽音轨、探测时长和口播媒体完整解码，不含 GPL 组件。
#
# 用法：scripts/ffmpeg-minimal/build.sh [输出目录]
# 依赖：Docker；容器内使用 Debian mingw-w64 交叉编译。
set -euo pipefail

OUT_DIR="${1:-$(dirname "$0")/../../client/src-tauri/resources/ffmpeg}"
# BuildKit 导出：把 export 阶段的静态 exe 直接落到输出目录。
DOCKER_BUILDKIT=1 docker build --output "type=local,dest=$OUT_DIR" "$(dirname "$0")"

test -f "$OUT_DIR/ffmpeg.exe"
test -f "$OUT_DIR/ffprobe.exe"
test -f "$OUT_DIR/ffmpeg-7.1.5.tar.xz"
test -f "$OUT_DIR/BUILD-PACKAGES.txt"
printf '%s\n' "Windows media tools exported to $OUT_DIR"
file "$OUT_DIR/ffmpeg.exe" "$OUT_DIR/ffprobe.exe"
