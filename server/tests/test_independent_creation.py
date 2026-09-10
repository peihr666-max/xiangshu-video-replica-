"""CW-010: independent creation (C2 独立创作) recovery baseline on real PostgreSQL.

Migrated off the ``tmp_path`` SQLite lane (route ``TestClient`` + ``get_database``
override) onto a dedicated TEST-PG database with an *independent multi-connection*
baseline. Two identity paths coexist on PG and this suite uses both deliberately.
The *fenced write* path (``BusinessDbDep`` →
``customer_fence.customer_session_snapshot``) makes a customer Bearer session the
sole identity and refuses the internal ``X-Dev-User-Id`` header with 401, so the
billing / RBAC / idempotency assertions drive the **service** layer directly inside
``pg_transaction`` rounds — the same shape CW-010a (``test_wallet_billing_service``)
uses — constructing the acting ``CurrentUser`` (employee / admin / auditor)
explicitly. The *unfenced read* path (``get_database`` + ``get_current_user``) DOES
authenticate the dev header on PG under the test runtime's ``development`` auth mode
(``internal_auth_required()`` is false and ``ALLOW_DEV_IDENTITY_HEADER=1``), so the
read routes are driven through ``TestClient`` with the dev header and zero override
(the route paragraph below). RBAC, idempotency, the mode/asset matrix, wallet
RESERVE/SETTLE/RELEASE and the PG worker (``run_pg_worker_once``) lifecycle are all
exercised against real PostgreSQL: never SQLite, never a mock-persisted store,
never a missing-PG skip (the CW-007 ``require_pg_or_explicit_skip`` hard gate fails
closed when the fixture is unreachable).

The independent-specific HTTP routes are restored here on the PG lane rather than
deleted: the *read* routes (``GET /api/independent/capabilities`` and the
independent-creation page's ``GET /api/studio/saved-prompts`` import source) ride
the unfenced ``get_database`` dependency and authenticate the dev header on PG, so
they are driven through ``TestClient`` with **zero** dependency override; the
*fenced write* route (``POST /api/independent/video-tasks``) is driven through a
``_PgBusinessDb`` double that mirrors the production ``BusinessDb.write()`` on a
real ``pg_transaction`` (catch ``AuditedSecurityDenial`` → ``persist_security_denial``
→ re-raise) so the 201 body, ``BatchResult`` serialization and wallet RESERVE all
commit to PostgreSQL — the database is never mocked, only the acting user the
Bearer-session fence would otherwise resolve. The *shared* post-creation routes
(``GET /api/generation-batches`` listing / detail / cancel) are the generation
domain's own contract and stay covered by ``test_generation.py``; this file owns
the independent-creation database baseline plus its two dedicated routes per CW-010.

Migration findings (SQLite → PostgreSQL):
- ``runtime_settings.h3_extended_modes_enabled`` is a real boolean column, so the
  SQLite lane's ``SET ... = 1`` becomes ``SET ... = true``.
- ``operation_cost_rates`` FK-references ``users`` (ON DELETE SET NULL), so
  ``TRUNCATE users CASCADE`` clears the migration-seeded rate defaults that
  ``snapshot_generation_rates`` reads on the PG lane; the seed captures and
  restores them (ON CONFLICT DO NOTHING) so every created task freezes a real
  cost snapshot.
- ``reference_asset_ids`` over the capability limit is rejected by the
  ``IndependentVideoRequest`` model (``max_length``) at construction time, so the
  service-level assertion is a pydantic ``ValidationError`` (the route turned it
  into a 422 ``too_long`` body).
- The foreign-asset and auditor denials are PG ``AuditedSecurityDenial`` (an
  ``HTTPException`` subclass) because ``_raise_denial_with_audit`` defers the
  audit to the route layer on PostgreSQL; the status code (404 / 403) is asserted.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager

# Set the audit HMAC key before importing app modules (audit writers require it).
os.environ.setdefault(
    "VIDEO_REPLICA_ADMIN_SESSION_HMAC_KEY",
    "test-key-for-cw010-independent-tests-minimum-48-bytes-long-12",
)

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pg_test_kit import (
    create_test_database,
    drop_test_database,
    require_pg_or_explicit_skip,
    upgrade_test_database_to_head,
)
from pydantic import ValidationError

from app.auth import CurrentUser
from app.customer_fence import get_business_db
from app.db_pg import DATABASE_URL_ENV, close_pg_pool, pg_transaction
from app.db_portable import BusinessConnection
from app.generation import (
    BatchResult,
    GenerationBatchListPage,
    cancel_generation_batch,
    get_generation_batch,
    list_generation_batches,
)
from app.generation_worker import run_pg_worker_once
from app.independent import (
    IndependentVideoRequest,
    create_independent_batch,
    read_independent_capabilities,
)
from app.main import app
from app.permissions import AuditedSecurityDenial, persist_security_denial
from app.storage import FakeStorageAdapter

CW010_INDEPENDENT_DB_NAME = "cw010_independent_test"

_INDEPENDENT_TABLES = (
    "wallet_transactions, assets, versions, generation_tasks, "
    "generation_batches, user_queue_cursors, projects, wallets, "
    "runtime_settings, users"
)

# Real boolean column on PostgreSQL (the SQLite lane used ``= 1``).
ENABLED_UPDATE = "UPDATE runtime_settings SET h3_extended_modes_enabled = true WHERE id = 1"

EMPLOYEE_1 = CurrentUser(
    id="employee_1", username="employee_1", display_name="Employee One", role="employee"
)
EMPLOYEE_2 = CurrentUser(
    id="employee_2", username="employee_2", display_name="Employee Two", role="employee"
)
AUDITOR_1 = CurrentUser(
    id="auditor_1", username="auditor_1", display_name="Auditor One", role="auditor"
)


# ---------------------------------------------------------------------------
# PostgreSQL integration (dedicated migrated fixture database)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def independent_dsn() -> Iterator[str]:
    """A dedicated migrated PG database for the independent-creation baseline.

    Created through the CW-007 kit helpers so ``assert_safe_test_database``
    guards the ``DROP ... WITH (FORCE)`` against the allowlisted name
    (registered in ``pg_test_kit.RECORDED_TEST_DATABASES``) and the kit resolves
    the admin DSN — no hand-rolled DSN concatenation lives in this file.
    """
    require_pg_or_explicit_skip()
    dsn = create_test_database(CW010_INDEPENDENT_DB_NAME)
    upgrade_test_database_to_head(dsn)
    try:
        yield dsn
    finally:
        drop_test_database(CW010_INDEPENDENT_DB_NAME)


def _executemany(pg: psycopg.Connection, sql: str, rows: list[tuple[object, ...]]) -> None:
    """psycopg3 exposes ``executemany`` on the cursor, not the connection."""
    with pg.cursor() as cursor:
        cursor.executemany(sql, rows)


def _seed_scene(dsn: str) -> None:
    """TRUNCATE and re-seed the independent-creation scene on real PostgreSQL."""
    with psycopg.connect(dsn, autocommit=True) as pg:
        # operation_cost_rates FK-references users, so the CASCADE below clears
        # the migration-seeded defaults snapshot_generation_rates reads on PG.
        default_rates = pg.execute(
            "SELECT subject, kind, unit, resolution, unit_price_fen FROM operation_cost_rates"
        ).fetchall()
        pg.execute("SET session_replication_role = replica")
        pg.execute(f"TRUNCATE {_INDEPENDENT_TABLES} CASCADE")
        pg.execute("SET session_replication_role = DEFAULT")
        with pg.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO operation_cost_rates "
                "(subject, kind, unit, resolution, unit_price_fen) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (subject) DO NOTHING",
                default_rates,
            )
        pg.execute(
            "INSERT INTO runtime_settings "
            "(id, max_generation_count_per_batch, max_concurrent_h3_tasks, "
            " internal_base_unit_price_fen, min_recharge_fen, recharge_step_fen, "
            " fair_queue_enabled) "
            "VALUES (1, 4, 100, 1000, 10000, 1000, true)"
        )
        _executemany(
            pg,
            "INSERT INTO users (id, username, display_name, role) VALUES (%s, %s, %s, %s)",
            [
                ("employee_1", "employee_1", "Employee One", "employee"),
                ("employee_2", "employee_2", "Employee Two", "employee"),
                ("admin_1", "admin_1", "Admin One", "admin"),
                ("auditor_1", "auditor_1", "Auditor One", "auditor"),
            ],
        )
        _executemany(
            pg,
            "INSERT INTO wallets (user_id, available_credits, reserved_credits) VALUES (%s, %s, 0)",
            [("employee_1", 1000), ("employee_2", 1000)],
        )
        _executemany(
            pg,
            "INSERT INTO projects (id, owner_user_id, name) VALUES (%s, %s, %s)",
            [("project_a", "employee_1", "A"), ("project_b", "employee_2", "B")],
        )
        # 独立创作素材：用户归属、无项目（materials 通道产物形态）+ 一个项目内视频资产。
        _executemany(
            pg,
            "INSERT INTO assets ("
            " id, project_id, kind, storage_uri, sha256, size_bytes,"
            " content_type, created_by_user_id"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    "frame-owned",
                    None,
                    "material_image",
                    "fake://generation-results/frame.png",
                    "frame-hash",
                    9,
                    "image/png",
                    "employee_1",
                ),
                (
                    "frame-other",
                    None,
                    "material_image",
                    "fake://generation-results/other.png",
                    "other-hash",
                    9,
                    "image/png",
                    "employee_2",
                ),
                (
                    "asset-video",
                    "project_a",
                    "reference_video",
                    "local://assets/ref.mp4",
                    "video-hash",
                    9,
                    "video/mp4",
                    "employee_1",
                ),
            ],
        )


@pytest.fixture()
def scene(independent_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Point the app PG pool at the independent database and seed one clean scene."""
    close_pg_pool()
    monkeypatch.setenv(DATABASE_URL_ENV, independent_dsn)
    monkeypatch.delenv("VIDEO_REPLICA_CUSTOMER_PRODUCTION", raising=False)
    _seed_scene(independent_dsn)
    yield independent_dsn
    close_pg_pool()


# ---------------------------------------------------------------------------
# Service helpers — each logical block runs in its own pg_transaction
# (a separate pooled connection), the CW-010 multi-connection baseline.
# ---------------------------------------------------------------------------


def _enable_extended_modes() -> None:
    with pg_transaction() as raw:
        BusinessConnection.postgres(raw).execute(ENABLED_UPDATE)


def _create(request: IndependentVideoRequest, actor: CurrentUser) -> BatchResult:
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        return create_independent_batch(conn, actor=actor, request=request)


def _list_batches(actor: CurrentUser) -> GenerationBatchListPage:
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        return list_generation_batches(conn, actor=actor)


def _get_batch(batch_id: str, actor: CurrentUser) -> BatchResult:
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        return get_generation_batch(conn, batch_id=batch_id, actor=actor)


def _cancel_batch(batch_id: str, actor: CurrentUser) -> BatchResult:
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        return cancel_generation_batch(conn, actor=actor, batch_id=batch_id)


def _wallet(user_id: str) -> tuple[int, int]:
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        row = conn.execute(
            "SELECT available_credits, reserved_credits FROM wallets WHERE user_id = %s",
            (user_id,),
        ).fetchone()
    assert row is not None
    return int(row["available_credits"]), int(row["reserved_credits"])


def _ledger_count(tx_type: str) -> int:
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM wallet_transactions WHERE type = %s",
            (tx_type,),
        ).fetchone()
    assert row is not None
    return int(row["n"])


def _run_worker(worker_id: str) -> int:
    storage = FakeStorageAdapter(provider="fake", bucket="generation-results")
    return run_pg_worker_once(worker_id=worker_id, storage=storage)


# ---------------------------------------------------------------------------
# Route doubles. The independent WRITE route rides ``BusinessDbDep`` whose
# customer session fence refuses the internal ``X-Dev-User-Id`` header on the
# PostgreSQL lane (``customer_fence.customer_session_snapshot`` → 401
# SESSION_TOKEN_REQUIRED), so it cannot be driven by the dev header the READ
# routes use. ``_PgBusinessDb`` mirrors the production ``BusinessDb.write()``: it
# opens a *real* ``pg_transaction`` and re-raises the deferred denial audit
# exactly like ``fenced_pg_transaction`` (catch ``AuditedSecurityDenial`` →
# ``persist_security_denial`` → re-raise), injecting the acting ``CurrentUser``
# the fence would otherwise resolve from a Bearer session. The database is never
# mocked. The READ routes (``GET /api/independent/capabilities``,
# ``GET /api/studio/saved-prompts``) ride the unfenced ``get_database`` and
# authenticate the dev header on PG, so they need no override at all.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_dependency_overrides() -> Iterator[None]:
    """Guarantee a route double never leaks into the next test."""
    yield
    app.dependency_overrides.clear()


class _PgBusinessDb:
    """A ``BusinessDb`` double whose ``write()`` runs on a real PG transaction."""

    def __init__(self, current_actor: CurrentUser) -> None:
        self.current_actor = current_actor

    @contextmanager
    def write(
        self, *, isolation: object = None
    ) -> Iterator[tuple[BusinessConnection, CurrentUser]]:
        try:
            with pg_transaction() as raw:
                yield BusinessConnection.postgres(raw), self.current_actor
        except AuditedSecurityDenial as exc:
            persist_security_denial(exc)
            raise


def _override_business_db(actor: CurrentUser) -> _PgBusinessDb:
    """Register the fenced-write double for ``actor``; autouse fixture clears it."""
    holder = _PgBusinessDb(actor)

    def override() -> _PgBusinessDb:
        return holder

    app.dependency_overrides[get_business_db] = override
    return holder


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


def test_capabilities_report_extended_modes_disabled_by_default(scene: str) -> None:
    with pg_transaction() as raw:
        caps = read_independent_capabilities(BusinessConnection.postgres(raw))

    assert caps.i2v_enabled is True
    assert caps.t2v_enabled is False
    assert caps.r2v_enabled is False
    assert caps.last_frame_enabled is False
    assert caps.extended_modes_enabled is False
    assert caps.max_quantity >= 1


def test_capabilities_flip_with_runtime_flag(scene: str) -> None:
    _enable_extended_modes()

    with pg_transaction() as raw:
        caps = read_independent_capabilities(BusinessConnection.postgres(raw))

    assert caps.extended_modes_enabled is True
    assert caps.t2v_enabled is True
    assert caps.r2v_enabled is True
    assert caps.last_frame_enabled is True


def test_capabilities_route_serves_http_contract_on_pg(scene: str) -> None:
    """Restore the ``GET /api/independent/capabilities`` HTTP contract on PG.

    origin/main drove this through ``client.get``; the migration kept only the
    service call. The route rides the unfenced ``get_database`` dependency, so
    the real handler + real PG pool serve it with **zero** override — proving the
    route (not just the service) reads the migrated runtime_settings flag.
    """
    client = TestClient(app)
    response = client.get("/api/independent/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["i2v_enabled"] is True
    assert body["extended_modes_enabled"] is False
    assert body["t2v_enabled"] is False
    assert body["r2v_enabled"] is False
    assert isinstance(body["max_quantity"], int) and body["max_quantity"] >= 1

    _enable_extended_modes()
    flipped = client.get("/api/independent/capabilities").json()
    assert flipped["extended_modes_enabled"] is True
    assert flipped["t2v_enabled"] is True
    assert flipped["r2v_enabled"] is True
    assert flipped["last_frame_enabled"] is True


# ---------------------------------------------------------------------------
# Batch creation, idempotency and the mode/asset matrix
# ---------------------------------------------------------------------------


def test_i2v_batch_creation_reserves_seconds_and_marks_independent(scene: str) -> None:
    batch = _create(
        IndependentVideoRequest(
            mode="i2v",
            prompt_text="镜头缓缓推进，展示乡墅庭院的黄昏",
            first_frame_asset_id="frame-owned",
            output_duration_seconds=10,
            resolution="768P",
            ratio="16:9",
            quantity=2,
            idempotency_key="i2v-key-1",
        ),
        EMPLOYEE_1,
    )

    assert batch.project_id is None
    assert batch.creation_kind == "independent"
    assert batch.stale is False
    assert batch.progress.total_count == 2

    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        mode_rows = conn.execute(
            "SELECT generation_mode, billed_seconds FROM generation_tasks WHERE batch_id = %s",
            (batch.id,),
        ).fetchall()
    assert {str(row["generation_mode"]) for row in mode_rows} == {"I2V"}
    assert {int(row["billed_seconds"]) for row in mode_rows} == {10}
    assert _wallet("employee_1") == (980, 20)
    assert _ledger_count("RESERVE") == 2


def test_i2v_replay_returns_same_batch_and_conflicting_key_is_rejected(scene: str) -> None:
    request = IndependentVideoRequest(
        mode="i2v",
        prompt_text="黄昏庭院航拍",
        first_frame_asset_id="frame-owned",
        output_duration_seconds=8,
        quantity=1,
        idempotency_key="replay-key",
    )
    first = _create(request, EMPLOYEE_1)
    replay = _create(request, EMPLOYEE_1)
    assert replay.id == first.id
    # 增量验收①：同一幂等键重放新增收费任务=0 —— RESERVE 恰为 1，钱包差额未被二次扣减。
    assert _ledger_count("RESERVE") == 1
    assert _wallet("employee_1") == (992, 8)

    conflict = IndependentVideoRequest(
        mode="i2v",
        prompt_text="不一样的提示词",
        first_frame_asset_id="frame-owned",
        output_duration_seconds=8,
        quantity=1,
        idempotency_key="replay-key",
    )
    with pytest.raises(HTTPException) as exc:
        _create(conflict, EMPLOYEE_1)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "IDEMPOTENCY_CONFLICT"
    # 被拒的冲突请求同样不得新增收费任务（事务回滚干净）。
    assert _ledger_count("RESERVE") == 1
    assert _wallet("employee_1") == (992, 8)


def test_extended_modes_are_gated_until_verified(scene: str) -> None:
    gated = [
        IndependentVideoRequest(
            mode="t2v",
            prompt_text="纯文字生成",
            output_duration_seconds=6,
            quantity=1,
            idempotency_key="gate-t2v",
        ),
        IndependentVideoRequest(
            mode="i2v",
            prompt_text="带尾帧",
            first_frame_asset_id="frame-owned",
            last_frame_asset_id="frame-owned",
            output_duration_seconds=6,
            quantity=1,
            idempotency_key="gate-tail",
        ),
        IndependentVideoRequest(
            mode="r2v",
            prompt_text="参考生成",
            reference_asset_ids=["frame-owned"],
            output_duration_seconds=6,
            quantity=1,
            idempotency_key="gate-r2v",
        ),
    ]
    for request in gated:
        with pytest.raises(HTTPException) as exc:
            _create(request, EMPLOYEE_1)
        assert exc.value.status_code == 409, request.mode
        assert exc.value.detail["code"] == "EXTENDED_MODE_PENDING_VERIFICATION"


def test_extended_modes_open_after_verification(scene: str) -> None:
    _enable_extended_modes()

    t2v = _create(
        IndependentVideoRequest(
            mode="t2v",
            prompt_text="清晨山间别墅的延时摄影",
            output_duration_seconds=6,
            quantity=1,
            idempotency_key="t2v-open",
        ),
        EMPLOYEE_1,
    )
    r2v = _create(
        IndependentVideoRequest(
            mode="r2v",
            prompt_text="按照参考图生成别墅外观",
            reference_asset_ids=["frame-owned"],
            output_duration_seconds=6,
            quantity=1,
            idempotency_key="r2v-open",
        ),
        EMPLOYEE_1,
    )
    tail = _create(
        IndependentVideoRequest(
            mode="i2v",
            prompt_text="首尾帧过渡",
            first_frame_asset_id="frame-owned",
            last_frame_asset_id="frame-owned",
            output_duration_seconds=6,
            quantity=1,
            idempotency_key="tail-open",
        ),
        EMPLOYEE_1,
    )

    assert t2v.stale is False
    assert r2v.creation_kind == "independent"
    assert tail.progress.total_count == 1


def test_mode_asset_matrix_is_enforced(scene: str) -> None:
    _enable_extended_modes()

    with pytest.raises(HTTPException) as missing_first:
        _create(
            IndependentVideoRequest(
                mode="i2v",
                prompt_text="没有首帧",
                output_duration_seconds=8,
                quantity=1,
                idempotency_key="matrix-1",
            ),
            EMPLOYEE_1,
        )
    assert missing_first.value.status_code == 422
    assert missing_first.value.detail["code"] == "INDEPENDENT_FIRST_FRAME_REQUIRED"

    with pytest.raises(HTTPException) as t2v_with_frame:
        _create(
            IndependentVideoRequest(
                mode="t2v",
                prompt_text="文生却带首帧",
                first_frame_asset_id="frame-owned",
                output_duration_seconds=8,
                quantity=1,
                idempotency_key="matrix-2",
            ),
            EMPLOYEE_1,
        )
    assert t2v_with_frame.value.status_code == 422
    assert t2v_with_frame.value.detail["code"] == "INDEPENDENT_MODE_ASSET_CONFLICT"

    with pytest.raises(HTTPException) as r2v_without_ref:
        _create(
            IndependentVideoRequest(
                mode="r2v",
                prompt_text="无参考",
                output_duration_seconds=8,
                quantity=1,
                idempotency_key="matrix-3",
            ),
            EMPLOYEE_1,
        )
    assert r2v_without_ref.value.status_code == 422
    assert r2v_without_ref.value.detail["code"] == "INDEPENDENT_REFERENCE_REQUIRED"

    # 别人的素材：material_image 归属校验拒绝（PG 上是 AuditedSecurityDenial 404）。
    with pytest.raises(HTTPException) as foreign_asset:
        _create(
            IndependentVideoRequest(
                mode="i2v",
                prompt_text="别人的素材",
                first_frame_asset_id="frame-other",
                output_duration_seconds=8,
                quantity=1,
                idempotency_key="matrix-4",
            ),
            EMPLOYEE_1,
        )
    assert foreign_asset.value.status_code == 404

    with pytest.raises(HTTPException) as video_asset:
        _create(
            IndependentVideoRequest(
                mode="i2v",
                prompt_text="视频当首帧",
                first_frame_asset_id="asset-video",
                output_duration_seconds=8,
                quantity=1,
                idempotency_key="matrix-5",
            ),
            EMPLOYEE_1,
        )
    assert video_asset.value.status_code == 422
    assert video_asset.value.detail["code"] == "INDEPENDENT_ASSET_KIND_UNSUPPORTED"


def test_reference_images_reject_duplicates_and_more_than_capability_limit(scene: str) -> None:
    _enable_extended_modes()

    with pytest.raises(HTTPException) as duplicate:
        _create(
            IndependentVideoRequest(
                mode="r2v",
                prompt_text="严格校验参考图",
                reference_asset_ids=["frame-owned", "frame-owned"],
                output_duration_seconds=8,
                quantity=1,
                idempotency_key="reference-duplicate",
            ),
            EMPLOYEE_1,
        )
    assert duplicate.value.status_code == 422
    assert duplicate.value.detail["code"] == "INDEPENDENT_REFERENCE_DUPLICATE"

    # 超出能力上限（>4 张）由请求模型 max_length 拒绝（路由层表现为 422 too_long）。
    with pytest.raises(ValidationError):
        IndependentVideoRequest(
            mode="r2v",
            prompt_text="超量参考图",
            reference_asset_ids=[f"frame-{index}" for index in range(5)],
            output_duration_seconds=8,
            quantity=1,
            idempotency_key="reference-over-limit",
        )


def test_auditor_cannot_create_independent_tasks(scene: str) -> None:
    with pytest.raises(AuditedSecurityDenial) as exc:
        _create(
            IndependentVideoRequest(
                mode="i2v",
                prompt_text="审计员不可提交",
                first_frame_asset_id="frame-owned",
                output_duration_seconds=8,
                quantity=1,
                idempotency_key="auditor-key",
            ),
            AUDITOR_1,
        )
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Worker lifecycle: settle on success, release on confirmed failure
# ---------------------------------------------------------------------------


def test_worker_settles_independent_task_and_releases_on_failure(scene: str) -> None:
    batch = _create(
        IndependentVideoRequest(
            mode="i2v",
            prompt_text="首帧推进镜头",
            first_frame_asset_id="frame-owned",
            output_duration_seconds=10,
            quantity=2,
            idempotency_key="worker-key",
        ),
        EMPLOYEE_1,
    )

    processed = _run_worker("independent-worker")

    assert processed == 2
    assert _wallet("employee_1") == (980, 0)  # SETTLE：reserved 清零
    assert _ledger_count("SETTLE") == 2

    page = _list_batches(EMPLOYEE_1)
    independent_items = [item for item in page.items if item.id == batch.id]
    assert len(independent_items) == 1
    assert independent_items[0].creation_kind == "independent"
    assert independent_items[0].progress.progress_percent == 100

    other = _list_batches(EMPLOYEE_2)
    assert all(item.id != batch.id for item in other.items)

    detail = _get_batch(batch.id, EMPLOYEE_1)
    assert detail.project_id is None

    with pytest.raises(HTTPException) as denied:
        _get_batch(batch.id, EMPLOYEE_2)
    assert denied.value.status_code == 404


def test_independent_batches_never_leak_provider_names(scene: str) -> None:
    batch = _create(
        IndependentVideoRequest(
            mode="i2v",
            prompt_text="红线检查",
            first_frame_asset_id="frame-owned",
            output_duration_seconds=6,
            quantity=1,
            idempotency_key="redline-key",
        ),
        EMPLOYEE_1,
    )

    body = batch.model_dump_json().lower()
    assert "metaso" not in body
    assert "tikhub" not in body


def test_saved_prompts_aggregate_across_projects(scene: str) -> None:
    with psycopg.connect(scene, autocommit=True) as pg:
        pg.execute(
            "INSERT INTO users (id, username, display_name, role) "
            "VALUES ('u3', 'u3', 'U3', 'employee')"
        )
        pg.execute("INSERT INTO projects (id, owner_user_id, name) VALUES ('project_c', 'u3', 'C')")
        _executemany(
            pg,
            "INSERT INTO versions ("
            " id, project_id, kind, version_number, payload_json,"
            " created_by_user_id, scope, source, author_user_id"
            ") VALUES (%s, %s, 'saved_prompt', 1, %s, %s, 'user', 'reverse_prompt_revision', %s)",
            [
                (
                    "sp-1",
                    "project_a",
                    json.dumps({"name": "庭院黄昏", "prompt_text": "A 的提示词"}),
                    "employee_1",
                    "employee_1",
                ),
                (
                    "sp-2",
                    "project_b",
                    json.dumps({"name": "别人的", "prompt_text": "B 的提示词"}),
                    "employee_2",
                    "employee_2",
                ),
                (
                    "sp-3",
                    "project_c",
                    json.dumps({"name": "空文本", "prompt_text": ""}),
                    "u3",
                    "u3",
                ),
            ],
        )
        # 坏 payload_json 行（version_number=2 避开 (project,kind,version) 唯一键）：
        # 路由必须静默跳过（json.JSONDecodeError）而非 500。
        pg.execute(
            "INSERT INTO versions ("
            " id, project_id, kind, version_number, payload_json,"
            " created_by_user_id, scope, source, author_user_id"
            ") VALUES ('sp-bad', 'project_a', 'saved_prompt', 2, '{not-json',"
            " 'employee_1', 'user', 'reverse_prompt_revision', 'employee_1')"
        )

    # 独立创作页「导入提示词」数据源：跨项目聚合、仅作者本人、按时间倒序。
    # 恢复为 origin/main 驱动的真实路由（GET /api/studio/saved-prompts）：它走
    # 无栅栏的 get_database + get_current_user（PG 上认 dev header），零 override，
    # 因此断言的是生产 handler 本身（owner 过滤 / limit 钳制 / 坏 JSON 跳过 /
    # SavedPromptListPage 序列化），而非手抄一份它的 SQL 自证。
    client = TestClient(app)
    headers = {"X-Dev-User-Id": "employee_1"}
    response = client.get("/api/studio/saved-prompts", headers=headers)
    assert response.status_code == 200
    items = response.json()["items"]
    # 仅作者本人：排除 employee_2 的 sp-2、u3 的 sp-3；坏 JSON 行 sp-bad 被跳过。
    assert [item["id"] for item in items] == ["sp-1"]
    assert items[0]["name"] == "庭院黄昏"
    assert items[0]["prompt_text"] == "A 的提示词"
    assert items[0]["project_id"] == "project_a"

    # limit 钳制：<1 或 >100 都回落 50，仍只返回作者本人可见行。
    clamped_low = client.get("/api/studio/saved-prompts?limit=0", headers=headers).json()["items"]
    clamped_high = client.get("/api/studio/saved-prompts?limit=999", headers=headers).json()[
        "items"
    ]
    assert [item["id"] for item in clamped_low] == ["sp-1"]
    assert [item["id"] for item in clamped_high] == ["sp-1"]

    # 越权隔离：employee_2 只看到自己的 sp-2（owner 过滤由路由 actor.id 驱动）。
    other = client.get("/api/studio/saved-prompts", headers={"X-Dev-User-Id": "employee_2"}).json()[
        "items"
    ]
    assert [item["id"] for item in other] == ["sp-2"]


def test_cancel_independent_batch_releases_reserved_seconds(scene: str) -> None:
    batch = _create(
        IndependentVideoRequest(
            mode="i2v",
            prompt_text="排队中取消",
            first_frame_asset_id="frame-owned",
            output_duration_seconds=10,
            quantity=1,
            idempotency_key="cancel-key",
        ),
        EMPLOYEE_1,
    )
    assert _wallet("employee_1") == (990, 10)

    cancelled = _cancel_batch(batch.id, EMPLOYEE_1)

    assert cancelled.status == "CANCELLED"
    assert _wallet("employee_1") == (1000, 0)  # RELEASE：全额退还
    assert _ledger_count("RELEASE") == 1


def test_failed_independent_task_releases_credits(
    scene: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIDEO_REPLICA_FAKE_H3_OUTCOME", "provider_failed")
    batch = _create(
        IndependentVideoRequest(
            mode="i2v",
            prompt_text="供应商失败的回款",
            first_frame_asset_id="frame-owned",
            output_duration_seconds=6,
            quantity=1,
            idempotency_key="fail-key",
        ),
        EMPLOYEE_1,
    )

    _run_worker("fail-worker")

    assert _wallet("employee_1") == (1000, 0)  # RELEASE：失败不扣费
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        status_row = conn.execute(
            "SELECT status FROM generation_tasks WHERE batch_id = %s",
            (batch.id,),
        ).fetchone()
    assert status_row is not None
    assert str(status_row["status"]) == "FAILED"


def test_t2v_and_r2v_tasks_run_through_worker_with_protocol_payload(scene: str) -> None:
    _enable_extended_modes()
    _create(
        IndependentVideoRequest(
            mode="t2v",
            prompt_text="清晨山间别墅的延时摄影",
            output_duration_seconds=6,
            quantity=1,
            idempotency_key="t2v-worker",
        ),
        EMPLOYEE_1,
    )
    _create(
        IndependentVideoRequest(
            mode="r2v",
            prompt_text="按照参考图生成别墅外观",
            reference_asset_ids=["frame-owned"],
            output_duration_seconds=6,
            quantity=1,
            idempotency_key="r2v-worker",
        ),
        EMPLOYEE_1,
    )

    processed = _run_worker("mode-worker")

    assert processed == 2
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        rows = conn.execute(
            "SELECT generation_mode, provider_request_json FROM generation_tasks"
        ).fetchall()
    by_mode = {str(row["generation_mode"]): row for row in rows}
    t2v_request = json.loads(str(by_mode["T2V"]["provider_request_json"]))
    assert [item["type"] for item in t2v_request["content"]] == ["text"]

    r2v_request = json.loads(str(by_mode["R2V"]["provider_request_json"]))
    roles = [item.get("role") for item in r2v_request["content"][1:]]
    assert roles == ["reference_image"]
    assert r2v_request["content"][1]["name"] == "ref-1"
    assert "first_frame" not in roles and "last_frame" not in roles


def test_video_task_route_creates_batch_through_fenced_write_on_pg(scene: str) -> None:
    """Restore the ``POST /api/independent/video-tasks`` fenced-write HTTP contract.

    origin/main drove this through ``client.post``; the migration kept only the
    service call. The real ``get_business_db`` fence refuses the dev header on PG
    (401 SESSION_TOKEN_REQUIRED), so the ``_PgBusinessDb`` double mirrors the
    production ``BusinessDb.write()`` on a *real* ``pg_transaction``: the 201
    status, the ``BatchResult`` body and the wallet RESERVE all commit to
    PostgreSQL — the database is never mocked, only the acting user the
    Bearer-session fence would otherwise resolve.
    """
    _override_business_db(EMPLOYEE_1)
    client = TestClient(app)
    payload = {
        "mode": "i2v",
        "prompt_text": "路由建批：黄昏庭院航拍",
        "first_frame_asset_id": "frame-owned",
        "output_duration_seconds": 10,
        "quantity": 1,
        "idempotency_key": "route-i2v-1",
    }
    response = client.post("/api/independent/video-tasks", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["creation_kind"] == "independent"
    assert body["project_id"] is None
    assert body["progress"]["total_count"] == 1

    # fenced 写确实提交到真 PG（非 mock 持久化）：增量验收②成功建批预留一次。
    assert _wallet("employee_1") == (990, 10)
    assert _ledger_count("RESERVE") == 1

    # 同一幂等键经同一路由重放：新增收费任务=0，返回同一批次。
    replay = client.post("/api/independent/video-tasks", json=payload)
    assert replay.status_code == 201
    assert replay.json()["id"] == body["id"]
    assert _ledger_count("RESERVE") == 1
    assert _wallet("employee_1") == (990, 10)
