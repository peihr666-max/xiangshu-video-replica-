from __future__ import annotations

from app.db_portable import BusinessConnection
from app.models import GenerationTaskLease


class GenerationTaskRepository:
    def __init__(self, conn: BusinessConnection) -> None:
        self.conn = conn

    def acquire_next_lease(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> GenerationTaskLease | None:
        with self.conn:
            row = self.conn.execute(
                """
                UPDATE generation_tasks
                SET
                    status = 'RUNNING',
                    attempt = attempt + 1,
                    locked_by = %s,
                    locked_until = datetime('now', %s),
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = (
                    SELECT id
                    FROM generation_tasks
                    WHERE
                        (
                            status IN ('PENDING', 'RETRY_READY')
                            OR (status = 'RUNNING' AND locked_until <= CURRENT_TIMESTAMP)
                        )
                        AND (locked_until IS NULL OR locked_until <= CURRENT_TIMESTAMP)
                        AND (next_poll_at IS NULL OR next_poll_at <= CURRENT_TIMESTAMP)
                    ORDER BY created_at, id
                    LIMIT 1
                )
                RETURNING id, status, attempt, locked_by, locked_until
                """,
                (worker_id, f"{lease_seconds} seconds"),
            ).fetchone()

        if row is None:
            return None

        return GenerationTaskLease(
            id=str(row["id"]),
            status=str(row["status"]),
            attempt=int(row["attempt"]),
            locked_by=str(row["locked_by"]),
            locked_until=str(row["locked_until"]),
        )
