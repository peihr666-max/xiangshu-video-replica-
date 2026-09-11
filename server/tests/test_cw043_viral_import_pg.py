"""CW-043 Segment 4+ — 爆款导入 durable-queue 租约机制 TEST-PG 矩阵.

CW-043 审计实施：``CW043-PG-COVERAGE-MATRIX`` §5.1.1 #20 把旧
``test_viral_import.py`` 的 import 全矩阵标为 ⚠️部分（旧文件仅 SQLite，且多为
经 ``X-Dev-User-Id`` 的 TestClient 路由级重型集成）。CW-026 收敛后 PG lane 只认
客户会话 Bearer，路由级 dev-header 用例在 PG 上不可达；本模块改在真实 PG 上直接
验证 ``run_pg_worker_once`` 消费爆款导入队列所用的**持久队列租约机制**——这是
``test_cw030_worker_pg_matrix.py`` 唯一未覆盖的任务类（cw030 grep viral_import = 0）：

- 独占认领（``FOR UPDATE SKIP LOCKED`` + status 状态机：一个 PENDING 任务不会被
  两个 worker 重复认领）
- 过期租约回收 + attempt 递增（RUNNING 且 locked_until 过期 → 复位 PENDING 后被
  新 worker 重新认领，attempt 1→2，started_at 保留）
- 失败释放锁 + retryable 分级（普通异常默认可重试；终态 ViralImportError
  retryable=False 落 retryable=0）
- 陈旧租约失败是 no-op（attempt + locked_by 栅栏令牌：被回收后旧 worker 的迟到
  失败不得覆盖已恢复状态）
- 幂等键按属主唯一（``uq_viral_import_tasks_owner_idempotency`` —— enqueue 的
  ``ON CONFLICT (owner_user_id, idempotency_key) DO NOTHING`` 重放去重所依赖的约束）

PG-lane 事实（CW-043 审计确认）：``viral_import_tasks`` 的 ``locked_until`` /
``updated_at`` / ``created_at`` 皆 ``sa.Text()``（迁移 078），认领/回收用 TEXT 词法
比较 ``locked_until <= now_text``，且 ``now_text`` 由 Python 侧
``datetime.now(UTC).strftime`` 生成——全程与会话 TimeZone 无关。故本模块用固定过去
文本 ``'2020-01-01 00:00:00'`` 制造确定性过期，不依赖 SQL ``now()``。

专属隔离库 ``cw043_viral_import_test`` 已登记 ``pg_test_kit.RECORDED_TEST_DATABASES``；
零 SQLite 替代、零缺库 skip（缺 PG 即硬失败，PG-05）；用例间 DELETE 复位隔离。
认领/失败经 ``pg_transaction`` 生产事务通道（与 ``run_pg_worker_once`` 同形）。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any, cast

# 审计写入器在导入期即要求 HMAC key（enqueue 走 insert_audit）；先于 app 导入设置。
os.environ.setdefault(
    "VIDEO_REPLICA_ADMIN_SESSION_HMAC_KEY",
    "test-key-for-cw043-viral-import-matrix-tests-minimum-48-bytes-long",
)

import psycopg
import pytest
from pg_test_kit import (
    create_test_database,
    drop_test_database,
    require_pg_or_explicit_skip,
    upgrade_test_database_to_head,
)
from psycopg.rows import dict_row

from app.db_pg import DATABASE_URL_ENV, close_pg_pool, pg_transaction
from app.db_portable import BusinessConnection
from app.viral_import import (
    ViralImportError,
    ViralImportLease,
    acquire_viral_import_task,
    fail_viral_import_task,
)

CW043_VIRAL_IMPORT_TEST_DB = "cw043_viral_import_test"

# 固定“已过期”时刻：acquire 用 TEXT 词法比较 locked_until <= now_text，
# 该值恒小于任何真实 now（2026+），确定性触发回收且与会话 TimeZone 无关。
_EXPIRED = "2020-01-01 00:00:00"
# 固定“仍持有”时刻：恒大于真实 now，代表未过期的活动租约。
_HELD = "2999-01-01 00:00:00"
_SEED_STAMP = "2026-09-06 03:00:00"


# ---------------------------------------------------------------------------
# 座子：专属库 + DATABASE_URL_ENV 指向它（pg_transaction 走生产 PG 通道）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def import_dsn() -> Iterator[str]:
    """专属爆款导入队列测试库：建库 → alembic head → 用完即删."""
    require_pg_or_explicit_skip()
    dsn = create_test_database(CW043_VIRAL_IMPORT_TEST_DB)
    upgrade_test_database_to_head(dsn)
    try:
        yield dsn
    finally:
        drop_test_database(CW043_VIRAL_IMPORT_TEST_DB)


@pytest.fixture()
def pg_state(import_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """DATABASE_URL_ENV 指向专属库：``pg_transaction`` 走生产 PG 事务通道."""
    close_pg_pool()
    monkeypatch.setenv(DATABASE_URL_ENV, import_dsn)
    monkeypatch.delenv("VIDEO_REPLICA_CUSTOMER_PRODUCTION", raising=False)
    yield import_dsn
    close_pg_pool()


# ---------------------------------------------------------------------------
# 原语播种 helper（worker-identical 行，无路由机制）
# ---------------------------------------------------------------------------

# 叶子优先 DELETE：viral_import_tasks 的 project_id/owner_user_id 是 FK。
_CLEANUP_ORDER = ("viral_import_tasks", "projects", "users")


def _exec(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> None:
    with psycopg.connect(dsn, autocommit=True) as pg:
        pg.execute(sql, params)


def _rows(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as pg:
        return [dict(row) for row in pg.execute(sql, params).fetchall()]


def _one(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> Any:
    with psycopg.connect(dsn, autocommit=True) as pg:
        row = pg.execute(sql, params).fetchone()
        return None if row is None else row[0]


def _truncate(dsn: str) -> None:
    for table in _CLEANUP_ORDER:
        _exec(dsn, f"DELETE FROM {table}")


def _seed_base(dsn: str) -> None:
    _truncate(dsn)
    _exec(
        dsn,
        "INSERT INTO users (id, username, display_name, role) VALUES"
        " ('u1', 'u1', 'User One', 'employee'),"
        " ('u2', 'u2', 'User Two', 'employee')",
    )
    _exec(
        dsn,
        "INSERT INTO projects (id, name, owner_user_id) VALUES"
        " ('proj-1', 'CW043 Viral Import', 'u1')",
    )


def _seed_import_task(
    dsn: str,
    *,
    task_id: str,
    owner: str = "u1",
    project_id: str | None = "proj-1",
    platform: str = "douyin",
    video_id: str = "vid-1",
    purpose: str = "replica",
    idempotency_key: str | None = None,
    status: str = "PENDING",
    attempt: int = 0,
    locked_by: str | None = None,
    locked_until: str | None = None,
) -> None:
    _exec(
        dsn,
        "INSERT INTO viral_import_tasks (id, owner_user_id, project_id, platform,"
        " video_id, purpose, idempotency_key, request_hash, request_json, status,"
        " attempt, locked_by, locked_until, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '{}', %s, %s, %s, %s, %s, %s)",
        (
            task_id,
            owner,
            project_id,
            platform,
            video_id,
            purpose,
            idempotency_key or f"ik-{task_id}",
            f"rh-{task_id}",
            status,
            attempt,
            locked_by,
            locked_until,
            _SEED_STAMP,
            _SEED_STAMP,
        ),
    )


def _import_row(dsn: str, task_id: str) -> dict[str, Any]:
    return _rows(
        dsn,
        "SELECT status, attempt, locked_by, locked_until, retryable, error_code,"
        " started_at FROM viral_import_tasks WHERE id = %s",
        (task_id,),
    )[0]


def _expire_lease(dsn: str, task_id: str) -> None:
    _exec(
        dsn,
        "UPDATE viral_import_tasks SET locked_until = %s WHERE id = %s",
        (_EXPIRED, task_id),
    )


def _acquire(worker_id: str) -> ViralImportLease | None:
    with pg_transaction() as raw:
        return acquire_viral_import_task(BusinessConnection.postgres(raw), worker_id=worker_id)


def _fail(lease: ViralImportLease, cause: Exception) -> None:
    with pg_transaction() as raw:
        fail_viral_import_task(BusinessConnection.postgres(raw), lease=lease, cause=cause)


# ===========================================================================
# A. 独占认领（FOR UPDATE SKIP LOCKED + 状态机）
# ===========================================================================


def test_acquire_viral_import_lease_is_exclusive_on_real_pg(pg_state: str) -> None:
    """一个 PENDING 导入任务只被一个 worker 认领：worker-a 得租约（attempt 0→1、
    status→RUNNING、locked_by 落定），worker-b 在真实 PG 的 ``FOR UPDATE SKIP
    LOCKED`` + ``status='PENDING'`` 状态机下拿不到同一任务（返回 None）。"""
    _seed_base(pg_state)
    _seed_import_task(pg_state, task_id="vi-1")

    first = _acquire("worker-a")
    assert first is not None
    assert first.id == "vi-1"
    assert first.worker_id == "worker-a"
    assert first.attempt == 1
    assert first.owner_user_id == "u1"
    assert first.project_id == "proj-1"

    second = _acquire("worker-b")
    assert second is None

    row = _import_row(pg_state, "vi-1")
    assert row["status"] == "RUNNING"
    assert row["locked_by"] == "worker-a"
    assert int(row["attempt"]) == 1
    # started_at 首次认领即落定。
    assert row["started_at"] is not None


def test_expired_viral_import_lease_is_reclaimed_and_attempt_increments_on_real_pg(
    pg_state: str,
) -> None:
    """worker-a 持有的租约过期（locked_until 过去）后，acquire 的首段 UPDATE 把它
    复位 PENDING（保留 attempt），次段 UPDATE 由 worker-b 重新认领：attempt 1→2、
    locked_by 换到 worker-b、status 仍 RUNNING。这是 PG lane 崩溃 worker 的任务
    回收路径。"""
    _seed_base(pg_state)
    _seed_import_task(
        pg_state,
        task_id="vi-1",
        status="RUNNING",
        attempt=1,
        locked_by="worker-a",
        locked_until=_HELD,
    )
    _expire_lease(pg_state, "vi-1")

    reacquired = _acquire("worker-b")
    assert reacquired is not None
    assert reacquired.id == "vi-1"
    assert reacquired.attempt == 2

    row = _import_row(pg_state, "vi-1")
    assert row["status"] == "RUNNING"
    assert row["locked_by"] == "worker-b"
    assert int(row["attempt"]) == 2


# ===========================================================================
# B. 失败释放锁 + retryable 分级
# ===========================================================================


def test_fail_viral_import_task_releases_lease_and_marks_retryable_on_real_pg(
    pg_state: str,
) -> None:
    """普通异常（非 ViralImportError）→ status FAILED、retryable=1（默认可重试）、
    error_code=VIRAL_IMPORT_FAILED、locked_by/locked_until 释放为 NULL。"""
    _seed_base(pg_state)
    _seed_import_task(pg_state, task_id="vi-1")
    lease = _acquire("worker-a")
    assert lease is not None

    _fail(lease, RuntimeError("provider transport dropped"))

    row = _import_row(pg_state, "vi-1")
    assert row["status"] == "FAILED"
    assert int(row["retryable"]) == 1
    assert row["error_code"] == "VIRAL_IMPORT_FAILED"
    assert row["locked_by"] is None
    assert row["locked_until"] is None


def test_terminal_viral_import_error_marks_non_retryable_on_real_pg(pg_state: str) -> None:
    """终态 ViralImportError(retryable=False) → status FAILED、retryable=0（不再
    自动重试）、error_code 取异常携带的业务码。"""
    _seed_base(pg_state)
    _seed_import_task(pg_state, task_id="vi-1")
    lease = _acquire("worker-a")
    assert lease is not None

    _fail(
        lease,
        ViralImportError(
            409, "VIRAL_IMPORT_PROJECT_CHANGED", "目标项目归属已变化。", retryable=False
        ),
    )

    row = _import_row(pg_state, "vi-1")
    assert row["status"] == "FAILED"
    assert int(row["retryable"]) == 0
    assert row["error_code"] == "VIRAL_IMPORT_PROJECT_CHANGED"
    assert row["locked_by"] is None


# ===========================================================================
# C. 栅栏令牌：陈旧租约的迟到失败不得覆盖已恢复状态
# ===========================================================================


def test_stale_viral_import_lease_failure_is_a_noop_on_real_pg(pg_state: str) -> None:
    """worker-a 认领后租约过期、被 worker-b 回收（attempt→2）。worker-a 迟到的
    fail 携带陈旧栅栏（locked_by=worker-a、attempt=1），其 WHERE 与库中现值
    （worker-b、attempt=2）不匹配 → 0 行更新（no-op），任务保持 worker-b 的
    RUNNING/attempt=2 不被覆盖。"""
    _seed_base(pg_state)
    _seed_import_task(pg_state, task_id="vi-1")

    stale_lease = _acquire("worker-a")
    assert stale_lease is not None
    assert stale_lease.attempt == 1

    # 租约过期 → worker-b 回收（attempt 2、locked_by worker-b）。
    _expire_lease(pg_state, "vi-1")
    fresh_lease = _acquire("worker-b")
    assert fresh_lease is not None
    assert fresh_lease.attempt == 2

    # 陈旧 worker-a 的迟到失败：栅栏不匹配 → no-op。
    _fail(stale_lease, RuntimeError("late failure from the stale worker"))

    row = _import_row(pg_state, "vi-1")
    assert row["status"] == "RUNNING", "陈旧失败不得覆盖已回收的 RUNNING 状态"
    assert row["locked_by"] == "worker-b"
    assert int(row["attempt"]) == 2


# ===========================================================================
# D. 幂等键按属主唯一（enqueue ON CONFLICT 重放去重所依赖的约束）
# ===========================================================================


def test_viral_import_idempotency_key_is_unique_per_owner_on_real_pg(pg_state: str) -> None:
    """``uq_viral_import_tasks_owner_idempotency``：同属主重复幂等键触发唯一违例
    （enqueue 的 ``ON CONFLICT (owner_user_id, idempotency_key) DO NOTHING`` 重放
    去重即依赖它）；不同属主可复用同一幂等键（约束按属主范围）。"""
    _seed_base(pg_state)
    _seed_import_task(pg_state, task_id="vi-1", owner="u1", idempotency_key="shared-key")

    with pytest.raises(psycopg.IntegrityError):
        _seed_import_task(pg_state, task_id="vi-2", owner="u1", idempotency_key="shared-key")

    # 另一属主复用同一幂等键：约束是 (owner_user_id, idempotency_key) 复合唯一。
    _seed_import_task(pg_state, task_id="vi-3", owner="u2", idempotency_key="shared-key")

    assert cast(int, _one(pg_state, "SELECT count(*) FROM viral_import_tasks")) == 2
