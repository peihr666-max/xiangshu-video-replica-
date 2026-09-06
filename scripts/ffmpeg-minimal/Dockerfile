# 精简 LGPL 构建 ffmpeg/ffprobe（静态 exe，musl 交叉编译）。
# 只保留"上传视频 → 抽音轨（AAC/m4a）→ ffprobe 探测时长"所需能力；
# 不含 x264/x265 等 GPL 库，产物按 LGPL v3 分发（见
# client/src-tauri/resources/ffmpeg/README.md）。
FROM debian:bookworm-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config curl ca-certificates xz-utils make \
        nasm yasm && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src

# musl 交叉工具链
RUN curl -fsSL https://musl.cc/x86_64-linux-musl-cross.tgz \
      | tar -xz -C /opt
ENV PATH="/opt/x86_64-linux-musl-cross/bin:${PATH}"
ENV CC=x86_64-linux-musl-gcc CXX=x86_64-linux-musl-g++ \
    AR=x86_64-linux-musl-ar RANLIB=x86_64-linux-musl-ranlib

ARG FFMPEG_VERSION=7.1.1
RUN curl -fsSL "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" \
      | tar -xJ --strip-components=1

# 精简配置：容器/解码（视频容器只为读出音轨）、AAC 原生编码、无 GPL 组件。
RUN ./configure \
        --target-os=linux --arch=x86_64 \
        --cross-prefix=x86_64-linux-musl- \
        --pkg-config-flags=--static \
        --extra-ldflags=-static \
        --extra-cflags="-Os -ffunction-sections -fdata-sections" \
        --extra-ldflags="-Wl,--gc-sections" \
        --disable-everything --disable-autodetect --disable-debug \
        --disable-doc --disable-programs --disable-network --disable-iconv \
        --disable-bzlib --disable-lzma --disable-sdl2 --disable-xlib \
        --disable-libxcb --disable-vaapi --disable-vdpau --disable-d3d11va \
        --enable-small \
        --enable-ffmpeg --enable-ffprobe \
        --enable-protocol=file \
        --enable-demuxer=mov,mp4,m4a,matroska,webm,avi,flv,ogg,wav,mp3,aac \
        --enable-parser=aac,ac3,dca,flac,h264,hevc,mpegaudio,opus,vorbis,vp8,vp9 \
        --enable-decoder=aac,mp3,mp2,flac,opus,vorbis,pcm_s16le,pcm_u8,ac3,eac3 \
        --enable-encoder=aac,flac,pcm_s16le \
        --enable-muxer=mp4,ipod,adts,flac,wav \
        --enable-bsf=aac_adtstoasc \
        --enable-filter=aresample,aformat,anull,volume \
        && make -j"$(nproc)"

RUN test -x ffmpeg && test -x ffprobe && \
    ./ffmpeg -version | head -3

FROM scratch AS export
COPY --from=build /src/ffmpeg /out/ffmpeg
COPY --from=build /src/ffprobe /out/ffprobe
