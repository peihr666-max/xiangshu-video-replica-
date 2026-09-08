# resources/ffmpeg/ — 精简构建 ffmpeg/ffprobe（决策 #5）

本目录随 Windows NSIS 安装包分发**精简 LGPL 构建**的 `ffmpeg.exe` 与
`ffprobe.exe`，供服务端媒体管线（`server/app/media_tools.py`）抽音轨、探测
时长，并在口播声音试听和口播成片归档前完整解码媒体流。`start-backend.bat`
已把 `VIDEO_REPLICA_FFMPEG_DIR` 默认指向本目录；两个二进制缺失时任务
fail-closed 报明确错误，不静默降级。

## 为什么是精简构建

- 我们的场景需要容器解析、常见音视频解码、AAC 编码和完整解码校验。
  二进制体积由 Windows CI 每次构建后记录；扩展视频解码器后的新体积以
  CI 实测产物为准。
- 不启用 x264/x265 等 GPL 库 → 可用 LGPL 许可分发，商业闭源合规义务更轻。
- 两个程序静态链接，无需附带第三方运行库 DLL；许可证、对应源码和构建
  记录随程序一起分发，详见 `SOURCE-NOTICE.md`。

## 构建方式

在任意有 Docker 的机器上执行仓库脚本 `scripts/ffmpeg-minimal/build.sh`。
脚本使用 Debian mingw-w64 交叉编译原生 Windows PE32+ 程序，产物输出到
本目录。CI 在 Windows 的 MSYS2 环境使用同一份 `configure.sh` 构建，避开
GitHub artifact 存储依赖；随后实际执行两个程序、完成 WAV → AAC/M4A
转换，验证 MP3/H.264 完整解码及截断视频拒绝，并检查内部安装包中的路径
和 SHA256。二进制与源码归档不提交进 git（见同目录 `.gitignore`），由
固定构建流程在 CI 中生成和获取。

## 自检

```bat
resources\ffmpeg\ffmpeg.exe -version
resources\ffmpeg\ffprobe.exe -version
```

版本横幅应显示 `--enable-gpl` **不存在**、配置包含
`--enable-version3`（LGPL v3 构建）。
