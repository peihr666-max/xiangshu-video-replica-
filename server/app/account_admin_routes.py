"""Native administrator account operations; never the legacy proxy identity."""

import json
from dataclasses import asdict
from typing import cast
from uuid import uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel

from app.admin_auth_routes import AdminReader, AdminWriter
from app.admin_write_contract import (
    AdminWriteContract,
    require_write_contract,
    write_with_idempotency,
)
from app.api_key_routes import ApiKeyRecordResponse
from app.api_key_service import list_api_keys
from app.auth import CurrentUser, Role
from app.control_routes import (
    BillingSettingsSnapshot,
    BillingSettingsUpdate,
    ControlRechargeOrderPage,
    ControlWalletTransactionPage,
    MaskedZPaySettings,
    OrderStatus,
    TransactionType,
    ZPaySettingsUpdate,
    _update_control_billing_settings_business,
    _update_control_zpay_settings_business,
    list_recharge_orders,
    list_wallet_transactions,
)
from app.db_pg import pg_transaction
from app.db_portable import BusinessConnection
from app.payment_provider import PaymentProviderError, get_payment_provider
from app.settings import SettingsRepository
from app.zpay_payments import (
    WECHAT_NATIVE_SETTLEMENT_SPEC,
    ZPAY_SETTLEMENT_SPEC,
    PaymentConfirmationError,
    confirm_recharge_payment,
    read_recharge_order,
    serialize_recharge_order,
)

router = APIRouter(prefix="/api/control", tags=["account-operations"])


@router.post("/customers/{user_id}/recharge-orders/{order_no}/reconcile")
def reconcile_order(
    user_id: str,
    order_no: str,
    body: AdminWriteContract,
    request: Request,
    response: Response,
    actor: AdminWriter,
) -> dict[str, object]:
    require_write_contract(request, body)
    response.headers["Cache-Control"] = "no-store"
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        original = read_recharge_order(conn, merchant_order_no=order_no)
        if original is None or str(original["user_id"]) != user_id:
            raise HTTPException(404, detail="该账号下的充值订单不存在。")
        provider_name = str(original["provider"])
        if provider_name not in {"zpay", "wechat_native"}:
            raise HTTPException(409, detail="此订单不支持支付网关补发。")
        paid = str(original["status"]) == "PAID"
        gateway = get_payment_provider(provider_name)
        try:
            merchant = None if paid else gateway.load_merchant_config(conn)
        except ValueError as exc:
            raise HTTPException(503, detail="支付渠道配置暂不可用。") from exc
    # No database connection or wallet lock is held during the external request.
    remote = None
    if merchant is not None:
        try:
            remote = gateway.query_order(
                merchant=merchant,
                deployment=gateway.load_deployment_config(),
                merchant_order_no=order_no,
            )
        except (ValueError, PaymentProviderError) as exc:
            raise HTTPException(502, detail="支付网关暂时无法核验，请稍后重试。") from exc
        if not remote.paid:
            raise HTTPException(409, detail="网关尚未确认支付成功，未增加积分。")
        if (
            remote.merchant_order_no != order_no
            or not remote.provider_trade_no
            or remote.amount_fen is None
            or remote.channel is None
        ):
            raise HTTPException(502, detail="网关支付凭证不完整，未增加积分。")

    def business(raw: psycopg.Connection, request_id: str) -> dict[str, object]:
        # Recheck authority after the potentially slow provider call and hold it until commit.
        authority = raw.execute(
            "SELECT s.id FROM admin_sessions s JOIN users u ON u.id = s.actor_user_id "
            "WHERE s.id = %s AND u.id = %s AND s.revoked_at IS NULL "
            "AND s.auth_method = 'password' AND u.is_active = 1 AND "
            "u.role IN ('admin', 'operator') "
            "AND s.expires_at::timestamptz > clock_timestamp() FOR SHARE OF s, u",
            (actor.session_id, actor.user_id),
        ).fetchone()
        if authority is None:
            raise HTTPException(403, detail="管理员权限已变化，请重新登录。")
        conn = BusinessConnection.postgres(raw)
        current = read_recharge_order(conn, merchant_order_no=order_no)
        if (
            current is None
            or str(current["user_id"]) != user_id
            or str(current["provider"]) != provider_name
        ):
            raise HTTPException(409, detail="充值订单归属已变化。")
        if remote is not None and merchant is not None:
            try:
                current = confirm_recharge_payment(
                    conn,
                    merchant_order_no=order_no,
                    provider_trade_no=remote.provider_trade_no or "",
                    amount_fen=remote.amount_fen or 0,
                    channel=remote.channel or "",
                    source_digest=remote.response_digest,
                    allowed_channels=merchant.allowed_channels,
                    provider_spec=ZPAY_SETTLEMENT_SPEC
                    if provider_name == "zpay"
                    else WECHAT_NATIVE_SETTLEMENT_SPEC,
                )
            except PaymentConfirmationError as exc:
                raise HTTPException(
                    exc.status_code, detail={"code": exc.code, "message": str(exc)}
                ) from exc
        if str(current["status"]) != "PAID":
            raise HTTPException(409, detail="订单未确认支付成功。")
        conn.execute(
            "INSERT INTO audit_logs (id, actor_user_id, action, "
            "entity_type, entity_id, metadata_json) "
            "VALUES (%s, %s, 'account_payment.reconcile', 'recharge_order', %s, %s)",
            (
                str(uuid4()),
                actor.user_id,
                str(current["id"]),
                json.dumps({"reason": body.reason, "request_id": request_id, "user_id": user_id}),
            ),
        )
        return dict(serialize_recharge_order(current))

    return write_with_idempotency(request, response, actor, body, business, success_status=200)


class AccountSummary(BaseModel):
    user_id: str
    available_credits: int
    reserved_credits: int
    total_consumed_credits: int
    software_consumed_credits: int
    other_consumed_credits: int
    tokens: list[ApiKeyRecordResponse]


@router.get("/customers/{user_id}/account-summary", response_model=AccountSummary)
def account_summary(user_id: str, _actor: AdminReader, response: Response) -> AccountSummary:
    response.headers["Cache-Control"] = "no-store"
    with pg_transaction() as conn:
        wallet = conn.execute(
            "SELECT w.available_credits, w.reserved_credits FROM wallets w JOIN users u "
            "ON u.id = w.user_id WHERE u.id = %s AND (u.role = 'customer' OR EXISTS "
            "(SELECT 1 FROM activation_code_activations a WHERE a.user_id = u.id))",
            (user_id,),
        ).fetchone()
        if wallet is None:
            raise HTTPException(404, detail="客户账号不存在。")
        spend = conn.execute(
            "SELECT COALESCE(SUM(-reserved_delta), 0), "
            "COALESCE(SUM(-reserved_delta) FILTER (WHERE auth_source = 'session'), 0), "
            "COALESCE(SUM(-reserved_delta) FILTER (WHERE api_key_id IS NULL "
            "AND auth_source IS DISTINCT FROM 'session'), 0) "
            "FROM wallet_transactions WHERE user_id = %s AND type = 'SETTLE'",
            (user_id,),
        ).fetchone()
        assert spend is not None
        return AccountSummary(
            user_id=user_id,
            available_credits=wallet[0],
            reserved_credits=wallet[1],
            total_consumed_credits=spend[0],
            software_consumed_credits=spend[1],
            other_consumed_credits=spend[2],
            tokens=[
                ApiKeyRecordResponse.model_validate(asdict(k))
                for k in list_api_keys(conn, user_id=user_id)
            ],
        )


class CustomerPaymentSettings(BaseModel):
    billing: BillingSettingsSnapshot
    zpay: MaskedZPaySettings


@router.get("/settings/customer-payments", response_model=CustomerPaymentSettings)
def payment_settings(_actor: AdminReader, response: Response) -> CustomerPaymentSettings:
    response.headers["Cache-Control"] = "no-store"
    with pg_transaction() as conn:
        repo = SettingsRepository(BusinessConnection.postgres(conn))
        return CustomerPaymentSettings(
            billing=BillingSettingsSnapshot(**repo.read_billing_settings()),
            zpay=MaskedZPaySettings(**repo.read_zpay_config()),
        )


@router.patch("/settings/customer-payments/billing", response_model=BillingSettingsSnapshot)
def save_billing(
    body: BillingSettingsUpdate, request: Request, response: Response, actor: AdminWriter
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return write_with_idempotency(
        request,
        response,
        actor,
        body,
        lambda conn, request_id: _update_control_billing_settings_business(
            BusinessConnection.postgres(conn),
            actor=CurrentUser(
                id=actor.user_id,
                username=actor.username,
                display_name=actor.display_name,
                role=cast(Role, actor.role),
            ),
            payload=body,
            request_id=request_id,
        ),
        success_status=200,
    )


@router.patch("/settings/customer-payments/zpay", response_model=MaskedZPaySettings)
def save_zpay(
    body: ZPaySettingsUpdate, request: Request, response: Response, actor: AdminWriter
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return write_with_idempotency(
        request,
        response,
        actor,
        body,
        lambda conn, request_id: _update_control_zpay_settings_business(
            BusinessConnection.postgres(conn),
            actor=CurrentUser(
                id=actor.user_id,
                username=actor.username,
                display_name=actor.display_name,
                role=cast(Role, actor.role),
            ),
            payload=body,
            request_id=request_id,
        ),
        success_status=200,
    )


@router.get("/customers/{user_id}/recharge-orders", response_model=ControlRechargeOrderPage)
def account_recharge_orders(
    user_id: str,
    actor: AdminReader,
    response: Response,
    status: OrderStatus | None = None,
    username: str | None = None,
    channel: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ControlRechargeOrderPage:
    response.headers["Cache-Control"] = "no-store"
    with pg_transaction() as raw:
        return list_recharge_orders(
            conn=BusinessConnection.postgres(raw),
            _actor=CurrentUser(
                id=actor.user_id,
                username=actor.username,
                display_name=actor.display_name,
                role=cast(Role, actor.role),
            ),
            user_id=user_id,
            status=status,
            username=username,
            channel=channel,
            created_from=created_from,
            created_to=created_to,
            limit=limit,
            offset=offset,
        )


@router.get("/customers/{user_id}/wallet-transactions", response_model=ControlWalletTransactionPage)
def account_wallet_transactions(
    user_id: str,
    actor: AdminReader,
    response: Response,
    type: TransactionType | None = None,
    username: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ControlWalletTransactionPage:
    response.headers["Cache-Control"] = "no-store"
    with pg_transaction() as raw:
        return list_wallet_transactions(
            conn=BusinessConnection.postgres(raw),
            _actor=CurrentUser(
                id=actor.user_id,
                username=actor.username,
                display_name=actor.display_name,
                role=cast(Role, actor.role),
            ),
            user_id=user_id,
            type=type,
            username=username,
            created_from=created_from,
            created_to=created_to,
            limit=limit,
            offset=offset,
        )
