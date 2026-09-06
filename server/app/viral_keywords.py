"""爆款视频搜索关键词配置（C4 重启，服务端维护）.

分类页签 → 各平台搜索关键词的映射。前端分类名保持稳定，调整关键词只
影响服务端拉取行为。关键词应尽量选宽词：「最近 7 天」筛选叠加窄词会把
候选池压得很薄（实测「乡墅」一周内仅 5 条）。

后续如需运营可配，可迁移到 SettingsRepository 的运行时配置或管理端；
当前为代码内常量（跟仓库评审走）。
"""

from __future__ import annotations

from app.viral_tikhub import PLATFORM_DOUYIN, PLATFORM_WECHAT

VIRAL_CATEGORIES: dict[str, dict[str, str]] = {
    "建房预算": {"douyin": "自建房预算", "wechat_channels": "建房预算"},
    "户型设计": {"douyin": "别墅设计", "wechat_channels": "别墅设计"},
    "施工避坑": {"douyin": "自建房施工", "wechat_channels": "自建房避坑"},
    "庭院案例": {"douyin": "农村庭院设计", "wechat_channels": "农村庭院设计"},
}


def viral_categories() -> list[str]:
    """分类页签的稳定顺序."""
    return list(VIRAL_CATEGORIES)


def viral_keyword(category: str, platform: str) -> str | None:
    """某分类在某平台的搜索关键词；未配置返回 None（跳过该分类）."""
    keywords = VIRAL_CATEGORIES.get(category)
    if not keywords:
        return None
    keyword = keywords.get(platform, "")
    return keyword or None


def viral_platforms() -> tuple[str, ...]:
    return (PLATFORM_DOUYIN, PLATFORM_WECHAT)
