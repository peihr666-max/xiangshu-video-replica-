# resources/ffmpeg/ — 精简构建 ffmpeg/ffprobe（决策 #5）

本目录随 Windows NSIS 安装包分发**精简 LGPL 构建**的 `ffmpeg.exe` 与
`ffprobe.exe`，供服务端"提取文案"管线（`server/app/media_tools.py`）抽音轨
与探测时长使用。`start-backend.bat` 已把 `VIDEO_REPLICA_FFMPEG_DIR` 默认
指向本目录；两个二进制缺失时任务 fail-closed 报明确错误，不静默降级。

## 为什么是精简构建

- 全量静态构建（gyan.dev essentials）会让安装包增加约 30 MB、磁盘约
  180 MB；我们的场景只需要容器解析 + 音频解码 + AAC 编码，精简构建
  单 exe 约 5–15 MB，安装包增量约 5–10 MB。
- 不启用 x264/x265 等 GPL 库 → 可用 LGPL 许可分发，商业闭源合规义务更轻。
- 需要的分发文件只有两个：`ffmpeg.exe`、`ffprobe.exe`（静态链接，
  放在本目录即可，无需 DLL）。

## 构建方式

在任意有 Docker 的机器上执行仓库脚本 `scripts/ffmpeg-minimal/build.sh`
（musl 交叉编译，产物输出到本目录）。CI 的 Windows NSIS 门禁会验证
安装包里包含这两个文件；不要把二进制提交进 git（见同目录 `.gitignore`）。

## 自检

```bat
resources\ffmpeg\ffmpeg.exe -version
resources\ffmpeg\ffprobe.exe -version
```

版本横幅应显示 `--enable-gpl` **不存在**、配置包含
`--enable-version3`（LGPL v3 构建）。
