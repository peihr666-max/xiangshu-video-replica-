# FFmpeg 7.1.5 source and build notice

The internal Windows installer contains an unmodified FFmpeg 7.1.5 source
archive next to the corresponding `ffmpeg.exe` and `ffprobe.exe` binaries.

- Upstream source: <https://ffmpeg.org/releases/ffmpeg-7.1.5.tar.xz>
- SHA256: `de668509caf9e35e3cd162473441fdb29538c6d96ed080292b3cf9e6fc5d558f`
- Source modifications: none
- License: GNU Lesser General Public License version 3 or later; see
  `COPYING.LGPLv3` in this directory.
- Reproducible build definition: `scripts/ffmpeg-minimal/Dockerfile`
- Compiler package manifest: generated as `BUILD-PACKAGES.txt` and included in
  the same installer directory.

The exact configure invocation is:

```text
./configure \
  --target-os=mingw32 \
  --arch=x86_64 \
  --enable-cross-compile \
  --cross-prefix=x86_64-w64-mingw32- \
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
```

The CI build rejects source checksum mismatches, `--enable-gpl`, non-Windows
executables, conversion failures, and installer payload hash mismatches.
