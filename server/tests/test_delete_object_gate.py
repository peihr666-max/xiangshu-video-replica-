"""DEDUP-CAS-20260916 — 删除闸门：业务模块不得直接调用 ``storage.delete_object``。

为什么这是一条测试，而不是一句注释
----------------------------------
内容寻址把「同一份字节只留一份物理对象」变成事实，随之而来的风险全部集中在
**删除**：只要有一处直接删字节的地方，而该对象此刻仍被另一个资产引用，就会把
别人的资产删坏 —— 而且删的是字节，不可回滚。

改造前这个判断散落在 17 个调用点，每一处都得自己重新推导一遍，其中
``project.delete`` 那处推导错了（``project_id <> %s`` 对 ``project_id IS NULL``
的引用求值为 NULL 而非 TRUE），素材库/人物资料这类用户级资产被判为「无共享引用」，
对象被删掉而引用还在。**判断一旦可以被重写，就一定会被再次写错**，所以这里把
「只有 content_store 能删对象」变成构建即失败的不变式，而不是靠评审记得。

本模块做三件事，全部零 PG 依赖：
1. 扫描 ``app/``，除 ``storage.py``（实现）与 ``content_store.py``（闸门）外，
   任何模块出现直接删除调用即失败；
2. 闸门入口命名稳定存在；
3. 无连接分支真的拒绝 CAS 命名空间（``content/``）下的键，并放行私有键 ——
   拒绝是**泄漏一个对象**（回收器会兜底），放行错了才是**删掉共享字节**。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app import content_store

APP_DIR = Path(__file__).resolve().parent.parent / "app"

# 只有这两个模块可以触达存储层原语：
# storage.py 是它的实现，content_store.py 是唯一被允许做删除裁决的地方。
_ALLOWED_MODULES = {"storage.py", "content_store.py"}

# 历史调用点的清单。它们必须仍然通过闸门清理，而不是「顺手删掉清理逻辑」——
# 后者能让上面的扫描通过，却把孤儿对象留成永久泄漏。
_GATE_CALLERS: dict[str, str] = {
    "bootstrap.py": "delete_object_outside_content_namespace",
    "character_asset_review.py": "delete_object_outside_content_namespace",
    "character_image_generation.py": "delete_object_outside_content_namespace",
    "first_frames.py": "delete_object_outside_content_namespace",
    "image_tasks.py": "delete_object_if_unreferenced",
    "generation_worker.py": "delete_object_if_unreferenced",
    "oral.py": "delete_object_outside_content_namespace",
    "oral_worker.py": "delete_object_outside_content_namespace",
    "rbac_routes.py": "delete_object_if_unreferenced",
    "script_from_audio.py": "delete_object_outside_content_namespace",
    "settings.py": "delete_object_outside_content_namespace",
    "simple_character.py": "delete_object_outside_content_namespace",
    "simple_character_routes.py": "delete_object_outside_content_namespace",
    "source_frames.py": "delete_object_outside_content_namespace",
    "upload_cleanup.py": "delete_object_outside_content_namespace",
    "viral_media_preparation.py": "delete_object_outside_content_namespace",
}


class _RecordingStorage:
    """记录被删键的最小替身，避免为了验证拒绝行为去搭一个真实后端。"""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_object(self, key: str, *, actor_id: str | None = None) -> None:
        self.deleted.append(key)


def _direct_deletion_lines(path: Path) -> list[int]:
    """用 AST 找删除调用，免得注释或字符串里的同名字样把扫描带偏。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Attribute) and target.attr in {
            "delete_object",
            "_delete_object",
        }:
            found.append(node.lineno)
    return sorted(found)


def test_only_the_gate_may_delete_storage_objects() -> None:
    offenders = {
        path.relative_to(APP_DIR).as_posix(): lines
        for path in sorted(APP_DIR.rglob("*.py"))
        if path.name not in _ALLOWED_MODULES and (lines := _direct_deletion_lines(path))
    }
    assert offenders == {}, (
        f"业务模块必须经 content_store 的闸门删除对象；以下位置绕过了闸门直接删除：{offenders}"
    )


def test_gate_entry_points_keep_their_names() -> None:
    assert callable(content_store.delete_object_outside_content_namespace)
    assert callable(content_store.delete_object_if_unreferenced)
    assert callable(content_store.is_content_object_key)


@pytest.mark.parametrize("module", sorted(_GATE_CALLERS))
def test_known_cleanup_paths_still_route_through_the_gate(module: str) -> None:
    source = (APP_DIR / module).read_text(encoding="utf-8")
    expected = _GATE_CALLERS[module]
    assert expected in source, (
        f"{module} 应当通过 {expected} 清理对象；"
        "若清理逻辑被整体删除，孤儿对象会变成永久泄漏，这里也要拦住。"
    )


@pytest.mark.parametrize(
    "object_key",
    [
        "content",
        "content/",
        "content/ab/cd/" + "a" * 64 + ".mp4",
        "content/ab/cd/" + "a" * 64,
    ],
)
def test_namespace_guard_refuses_content_addressed_keys(object_key: str) -> None:
    storage = _RecordingStorage()
    removed = content_store.delete_object_outside_content_namespace(storage, object_key)
    assert removed is False, "CAS 命名空间下的键必须交给回收器，不能就地删除"
    assert storage.deleted == []


@pytest.mark.parametrize(
    "object_key",
    [
        "projects/p1/uploads/clip.mp4",
        "uploads/content/clip.mp4",
        "content-archive/clip.mp4",
        "contentish/clip.mp4",
        ".cw031-readiness/probe",
    ],
)
def test_namespace_guard_allows_private_keys(object_key: str) -> None:
    storage = _RecordingStorage()
    removed = content_store.delete_object_outside_content_namespace(storage, object_key)
    assert removed is True
    assert storage.deleted == [object_key]


def test_namespace_guard_prefix_check_is_not_a_substring_check() -> None:
    """``contentish/x`` 这类前缀相近的键不属于登记表命名空间，必须放行。"""
    assert content_store.is_content_object_key("content/a")
    assert content_store.is_content_object_key("content")
    assert not content_store.is_content_object_key("contentish/a")
    assert not content_store.is_content_object_key("uploads/content/a")
    assert not content_store.is_content_object_key("")


def _reclaim_call_sites() -> dict[str, int]:
    """AST 扫描 ``app/`` 里对回收器的调用点（排除 content_store 自身的定义）。"""
    found: dict[str, int] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        if path.name == "content_store.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", None)
            if name == "reclaim_expired_content_objects":
                found[path.relative_to(APP_DIR).as_posix()] = node.lineno
    return found


def test_reclaim_sweeper_has_a_production_entry_point() -> None:
    """回收器必须有生产入口，否则字节只增不减。

    释放引用只是把 ``ref_count`` 减到 0 并排定 ``reclaim_after``；真正删字节的
    是 ``reclaim_expired_content_objects``。它在改造初期只有一个测试调用点 ——
    等于装好了回收器却没通电：只要后续链路接入非 pinned 对象，删掉的资产就会
    永久泄漏。这条测试把「有人真的会来扫」变成构建即失败。
    """
    sites = _reclaim_call_sites()
    assert sites, "没有任何生产模块调用 reclaim_expired_content_objects"
    assert "upload_cleanup.py" in sites, "清理 CLI 必须能驱动回收"
    assert "generation_worker.py" in sites, "worker 必须周期性驱动回收"


def test_reclaim_entry_points_are_importable() -> None:
    """入口不只是「出现过字符串」，而是可调用的现成函数。"""
    from app.generation_worker import reclaim_expired_content_objects_throttled
    from app.upload_cleanup import reclaim_content_objects

    assert callable(reclaim_content_objects)
    assert callable(reclaim_expired_content_objects_throttled)
