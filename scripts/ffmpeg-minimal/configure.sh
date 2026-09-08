#!/usr/bin/env bash
# Shared FFmpeg feature set for Docker cross-builds and native MSYS2 builds.
set -euo pipefail

configure_command="${FFMPEG_CONFIGURE_COMMAND:-./configure}"
cross_args=()
if [[ -n "${FFMPEG_CROSS_PREFIX:-}" ]]; then
  cross_args+=(--enable-cross-compile "--cross-prefix=${FFMPEG_CROSS_PREFIX}")
fi

exec "$configure_command" \
  --target-os=mingw32 \
  --arch=x86_64 \
  "${cross_args[@]}" \
  --enable-static \
  --disable-shared \
  --enable-w32threads \
  --enable-version3 \
  --extra-cflags="-Os -ffunction-sections -fdata-sections" \
  --extra-ldflags="-static -Wl,--gc-sections" \
  --disable-everything \
  --disable-autodetect \
  --disable-debug \
  --disable-doc \
  --disable-programs \
  --disable-network \
  --disable-iconv \
  --disable-bzlib \
  --disable-lzma \
  --disable-sdl2 \
  --disable-xlib \
  --disable-libxcb \
  --disable-vaapi \
  --disable-vdpau \
  --disable-d3d11va \
  --enable-small \
  --enable-ffmpeg \
  --enable-ffprobe \
  --enable-protocol=file \
  --enable-demuxer=mov,mp4,m4a,matroska,webm,avi,flv,ogg,wav,mp3,aac \
  --enable-parser=aac,ac3,dca,flac,h264,hevc,mpegaudio,opus,vorbis,vp8,vp9 \
  --enable-decoder=aac,mp3,mp2,flac,opus,vorbis,pcm_s16le,pcm_u8,ac3,eac3 \
  --enable-encoder=aac,flac,pcm_s16le \
  --enable-muxer=mp4,ipod,adts,flac,wav \
  --enable-bsf=aac_adtstoasc \
  --enable-filter=aresample,aformat,anull,volume
