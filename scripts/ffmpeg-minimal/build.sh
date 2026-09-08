#!/usr/bin/env bash
# Build the internal Windows media runtime. Generated binaries and font files
# are intentionally not committed; CI rebuilds them from pinned sources.
set -euo pipefail

OUT_DIR="${1:-$(dirname "$0")/../../client/src-tauri/resources/ffmpeg}"

DOCKER_BUILDKIT=1 docker build \
  --output "type=local,dest=$OUT_DIR" \
  "$(dirname "$0")"

required=(
  ffmpeg.exe
  ffprobe.exe
  FFmpeg-LGPLv3.txt
  NotoSansSC-Regular.otf
  NotoSansSC-OFL-1.1.txt
)
for filename in "${required[@]}"; do
  test -s "$OUT_DIR/$filename"
done

font_sha="$(sha256sum "$OUT_DIR/NotoSansSC-Regular.otf" | awk '{print $1}')"
test "$font_sha" = "faa6c9df652116dde789d351359f3d7e5d2285a2b2a1f04a2d7244df706d5ea9"

echo "Windows media runtime built at $OUT_DIR"
for filename in "${required[@]}"; do
  sha256sum "$OUT_DIR/$filename"
done
