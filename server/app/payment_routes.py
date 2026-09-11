from __future__ import annotations

import logging
import sqlite3
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.admin_write_contract import AdminWriteContract
from app.admin_write_contract import require_write_contract as _require_write_contract
from app.auth import Database
from app.control_auth import ControlUser
from app.db_portable import BusinessConnection
from app.ops_metrics import get_or_create_request_id
from app.payment_provider import (
    MerchantConfig,
    OrderQueryError,
    PaymentProvider,
    get_payment_provider,
)
from app.permissions import write_audit
from app.recharge_routes import RechargeOrderStatusResponse
from app.zpay_payments import (
    PaymentConfirmationError,
    confirm_recharge_payment,
    read_recharge_order,
    serialize_recharge_order,
)

# Import to trigger provider registration
import app.zpay_provider  # noqa: F401

router = APIRouter(prefix="/api", tags=["payments"])
logger = logging.getLogger(__name__)


def get_zpay_provider() -> PaymentProvider:
    """Dependency: get the ZPay payment provider."""
    return get_payment_provider("zpay")


ZPayProviderDep = Annotated[PaymentProvider, Depends(get_zpay_provider)]


@router.get("/payments/zpay/notify", response_class=PlainTextResponse)
def zpay_notify(
    request: Request,
    conn: Database,
    provider: ZPayProviderDep,
) -> PlainTextResponse:
    params = _unique_query_params(request)
    merchant = _load_merchant_config(conn, provider)

    # Use provider abstraction for notification verification
    verification = provider.verify_notification(params, merchant)
    if not verification.valid:
        logger.warning("ZPay callback rejected: %s", verification.error_code)
        return PlainTextResponse("failure", status_code=400)

    assert verification.merchant_order_no is not None
    assert verification.provider_trade_no is not None
    assert verification.amount_fen is not None
    assert verification.channel is not None
    assert verification.source_digest is not None

    try:
        confirm_recharge_payment(
            conn,
            merchant_order_no=verification.merchant_order_no,
            provider_trade_no=verification.provider_trade_no,
            amount_fen=verification.amount_fen,
            channel=verification.channel,
            source_digest=verification.source_digest,
            allowed_channels=merchant.allowed_channels,
        )
    except PaymentConfirmationError as exc:
        logger.warning("ZPay callback rejected: %s", exc.code)
        return PlainTextResponse("failure", status_code=exc.status_code)
    except (sqlite3.OperationalError, psycopg.errors.OperationalError) as exc:
        logger.warning("ZPay callback deferred because the payment database is busy: %s", exc)
        return PlainTextResponse("retry", status_code=503)
    return PlainTextResponse("success")


@router.get("/payments/zpay/return", response_class=HTMLResponse)
def zpay_return() -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<title>支付确认中</title></head><body><main><h1>正在确认支付</h1>"
        "<p>请返回内部系统查看充值状态。</p></main></body></html>"
    )


@router.post(
    "/control/recharge-orders/{order_no}/sync",
    response_model=RechargeOrderStatusResponse,
)
def sync_recharge_order_with_zpay(
    order_no: str,
    body: AdminWriteContract,
    request: Request,
    conn: Database,
    _actor: ControlUser,
    provider: ZPayProviderDep,
) -> RechargeOrderStatusResponse:
    """Manual single-order query with the admin write contract (A4, A2).

    The operator must send confirm + reason + an Idempotency-Key like every
    other control-plane write, and the attempt lands an ``audit_logs`` row:
    a manual sync can credit a wallet, so it must name who asked for it.
    The query itself stays naturally idempotent (PAID orders replay, the
    confirmed credit is unique-constrained), so no snapshot layer is needed.
    """
    _key, reason = _require_write_contract(request, body)
    request_id = get_or_create_request_id(request)
    write_audit(
        conn,
        actor=_actor,
        action="payment.sync",
        entity_type="recharge_order",
        entity_id=order_no,
        metadata={"reason": reason, "request_id": request_id},
    )
    local_order = read_recharge_order(conn, merchant_order_no=order_no)
    if local_order is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "RECHARGE_ORDER_NOT_FOUND",
                "message": "Recharge order does not exist.",
            },
        )
    if str(local_order["status"]) == "PAID":
        return RechargeOrderStatusResponse(**serialize_recharge_order(local_order))
    if str(local_order["status"]) != "PENDING":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RECHARGE_ORDER_NOT_SYNCABLE",
                "message": "Recharge order is not waiting for payment.",
            },
        )

    merchant = _load_merchant_config(conn, provider)
    try:
        deployment = provider.load_deployment_config()
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "ZPAY_CONFIGURATION_INVALID", "message": str(exc)},
        ) from exc
    try:
        remote_order = provider.query_order(
            merchant=merchant,
            deployment=deployment,
            merchant_order_no=order_no,
        )
    except OrderQueryError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": "ZPAY_QUERY_FAILED",
                "message": "ZPay order status could not be confirmed.",
            },
        ) from exc

    if not remote_order.paid:
        return RechargeOrderStatusResponse(**serialize_recharge_order(local_order))
    if (
        remote_order.merchant_order_no != order_no
        or remote_order.provider_trade_no is None
        or remote_order.amount_fen is None
        or remote_order.channel is None
    ):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "ZPAY_QUERY_RESPONSE_INVALID",
                "message": "ZPay paid order response is incomplete.",
            },
        )

    try:
        confirmed = confirm_recharge_payment(
            conn,
            merchant_order_no=order_no,
            provider_trade_no=remote_order.provider_trade_no,
            amount_fen=remote_order.amount_fen,
            channel=remote_order.channel,
            source_digest=remote_order.response_digest,
            allowed_channels=merchant.allowed_channels,
        )
    except PaymentConfirmationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except sqlite3.OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "PAYMENT_DATABASE_BUSY",
                "message": "Payment settlement is temporarily busy.",
            },
        ) from exc
    return RechargeOrderStatusResponse(**serialize_recharge_order(confirmed))


def _load_merchant_config(
    conn: BusinessConnection,
    provider: PaymentProvider,
) -> MerchantConfig:
    """Load merchant configuration via the provider abstraction."""
    try:
        return provider.load_merchant_config(conn)
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "ZPAY_CONFIGURATION_INVALID", "message": str(exc)},
        ) from exc


def _unique_query_params(request: Request) -> dict[str, str]:
    params: dict[str, str] = {}
    for name, value in request.query_params.multi_items():
        if name in params:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "ZPAY_DUPLICATE_PARAMETER",
                    "message": "ZPay callback contains duplicate parameters.",
                },
            )
        params[name] = value
    return params
