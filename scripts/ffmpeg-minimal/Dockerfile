# 精简 LGPL Windows 构建：为内部 NSIS 安装包生成静态 ffmpeg.exe/ffprobe.exe。
# 只保留“上传视频 -> 抽音轨（AAC/m4a）-> ffprobe 探测时长”所需能力，
# 不启用 x264/x265 等 GPL 组件。
FROM debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171 AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
        binutils-mingw-w64-x86-64 \
        build-essential \
        ca-certificates \
        curl \
        file \
        gcc-mingw-w64-x86-64 \
        g++-mingw-w64-x86-64 \
        make \
        nasm \
        pkg-config \
        xz-utils \
        yasm && \
    dpkg-query -W -f='${binary:Package}\t${Version}\n' > /tmp/BUILD-PACKAGES.txt && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src

COPY configure.sh /tmp/configure-ffmpeg.sh

ARG FFMPEG_VERSION=7.1.5
ARG FFMPEG_SHA256=de668509caf9e35e3cd162473441fdb29538c6d96ed080292b3cf9e6fc5d558f
RUN curl -fsSL --retry 3 --retry-delay 2 \
        "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" \
        -o /tmp/ffmpeg-source.tar.xz && \
    printf '%s  %s\n' "$FFMPEG_SHA256" /tmp/ffmpeg-source.tar.xz | sha256sum -c - && \
    tar -xJf /tmp/ffmpeg-source.tar.xz --strip-components=1

# Debian 的 mingw-w64 交叉编译器生成原生 PE32+ Windows 程序。
# configure.sh 与 Windows CI 共用同一组功能开关。
RUN FFMPEG_CROSS_PREFIX=x86_64-w64-mingw32- bash /tmp/configure-ffmpeg.sh && \
    make -j"$(nproc)" && \
    test -f ffmpeg.exe && \
    test -f ffprobe.exe && \
    file ffmpeg.exe ffprobe.exe | tee /tmp/file-types.txt && \
    grep -c 'PE32+ executable' /tmp/file-types.txt | grep -qx '2'

FROM scratch AS export
COPY --from=build /src/ffmpeg.exe /ffmpeg.exe
COPY --from=build /src/ffprobe.exe /ffprobe.exe
COPY --from=build /tmp/ffmpeg-source.tar.xz /ffmpeg-7.1.5.tar.xz
COPY --from=build /tmp/BUILD-PACKAGES.txt /BUILD-PACKAGES.txt
