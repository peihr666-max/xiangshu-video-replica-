#!/usr/bin/env bash
# Build the internal Windows FFmpeg tools on a GitHub Windows runner in MSYS2.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf 'usage: %s <source-archive> <output-directory>\n' "$0" >&2
  exit 2
fi

to_unix_path() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -u "$1"
  else
    printf '%s\n' "$1"
  fi
}

source_archive="$(to_unix_path "$1")"
output_dir="$(to_unix_path "$2")"
runner_temp="$(to_unix_path "${RUNNER_TEMP:?RUNNER_TEMP is required}")"
script_dir="$(cd "$(dirname "$0")" && pwd)"
build_dir="$runner_temp/ffmpeg-7.1.5-msys2-build"
expected_sha256="de668509caf9e35e3cd162473441fdb29538c6d96ed080292b3cf9e6fc5d558f"

actual_sha256="$(sha256sum "$source_archive" | awk '{print $1}')"
[[ "$actual_sha256" == "$expected_sha256" ]]

mkdir -p "$build_dir" "$output_dir"
tar -xJf "$source_archive" -C "$build_dir" --strip-components=1
(
  cd "$build_dir"
  bash "$script_dir/configure.sh"
  make -j"$(nproc)"
  test -f ffmpeg.exe
  test -f ffprobe.exe
  file ffmpeg.exe ffprobe.exe | tee "$runner_temp/ffmpeg-file-types.txt"
  test "$(grep -c 'PE32+ executable' "$runner_temp/ffmpeg-file-types.txt")" -eq 2
  cp ffmpeg.exe ffprobe.exe "$output_dir/"
)

cp "$source_archive" "$output_dir/ffmpeg-7.1.5.tar.xz"
pacman -Q > "$output_dir/BUILD-PACKAGES.txt"
(
  cd "$output_dir"
  sha256sum ffmpeg.exe ffprobe.exe ffmpeg-7.1.5.tar.xz > SHA256SUMS.txt
)
