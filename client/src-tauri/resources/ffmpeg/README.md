# Windows 媒体运行时

本目录在内部 Windows NSIS 构建时包含以下产物：

- `ffmpeg.exe` / `ffprobe.exe`：FFmpeg 9.0.1，使用 MinGW-w64 交叉编译。
- `NotoSansSC-Regular.otf`：Noto Sans CJK SC `Sans2.004` 静态字体。
- `FFmpeg-LGPLv3.txt` / `NotoSansSC-OFL-1.1.txt`：随包许可证。

运行时同时服务于“提取文案”音频管线与 CL-13 口播静态文字后期。
`start-backend.bat` 会自动设置 `VIDEO_REPLICA_FFMPEG_DIR` 和
`VIDEO_REPLICA_COMPOSE_FONT_PATH`；任一能力缺失时后期能力接口会明确返回不可用。

## 构建

在支持 Docker BuildKit 的环境执行：

```bash
scripts/ffmpeg-minimal/build.sh
```

构建脚本从固定版本与固定 SHA256 重建产物，二进制和字体不提交进 Git。
Windows CI 会检查编译参数、编解码器、滤镜以及安装包内容。

## 许可边界

- FFmpeg 构建显式不启用 `--enable-gpl` / `--enable-nonfree`，不链接 x264、
  x265 或 OpenH264；H.264 编码使用 Windows Media Foundation `h264_mf`。
- Noto 字体按 SIL Open Font License 1.1 随包分发。
- Pillow 12.3.0 按 MIT-CMU 许可使用，由 Python 包依赖锁定。
- 客户云版 `tauri.customer.conf.json` 保持 `resources: []`，不携带本地媒体运行时。

上游源码与许可说明：

- <https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz>
- <https://ffmpeg.org/legal.html>
- <https://github.com/notofonts/noto-cjk/releases/tag/Sans2.004>
- <https://github.com/python-pillow/Pillow>
