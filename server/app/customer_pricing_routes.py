"""Customer price publication and audited administrator configuration."""

import json
from uuid import uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.admin_auth_routes import AdminReader, AdminWriter
from app.admin_write_contract import AdminWriteContract, write_with_idempotency
from app.customer_fence import customer_read_transaction
from app.customer_pricing import PricingConfig, read_pricing
from app.db_pg import pg_transaction
from app.db_portable import BusinessConnection

router = APIRouter(tags=["customer-pricing"])


class PriceEntry(BaseModel):
    subject: str
    name: str
    specification: str
    unit: str
    unit_credits: int
    configurable: bool


class PricingResponse(BaseModel):
    version: int
    configured: bool
    config: PricingConfig | None
    prices: list[PriceEntry]
    recharge_rounding: str = "按支付金额换算，向下取整到整数积分"


class PricingUpdate(AdminWriteContract):
    expected_version: int = Field(ge=0)
    config: PricingConfig


def pricing_response(conn: BusinessConnection) -> PricingResponse:
    version, config = read_pricing(conn)
    prices = [
        PriceEntry(
            subject=subject,
            name=name,
            specification=spec,
            unit=unit,
            unit_credits=int(getattr(config, subject)) if config else 1,
            configurable=True,
        )
        for subject, name, spec, unit in (
            ("video_768p", "视频生成", "768P", "秒"),
            ("video_2k", "视频生成", "2K", "秒"),
            ("oral", "数字人口播", "每个生成任务", "次"),
        )
    ]
    # These integrated functions have no wallet charge. Never advertise upstream costs
    # as customer retail prices or imply a charge that the service does not perform.
    prices.extend(
        PriceEntry(
            subject=subject,
            name=name,
            specification="当前不单独扣分",
            unit="次",
            unit_credits=0,
            configurable=False,
        )
        for subject, name in (
            ("analysis", "视频解析"),
            ("first_frame", "首帧图片"),
            ("character", "人物图片"),
            ("context_ir", "提示词编译"),
        )
    )
    return PricingResponse(
        version=version, configured=config is not None, config=config, prices=prices
    )


@router.get("/api/customer/pricing", response_model=PricingResponse)
def customer_prices(request: Request, response: Response) -> PricingResponse:
    response.headers["Cache-Control"] = "no-store"
    with customer_read_transaction(request) as (conn, _):
        return pricing_response(BusinessConnection.postgres(conn))


@router.get("/api/control/settings/customer-pricing", response_model=PricingResponse)
def admin_prices(_actor: AdminReader, response: Response) -> PricingResponse:
    response.headers["Cache-Control"] = "no-store"
    with pg_transaction() as conn:
        return pricing_response(BusinessConnection.postgres(conn))


@router.put("/api/control/settings/customer-pricing", response_model=PricingResponse)
def update_prices(
    payload: PricingUpdate, request: Request, response: Response, actor: AdminWriter
) -> dict[str, object]:
    def business(conn: psycopg.Connection, request_id: str) -> dict[str, object]:
        old = conn.execute(
            "SELECT version, config_json FROM customer_credit_pricing WHERE id = 1 FOR UPDATE"
        ).fetchone()
        if old is None or int(old[0]) != payload.expected_version:
            raise HTTPException(
                409,
                detail={
                    "code": "PRICING_VERSION_CONFLICT",
                    "message": "价格已被修改，请刷新后重试。",
                },
            )
        conn.execute(
            "UPDATE customer_credit_pricing SET config_json = %s, version = version + 1, "
            "updated_at = now() WHERE id = 1",
            (payload.config.model_dump_json(),),
        )
        conn.execute(
            "INSERT INTO audit_logs (id, actor_user_id, action, entity_type, entity_id, "
            "metadata_json) VALUES (%s, %s, 'customer_pricing.update', "
            "'customer_pricing', '1', %s)",
            (
                str(uuid4()),
                actor.user_id,
                json.dumps(
                    {
                        "old": json.loads(old[1]) if old[1] else None,
                        "new": payload.config.model_dump(),
                        "version": int(old[0]) + 1,
                        "reason": payload.reason,
                        "request_id": request_id,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        return pricing_response(BusinessConnection.postgres(conn)).model_dump()

    response.headers["Cache-Control"] = "no-store"
    return write_with_idempotency(
        request,
        response,
        actor,
        payload,
        business,
        success_status=200,
        unavailable_code="PRICING_UNAVAILABLE",
        unavailable_message="积分配置暂不可用。",
    )
