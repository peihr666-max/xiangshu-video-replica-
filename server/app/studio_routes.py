"""Studio workspace real counters (C6/C10a: 平台侧真实统计).

The V1.4 studio shell shows metric cards (今日成片 / 队列 / 待处理) that had
no data source — they rendered fixtures in review mode and "—" in production.
This module exposes one aggregate over the caller's visible generation tasks,
mirroring the exact visibility semantics of ``list_generation_batches``:
employees/customers see only batches of projects they own, hidden batches
stay hidden, superseded tasks never count. Nothing here invents numbers —
published/external platform metrics (播放/互动) remain absent until their
capability lands (C5 发布 / C6 外部数据源).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.auth import AuthenticatedUser, CurrentUser, Database
from app.db_portable import BusinessConnection

router = APIRouter(prefix="/api")

_BEIJING_TZ = timezone(timedelta(hours=8))

# CURRENT_TIMESTAMP writes UTC on both dialects; the text comparison below
# therefore keys on the Beijing calendar day converted back to UTC.
_CUTOFF_FORMAT = "%Y-%m-%d %H:%M:%S"


def utc_cutoff_for_beijing_day(now: datetime | None = None) -> str:
    """UTC text cutoff for the start of the current Beijing calendar day."""
    moment = now or datetime.now(tz=UTC)
    beijing_midnight = moment.astimezone(_BEIJING_TZ).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return beijing_midnight.astimezone(UTC).strftime(_CUTOFF_FORMAT)


class StudioStatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    today_completed: int
    running: int
    queued: int
    needs_attention: int
    total_completed: int


def studio_task_stats(
    conn: BusinessConnection,
    *,
    actor: CurrentUser,
    now: datetime | None = None,
) -> StudioStatsResponse:
    cutoff = utc_cutoff_for_beijing_day(now)
    clauses = [
        "task.superseded_by_task_id IS NULL",
        "NOT EXISTS ("
        "SELECT 1 FROM customer_batch_visibility AS visibility "
        "WHERE visibility.user_id = %s AND visibility.batch_id = task.batch_id)",
    ]
    # Placeholder order mirrors the SQL text: the SELECT's cutoff comes first,
    # then the visibility clause, then the optional owner clause.
    parameters: list[object] = [cutoff, actor.id]
    if actor.role in {"employee", "customer"}:
        clauses.append("project.owner_user_id = %s")
        parameters.append(actor.id)

    row = conn.execute(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN task.status = 'SUCCEEDED' AND task.completed_at >= %s
                THEN 1 ELSE 0 END), 0) AS today_completed,
            COALESCE(SUM(CASE WHEN task.status = 'RUNNING'
                THEN 1 ELSE 0 END), 0) AS running,
            COALESCE(SUM(CASE WHEN task.status IN ('PENDING', 'QUEUED')
                THEN 1 ELSE 0 END), 0) AS queued,
            COALESCE(SUM(CASE WHEN task.status = 'FAILED'
                OR task.status = 'SUBMISSION_UNCERTAIN'
                OR task.archive_status = 'ARCHIVE_FAILED'
                THEN 1 ELSE 0 END), 0) AS needs_attention,
            COALESCE(SUM(CASE WHEN task.status = 'SUCCEEDED'
                THEN 1 ELSE 0 END), 0) AS total_completed
        FROM generation_tasks AS task
        JOIN generation_batches AS batch ON batch.id = task.batch_id
        JOIN projects AS project ON project.id = batch.project_id
        WHERE {" AND ".join(clauses)}
        """,
        tuple(parameters),
    ).fetchone()
    if row is None:  # pragma: no cover - aggregate always returns one row
        return StudioStatsResponse(
            today_completed=0,
            running=0,
            queued=0,
            needs_attention=0,
            total_completed=0,
        )
    return StudioStatsResponse(
        today_completed=int(row["today_completed"]),
        running=int(row["running"]),
        queued=int(row["queued"]),
        needs_attention=int(row["needs_attention"]),
        total_completed=int(row["total_completed"]),
    )


@router.get("/studio/stats", response_model=StudioStatsResponse)
def read_studio_stats(conn: Database, actor: AuthenticatedUser) -> StudioStatsResponse:
    return studio_task_stats(conn, actor=actor)
