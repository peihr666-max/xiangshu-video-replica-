from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from app.db_portable import BusinessConnection


@dataclass(frozen=True)
class GenerationRateSnapshot:
    cost_subject: str
    cost_unit_price_fen: int | None
    external_unit_price_fen: int | None
    billed_seconds: int


def _resolution_suffix(resolution: str) -> str:
    normalized = resolution.strip().lower()
    if normalized not in {"768p", "2k"}:
        raise ValueError(f"unsupported rate resolution: {resolution}")
    return normalized


def _rate(conn: BusinessConnection, subject: str) -> tuple[str, int]:
    row = conn.execute(
        "SELECT unit, unit_price_fen FROM operation_cost_rates WHERE subject = %s",
        (subject,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"operation cost rate is not configured: {subject}")
    return str(row["unit"]), int(row["unit_price_fen"])


def snapshot_generation_rates(
    conn: BusinessConnection,
    *,
    task_id: str,
    resolution: str,
    billed_seconds: int,
) -> GenerationRateSnapshot:
    """Freeze customer and upstream rates in the task creation transaction."""
    if billed_seconds < 1:
        raise ValueError("billed_seconds must be positive")
    suffix = _resolution_suffix(resolution)
    cost_subject = f"video_generation_{suffix}"
    if not getattr(conn, "is_postgres", False):
        return GenerationRateSnapshot(cost_subject, None, None, billed_seconds)
    _, cost_price = _rate(conn, cost_subject)
    _, external_price = _rate(conn, f"external_price_{suffix}")
    updated = conn.execute(
        """
        UPDATE generation_tasks
        SET cost_rate_subject_snapshot = %s,
            cost_unit_price_fen_snapshot = %s,
            external_unit_price_fen_snapshot = %s,
            billed_seconds = %s,
            cost_status = 'PENDING'
        WHERE id = %s
        """,
        (cost_subject, cost_price, external_price, billed_seconds, task_id),
    )
    if updated.rowcount != 1:
        raise RuntimeError("generation task disappeared before rate snapshot")
    begin_operation_cost(
        conn,
        source_type="generation_task",
        source_id=task_id,
        subject=cost_subject,
        generation_task_id=task_id,
        resolution=resolution.upper(),
        unit_price_fen=cost_price,
        metadata={"billed_seconds": billed_seconds},
    )
    begin_operation_cost(
        conn,
        source_type="generation_task",
        source_id=task_id,
        subject="context_ir",
        generation_task_id=task_id,
        resolution=resolution.upper(),
        metadata={"usage_source": "provider_response"},
    )
    return GenerationRateSnapshot(cost_subject, cost_price, external_price, billed_seconds)


def begin_operation_cost(
    conn: BusinessConnection,
    *,
    source_type: str,
    source_id: str,
    subject: str,
    user_id: str | None = None,
    generation_task_id: str | None = None,
    resolution: str | None = None,
    unit_price_fen: int | None = None,
    metadata: dict[str, object] | None = None,
) -> str:
    """Create the idempotent rate snapshot immediately before a provider call."""
    if not getattr(conn, "is_postgres", False):
        return ""
    unit, configured_price = _rate(conn, subject)
    price = configured_price if unit_price_fen is None else unit_price_fen
    record_id = str(uuid4())
    row = conn.execute(
        """
        INSERT INTO operation_cost_records (
            id, source_type, source_id, subject, user_id, generation_task_id,
            resolution, unit, unit_price_fen, metadata_json
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_type, source_id, subject) DO UPDATE SET
            source_id = excluded.source_id
        RETURNING id
        """,
        (
            record_id,
            source_type,
            source_id,
            subject,
            user_id,
            generation_task_id,
            resolution,
            unit,
            price,
            json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
        ),
    ).fetchone()
    assert row is not None
    return str(row["id"])


def complete_operation_cost(
    conn: BusinessConnection,
    *,
    record_id: str,
    usage_amount: float | int | None,
) -> None:
    """Complete a provider cost record; absent usage stays visibly UNKNOWN."""
    if not getattr(conn, "is_postgres", False) or not record_id:
        return
    if usage_amount is not None and usage_amount < 0:
        raise ValueError("usage_amount must be non-negative")
    usage = None if usage_amount is None else Decimal(str(usage_amount))
    status = "UNKNOWN" if usage is None else "ACTUAL"
    updated = conn.execute(
        """
        UPDATE operation_cost_records
        SET usage_amount = %s::numeric,
            cost_fen = CASE
                WHEN %s::numeric IS NULL THEN NULL
                ELSE unit_price_fen * %s::numeric
            END,
            status = %s,
            completed_at = now()
        WHERE id = %s
          AND (
              status = 'PENDING'
              OR (status = %s AND usage_amount IS NOT DISTINCT FROM %s::numeric)
          )
        """,
        (usage, usage, usage, status, record_id, status, usage),
    )
    if updated.rowcount != 1:
        existing = conn.execute(
            "SELECT status, usage_amount FROM operation_cost_records WHERE id = %s", (record_id,)
        ).fetchone()
        if existing is None:
            raise RuntimeError("operation cost record disappeared")
        raise RuntimeError(
            "operation cost record was already completed with a different result: "
            f"status={existing['status']}, usage_amount={existing['usage_amount']}"
        )


def record_video_generation_cost(
    conn: BusinessConnection,
    *,
    task_id: str,
    output_seconds: float | None,
) -> None:
    """Persist provider-reported output seconds using the frozen task rate."""
    if not getattr(conn, "is_postgres", False):
        return
    row = conn.execute(
        """
        SELECT cost_rate_subject_snapshot, cost_unit_price_fen_snapshot
        FROM generation_tasks WHERE id = %s
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("generation task does not exist")
    subject = row["cost_rate_subject_snapshot"]
    price = row["cost_unit_price_fen_snapshot"]
    if subject is None or price is None:
        # Tasks already in flight when 059 is deployed have no truthful
        # submission-time rate. Preserve any reported usage, but do not price it
        # with today's mutable rate.
        conn.execute(
            """
            UPDATE generation_tasks
            SET actual_output_seconds = %s::numeric,
                actual_cost = NULL,
                cost_status = 'UNKNOWN'
            WHERE id = %s
            """,
            (output_seconds, task_id),
        )
        return
    record_id = begin_operation_cost(
        conn,
        source_type="generation_task",
        source_id=task_id,
        subject=str(subject),
        generation_task_id=task_id,
        unit_price_fen=int(price),
    )
    complete_operation_cost(conn, record_id=record_id, usage_amount=output_seconds)
    context_ir = conn.execute(
        """
        SELECT id FROM operation_cost_records
        WHERE source_type = 'generation_task' AND source_id = %s
          AND subject = 'context_ir'
        """,
        (task_id,),
    ).fetchone()
    if context_ir is not None:
        # The verified H3 response exposes output seconds but no Context IR
        # usage flag/count. Keep it UNKNOWN instead of assuming the default.
        complete_operation_cost(conn, record_id=str(context_ir["id"]), usage_amount=None)
    conn.execute(
        """
        UPDATE generation_tasks
        SET actual_output_seconds = %s::numeric,
            actual_cost = CASE
                WHEN %s::numeric IS NULL THEN NULL
                ELSE %s::numeric * %s / 100.0
            END,
            cost_status = %s
        WHERE id = %s
        """,
        (
            output_seconds,
            output_seconds,
            output_seconds,
            int(price),
            "UNKNOWN" if output_seconds is None else "ACTUAL",
            task_id,
        ),
    )


def record_video_generation_not_called(
    conn: BusinessConnection,
    *,
    task_id: str,
) -> None:
    """Close submission snapshots at zero when no provider call was made."""
    if not getattr(conn, "is_postgres", False):
        return
    records = conn.execute(
        """
        SELECT id FROM operation_cost_records
        WHERE source_type = 'generation_task' AND source_id = %s
        """,
        (task_id,),
    ).fetchall()
    for record in records:
        complete_operation_cost(conn, record_id=str(record["id"]), usage_amount=0)
    updated = conn.execute(
        """
        UPDATE generation_tasks
        SET actual_output_seconds = 0,
            actual_cost = 0,
            cost_status = 'ACTUAL'
        WHERE id = %s
        """,
        (task_id,),
    )
    if updated.rowcount != 1:
        raise RuntimeError("generation task does not exist")
