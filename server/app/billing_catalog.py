"""Business fee subjects. An absent retail tariff never authorizes a charge."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from app.db_portable import BusinessConnection

Unit = Literal["second", "image", "call"]


@dataclass(frozen=True)
class Service:
    name: str
    unit: Unit
    provider: str
    module: str
    customer_charge_allowed: bool = True


SERVICES: dict[str, Service] = {
    "video_768p": Service("视频生成 · 768P", "second", "metaso", "video"),
    "video_2k": Service("视频生成 · 2K", "second", "metaso", "video"),
    "analysis": Service("视频分析", "call", "apilio", "replica"),
    "first_frame": Service("首帧图片", "image", "apilio", "replacement"),
    "character": Service("人物形象及任务图片", "image", "apilio", "people"),
    "rewrite": Service("文案改写", "call", "deepseek", "copy"),
    "oral": Service("数字人口播", "second", "hifly", "oral"),
    "asr": Service("语音转写", "second", "dashscope", "copy"),
    "viral_data": Service("爆款视频数据请求", "call", "tikhub", "viral"),
    "link_resolution": Service("抖一抖链接解析", "call", "douyidou", "workbench"),
    "avatar_clone": Service("口播分身创建", "call", "hifly", "people"),
    "voice_clone": Service("声音克隆", "call", "hifly", "people"),
    "voice_demo": Service("声音试听合成", "call", "hifly", "people"),
    "quality_inspection": Service("图片及视频质量检查", "call", "apilio", "internal", False),
    "analysis_repair": Service("分析结果修复", "call", "apilio", "internal", False),
    "cos": Service("云存储", "call", "cos", "infrastructure", False),
    "zpay": Service("支付通道", "call", "zpay", "infrastructure", False),
}

# Existing cost hooks refer to these provider subjects; they share the same tariff.
COST_SUBJECTS = {
    "video_generation_768p": "video_768p",
    "video_generation_2k": "video_2k",
    "video_analysis_768p": "analysis",
    "video_analysis_2k": "analysis",
    "first_frame_image": "first_frame",
    "character_sheet_image": "character",
}


class Tariff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    unit_credits: Decimal | None = Field(default=None, ge=0, le=1_000_000, decimal_places=6)
    unit_cost_fen: Decimal | None = Field(default=None, ge=0, le=100_000_000, decimal_places=6)
    unit_rounding: Literal["ceil", "exact"] = "ceil"
    version: int = Field(default=0, ge=0)


def amount(value: Decimal | str | int | float) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or result > Decimal("2147483647"):
        raise ValueError("计费用量必须是有限非负数且不超出允许范围")
    return result.quantize(Decimal("0.000001"))


def calculate_credits(
    tariff: Tariff | None,
    units: Decimal | str | int | float,
    *,
    discount_basis_points: int = 10_000,
    rounding: str = "ceil",
) -> int:
    usage = amount(units)
    if tariff is None or not tariff.enabled or not tariff.unit_credits or not usage:
        return 0
    if not 1 <= discount_basis_points <= 10_000:
        raise ValueError("折扣超出允许范围")
    if tariff.unit_rounding == "ceil":
        usage = usage.to_integral_value(rounding=ROUND_CEILING)
    value = usage * tariff.unit_credits * Decimal(discount_basis_points) / 10_000
    credits = max(
        1,
        int(
            value.to_integral_value(rounding=ROUND_FLOOR if rounding == "floor" else ROUND_CEILING)
        ),
    )
    if credits > 2_147_483_647:
        raise ValueError("积分金额超出允许范围")
    return credits


def read_tariff(conn: BusinessConnection, service: str) -> Tariff | None:
    if service not in SERVICES:
        raise ValueError("未知计费科目")
    row = conn.execute(
        "SELECT enabled, unit_credits, unit_cost_fen, unit_rounding, version "
        "FROM billing_tariffs WHERE service = %s FOR SHARE",
        (service,),
    ).fetchone()
    if row is None:
        return None
    return Tariff(
        **{
            key: row[key]
            for key in ("enabled", "unit_credits", "unit_cost_fen", "unit_rounding", "version")
        }
    )


def retail_snapshot(
    conn: BusinessConnection, service: str, units: Decimal | str | int | float
) -> dict[str, object]:
    from app.customer_pricing import read_pricing

    _, config = read_pricing(conn)
    tariff = read_tariff(conn, service)
    discount = config.discount_basis_points if config else 10000
    rounding = config.consumption_rounding if config else "ceil"
    permitted = SERVICES[service].customer_charge_allowed
    credits = calculate_credits(
        tariff if permitted else None, units, discount_basis_points=discount, rounding=rounding
    )
    return {
        "service": service,
        "version": tariff.version if tariff else 0,
        "unit": SERVICES[service].unit,
        "units": str(amount(units)),
        "enabled": bool(permitted and tariff and tariff.enabled and tariff.unit_credits),
        "unit_credits": str(tariff.unit_credits or 0) if tariff else "0",
        "unit_rounding": tariff.unit_rounding if tariff else "ceil",
        "credits": credits,
        "discount_basis_points": discount,
        "consumption_rounding": rounding,
        "points_per_yuan": config.points_per_yuan if config else None,
        "free_reason": None
        if credits
        else (
            "platform_service"
            if not permitted
            else "unconfigured"
            if tariff is None
            else "disabled"
            if not tariff.enabled
            else "zero_price"
        ),
    }


def credits_from_snapshot(snapshot: dict[str, object], units: Decimal | str | int | float) -> int:
    return calculate_credits(
        Tariff(
            enabled=bool(snapshot["enabled"]),
            unit_credits=Decimal(str(snapshot["unit_credits"])),
            unit_rounding=cast(Literal["ceil", "exact"], str(snapshot["unit_rounding"])),
        ),
        units,
        discount_basis_points=int(str(snapshot["discount_basis_points"])),
        rounding=str(snapshot["consumption_rounding"]),
    )


def oral_budget_units(
    conn: BusinessConnection, *, script_text: str | None, audio_asset_id: str | None
) -> Decimal:
    if not audio_asset_id:
        return Decimal(max(1, (len(script_text or "") + 1) // 2))
    import json

    asset = conn.execute(
        "SELECT metadata_json FROM assets WHERE id=%s", (audio_asset_id,)
    ).fetchone()
    metadata = json.loads(str(asset[0] or "{}")) if asset else {}
    return amount(
        metadata.get("audio_duration_seconds")
        or metadata.get("duration_seconds")
        or metadata.get("duration_sec")
        or 0
    )
