"""W11 wallet billing service baselines on real PostgreSQL (CW-010).

The original suite exercised RESERVE/SETTLE/RELEASE against per-test SQLite
files. CW-010 migrates every assertion to the real PostgreSQL lane the
customer backend runs on: the same business services, the same
``BusinessConnection`` surface, real transactions from the shared pool.

Transaction boundaries follow PG semantics — the outer ``pg_transaction``
owns the commit, so each test runs its operations inside one pool
transaction (seed in its own committed transaction), and tests that assert
"no partial write after a rejected call" let the rejected call roll its own
transaction back and assert in a fresh one.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest
from pg_test_kit import (
    create_test_database,
    drop_test_database,
    require_pg_or_explicit_skip,
    upgrade_test_database_to_head,
)

import app.internal_billing as internal_billing
from app.db_pg import close_pg_pool, pg_transaction
from app.db_portable import BusinessConnection
from app.internal_billing import (
    BillingInvariantError,
    InsufficientCreditsError,
    finalize_internal_billing,
    reconcile_dangling_billing_reservations,
    reserve_internal_billing,
)

DB_NAME = "cw010_wallet_billing_test"


@pytest.fixture(scope="module")
def billing_dsn() -> Iterator[str]:
    require_pg_or_explicit_skip()
    dsn = create_test_database(DB_NAME)
    upgrade_test_database_to_head(dsn)
    patcher = pytest.MonkeyPatch()
    patcher.setenv("VIDEO_REPLICA_DATABASE_URL", dsn)
    yield dsn
    patcher.undo()
    close_pg_pool()
    drop_test_database(DB_NAME)


@pytest.fixture()
def billing_env(billing_dsn: str) -> str:
    """Wipe every business table in a short transaction (locks release at
    commit — a long-held TRUNCATE lock would starve concurrent workers)."""
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        conn.execute("SET session_replication_role = replica")
        conn.execute(
            "TRUNCATE assets, wallet_transactions, wallets, generation_tasks, "
            "generation_batches, projects, users, "
            "customer_session_events, customer_session_state, "
            "customer_idempotency_envelopes, customer_devices, activation_code_events, "
            "activation_code_activations, activation_code_deliveries, "
            "activation_code_exports, activation_codes, activation_code_batches, "
            "admin_write_idempotency, admin_sessions, recharge_orders CASCADE"
        )
        conn.execute("SET session_replication_role = DEFAULT")
    yield billing_dsn


def _seed(dsn: str, *, available_credits: int = 2) -> None:
    """Seed in its own committed transaction (never part of the test's)."""
    with pg_transaction() as raw:
        seed_task(BusinessConnection.postgres(raw), available_credits=available_credits)


def _fresh_conn(dsn: str) -> Iterator[BusinessConnection]:
    """A separate pool transaction (used for post-rollback assertions)."""
    with pg_transaction() as raw:
        yield BusinessConnection.postgres(raw)


def seed_task(conn: BusinessConnection, *, available_credits: int = 2) -> None:
    conn.execute(
        "INSERT INTO users (id, username, display_name, role) VALUES (%s, %s, %s, %s)",
        ("user_1", "user_1", "User One", "employee"),
    )
    conn.execute(
        "INSERT INTO projects (id, owner_user_id, name) VALUES (%s, %s, %s)",
        ("project_1", "user_1", "Project One"),
    )
    conn.execute(
        """
        INSERT INTO generation_batches (
            id, project_id, created_by_user_id, idempotency_key,
            request_hash, request_snapshot_json
        ) VALUES ('batch_1', 'project_1', 'user_1', 'batch-key', 'hash', '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO generation_tasks (id, batch_id, generation_mode, provider, model, status)
        VALUES ('task_1', 'batch_1', 'I2V', 'fake_h3', 'MiniMax-H3', 'PENDING')
        """
    )
    conn.execute(
        """
        INSERT INTO wallets (user_id, available_credits, reserved_credits)
        VALUES ('user_1', %s, 0)
        """,
        (available_credits,),
    )


def seed_second_task(conn: BusinessConnection) -> None:
    conn.execute(
        """
        INSERT INTO generation_tasks (id, batch_id, generation_mode, provider, model, status)
        VALUES ('task_2', 'batch_1', 'I2V', 'fake_h3', 'MiniMax-H3', 'PENDING')
        """
    )


def wallet_state(conn: BusinessConnection) -> tuple[int, int]:
    row = conn.execute(
        "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = 'user_1'"
    ).fetchone()
    assert row is not None
    return int(row["available_credits"]), int(row["reserved_credits"])


def transaction_types(conn: BusinessConnection) -> list[tuple[str, int]]:
    return [
        (str(row["type"]), int(row["billing_round"]))
        for row in conn.execute(
            """
            SELECT type, billing_round
            FROM wallet_transactions
            WHERE task_id = 'task_1'
            ORDER BY created_at, type
            """
        ).fetchall()
    ]


def test_reserve_and_finalize_support_multiple_seconds_per_round(
    billing_env: str,
) -> None:
    """W11 按秒计费：预留/结算/释放按提交档位秒数记账（不再固定 1）。"""
    del billing_env
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        seed_task(conn, available_credits=20)
        reserve_internal_billing(
            conn,
            user_id="user_1",
            task_id="task_1",
            billing_round=1,
            seconds=15,
        )
        assert wallet_state(conn) == (5, 15)
        conn.execute(
            """
            UPDATE generation_tasks
            SET status = 'SUCCEEDED', archive_status = 'DIRECT',
                provider_result_url = 'https://cdn.example/video.mp4'
            WHERE id = 'task_1'
            """
        )
        result = finalize_internal_billing(conn, task_id="task_1", outcome="success")
        assert result.seconds == 15
        assert wallet_state(conn) == (5, 0)
        deltas = [
            (str(row["type"]), int(row["available_delta"]), int(row["reserved_delta"]))
            for row in conn.execute(
                """
                SELECT type, available_delta, reserved_delta
                FROM wallet_transactions WHERE task_id = 'task_1'
                ORDER BY created_at
                """
            ).fetchall()
        ]
        assert deltas == [("RESERVE", -15, 15), ("SETTLE", 0, -15)]


def test_release_returns_all_reserved_seconds(billing_env: str) -> None:
    del billing_env
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        seed_task(conn, available_credits=20)
        reserve_internal_billing(
            conn,
            user_id="user_1",
            task_id="task_1",
            billing_round=1,
            seconds=15,
        )
        conn.execute("UPDATE generation_tasks SET status = 'FAILED' WHERE id = 'task_1'")
        result = finalize_internal_billing(conn, task_id="task_1", outcome="failed")
        assert result.seconds == 15
        assert wallet_state(conn) == (20, 0)


def test_reserve_rejects_zero_or_negative_seconds(billing_env: str, billing_dsn: str) -> None:
    _seed(billing_dsn)
    with pytest.raises(BillingInvariantError):
        with pg_transaction() as raw:
            reserve_internal_billing(
                BusinessConnection.postgres(raw),
                user_id="user_1",
                task_id="task_1",
                billing_round=1,
                seconds=0,
            )
    for fresh in _fresh_conn(billing_dsn):
        assert wallet_state(fresh) == (2, 0)
        assert transaction_types(fresh) == []


def test_reserve_moves_one_credit_and_is_idempotent(billing_env: str) -> None:
    del billing_env
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        seed_task(conn)
        first_round = reserve_internal_billing(
            conn, user_id="user_1", task_id="task_1", billing_round=1
        )
        replay_round = reserve_internal_billing(
            conn, user_id="user_1", task_id="task_1", billing_round=1
        )
        assert first_round == replay_round == 1
        assert wallet_state(conn) == (1, 1)
        assert transaction_types(conn) == [("RESERVE", 1)]


def test_reserve_rejects_insufficient_credits_without_partial_write(
    billing_env: str, billing_dsn: str
) -> None:
    _seed(billing_dsn, available_credits=0)
    with pytest.raises(InsufficientCreditsError):
        with pg_transaction() as raw:
            reserve_internal_billing(
                BusinessConnection.postgres(raw),
                user_id="user_1",
                task_id="task_1",
                billing_round=1,
            )
    for fresh in _fresh_conn(billing_dsn):
        assert wallet_state(fresh) == (0, 0)
        assert transaction_types(fresh) == []


def test_reserve_rejects_a_new_round_while_the_previous_round_is_active(
    billing_env: str, billing_dsn: str
) -> None:
    _seed(billing_dsn)
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        reserve_internal_billing(conn, user_id="user_1", task_id="task_1", billing_round=1)
    with pytest.raises(BillingInvariantError):
        with pg_transaction() as raw:
            reserve_internal_billing(
                BusinessConnection.postgres(raw),
                user_id="user_1",
                task_id="task_1",
                billing_round=2,
            )
    for fresh in _fresh_conn(billing_dsn):
        assert wallet_state(fresh) == (1, 1)
        assert transaction_types(fresh) == [("RESERVE", 1)]


def test_finalize_success_settles_only_an_archived_result(
    billing_env: str, billing_dsn: str
) -> None:
    _seed(billing_dsn)
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        reserve_internal_billing(conn, user_id="user_1", task_id="task_1", billing_round=1)

    with pytest.raises(BillingInvariantError):
        with pg_transaction() as raw:
            finalize_internal_billing(
                BusinessConnection.postgres(raw), task_id="task_1", outcome="success"
            )
    for fresh in _fresh_conn(billing_dsn):
        assert wallet_state(fresh) == (1, 1)
        assert transaction_types(fresh) == [("RESERVE", 1)]

    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        conn.execute(
            """
            INSERT INTO assets (
                id, project_id, kind, storage_uri, sha256,
                size_bytes, content_type, created_by_user_id
            ) VALUES ('result_1', 'project_1', 'video', 'cos://bucket/result.mp4',
                      'sha', 12, 'video/mp4', 'user_1')
            """
        )
        conn.execute(
            """
            UPDATE generation_tasks
            SET status = 'SUCCEEDED', archive_status = 'ARCHIVED',
                result_asset_id = 'result_1'
            WHERE id = 'task_1'
            """
        )
        first = finalize_internal_billing(conn, task_id="task_1", outcome="success")
        replay = finalize_internal_billing(conn, task_id="task_1", outcome="success")
        assert first.transaction_type == replay.transaction_type == "SETTLE"
        assert first.billing_round == replay.billing_round == 1
        assert wallet_state(conn) == (1, 0)
        assert transaction_types(conn) == [("RESERVE", 1), ("SETTLE", 1)]


def test_real_provider_result_must_be_archived_in_cos(billing_env: str, billing_dsn: str) -> None:
    _seed(billing_dsn)
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        reserve_internal_billing(conn, user_id="user_1", task_id="task_1", billing_round=1)
        conn.execute(
            """
            INSERT INTO assets (
                id, project_id, kind, storage_uri, sha256,
                size_bytes, content_type, created_by_user_id
            ) VALUES ('result_local', 'project_1', 'video',
                      'local://results/task.mp4', 'sha', 12, 'video/mp4', 'user_1')
            """
        )
        conn.execute(
            """
            UPDATE generation_tasks
            SET provider = 'metaso', status = 'SUCCEEDED',
                archive_status = 'ARCHIVED', result_asset_id = 'result_local'
            WHERE id = 'task_1'
            """
        )

    with pytest.raises(BillingInvariantError):
        with pg_transaction() as raw:
            finalize_internal_billing(
                BusinessConnection.postgres(raw), task_id="task_1", outcome="success"
            )
    for fresh in _fresh_conn(billing_dsn):
        assert wallet_state(fresh) == (1, 1)
        assert transaction_types(fresh) == [("RESERVE", 1)]


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_finalize_failure_or_cancellation_releases_credit_once(
    billing_env: str, outcome: str
) -> None:
    del billing_env
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        seed_task(conn, available_credits=1)
        reserve_internal_billing(conn, user_id="user_1", task_id="task_1", billing_round=1)
        conn.execute(
            "UPDATE generation_tasks SET status = %s WHERE id = 'task_1'",
            ("FAILED" if outcome == "failed" else "CANCELLED",),
        )
        first = finalize_internal_billing(conn, task_id="task_1", outcome=outcome)
        replay = finalize_internal_billing(conn, task_id="task_1", outcome=outcome)
        assert first.transaction_type == replay.transaction_type == "RELEASE"
        assert wallet_state(conn) == (1, 0)
        assert transaction_types(conn) == [("RELEASE", 1), ("RESERVE", 1)]


def test_dangling_reservation_sweep_releases_terminal_failure_once(
    billing_env: str,
) -> None:
    del billing_env
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        seed_task(conn, available_credits=1)
        reserve_internal_billing(conn, user_id="user_1", task_id="task_1", billing_round=1)
        conn.execute("UPDATE generation_tasks SET status = 'FAILED' WHERE id = 'task_1'")
        first = reconcile_dangling_billing_reservations(conn)
        replay = reconcile_dangling_billing_reservations(conn)
        assert first.scanned == first.released == 1
        assert first.settled == first.failed == 0
        assert replay.scanned == replay.released == replay.settled == replay.failed == 0
        assert wallet_state(conn) == (1, 0)
        assert transaction_types(conn) == [("RELEASE", 1), ("RESERVE", 1)]


def test_dangling_reservation_sweep_settles_only_archived_success(
    billing_env: str,
) -> None:
    del billing_env
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        seed_task(conn)
        reserve_internal_billing(conn, user_id="user_1", task_id="task_1", billing_round=1)
        conn.execute(
            """
            INSERT INTO assets (
                id, project_id, kind, storage_uri, sha256,
                size_bytes, content_type, created_by_user_id
            ) VALUES ('result_1', 'project_1', 'video',
                      'cos://bucket/result.mp4', 'sha', 12,
                      'video/mp4', 'user_1')
            """
        )
        conn.execute(
            """
            UPDATE generation_tasks
            SET status = 'SUCCEEDED', archive_status = 'ARCHIVED',
                result_asset_id = 'result_1'
            WHERE id = 'task_1'
            """
        )
        result = reconcile_dangling_billing_reservations(conn)
        assert result.scanned == result.settled == 1
        assert result.released == result.failed == 0
        assert wallet_state(conn) == (1, 0)
        assert transaction_types(conn) == [("RESERVE", 1), ("SETTLE", 1)]


def test_dangling_reservation_sweep_isolates_poisoned_candidate(
    billing_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    del billing_env
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        seed_task(conn, available_credits=2)
        seed_second_task(conn)
        reserve_internal_billing(conn, user_id="user_1", task_id="task_1", billing_round=1)
        reserve_internal_billing(conn, user_id="user_1", task_id="task_2", billing_round=1)
        conn.execute(
            "UPDATE generation_tasks SET status = 'FAILED' WHERE id IN ('task_1','task_2')"
        )

    original_finalize = internal_billing.finalize_internal_billing

    def poison_first_candidate(
        business_conn: BusinessConnection,
        *,
        task_id: str,
        outcome: internal_billing.BillingOutcome,
    ):
        result = original_finalize(business_conn, task_id=task_id, outcome=outcome)
        if task_id == "task_1":
            raise BillingInvariantError("poisoned candidate")
        return result

    monkeypatch.setattr(internal_billing, "finalize_internal_billing", poison_first_candidate)
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        result = reconcile_dangling_billing_reservations(conn)
        assert result.scanned == 2
        assert result.released == result.failed == 1
        assert result.settled == 0
        assert wallet_state(conn) == (1, 1)
        terminal_rows = conn.execute(
            "SELECT task_id FROM wallet_transactions WHERE type = 'RELEASE' ORDER BY task_id"
        ).fetchall()
        assert [str(row[0]) for row in terminal_rows] == ["task_2"]


def test_released_task_can_reserve_a_new_billing_round(billing_env: str) -> None:
    del billing_env
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        seed_task(conn, available_credits=1)
        reserve_internal_billing(conn, user_id="user_1", task_id="task_1", billing_round=1)
        conn.execute("UPDATE generation_tasks SET status = 'FAILED' WHERE id = 'task_1'")
        finalize_internal_billing(conn, task_id="task_1", outcome="failed")
        second_round = reserve_internal_billing(conn, user_id="user_1", task_id="task_1")
        assert second_round == 2
        assert wallet_state(conn) == (0, 1)
        assert transaction_types(conn) == [
            ("RELEASE", 1),
            ("RESERVE", 1),
            ("RESERVE", 2),
        ]


def test_historical_unbilled_task_is_a_noop(billing_env: str) -> None:
    del billing_env
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        seed_task(conn)
        conn.execute("UPDATE generation_tasks SET status = 'FAILED' WHERE id = 'task_1'")
        result = finalize_internal_billing(conn, task_id="task_1", outcome="failed")
        assert result.transaction_type is None
        assert result.billing_round is None
        assert wallet_state(conn) == (2, 0)
        assert transaction_types(conn) == []


def test_concurrent_task_reservations_cannot_overspend(billing_env: str, billing_dsn: str) -> None:
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        seed_task(conn, available_credits=1)
        seed_second_task(conn)

    barrier = threading.Barrier(2)
    results: list[str] = []
    result_lock = threading.Lock()

    def reserve(task_id: str) -> None:
        result = "insufficient"
        try:
            with pg_transaction() as raw:
                business = BusinessConnection.postgres(raw)
                barrier.wait()
                try:
                    reserve_internal_billing(
                        business,
                        user_id="user_1",
                        task_id=task_id,
                        billing_round=1,
                    )
                except InsufficientCreditsError:
                    result = "insufficient"
                else:
                    result = "reserved"
        except Exception:
            result = "insufficient"
        with result_lock:
            results.append(result)

    threads = [
        threading.Thread(target=reserve, args=("task_1",)),
        threading.Thread(target=reserve, args=("task_2",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["insufficient", "reserved"]
    for fresh in _fresh_conn(billing_dsn):
        assert wallet_state(fresh) == (0, 1)
        assert (
            fresh.execute(
                "SELECT COUNT(*) FROM wallet_transactions WHERE type = 'RESERVE'"
            ).fetchone()[0]
            == 1
        )
