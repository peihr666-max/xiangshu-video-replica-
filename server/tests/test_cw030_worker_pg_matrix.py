"""CW-030 — per-worker-class PG claim / lease / recovery matrix.

Every formally supported task class is verified on the real PostgreSQL lane
through the exact claim/complete/fail functions the production PG worker loop
(``run_pg_worker_once``) uses, in fenced ``pg_transaction`` blocks:

- 独立任务 (independent ``generation_batches`` riding the shared generation
  machinery): 2-worker double claim, expired lease → SUBMISSION_UNCERTAIN +
  slot release, late duplicate uncertainty cannot disturb a replacement task,
  worker settle with exactly-once billing, crash after claim leaves a durable
  RUNNING that never blind-resubmits;
- 首帧/联系表 (the shared ``image_tasks`` state machine): double claim,
  expired lease quarantined to ``IMAGE_TASK_LEASE_EXPIRED`` or resumed from a
  recoverable checkpoint, stale-lease failure is a no-op, and the
  submission fence splits SUBMISSION_UNCERTAIN from retryable FAILED;
- 人物图 (``character_generation_tasks``): SKIP LOCKED double-claim guard,
  expired lease with attempts left is recoverable, exhausted attempts fail
  closed (this class has no SUBMISSION_UNCERTAIN semantics — registered as
  the CW-002 known limitation);
- 源帧 (``source_frame_tasks``): double claim is exclusive, an expired task
  fails closed to manual recovery (never auto-retried), and the degraded
  worker round processes source frames locally when quality settings are
  missing;
- 文案改写 (``script_rewrite_tasks``): exclusivity, expired submission
  quarantined without recalling the provider, a 504 after submission lands in
  SUBMISSION_UNCERTAIN, a stale-lease completion cannot overwrite recovered
  state, and the worker settles on PG;
- ASR (``script_from_audio_tasks``): exclusivity, expired pre-submission
  leases reset to PENDING while expired in-flight submissions quarantine,
  provider failure is terminal without blind resubmit, and the durable audio
  receipt survives a retry;
- 混合队列/两设备: mixed H3 + independent rounds rotate within the frozen
  per-user ``running<=1`` slot and the ``_FAIR_QUEUE_MAX_ROUNDS`` bound, and a
  second device cannot grow the same user's running slot from 1 to 2.

Per CW-002's signed scope the fair queue covers H3/独立/口播; 图片/文案/ASR
have no fairness rotation and this suite registers (not fakes) that limit.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any, cast

# Set HMAC key before importing app modules (audit writers require it).
os.environ.setdefault(
    "VIDEO_REPLICA_ADMIN_SESSION_HMAC_KEY",
    "test-key-for-cw030-worker-matrix-tests-minimum-48-bytes-long-1",
)

import psycopg
import pytest
from fastapi import HTTPException
from pg_test_kit import (
    create_test_database,
    drop_test_database,
    require_pg_or_explicit_skip,
    upgrade_test_database_to_head,
)
from psycopg.rows import dict_row

from app.character_image_generation import acquire_character_generation_task
from app.db_pg import DATABASE_URL_ENV, close_pg_pool, pg_transaction
from app.db_portable import BusinessConnection
from app.generation import (
    acquire_generation_task_lease,
    mark_expired_active_leases_needing_attention,
    mark_task_submission_uncertain,
)
from app.generation_worker import run_pg_worker_once, run_pg_worker_round
from app.image_tasks import (
    acquire_character_sheet_task,
    acquire_first_frame_task,
    fail_image_task,
)
from app.script_from_audio import (
    acquire_script_from_audio_task,
    fail_script_from_audio_task,
)
from app.script_rewrite import (
    _script_rewrite_request_hash,
    acquire_script_rewrite_task,
    complete_script_rewrite_task,
    fail_script_rewrite_task,
    mark_script_rewrite_submission_started,
    prepare_script_rewrite_task,
)
from app.source_frames import ExtractedSourceFrame, acquire_source_frame_task
from app.storage import FakeStorageAdapter

CW030_DB_NAME = "cw030_worker_matrix_test"

DEFAULT_DSN = "postgresql://testuser:testpass@localhost:5433/customer_v3_test"

_MATRIX_CLEANUP_ORDER = (
    # Reset only this isolated fixture, including new immutable billing descendants.
    "wallet_transactions",
    "generation_task_operations",
    "external_call_logs",
    "operation_cost_records",
    "generation_tasks",
    "generation_batches",
    "script_rewrite_tasks",
    "script_from_audio_tasks",
    "source_frame_tasks",
    "first_frame_tasks",
    "character_sheet_tasks",
    "character_generation_tasks",
    "character_assets",
    "character_versions",
    "character_personas",
    "person_identities",
    "user_queue_cursors",
    "audit_logs",
    "assets",
    "versions",
    "projects",
    "internal_access_tokens",
    "recharge_orders",
    "wallets",
    "users",
    "runtime_settings",
)

_REQUEST_SNAPSHOT = '{"output_duration_seconds": 10, "resolution": "768P"}'
_PROMPT_SNAPSHOT = '{"prompt_text": "a cat", "first_frame_uri": "cos://bucket/ff.jpg"}'

_SHA_A = "a" * 64
_FIRST_FRAME_CHECKPOINT_JSON = (
    '{"execution": {"provider": "fake-image", "model": "fake-image-model"},'
    ' "checkpoint": {"schema_version": 1, "candidates": ['
    '{"index": 0, "storage_uri": "fake://generation-results/candidate-0.png",'
    ' "sha256": "' + _SHA_A + '", "size_bytes": 9, "content_type": "image/png",'
    ' "quality": {"passed": true}}]}}'
)


def _pg_dsn() -> str:
    return os.environ.get("TEST_POSTGRESQL_URL", DEFAULT_DSN)


@pytest.fixture(scope="module")
def matrix_dsn() -> Iterator[str]:
    require_pg_or_explicit_skip(_pg_dsn())
    dsn = create_test_database(CW030_DB_NAME)
    upgrade_test_database_to_head(dsn)
    try:
        yield dsn
    finally:
        drop_test_database(CW030_DB_NAME)


@pytest.fixture()
def pg_state(matrix_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    close_pg_pool()
    monkeypatch.setenv(DATABASE_URL_ENV, matrix_dsn)
    monkeypatch.delenv("VIDEO_REPLICA_CUSTOMER_PRODUCTION", raising=False)
    monkeypatch.delenv("VIDEO_REPLICA_FAKE_H3_OUTCOME", raising=False)
    yield matrix_dsn
    close_pg_pool()


# ---------------------------------------------------------------------------
# Raw-seed helpers (worker-identical rows, no route machinery)
# ---------------------------------------------------------------------------


def _exec(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> None:
    with psycopg.connect(dsn, autocommit=True) as pg:
        pg.execute(sql, params)


def _rows(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as pg:
        found = pg.execute(sql, params).fetchall()
        return [dict(row) for row in found]


def _one(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> Any:
    with psycopg.connect(dsn, autocommit=True) as pg:
        row = pg.execute(sql, params).fetchone()
        return None if row is None else row[0]


def _truncate(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as pg:
        pg.execute("SET session_replication_role = replica")
        pg.execute("TRUNCATE " + ",".join(_MATRIX_CLEANUP_ORDER) + " CASCADE")
        pg.execute("SET session_replication_role = DEFAULT")


def _seed_base(dsn: str, *, fair_queue: bool = True) -> None:
    _truncate(dsn)
    _exec(
        dsn,
        "INSERT INTO runtime_settings ("
        " id, max_generation_count_per_batch, max_concurrent_h3_tasks,"
        " internal_base_unit_price_fen, min_recharge_fen, recharge_step_fen,"
        " fair_queue_enabled"
        ") VALUES (1, 4, 100, 1000, 10000, 1000, %s)",
        (fair_queue,),
    )
    _exec(
        dsn,
        "INSERT INTO users (id, username, display_name, role) VALUES"
        " ('u1', 'u1', 'User One', 'employee'),"
        " ('u2', 'u2', 'User Two', 'user'),"
        " ('u3', 'u3', 'User Three', 'user')",
    )
    _exec(
        dsn,
        "INSERT INTO wallets (user_id, available_credits, reserved_credits) VALUES"
        " ('u1', 1000, 0), ('u2', 1000, 0), ('u3', 1000, 0)",
    )
    _exec(
        dsn,
        "INSERT INTO projects (id, name, owner_user_id) VALUES ('proj-1', 'CW030 Matrix', 'u1')",
    )
    _exec(
        dsn,
        "INSERT INTO versions (id, project_id, kind, version_number, payload_json) VALUES"
        " ('pv-1', 'proj-1', 'video', 1, '{}')",
    )
    _exec(
        dsn,
        "INSERT INTO person_identities (id, owner_user_id, display_name,"
        " authorization_status) VALUES ('identity-owned', 'u1', '张工', 'AUTHORIZED')",
    )


def _seed_generation_task(
    dsn: str,
    *,
    task_id: str,
    user_id: str,
    batch_id: str | None = None,
    creation_kind: str = "replica",
    project_id: str | None = "proj-1",
    provider: str = "fake_h3",
    status: str = "PENDING",
) -> str:
    batch = batch_id or f"batch-{task_id}"
    _exec(
        dsn,
        "INSERT INTO generation_batches ("
        " id, project_id, created_by_user_id, idempotency_key,"
        " request_hash, request_snapshot_json, status, creation_kind"
        ") VALUES (%s, %s, %s, %s, %s, %s, 'QUEUED', %s)",
        (
            batch,
            project_id,
            user_id,
            f"ik-{batch}",
            f"rh-{batch}",
            _REQUEST_SNAPSHOT,
            creation_kind,
        ),
    )
    _exec(
        dsn,
        "INSERT INTO generation_tasks ("
        " id, batch_id, generation_mode, provider, model,"
        " status, archive_status, quality_status,"
        " prompt_version_id, prompt_snapshot_json, next_poll_at"
        ") VALUES (%s, %s, 'I2V', %s, 'h3', %s, 'PENDING', 'PENDING', 'pv-1', %s, NULL)",
        (task_id, batch, provider, status, _PROMPT_SNAPSHOT),
    )
    _exec(
        dsn,
        "INSERT INTO user_queue_cursors (user_id, last_dispatched_at, running_tasks_count)"
        " VALUES (%s, now(), 0) ON CONFLICT (user_id) DO NOTHING",
        (user_id,),
    )
    return task_id


def _acquire(dsn: str, worker_id: str) -> Any:
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        return acquire_generation_task_lease(conn, worker_id=worker_id)


def _cursor_count(dsn: str, user_id: str) -> int:
    value = _one(
        dsn,
        "SELECT running_tasks_count FROM user_queue_cursors WHERE user_id = %s",
        (user_id,),
    )
    return -1 if value is None else int(value)


def _task_status(dsn: str, table: str, task_id: str) -> str | None:
    return cast(str | None, _one(dsn, f"SELECT status FROM {table} WHERE id = %s", (task_id,)))


def _run_worker(worker_id: str, *, max_tasks: int | None = 1) -> int:
    storage = FakeStorageAdapter(provider="cos", bucket="bucket")
    return run_pg_worker_once(worker_id=worker_id, storage=storage, max_tasks=max_tasks)


# ---------------------------------------------------------------------------
# A. 独立任务 — shared generation machinery, independent-kind seeds
# ---------------------------------------------------------------------------


def test_independent_double_claim_is_exclusive(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_generation_task(
        pg_state, task_id="ind-1", user_id="u1", creation_kind="independent", project_id=None
    )
    first = _acquire(pg_state, "worker-a")
    assert first is not None
    assert str(first["id"]) == "ind-1"
    second = _acquire(pg_state, "worker-b")
    assert second is None, "the same independent task must never be claimed twice"
    assert _cursor_count(pg_state, "u1") == 1


def test_independent_expired_lease_marks_uncertain_and_releases_slot(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_generation_task(
        pg_state, task_id="ind-1", user_id="u1", creation_kind="independent", project_id=None
    )
    lease = _acquire(pg_state, "worker-a")
    assert lease is not None
    _exec(
        pg_state,
        "UPDATE generation_tasks SET locked_until = now() - interval '5 minutes' WHERE id = %s",
        ("ind-1",),
    )
    with pg_transaction() as raw:
        mark_expired_active_leases_needing_attention(BusinessConnection.postgres(raw))
    assert _cursor_count(pg_state, "u1") == 0
    assert _task_status(pg_state, "generation_tasks", "ind-1") == "SUBMISSION_UNCERTAIN"
    replacement = _acquire(pg_state, "worker-b")
    assert replacement is None, "an uncertain task must not be silently resubmitted"


def test_independent_late_uncertainty_cannot_disturb_replacement(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_generation_task(
        pg_state, task_id="ind-1", user_id="u1", creation_kind="independent", project_id=None
    )
    lease = _acquire(pg_state, "worker-a")
    assert lease is not None
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        mark_task_submission_uncertain(
            conn,
            task_id="ind-1",
            message="POST timed out",
            provider_task_id="prov-ind-1",
        )
    assert _cursor_count(pg_state, "u1") == 0
    # A replacement task takes the freed slot; a late duplicate uncertainty
    # signal for the old task must not touch the replacement's slot.
    _seed_generation_task(
        pg_state, task_id="ind-2", user_id="u1", creation_kind="independent", project_id=None
    )
    replacement = _acquire(pg_state, "worker-b")
    assert replacement is not None
    assert _cursor_count(pg_state, "u1") == 1
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        mark_task_submission_uncertain(
            conn,
            task_id="ind-1",
            message="duplicate late signal",
            provider_task_id="prov-ind-1",
        )
    assert _cursor_count(pg_state, "u1") == 1, "late duplicate uncertainty must not double-count"
    assert _task_status(pg_state, "generation_tasks", "ind-2") == "SUBMITTING"


def test_independent_worker_settles_exactly_once_on_pg(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_generation_task(
        pg_state, task_id="ind-1", user_id="u1", creation_kind="independent", project_id=None
    )
    # The creation route commits the RESERVE (billing_round 1) before the
    # task is claimable; the worker owns the SETTLE side of the round.
    _exec(
        pg_state,
        "UPDATE wallets SET available_credits = 999, reserved_credits = 1 WHERE user_id = 'u1'",
    )
    _exec(
        pg_state,
        "INSERT INTO wallet_transactions ("
        " id, user_id, type, available_delta, reserved_delta, task_id,"
        " billing_round, idempotency_key"
        ") VALUES ('wt-ind-1-r1', 'u1', 'RESERVE', -1, 1, 'ind-1', 1, 'reserve:ind-1:1')",
    )
    processed = _run_worker("cw030-independent-worker")
    final = _rows(
        pg_state,
        "SELECT status, error_code, error_message_redacted FROM generation_tasks"
        " WHERE id = 'ind-1'",
    )[0]
    assert processed == 1, final
    assert final["status"] == "SUCCEEDED", final
    ledger = _rows(
        pg_state,
        "SELECT type, billing_round FROM wallet_transactions WHERE task_id = 'ind-1'"
        " ORDER BY billing_round, type",
    )
    assert [(str(r["type"]), int(r["billing_round"])) for r in ledger] == [
        ("RESERVE", 1),
        ("SETTLE", 1),
    ], ledger
    assert _one(pg_state, "SELECT reserved_credits FROM wallets WHERE user_id = 'u1'") == 0


def test_independent_crash_after_claim_never_blind_resubmits(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_generation_task(
        pg_state, task_id="ind-1", user_id="u1", creation_kind="independent", project_id=None
    )
    lease = _acquire(pg_state, "worker-a")
    assert lease is not None
    # The claim transaction committed the durable SUBMITTING lease; a crash
    # here must never silently re-fire the paid provider from a fresh worker.
    assert _task_status(pg_state, "generation_tasks", "ind-1") == "SUBMITTING"
    _exec(
        pg_state,
        "UPDATE generation_tasks SET locked_until = now() - interval '5 minutes' WHERE id = %s",
        ("ind-1",),
    )
    processed = _run_worker("restart-worker")
    assert processed == 0, "the restart must not blind-resubmit the uncertain task"
    assert _task_status(pg_state, "generation_tasks", "ind-1") == "SUBMISSION_UNCERTAIN"


# ---------------------------------------------------------------------------
# B/C. 首帧 + 联系表 — the shared image_tasks state machine
# ---------------------------------------------------------------------------


def _seed_image_task(
    dsn: str,
    *,
    table: str,
    task_id: str,
    user_id: str = "u1",
    status: str = "PENDING",
    result_json: str | None = None,
    attempt: int = 0,
) -> None:
    locked_by = user_id if status == "RUNNING" else None
    if table == "first_frame_tasks":
        _exec(
            dsn,
            "INSERT INTO first_frame_tasks ("
            " id, created_by_user_id, project_id, idempotency_key, request_hash,"
            " request_json, result_json, status, attempt, locked_by"
            ") VALUES (%s, %s, 'proj-1', %s, %s, '{}', %s, %s, %s, %s)",
            (
                task_id,
                user_id,
                f"ik-{task_id}",
                f"rh-{task_id}",
                result_json,
                status,
                attempt,
                locked_by,
            ),
        )
    else:
        _exec(
            dsn,
            "INSERT INTO character_sheet_tasks ("
            " id, created_by_user_id, identity_id, idempotency_key, request_hash,"
            " request_json, result_json, status, attempt, locked_by, operation,"
            " source_storage_uri, source_content_type, source_sha256, source_size_bytes"
            ") VALUES (%s, %s, 'identity-owned', %s, %s, '{}', %s, %s, %s, %s, 'CREATE',"
            " 'fake://sf-uploads/identity-owned.png', 'image/png', '" + "f" * 64 + "', 9)",
            (
                task_id,
                user_id,
                f"ik-{task_id}",
                f"rh-{task_id}",
                result_json,
                status,
                attempt,
                locked_by,
            ),
        )


def _expire_running_lease(dsn: str, table: str, task_id: str) -> None:
    _exec(
        dsn,
        f"UPDATE {table} SET locked_until = now() - interval '5 minutes' WHERE id = %s",
        (task_id,),
    )


def test_first_frame_double_claim_is_exclusive(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_image_task(pg_state, table="first_frame_tasks", task_id="ff-1")
    with pg_transaction() as raw:
        first = acquire_first_frame_task(BusinessConnection.postgres(raw), worker_id="worker-a")
    assert first is not None
    assert first.id == "ff-1"
    with pg_transaction() as raw:
        second = acquire_first_frame_task(BusinessConnection.postgres(raw), worker_id="worker-b")
    assert second is None
    assert _task_status(pg_state, "first_frame_tasks", "ff-1") == "RUNNING"


def test_first_frame_expired_without_checkpoint_is_quarantined(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_image_task(
        pg_state,
        table="first_frame_tasks",
        task_id="ff-1",
        status="RUNNING",
        attempt=3,
    )
    _expire_running_lease(pg_state, "first_frame_tasks", "ff-1")
    # attempt>=3: no checkpoint resume, no retry — quarantine to UNCERTAIN.
    with pg_transaction() as raw:
        lease = acquire_first_frame_task(BusinessConnection.postgres(raw), worker_id="worker-a")
    assert lease is None
    row = _rows(
        pg_state,
        "SELECT status, error_code FROM first_frame_tasks WHERE id = 'ff-1'",
    )[0]
    assert row["status"] == "SUBMISSION_UNCERTAIN"
    assert row["error_code"] == "IMAGE_TASK_LEASE_EXPIRED"


def test_first_frame_expired_with_checkpoint_resumes(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_image_task(
        pg_state,
        table="first_frame_tasks",
        task_id="ff-1",
        status="RUNNING",
        attempt=1,
        result_json=_FIRST_FRAME_CHECKPOINT_JSON,
    )
    _expire_running_lease(pg_state, "first_frame_tasks", "ff-1")
    with pg_transaction() as raw:
        lease = acquire_first_frame_task(BusinessConnection.postgres(raw), worker_id="worker-a")
    # The resume marker is transient (the claim clears error_code); the
    # resume is proven by attempt 1->2 under the new owner — a
    # non-recoverable task would have been quarantined at attempt 1.
    row = _rows(
        pg_state,
        "SELECT status, attempt, locked_by FROM first_frame_tasks WHERE id = 'ff-1'",
    )[0]
    assert row["status"] == "RUNNING"
    assert row["locked_by"] == "worker-a"
    assert int(row["attempt"]) == 2
    assert lease is not None and lease.id == "ff-1"


def test_first_frame_stale_lease_failure_is_a_noop(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_image_task(pg_state, table="first_frame_tasks", task_id="ff-1")
    with pg_transaction() as raw:
        lease = acquire_first_frame_task(BusinessConnection.postgres(raw), worker_id="worker-a")
    assert lease is not None
    # The lease is lost (quarantined underneath the stale worker).
    _exec(
        pg_state,
        "UPDATE first_frame_tasks SET status = 'SUBMISSION_UNCERTAIN',"
        " error_code = 'IMAGE_TASK_LEASE_EXPIRED', locked_by = NULL,"
        " locked_until = NULL WHERE id = 'ff-1'",
    )
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        fail_image_task(
            conn,
            table="first_frame_tasks",
            lease=lease,
            cause=RuntimeError("late provider failure from the stale worker"),
            submission_started=True,
        )
    row = _rows(pg_state, "SELECT status, error_code FROM first_frame_tasks WHERE id = 'ff-1'")[0]
    assert row["status"] == "SUBMISSION_UNCERTAIN", (
        "the stale worker's late failure must not overwrite the recovered state"
    )
    assert row["error_code"] == "IMAGE_TASK_LEASE_EXPIRED"


@pytest.mark.parametrize("action", ["renew", "provider", "checkpoint", "prepare"])
def test_first_frame_stale_attempt_cannot_change_checkpoint_or_lease(pg_state: str, action: str):
    from app.image_tasks import (
        _require_owned_task,
        record_image_task_provider,
        renew_image_task_lease,
        save_first_frame_task_checkpoint,
    )

    _seed_base(pg_state)
    _seed_image_task(pg_state, table="first_frame_tasks", task_id="late-image")
    with pg_transaction() as raw:
        lease = acquire_first_frame_task(BusinessConnection.postgres(raw), worker_id="reused-id")
    assert lease is not None
    _exec(pg_state, "UPDATE first_frame_tasks SET attempt=attempt+1 WHERE id='late-image'")
    with pytest.raises(RuntimeError, match="lease was lost"):
        with pg_transaction() as raw:
            conn = BusinessConnection.postgres(raw)
            if action == "renew":
                renew_image_task_lease(conn, table="first_frame_tasks", lease=lease)
            elif action == "provider":
                record_image_task_provider(
                    conn, table="first_frame_tasks", lease=lease, provider="old", model="old"
                )
            elif action == "checkpoint":
                save_first_frame_task_checkpoint(conn, lease=lease, candidates=[])
            else:
                _require_owned_task(conn, "first_frame_tasks", lease)


def test_first_frame_submission_fence_splits_uncertain_and_retryable(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_image_task(pg_state, table="first_frame_tasks", task_id="ff-1")
    with pg_transaction() as raw:
        lease = acquire_first_frame_task(BusinessConnection.postgres(raw), worker_id="worker-a")
    assert lease is not None
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        fail_image_task(
            conn,
            table="first_frame_tasks",
            lease=lease,
            cause=RuntimeError("provider transport dropped after submission"),
            submission_started=True,
        )
    row = _rows(pg_state, "SELECT status, retryable FROM first_frame_tasks WHERE id = 'ff-1'")[0]
    assert row["status"] == "SUBMISSION_UNCERTAIN"
    assert int(row["retryable"]) == 0

    _seed_image_task(pg_state, table="first_frame_tasks", task_id="ff-2")
    with pg_transaction() as raw:
        lease2 = acquire_first_frame_task(BusinessConnection.postgres(raw), worker_id="worker-a")
    assert lease2 is not None
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        fail_image_task(
            conn,
            table="first_frame_tasks",
            lease=lease2,
            cause=RuntimeError("storage unavailable before any provider call"),
            submission_started=False,
        )
    row2 = _rows(pg_state, "SELECT status, retryable FROM first_frame_tasks WHERE id = 'ff-2'")[0]
    assert row2["status"] == "FAILED"
    assert int(row2["retryable"]) == 1


def test_character_sheet_double_claim_and_expiry(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_image_task(pg_state, table="character_sheet_tasks", task_id="cs-1")
    with pg_transaction() as raw:
        first = acquire_character_sheet_task(BusinessConnection.postgres(raw), worker_id="worker-a")
    assert first is not None
    with pg_transaction() as raw:
        second = acquire_character_sheet_task(
            BusinessConnection.postgres(raw), worker_id="worker-b"
        )
    assert second is None
    # Expire the RUNNING lease; the next acquire quarantines it (no checkpoint
    # resume exists for contact sheets).
    _expire_running_lease(pg_state, "character_sheet_tasks", "cs-1")
    with pg_transaction() as raw:
        third = acquire_character_sheet_task(BusinessConnection.postgres(raw), worker_id="worker-b")
    assert third is None
    row = _rows(
        pg_state,
        "SELECT status, error_code FROM character_sheet_tasks WHERE id = 'cs-1'",
    )[0]
    assert row["status"] == "SUBMISSION_UNCERTAIN"
    assert row["error_code"] == "IMAGE_TASK_LEASE_EXPIRED"


# ---------------------------------------------------------------------------
# D. 人物图 — character_generation_tasks (no SUBMISSION_UNCERTAIN semantics:
# registered CW-002 limitation; failure closes through attempt exhaustion)
# ---------------------------------------------------------------------------


def _seed_character_domain(dsn: str) -> None:
    _exec(
        dsn,
        "INSERT INTO person_identities (id, owner_user_id, display_name,"
        " authorization_status) VALUES ('pi-1', 'u1', '张工', 'AUTHORIZED')",
    )
    _exec(
        dsn,
        "INSERT INTO character_personas (id, identity_id, name) VALUES ('cp-1', 'pi-1', '张工')",
    )
    _exec(
        dsn,
        "INSERT INTO assets ("
        " id, project_id, kind, storage_uri, sha256, size_bytes, content_type,"
        " created_by_user_id"
        ") VALUES ('char-src', NULL, 'material_image',"
        " 'fake://generation-results/char-src.png', '" + "c" * 64 + "', 9, 'image/png', 'u1')"
        " ON CONFLICT (id) DO NOTHING",
    )
    _exec(
        dsn,
        "INSERT INTO character_versions ("
        " id, persona_id, version_number, status, source_asset_id, source_sha256,"
        " persona_snapshot_json, provider, model, generation_params_json,"
        " template_version, template_hash, required_view_types_json, created_by"
        ") VALUES ('cv-1', 'cp-1', 1, 'PUBLISHED', 'char-src', '"
        + "d" * 64
        + "', '{}', 'fake-image', 'fake-image-model', '{}', 'v1', '"
        + "e" * 64
        + "', '[]', 'u1')",
    )


def _seed_character_task(
    dsn: str,
    *,
    task_id: str,
    status: str = "PENDING",
    attempt: int = 0,
    max_attempts: int = 3,
) -> None:
    _exec(
        dsn,
        "INSERT INTO character_generation_tasks ("
        " id, character_version_id, view_type, provider, model, idempotency_key,"
        " request_hash, candidate_number, status, attempt, max_attempts, locked_by,"
        " created_by"
        ") VALUES (%s, 'cv-1', 'FRONT_FACE', 'fake-image', 'fake-image-model', %s, %s, 1,"
        " %s, %s, %s, %s, 'u1')",
        (
            task_id,
            f"ik-{task_id}",
            f"rh-{task_id}",
            status,
            attempt,
            max_attempts,
            "worker-a" if status == "RUNNING" else None,
        ),
    )


def test_character_generation_skip_locked_double_claim(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_character_domain(pg_state)
    _seed_character_task(pg_state, task_id="cg-1")
    with pg_transaction() as raw:
        first = acquire_character_generation_task(
            BusinessConnection.postgres(raw), worker_id="worker-a"
        )
    assert first is not None
    assert str(first["id"]) == "cg-1"
    with pg_transaction() as raw:
        second = acquire_character_generation_task(
            BusinessConnection.postgres(raw), worker_id="worker-b"
        )
    assert second is None


def test_character_generation_expired_lease_with_attempts_left_recovers(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_character_domain(pg_state)
    _seed_character_task(pg_state, task_id="cg-1", status="RUNNING", attempt=1)
    _expire_running_lease(pg_state, "character_generation_tasks", "cg-1")
    with pg_transaction() as raw:
        reacquired = acquire_character_generation_task(
            BusinessConnection.postgres(raw), worker_id="worker-b"
        )
    assert reacquired is not None
    row = _rows(
        pg_state,
        "SELECT status, attempt, locked_by FROM character_generation_tasks WHERE id = 'cg-1'",
    )[0]
    assert row["status"] == "RUNNING"
    assert row["locked_by"] == "worker-b"
    assert int(row["attempt"]) == 2


def test_character_generation_exhausted_attempts_fail_closed(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_character_domain(pg_state)
    _seed_character_task(pg_state, task_id="cg-1", status="RUNNING", attempt=3, max_attempts=3)
    _expire_running_lease(pg_state, "character_generation_tasks", "cg-1")
    with pg_transaction() as raw:
        lease = acquire_character_generation_task(
            BusinessConnection.postgres(raw), worker_id="worker-b"
        )
    assert lease is None
    row = _rows(
        pg_state,
        "SELECT status, error_code FROM character_generation_tasks WHERE id = 'cg-1'",
    )[0]
    assert row["status"] == "FAILED"
    assert row["error_code"] == "CHARACTER_LEASE_EXPIRED"


# ---------------------------------------------------------------------------
# E. 源帧 — exclusivity + manual recovery + degraded worker round
# ---------------------------------------------------------------------------


def _seed_source_frame_task(
    dsn: str,
    *,
    task_id: str,
    status: str = "PENDING",
    timestamps: str = "[1.0]",
) -> None:
    _exec(
        dsn,
        "INSERT INTO assets ("
        " id, project_id, kind, storage_uri, sha256, size_bytes, content_type,"
        " created_by_user_id"
        ") VALUES ('asset-ref', 'proj-1', 'reference_video',"
        " 'fake://sf-uploads/reference.mp4', '" + "b" * 64 + "', 16, 'video/mp4', 'u1')"
        " ON CONFLICT (id) DO NOTHING",
    )
    _exec(
        dsn,
        "INSERT INTO source_frame_tasks ("
        " id, project_id, asset_id, created_by_user_id, idempotency_key,"
        " request_hash, request_json, status"
        ") VALUES (%s, 'proj-1', 'asset-ref', 'u1', %s, %s, %s, %s)",
        (
            task_id,
            f"ik-{task_id}",
            f"rh-{task_id}",
            '{"timestamps_seconds": ' + timestamps + "}",
            status,
        ),
    )


class _FakeSourceFrameExtractor:
    def extract(
        self,
        content: bytes,
        *,
        filename: str,
        timestamps_seconds: tuple[float, ...],
    ) -> list[ExtractedSourceFrame]:
        assert content == b"reference-video"
        return [
            ExtractedSourceFrame(
                timestamp_seconds=timestamp,
                image=f"frame-{timestamp}".encode(),
                technical_score=round(timestamp / 12, 3),
            )
            for timestamp in timestamps_seconds
        ]


def test_source_frame_double_claim_is_exclusive(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_source_frame_task(pg_state, task_id="sf-1")
    with pg_transaction() as raw:
        first = acquire_source_frame_task(BusinessConnection.postgres(raw), worker_id="worker-a")
    assert first is not None
    with pg_transaction() as raw:
        second = acquire_source_frame_task(BusinessConnection.postgres(raw), worker_id="worker-b")
    assert second is None


def test_source_frame_expired_fails_closed_to_manual_recovery(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_source_frame_task(pg_state, task_id="sf-1", status="RUNNING")
    _exec(
        pg_state,
        "UPDATE source_frame_tasks SET locked_by = 'worker-a',"
        " locked_until = now() - interval '5 minutes' WHERE id = 'sf-1'",
    )
    with pg_transaction() as raw:
        reacquired = acquire_source_frame_task(
            BusinessConnection.postgres(raw), worker_id="worker-b"
        )
    assert reacquired is None
    row = _rows(
        pg_state, "SELECT status, error_code, retryable FROM source_frame_tasks WHERE id = 'sf-1'"
    )[0]
    assert row["status"] == "FAILED"
    assert row["error_code"] == "SOURCE_FRAME_TASK_RECOVERY_REQUIRED"
    assert int(row["retryable"]) == 1, "manual restart stays possible; auto-retry stays off"


def test_pg_worker_round_processes_source_frames_with_missing_quality_settings(
    pg_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_base(pg_state)
    _seed_source_frame_task(pg_state, task_id="sf-1")
    storage = FakeStorageAdapter(provider="fake", bucket="sf-uploads")
    storage.put_object("reference.mp4", b"reference-video", content_type="video/mp4")
    monkeypatch.setattr(
        "app.generation_worker.get_first_frame_quality_inspector",
        lambda _conn: (_ for _ in ()).throw(
            HTTPException(
                status_code=503,
                detail={"code": "FIRST_FRAME_QUALITY_SETTINGS_UNAVAILABLE"},
            )
        ),
    )
    monkeypatch.setattr(
        "app.generation_worker.get_media_storage",
        lambda _conn: storage,
    )
    monkeypatch.setattr(
        "app.generation_worker.FFmpegSourceFrameExtractor",
        lambda: _FakeSourceFrameExtractor(),
    )
    processed = run_pg_worker_round(worker_id="sf-fallback-worker", max_tasks=1)
    final = _rows(
        pg_state,
        "SELECT status, error_code, error_message_redacted FROM source_frame_tasks"
        " WHERE id = 'sf-1'",
    )[0]
    assert processed == 1, final
    assert final["status"] == "SUCCEEDED", final


# ---------------------------------------------------------------------------
# F. 文案改写 — script_rewrite_tasks on the PG lane
# ---------------------------------------------------------------------------


_REWRITE_TEXT = "原始口播稿。"
_REWRITE_HASH = _script_rewrite_request_hash({"text": _REWRITE_TEXT})


def _seed_script_rewrite_task(
    dsn: str, *, task_id: str, user_id: str = "u1", status: str = "PENDING"
) -> None:
    _exec(
        dsn,
        "INSERT INTO script_rewrite_tasks ("
        " id, project_id, created_by_user_id, idempotency_key, request_hash,"
        " request_json, status"
        ") VALUES (%s, 'proj-1', %s, %s, %s, %s, %s)",
        (
            task_id,
            user_id,
            f"ik-{task_id}",
            _REWRITE_HASH,
            json.dumps({"text": _REWRITE_TEXT}, ensure_ascii=False, separators=(",", ":")),
            status,
        ),
    )


def _rewrite_lease(dsn: str, worker_id: str) -> Any:
    with pg_transaction() as raw:
        return acquire_script_rewrite_task(BusinessConnection.postgres(raw), worker_id=worker_id)


def _configure_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    """prepare resolves DeepSeek settings through SettingsRepository; the
    matrix stubs that seam so the paid HTTP boundary (_request_deepseek)
    stays the only faked layer."""

    class _StubSettingsRepository:
        def __init__(self, conn: object) -> None:
            self._conn = conn

        def load_provider_config(self, provider: str) -> dict[str, str]:
            assert provider == "deepseek"
            return {"api_key": "test-key", "model": "deepseek-chat"}

    import app.script_rewrite as script_rewrite

    monkeypatch.setattr(script_rewrite, "SettingsRepository", _StubSettingsRepository)


@pytest.mark.parametrize("service", ["first_frame", "rewrite"])
def test_stale_failure_cannot_release_current_attempt_budget(pg_state: str, service: str) -> None:
    from app.usage_billing import accept_operation

    _seed_base(pg_state)
    _exec(
        pg_state,
        "INSERT INTO billing_tariffs(service,enabled,unit_credits) VALUES(%s,true,7)",
        (service,),
    )
    if service == "first_frame":
        _seed_image_task(pg_state, table="first_frame_tasks", task_id="late")
        table = "first_frame_tasks"
        with pg_transaction() as raw:
            lease = acquire_first_frame_task(
                BusinessConnection.postgres(raw), worker_id="same-worker"
            )
    else:
        _seed_script_rewrite_task(pg_state, task_id="late")
        table = "script_rewrite_tasks"
        lease = _rewrite_lease(pg_state, "same-worker")
    assert lease is not None
    with pg_transaction() as raw:
        accept_operation(
            BusinessConnection.postgres(raw),
            user_id="u1",
            service=service,
            source_id="late",
            units=1,
        )
    # A restarted worker may reuse its name: attempt is the fencing token.
    _exec(pg_state, f"UPDATE {table} SET attempt=attempt+1 WHERE id='late'")
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        if service == "first_frame":
            fail_image_task(
                conn,
                table="first_frame_tasks",
                lease=lease,
                cause=ValueError("late"),
                submission_started=False,
            )
        else:
            fail_script_rewrite_task(
                conn, lease=lease, cause=ValueError("late"), submission_started=False
            )
    assert _one(pg_state, "SELECT reserved_credits FROM wallets WHERE user_id='u1'") == 7
    assert _task_status(pg_state, table, "late") == "RUNNING"


def test_uncertain_checkpoint_recovery_releases_old_budget(pg_state: str) -> None:
    from app.usage_billing import accept_operation, finish_source, reconcile_operations

    _seed_base(pg_state)
    _exec(
        pg_state,
        "INSERT INTO billing_tariffs(service,enabled,unit_credits) VALUES('first_frame',true,7)",
    )
    _seed_image_task(
        pg_state,
        table="first_frame_tasks",
        task_id="old",
        status="SUBMISSION_UNCERTAIN",
        result_json=_FIRST_FRAME_CHECKPOINT_JSON,
    )
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        accept_operation(conn, user_id="u1", service="first_frame", source_id="old", units=1)
        assert reconcile_operations(conn) == 1
        accept_operation(conn, user_id="u1", service="first_frame", source_id="new", units=1)
        finish_source(conn, "new", units=1, succeeded=True)
    assert _one(pg_state, "SELECT reserved_credits FROM wallets WHERE user_id='u1'") == 0
    assert _one(pg_state, "SELECT sum(charged_credits) FROM billing_operations") == 7


def test_pg_first_frame_quality_transport_records_parent_cost(pg_state: str, monkeypatch) -> None:
    from types import SimpleNamespace

    from app.first_frames import ApilioFirstFrameQualityInspector
    from app.usage_billing import accept_operation

    _seed_base(pg_state)
    _seed_image_task(pg_state, table="first_frame_tasks", task_id="quality-cost")
    _exec(
        pg_state,
        "INSERT INTO billing_tariffs(service,unit_cost_fen) VALUES('quality_inspection',0.125)",
    )
    with pg_transaction() as raw:
        accept_operation(
            BusinessConnection.postgres(raw),
            user_id="u1",
            service="first_frame",
            source_id="quality-cost",
            units=1,
        )

    class Transport:
        def post(self, *args, **kwargs):
            return b'{"choices":[{"message":{"content":"{}"}}]}', {}

    inspector = ApilioFirstFrameQualityInspector(api_key="test-key", transport=Transport())
    monkeypatch.setattr(
        "app.generation_worker.prepare_first_frame_task",
        lambda *args, **kwargs: SimpleNamespace(
            provider=SimpleNamespace(provider_name="fake"), plan=SimpleNamespace(model="fake")
        ),
    )
    monkeypatch.setattr(
        "app.generation_worker.record_image_task_provider", lambda *args, **kwargs: None
    )

    def execute(*args, **kwargs):
        inspector._chat_json([])
        raise ValueError("publication unavailable")

    monkeypatch.setattr("app.generation_worker.run_first_frame_task_outside_transaction", execute)
    assert _run_worker("quality-worker") == 1
    assert (
        _one(pg_state, "SELECT cost_fen FROM billing_attempts WHERE service='quality_inspection'")
        == 0.125
    )
    assert (
        _one(
            pg_state,
            "SELECT source_id FROM billing_operations WHERE id=(SELECT operation_id "
            "FROM billing_attempts WHERE service='quality_inspection')",
        )
        == "quality-cost"
    )


def test_pg_analysis_keeps_known_call_cost_when_repair_fails(pg_state: str) -> None:
    from app.analysis import ProviderResponse
    from app.usage_billing import accept_operation

    _seed_base(pg_state)
    _exec(
        pg_state,
        "INSERT INTO "
        "assets(id,project_id,kind,storage_uri,sha256,size_bytes,content_type,created_by_user_id) VALUES('analysis-input','proj-1','reference_video','fake://bucket/ref.mp4',%s,8,'video/mp4','u1')",
        ("a" * 64,),
    )
    _exec(
        pg_state,
        "INSERT INTO "
        "analysis_tasks(id,project_id,asset_id,created_by_user_id,duration_seconds) "
        "VALUES('analysis-failed','proj-1','analysis-input','u1',5)",
    )
    _exec(
        pg_state,
        "INSERT INTO billing_tariffs(service,enabled,unit_credits,unit_cost_fen) "
        "VALUES('analysis',true,7,2.5)",
    )
    with pg_transaction() as raw:
        accept_operation(
            BusinessConnection.postgres(raw),
            user_id="u1",
            service="analysis",
            source_id="analysis-failed",
            units=1,
        )

    class Provider:
        requires_https_video_url = False

        def analyze(self, **kwargs):
            return ProviderResponse(text="invalid", raw={})

        def repair_json(self, **kwargs):
            raise ValueError("repair failed")

    assert (
        run_pg_worker_once(
            worker_id="analysis-worker",
            storage=FakeStorageAdapter(provider="fake", bucket="bucket"),
            analysis_provider=Provider(),
            max_tasks=1,
        )
        == 1
    )
    assert _one(pg_state, "SELECT cost_fen FROM billing_attempts WHERE service='analysis'") == 2.5
    assert _one(pg_state, "SELECT charged_credits FROM billing_operations") == 0
    assert _one(pg_state, "SELECT reserved_credits FROM wallets WHERE user_id='u1'") == 0


def test_script_rewrite_claim_is_exclusive(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_script_rewrite_task(pg_state, task_id="sr-1")
    first = _rewrite_lease(pg_state, "worker-a")
    assert first is not None
    assert _rewrite_lease(pg_state, "worker-b") is None


def test_script_rewrite_expired_submission_quarantines_without_recall(
    pg_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_base(pg_state)
    _configure_deepseek(monkeypatch)
    _seed_script_rewrite_task(pg_state, task_id="sr-1")
    lease = _rewrite_lease(pg_state, "crashed-worker")
    assert lease is not None
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        prepare_script_rewrite_task(conn, lease=lease)
        mark_script_rewrite_submission_started(conn, lease=lease)
    # Expire the lease from outside the fenced transaction (an in-block
    # UPDATE would self-deadlock on the row the transaction just marked).
    _expire_running_lease(pg_state, "script_rewrite_tasks", "sr-1")
    # The replacement worker must NOT pick the uncertain task back up (the
    # provider call already left; a resubmit would double-charge DeepSeek).
    assert _rewrite_lease(pg_state, "replacement-worker") is None
    assert _task_status(pg_state, "script_rewrite_tasks", "sr-1") == "SUBMISSION_UNCERTAIN"


def test_script_rewrite_network_timeout_lands_uncertain_not_retried(
    pg_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_base(pg_state)
    _configure_deepseek(monkeypatch)
    _seed_script_rewrite_task(pg_state, task_id="sr-1")
    lease = _rewrite_lease(pg_state, "timeout-worker")
    assert lease is not None
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        prepare_script_rewrite_task(conn, lease=lease)
        mark_script_rewrite_submission_started(conn, lease=lease)
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        fail_script_rewrite_task(
            conn,
            lease=lease,
            cause=HTTPException(
                504,
                detail={
                    "code": "DEEPSEEK_NETWORK_FAILED",
                    "message": "连接 AI 改写服务失败，请检查网络后重试。",
                },
            ),
            submission_started=True,
        )
    assert _task_status(pg_state, "script_rewrite_tasks", "sr-1") == "SUBMISSION_UNCERTAIN"
    assert _rewrite_lease(pg_state, "second-worker") is None


def test_script_rewrite_stale_completion_cannot_overwrite_recovered_state(
    pg_state: str,
) -> None:
    from app.script_rewrite import ScriptRewriteResult

    _seed_base(pg_state)
    _seed_script_rewrite_task(pg_state, task_id="sr-1")
    stale_lease = _rewrite_lease(pg_state, "worker-a")
    assert stale_lease is not None
    # The lease is lost underneath the stale worker (quarantined).
    _exec(
        pg_state,
        "UPDATE script_rewrite_tasks SET status = 'SUBMISSION_UNCERTAIN', locked_by = NULL,"
        " locked_until = NULL WHERE id = 'sr-1'",
    )
    with pytest.raises(RuntimeError, match="lease was lost"):
        with pg_transaction() as raw:
            conn = BusinessConnection.postgres(raw)
            complete_script_rewrite_task(
                conn,
                lease=stale_lease,
                result=ScriptRewriteResult(
                    rewritten_text="迟到结果",
                    provider="deepseek",
                    model="deepseek-chat",
                ),
            )
    row = _rows(
        pg_state,
        "SELECT status, result_json FROM script_rewrite_tasks WHERE id = 'sr-1'",
    )[0]
    assert row["status"] == "SUBMISSION_UNCERTAIN"
    assert row["result_json"] is None, "the late result must not overwrite recovered state"


def test_script_rewrite_worker_settles_on_pg(
    pg_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.script_rewrite as script_rewrite

    _seed_base(pg_state)
    _configure_deepseek(monkeypatch)
    _seed_script_rewrite_task(pg_state, task_id="sr-1")
    monkeypatch.setattr(
        script_rewrite,
        "_request_deepseek",
        lambda **_kwargs: "这是改写后的口播稿。",
    )
    processed = _run_worker("cw030-rewrite-worker")
    assert processed == 1
    row = _rows(
        pg_state,
        "SELECT status, result_json FROM script_rewrite_tasks WHERE id = 'sr-1'",
    )[0]
    assert row["status"] == "SUCCEEDED"
    assert "这是改写后的口播稿。" in str(row["result_json"])


# ---------------------------------------------------------------------------
# G. ASR — script_from_audio_tasks on the PG lane
# ---------------------------------------------------------------------------


def _seed_audio_task(
    dsn: str,
    *,
    task_id: str,
    status: str = "PENDING",
    audio_object_key: str | None = None,
) -> None:
    _exec(
        dsn,
        "INSERT INTO script_from_audio_tasks ("
        " id, project_id, source_asset_id, created_by_user_id, idempotency_key,"
        " request_hash, request_json, audio_object_key, status"
        ") VALUES (%s, 'proj-1', 'asset-ref', 'u1', %s, %s, '{}', %s, %s)"
        " ON CONFLICT (id) DO NOTHING",
        (task_id, f"ik-{task_id}", f"rh-{task_id}", audio_object_key, status),
    )


def _audio_lease(dsn: str, worker_id: str) -> Any:
    with pg_transaction() as raw:
        return acquire_script_from_audio_task(BusinessConnection.postgres(raw), worker_id=worker_id)


def test_script_from_audio_claim_is_exclusive(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_source_frame_task(pg_state, task_id="sf-asset")  # ensures asset-ref exists
    _seed_audio_task(pg_state, task_id="sfa-1")
    first = _audio_lease(pg_state, "worker-a")
    assert first is not None
    assert _audio_lease(pg_state, "worker-b") is None


def test_script_from_audio_expired_presubmission_lease_resets_to_pending(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_source_frame_task(pg_state, task_id="sf-asset")
    _seed_audio_task(pg_state, task_id="sfa-1", status="RUNNING")
    _exec(
        pg_state,
        "UPDATE script_from_audio_tasks SET locked_by = 'worker-a',"
        " locked_until = now() - interval '5 minutes' WHERE id = 'sfa-1'",
    )
    # No provider submission happened: the lease resets to PENDING and the
    # task is safely re-claimable (the audio receipt stays durable).
    reacquired = _audio_lease(pg_state, "worker-b")
    assert reacquired is not None
    row = _rows(
        pg_state,
        "SELECT status, locked_by, attempt FROM script_from_audio_tasks WHERE id = 'sfa-1'",
    )[0]
    assert row["status"] == "RUNNING"
    assert row["locked_by"] == "worker-b"
    assert int(row["attempt"]) == 1


def test_script_from_audio_expired_inflight_submission_quarantines(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_source_frame_task(pg_state, task_id="sf-asset")
    _seed_audio_task(pg_state, task_id="sfa-1", status="RUNNING")
    _exec(
        pg_state,
        "UPDATE script_from_audio_tasks SET locked_by = 'worker-a',"
        " provider_started_at = now()::text, provider_task_id = NULL,"
        " locked_until = now() - interval '5 minutes' WHERE id = 'sfa-1'",
    )
    assert _audio_lease(pg_state, "worker-b") is None
    row = _rows(
        pg_state,
        "SELECT status, error_code, retryable FROM script_from_audio_tasks WHERE id = 'sfa-1'",
    )[0]
    assert row["status"] == "SUBMISSION_UNCERTAIN"
    assert row["error_code"] == "SCRIPT_FROM_AUDIO_SUBMISSION_UNCERTAIN"
    assert int(row["retryable"]) == 0


def test_script_from_audio_provider_failure_is_terminal_without_resubmit(
    pg_state: str,
) -> None:
    _seed_base(pg_state)
    _seed_source_frame_task(pg_state, task_id="sf-asset")
    _seed_audio_task(pg_state, task_id="sfa-1")
    lease = _audio_lease(pg_state, "worker-a")
    assert lease is not None
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        fail_script_from_audio_task(
            conn,
            lease=lease,
            cause=RuntimeError("ASR provider timeout after 30s"),
            submission_started=True,
        )
    row = _rows(
        pg_state,
        "SELECT status, retryable FROM script_from_audio_tasks WHERE id = 'sfa-1'",
    )[0]
    assert row["status"] == "SUBMISSION_UNCERTAIN"
    assert int(row["retryable"]) == 0
    assert _audio_lease(pg_state, "worker-b") is None, "never blind-resubmit a paid ASR call"


def test_script_from_audio_receipt_survives_retry(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_source_frame_task(pg_state, task_id="sf-asset")
    _seed_audio_task(pg_state, task_id="sfa-1", audio_object_key="audio/sfa-1.opus")
    lease = _audio_lease(pg_state, "worker-a")
    assert lease is not None
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        fail_script_from_audio_task(
            conn,
            lease=lease,
            cause=RuntimeError("transcription worker crashed after upload"),
            submission_started=False,
        )
    row = _rows(
        pg_state,
        "SELECT audio_object_key FROM script_from_audio_tasks WHERE id = 'sfa-1'",
    )[0]
    assert row["audio_object_key"] == "audio/sfa-1.opus", (
        "the durable audio receipt must survive a worker retry"
    )


# ---------------------------------------------------------------------------
# H. 混合队列与两设备
# ---------------------------------------------------------------------------


def test_mixed_h3_and_independent_rotation_within_frozen_bounds(pg_state: str) -> None:
    _seed_base(pg_state)
    _seed_generation_task(pg_state, task_id="h3-u1", user_id="u1")
    _seed_generation_task(
        pg_state, task_id="ind-u2", user_id="u2", creation_kind="independent", project_id=None
    )
    _seed_generation_task(pg_state, task_id="h3-u3", user_id="u3")
    served: set[str] = set()
    rounds = 0
    while rounds < 8 and len(served) < 3:
        rounds += 1
        _run_worker(f"mixed-worker-{rounds}", max_tasks=3)
        served = {
            str(row["id"])
            for row in _rows(pg_state, "SELECT id FROM generation_tasks WHERE status = 'SUCCEEDED'")
        }
    assert len(served) == 3, f"every user must be served within the 8-round bound: {served}"
    assert rounds <= 8
    for user in ("u1", "u2", "u3"):
        assert _cursor_count(pg_state, user) == 0


def test_second_device_cannot_grow_same_user_running_slot(pg_state: str) -> None:
    _seed_base(pg_state)
    # Device A submits one task; a worker claims it (running slot = 1).
    _seed_generation_task(pg_state, task_id="dev-a-task", user_id="u1")
    first = _acquire(pg_state, "worker-device-a")
    assert first is not None
    assert _cursor_count(pg_state, "u1") == 1
    # Device B (same user, second device/session) submits another task.
    _seed_generation_task(pg_state, task_id="dev-b-task", user_id="u1")
    blocked = _acquire(pg_state, "worker-device-b")
    assert blocked is None, "the second device must not grow running_tasks_count past 1"
    assert (
        _one(pg_state, "SELECT running_tasks_count FROM user_queue_cursors WHERE user_id = 'u1'")
        == 1
    )
