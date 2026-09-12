from __future__ import annotations

import sqlite3
from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal, TypedDict, cast
from uuid import uuid4

import psycopg

from app.db_portable import BusinessConnection
from app.zpay import ALLOWED_ZPAY_CHANNELS

ZPAY_NOTIFY_BUSY_TIMEOUT_MS = 1000
RechargeStatus = Literal["PENDING", "PAID", "FAILED", "CLOSED"]


@dataclass(frozen=True)
class SettlementProviderSpec:
    """Provider-specific knobs for the single shared recharge settlement routine.

    ``confirm_recharge_payment`` is the one idempotent settlement path for every
    provider; this spec carries the only per-provider variation so the fund logic
    never forks. ``trade_no_column`` names the ``recharge_orders`` column that stores
    the provider trade reference: ZPay uses ``provider_trade_no`` while WeChat Native
    uses ``transaction_id`` (migration 083 forces a wechat_native order's
    ``provider_trade_no`` to stay NULL and its ``transaction_id`` to be NOT NULL once
    PAID). The column name is a code-controlled constant, never user input.
    """

    provider_name: str
    provider_label: str
    error_prefix: str
    channel_universe: Collection[str]
    trade_no_column: str


# WeChat Native only ever settles the wxpay channel; kept local so this fund module
# does not import the provider module (avoids an import cycle at registration time).
_WECHAT_NATIVE_CHANNEL_UNIVERSE = frozenset({"wxpay"})

ZPAY_SETTLEMENT_SPEC = SettlementProviderSpec(
    provider_name="zpay",
    provider_label="ZPay",
    error_prefix="ZPAY",
    channel_universe=ALLOWED_ZPAY_CHANNELS,
    trade_no_column="provider_trade_no",
)
WECHAT_NATIVE_SETTLEMENT_SPEC = SettlementProviderSpec(
    provider_name="wechat_native",
    provider_label="WeChat Pay",
    error_prefix="WECHAT",
    channel_universe=_WECHAT_NATIVE_CHANNEL_UNIVERSE,
    trade_no_column="transaction_id",
)

# Allowlist guard for the column identifier interpolated into settlement SQL. It only
# ever comes from the frozen specs above, but a fund path validates the identifier it
# splices rather than trusting the call site.
_SETTLEMENT_TRADE_COLUMNS = frozenset({"provider_trade_no", "transaction_id"})


class RechargeOrderData(TypedDict):
    order_no: str
    status: RechargeStatus
    amount_fen: int
    credits: int
    channel: str
    created_at: str
    paid_at: str | None


class PaymentConfirmationError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def read_recharge_order(
    conn: BusinessConnection,
    *,
    merchant_order_no: str,
) -> sqlite3.Row | None:
    return cast(
        sqlite3.Row | None,
        conn.execute(
            """
            SELECT
                id, user_id, merchant_order_no, provider, provider_trade_no, channel, status,
                amount_fen, credits, notify_digest, created_at, paid_at
            FROM recharge_orders
            WHERE merchant_order_no = %s
            """,
            (merchant_order_no,),
        ).fetchone(),
    )


def _read_settlement_order(
    conn: BusinessConnection, *, merchant_order_no: str, trade_no_column: str
) -> sqlite3.Row | None:
    """Read a recharge order for settlement, aliasing the trade reference column.

    Same projection as ``read_recharge_order`` but the provider trade reference is
    selected from ``trade_no_column`` (``provider_trade_no`` for ZPay,
    ``transaction_id`` for WeChat Native) under the fixed alias ``trade_ref`` so the
    settlement routine stays column-agnostic. The public ``read_recharge_order`` keeps
    its ZPay-shaped ``provider_trade_no`` projection for the manual-sync route.
    """
    if trade_no_column not in _SETTLEMENT_TRADE_COLUMNS:
        raise ValueError(f"Unsupported settlement trade column: {trade_no_column}")
    return cast(
        sqlite3.Row | None,
        conn.execute(
            f"""
            SELECT
                id, user_id, merchant_order_no, provider, channel, status,
                amount_fen, credits, notify_digest, created_at, paid_at,
                {trade_no_column} AS trade_ref
            FROM recharge_orders
            WHERE merchant_order_no = %s
            """,
            (merchant_order_no,),
        ).fetchone(),
    )


def serialize_recharge_order(row: sqlite3.Row) -> RechargeOrderData:
    return {
        "order_no": str(row["merchant_order_no"]),
        "status": cast(RechargeStatus, str(row["status"])),
        "amount_fen": int(row["amount_fen"]),
        "credits": int(row["credits"]),
        "channel": str(row["channel"]),
        "created_at": str(row["created_at"]),
        "paid_at": None if row["paid_at"] is None else str(row["paid_at"]),
    }


def confirm_recharge_payment(
    conn: BusinessConnection,
    *,
    merchant_order_no: str,
    provider_trade_no: str,
    amount_fen: int,
    channel: str,
    source_digest: str,
    allowed_channels: Collection[str] | None = None,
    provider_spec: SettlementProviderSpec = ZPAY_SETTLEMENT_SPEC,
) -> sqlite3.Row:
    """Idempotently settle a recharge order and credit the owner's wallet.

    ``provider_trade_no`` carries the provider's trade reference *value* regardless of
    which column stores it: ``provider_spec.trade_no_column`` names that column
    (``provider_trade_no`` for ZPay, ``transaction_id`` for WeChat Native). The default
    spec keeps every existing ZPay caller byte-identical.
    """
    spec = provider_spec
    prefix = spec.error_prefix
    label = spec.provider_label
    if not merchant_order_no or not provider_trade_no.strip():
        raise PaymentConfirmationError(
            f"{prefix}_PAYMENT_REFERENCE_INVALID",
            f"{label} order and trade numbers are required.",
            status_code=400,
        )

    conn.execute(f"PRAGMA busy_timeout = {ZPAY_NOTIFY_BUSY_TIMEOUT_MS}")
    try:
        conn.execute("BEGIN IMMEDIATE")
        order = _read_settlement_order(
            conn, merchant_order_no=merchant_order_no, trade_no_column=spec.trade_no_column
        )
        if order is None:
            raise PaymentConfirmationError(
                f"{prefix}_ORDER_NOT_FOUND",
                "Recharge order does not exist.",
                status_code=404,
            )
        if str(order["provider"]) != spec.provider_name:
            raise PaymentConfirmationError(
                f"{prefix}_PROVIDER_MISMATCH",
                f"Recharge order provider does not match {label}.",
            )
        if int(order["amount_fen"]) != amount_fen:
            raise PaymentConfirmationError(
                f"{prefix}_AMOUNT_MISMATCH",
                f"{label} amount does not match the stored recharge order.",
            )
        merchant_channels = set(allowed_channels or (str(order["channel"]),))
        if channel not in spec.channel_universe or channel not in merchant_channels:
            raise PaymentConfirmationError(
                f"{prefix}_CHANNEL_MISMATCH",
                f"{label} channel is not enabled for this merchant.",
            )

        bound_order = conn.execute(
            f"""
            SELECT merchant_order_no
            FROM recharge_orders
            WHERE {spec.trade_no_column} = %s AND merchant_order_no != %s
            """,
            (provider_trade_no, merchant_order_no),
        ).fetchone()
        if bound_order is not None:
            raise PaymentConfirmationError(
                f"{prefix}_TRADE_ALREADY_BOUND",
                f"{label} trade number is already bound to another recharge order.",
            )

        existing_trade_no = order["trade_ref"]
        if existing_trade_no is not None and str(existing_trade_no) != provider_trade_no:
            raise PaymentConfirmationError(
                f"{prefix}_TRADE_NO_MISMATCH",
                f"{label} trade number does not match the stored recharge order.",
            )
        if str(order["status"]) == "PAID":
            # Idempotent replay: the order is already settled. The rollback
            # abandons this read-only transaction (a no-op on the PG lane,
            # where the outer pg_transaction owns commit authority).
            conn.rollback()
            return order
        if str(order["status"]) not in {"PENDING", "CLOSED"}:
            raise PaymentConfirmationError(
                f"{prefix}_ORDER_NOT_SETTLEABLE",
                "Recharge order is not waiting for settlement.",
            )

        updated = conn.execute(
            f"""
            UPDATE recharge_orders
            SET status = 'PAID',
                {spec.trade_no_column} = %s,
                notify_digest = %s,
                paid_at = CURRENT_TIMESTAMP
            WHERE id = %s AND status IN ('PENDING', 'CLOSED')
            """,
            (provider_trade_no, source_digest, str(order["id"])),
        )
        if updated.rowcount != 1:
            raise PaymentConfirmationError(
                f"{prefix}_ORDER_CHANGED",
                "Recharge order changed while payment was being confirmed.",
            )

        conn.execute(
            """
            INSERT INTO wallet_transactions (
                id, user_id, type, available_delta, reserved_delta,
                recharge_order_id, task_id, billing_round, idempotency_key
            ) VALUES (%s, %s, 'CHARGE', %s, 0, %s, NULL, NULL, %s)
            """,
            (
                str(uuid4()),
                str(order["user_id"]),
                int(order["credits"]),
                str(order["id"]),
                f"{spec.provider_name}:charge:{order['id']}",
            ),
        )
        wallet = conn.execute(
            """
            UPDATE wallets
            SET available_credits = available_credits + %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = %s AND available_credits <= 2147483647 - %s
            """,
            (int(order["credits"]), str(order["user_id"]), int(order["credits"])),
        )
        if wallet.rowcount != 1:
            # Either the wallet is missing or the credit would overflow int4
            # (the T23 admin-adjustment bound, M3 review LOW). Distinguish so
            # the callback answers a final 409 instead of a retried 500.
            exists = conn.execute(
                "SELECT 1 FROM wallets WHERE user_id = %s", (str(order["user_id"]),)
            ).fetchone()
            if exists is None:
                raise PaymentConfirmationError(
                    "WALLET_NOT_FOUND",
                    "Wallet record is missing for the recharge order owner.",
                    status_code=500,
                )
            raise PaymentConfirmationError(
                "WALLET_CREDIT_OVERFLOW",
                "Wallet credit balance would overflow; settle manually.",
                status_code=409,
            )

        conn.commit()
        confirmed = _read_settlement_order(
            conn, merchant_order_no=merchant_order_no, trade_no_column=spec.trade_no_column
        )
        if confirmed is None:  # pragma: no cover - protected by the transaction above
            raise RuntimeError("confirmed recharge order disappeared")
        return confirmed
    except PaymentConfirmationError:
        conn.rollback()
        raise
    except (sqlite3.IntegrityError, psycopg.errors.UniqueViolation) as exc:
        conn.rollback()
        raise PaymentConfirmationError(
            f"{prefix}_SETTLEMENT_CONFLICT",
            "Payment settlement conflicts with an existing ledger entry.",
        ) from exc
    except Exception:
        conn.rollback()
        raise
