"""Studio workspace real counters (C6/C10a: 平台侧真实统计).

The V1.4 studio shell shows metric cards (今日成片 / 队列 / 待处理) that had
no data source — they rendered fixtures in review mode and "—" in production.
This module exposes one aggregate over the caller's visible generation tasks,
mirroring the exact visibility semantics of ``list_generation_batches``:
employees/customers see only batches of projects they own, hidden batches
stay hidden, superseded tasks never count. The C5 published counter reads the
caller's own publish_records (external 播放/互动 metrics still have no data
source until C6 lands).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.auth import AuthenticatedUser, CurrentUser, Database
from app.db_portable import BusinessConnection
from app.publish import published_total

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
    published_total: int


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
            COALESCE(SUM(CASE WHEN task.status = 'SUCCEEDED' AND task.updated_at >= %s
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
            published_total=0,
        )
    return StudioStatsResponse(
        today_completed=int(row["today_completed"]),
        running=int(row["running"]),
        queued=int(row["queued"]),
        needs_attention=int(row["needs_attention"]),
        total_completed=int(row["total_completed"]),
        published_total=published_total(
            conn, actor_id=actor.id, scoped_to_owner=actor.role in {"employee", "customer"}
        ),
    )


@router.get("/studio/stats", response_model=StudioStatsResponse)
def read_studio_stats(conn: Database, actor: AuthenticatedUser) -> StudioStatsResponse:
    return studio_task_stats(conn, actor=actor)


# ---------------------------------------------------------------------------
# C6 数据看板：窗口内成片聚合（每日桶 / 任务类型分布 / 最近成片）
# ---------------------------------------------------------------------------


class StudioAnalyticsDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: str
    completed: int


class StudioAnalyticsKindCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    completed: int


class StudioAnalyticsWorkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    batch_id: str
    project_id: str
    title: str
    creation_kind: str
    completed_at: str


class StudioAnalyticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    range_days: int
    today_completed: int
    range_completed: int
    total_completed: int
    daily: list[StudioAnalyticsDay]
    kind_breakdown: list[StudioAnalyticsKindCount]
    recent_works: list[StudioAnalyticsWorkItem]


_RECENT_WORKS_CAP = 20
_MOMENT_FORMAT = "%Y-%m-%d %H:%M:%S"


def _utc_moment(value: str) -> datetime:
    """UTC 文本时间戳（SQLite 文本 / PG 文本或 datetime 序列化）→ UTC 时刻。"""
    text = str(value)[:19].replace("T", " ")
    return datetime.strptime(text, _MOMENT_FORMAT).replace(tzinfo=UTC)


def studio_analytics(
    conn: BusinessConnection,
    *,
    actor: CurrentUser,
    days: int = 7,
    now: datetime | None = None,
) -> StudioAnalyticsResponse:
    """窗口内成片聚合；可见性与归属口径与 studio_task_stats 完全一致。

    "完成时刻"沿用 stats 的 updated_at 口径（完成即终态写 updated_at），
    按北京日界分桶；播放/互动等外部平台数据不在其中——不伪造。
    """
    days = max(1, min(int(days), 90))
    stats = studio_task_stats(conn, actor=actor, now=now)
    moment = now or datetime.now(tz=UTC)
    start_day = moment.astimezone(_BEIJING_TZ).date() - timedelta(days=days - 1)
    range_start = (
        datetime(start_day.year, start_day.month, start_day.day, tzinfo=_BEIJING_TZ)
        .astimezone(UTC)
        .strftime(_CUTOFF_FORMAT)
    )

    clauses = [
        "task.superseded_by_task_id IS NULL",
        "NOT EXISTS ("
        "SELECT 1 FROM customer_batch_visibility AS visibility "
        "WHERE visibility.user_id = %s AND visibility.batch_id = task.batch_id)",
    ]
    # 占位符顺序随 SQL 文本：可见性 → 归属（可选）→ 窗口起点。
    parameters: list[object] = [actor.id]
    if actor.role in {"employee", "customer"}:
        clauses.append("project.owner_user_id = %s")
        parameters.append(actor.id)
    clauses.append("task.updated_at >= %s")
    parameters.append(range_start)

    rows = conn.execute(
        f"""
        SELECT task.id, task.batch_id, task.status, task.updated_at,
               batch.creation_kind, batch.project_id, project.name AS project_name
        FROM generation_tasks AS task
        JOIN generation_batches AS batch ON batch.id = task.batch_id
        JOIN projects AS project ON project.id = batch.project_id
        WHERE {" AND ".join(clauses)}
        """,
        tuple(parameters),
    ).fetchall()

    range_completed = 0
    completed_by_day: dict[str, int] = {}
    completed_by_kind: dict[str, int] = {}
    works: list[tuple[datetime, str, StudioAnalyticsWorkItem]] = []
    for row in rows:
        if row["status"] != "SUCCEEDED":
            continue
        range_completed += 1
        completed_at = _utc_moment(str(row["updated_at"]))
        day_label = completed_at.astimezone(_BEIJING_TZ).date().isoformat()
        completed_by_day[day_label] = completed_by_day.get(day_label, 0) + 1
        kind = str(row["creation_kind"] or "replica")
        completed_by_kind[kind] = completed_by_kind.get(kind, 0) + 1
        works.append(
            (
                completed_at,
                str(row["id"]),
                StudioAnalyticsWorkItem(
                    task_id=str(row["id"]),
                    batch_id=str(row["batch_id"]),
                    project_id=str(row["project_id"]),
                    title=str(row["project_name"] or ""),
                    creation_kind=kind,
                    completed_at=str(row["updated_at"]),
                ),
            )
        )
    # 最近成片：完成时刻倒序，同一时刻按任务编号稳定排序，截断到看板表格容量。
    works.sort(key=lambda item: (-item[0].timestamp(), item[1]))
    daily = [
        StudioAnalyticsDay(
            day=(start_day + timedelta(days=offset)).isoformat(),
            completed=completed_by_day.get((start_day + timedelta(days=offset)).isoformat(), 0),
        )
        for offset in range(days)
    ]
    kind_breakdown = [
        StudioAnalyticsKindCount(kind=kind, completed=count)
        for kind, count in sorted(completed_by_kind.items(), key=lambda item: (-item[1], item[0]))
    ]
    return StudioAnalyticsResponse(
        range_days=days,
        today_completed=stats.today_completed,
        range_completed=range_completed,
        total_completed=stats.total_completed,
        daily=daily,
        kind_breakdown=kind_breakdown,
        recent_works=[item for _, _, item in works[:_RECENT_WORKS_CAP]],
    )


@router.get("/studio/analytics", response_model=StudioAnalyticsResponse)
def read_studio_analytics(
    conn: Database,
    actor: AuthenticatedUser,
    days: int = 7,
) -> StudioAnalyticsResponse:
    return studio_analytics(conn, actor=actor, days=days)


# ---------------------------------------------------------------------------
# C2 独立创作：跨项目「我的提示词」只读聚合
# ---------------------------------------------------------------------------


class SavedPromptListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    name: str
    prompt_text: str
    created_at: str


class SavedPromptListPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SavedPromptListItem]


@router.get("/studio/saved-prompts", response_model=SavedPromptListPage)
def read_user_saved_prompts(
    conn: Database,
    actor: AuthenticatedUser,
    limit: int = 50,
) -> SavedPromptListPage:
    """跨项目聚合作者本人的已保存提示词（versions kind='saved_prompt'）。

    独立创作页的「导入提示词」数据源：只读、仅作者本人、按时间倒序。
    存储仍复用项目域的 versions 底座（迁移 061），零新表。
    """
    if limit < 1 or limit > 100:
        limit = 50
    rows = conn.execute(
        """
        SELECT id, project_id, payload_json, created_at
        FROM versions
        WHERE kind = 'saved_prompt' AND author_user_id = %s
        ORDER BY created_at DESC, version_number DESC
        LIMIT %s
        """,
        (actor.id, limit),
    ).fetchall()
    items: list[SavedPromptListItem] = []
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        items.append(
            SavedPromptListItem(
                id=str(row["id"]),
                project_id=str(row["project_id"]),
                name=str(payload.get("name") or "未命名提示词"),
                prompt_text=str(payload.get("prompt_text") or ""),
                created_at=str(row["created_at"]),
            )
        )
    return SavedPromptListPage(items=items)
