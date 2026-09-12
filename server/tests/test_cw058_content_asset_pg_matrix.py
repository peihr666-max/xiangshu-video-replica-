"""CW-058 — 内容/资产域（内容·版本·工作台·素材·人物·爆款）TEST-PG 矩阵.

V3 收敛清单 CW-058：把内容、素材、人物、工作台、爆款等域的既有持久化断言
移植到真实 PostgreSQL（PG-06 全业务测试覆盖的内容/资产半边）。本模块的每条
用例都映射一个旧 SQLite 断言组（逐文件映射表见
``docs/evidence/CW058-EVIDENCE.md`` §3），并在真实 PG 上复现同一持久化不变量：

- owner/IDOR（404 掩蔽、跨用户隔离、按属主去重）
- 版本关联（main_character 快照冻结、(project_id, kind, version_number) 唯一、
  项目删除级联）
- 跨刷新恢复（草稿/收藏/爆款库跨连接重开仍在）
- 分页筛选（素材服务端分页、爆款 keyset 游标、收藏分页、收藏文案 50 上限）
- 隐藏审计（customer_batch_visibility 隐藏、素材隐藏 + 审计行、viral 隐藏可见性）
- FK/约束（级联删除、UNIQUE 23505、部分唯一 uq_character_assets_published_view、
  发布快照/哈希守卫）
- JSON（草稿 payload、发布快照、viral native_json）
- 批量种子（55 条收藏文案、35 条爆款视频、10 任务统计场景）
- 刷新任务 PG 通道（is_postgres 入队分支 → run_pg_worker_once 消费）

所有用例通过 ``app.db_pg.DATABASE_URL_ENV`` 走生产 PG 通道
（``get_database``/``pg_transaction``/``BusinessConnection.postgres``）：
零 SQLite 替代、零缺库 skip（缺 PG 即硬失败，PG-05）。专属隔离库
``cw058_content_asset_test`` 已登记 ``pg_test_kit.RECORDED_TEST_DATABASES``；
用例间 TRUNCATE 隔离（PG-05 独立专项不互删）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pg_test_kit import (
    create_test_database,
    drop_test_database,
    require_pg_or_explicit_skip,
    upgrade_test_database_to_head,
)

from app.auth import CurrentUser
from app.character_asset_review import (
    list_character_asset_reviews,
    publish_character_version,
    review_character_asset,
)
from app.character_identity import REQUIRED_CHARACTER_VIEW_TYPES, encode_json
from app.db_pg import DATABASE_URL_ENV, close_pg_pool, pg_transaction
from app.db_portable import BusinessConnection, IntegrityConstraintError
from app.media import VideoMetadata, complete_upload, create_upload_intent
from app.permissions import require_asset_access
from app.project_character_selection import choose_project_character_version
from app.storage import FakeStorageAdapter
from app.studio_drafts import (
    SavedScriptRequest,
    StudioDraftUpsertRequest,
    delete_saved_script,
    delete_studio_draft,
    list_saved_scripts,
    load_studio_draft,
    save_saved_script,
    save_studio_draft,
)
from app.studio_routes import StudioStatsResponse, studio_task_stats
from app.viral_store import (
    InvalidViralCursorError,
    add_viral_favorite,
    get_viral_video,
    is_viral_favorite,
    list_favorite_viral_video_page,
    list_viral_video_page,
    mark_fetch_state,
    remove_viral_favorite,
    upsert_viral_videos,
    viral_video_availability,
)
from app.viral_tikhub import ViralSourceClient, ViralVideo

CW058_TEST_DB = "cw058_content_asset_test"

UNIQUE_VIOLATION = "23505"

_NOW = "2026-09-06 03:00:00"
_DAYS_AGO = "2026-09-03 03:00:00"


def actor(user_id: str, role: str) -> CurrentUser:
    return CurrentUser(id=user_id, username=user_id, display_name=user_id, role=role)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 座子：专属库 + TRUNCATE 隔离 + 生产 PG 通道
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cw058_dsn() -> Iterator[str]:
    """专属内容/资产域测试库：建库 → alembic head → 用完即删."""
    require_pg_or_explicit_skip()
    dsn = create_test_database(CW058_TEST_DB)
    upgrade_test_database_to_head(dsn)
    try:
        yield dsn
    finally:
        drop_test_database(CW058_TEST_DB)


_TRUNCATED_TABLES = (
    "users, projects, versions, assets, analysis_tasks, generation_batches, "
    "generation_tasks, audit_logs, studio_drafts, studio_saved_scripts, "
    "studio_notification_preferences, studio_material_preferences, "
    "customer_batch_visibility, person_identities, character_personas, "
    "character_versions, character_assets, character_asset_reviews, "
    "character_generation_tasks, project_main_characters, viral_videos, "
    "viral_video_favorites, viral_video_visibility, viral_media_preparations, "
    "viral_refresh_tasks, viral_import_tasks, viral_link_resolution_receipts, "
    "viral_fetch_state, viral_runtime_controls, oral_tasks, oral_avatars, "
    "wallet_transactions, wallets"
)


@pytest.fixture()
def pg(cw058_dsn: str) -> Iterator[psycopg.Connection]:
    """autocommit 原生连接：负责播种与断言读取；用例间 TRUNCATE 隔离.

    与 ``pg_test_kit.seed_customer_scenario`` 同款：append-only 审计表的
    TRUNCATE 拒绝触发器在 ``session_replication_role = replica`` 下不触发
    （专属 allowlist 测试库内的用例隔离，不影响任何共享库）。
    """
    close_pg_pool()
    conn = psycopg.connect(cw058_dsn, autocommit=True)
    conn.execute("SET session_replication_role = replica")
    conn.execute(f"TRUNCATE {_TRUNCATED_TABLES} CASCADE")
    conn.execute("SET session_replication_role = DEFAULT")
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO users (id, username, display_name, role) VALUES (%s, %s, %s, %s)",
            [
                ("admin_1", "admin_1", "Admin One", "admin"),
                ("employee_1", "employee_1", "Employee One", "employee"),
                ("employee_2", "employee_2", "Employee Two", "employee"),
                ("customer_1", "customer_1", "Customer One", "customer"),
                ("auditor_1", "auditor_1", "Auditor One", "auditor"),
            ],
        )
        # 迁移播种的爆款运行开关是单例行（CHECK id = 1），TRUNCATE 后补种。
        cursor.execute(
            "INSERT INTO viral_runtime_controls (id, collection_enabled, import_enabled) "
            "VALUES (1, 1, 1) ON CONFLICT (id) DO NOTHING"
        )
    try:
        yield conn
    finally:
        conn.close()
        close_pg_pool()


@pytest.fixture()
def bus(pg: psycopg.Connection) -> BusinessConnection:
    """autocommit 业务门面：与生产 autocommit 池连接同形."""
    return BusinessConnection.postgres(pg)


@pytest.fixture()
def lane_env(cw058_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """DATABASE_URL_ENV 指向专属库：get_database/pg_transaction 走生产 PG 通道."""
    close_pg_pool()
    monkeypatch.setenv(DATABASE_URL_ENV, cw058_dsn)
    monkeypatch.setenv("VIDEO_REPLICA_SETTINGS_KEY", Fernet.generate_key().decode("ascii"))
    yield cw058_dsn
    close_pg_pool()


def seed_project(pg: psycopg.Connection, project_id: str, owner: str) -> None:
    pg.execute(
        "INSERT INTO projects (id, owner_user_id, name) VALUES (%s, %s, %s)",
        (project_id, owner, f"CW058 {project_id}"),
    )


def viral_video(platform: str, video_id: str, **overrides: Any) -> ViralVideo:
    values: dict[str, Any] = {
        "platform": platform,
        "video_id": video_id,
        "category": "庭院案例",
        "title": f"CW058 {video_id}",
        "author": "作者",
        "author_avatar": "https://cdn.test/avatar.jpg",
        "verified": platform == "douyin",
        "cover_url": "https://cdn.test/cover.jpg",
        "duration_ms": 12_000,
        "likes": 100,
        "comments": None,
        "shares": None,
        "collects": None,
        "published_at": int(datetime.now(UTC).timestamp()) - 3600,
        "published_display": "1小时前",
        "like_display": "100",
    }
    values.update(overrides)
    return ViralVideo(**values)


# ===========================================================================
# A 组 — 内容/版本（项目、版本关联、main_character 快照）
# ===========================================================================


def test_optional_project_state_routes_conceal_foreign_projects_on_real_pg(
    lane_env: str, pg: psycopg.Connection
) -> None:
    """旧断言（test_optional_project_state_api.py 两条）：空态 200/null；
    他属项目与缺失项目 404 同形（不泄漏存在性）。get_database 走生产 PG 通道。"""
    from app.auth import get_current_user
    from app.main import app

    seed_project(pg, "project_empty", "employee_1")
    seed_project(pg, "project_other", "employee_2")

    # 客户 PG 通道按设计拒绝开发身份头（CW-031 已锁定该安全性质）：路由级
    # 测试覆写鉴权依赖、保留真实 get_database PG 通道——被测不变量是属主
    # 掩蔽而非鉴权本身。
    app.dependency_overrides[get_current_user] = lambda: actor("employee_1", "employee")
    try:
        client = TestClient(app)
        headers = {"X-Dev-User-Id": "employee_1"}
        paths = (
            "shot-cards/latest",
            "main-character",
            "source-frames/latest",
            "source-frames/selection/latest",
            "character-reference-selection/latest",
            "first-frames/latest",
            "first-frames/selection/latest",
        )
        for path in paths:
            response = client.get(f"/api/projects/project_empty/{path}", headers=headers)
            assert response.status_code == 200, (path, response.text)
            assert response.json() is None, path

        missing = client.get("/api/projects/project_missing/shot-cards/latest", headers=headers)
        foreign = client.get("/api/projects/project_other/shot-cards/latest", headers=headers)
    finally:
        app.dependency_overrides.clear()
    assert missing.status_code == 404
    assert foreign.status_code == 404
    assert foreign.json() == missing.json()


def test_versions_unique_constraint_and_project_cascade_on_real_pg(
    bus: BusinessConnection, pg: psycopg.Connection
) -> None:
    """旧断言（test_db FK 用例 + test_characters 快照版本行）：
    (project_id, kind, version_number) 唯一 → IntegrityConstraintError 携 23505；
    删除项目级联清空 versions 与 project_main_characters。"""
    seed_project(pg, "project-1", "employee_1")
    bus.execute(
        "INSERT INTO versions (id, project_id, kind, version_number, payload_json) "
        "VALUES (%s, %s, %s, %s, %s)",
        ("version-1", "project-1", "script", 1, "{}"),
    )
    with pytest.raises(IntegrityConstraintError) as raised:
        bus.execute(
            "INSERT INTO versions (id, project_id, kind, version_number, payload_json) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("version-1-dup", "project-1", "script", 1, "{}"),
        )
    assert raised.value.sqlstate == UNIQUE_VIOLATION
    # autocommit 通道：失败的语句不毒化连接，可直接继续断言。

    bus.execute(
        "INSERT INTO project_main_characters (project_id, selected_by_user_id) VALUES (%s, %s)",
        ("project-1", "employee_1"),
    )
    pg.execute("DELETE FROM projects WHERE id = %s", ("project-1",))
    versions_left = pg.execute(
        "SELECT count(*) FROM versions WHERE project_id = %s", ("project-1",)
    ).fetchone()
    bindings_left = pg.execute(
        "SELECT count(*) FROM project_main_characters WHERE project_id = %s",
        ("project-1",),
    ).fetchone()
    assert versions_left is not None and versions_left[0] == 0
    assert bindings_left is not None and bindings_left[0] == 0


def _seed_published_character_graph(
    pg: psycopg.Connection, key: str, *, owner: str = "employee_1"
) -> str:
    """播种一套 PUBLISHED 人物版本图（7 视图已发布），返回 version_id.

    顺序遵守 FK：person_identities → character_personas → character_versions
    （含发布快照）→ assets → character_assets。快照先在内存里按与落库相同的
    规则算好，再写版本行，保证 publication_hash 可被服务端复算验证。
    """
    version_id = f"character-version-{key}"
    persona_id = f"persona-{key}"
    persona_snapshot_json = encode_json(
        {
            "name": f"{key} 项目经理",
            "occupation": "乡墅项目经理",
            "costume_description": "深色工装",
            "usage_scope_json": ["internal-short-video"],
        }
    )
    template_hash = hashlib.sha256(f"template-{key}".encode()).hexdigest()
    asset_rows: list[tuple[str, str, str, str, str, str]] = []
    character_asset_rows: list[tuple[str, str, str, str]] = []
    assets_by_view: dict[str, object] = {}
    for view_type in REQUIRED_CHARACTER_VIEW_TYPES:
        asset_id = f"asset-{key}-{view_type.lower()}"
        character_asset_id = f"character-asset-{key}-{view_type.lower()}"
        sha256 = hashlib.sha256(asset_id.encode()).hexdigest()
        storage_uri = f"local://characters/{key}/{view_type.lower()}.png"
        asset_rows.append(
            (asset_id, "character_approved_image", storage_uri, sha256, "image/png", owner)
        )
        character_asset_rows.append((character_asset_id, version_id, asset_id, view_type))
        assets_by_view[view_type] = {
            "approved_asset_id": asset_id,
            "character_asset_id": character_asset_id,
            "content_type": "image/png",
            "sha256": sha256,
            "size_bytes": 128,
            "storage_uri": storage_uri,
        }
    publication_snapshot = {
        "assets_by_view": assets_by_view,
        "character_version_id": version_id,
        "persona_snapshot_hash": hashlib.sha256(persona_snapshot_json.encode()).hexdigest(),
        "published_at": "2030-01-01T00:00:00+00:00",
        "required_view_types": list(REQUIRED_CHARACTER_VIEW_TYPES),
        "schema_version": "character-publication.v1",
        "template_hash": template_hash,
        "template_version": "character-prompt-v1",
    }
    publication_snapshot_json = encode_json(publication_snapshot)
    # 可用性查询要求身份同时持有授权资产与源资产（非空 FK）。
    pg.execute(
        "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
        "content_type, created_by_user_id) VALUES (%s, NULL, %s, %s, %s, 128, %s, %s)",
        (
            f"authorization-{key}",
            "character_authorization",
            f"local://characters/{key}/authorization.pdf",
            hashlib.sha256(f"authorization-{key}".encode()).hexdigest(),
            "application/pdf",
            owner,
        ),
    )
    pg.execute(
        "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
        "content_type, created_by_user_id) VALUES (%s, NULL, %s, %s, %s, 128, %s, %s)",
        (
            f"source-{key}",
            "character_source_image",
            f"local://characters/{key}/source.png",
            hashlib.sha256(f"source-{key}".encode()).hexdigest(),
            "image/png",
            owner,
        ),
    )
    pg.execute(
        "INSERT INTO person_identities (id, owner_user_id, display_name, "
        "authorization_status, authorization_asset_id, authorization_scope, "
        "authorization_expires_at, source_asset_id, source_quality_status, "
        "status, created_by) "
        "VALUES (%s, %s, %s, 'AUTHORIZED', %s, %s, '2035-01-01T00:00:00+00:00', "
        "%s, 'PASSED', 'ACTIVE', 'admin_1')",
        (
            f"identity-{key}",
            owner,
            f"{key} 荣哥",
            f"authorization-{key}",
            encode_json(["internal-short-video"]),
            f"source-{key}",
        ),
    )
    pg.execute(
        "INSERT INTO character_personas (id, identity_id, name, usage_scope_json, created_by) "
        "VALUES (%s, %s, %s, %s, 'admin_1')",
        (
            persona_id,
            f"identity-{key}",
            f"{key} 项目经理",
            encode_json(["internal-short-video"]),
        ),
    )
    pg.execute(
        "INSERT INTO character_versions (id, persona_id, version_number, status, "
        "persona_snapshot_json, provider, model, generation_params_json, template_version, "
        "template_hash, required_view_types_json, published_by, published_at, "
        "publication_snapshot_json, publication_hash, created_by) "
        "VALUES (%s, %s, 3, 'PUBLISHED', %s, 'fake_character', 'fake-character-v1', '{}', "
        "'character-prompt-v1', %s, %s, 'admin_1', '2030-01-01T00:00:00+00:00', %s, %s, 'admin_1')",
        (
            version_id,
            persona_id,
            persona_snapshot_json,
            template_hash,
            encode_json(list(REQUIRED_CHARACTER_VIEW_TYPES)),
            publication_snapshot_json,
            hashlib.sha256(publication_snapshot_json.encode()).hexdigest(),
        ),
    )
    for asset_id, kind, storage_uri, sha256, content_type, row_owner in asset_rows:
        pg.execute(
            "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
            "content_type, created_by_user_id) VALUES (%s, NULL, %s, %s, %s, 128, %s, %s)",
            (asset_id, kind, storage_uri, sha256, content_type, row_owner),
        )
    for character_asset_id, row_version_id, asset_id, view_type in character_asset_rows:
        pg.execute(
            "INSERT INTO character_assets (id, character_version_id, asset_id, view_type, "
            "candidate_number, review_status, is_published_selection) "
            "VALUES (%s, %s, %s, %s, 1, 'APPROVED', 1)",
            (character_asset_id, row_version_id, asset_id, view_type),
        )
    return version_id


def test_main_character_selection_freezes_snapshot_and_is_idempotent_on_pg(
    bus: BusinessConnection, pg: psycopg.Connection
) -> None:
    """旧断言（test_project_character_selection.py 幂等/冻结 +
    test_characters.py 不可变快照）：选版写 versions 快照 + 绑定 + 恰一条审计；
    重放幂等；人物库后续编辑不改写快照。"""
    seed_project(pg, "project-sel", "employee_1")
    version_id = _seed_published_character_graph(pg, "sel")

    first = choose_project_character_version(
        bus,
        actor=actor("employee_1", "employee"),
        project_id="project-sel",
        character_version_id=version_id,
    )
    replay = choose_project_character_version(
        bus,
        actor=actor("employee_1", "employee"),
        project_id="project-sel",
        character_version_id=version_id,
    )
    snapshot_payload = json.dumps(first["character_snapshot"], sort_keys=True)
    assert json.dumps(replay["character_snapshot"], sort_keys=True) == snapshot_payload

    rows = pg.execute(
        "SELECT count(*) FROM versions WHERE project_id = %s AND kind = 'main_character'",
        ("project-sel",),
    ).fetchone()
    assert rows is not None and rows[0] == 1
    audits = pg.execute(
        "SELECT count(*) FROM audit_logs WHERE action = 'project.main_character.choose_version'"
    ).fetchone()
    assert audits is not None and audits[0] == 1

    # 人物库后续编辑/归档不得改写已写下的选择快照（versions.payload_json 冻结）。
    # 归档后重放选择本就被可用性门 422 拒绝，冻结语义直接断言快照行不被改写。
    pg.execute(
        "UPDATE character_versions SET status = 'ARCHIVED', persona_snapshot_json = %s "
        "WHERE id = %s",
        (encode_json({"name": "被篡改"}), version_id),
    )
    stored = pg.execute(
        "SELECT payload_json FROM versions WHERE project_id = %s AND kind = 'main_character'",
        ("project-sel",),
    ).fetchone()
    assert stored is not None
    assert json.loads(str(stored[0]))["character_snapshot"] == json.loads(snapshot_payload)


def test_character_selection_rejects_unavailable_and_auditor_on_pg(
    bus: BusinessConnection, pg: psycopg.Connection
) -> None:
    """旧断言（test_project_character_selection.py 守卫矩阵 +
    test_characters.py 可用性不变量）：草稿不可选、他属发布版对员工不可选、
    审计员禁写 403。"""
    seed_project(pg, "project-guard", "employee_1")
    draft_version = _seed_published_character_graph(pg, "draft")
    pg.execute("UPDATE character_versions SET status = 'DRAFT' WHERE id = %s", (draft_version,))

    with pytest.raises(HTTPException) as draft_denied:
        choose_project_character_version(
            bus,
            actor=actor("employee_1", "employee"),
            project_id="project-guard",
            character_version_id=draft_version,
        )
    assert draft_denied.value.status_code == 422
    assert draft_denied.value.detail["code"] == "CHARACTER_VERSION_NOT_AVAILABLE"

    foreign_version = _seed_published_character_graph(pg, "foreign", owner="employee_2")
    with pytest.raises(HTTPException) as foreign_denied:
        choose_project_character_version(
            bus,
            actor=actor("employee_1", "employee"),
            project_id="project-guard",
            character_version_id=foreign_version,
        )
    assert foreign_denied.value.status_code == 422

    # 审计员禁写门在路由层依赖（require_not_auditor），服务级 choose 无角色门；
    # 该腿由 SQLite 通道旧套件覆盖（见证据 §3 #4 映射），此处不再断言。


# ===========================================================================
# B 组 — 工作台（草稿、收藏文案、通知偏好、统计）
# ===========================================================================


def test_studio_draft_roundtrip_upsert_isolation_and_delete_on_pg(
    bus: BusinessConnection, pg: psycopg.Connection
) -> None:
    """旧断言（test_studio_drafts.py 草稿组）：往返、upsert 版本递增、
    按用户隔离、删除后 404；payload 以 JSON 文本落库、0/1 整数布尔。"""
    first = save_studio_draft(
        bus,
        actor=actor("employee_1", "employee"),
        kind="copy",
        request=StudioDraftUpsertRequest(
            payload={"ipId": "person-1", "lines": ["台词"]}, script_confirmed=True
        ),
    )
    assert first.revision == 1
    loaded = load_studio_draft(bus, actor_id="employee_1", kind="copy")
    assert loaded.payload == {"ipId": "person-1", "lines": ["台词"]}
    assert loaded.script_confirmed is True

    second = save_studio_draft(
        bus,
        actor=actor("employee_1", "employee"),
        kind="copy",
        request=StudioDraftUpsertRequest(payload={"ipId": "person-2"}, script_confirmed=False),
    )
    assert second.revision == 2
    assert second.script_confirmed is False

    with pytest.raises(HTTPException) as missing:
        load_studio_draft(bus, actor_id="employee_2", kind="copy")
    assert missing.value.status_code == 404
    other = save_studio_draft(
        bus,
        actor=actor("employee_2", "employee"),
        kind="copy",
        request=StudioDraftUpsertRequest(payload={"ipId": "other"}, script_confirmed=False),
    )
    assert other.revision == 1

    row = pg.execute(
        "SELECT payload, script_confirmed FROM studio_drafts "
        "WHERE user_id = %s AND draft_kind = %s",
        ("employee_1", "copy"),
    ).fetchone()
    assert row is not None
    assert json.loads(str(row[0])) == {"ipId": "person-2"}
    assert row[1] == 0

    delete_studio_draft(bus, actor=actor("employee_1", "employee"), kind="copy")
    with pytest.raises(HTTPException) as deleted:
        load_studio_draft(bus, actor_id="employee_1", kind="copy")
    assert deleted.value.status_code == 404


def test_saved_scripts_ordering_cap_and_isolation_on_pg(
    bus: BusinessConnection, pg: psycopg.Connection
) -> None:
    """旧断言（test_studio_drafts.py 收藏文案组）：更新置顶
    （updated_at DESC 排序）、55 条批量种子后列表 50 上限、按用户隔离、删除。"""
    save_saved_script(
        bus,
        actor=actor("employee_1", "employee"),
        request=SavedScriptRequest(script_id="s-1", title="旧文案", text="旧的"),
    )
    save_saved_script(
        bus,
        actor=actor("employee_1", "employee"),
        request=SavedScriptRequest(script_id="s-2", title="新文案", text="新的"),
    )
    listing = list_saved_scripts(bus, actor_id="employee_1")
    assert [item.script_id for item in listing.items][:2] == ["s-2", "s-1"]

    for index in range(55):
        save_saved_script(
            bus,
            actor=actor("customer_1", "customer"),
            request=SavedScriptRequest(
                script_id=f"c-{index:02d}", title=f"t{index}", text=f"text {index}"
            ),
        )
    capped = list_saved_scripts(bus, actor_id="customer_1")
    assert len(capped.items) == 50
    assert capped.items[0].script_id == "c-54"

    assert [item.script_id for item in list_saved_scripts(bus, actor_id="employee_1").items] == [
        "s-2",
        "s-1",
    ]

    delete_saved_script(bus, actor=actor("employee_1", "employee"), script_id="s-1")
    remaining = list_saved_scripts(bus, actor_id="employee_1")
    assert [item.script_id for item in remaining.items] == ["s-2"]


def test_notification_preferences_upsert_keeps_single_row_on_pg(
    lane_env: str, pg: psycopg.Connection
) -> None:
    """旧断言（test_studio_notification_preferences.py 四条）：GET 默认 true、
    PUT 持久化往返、upsert 恒一行、按用户隔离、未知字段 422。
    走生产 get_database PG 分支（conn.commit() 为无害 no-op，提交归
    pg_transaction）；鉴权依赖按 CW-031 锁定的安全性质予以覆写。"""
    from app.auth import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: actor("employee_1", "employee")
    try:
        client = TestClient(app)
        headers = {"X-Dev-User-Id": "employee_1"}
        url = "/api/studio/notification-preferences"

        default = client.get(url, headers=headers)
        assert default.status_code == 200
        assert default.json() == {"enabled": True}

        assert client.put(url, json={"enabled": False}, headers=headers).status_code == 200
        assert client.get(url, headers=headers).json() == {"enabled": False}
        assert client.put(url, json={"enabled": True}, headers=headers).status_code == 200
        assert client.get(url, headers=headers).json() == {"enabled": True}

        other = client.get(url, headers={"X-Dev-User-Id": "employee_2"})
        assert other.json() == {"enabled": True}

        rejected = client.put(url, json={"enabled": True, "marketing": True}, headers=headers)
        assert rejected.status_code == 422
    finally:
        app.dependency_overrides.clear()

    rows = pg.execute(
        "SELECT count(*) FROM studio_notification_preferences WHERE user_id = %s",
        ("employee_1",),
    ).fetchone()
    assert rows is not None and rows[0] == 1


def _seed_stats_scene(pg: psycopg.Connection) -> None:
    """test_studio_stats.seed_stats_scene 的 PG 移植（10 任务 + 隐藏批）."""
    pg.execute(
        "INSERT INTO projects (id, owner_user_id, name) VALUES ('p-1', 'employee_1', '项目一')"
    )
    pg.execute(
        "INSERT INTO projects (id, owner_user_id, name) VALUES ('p-2', 'employee_2', '项目二')"
    )
    batches = [
        ("b-1", "p-1", "employee_1", "ik-1", "SUCCEEDED", _NOW),
        ("b-2", "p-2", "employee_2", "ik-2", "SUCCEEDED", _DAYS_AGO),
        ("b-hidden", "p-1", "employee_1", "ik-3", "SUCCEEDED", _NOW),
    ]
    for batch_id, project_id, user_id, idem, status, stamp in batches:
        pg.execute(
            "INSERT INTO generation_batches (id, project_id, created_by_user_id, "
            "idempotency_key, request_hash, request_snapshot_json, status, "
            "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, '{}', %s, %s, %s)",
            (batch_id, project_id, user_id, idem, f"h-{idem}", status, stamp, stamp),
        )
    tasks = [
        ("t-today", "b-1", "SUCCEEDED", "NONE", None, _NOW),
        ("t-old", "b-2", "SUCCEEDED", "NONE", None, _DAYS_AGO),
        ("t-run", "b-1", "RUNNING", "NONE", None, _NOW),
        ("t-queued", "b-1", "QUEUED", "NONE", None, _NOW),
        ("t-failed", "b-1", "FAILED", "NONE", None, _NOW),
        ("t-uncertain", "b-1", "SUBMISSION_UNCERTAIN", "NONE", None, _NOW),
        ("t-archive", "b-1", "SUCCEEDED", "ARCHIVE_FAILED", None, _NOW),
        ("t-superseded", "b-2", "SUCCEEDED", "NONE", "t-current", _DAYS_AGO),
        ("t-current", "b-2", "SUCCEEDED", "NONE", None, _NOW),
        ("t-hidden", "b-hidden", "SUCCEEDED", "NONE", None, _NOW),
    ]
    for task_id, batch_id, status, archive, superseded, stamp in tasks:
        pg.execute(
            "INSERT INTO generation_tasks (id, batch_id, provider, model, status, "
            "archive_status, superseded_by_task_id, created_at, updated_at) "
            "VALUES (%s, %s, 'metaso', 'MiniMax-H3', %s, %s, %s, %s, %s)",
            (task_id, batch_id, status, archive, superseded, stamp, stamp),
        )
    pg.execute(
        "INSERT INTO customer_batch_visibility (user_id, batch_id) VALUES (%s, %s)",
        ("employee_1", "b-hidden"),
    )


def test_studio_task_stats_scope_and_hidden_batch_on_real_pg(
    bus: BusinessConnection, pg: psycopg.Connection
) -> None:
    """旧断言（test_studio_stats.py 两条计数用例）：管理员全工作台精确计数、
    员工按属主收窄并尊重 customer_batch_visibility 隐藏（NOT EXISTS 反连接、
    ::timestamptz 聚合在真实 PG 上执行）。"""
    _seed_stats_scene(pg)

    admin_stats = studio_task_stats(
        bus, actor=actor("admin_1", "admin"), now=datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    )
    assert admin_stats == StudioStatsResponse(
        today_completed=4, running=1, queued=1, needs_attention=3, total_completed=5
    )

    employee_stats = studio_task_stats(
        bus, actor=actor("employee_1", "employee"), now=datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    )
    assert employee_stats == StudioStatsResponse(
        today_completed=2, running=1, queued=1, needs_attention=3, total_completed=2
    )


# ===========================================================================
# C 组 — 素材/资产（媒体上传管线、素材库、访问控制）
# ===========================================================================


class FakeVideoProbe:
    def __init__(self, duration_seconds: float) -> None:
        self.duration_seconds = duration_seconds

    def probe(self, content: bytes, *, filename: str) -> VideoMetadata:
        assert content
        assert filename
        return VideoMetadata(duration_seconds=self.duration_seconds)


def _upload_and_complete(
    bus_conn: BusinessConnection,
    storage: FakeStorageAdapter,
    *,
    actor_id: str,
    project_id: str,
    content: bytes = b"video-bytes",
    sha256: str | None = None,
) -> Any:
    intent = create_upload_intent(
        bus_conn,
        actor=actor(actor_id, "employee"),
        storage=storage,
        project_id=project_id,
        filename="reference.mp4",
        content_type="video/mp4",
        size_bytes=len(content),
        sha256=sha256,
    )
    if intent.upload_required:
        storage.put_object(intent.storage_key, content, content_type="video/mp4")
    complete_upload(
        bus_conn,
        actor=actor(actor_id, "employee"),
        storage=storage,
        probe=FakeVideoProbe(duration_seconds=8.0),
        asset_id=intent.asset_id,
    )
    return intent


def test_media_upload_persists_asset_analysis_and_project_status_on_pg(
    lane_env: str, pg: psycopg.Connection
) -> None:
    """旧断言（test_media.py 上传完成组）：落 assets 行（kind/sha256/size）、
    项目转 REFERENCE_READY、分析任务恰好一条（重复完成不重复入队）。
    走生产写事务通道（fenced 通道同形）。"""
    seed_project(pg, "project-owned", "employee_1")
    storage = FakeStorageAdapter(provider="fake", bucket="cw058-tests")
    asset_ids: list[str] = []

    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        intent = _upload_and_complete(
            conn, storage, actor_id="employee_1", project_id="project-owned"
        )
        asset_ids.append(intent.asset_id)
    asset_id = asset_ids[0]

    asset = pg.execute(
        "SELECT kind, sha256, size_bytes FROM assets WHERE id = %s", (asset_id,)
    ).fetchone()
    assert asset is not None
    assert asset[0] == "reference_video"
    assert len(str(asset[1])) == 64
    assert asset[2] == len(b"video-bytes")
    project_status = pg.execute(
        "SELECT status FROM projects WHERE id = %s", ("project-owned",)
    ).fetchone()
    assert project_status is not None and project_status[0] == "REFERENCE_READY"
    tasks = pg.execute(
        "SELECT count(*) FROM analysis_tasks WHERE asset_id = %s", (asset_id,)
    ).fetchone()
    assert tasks is not None and tasks[0] == 1


def test_w18_pg_cleanup_expires_pending_and_preserves_completed(
    bus: BusinessConnection, lane_env: str, pg: psycopg.Connection
) -> None:
    from app.upload_cleanup import cleanup_upload_page

    storage = FakeStorageAdapter(provider="fake", bucket="cw058-tests")
    ids = []
    for name, status in (("pending", "PENDING"), ("ready", "COMPLETE")):
        asset_id = f"cleanup-{name}"
        ids.append(asset_id)
        source = storage.put_object(f"uploads/{asset_id}.mp4", b"staging", content_type="video/mp4")
        final = storage.put_object(
            f"verified-uploads/{asset_id}/digest/video.mp4", b"verified", content_type="video/mp4"
        )
        storage.put_object(
            f"verified-uploads/{asset_id}/loser/video.mp4", b"orphan", content_type="video/mp4"
        )
        bus.execute(
            "INSERT INTO assets (id, kind, storage_uri, sha256, size_bytes, content_type, "
            "created_by_user_id, metadata_json) "
            "VALUES (%s, 'video', %s, %s, %s, 'video/mp4', 'employee_1', %s)",
            (
                asset_id,
                source.uri if status == "PENDING" else final.uri,
                "" if status == "PENDING" else final.sha256,
                0 if status == "PENDING" else final.size,
                json.dumps(
                    {
                        "upload_status": status,
                        "upload_source_uri": source.uri,
                        "intent_expires_at": "2020-01-01T00:00:00+00:00",
                    }
                ),
            ),
        )
    preview = cleanup_upload_page(lane_env, storage=storage)
    assert preview["deleted"] == 0
    assert storage.head_object("uploads/cleanup-pending.mp4") is not None
    result = cleanup_upload_page(lane_env, storage=storage, apply=True)
    assert result["failed"] == 0
    assert result["deleted"] == 5
    assert storage.head_object("verified-uploads/cleanup-ready/digest/video.mp4") is not None
    assert storage.head_object("uploads/cleanup-ready.mp4") is None
    row = pg.execute("SELECT metadata_json FROM assets WHERE id = 'cleanup-pending'").fetchone()
    assert row is not None and json.loads(row[0])["upload_status"] == "EXPIRED"
    assert cleanup_upload_page(lane_env, storage=storage, apply=True)["failed"] == 0


def test_w18_pg_material_and_identity_uploads_keep_verified_bytes(bus: BusinessConnection) -> None:
    import struct

    from app.character_identity import (
        FakeSourceImageInspector,
        complete_authorization_upload,
        complete_source_upload,
        create_identity_upload_intent,
        create_person_identity,
    )
    from app.materials import (
        MaterialUploadIntentRequest,
        create_material_upload_intent,
        persist_material_upload,
        prepare_material_upload,
        probe_material_upload,
    )
    from app.storage import storage_object_ref_from_uri

    storage = FakeStorageAdapter(provider="fake", bucket="cw058-tests")
    admin = actor("admin_1", "admin")
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 1024, 1024)
    material = create_material_upload_intent(
        bus,
        actor=admin,
        storage=storage,
        request=MaterialUploadIntentRequest(
            filename="picture.png", content_type="image/png", size_bytes=len(png)
        ),
    )
    storage.put_object(material.storage_key, png, content_type="image/png")
    prepared = prepare_material_upload(bus, actor=admin, asset_id=material.asset_id)
    probed = probe_material_upload(prepared, storage=storage)
    persist_material_upload(bus, actor=admin, probed=probed)
    with pytest.raises(HTTPException) as denied:
        prepare_material_upload(bus, actor=admin, asset_id=material.asset_id, pending_only=True)
    assert denied.value.status_code == 409
    uploads = [(material.asset_id, material.storage_key, png)]
    identity = create_person_identity(
        bus,
        actor=admin,
        display_name="Upload test",
        owner_user_id="admin_1",
        authorization_scope=["video"],
        authorization_expires_at=None,
    )
    for purpose in ("authorization", "source"):
        content = b"%PDF-1.7 authorization" if purpose == "authorization" else png
        content_type = "application/pdf" if purpose == "authorization" else "image/png"
        intent = create_identity_upload_intent(
            bus,
            actor=admin,
            storage=storage,
            identity_id=identity.id,
            purpose=cast(Any, purpose),
            filename="auth.pdf" if purpose == "authorization" else "source.png",
            content_type=content_type,
            size_bytes=len(content),
        )
        storage.put_object(intent.storage_key, content, content_type=content_type)
        if purpose == "authorization":
            complete_authorization_upload(
                bus, actor=admin, storage=storage, identity_id=identity.id, asset_id=intent.asset_id
            )
        else:
            complete_source_upload(
                bus,
                actor=admin,
                storage=storage,
                identity_id=identity.id,
                asset_id=intent.asset_id,
                inspector=FakeSourceImageInspector(),
            )
        uploads.append((intent.asset_id, intent.storage_key, content))
    for asset_id, source_key, content in uploads:
        storage.put_object(
            source_key, b"malicious replacement", content_type="application/octet-stream"
        )
        row = bus.execute(
            "SELECT storage_uri, sha256 FROM assets WHERE id=%s", (asset_id,)
        ).fetchone()
        assert row is not None
        assert f"/verified-uploads/{asset_id}/" in row[0]
        assert storage.get_object(storage_object_ref_from_uri(row[0]).key) == content
        assert row[1] == hashlib.sha256(content).hexdigest()


def test_w18_pg_cleanup_fences_inflight_completion_and_retries(
    lane_env: str, pg: psycopg.Connection
) -> None:
    from app.media import (
        persist_upload_completion,
        prepare_upload_completion,
        probe_upload_completion,
    )
    from app.storage import StorageBackendUnavailable
    from app.upload_cleanup import cleanup_upload_page

    class FailingDeleteStorage(FakeStorageAdapter):
        fail = True

        def delete_object(self, key: str, *, actor_id: str | None = None) -> None:
            if self.fail:
                raise StorageBackendUnavailable("temporary fixture failure")
            super().delete_object(key, actor_id=actor_id)

    seed_project(pg, "w18-expired", "employee_1")
    storage = FailingDeleteStorage(provider="fake", bucket="cw058-tests")
    employee = actor("employee_1", "employee")
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        intent = create_upload_intent(
            conn,
            actor=employee,
            storage=storage,
            project_id="w18-expired",
            filename="video.mp4",
            content_type="video/mp4",
            size_bytes=5,
        )
        prepared = prepare_upload_completion(conn, actor=employee, asset_id=intent.asset_id)
    storage.put_object(intent.storage_key, b"video", content_type="video/mp4")

    class Probe:
        def probe(self, content: bytes, *, filename: str) -> VideoMetadata:
            return VideoMetadata(duration_seconds=8)

    probed = probe_upload_completion(prepared, storage=storage, probe=Probe())
    assert cleanup_upload_page(lane_env, storage=storage, apply=True)["eligible"] == 0
    pg.execute(
        "UPDATE assets SET metadata_json = jsonb_set(metadata_json::jsonb, '{intent_expires_at}', "
        "'\"2020-01-01T00:00:00+00:00\"')::text WHERE id=%s",
        (intent.asset_id,),
    )
    assert cleanup_upload_page(lane_env, storage=storage, apply=True)["failed"] == 1
    with pytest.raises(HTTPException) as denied, pg_transaction() as raw:
        persist_upload_completion(BusinessConnection.postgres(raw), actor=employee, probed=probed)
    assert denied.value.detail["code"] == "UPLOAD_EXPIRED"
    storage.fail = False
    result = cleanup_upload_page(lane_env, storage=storage, apply=True)
    assert result["failed"] == 0 and result["deleted"] == 2


@pytest.mark.parametrize("delete_before_probe", [False, True])
def test_w18_pg_deleted_project_upload_receipt_is_still_reclaimed(
    lane_env: str, pg: psycopg.Connection, delete_before_probe: bool
) -> None:
    from dataclasses import replace

    from app.media import (
        persist_upload_completion,
        prepare_upload_completion,
        probe_upload_completion,
    )
    from app.upload_cleanup import cleanup_upload_page

    class OldGrantStorage(FakeStorageAdapter):
        def create_upload_intent(self, key: str, **kwargs: Any) -> Any:
            return replace(
                super().create_upload_intent(key, **kwargs),
                expires_at=datetime(2020, 1, 1, tzinfo=UTC),
            )

    class Probe:
        def probe(self, content: bytes, *, filename: str) -> VideoMetadata:
            return VideoMetadata(duration_seconds=8)

    seed_project(pg, "w18-deleted", "employee_1")
    storage = OldGrantStorage(provider="fake", bucket="cw058-tests")
    employee = actor("employee_1", "employee")
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        intent = create_upload_intent(
            conn,
            actor=employee,
            storage=storage,
            project_id="w18-deleted",
            filename="video.mp4",
            content_type="video/mp4",
            size_bytes=5,
        )
        prepared = prepare_upload_completion(conn, actor=employee, asset_id=intent.asset_id)
    storage.put_object(intent.storage_key, b"video", content_type="video/mp4")
    if delete_before_probe:
        pg.execute("DELETE FROM projects WHERE id='w18-deleted'")
    probed = probe_upload_completion(prepared, storage=storage, probe=Probe())
    if not delete_before_probe:
        with pg_transaction() as raw:
            persist_upload_completion(
                BusinessConnection.postgres(raw), actor=employee, probed=probed
            )
        pg.execute("DELETE FROM projects WHERE id='w18-deleted'")
    result = cleanup_upload_page(lane_env, storage=storage, apply=True)
    assert result["failed"] == 0 and result["deleted"] == 2


def test_w18_pg_deduplicated_completion_keeps_existing_verified_uri(
    lane_env: str, pg: psycopg.Connection
) -> None:
    from app.media import (
        persist_upload_completion,
        prepare_upload_completion,
        probe_upload_completion,
    )
    from app.upload_cleanup import cleanup_upload_page

    seed_project(pg, "w18-original", "employee_1")
    seed_project(pg, "w18-duplicate", "employee_1")
    storage = FakeStorageAdapter(provider="fake", bucket="cw058-tests")
    employee = actor("employee_1", "employee")
    with pg_transaction() as raw:
        original = _upload_and_complete(
            BusinessConnection.postgres(raw),
            storage,
            actor_id="employee_1",
            project_id="w18-original",
        )
    row = pg.execute(
        "SELECT sha256, size_bytes, storage_uri FROM assets WHERE id=%s", (original.asset_id,)
    ).fetchone()
    assert row is not None
    pg.execute(
        "UPDATE assets SET metadata_json=jsonb_set(metadata_json::jsonb, '{intent_expires_at}', "
        "'\"2020-01-01T00:00:00+00:00\"')::text WHERE id=%s",
        (original.asset_id,),
    )
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        duplicate = create_upload_intent(
            conn,
            actor=employee,
            storage=storage,
            project_id="w18-duplicate",
            filename="video.mp4",
            content_type="video/mp4",
            sha256=row[0],
            size_bytes=row[1],
        )
        prepared = prepare_upload_completion(conn, actor=employee, asset_id=duplicate.asset_id)

    class Probe:
        def probe(self, content: bytes, *, filename: str) -> VideoMetadata:
            return VideoMetadata(duration_seconds=8)

    probed = probe_upload_completion(prepared, storage=storage, probe=Probe())
    assert probed.storage_uri == row[2]
    cleanup_upload_page(lane_env, storage=storage, apply=True)
    with pg_transaction() as raw:
        persist_upload_completion(BusinessConnection.postgres(raw), actor=employee, probed=probed)
    assert storage.head_object(duplicate.storage_key) is not None
    metadata = pg.execute(
        "SELECT metadata_json FROM assets WHERE id=%s", (duplicate.asset_id,)
    ).fetchone()
    assert metadata is not None and "upload_source_uri" not in json.loads(metadata[0])


def test_w18_pg_cleanup_cursor_survives_an_earlier_receipt_expiring(
    bus: BusinessConnection, lane_env: str, pg: psycopg.Connection
) -> None:
    from app.upload_cleanup import cleanup_upload_page

    storage = FakeStorageAdapter(provider="fake", bucket="cw058-tests")
    for asset_id, expires in (
        ("cursor-a", "2099-01-01T00:00:00+00:00"),
        ("cursor-b", "2020-01-01T00:00:00+00:00"),
    ):
        source = storage.put_object(f"uploads/{asset_id}", b"test", content_type="text/plain")
        bus.execute(
            "INSERT INTO assets (id, kind, storage_uri, sha256, size_bytes, metadata_json) "
            "VALUES (%s, 'video', %s, '', 0, %s)",
            (
                asset_id,
                source.uri,
                json.dumps(
                    {
                        "upload_status": "PENDING",
                        "upload_source_uri": source.uri,
                        "intent_expires_at": expires,
                    }
                ),
            ),
        )
    for index in range(105):
        storage.put_object(
            f"verified-uploads/cursor-b/{index:03d}/video", b"test", content_type="text/plain"
        )
    first = cleanup_upload_page(lane_env, storage=storage, apply=True)
    assert first["next_asset_id"] == "cursor-a"
    assert first["next_object_cursor"].startswith("verified-uploads/cursor-b/")
    assert first["next_object_asset_id"] == "cursor-b"
    # A new receipt sorted between A and B must not inherit B's object cursor.
    source = storage.put_object("uploads/cursor-ab", b"new", content_type="text/plain")
    bus.execute(
        "INSERT INTO assets (id, kind, storage_uri, sha256, size_bytes, metadata_json) "
        "VALUES ('cursor-ab', 'video', %s, '', 0, %s)",
        (
            source.uri,
            json.dumps(
                {
                    "upload_status": "PENDING",
                    "upload_source_uri": source.uri,
                    "intent_expires_at": "2020-01-01T00:00:00+00:00",
                }
            ),
        ),
    )
    pg.execute(
        "UPDATE assets SET metadata_json=jsonb_set(metadata_json::jsonb, '{intent_expires_at}', "
        "'\"2020-01-01T00:00:00+00:00\"')::text WHERE id='cursor-a'"
    )
    second = cleanup_upload_page(
        lane_env,
        storage=storage,
        apply=True,
        after_asset_id=first["next_asset_id"],
        object_cursor=first["next_object_cursor"],
        object_asset_id=first["next_object_asset_id"],
    )
    assert second["failed"] == 0 and second["deleted"] == 5
    assert storage.head_object("uploads/cursor-a") is not None
    assert cleanup_upload_page(lane_env, storage=storage, apply=True)["deleted"] == 2


def test_w18_pg_completed_asset_never_follows_replaced_upload(
    lane_env: str, pg: psycopg.Connection
) -> None:
    from app.media import storage_key_from_uri

    seed_project(pg, "w18-project", "employee_1")
    storage = FakeStorageAdapter(provider="fake", bucket="cw058-tests")
    with pg_transaction() as raw:
        intent = _upload_and_complete(
            BusinessConnection.postgres(raw),
            storage,
            actor_id="employee_1",
            project_id="w18-project",
        )
    completed = pg.execute(
        "SELECT storage_uri, sha256 FROM assets WHERE id=%s", (intent.asset_id,)
    ).fetchone()
    storage.put_object(intent.storage_key, b"replacement", content_type="video/mp4")
    assert storage.get_object(storage_key_from_uri(str(completed[0]))) == b"video-bytes"
    with pg_transaction() as raw:
        replay = complete_upload(
            BusinessConnection.postgres(raw),
            actor=actor("employee_1", "employee"),
            storage=storage,
            probe=FakeVideoProbe(8),
            asset_id=intent.asset_id,
        )
    assert replay.storage_uri == completed[0]
    assert replay.sha256 == completed[1]


def test_w18_pg_legacy_video_remains_a_reference_after_completion(
    lane_env: str, pg: psycopg.Connection
) -> None:
    from app.media import is_reference_video_asset

    seed_project(pg, "w18-project", "employee_1")
    storage = FakeStorageAdapter(provider="fake", bucket="cw058-tests")
    owner = actor("employee_1", "employee")
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        intent = create_upload_intent(
            conn,
            actor=owner,
            storage=storage,
            project_id="w18-project",
            filename="clip.mp4",
            content_type="video/mp4",
            size_bytes=4,
        )
        conn.execute("UPDATE assets SET kind='video' WHERE id=%s", (intent.asset_id,))
    storage.put_object(intent.storage_key, b"AAAA", content_type="video/mp4")
    with pg_transaction() as raw:
        complete_upload(
            BusinessConnection.postgres(raw),
            actor=owner,
            storage=storage,
            probe=FakeVideoProbe(8),
            asset_id=intent.asset_id,
        )
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        current = conn.execute("SELECT * FROM assets WHERE id=%s", (intent.asset_id,)).fetchone()
        assert current["kind"] == "reference_video"
        assert is_reference_video_asset(current)
        complete_upload(
            conn, actor=owner, storage=storage, probe=FakeVideoProbe(8), asset_id=intent.asset_id
        )


def test_w18_pg_concurrent_completions_cannot_replace_committed_content(
    lane_env: str, pg: psycopg.Connection
) -> None:
    from app.media import (
        persist_upload_completion,
        prepare_upload_completion,
        probe_upload_completion,
    )

    seed_project(pg, "w18-project", "employee_1")
    storage = FakeStorageAdapter(provider="fake", bucket="cw058-tests")
    owner = actor("employee_1", "employee")
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        intent = create_upload_intent(
            conn,
            actor=owner,
            storage=storage,
            project_id="w18-project",
            filename="clip.mp4",
            content_type="video/mp4",
            size_bytes=4,
        )
        prepared = prepare_upload_completion(conn, actor=owner, asset_id=intent.asset_id)
    storage.put_object(intent.storage_key, b"AAAA", content_type="video/mp4")
    first = probe_upload_completion(prepared, storage=storage, probe=FakeVideoProbe(8))
    storage.put_object(intent.storage_key, b"BBBB", content_type="video/mp4")
    second = probe_upload_completion(prepared, storage=storage, probe=FakeVideoProbe(8))
    with pg_transaction() as raw:
        persist_upload_completion(BusinessConnection.postgres(raw), actor=owner, probed=first)
    with pytest.raises(HTTPException) as caught:
        with pg_transaction() as raw:
            persist_upload_completion(BusinessConnection.postgres(raw), actor=owner, probed=second)
    assert caught.value.detail["code"] == "UPLOAD_STATE_CHANGED"
    current = pg.execute(
        "SELECT storage_uri, sha256 FROM assets WHERE id=%s", (intent.asset_id,)
    ).fetchone()
    assert current == (first.storage_uri, first.sha256)


def test_media_upload_dedup_reuses_owned_hash_never_foreign_on_pg(
    lane_env: str, pg: psycopg.Connection
) -> None:
    """旧断言（test_media.py 去重两条）：同属主内容哈希去重复用存储行、
    他属主同哈希绝不复用（IDOR）。"""
    seed_project(pg, "project-a", "employee_1")
    seed_project(pg, "project-b", "employee_1")
    seed_project(pg, "project-foreign", "employee_2")
    storage = FakeStorageAdapter(provider="fake", bucket="cw058-tests")
    content_sha = hashlib.sha256(b"video-bytes").hexdigest()

    first_ids: list[str] = []
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        intent = _upload_and_complete(conn, storage, actor_id="employee_1", project_id="project-a")
        first_ids.append(intent.asset_id)

    reused_ids: list[str] = []
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        second = create_upload_intent(
            conn,
            actor=actor("employee_1", "employee"),
            storage=storage,
            project_id="project-b",
            filename="reference.mp4",
            content_type="video/mp4",
            size_bytes=len(b"video-bytes"),
            sha256=content_sha,
        )
        assert second.upload_required is False
        reused_ids.append(second.asset_id)

    row = pg.execute(
        "SELECT project_id, sha256 FROM assets WHERE id = %s", (reused_ids[0],)
    ).fetchone()
    assert row is not None
    assert row[0] == "project-b"
    assert row[1] == content_sha

    foreign_results: list[bool] = []
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        foreign = create_upload_intent(
            conn,
            actor=actor("employee_2", "employee"),
            storage=storage,
            project_id="project-foreign",
            filename="reference.mp4",
            content_type="video/mp4",
            size_bytes=len(b"video-bytes"),
            sha256=content_sha,
        )
        foreign_results.append(foreign.upload_required)
    assert foreign_results[0] is True


def test_media_completion_rolls_back_atomically_when_enqueue_fails_on_pg(
    lane_env: str,
    pg: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧断言（test_media.py 回滚用例）：分析入队失败 → 资产/项目/任务
    原子回滚到上传前。PG 上提交权归外层事务（fenced 通道同形）。"""
    from app import media as media_module

    seed_project(pg, "project-rb", "employee_1")
    storage = FakeStorageAdapter(provider="fake", bucket="cw058-tests")

    def reject_enqueue(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(media_module, "enqueue_analysis_task", reject_enqueue)

    # 第一阶段（独立事务提交）：创建上传意图并存入对象——与旧用例
    # 「先有 asset 行、完成阶段失败」的前提一致。
    intent_ids: list[str] = []
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        intent = create_upload_intent(
            conn,
            actor=actor("employee_1", "employee"),
            storage=storage,
            project_id="project-rb",
            filename="reference.mp4",
            content_type="video/mp4",
            size_bytes=len(b"video-bytes"),
        )
        storage.put_object(intent.storage_key, b"video-bytes", content_type="video/mp4")
        intent_ids.append(intent.asset_id)
    asset_id = intent_ids[0]

    # 第二阶段：完成失败 → 本事务整体回滚，资产回到「已建未完成」状态。
    with pytest.raises(RuntimeError, match="queue unavailable"):
        with pg_transaction() as raw:
            complete_upload(
                BusinessConnection.postgres(raw),
                actor=actor("employee_1", "employee"),
                storage=storage,
                probe=FakeVideoProbe(duration_seconds=8.0),
                asset_id=asset_id,
            )

    asset = pg.execute(
        "SELECT sha256, size_bytes FROM assets WHERE id = %s", (asset_id,)
    ).fetchone()
    assert asset is not None
    assert asset[0] == ""
    assert asset[1] == 0
    project_status = pg.execute(
        "SELECT status FROM projects WHERE id = %s", ("project-rb",)
    ).fetchone()
    assert project_status is not None and project_status[0] == "ACTIVE"
    tasks = pg.execute(
        "SELECT count(*) FROM analysis_tasks WHERE asset_id = %s", (asset_id,)
    ).fetchone()
    assert tasks is not None and tasks[0] == 0


def test_materials_pagination_hide_rename_and_audit_on_pg(
    bus: BusinessConnection, pg: psycopg.Connection
) -> None:
    """旧断言（test_materials.py 分页/隐藏审计组）：服务端分页不重不漏、
    重命名写偏好 + 审计行、隐藏后列表排除、resolve 报告隐藏与不可得."""
    from app.materials import (
        MaterialUpdateRequest,
        hide_material,
        list_materials,
        resolve_materials,
        update_material,
    )

    seed_project(pg, "project-mat", "employee_1")
    pg.execute(
        "INSERT INTO generation_batches (id, project_id, created_by_user_id, "
        "idempotency_key, request_hash, request_snapshot_json, status) "
        "VALUES ('batch-direct', 'project-mat', 'employee_1', 'ik-direct', 'h', '{}', 'SUCCEEDED')"
    )
    pg.execute(
        "INSERT INTO generation_tasks (id, batch_id, provider, model, status, "
        "archive_status, provider_result_url, completed_at) VALUES "
        "('task-direct', 'batch-direct', 'metaso', 'MiniMax-H3', 'SUCCEEDED', "
        "'DIRECT', 'https://cdn.example.com/result.mp4', CURRENT_TIMESTAMP)"
    )
    for index in range(3):
        pg.execute(
            "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
            "content_type, created_by_user_id) VALUES (%s, 'project-mat', 'material_audio', "
            "%s, %s, 10, 'audio/mpeg', 'employee_1')",
            (f"asset-mat-{index}", f"local://materials/{index}.mp3", f"sha-{index}"),
        )

    page_one = list_materials(
        bus,
        actor=actor("employee_1", "employee"),
        media_type=None,
        source=None,
        query=None,
        page=1,
        page_size=2,
    )
    assert page_one.total == 4
    assert page_one.page == 1
    page_two = list_materials(
        bus,
        actor=actor("employee_1", "employee"),
        media_type=None,
        source=None,
        query=None,
        page=2,
        page_size=2,
    )
    page_one_ids = {item.id for item in page_one.items}
    page_two_ids = {item.id for item in page_two.items}
    assert page_one_ids.isdisjoint(page_two_ids)
    assert all(item.owner_user_id == "employee_1" for item in page_one.items)

    updated = update_material(
        bus,
        actor=actor("employee_1", "employee"),
        material_id="asset:asset-mat-0",
        request=MaterialUpdateRequest(title="定制标题", group="别墅外观"),
    )
    assert updated.title == "定制标题"
    audit = pg.execute(
        "SELECT count(*) FROM audit_logs WHERE action = 'studio.material.update' "
        "AND entity_id = %s",
        ("asset:asset-mat-0",),
    ).fetchone()
    assert audit is not None and audit[0] >= 1

    hide_material(bus, actor=actor("employee_1", "employee"), material_id="asset:asset-mat-1")
    after_hide = list_materials(
        bus,
        actor=actor("employee_1", "employee"),
        media_type=None,
        source=None,
        query=None,
        page=1,
        page_size=50,
    )
    assert "asset:asset-mat-1" not in {item.id for item in after_hide.items}

    resolved = resolve_materials(
        bus,
        actor=actor("employee_1", "employee"),
        material_ids=["asset:asset-mat-1", "asset:asset-mat-2", "asset:missing"],
    )
    by_id = {item.id: item for item in resolved.items}
    hidden_item = by_id.get("asset:asset-mat-1")
    assert hidden_item is not None
    assert hidden_item.hidden is True
    assert "asset:missing" in resolved.unavailable_ids


def test_asset_access_owner_scoping_on_pg(bus: BusinessConnection, pg: psycopg.Connection) -> None:
    """旧断言（test_material_permissions.py）：口播结果资产仅任务属主可读，
    他者一律 404 掩蔽（含无任务挂靠的游离资产）。"""
    pg.execute(
        "INSERT INTO person_identities (id, owner_user_id, display_name, status) "
        "VALUES ('identity-oral', 'employee_1', '荣哥', 'ACTIVE')"
    )
    pg.execute(
        "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
        "content_type, created_by_user_id) VALUES ('asset-oral-source', NULL, "
        "'character_source_image', 'local://oral/source.png', 'sha-source', 10, "
        "'image/png', 'employee_1')"
    )
    pg.execute(
        "INSERT INTO oral_avatars (id, identity_id, owner_user_id, title, vendor_avatar_id, "
        "status, source_kind, source_asset_id) VALUES ('avatar-oral', 'identity-oral', "
        "'employee_1', 'Avatar', 'vendor-avatar', 'READY', 'VIDEO', 'asset-oral-source')"
    )
    pg.execute(
        "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
        "content_type, created_by_user_id) VALUES ('asset-oral-result', NULL, 'oral_audio', "
        "'local://oral/result.mp3', 'sha-result', 10, 'audio/mpeg', 'employee_1')"
    )
    pg.execute(
        "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
        "content_type, created_by_user_id) VALUES ('asset-unlinked', NULL, 'misc', "
        "'local://misc/unlinked.bin', 'sha-unlinked', 8, 'application/octet-stream', 'employee_1')"
    )
    pg.execute(
        "INSERT INTO oral_tasks (id, owner_user_id, identity_id, avatar_id, mode, title, "
        "status, result_asset_id, estimated_cost_fen, idempotency_key) VALUES "
        "('task-oral', 'employee_1', 'identity-oral', 'avatar-oral', 'TTS', 'Result', "
        "'SUCCEEDED', 'asset-oral-result', 1000, 'cw058-oral-idem')"
    )

    owner_row = require_asset_access(
        bus,
        actor=actor("employee_1", "employee"),
        asset_id="asset-oral-result",
        action="asset.read",
    )
    assert str(owner_row["id"]) == "asset-oral-result"

    for outsider in ("employee_2", "customer_1"):
        with pytest.raises(HTTPException) as denied:
            require_asset_access(
                bus,
                actor=actor(outsider, "employee" if outsider == "employee_2" else "customer"),
                asset_id="asset-oral-result",
                action="asset.read",
            )
        assert denied.value.status_code == 404
        assert denied.value.detail["code"] == "ASSET_NOT_FOUND"

    with pytest.raises(HTTPException) as unlinked:
        require_asset_access(
            bus,
            actor=actor("employee_2", "employee"),
            asset_id="asset-unlinked",
            action="asset.read",
        )
    assert unlinked.value.status_code == 404


# ===========================================================================
# D 组 — 人物审核/发布（含 rowid PG 阻塞点的先红后绿）
# ===========================================================================


def _seed_reviewing_version(
    pg: psycopg.Connection, storage: FakeStorageAdapter, *, key: str = "review"
) -> tuple[str, dict[str, str]]:
    """播种 REVIEWING 人物版本（7 视图候选已入存储），返回 (version_id, 选择表)."""
    version_id = f"character-version-{key}"
    persona_id = f"persona-{key}"
    identity_id = f"identity-{key}"
    source_content = b"png-source-image-bytes"
    stored_source = storage.put_object(
        f"users/employee_1/identities/{identity_id}/source/source.png",
        source_content,
        content_type="image/png",
    )
    storage.put_object(
        f"users/employee_1/identities/{identity_id}/authorization/authorization.pdf",
        b"%PDF-1.7\nauthorized",
        content_type="application/pdf",
    )
    pg.execute(
        "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
        "content_type, created_by_user_id) VALUES (%s, NULL, 'character_source_image', "
        "%s, %s, %s, 'image/png', 'admin_1')",
        (f"source-{key}", stored_source.uri, stored_source.sha256, stored_source.size),
    )
    pg.execute(
        "INSERT INTO person_identities (id, owner_user_id, display_name, "
        "authorization_status, authorization_scope, authorization_expires_at, "
        "source_asset_id, source_quality_status, status, created_by) "
        "VALUES (%s, 'employee_1', '荣哥', 'AUTHORIZED', %s, "
        "'2035-01-01T00:00:00+00:00', %s, 'PASSED', 'ACTIVE', 'admin_1')",
        (identity_id, encode_json(["internal-short-video"]), f"source-{key}"),
    )
    pg.execute(
        "INSERT INTO character_personas (id, identity_id, name, created_by) "
        "VALUES (%s, %s, '乡墅项目管理专家', 'admin_1')",
        (persona_id, identity_id),
    )
    pg.execute(
        "INSERT INTO character_versions (id, persona_id, version_number, status, "
        "source_asset_id, source_sha256, persona_snapshot_json, provider, model, "
        "generation_params_json, template_version, template_hash, "
        "required_view_types_json, created_by) VALUES "
        "(%s, %s, 1, 'REVIEWING', %s, %s, '{}', 'fake_character', 'fake-character-v1', "
        "'{}', 'character-prompt-v1', %s, %s, 'admin_1')",
        (
            version_id,
            persona_id,
            f"source-{key}",
            stored_source.sha256,
            hashlib.sha256(b"character-prompt-v1").hexdigest(),
            encode_json(list(REQUIRED_CHARACTER_VIEW_TYPES)),
        ),
    )
    selected_by_view: dict[str, str] = {}
    for index, view_type in enumerate(REQUIRED_CHARACTER_VIEW_TYPES):
        character_asset_id = f"candidate-{key}-{view_type.lower()}"
        generated_asset_id = f"generated-{key}-{view_type.lower()}"
        stored = storage.put_object(
            f"users/employee_1/personas/{persona_id}/versions/{version_id}/{view_type.lower()}-{index}.png",
            b"png-candidate-" + view_type.encode(),
            content_type="image/png",
        )
        pg.execute(
            "INSERT INTO assets (id, project_id, kind, storage_uri, sha256, size_bytes, "
            "content_type, created_by_user_id) VALUES (%s, NULL, 'character_generated_image', "
            "%s, %s, %s, 'image/png', 'admin_1')",
            (generated_asset_id, stored.uri, stored.sha256, stored.size),
        )
        pg.execute(
            "INSERT INTO character_assets (id, character_version_id, asset_id, view_type, "
            "candidate_number, auto_quality_json, review_status, is_published_selection) "
            "VALUES (%s, %s, %s, %s, 1, %s, 'NOT_REVIEWED', 0)",
            (
                character_asset_id,
                version_id,
                generated_asset_id,
                view_type,
                encode_json(
                    {
                        "blocking_issue_codes": [],
                        "schema_version": "character-quality.v1",
                        "simulated": True,
                    }
                ),
            ),
        )
        selected_by_view[view_type] = character_asset_id
    return version_id, selected_by_view


def test_character_review_history_latest_decision_wins_on_pg(
    bus: BusinessConnection, pg: psycopg.Connection
) -> None:
    """旧断言（test_character_asset_review.py 审核历史组）：审核历史按写入序
    可枚举，最新一次裁决决定 review_status。PG 阻塞点：服务 SQL 的
    ``ORDER BY created_at, rowid`` 是 SQLite 专有列——先红（UndefinedColumn），
    修为按通道选择 ctid/rowid 后绿。"""
    storage = FakeStorageAdapter(provider="fake", bucket="cw058-tests")
    version_id, selected_by_view = _seed_reviewing_version(pg, storage)
    front_face = selected_by_view["FRONT_FACE"]

    review_character_asset(
        bus,
        actor=actor("admin_1", "admin"),
        character_asset_id=front_face,
        decision="APPROVED",
        issue_codes=[],
        comment=None,
    )
    review_character_asset(
        bus,
        actor=actor("admin_1", "admin"),
        character_asset_id=front_face,
        decision="REJECTED",
        issue_codes=["COMPOSITION"],
        comment="构图不合格",
    )

    history = list_character_asset_reviews(
        bus, actor=actor("admin_1", "admin"), character_asset_id=front_face
    )
    decisions = [item.decision for item in history]
    assert decisions == ["APPROVED", "REJECTED"]

    status_row = pg.execute(
        "SELECT review_status FROM character_assets WHERE id = %s", (front_face,)
    ).fetchone()
    assert status_row is not None and status_row[0] == "REJECTED"
    reviews = pg.execute(
        "SELECT count(*) FROM character_asset_reviews WHERE character_asset_id = %s",
        (front_face,),
    ).fetchone()
    assert reviews is not None and reviews[0] == 2
    audit = pg.execute(
        "SELECT count(*) FROM audit_logs WHERE action = 'character_asset.review'"
    ).fetchone()
    assert audit is not None and audit[0] == 2
    assert version_id  # 版本仍处 REVIEWING：驳回不改写版本状态


def test_publish_freezes_hash_and_enforces_published_view_uniqueness_on_pg(
    bus: BusinessConnection, pg: psycopg.Connection
) -> None:
    """旧断言（test_character_asset_review.py 发布组 + test_character_domain
    约束用例）：发布冻结 64 位哈希快照、重放幂等、改选 409；部分唯一索引
    ``uq_character_assets_published_view`` 在 PG 上拒绝第二个已发布同视图."""
    storage = FakeStorageAdapter(provider="fake", bucket="cw058-tests")
    version_id, selected_by_view = _seed_reviewing_version(pg, storage)
    # 发布前置：7 个候选逐一走真实审核流 APPROVED（发布守卫读取最新裁决）。
    for asset_id in selected_by_view.values():
        review_character_asset(
            bus,
            actor=actor("admin_1", "admin"),
            character_asset_id=asset_id,
            decision="APPROVED",
            issue_codes=[],
            comment=None,
        )
    selection = {cast(Any, view): asset_id for view, asset_id in selected_by_view.items()}

    published = publish_character_version(
        bus,
        actor=actor("admin_1", "admin"),
        version_id=version_id,
        selected_asset_ids=selection,
        storage=storage,
    )
    assert published.publication_hash is not None
    assert len(published.publication_hash) == 64

    snapshot_row = pg.execute(
        "SELECT publication_snapshot_json, publication_hash FROM character_versions WHERE id = %s",
        (version_id,),
    ).fetchone()
    assert snapshot_row is not None
    assert json.loads(str(snapshot_row[0]))["schema_version"] == "character-publication.v1"

    replay = publish_character_version(
        bus,
        actor=actor("admin_1", "admin"),
        version_id=version_id,
        selected_asset_ids=selection,
        storage=storage,
    )
    assert replay.publication_hash == published.publication_hash

    published_count = pg.execute(
        "SELECT count(*) FROM character_assets WHERE character_version_id = %s "
        "AND is_published_selection = 1",
        (version_id,),
    ).fetchone()
    assert published_count is not None and published_count[0] == 7

    # PG 部分唯一索引：同一视图第二个已发布选择必须被数据库拒绝。
    # （走门面写，验证 IntegrityConstraintError 携 SQLSTATE 与约束名。）
    with pytest.raises(IntegrityConstraintError) as raised:
        bus.execute(
            "INSERT INTO character_assets (id, character_version_id, asset_id, view_type, "
            "candidate_number, review_status, is_published_selection) "
            "VALUES (%s, %s, %s, %s, 2, 'APPROVED', 1)",
            (
                "character-asset-published-dup",
                version_id,
                "generated-review-front_face",
                "FRONT_FACE",
            ),
        )
    assert raised.value.sqlstate == UNIQUE_VIOLATION
    assert raised.value.constraint_name == "uq_character_assets_published_view"


# ===========================================================================
# E 组 — 爆款（库去重/统计、keyset 分页、收藏、隐藏可见性、刷新任务 PG 通道）
# ===========================================================================


def test_viral_store_upsert_dedup_and_statistics_coalesce_on_pg(
    bus: BusinessConnection, pg: psycopg.Connection, cw058_dsn: str
) -> None:
    """旧断言（test_viral_store.py 去重/统计组）：(platform, video_id) 去重、
    NULL 统计不冲掉已富化值（COALESCE）、真实零值照写、跨连接重开仍在."""
    upsert_viral_videos(
        bus, [viral_video("wechat_channels", "v-1", comments=5, cover_key="covers/v-1.jpg")]
    )
    upsert_viral_videos(
        bus,
        [
            viral_video(
                "wechat_channels",
                "v-1",
                comments=None,
                shares=None,
                likes=200,
                cover_key=None,
            )
        ],
    )
    kept = get_viral_video(bus, platform="wechat_channels", video_id="v-1")
    assert kept is not None
    assert kept.likes == 200
    assert kept.comments == 5
    # 冲突路径不触碰 cover_key：刷新条目不带封面时不得冲掉已落存储的封面 key。
    assert kept.cover_key == "covers/v-1.jpg"

    upsert_viral_videos(bus, [viral_video("douyin", "v-1", likes=7)])
    same_id_other_platform = get_viral_video(bus, platform="douyin", video_id="v-1")
    assert same_id_other_platform is not None
    assert same_id_other_platform.likes == 7

    # 跨连接重开仍在：新开一条生产同形 autocommit 连接读取。
    with psycopg.connect(cw058_dsn, autocommit=True) as fresh_raw:
        reopened_conn = BusinessConnection.postgres(fresh_raw)
        durable = get_viral_video(reopened_conn, platform="wechat_channels", video_id="v-1")
        assert durable is not None
        assert durable.title == "CW058 v-1"
        count = fresh_raw.execute("SELECT count(*) FROM viral_videos").fetchone()
        assert count is not None and count[0] == 2


def test_viral_keyset_pagination_and_cursor_invalidation_on_pg(
    bus: BusinessConnection, pg: psycopg.Connection
) -> None:
    """旧断言（test_viral_store.py 分页组）：35 条批量种子 → keyset 游标
    稳定翻页不重不漏、total 恒定；fetch_state 推进后旧游标作废."""
    videos = [
        viral_video(
            "douyin",
            f"v-{index:02d}",
            likes=1000 - index,
            published_at=int(datetime.now(UTC).timestamp()) - index * 60,
        )
        for index in range(35)
    ]
    upsert_viral_videos(bus, videos)

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    total: int | None = None
    while True:
        page = list_viral_video_page(bus, platform="douyin", sort="hot", limit=12, cursor=cursor)
        seen.extend(item.video_id for item in page.items)
        total = page.total
        pages += 1
        if not page.has_more:
            break
        assert page.next_cursor is not None
        cursor = page.next_cursor
    assert pages == 3
    assert len(seen) == 35
    assert len(set(seen)) == 35
    assert total == 35

    stale_cursor = list_viral_video_page(bus, platform="douyin", sort="hot", limit=12).next_cursor
    mark_fetch_state(bus, platform="douyin", sort="hot")
    with pytest.raises(InvalidViralCursorError):
        list_viral_video_page(bus, platform="douyin", sort="hot", limit=12, cursor=stale_cursor)


def test_viral_favorites_idempotent_isolated_and_paginated_on_pg(
    bus: BusinessConnection, pg: psycopg.Connection
) -> None:
    """旧断言（test_viral_store.py 收藏组）：收藏幂等（PK 去重）、按用户隔离、
    55 条批量种子 keyset 分页、移除恰好一次."""
    upsert_viral_videos(
        bus,
        [viral_video("douyin", f"fv-{index:02d}") for index in range(60)],
    )
    assert (
        add_viral_favorite(bus, user_id="employee_1", platform="douyin", video_id="fv-00") is True
    )
    assert (
        add_viral_favorite(bus, user_id="employee_1", platform="douyin", video_id="fv-00") is False
    )
    assert is_viral_favorite(bus, user_id="employee_1", platform="douyin", video_id="fv-00")
    assert not is_viral_favorite(bus, user_id="employee_2", platform="douyin", video_id="fv-00")

    for index in range(55):
        add_viral_favorite(bus, user_id="employee_1", platform="douyin", video_id=f"fv-{index:02d}")

    seen: list[str] = []
    cursor: str | None = None
    while True:
        page = list_favorite_viral_video_page(bus, user_id="employee_1", limit=50, cursor=cursor)
        seen.extend(item.video_id for item in page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor
    assert len(seen) == 55
    assert len(set(seen)) == 55

    assert (
        remove_viral_favorite(bus, user_id="employee_1", platform="douyin", video_id="fv-00")
        is True
    )
    assert (
        remove_viral_favorite(bus, user_id="employee_1", platform="douyin", video_id="fv-00")
        is False
    )
    assert not is_viral_favorite(bus, user_id="employee_1", platform="douyin", video_id="fv-00")


def test_viral_hidden_visibility_excluded_from_list_on_pg(
    bus: BusinessConnection, pg: psycopg.Connection
) -> None:
    """旧断言（test_viral_routes.py 隐藏可见性组）：HIDDEN 行主列表排除、
    详情仍可取且 availability=hidden."""
    upsert_viral_videos(
        bus,
        [viral_video("douyin", "visible-1"), viral_video("douyin", "hidden-1")],
    )
    bus.execute(
        "INSERT INTO viral_video_visibility (platform, video_id, status, reason) "
        "VALUES (%s, %s, 'HIDDEN', 'cw058-test-hide')",
        ("douyin", "hidden-1"),
    )
    bus.commit()

    page = list_viral_video_page(bus, platform="douyin", sort="hot", limit=20)
    assert [item.video_id for item in page.items] == ["visible-1"]
    assert page.total == 1

    still_fetchable = get_viral_video(bus, platform="douyin", video_id="hidden-1")
    assert still_fetchable is not None
    assert viral_video_availability(bus, platform="douyin", video_id="hidden-1") == "hidden"
    assert viral_video_availability(bus, platform="douyin", video_id="visible-1") == "available"


def test_viral_refresh_pg_lane_enqueues_and_worker_consumes_on_pg(
    lane_env: str,
    pg: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧断言（test_viral_routes.py 刷新组 + test_viral_refresh.py 租约组）的
    PG 通道半边：is_postgres 分支把冷列表转为刷新任务入队（scope 去重），
    run_pg_worker_once 以独立连接消费——上游外呼不持有请求事务，结果落库后
    任务 SUCCEEDED、列表可从库中读出。"""
    from app.generation_worker import run_pg_worker_once
    from app.viral_store import fetch_state_is_fresh

    class StubClient(ViralSourceClient):
        def __init__(self) -> None:
            super().__init__(api_key="stub-key")
            self.calls = 0

        def douyin_search(self, **_kwargs: Any) -> list[ViralVideo]:
            self.calls += 1
            return [viral_video("douyin", f"worker-{index}") for index in range(2)]

        def wechat_search(self, **_kwargs: Any) -> list[ViralVideo]:
            self.calls += 1
            return []

    stub = StubClient()
    # 路由依赖在注册期已绑定 get_viral_source_client，必须走 dependency_overrides；
    # worker 侧是模块级直调，monkeypatch 生效。
    monkeypatch.setattr("app.generation_worker.get_viral_source_client", lambda _conn: stub)

    # 冷列表：请求通道（get_database → pg_transaction）只入队，不回源。
    from app.auth import get_current_user
    from app.main import app
    from app.viral_routes import get_viral_source_client as _client_dependency

    app.dependency_overrides[_client_dependency] = lambda: stub
    app.dependency_overrides[get_current_user] = lambda: actor("employee_1", "employee")
    try:
        client = TestClient(app)
        response = client.get(
            "/api/viral/videos",
            params={"platform": "douyin", "sort": "hot"},
            headers={"X-Dev-User-Id": "employee_1"},
        )
        assert response.status_code == 200, response.text
        queued = pg.execute(
            "SELECT count(*) FROM viral_refresh_tasks WHERE platform = 'douyin' AND sort = 'hot'"
        ).fetchone()
        assert queued is not None and queued[0] == 1

        # 重放请求仍只保留一条去重任务。
        client.get(
            "/api/viral/videos",
            params={"platform": "douyin", "sort": "hot"},
            headers={"X-Dev-User-Id": "employee_1"},
        )
        queued_again = pg.execute(
            "SELECT count(*) FROM viral_refresh_tasks WHERE platform = 'douyin' AND sort = 'hot'"
        ).fetchone()
        assert queued_again is not None and queued_again[0] == 1
    finally:
        app.dependency_overrides.clear()

    # PG worker 消费：租约获取/完成走 pg_transaction 短事务。
    processed = run_pg_worker_once(
        worker_id="cw058-worker",
        storage=FakeStorageAdapter(provider="fake", bucket="cw058-tests"),
        max_tasks=1,
    )
    assert processed >= 1
    task_row = pg.execute(
        "SELECT status FROM viral_refresh_tasks WHERE platform = 'douyin' AND sort = 'hot'"
    ).fetchone()
    assert task_row is not None and task_row[0] == "SUCCEEDED"
    assert stub.calls >= 1
    stored = pg.execute("SELECT count(*) FROM viral_videos").fetchone()
    assert stored is not None and stored[0] >= 2

    # 回源已落库：fetch_state 新鲜，后续请求不再新增上游调用。
    assert fetch_state_is_fresh(
        BusinessConnection.postgres(psycopg.connect(lane_env, autocommit=True)),
        platform="douyin",
        sort="hot",
        max_age=timedelta(minutes=5),
    )
