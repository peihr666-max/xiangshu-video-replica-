from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from app.db_portable import BusinessConnection
from app.operation_costs import (
    begin_operation_cost,
    complete_operation_cost,
    record_video_generation_cost,
    record_video_generation_not_called,
    snapshot_generation_rates,
)

DEFAULT_DSN = "postgresql://testuser:testpass@localhost:5433/customer_v3_test"
DB_NAME = "operation_costs_test"


def _dsn() -> str:
    import os

    return os.environ.get("TEST_POSTGRESQL_URL", DEFAULT_DSN)


def _database_dsn(name: str) -> str:
    return _dsn().rsplit("/", 1)[0] + f"/{name}"


@pytest.fixture(scope="module")
def cost_dsn() -> Iterator[str]:
    from alembic import command
    from alembic.config import Config

    try:
        with psycopg.connect(_dsn(), connect_timeout=3):
            pass
    except Exception:
        pytest.skip("PostgreSQL fixture is not available")

    admin_dsn = _database_dsn("postgres")
    target_dsn = _database_dsn(DB_NAME)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{DB_NAME}"')

    server_dir = Path(__file__).resolve().parent.parent
    config = Config(str(server_dir / "alembic.ini"))
    config.set_main_option("script_location", str(server_dir / "migrations"))
    config.set_main_option(
        "sqlalchemy.url", target_dsn.replace("postgresql://", "postgresql+psycopg://")
    )
    command.upgrade(config, "head")
    try:
        yield target_dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')


def _seed_generation_task(conn: psycopg.Connection) -> None:
    conn.execute("INSERT INTO users (id, username, display_name) VALUES ('u1', 'u1', 'User One')")
    conn.execute("INSERT INTO projects (id, owner_user_id, name) VALUES ('p1', 'u1', 'P1')")
    conn.execute(
        "INSERT INTO generation_batches "
        "(id, project_id, created_by_user_id, idempotency_key, request_hash, "
        "request_snapshot_json) "
        "VALUES ('b1', 'p1', 'u1', 'idem-b1', 'hash-b1', '{}')"
    )
    conn.execute(
        "INSERT INTO generation_tasks (id, batch_id, provider, model, billed_seconds) "
        "VALUES ('t1', 'b1', 'metaso', 'MiniMax-H3', 15)"
    )


def test_generation_cost_uses_submission_rate_and_real_output_seconds(cost_dsn: str) -> None:
    with psycopg.connect(cost_dsn, autocommit=True, row_factory=psycopg.rows.dict_row) as raw:
        _seed_generation_task(raw)
        conn = BusinessConnection.postgres(raw)
        snapshot = snapshot_generation_rates(
            conn,
            task_id="t1",
            resolution="768P",
            billed_seconds=15,
        )
        assert snapshot.cost_unit_price_fen == 9
        assert snapshot.external_unit_price_fen == 12

        raw.execute(
            "UPDATE operation_cost_rates SET unit_price_fen = 99 "
            "WHERE subject = 'video_generation_768p'"
        )
        record_video_generation_cost(conn, task_id="t1", output_seconds=12.5)

        task = raw.execute(
            "SELECT actual_output_seconds, actual_cost, cost_status "
            "FROM generation_tasks WHERE id = 't1'"
        ).fetchone()
        assert float(task["actual_output_seconds"]) == 12.5
        assert float(task["actual_cost"]) == pytest.approx(1.125)
        assert task["cost_status"] == "ACTUAL"

        record = raw.execute(
            "SELECT usage_amount, unit_price_fen, cost_fen, status "
            "FROM operation_cost_records WHERE source_type = 'generation_task' "
            "AND source_id = 't1' AND subject = 'video_generation_768p'"
        ).fetchone()
        assert float(record["usage_amount"]) == 12.5
        assert record["unit_price_fen"] == 9
        assert float(record["cost_fen"]) == pytest.approx(112.5)
        assert record["status"] == "ACTUAL"
        context_ir = raw.execute(
            "SELECT status, usage_amount FROM operation_cost_records "
            "WHERE source_type = 'generation_task' AND source_id = 't1' "
            "AND subject = 'context_ir'"
        ).fetchone()
        assert context_ir["status"] == "UNKNOWN"
        assert context_ir["usage_amount"] is None


def test_missing_provider_usage_is_recorded_as_unknown(cost_dsn: str) -> None:
    with psycopg.connect(cost_dsn, autocommit=True, row_factory=psycopg.rows.dict_row) as raw:
        raw.execute(
            "INSERT INTO generation_tasks (id, batch_id, provider, model, billed_seconds) "
            "VALUES ('t2', 'b1', 'metaso', 'MiniMax-H3', 4)"
        )
        conn = BusinessConnection.postgres(raw)
        snapshot_generation_rates(conn, task_id="t2", resolution="2K", billed_seconds=4)
        record_video_generation_cost(conn, task_id="t2", output_seconds=None)

        task = raw.execute(
            "SELECT actual_output_seconds, actual_cost, cost_status "
            "FROM generation_tasks WHERE id = 't2'"
        ).fetchone()
        assert task["actual_output_seconds"] is None
        assert task["actual_cost"] is None
        assert task["cost_status"] == "UNKNOWN"


def test_provider_not_called_closes_snapshots_as_known_zero(cost_dsn: str) -> None:
    with psycopg.connect(cost_dsn, autocommit=True, row_factory=psycopg.rows.dict_row) as raw:
        raw.execute(
            "INSERT INTO generation_tasks (id, batch_id, provider, model, billed_seconds) "
            "VALUES ('t_not_called', 'b1', 'metaso', 'MiniMax-H3', 4)"
        )
        conn = BusinessConnection.postgres(raw)
        snapshot_generation_rates(conn, task_id="t_not_called", resolution="768P", billed_seconds=4)

        record_video_generation_not_called(conn, task_id="t_not_called")
        record_video_generation_not_called(conn, task_id="t_not_called")

        task = raw.execute(
            "SELECT actual_output_seconds, actual_cost, cost_status "
            "FROM generation_tasks WHERE id = 't_not_called'"
        ).fetchone()
        records = raw.execute(
            "SELECT subject, usage_amount, cost_fen, status "
            "FROM operation_cost_records WHERE source_id = 't_not_called' ORDER BY subject"
        ).fetchall()
        assert dict(task) == {
            "actual_output_seconds": 0,
            "actual_cost": 0,
            "cost_status": "ACTUAL",
        }
        assert len(records) == 2
        assert all(row["usage_amount"] == 0 for row in records)
        assert all(row["cost_fen"] == 0 for row in records)
        assert all(row["status"] == "ACTUAL" for row in records)


def test_pre_migration_task_without_snapshot_is_not_priced_at_current_rate(
    cost_dsn: str,
) -> None:
    with psycopg.connect(cost_dsn, autocommit=True, row_factory=psycopg.rows.dict_row) as raw:
        raw.execute(
            "INSERT INTO generation_tasks (id, batch_id, provider, model, billed_seconds) "
            "VALUES ('t3', 'b1', 'metaso', 'MiniMax-H3', 4)"
        )
        record_video_generation_cost(
            BusinessConnection.postgres(raw), task_id="t3", output_seconds=3.5
        )

        task = raw.execute(
            "SELECT actual_output_seconds, actual_cost, cost_status "
            "FROM generation_tasks WHERE id = 't3'"
        ).fetchone()
        assert float(task["actual_output_seconds"]) == 3.5
        assert task["actual_cost"] is None
        assert task["cost_status"] == "UNKNOWN"
        assert (
            raw.execute(
                "SELECT count(*) FROM operation_cost_records WHERE source_id = 't3'"
            ).fetchone()[0]
            == 0
        )


def test_generic_operation_cost_is_idempotent_and_uses_rate_snapshot(cost_dsn: str) -> None:
    with psycopg.connect(cost_dsn, autocommit=True, row_factory=psycopg.rows.dict_row) as raw:
        conn = BusinessConnection.postgres(raw)
        record_id = begin_operation_cost(
            conn,
            source_type="analysis_task",
            source_id=f"analysis-{uuid.uuid4()}",
            subject="video_analysis_768p",
            user_id="u1",
            resolution="768P",
        )
        complete_operation_cost(conn, record_id=record_id, usage_amount=8.25)
        complete_operation_cost(conn, record_id=record_id, usage_amount=8.25)
        row = raw.execute(
            "SELECT unit_price_fen, usage_amount, cost_fen, status "
            "FROM operation_cost_records WHERE id = %s",
            (record_id,),
        ).fetchone()
        assert row["unit_price_fen"] == 9
        assert float(row["usage_amount"]) == 8.25
        assert float(row["cost_fen"]) == pytest.approx(74.25)
        assert row["status"] == "ACTUAL"


def test_completed_operation_cost_rejects_conflicting_replay(cost_dsn: str) -> None:
    with psycopg.connect(cost_dsn, autocommit=True, row_factory=psycopg.rows.dict_row) as raw:
        conn = BusinessConnection.postgres(raw)
        record_id = begin_operation_cost(
            conn,
            source_type="analysis_task",
            source_id=f"analysis-conflict-{uuid.uuid4()}",
            subject="video_analysis_768p",
            resolution="768P",
        )
        complete_operation_cost(conn, record_id=record_id, usage_amount=8.25)

        with pytest.raises(RuntimeError, match="different result"):
            complete_operation_cost(conn, record_id=record_id, usage_amount=9)
        with pytest.raises(RuntimeError, match="different result"):
            complete_operation_cost(conn, record_id=record_id, usage_amount=None)


def test_operation_cost_migration_downgrade_roundtrip(cost_dsn: str) -> None:
    from alembic import command
    from alembic.config import Config

    server_dir = Path(__file__).resolve().parent.parent
    config = Config(str(server_dir / "alembic.ini"))
    config.set_main_option("script_location", str(server_dir / "migrations"))
    config.set_main_option(
        "sqlalchemy.url", cost_dsn.replace("postgresql://", "postgresql+psycopg://")
    )
    with psycopg.connect(cost_dsn, autocommit=True) as raw:
        assert (
            raw.execute("SELECT to_regclass('idx_wallet_transactions_type_created_at')").fetchone()[
                0
            ]
            is not None
        )
    with pytest.raises(RuntimeError, match="cannot downgrade 066"):
        command.downgrade(config, "065_second_based_billing")
    with psycopg.connect(cost_dsn, autocommit=True) as raw:
        raw.execute("DELETE FROM operation_cost_records")
        raw.execute(
            "UPDATE generation_tasks SET cost_rate_subject_snapshot=NULL, "
            "cost_unit_price_fen_snapshot=NULL, external_unit_price_fen_snapshot=NULL, "
            "actual_output_seconds=NULL, cost_status=NULL"
        )
    command.downgrade(config, "065_second_based_billing")
    try:
        with psycopg.connect(cost_dsn, autocommit=True) as raw:
            assert raw.execute("SELECT to_regclass('operation_cost_records')").fetchone()[0] is None
            assert (
                raw.execute(
                    "SELECT to_regclass('idx_wallet_transactions_type_created_at')"
                ).fetchone()[0]
                is None
            )
            columns = {
                row[0]
                for row in raw.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'generation_tasks'
                    """
                ).fetchall()
            }
            assert "actual_output_seconds" not in columns
            assert "cost_rate_subject_snapshot" not in columns
    finally:
        command.upgrade(config, "head")
