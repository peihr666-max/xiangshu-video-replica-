from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, cast
from uuid import uuid4

from app.customer_pricing import quote_snapshot
from app.db_portable import BusinessConnection

BillingOutcome = Literal["success", "failed", "cancelled"]
TerminalTransactionType = Literal["SETTLE", "RELEASE"]
OralProviderOutcome = Literal["SUCCEEDED", "FAILED", "CANCELLED", "NOT_FOUND"]
OralChargeEvidence = Literal["CHARGED", "NOT_CHARGED"]


class InternalBillingError(RuntimeError):
    """Base error for wallet invariants that callers must not silently ignore."""


class InsufficientCreditsError(InternalBillingError):
    pass


class BillingInvariantError(InternalBillingError):
    pass


def _record_source(conn: BusinessConnection, key: str, snapshot: str) -> None:
    if conn.is_postgres:
        conn.execute(
            "UPDATE wallet_transactions SET api_key_id = %s, auth_source = %s, "
            "pricing_snapshot_json = %s WHERE idempotency_key = %s",
            (conn.api_key_id, conn.auth_source, snapshot, key),
        )


def _copy_source(
    conn: BusinessConnection,
    key: str,
    *,
    task_id: str | None = None,
    oral_task_id: str | None = None,
    billing_round: int,
) -> None:
    if conn.is_postgres:
        conn.execute(
            "UPDATE wallet_transactions AS terminal SET api_key_id = reserve.api_key_id, "
            "auth_source = reserve.auth_source, pricing_snapshot_json = "
            "reserve.pricing_snapshot_json "
            "FROM wallet_transactions AS reserve WHERE terminal.idempotency_key = %s "
            "AND reserve.type = 'RESERVE' AND reserve.billing_round = %s "
            "AND (reserve.task_id = %s OR reserve.oral_task_id = %s) "
            "AND terminal.user_id = reserve.user_id",
            (key, billing_round, task_id, oral_task_id),
        )


@dataclass(frozen=True)
class BillingFinalization:
    task_id: str
    billing_round: int | None
    transaction_type: TerminalTransactionType | None
    # W11 按秒计费：本轮流水的秒数（旧数据/历史任务为 1）。
    seconds: int = 1


@dataclass(frozen=True)
class DanglingBillingReservation:
    task_kind: Literal["generation", "oral"]
    task_id: str
    user_id: str
    billing_round: int
    reservation_id: str
    outcome: BillingOutcome


@dataclass(frozen=True)
class DanglingBillingReconciliation:
    scanned: int
    settled: int
    released: int
    failed: int


def find_dangling_billing_reservations(
    conn: BusinessConnection,
    *,
    limit: int = 100,
) -> list[DanglingBillingReservation]:
    """RESERVE rows whose task reached a terminal state without a terminal row.

    BILL-03: a dangling RESERVE holds one credit of the user's wallet
    reserved forever. The task is already terminal (archived success or
    failed/cancelled), so finalization is safe; the terminal write was lost
    when a fenced worker transaction rolled back after the task UPDATE was
    visible. SUBMISSION_UNCERTAIN and un-archived tasks are NOT terminal and
    must keep their reservation until reconciliation decides.
    """
    rows = conn.execute(
        """
        SELECT * FROM (
            SELECT 'generation' AS task_kind, wt.id AS reservation_id,
                   wt.task_id, wt.user_id, wt.billing_round, task.status, wt.created_at
            FROM wallet_transactions AS wt
            JOIN generation_tasks AS task ON task.id = wt.task_id
            WHERE wt.type = 'RESERVE'
              AND NOT EXISTS (
                  SELECT 1 FROM wallet_transactions AS terminal
                  WHERE terminal.task_id = wt.task_id
                    AND terminal.billing_round = wt.billing_round
                    AND terminal.type IN ('SETTLE', 'RELEASE')
              )
              AND (
                  (task.status = 'SUCCEEDED'
                   AND task.archive_status IN ('ARCHIVED', 'DIRECT'))
                  OR task.status IN ('FAILED', 'CANCELLED')
              )
            UNION ALL
            SELECT 'oral' AS task_kind, wt.id AS reservation_id,
                   wt.oral_task_id AS task_id, wt.user_id, wt.billing_round,
                   task.status, wt.created_at
            FROM wallet_transactions AS wt
            JOIN oral_tasks AS task ON task.id = wt.oral_task_id
            WHERE wt.type = 'RESERVE'
              AND NOT EXISTS (
                  SELECT 1 FROM wallet_transactions AS terminal
                  WHERE terminal.oral_task_id = wt.oral_task_id
                    AND terminal.billing_round = wt.billing_round
                    AND terminal.type IN ('SETTLE', 'RELEASE')
              )
              AND (
                  (task.status = 'SUCCEEDED' AND task.result_asset_id IS NOT NULL)
                  OR (
                      task.status IN ('FAILED', 'CANCELLED')
                      AND task.provider_charge_state IN ('NOT_SUBMITTED', 'NOT_CHARGED')
                  )
              )
        ) AS candidates
        ORDER BY created_at
        LIMIT %s
        """,
        (limit,),
    ).fetchall()
    return [
        DanglingBillingReservation(
            task_kind=cast(Literal["generation", "oral"], str(row["task_kind"])),
            task_id=str(row["task_id"]),
            user_id=str(row["user_id"]),
            billing_round=int(row["billing_round"]),
            reservation_id=str(row["reservation_id"]),
            outcome=(
                "success"
                if str(row["status"]) == "SUCCEEDED"
                else "cancelled"
                if str(row["status"]) == "CANCELLED"
                else "failed"
            ),
        )
        for row in rows
    ]


def reserve_internal_billing(
    conn: BusinessConnection,
    *,
    user_id: str,
    task_id: str,
    billing_round: int | None = None,
    seconds: int = 1,
) -> int:
    """Reserve the requested seconds inside the caller's transaction.

    W11 按秒计费：seconds 来自任务提交档位快照（billed_seconds）；
    默认 1 保持旧调用与历史任务语义（每轮 1 条 = 1 秒）。"""
    if seconds < 1:
        raise BillingInvariantError("reserved seconds must be positive")
    if conn.is_postgres:
        conn.execute("SELECT id FROM generation_tasks WHERE id = %s FOR UPDATE", (task_id,))
    task = conn.execute(
        """
        SELECT batch.created_by_user_id, task.prompt_snapshot_json
        FROM generation_tasks AS task
        JOIN generation_batches AS batch ON batch.id = task.batch_id
        WHERE task.id = %s
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise BillingInvariantError("generation task does not exist")
    if str(task["created_by_user_id"]) != user_id:
        raise BillingInvariantError("wallet owner does not match generation task owner")

    latest = conn.execute(
        """
        SELECT billing_round
        FROM wallet_transactions
        WHERE task_id = %s AND type = 'RESERVE'
        ORDER BY billing_round DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    latest_round = int(latest["billing_round"]) if latest is not None else None

    if billing_round is None:
        if latest_round is None:
            billing_round = 1
        else:
            terminal = conn.execute(
                """
                SELECT 1
                FROM wallet_transactions
                WHERE task_id = %s AND billing_round = %s
                  AND type IN ('SETTLE', 'RELEASE')
                """,
                (task_id, latest_round),
            ).fetchone()
            if terminal is None:
                return latest_round
            billing_round = latest_round + 1
    if billing_round < 1:
        raise BillingInvariantError("billing round must be positive")

    existing = conn.execute(
        """
        SELECT user_id
        FROM wallet_transactions
        WHERE task_id = %s AND billing_round = %s AND type = 'RESERVE'
        """,
        (task_id, billing_round),
    ).fetchone()
    if existing is not None:
        if str(existing["user_id"]) != user_id:
            raise BillingInvariantError("existing reservation belongs to another wallet")
        return billing_round
    if latest_round is not None and billing_round <= latest_round:
        raise BillingInvariantError("billing round cannot move backwards")
    if latest_round is not None:
        if billing_round != latest_round + 1:
            raise BillingInvariantError("billing rounds must be sequential")
        previous_terminal = conn.execute(
            """
            SELECT 1
            FROM wallet_transactions
            WHERE task_id = %s AND billing_round = %s
              AND type IN ('SETTLE', 'RELEASE')
            """,
            (task_id, latest_round),
        ).fetchone()
        if previous_terminal is None:
            raise BillingInvariantError("previous billing round is still active")

    payload = json.loads(str(task["prompt_snapshot_json"] or "{}"))
    resolution = str(payload.get("resolution", "768P")).upper()
    seconds, price_snapshot = quote_snapshot(
        conn, "video_2k" if resolution == "2K" else "video_768p", seconds
    )
    cursor = conn.execute(
        """
        UPDATE wallets
        SET
            available_credits = available_credits - %s,
            reserved_credits = reserved_credits + %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = %s AND available_credits >= %s
        """,
        (seconds, seconds, user_id, seconds),
    )
    if cursor.rowcount != 1:
        wallet = conn.execute(
            "SELECT 1 FROM wallets WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        if wallet is None:
            raise BillingInvariantError("wallet does not exist")
        raise InsufficientCreditsError(
            f"available credits are insufficient: need {seconds} credits"
        )

    conn.execute(
        """
        INSERT INTO wallet_transactions (
            id, user_id, type, available_delta, reserved_delta,
            task_id, billing_round, idempotency_key
        ) VALUES (%s, %s, 'RESERVE', %s, %s, %s, %s, %s)
        """,
        (
            str(uuid4()),
            user_id,
            -seconds,
            seconds,
            task_id,
            billing_round,
            f"reserve:{task_id}:{billing_round}",
        ),
    )
    _record_source(conn, f"reserve:{task_id}:{billing_round}", price_snapshot)
    return billing_round


def reserve_oral_billing(
    conn: BusinessConnection,
    *,
    user_id: str,
    oral_task_id: str,
    billing_round: int = 1,
) -> int:
    """Reserve the configured oral credits in the caller transaction."""
    if conn.is_postgres:
        _lock_oral_capacity_row(conn)
        conn.execute("SELECT id FROM oral_tasks WHERE id = %s FOR UPDATE", (oral_task_id,))
    task = conn.execute(
        "SELECT owner_user_id FROM oral_tasks WHERE id = %s", (oral_task_id,)
    ).fetchone()
    if task is None:
        raise BillingInvariantError("oral task does not exist")
    if str(task["owner_user_id"]) != user_id:
        raise BillingInvariantError("wallet owner does not match oral task owner")
    if billing_round < 1:
        raise BillingInvariantError("billing round must be positive")

    existing = conn.execute(
        """
        SELECT user_id FROM wallet_transactions
        WHERE oral_task_id = %s AND billing_round = %s AND type = 'RESERVE'
        """,
        (oral_task_id, billing_round),
    ).fetchone()
    if existing is not None:
        if str(existing["user_id"]) != user_id:
            raise BillingInvariantError("existing reservation belongs to another wallet")
        return billing_round

    credits, price_snapshot = quote_snapshot(conn, "oral", 1)
    cursor = conn.execute(
        """
        UPDATE wallets
        SET available_credits = available_credits - %s,
            reserved_credits = reserved_credits + %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = %s AND available_credits >= %s
        """,
        (credits, credits, user_id, credits),
    )
    if cursor.rowcount != 1:
        wallet = conn.execute("SELECT 1 FROM wallets WHERE user_id = %s", (user_id,)).fetchone()
        if wallet is None:
            raise BillingInvariantError("wallet does not exist")
        raise InsufficientCreditsError("available credits are insufficient")

    conn.execute(
        """
        INSERT INTO wallet_transactions (
            id, user_id, type, available_delta, reserved_delta,
            oral_task_id, billing_round, idempotency_key
        ) VALUES (%s, %s, 'RESERVE', %s, %s, %s, %s, %s)
        """,
        (
            str(uuid4()),
            user_id,
            -credits,
            credits,
            oral_task_id,
            billing_round,
            f"oral-reserve:{oral_task_id}:{billing_round}",
        ),
    )
    _record_source(conn, f"oral-reserve:{oral_task_id}:{billing_round}", price_snapshot)
    conn.execute(
        "UPDATE oral_tasks SET billing_round = %s WHERE id = %s",
        (billing_round, oral_task_id),
    )
    return billing_round


def release_oral_queue_slot(
    conn: BusinessConnection,
    *,
    oral_task_id: str,
) -> None:
    """Release an oral submit slot exactly once in the caller transaction."""
    _lock_oral_capacity_row(conn)
    released = conn.execute(
        """
        UPDATE oral_tasks
        SET queue_slot_acquired = 0, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s AND queue_slot_acquired = 1
        RETURNING owner_user_id
        """,
        (oral_task_id,),
    ).fetchone()
    if released is None or not conn.is_postgres:
        return
    conn.execute(
        """
        UPDATE user_queue_cursors
        SET running_tasks_count = GREATEST(running_tasks_count - 1, 0),
            last_dispatched_at = now()
        WHERE user_id = %s
        """,
        (str(released["owner_user_id"]),),
    )


def finalize_oral_billing(
    conn: BusinessConnection,
    *,
    oral_task_id: str,
) -> BillingFinalization:
    """Settle archived success or release an explicitly failed/cancelled oral task."""
    if conn.is_postgres:
        _lock_oral_capacity_row(conn)
        conn.execute("SELECT id FROM oral_tasks WHERE id = %s FOR UPDATE", (oral_task_id,))
    task = conn.execute(
        """
        SELECT task.status, task.owner_user_id, task.result_asset_id,
               task.provider_charge_state, asset.storage_uri
        FROM oral_tasks AS task
        LEFT JOIN assets AS asset ON asset.id = task.result_asset_id
        WHERE task.id = %s
        """,
        (oral_task_id,),
    ).fetchone()
    if task is None:
        raise BillingInvariantError("oral task does not exist")
    reservation = conn.execute(
        """
        SELECT user_id, billing_round, reserved_delta FROM wallet_transactions
        WHERE oral_task_id = %s AND type = 'RESERVE'
        ORDER BY billing_round DESC LIMIT 1
        """,
        (oral_task_id,),
    ).fetchone()
    if reservation is None:
        return BillingFinalization(task_id=oral_task_id, billing_round=None, transaction_type=None)
    user_id = str(reservation["user_id"])
    billing_round = int(reservation["billing_round"])
    credits = int(reservation["reserved_delta"])
    if user_id != str(task["owner_user_id"]):
        raise BillingInvariantError("reservation owner does not match oral task owner")
    existing = conn.execute(
        """
        SELECT type FROM wallet_transactions
        WHERE oral_task_id = %s AND billing_round = %s
          AND type IN ('SETTLE', 'RELEASE')
        """,
        (oral_task_id, billing_round),
    ).fetchone()
    if existing is not None:
        return BillingFinalization(
            task_id=oral_task_id,
            billing_round=billing_round,
            transaction_type=cast(TerminalTransactionType, str(existing["type"])),
        )

    status = str(task["status"])
    if status == "SUCCEEDED":
        if task["result_asset_id"] is None or not str(task["storage_uri"] or "").strip():
            raise BillingInvariantError("successful oral billing requires an archived asset")
        transaction_type: TerminalTransactionType = "SETTLE"
        available_delta = 0
    elif status in {"FAILED", "CANCELLED"} and str(task["provider_charge_state"]) in {
        "NOT_SUBMITTED",
        "NOT_CHARGED",
    }:
        transaction_type = "RELEASE"
        available_delta = credits
    else:
        raise BillingInvariantError("oral reservation must remain frozen for non-terminal status")

    cursor = conn.execute(
        """
        UPDATE wallets
        SET available_credits = available_credits + %s,
            reserved_credits = reserved_credits - %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = %s AND reserved_credits >= %s
        """,
        (available_delta, credits, user_id, credits),
    )
    if cursor.rowcount != 1:
        raise BillingInvariantError("reserved wallet credit is missing")
    conn.execute(
        """
        INSERT INTO wallet_transactions (
            id, user_id, type, available_delta, reserved_delta,
            oral_task_id, billing_round, idempotency_key
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            str(uuid4()),
            user_id,
            transaction_type,
            available_delta,
            -credits,
            oral_task_id,
            billing_round,
            f"oral-{transaction_type.lower()}:{oral_task_id}:{billing_round}",
        ),
    )
    _copy_source(
        conn,
        f"oral-{transaction_type.lower()}:{oral_task_id}:{billing_round}",
        oral_task_id=oral_task_id,
        billing_round=billing_round,
    )
    release_oral_queue_slot(conn, oral_task_id=oral_task_id)
    return BillingFinalization(
        task_id=oral_task_id,
        billing_round=billing_round,
        transaction_type=transaction_type,
    )


def reconcile_oral_billing_by_evidence(
    conn: BusinessConnection,
    *,
    oral_task_id: str,
    reconciliation_operation_id: str,
    provider_outcome: OralProviderOutcome,
    provider_charge_state: OralChargeEvidence,
    resolution: TerminalTransactionType,
    reason: str,
    evidence_asset_id: str,
    evidence_sha256: str,
) -> BillingFinalization:
    """Apply an operator-evidenced terminal decision without guessing locally."""
    _lock_oral_capacity_row(conn)
    if (resolution, provider_charge_state) not in {
        ("SETTLE", "CHARGED"),
        ("RELEASE", "NOT_CHARGED"),
    }:
        raise BillingInvariantError("billing resolution contradicts provider charge evidence")
    if provider_outcome not in {"SUCCEEDED", "FAILED", "CANCELLED", "NOT_FOUND"}:
        raise BillingInvariantError("provider outcome is unsupported")

    request_hash = hashlib.sha256(
        json.dumps(
            {
                "oral_task_id": oral_task_id,
                "provider_outcome": provider_outcome,
                "provider_charge_state": provider_charge_state,
                "resolution": resolution,
                "reason": reason,
                "evidence_asset_id": evidence_asset_id,
                "evidence_sha256": evidence_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    conn.execute(
        """
        INSERT INTO oral_billing_reconciliation_operations (
            id, oral_task_id, request_hash, evidence_asset_id,
            evidence_sha256, resolution
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (
            reconciliation_operation_id,
            oral_task_id,
            request_hash,
            evidence_asset_id,
            evidence_sha256,
            resolution,
        ),
    )
    operation = conn.execute(
        """
        SELECT oral_task_id, request_hash, evidence_asset_id, evidence_sha256,
               resolution, applied_at
        FROM oral_billing_reconciliation_operations
        WHERE id = %s
        FOR UPDATE
        """,
        (reconciliation_operation_id,),
    ).fetchone()
    if operation is None or (
        str(operation["oral_task_id"]) != oral_task_id
        or str(operation["request_hash"]) != request_hash
        or str(operation["evidence_asset_id"]) != evidence_asset_id
        or str(operation["evidence_sha256"]) != evidence_sha256
        or str(operation["resolution"]) != resolution
    ):
        raise BillingInvariantError("billing reconciliation operation conflicts")

    task = conn.execute(
        """
        SELECT owner_user_id, provider_charge_state, status
        FROM oral_tasks
        WHERE id = %s
        FOR UPDATE
        """,
        (oral_task_id,),
    ).fetchone()
    if task is None:
        raise BillingInvariantError("oral task does not exist")
    reservation = conn.execute(
        """
        SELECT user_id, billing_round, reserved_delta
        FROM wallet_transactions
        WHERE oral_task_id = %s AND type = 'RESERVE'
        ORDER BY billing_round DESC LIMIT 1
        """,
        (oral_task_id,),
    ).fetchone()
    if reservation is None:
        raise BillingInvariantError("oral task has no billing reservation")
    user_id = str(reservation["user_id"])
    billing_round = int(reservation["billing_round"])
    if user_id != str(task["owner_user_id"]):
        raise BillingInvariantError("reservation owner does not match oral task owner")

    existing = conn.execute(
        """
        SELECT type FROM wallet_transactions
        WHERE oral_task_id = %s AND billing_round = %s
          AND type IN ('SETTLE', 'RELEASE')
        """,
        (oral_task_id, billing_round),
    ).fetchone()
    if existing is not None:
        existing_type = cast(TerminalTransactionType, str(existing["type"]))
        if existing_type != resolution or operation["applied_at"] is None:
            raise BillingInvariantError("oral billing already has a different operation")
        return BillingFinalization(oral_task_id, billing_round, existing_type)

    if str(task["status"]) not in {"SUBMISSION_UNCERTAIN", "FAILED", "CANCELLED"}:
        raise BillingInvariantError("oral task does not require manual billing attention")
    if str(task["provider_charge_state"]) not in {"UNKNOWN", "CHARGED"}:
        raise BillingInvariantError("oral task does not require manual billing reconciliation")
    credits = int(reservation["reserved_delta"])
    available_delta = credits if resolution == "RELEASE" else 0
    wallet = conn.execute(
        """
        UPDATE wallets
        SET available_credits = available_credits + %s,
            reserved_credits = reserved_credits - %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = %s AND reserved_credits >= %s
        """,
        (available_delta, credits, user_id, credits),
    )
    if wallet.rowcount != 1:
        raise BillingInvariantError("reserved wallet credit is missing")
    conn.execute(
        """
        INSERT INTO wallet_transactions (
            id, user_id, type, available_delta, reserved_delta,
            oral_task_id, billing_round, idempotency_key
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            str(uuid4()),
            user_id,
            resolution,
            available_delta,
            -credits,
            oral_task_id,
            billing_round,
            f"oral-manual-{resolution.lower()}:{oral_task_id}:{billing_round}",
        ),
    )
    _copy_source(
        conn,
        f"oral-manual-{resolution.lower()}:{oral_task_id}:{billing_round}",
        oral_task_id=oral_task_id,
        billing_round=billing_round,
    )
    conn.execute(
        """
        UPDATE oral_tasks
        SET provider_charge_state = %s,
            status = CASE WHEN %s = 'RELEASE' THEN 'FAILED' ELSE status END,
            submission_state = CASE
                WHEN %s = 'RELEASE' THEN 'FAILED' ELSE submission_state
            END,
            error_message = CASE
                WHEN %s = 'RELEASE' THEN '供应商凭证确认未扣费，已人工释放预留次数'
                ELSE error_message
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            provider_charge_state,
            resolution,
            resolution,
            resolution,
            oral_task_id,
        ),
    )
    applied = conn.execute(
        """
        UPDATE oral_billing_reconciliation_operations
        SET applied_at = CURRENT_TIMESTAMP
        WHERE id = %s AND applied_at IS NULL
        """,
        (reconciliation_operation_id,),
    )
    if applied.rowcount != 1:
        raise BillingInvariantError("billing reconciliation operation was already applied")
    release_oral_queue_slot(conn, oral_task_id=oral_task_id)
    return BillingFinalization(oral_task_id, billing_round, resolution)


def _lock_oral_capacity_row(conn: BusinessConnection) -> None:
    """Match worker lock order without importing generation into billing."""
    if conn.is_postgres:
        row = conn.execute("SELECT id FROM runtime_settings WHERE id = 1 FOR UPDATE").fetchone()
        if row is None:
            raise BillingInvariantError("runtime settings capacity row is missing")
        return
    updated = conn.execute("UPDATE runtime_settings SET id = id WHERE id = 1")
    if updated.rowcount != 1:
        raise BillingInvariantError("runtime settings capacity row is missing")


def finalize_internal_billing(
    conn: BusinessConnection,
    *,
    task_id: str,
    outcome: BillingOutcome,
) -> BillingFinalization:
    """Settle or release the latest reserved round in the caller's transaction."""
    if conn.is_postgres:
        conn.execute("SELECT id FROM generation_tasks WHERE id = %s FOR UPDATE", (task_id,))
    task = conn.execute(
        """
        SELECT
            task.status,
            task.archive_status,
            task.result_asset_id,
            task.provider_result_url,
            task.provider,
            batch.created_by_user_id,
            asset.storage_uri
        FROM generation_tasks AS task
        JOIN generation_batches AS batch ON batch.id = task.batch_id
        LEFT JOIN assets AS asset ON asset.id = task.result_asset_id
        WHERE task.id = %s
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise BillingInvariantError("generation task does not exist")

    reservation = conn.execute(
        """
        SELECT user_id, billing_round, reserved_delta
        FROM wallet_transactions
        WHERE task_id = %s AND type = 'RESERVE'
        ORDER BY billing_round DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    if reservation is None:
        # Tasks created before internal billing was enabled remain historical
        # records. They must not mutate a wallet retroactively.
        return BillingFinalization(task_id=task_id, billing_round=None, transaction_type=None)

    user_id = str(reservation["user_id"])
    billing_round = int(reservation["billing_round"])
    # W11：本轮预留的秒数（旧行固定 1）。
    seconds = max(1, int(reservation["reserved_delta"]))
    if user_id != str(task["created_by_user_id"]):
        raise BillingInvariantError("reservation owner does not match generation task owner")

    existing = conn.execute(
        """
        SELECT type
        FROM wallet_transactions
        WHERE task_id = %s AND billing_round = %s
          AND type IN ('SETTLE', 'RELEASE')
        """,
        (task_id, billing_round),
    ).fetchone()
    if existing is not None:
        return BillingFinalization(
            task_id=task_id,
            billing_round=billing_round,
            transaction_type=cast(TerminalTransactionType, str(existing["type"])),
        )

    if outcome == "success":
        storage_uri = task["storage_uri"]
        archived_result = (
            str(task["archive_status"]) == "ARCHIVED"
            and task["result_asset_id"] is not None
            and storage_uri is not None
            and str(storage_uri).strip()
            and (str(task["provider"]) != "metaso" or str(storage_uri).startswith("cos://"))
        )
        direct_result = (
            str(task["archive_status"]) == "DIRECT"
            and isinstance(task["provider_result_url"], str)
            and bool(str(task["provider_result_url"]).strip())
        )
        if str(task["status"]) != "SUCCEEDED" or not (archived_result or direct_result):
            raise BillingInvariantError("successful billing requires a deliverable result")
        transaction_type: TerminalTransactionType = "SETTLE"
        available_delta = 0
    else:
        if str(task["status"]) not in {"FAILED", "CANCELLED"}:
            raise BillingInvariantError("released billing requires a failed or cancelled task")
        transaction_type = "RELEASE"
        available_delta = seconds

    cursor = conn.execute(
        """
        UPDATE wallets
        SET
            available_credits = available_credits + %s,
            reserved_credits = reserved_credits - %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = %s AND reserved_credits >= %s
        """,
        (available_delta, seconds, user_id, seconds),
    )
    if cursor.rowcount != 1:
        raise BillingInvariantError("reserved wallet credit is missing")

    conn.execute(
        """
        INSERT INTO wallet_transactions (
            id, user_id, type, available_delta, reserved_delta,
            task_id, billing_round, idempotency_key
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            str(uuid4()),
            user_id,
            transaction_type,
            available_delta,
            -seconds,
            task_id,
            billing_round,
            f"{transaction_type.lower()}:{task_id}:{billing_round}",
        ),
    )
    _copy_source(
        conn,
        f"{transaction_type.lower()}:{task_id}:{billing_round}",
        task_id=task_id,
        billing_round=billing_round,
    )
    return BillingFinalization(
        task_id=task_id,
        billing_round=billing_round,
        transaction_type=transaction_type,
        seconds=seconds,
    )


def reconcile_dangling_billing_reservations(
    conn: BusinessConnection,
    *,
    limit: int = 100,
) -> DanglingBillingReconciliation:
    """Finalize safe terminal reservations that lost their terminal ledger row.

    The detector deliberately excludes active and ``SUBMISSION_UNCERTAIN``
    tasks. Each candidate is revalidated by ``finalize_internal_billing`` in
    the caller-owned transaction, so a stale sweep cannot settle an
    unarchived result or release a non-terminal task.
    """
    candidates = find_dangling_billing_reservations(conn, limit=limit)
    settled = 0
    released = 0
    failed = 0
    for candidate in candidates:
        conn.execute("SAVEPOINT billing_reconcile_item")
        try:
            if candidate.task_kind == "oral":
                result = finalize_oral_billing(conn, oral_task_id=candidate.task_id)
            else:
                result = finalize_internal_billing(
                    conn,
                    task_id=candidate.task_id,
                    outcome=candidate.outcome,
                )
        except Exception:
            conn.execute("ROLLBACK TO SAVEPOINT billing_reconcile_item")
            conn.execute("RELEASE SAVEPOINT billing_reconcile_item")
            failed += 1
            continue
        conn.execute("RELEASE SAVEPOINT billing_reconcile_item")
        if result.transaction_type == "SETTLE":
            settled += 1
        elif result.transaction_type == "RELEASE":
            released += 1
    return DanglingBillingReconciliation(
        scanned=len(candidates),
        settled=settled,
        released=released,
        failed=failed,
    )
