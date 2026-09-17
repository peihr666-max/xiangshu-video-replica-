"""视频素材缩略图（MATERIAL-THUMBS-B-20260917，P0-3）。

素材库网格的视频瓦片此前只能让浏览器经服务端代理流式拉原视频出首帧。
本模块在视频入库的三个写入点（参考视频上传完成、素材上传完成、生成成片
归档）从**已在手的内容字节**抽首帧 JPEG，缩略图对象与原对象同址派生存放，
并把键记录进 ``assets.metadata_json``（零迁移）——列表 CTE 全分支已带出该
字段，批量授权据此签发 7 天有效的缩略图 URL。

不变量（由 tests/test_material_thumbs.py 钉住）：
- 键派生确定性：``<object_key>.thumb.jpg``；
- 任何抽帧/存储失败只损失缩略图本身，绝不影响原视频的可用性与上传结果；
- 缩略图必须显著小于原视频（网格批量下发才有意义）。
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from app.media_tools import resolve_media_binary

if TYPE_CHECKING:
    from app.storage import StorageAdapter

THUMBNAIL_SUFFIX = ".thumb.jpg"
_THUMBNAIL_MAX_HEIGHT = 480


def thumbnail_key_for(object_key: str) -> str:
    """缩略图对象键：与原对象同址派生，确定性、无碰撞、无需建表."""
    return f"{object_key}{THUMBNAIL_SUFFIX}"


def extract_thumbnail_jpeg(
    content: bytes, *, max_height: int = _THUMBNAIL_MAX_HEIGHT
) -> bytes | None:
    """从视频字节抽首帧 JPEG（缩到 ≤max_height）；任何失败返回 None 不抛错."""
    try:
        ffmpeg = resolve_media_binary("ffmpeg")
        result = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                "pipe:0",
                "-frames:v",
                "1",
                "-vf",
                # 滤镜表达式内的逗号必须转义（逗号是 ffmpeg 的滤镜分隔符）。
                f"scale=-2:min({max_height}\\,ih)",
                "-q:v",
                "4",
                "-f",
                "mjpeg",
                "pipe:1",
            ],
            input=content,
            capture_output=True,
            timeout=60,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.startswith(b"\xff\xd8"):
        return None
    return result.stdout


def store_video_thumbnail(
    storage: StorageAdapter,
    object_key: str,
    content: bytes,
) -> str | None:
    """抽帧并落存储；返回缩略图键，失败返回 None（调用方无需降级处理）."""
    thumb = extract_thumbnail_jpeg(content)
    if thumb is None:
        return None
    key = thumbnail_key_for(object_key)
    try:
        storage.put_object(key, thumb, content_type="image/jpeg")
    except Exception:
        return None
    return key
