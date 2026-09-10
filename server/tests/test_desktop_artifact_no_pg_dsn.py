"""CW-025: 桌面客户制品不注入 PG DSN 断言。

账本要求："验证桌面制品不接收 PG DSN，API 与 Worker 只连接同一登记 PG"。

客户版 Tauri 制品（tauri.customer.conf.json）是纯 UI 壳，连接云端 API，
不包含本地后端启动器，也不应该接收 PG DSN 环境变量。

本文件验证：
1. tauri.customer.conf.json 不含 VIDEO_REPLICA_DATABASE_URL 配置
2. tauri.customer.conf.json resources=[] 不打包 start-backend.sh
3. 客户制品构建脚本不注入 PG DSN
4. 内部 P0 制品（tauri.conf.json）与客户制品隔离

注意：start-backend.sh 本身是内部 P0 遗留物，归 CW-040 处理，
本测试只验证客户制品不引用它。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TAURI_CUSTOMER_CONF = REPO_ROOT / "client" / "src-tauri" / "tauri.customer.conf.json"
TAURI_INTERNAL_CONF = REPO_ROOT / "client" / "src-tauri" / "tauri.conf.json"
PACKAGE_JSON = REPO_ROOT / "package.json"
REQUIRE_CUSTOMER_API_BASE = REPO_ROOT / "scripts" / "require_customer_api_base.mjs"


def test_customer_tauri_config_exists() -> None:
    """前置检查：客户制品配置文件存在。"""
    assert TAURI_CUSTOMER_CONF.exists(), f"客户制品配置不存在: {TAURI_CUSTOMER_CONF}"


def test_customer_tauri_config_has_no_database_url_env() -> None:
    """CW-025: tauri.customer.conf.json 不含 VIDEO_REPLICA_DATABASE_URL。

    客户制品是纯 UI 壳，通过 HTTPS 连接云端 API，不应该接收 PG DSN。
    """
    config_text = TAURI_CUSTOMER_CONF.read_text(encoding="utf-8")
    config = json.loads(config_text)

    # 检查整个配置文件不含 DATABASE_URL 相关字符串
    assert "VIDEO_REPLICA_DATABASE_URL" not in config_text, (
        "客户制品配置不得含 VIDEO_REPLICA_DATABASE_URL"
    )
    assert "DATABASE_URL" not in config_text, "客户制品配置不得含任何 DATABASE_URL 引用"

    # 检查 env 字段（如果存在）不含 PG DSN
    if "env" in config:
        env_vars = config["env"]
        assert "VIDEO_REPLICA_DATABASE_URL" not in env_vars, (
            "客户制品 env 不得注入 VIDEO_REPLICA_DATABASE_URL"
        )


def test_customer_tauri_config_has_no_backend_resources() -> None:
    """CW-025: tauri.customer.conf.json resources=[] 不打包 start-backend.sh。

    客户制品描述明确："不包含本地 API 或 Worker 启动器"。
    """
    config = json.loads(TAURI_CUSTOMER_CONF.read_text(encoding="utf-8"))

    # 检查 bundle.resources 为空
    bundle = config.get("bundle", {})
    resources = bundle.get("resources", [])
    assert resources == [], f"客户制品 resources 必须为空（不打包后端启动器），实际: {resources}"

    # 检查描述明确说不含本地启动器
    long_description = bundle.get("longDescription", "")
    assert "不包含本地 API" in long_description or "不含本地" in long_description, (
        f"客户制品描述应明确不含本地启动器，实际: {long_description}"
    )


def test_customer_tauri_config_does_not_reference_start_backend() -> None:
    """CW-025: 客户制品配置不引用 start-backend.sh。"""
    config_text = TAURI_CUSTOMER_CONF.read_text(encoding="utf-8")

    assert "start-backend" not in config_text, (
        "客户制品配置不得引用 start-backend.sh（内部 P0 遗留物，归 CW-040）"
    )
    assert "start_backend" not in config_text, "客户制品配置不得引用 start_backend"


def test_internal_tauri_config_is_separate_from_customer() -> None:
    """CW-025: 内部 P0 制品（tauri.conf.json）与客户制品隔离。

    内部制品可以保留 start-backend.sh 和 DB_PATH（CW-040 才处理），
    但必须与客户制品配置文件分离。
    """
    assert TAURI_INTERNAL_CONF.exists(), f"内部制品配置不存在: {TAURI_INTERNAL_CONF}"
    assert TAURI_INTERNAL_CONF != TAURI_CUSTOMER_CONF, "内部制品和客户制品必须是不同的配置文件"

    internal_config = json.loads(TAURI_INTERNAL_CONF.read_text(encoding="utf-8"))
    customer_config = json.loads(TAURI_CUSTOMER_CONF.read_text(encoding="utf-8"))

    # 检查 identifier 不同
    internal_id = internal_config.get("identifier", "")
    customer_id = customer_config.get("identifier", "")
    assert internal_id != customer_id, (
        f"内部制品和客户制品 identifier 必须不同: {internal_id} vs {customer_id}"
    )

    # 客户制品 identifier 应该含 "customer"
    assert "customer" in customer_id.lower(), f"客户制品 identifier 应含 'customer': {customer_id}"


def test_package_json_customer_build_script_does_not_inject_pg_dsn() -> None:
    """CW-025: package.json 客户制品构建脚本不注入 PG DSN。

    tauri:build:customer 脚本应该只调用 require:customer-api-base 和 tauri build，
    不注入 VIDEO_REPLICA_DATABASE_URL。
    """
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    scripts = package.get("scripts", {})

    customer_build = scripts.get("tauri:build:customer", "")
    assert customer_build, "package.json 缺少 tauri:build:customer 脚本"

    # 检查脚本不含 DATABASE_URL 注入
    assert "VIDEO_REPLICA_DATABASE_URL" not in customer_build, (
        f"客户制品构建脚本不得注入 VIDEO_REPLICA_DATABASE_URL: {customer_build}"
    )
    assert "DATABASE_URL" not in customer_build, (
        f"客户制品构建脚本不得含任何 DATABASE_URL 引用: {customer_build}"
    )

    # 检查脚本使用 customer conf
    assert "tauri.customer.conf.json" in customer_build, (
        f"客户制品构建脚本必须使用 tauri.customer.conf.json: {customer_build}"
    )


def test_require_customer_api_base_script_does_not_inject_pg_dsn() -> None:
    """CW-025: require_customer_api_base.mjs 不注入 PG DSN。

    这个脚本只验证客户 API base URL 配置，不应该涉及数据库配置。
    """
    if not REQUIRE_CUSTOMER_API_BASE.exists():
        pytest.skip(f"脚本不存在: {REQUIRE_CUSTOMER_API_BASE}")

    script_text = REQUIRE_CUSTOMER_API_BASE.read_text(encoding="utf-8")

    # 检查脚本不含 DATABASE_URL 注入
    assert "VIDEO_REPLICA_DATABASE_URL" not in script_text, (
        "require_customer_api_base.mjs 不得注入 VIDEO_REPLICA_DATABASE_URL"
    )
    assert "DATABASE_URL" not in script_text, (
        "require_customer_api_base.mjs 不得含任何 DATABASE_URL 引用"
    )

    # 检查脚本不含 DB_PATH 注入
    assert "VIDEO_REPLICA_DB_PATH" not in script_text, (
        "require_customer_api_base.mjs 不得注入 VIDEO_REPLICA_DB_PATH"
    )


def test_customer_artifact_env_isolation_summary() -> None:
    """CW-025: 客户制品环境隔离总结断言。

    综合验证：客户制品构建链路（package.json → require_customer_api_base.mjs →
    tauri.customer.conf.json）全程不接触 PG DSN 或 DB_PATH。

    这是账本"验证桌面制品不接收 PG DSN"的最终验收断言。
    """
    # 1. 配置文件层面
    customer_conf_text = TAURI_CUSTOMER_CONF.read_text(encoding="utf-8")
    assert "VIDEO_REPLICA_DATABASE_URL" not in customer_conf_text
    assert "VIDEO_REPLICA_DB_PATH" not in customer_conf_text

    # 2. 构建脚本层面
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    customer_build = package.get("scripts", {}).get("tauri:build:customer", "")
    assert "VIDEO_REPLICA_DATABASE_URL" not in customer_build
    assert "VIDEO_REPLICA_DB_PATH" not in customer_build

    # 3. 辅助脚本层面
    if REQUIRE_CUSTOMER_API_BASE.exists():
        helper_text = REQUIRE_CUSTOMER_API_BASE.read_text(encoding="utf-8")
        assert "VIDEO_REPLICA_DATABASE_URL" not in helper_text
        assert "VIDEO_REPLICA_DB_PATH" not in helper_text

    # 4. resources 为空（不打包任何后端启动器）
    customer_conf = json.loads(customer_conf_text)
    assert customer_conf.get("bundle", {}).get("resources", []) == []
