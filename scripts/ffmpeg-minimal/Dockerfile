# Windows x64 LGPL FFmpeg runtime for the internal desktop build.
# The allow-list covers both audio extraction and CL-13 static text overlays.
FROM debian:bookworm-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
        binutils-mingw-w64-x86-64 \
        ca-certificates \
        curl \
        gcc-mingw-w64-x86-64-posix \
        make \
        nasm \
        pkg-config \
        xz-utils \
        yasm && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src

ARG FFMPEG_VERSION=9.0.1
ARG FFMPEG_SHA256=cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635
RUN curl -fsSLO "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" && \
    echo "${FFMPEG_SHA256}  ffmpeg-${FFMPEG_VERSION}.tar.xz" | sha256sum -c - && \
    tar -xJf "ffmpeg-${FFMPEG_VERSION}.tar.xz" --strip-components=1 && \
    rm "ffmpeg-${FFMPEG_VERSION}.tar.xz"

# No GPL/non-free external codec library is linked. Windows Media Foundation
# provides the H.264 encoder through the operating system.
RUN ./configure \
        --target-os=mingw32 \
        --arch=x86_64 \
        --cross-prefix=x86_64-w64-mingw32- \
        --enable-cross-compile \
        --enable-version3 \
        --enable-mediafoundation \
        --extra-cflags="-Os -ffunction-sections -fdata-sections" \
        --extra-ldflags="-static -Wl,--gc-sections" \
        --disable-everything \
        --disable-autodetect \
        --disable-debug \
        --disable-doc \
        --disable-network \
        --enable-small \
        --enable-ffmpeg \
        --enable-ffprobe \
        --enable-protocol=file,pipe \
        --enable-demuxer=mov,image2,matroska,webm,avi,flv,ogg,wav,mp3,aac \
        --enable-parser=h264,hevc,aac,mpegaudio \
        --enable-decoder=h264,hevc,aac,mp3,pcm_s16le,png,mjpeg \
        --enable-encoder=h264_mf,aac,png \
        --enable-muxer=mp4,image2,ipod,adts,wav \
        --enable-bsf=aac_adtstoasc \
        --enable-filter=overlay,scale,format,fps,setpts,trim,aresample,aformat,asetpts,atrim,amix,volume,anull \
        && make -j"$(nproc)"

ARG NOTO_TAG=Sans2.004
ARG NOTO_SHA256=faa6c9df652116dde789d351359f3d7e5d2285a2b2a1f04a2d7244df706d5ea9
RUN mkdir -p /assets && \
    curl -fsSL \
      "https://raw.githubusercontent.com/notofonts/noto-cjk/${NOTO_TAG}/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf" \
      -o /assets/NotoSansSC-Regular.otf && \
    echo "${NOTO_SHA256}  /assets/NotoSansSC-Regular.otf" | sha256sum -c - && \
    curl -fsSL \
      "https://raw.githubusercontent.com/notofonts/noto-cjk/${NOTO_TAG}/Sans/LICENSE" \
      -o /assets/NotoSansSC-OFL-1.1.txt

RUN test -s ffmpeg.exe && test -s ffprobe.exe && \
    test -s COPYING.LGPLv3 && test -s /assets/NotoSansSC-OFL-1.1.txt

FROM scratch AS export
COPY --from=build /src/ffmpeg.exe /out/ffmpeg.exe
COPY --from=build /src/ffprobe.exe /out/ffprobe.exe
COPY --from=build /src/COPYING.LGPLv3 /out/FFmpeg-LGPLv3.txt
COPY --from=build /assets/NotoSansSC-Regular.otf /out/NotoSansSC-Regular.otf
COPY --from=build /assets/NotoSansSC-OFL-1.1.txt /out/NotoSansSC-OFL-1.1.txt
