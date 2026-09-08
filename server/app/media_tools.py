"""本机媒体工具：ffmpeg/ffprobe 定位与音轨抽取。

客户版桌面部署把精简构建的 ffmpeg/ffprobe 随 NSIS 安装包分发到
``resources/ffmpeg/``（服务端启动脚本负责设置 ``VIDEO_REPLICA_FFMPEG_DIR``）。
解析顺序：环境变量目录 → PATH；两者皆失败时抛出可识别错误，任务
fail-closed，不静默降级到其它解析通道。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

FFMPEG_DIR_ENV = "VIDEO_REPLICA_FFMPEG_DIR"
FFMPEG_TIMEOUT_SECONDS = 300


class MediaToolUnavailable(RuntimeError):
    """ffmpeg/ffprobe binary could not be located."""


class MediaToolFailed(RuntimeError):
    """ffmpeg/ffprobe ran but returned a non-zero exit."""


def resolve_media_binary(tool: str) -> str:
    """Locate ``ffmpeg``/``ffprobe``; env dir wins, then PATH."""
    env_dir = os.environ.get(FFMPEG_DIR_ENV, "").strip()
    if env_dir:
        for suffix in (".exe", ""):
            candidate = Path(env_dir) / f"{tool}{suffix}"
            if candidate.is_file():
                return str(candidate)
    located = shutil.which(tool)
    if located:
        return located
    raise MediaToolUnavailable(f"未找到 {tool}，请确认安装包完整或配置 {FFMPEG_DIR_ENV}。")


def extract_audio(ffmpeg_path: str, video_path: Path, audio_path: Path) -> None:
    """单声道 16kHz 低码率 AAC 音轨，足够转写且远小于原视频。"""
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "aac",
        "-b:a",
        "32k",
        str(audio_path),
    ]
    _run(command)


def probe_duration_seconds(ffprobe_path: str, media_path: Path) -> float | None:
    """容器时长（秒）；探测失败返回 None，由 provider 自行选择模式。"""
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(media_path),
    ]
    try:
        output = subprocess.run(
            command,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
            check=True,
        ).stdout
        duration = json.loads(output.decode("utf-8"))["format"]["duration"]
        return float(duration)
    except (subprocess.SubprocessError, KeyError, ValueError, OSError):
        return None


def require_media_stream(
    content: bytes,
    *,
    extension: str,
    expected_stream: Literal["audio", "video"],
) -> None:
    """Fail closed unless the expected stream exists and fully decodes."""
    if not content:
        raise MediaToolFailed("媒体文件为空，无法归档")
    ffprobe_path = resolve_media_binary("ffprobe")
    ffmpeg_path = resolve_media_binary("ffmpeg")
    suffix = f".{extension.lstrip('.')}"
    try:
        with tempfile.TemporaryDirectory(prefix="video-replica-media-") as directory:
            media_path = Path(directory) / f"provider-result{suffix}"
            media_path.write_bytes(content)
            probe = subprocess.run(
                [
                    ffprobe_path,
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "json",
                    str(media_path),
                ],
                capture_output=True,
                timeout=FFMPEG_TIMEOUT_SECONDS,
            )
            if probe.returncode != 0:
                raise MediaToolFailed("媒体文件无法验证，请稍后重试")
            payload = json.loads(probe.stdout.decode("utf-8"))
            streams = payload.get("streams")
            if not isinstance(streams, list) or not any(
                isinstance(stream, dict) and stream.get("codec_type") == expected_stream
                for stream in streams
            ):
                raise MediaToolFailed("媒体文件无法验证，请稍后重试")
            decoded = subprocess.run(
                [
                    ffmpeg_path,
                    "-v",
                    "error",
                    "-xerror",
                    "-i",
                    str(media_path),
                    "-map",
                    f"0:{expected_stream[0]}:0",
                    "-f",
                    "null",
                    "-",
                    "-progress",
                    "pipe:1",
                    "-nostats",
                ],
                capture_output=True,
                timeout=FFMPEG_TIMEOUT_SECONDS,
            )
            progress = dict(
                line.split("=", 1)
                for line in decoded.stdout.decode("utf-8", "replace").splitlines()
                if "=" in line
            )
            has_output = (
                int(progress.get("out_time_us", "0")) > 0 or int(progress.get("frame", "0")) > 0
            )
            if decoded.returncode != 0 or progress.get("progress") != "end" or not has_output:
                raise MediaToolFailed("媒体文件无法验证，请稍后重试")
    except MediaToolFailed:
        raise
    except (json.JSONDecodeError, OSError, subprocess.SubprocessError, ValueError) as exc:
        raise MediaToolFailed("媒体文件无法验证，请稍后重试") from exc


def _run(command: list[str]) -> None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise MediaToolFailed(f"{Path(command[0]).name} 执行失败：{type(exc).__name__}") from exc
    if completed.returncode != 0:
        raise MediaToolFailed(f"{Path(command[0]).name} 返回非零退出码")
