"""Itemized prices and settlement: real PostgreSQL, no paid provider calls."""

# ruff: noqa: F811
import json
from datetime import date
from decimal import Decimal

import psycopg
import pytest
from test_customer_pricing import (  # noqa: F401
    account,
    admin_login,
    client,
    pricing_client,
    registration_client,
    registration_dsn,
    route_state,
)

from app.billing_catalog import SERVICES, Tariff, calculate_credits
from app.billing_reports import date_bounds, statistics
from app.db_portable import BusinessConnection
from app.usage_billing import accept_operation, finish_operation, record_attempt


def test_image_billing_and_customer_service_filter_share_settled_evidence(
    pricing_client, route_state
):
    from app.control_routes import image_task_billing

    customer, uid = account(pricing_client)
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        raw.execute("UPDATE wallets SET available_credits=100 WHERE user_id=%s", (uid,))
        raw.execute(
            "INSERT INTO billing_tariffs(service,enabled,unit_credits,unit_cost_fen) "
            "VALUES('character',true,5,1)"
        )
        op = accept_operation(
            conn, user_id=uid, service="character", source_id="image-task", units=1
        )
        record_attempt(conn, operation_id=op, attempt_key="first", usage=1)
        record_attempt(conn, operation_id=op, attempt_key="retry", usage=1)
        finish_operation(conn, operation_id=op, units=1, succeeded=True)
        assert image_task_billing(conn, task_id="image-task", user_id=uid) == (5, 0.02)
        assert image_task_billing(conn, task_id="image-task", user_id="other-user") == (0, None)
        record_attempt(conn, operation_id=op, attempt_key="unknown", usage=None)
        assert image_task_billing(conn, task_id="image-task", user_id=uid) == (5, None)
    response = pricing_client.get(
        "/api/customer/wallet/transactions?business=character", headers=customer
    )
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    assert len(rows) == 2
    assert {row["billing_operation_id"] for row in rows} == {op}
    assert {row["service"] for row in rows} == {"character"}
    assert sum(-row["reserved_delta"] for row in rows if row["type"] == "SETTLE") == 5
    assert (
        pricing_client.get(
            "/api/customer/wallet/transactions?business=asr", headers=customer
        ).json()["total"]
        == 0
    )
    from app.account_admin_routes import router as account_admin_router

    pricing_client.app.include_router(account_admin_router)
    admin = admin_login(pricing_client, route_state)
    admin_response = pricing_client.get(
        f"/api/control/customers/{uid}/wallet-transactions", headers=admin
    )
    assert admin_response.status_code == 200, admin_response.text
    admin_rows = admin_response.json()["items"]
    assert {row["id"] for row in admin_rows} == {row["id"] for row in rows}
    assert {row["source_id"] for row in admin_rows} == {"image-task"}
    assert {row["service_name"] for row in admin_rows} == {SERVICES["character"].name}
    assert {row["billing_operation_id"] for row in admin_rows} == {op}


def test_collection_meter_counts_actual_calls_and_preserves_batch(client, route_state):
    from app.billing_meter import collection_billing_context, meter_call
    from app.viral_collection_billing import create_collection_batch

    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        raw.execute("INSERT INTO billing_tariffs(service,unit_cost_fen) VALUES ('viral_data',2)")
        batch = create_collection_batch(
            conn, platform="douyin", config={"keywords": ["别墅"]}, user_ids=[]
        )
    with collection_billing_context(batch):
        with meter_call("viral_data"):
            pass
        with pytest.raises(RuntimeError), meter_call("viral_data"):
            raise RuntimeError("transport uncertain")
        with meter_call("viral_data"):
            pass
    with psycopg.connect(route_state) as raw:
        rows = raw.execute(
            "SELECT o.actual_units,a.usage,a.cost_fen FROM billing_operations o "
            "JOIN billing_attempts a ON a.operation_id=o.id WHERE o.collection_batch_id=%s",
            (batch,),
        ).fetchall()
        assert len(rows) == 3
        assert sum(row[0] for row in rows) == 2
        assert sum(row[2] or 0 for row in rows) == 4
        assert sum(row[1] is None for row in rows) == 1


def test_expired_collection_call_becomes_unknown_and_late_response_cannot_charge(
    client, route_state, monkeypatch
):
    import app.viral_collection_billing as collection
    from app.billing_meter import collection_billing_context, meter_call
    from app.db_pg import pg_transaction

    user = account(client, "expired_collection")[1]
    with psycopg.connect(route_state) as raw:
        batch = collection.create_collection_batch(
            BusinessConnection.postgres(raw), platform="douyin", config={}, user_ids=[user]
        )
    with collection_billing_context(batch), pytest.raises(RuntimeError, match="计量已超时"):
        with meter_call("viral_data"):
            monkeypatch.setattr(collection, "COLLECTION_REQUEST_DEADLINE_SECONDS", 0)
            with pg_transaction() as raw:
                assert (
                    collection.reconcile_collection_requests(BusinessConnection.postgres(raw)) == 1
                )
    assert collection.settle_collection_charges() == 0
    with psycopg.connect(route_state) as raw:
        assert raw.execute(
            "SELECT state,actual_units FROM billing_operations WHERE collection_batch_id=%s",
            (batch,),
        ).fetchone() == ("FAILED", 0)
        assert raw.execute(
            "SELECT a.state,a.usage,a.cost_fen FROM billing_attempts a JOIN billing_operations "
            "o ON o.id=a.operation_id WHERE o.collection_batch_id=%s",
            (batch,),
        ).fetchone() == ("UNKNOWN", None, None)


def test_activation_suspension_is_serialized_with_collection_charge(
    client, route_state, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import app.viral_collection_billing as collection
    from app.billing_meter import collection_billing_context, meter_call

    user = account(client, "activation_collection")[1]
    with psycopg.connect(route_state) as raw:
        credit_lot(
            raw,
            user,
            key="activation-collection-funds",
            credits=100,
            amount_fen=100,
            provider="admin_adjustment",
        )
        raw.execute(
            "INSERT INTO "
            "activation_code_batches(id,name,face_value_fen,unit_price_fen_snapshot,credits_snapshot,quantity,activation_expires_at,status,created_by_user_id)"
            " VALUES('collection-code-batch','test',1000,10,100,1,'2099-01-01','OPEN',%s)",
            (user,),
        )
        raw.execute(
            "INSERT INTO "
            "activation_codes(id,batch_id,code_digest,digest_key_version,masked_code,status,issued_at,bound_user_id,activated_at)"
            " "
            "VALUES('collection-code','collection-code-batch','collection-digest',1,'TEST-****','ACTIVE','2026-01-01',%s,'2026-01-01')",
            (user,),
        )
        raw.execute(
            "INSERT INTO "
            "activation_code_activations(id,code_id,user_id,first_device_id,recharge_order_id) "
            "VALUES('collection-binding','collection-code',%s,NULL,'activation-collection-funds')",
            (user,),
        )
        raw.execute(
            "INSERT INTO billing_tariffs(service,enabled,unit_credits) VALUES('viral_data',true,3)"
        )
        batch = collection.create_collection_batch(
            BusinessConnection.postgres(raw), platform="douyin", config={}, user_ids=[user]
        )
    with collection_billing_context(batch), meter_call("viral_data"):
        pass
    checked = Event()
    eligible = collection.eligible_collection_users

    def check(*args, **kwargs):
        result = eligible(*args, **kwargs)
        checked.set()
        return result

    monkeypatch.setattr(collection, "eligible_collection_users", check)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(route_state) as wallet_lock:
            wallet_lock.execute("SELECT user_id FROM wallets WHERE user_id=%s FOR UPDATE", (user,))
            pending = pool.submit(collection.settle_collection_charges)
            assert checked.wait(5)
            with (
                pytest.raises(psycopg.errors.LockNotAvailable),
                psycopg.connect(route_state) as admin,
            ):
                admin.execute("SET LOCAL lock_timeout='200ms'")
                admin.execute(
                    "UPDATE activation_codes SET "
                    "status='SUSPENDED',suspended_at=CURRENT_TIMESTAMP WHERE "
                    "id='collection-code'"
                )
        assert pending.result(timeout=5) == 1
    with psycopg.connect(route_state) as raw:
        raw.execute(
            "UPDATE activation_codes SET status='SUSPENDED',suspended_at=CURRENT_TIMESTAMP "
            "WHERE id='collection-code'"
        )
    with collection_billing_context(batch), meter_call("viral_data"):
        pass
    assert collection.settle_collection_charges() == 1
    with psycopg.connect(route_state) as raw:
        assert (
            raw.execute(
                "SELECT available_credits FROM wallets WHERE user_id=%s", (user,)
            ).fetchone()[0]
            == 97
        )
        assert (
            raw.execute(
                "SELECT count(*) FROM viral_collection_charges WHERE user_id=%s AND "
                "state='SKIPPED_INACTIVE'",
                (user,),
            ).fetchone()[0]
            == 1
        )


def test_shared_collection_reports_count_cost_once_and_freeze_per_request_price(
    client, route_state
):
    from app.billing_meter import collection_billing_context, meter_call
    from app.billing_reports import operation_rows
    from app.viral_collection_billing import collection_batch_rows, create_collection_batch

    users = [account(client, "collection_one")[1], account(client, "collection_two")[1]]
    with psycopg.connect(route_state) as raw:
        raw.execute(
            "INSERT INTO billing_tariffs(service,enabled,unit_credits,unit_cost_fen) "
            "VALUES ('viral_data',true,0.25,2)"
        )
        for index, user in enumerate(users):
            credit_lot(raw, user, key=f"collection-credit-{index}", credits=100, amount_fen=100)
        conn = BusinessConnection.postgres(raw)
        batch = create_collection_batch(conn, platform="douyin", config={}, user_ids=users)
        snapshot = json.loads(
            raw.execute(
                "SELECT pricing_snapshot_json FROM viral_collection_batches WHERE id=%s", (batch,)
            ).fetchone()[0]
        )
        raw.execute("UPDATE billing_tariffs SET unit_credits=99 WHERE service='viral_data'")
    with collection_billing_context(batch):
        for _ in range(2):
            with meter_call("viral_data"):
                pass
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        requests = raw.execute(
            "SELECT id FROM billing_operations WHERE collection_batch_id=%s AND user_id IS NULL",
            (batch,),
        ).fetchall()
        for request in requests:
            for user in users:
                operation = accept_operation(
                    conn,
                    user_id=user,
                    service="viral_data",
                    source_id=request[0],
                    units=1,
                    collection_batch_id=batch,
                    pricing_snapshot=snapshot,
                )
                assert finish_operation(conn, operation_id=operation, units=1, succeeded=True) == 1
                raw.execute(
                    "INSERT INTO viral_collection_charges(request_id,user_id,operation_id,"
                    "state,due_credits) VALUES(%s,%s,%s,'SUCCEEDED',1)",
                    (request[0], user, operation),
                )
        filters = dict(
            start=date(2000, 1, 1), end=date(2099, 1, 1), module="viral", provider="tikhub"
        )
        totals = statistics(conn, **filters)["totals"]
        assert totals["provider_call_count"] == 2
        assert totals["charged_credits"] == 4
        assert totals["known_cost_fen"] == 4
        assert totals["known_revenue_fen"] == 4
        assert totals["profit_fen"] == 0
        assert statistics(conn, **filters, user_id=users[0])["totals"]["profit_fen"] is None
        customer_rows = operation_rows(conn, **filters, user_id=users[0])
        assert len(customer_rows) == 2
        assert all(
            row["profit_fen"] is None and row["shared_cost_unallocated"] for row in customer_rows
        )
        batch_report = next(
            row
            for row in collection_batch_rows(conn, start=date(2000, 1, 1), end=date(2099, 1, 1))
            if row["id"] == batch
        )
        assert batch_report["confirmed_count"] == 2
        assert batch_report["customer_count"] == 2
        assert batch_report["pending_charges"] == 0
        assert batch_report["profit_fen"] == 0


def test_catalog_matches_business_units_and_separates_video_tiers():
    expected = {
        "video_768p": "second",
        "video_2k": "second",
        "oral": "second",
        "analysis": "call",
        "first_frame": "image",
        "character": "image",
        "rewrite": "call",
        "asr": "second",
        "viral_data": "call",
        "link_resolution": "call",
    }
    assert {key: SERVICES[key].unit for key in expected} == expected
    assert SERVICES["cos"].customer_charge_allowed is False
    assert SERVICES["zpay"].customer_charge_allowed is False


def test_collection_settlement_recovers_once_and_never_retries_insufficient_balance(
    client, route_state
):
    from concurrent.futures import ThreadPoolExecutor

    from app.billing_meter import collection_billing_context, meter_call
    from app.viral_collection_billing import (
        create_collection_batch,
        eligible_collection_users,
        settle_collection_charges,
    )

    rich = account(client, "rich_collection")[1]
    poor = account(client, "poor_collection")[1]
    inactive = account(client, "inactive_collection")[1]
    with psycopg.connect(route_state) as raw:
        raw.execute("UPDATE users SET is_active=0 WHERE id=%s", (inactive,))
        raw.execute(
            "INSERT INTO billing_tariffs(service,enabled,unit_credits) VALUES ('viral_data',true,3)"
        )
        credit_lot(raw, rich, key="collection-resume-funds", credits=100, amount_fen=100)
        conn = BusinessConnection.postgres(raw)
        eligible = eligible_collection_users(conn)
        assert set(eligible) == {rich, poor}
        batch = create_collection_batch(conn, platform="douyin", config={}, user_ids=eligible)
    late = account(client, "late_collection")[1]
    with collection_billing_context(batch):
        for _ in range(2):
            with meter_call("viral_data"):
                pass
    # Recovery reads persisted supplier requests; no dependency on the caller surviving.
    assert settle_collection_charges(limit=1) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: settle_collection_charges(), range(2))) == 3
    with psycopg.connect(route_state) as raw:
        assert raw.execute(
            "SELECT available_credits,reserved_credits FROM wallets WHERE user_id=%s", (rich,)
        ).fetchone() == (94, 0)
        assert (
            raw.execute(
                "SELECT count(*) FROM viral_collection_charges WHERE user_id=%s AND "
                "state='INSUFFICIENT_CREDITS'",
                (poor,),
            ).fetchone()[0]
            == 2
        )
        assert (
            raw.execute(
                "SELECT count(*) FROM billing_operations WHERE user_id IN (%s,%s)", (inactive, late)
            ).fetchone()[0]
            == 0
        )
        credit_lot(raw, poor, key="later-poor-funds", credits=100, amount_fen=100)
    assert settle_collection_charges() == 0
    with psycopg.connect(route_state) as raw:
        assert (
            raw.execute(
                "SELECT available_credits FROM wallets WHERE user_id=%s", (poor,)
            ).fetchone()[0]
            == 100
        )


def test_scheduled_collector_wires_batch_meter_and_settlement(client, route_state, monkeypatch):
    from app.billing_meter import meter_call
    from app.generation_worker import run_pg_collection_once
    from app.storage import FakeStorageAdapter

    user = account(client, "scheduled_collection")[1]
    with psycopg.connect(route_state) as raw:
        raw.execute(
            "INSERT INTO billing_tariffs(service,enabled,unit_credits,unit_cost_fen) VALUES "
            "('viral_data',true,2,0.5)"
        )
        credit_lot(raw, user, key="scheduled-funds", credits=100, amount_fen=100)
        raw.execute(
            "INSERT INTO viral_runtime_controls(id,collection_enabled,keywords_json) "
            "VALUES(1,1,%s) ON CONFLICT(id) DO UPDATE SET "
            "collection_enabled=1,keywords_json=excluded.keywords_json,next_collection_at=NULL",
            (json.dumps([{"platform": "douyin", "category": "其他", "keyword": "别墅"}]),),
        )
        raw.execute("DELETE FROM viral_refresh_tasks")

    class Source:
        def douyin_search(self, **_kwargs):
            with meter_call("viral_data"):
                return []

    monkeypatch.setattr(
        "app.viral_collection.viral_source_client_from_settings", lambda _: Source()
    )
    assert (
        run_pg_collection_once(
            worker_id="billing-integration",
            storage=FakeStorageAdapter(provider="cos", bucket="test"),
        )
        > 0
    )
    with psycopg.connect(route_state) as raw:
        assert raw.execute("SELECT status FROM viral_refresh_tasks").fetchone()[0] == "SUCCEEDED"
        assert (
            raw.execute(
                "SELECT available_credits FROM wallets WHERE user_id=%s", (user,)
            ).fetchone()[0]
            == 98
        )
        config = json.loads(
            raw.execute("SELECT collection_config_json FROM viral_refresh_tasks").fetchone()[0]
        )
        assert (
            raw.execute(
                "SELECT count(*) FROM billing_operations WHERE collection_batch_id=%s",
                (config["billing_batch_id"],),
            ).fetchone()[0]
            == 2
        )


def test_absent_disabled_zero_and_fractional_tariffs():
    assert calculate_credits(None, "10.8") == 0
    assert calculate_credits(Tariff(unit_credits=Decimal("2")), "10.8") == 0
    enabled = Tariff(enabled=True, unit_credits=Decimal("0.25"))
    assert calculate_credits(enabled, "4.1") == 2
    assert calculate_credits(enabled, "0") == 0
    for invalid in ("NaN", "Infinity", "-1"):
        with pytest.raises(ValueError):
            calculate_credits(enabled, invalid)


def test_free_operation_is_frozen_without_wallet_rows(client, route_state):
    _, user_id = account(client)
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        operation = accept_operation(
            conn, user_id=user_id, service="analysis", source_id="free", units=1
        )
        raw.execute(
            "INSERT INTO billing_tariffs(service, enabled, unit_credits, unit_cost_fen) "
            "VALUES ('analysis', true, 9, 0.025)"
        )
        assert (
            accept_operation(conn, user_id=user_id, service="analysis", source_id="free", units=1)
            == operation
        )
        record_attempt(conn, operation_id=operation, attempt_key="provider-1", usage=1)
        finish_operation(conn, operation_id=operation, units=1, succeeded=True)
        row = raw.execute(
            "SELECT charged_credits, state FROM billing_operations WHERE id=%s", (operation,)
        ).fetchone()
        assert (row[0], row[1]) == (0, "SUCCEEDED")
        assert (
            raw.execute(
                "SELECT count(*) FROM wallet_transactions WHERE user_id=%s", (user_id,)
            ).fetchone()[0]
            == 0
        )
        assert raw.execute(
            "SELECT cost_fen FROM billing_attempts WHERE operation_id=%s", (operation,)
        ).fetchone()[0] == Decimal("0.025")


def test_partial_delivery_refunds_budget_once_and_freezes_price(client, route_state):
    _, user_id = account(client)
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        raw.execute("UPDATE wallets SET available_credits=100 WHERE user_id=%s", (user_id,))
        raw.execute(
            "INSERT INTO billing_tariffs(service, enabled, unit_credits, unit_cost_fen) "
            "VALUES ('first_frame', true, 7, 0.001)"
        )
        operation = accept_operation(
            conn, user_id=user_id, service="first_frame", source_id="images", units=3
        )
        raw.execute("UPDATE billing_tariffs SET unit_credits=99 WHERE service='first_frame'")
        record_attempt(conn, operation_id=operation, attempt_key="a", usage=3)
        finish_operation(conn, operation_id=operation, units=2, succeeded=True)
        finish_operation(conn, operation_id=operation, units=2, succeeded=True)
        row = raw.execute(
            "SELECT available_credits, reserved_credits FROM wallets WHERE user_id=%s", (user_id,)
        ).fetchone()
        assert (row[0], row[1]) == (86, 0)
        assert (
            raw.execute(
                "SELECT charged_credits FROM billing_operations WHERE id=%s", (operation,)
            ).fetchone()[0]
            == 14
        )


def test_missing_cost_remains_unknown_and_retries_have_separate_costs(client, route_state):
    _, user_id = account(client)
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        operation = accept_operation(
            conn, user_id=user_id, service="rewrite", source_id="rewrite", units=1
        )
        record_attempt(conn, operation_id=operation, attempt_key="a", usage=1)
        record_attempt(conn, operation_id=operation, attempt_key="a", usage=1)
        record_attempt(conn, operation_id=operation, attempt_key="b", usage=1)
        finish_operation(conn, operation_id=operation, units=0, succeeded=False)
        row = raw.execute(
            "SELECT count(*), count(cost_fen) FROM billing_attempts WHERE operation_id=%s",
            (operation,),
        ).fetchone()
        assert (row[0], row[1]) == (2, 0)


def test_period_statistics_do_not_duplicate_revenue_for_multiple_attempts(client, route_state):
    _, user_id = account(client)
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        raw.execute("INSERT INTO billing_tariffs(service, unit_cost_fen) VALUES ('analysis', 2.5)")
        operation = accept_operation(
            conn, user_id=user_id, service="analysis", source_id="stats", units=1
        )
        for key in ("a", "b", "c"):
            record_attempt(conn, operation_id=operation, attempt_key=key, usage=1)
        finish_operation(conn, operation_id=operation, units=1, succeeded=True)
        report = statistics(conn, start=date(2000, 1, 1), end=date(2099, 1, 1), grain="month")
        assert report["totals"]["operation_count"] == 1
        assert report["totals"]["provider_call_count"] == 3
        assert report["totals"]["known_revenue_fen"] == 0
        assert report["totals"]["profit_fen"] == Decimal("-7.5")
        assert report["totals"]["platform_cost_fen"] == Decimal("7.5")


def test_statistics_leave_profit_pending_when_cost_not_configured(client, route_state):
    _, user_id = account(client)
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        operation = accept_operation(
            conn, user_id=user_id, service="analysis", source_id="unknown", units=1
        )
        record_attempt(conn, operation_id=operation, attempt_key="a", usage=1)
        finish_operation(conn, operation_id=operation, units=1, succeeded=True)
        report = statistics(conn, start=date(2000, 1, 1), end=date(2099, 1, 1), grain="year")
        assert report["totals"]["unknown_cost_count"] == 1
        assert report["totals"]["profit_fen"] is None


def test_shanghai_range_includes_leap_day_and_has_exclusive_upper_bound():
    lower, upper = date_bounds(date(2024, 2, 29), date(2024, 2, 29))
    assert lower.isoformat() == "2024-02-29T00:00:00+08:00"
    assert upper.isoformat() == "2024-03-01T00:00:00+08:00"


def test_customer_catalog_never_exposes_supplier_costs(client, route_state):
    from app.billing_routes import router

    client.app.include_router(router)
    headers, _ = account(client)
    with psycopg.connect(route_state) as raw:
        raw.execute(
            "INSERT INTO billing_tariffs(service,enabled,unit_credits,unit_cost_fen) VALUES "
            "('analysis',true,7,3.251)"
        )
    response = client.get("/api/customer/billing/catalog", headers=headers)
    assert response.status_code == 200, response.text
    assert "unit_cost_fen" not in response.text
    assert "3.251" not in response.text
    assert '"provider"' not in response.text
    assert "抖一抖" not in response.text
    assert {item["service"] for item in response.json()["services"]}.isdisjoint(
        {"cos", "zpay", "quality_inspection", "analysis_repair"}
    )
    from app.customer_pricing_routes import router as pricing_router

    client.app.include_router(pricing_router)
    pricing = client.get("/api/customer/pricing", headers=headers)
    assert pricing.status_code == 200
    assert "抖一抖" not in pricing.text
    assert {item["subject"] for item in pricing.json()["prices"]}.isdisjoint(
        {"cos", "zpay", "quality_inspection", "analysis_repair"}
    )
    response = client.get("/api/customer/billing/quote?service=analysis&units=2", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["credits"] == 14
    assert client.get("/api/control/billing/catalog", headers=headers).status_code in {401, 403}


def credit_lot(raw, user_id, *, key, credits, amount_fen, provider="zpay"):
    raw.execute(
        "INSERT INTO recharge_orders(id,user_id,merchant_order_no,provider,status,pricing_scope,"
        "base_unit_price_fen_snapshot,charged_unit_price_fen_snapshot,min_recharge_fen_snapshot,"
        "recharge_step_fen_snapshot,amount_fen,credits,credit_pricing_snapshot_json,paid_at) "
        "VALUES(%s,%s,%s,%s,%s,'CUSTOMER_STANDARD',1,1,1,1,%s,%s,%s,now())",
        (
            key,
            user_id,
            key,
            provider,
            "PENDING" if provider == "zpay" else "PAID",
            amount_fen,
            credits,
            '{"points_per_yuan":' + str(credits * 100 // amount_fen) + "}" if amount_fen else None,
        ),
    )
    raw.execute(
        "INSERT INTO wallet_transactions(id,user_id,type,available_delta,reserved_delta,"
        "recharge_order_id,idempotency_key) "
        "VALUES(%s,%s,'CHARGE',%s,0,%s,%s)",
        (key, user_id, credits, key, key),
    )
    raw.execute(
        "UPDATE wallets SET available_credits=available_credits+%s WHERE user_id=%s",
        (credits, user_id),
    )


def test_recharge_and_gift_consumption_revenue_are_distinct_from_point_face_value(
    client, route_state
):
    _, uid = account(client)
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        raw.execute(
            "UPDATE customer_credit_pricing SET config_json=%s", ('{"points_per_yuan":100}',)
        )
        raw.execute(
            "INSERT INTO billing_tariffs(service,enabled,unit_credits,unit_cost_fen) "
            "VALUES('character',true,75,10)"
        )
        # Paying 100 fen for 200 credits includes a discount/bonus: each credit carries 0.5 fen.
        credit_lot(raw, uid, key="cash", credits=200, amount_fen=100)
        credit_lot(raw, uid, key="gift", credits=100, amount_fen=0, provider="admin_adjustment")
        first = accept_operation(conn, user_id=uid, service="character", source_id="mixed", units=4)
        record_attempt(conn, operation_id=first, attempt_key="images", usage=3)
        finish_operation(conn, operation_id=first, units=3, succeeded=True)
        row = raw.execute(
            "SELECT charged_credits,revenue_fen,nominal_revenue_fen FROM billing_operations "
            "WHERE id=%s",
            (first,),
        ).fetchone()
        assert tuple(row) == (225, Decimal(100), Decimal(225))
        assert (
            raw.execute(
                "SELECT remaining_credits FROM billing_credit_lots WHERE id='gift'"
            ).fetchone()[0]
            == 75
        )
        second = accept_operation(
            conn, user_id=uid, service="character", source_id="gift-only", units=1
        )
        record_attempt(conn, operation_id=second, attempt_key="image", usage=1)
        finish_operation(conn, operation_id=second, units=1, succeeded=True)
        report = statistics(conn, start=date(2020, 1, 1), end=date(2099, 1, 1))
        assert report["totals"]["known_revenue_fen"] == 100
        assert report["totals"]["known_cost_fen"] == 40
        assert report["totals"]["profit_fen"] == 60


def test_preexisting_unknown_balance_is_not_relabelled_as_new_cash(client, route_state):
    _, uid = account(client)
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        raw.execute("UPDATE wallets SET available_credits=10 WHERE user_id=%s", (uid,))
        credit_lot(raw, uid, key="later-cash", credits=20, amount_fen=100)
        raw.execute(
            "INSERT INTO billing_tariffs(service,enabled,unit_credits,unit_cost_fen) "
            "VALUES('analysis',true,5,1)"
        )
        operation = accept_operation(
            conn, user_id=uid, service="analysis", source_id="unknown-funds", units=1
        )
        finish_operation(conn, operation_id=operation, units=1, succeeded=True)
        assert (
            raw.execute(
                "SELECT revenue_fen FROM billing_operations WHERE id=%s", (operation,)
            ).fetchone()[0]
            is None
        )
        assert (
            raw.execute(
                "SELECT remaining_credits FROM billing_credit_lots WHERE id='later-cash'"
            ).fetchone()[0]
            == 20
        )


def test_admin_publishes_independent_cost_and_price_with_audit_and_conflict(
    pricing_client, route_state
):
    from uuid import uuid4

    from app.billing_routes import router

    client = pricing_client
    client.app.include_router(router)
    customer, uid = account(client)
    admin = admin_login(client, route_state)
    request_headers = {**admin, "Idempotency-Key": str(uuid4())}
    payload = {
        "confirm": True,
        "reason": "Approved per-second test tariff",
        "service": "oral",
        "expected_version": 0,
        "tariff": {
            "enabled": True,
            "unit_credits": "0.25",
            "unit_cost_fen": "0.000125",
            "unit_rounding": "exact",
        },
    }
    response = client.put("/api/control/billing/tariff", headers=request_headers, json=payload)
    assert response.status_code == 200, response.text
    assert (
        client.put("/api/control/billing/tariff", headers=request_headers, json=payload).json()
        == response.json()
    )
    stale = client.put(
        "/api/control/billing/tariff",
        headers={**admin, "Idempotency-Key": str(uuid4())},
        json=payload,
    )
    assert stale.status_code == 409
    customer_quote = client.get(
        "/api/customer/billing/quote?service=oral&units=5.1", headers=customer
    )
    assert customer_quote.json()["credits"] == 2
    assert "unit_cost_fen" not in customer_quote.text
    with psycopg.connect(route_state) as raw:
        assert (
            raw.execute(
                "SELECT count(*) FROM audit_logs WHERE action='billing.tariff.update'"
            ).fetchone()[0]
            == 1
        )
        conn = BusinessConnection.postgres(raw)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as insufficient:
            accept_operation(
                conn, user_id=uid, service="oral", source_id="zero-wallet-paid", units=5.1
            )
        assert insufficient.value.status_code == 402


def test_core_facts_cannot_be_repriced_or_rewritten(client, route_state):
    _, uid = account(client)
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        operation = accept_operation(
            conn, user_id=uid, service="analysis", source_id="immutable", units=1
        )
        attempt = record_attempt(conn, operation_id=operation, attempt_key="once", usage=1)
        finish_operation(conn, operation_id=operation, units=1, succeeded=True)
    for sql, value in (
        ("UPDATE billing_operations SET revenue_fen=100 WHERE id=%s", operation),
        ("UPDATE billing_attempts SET unit_cost_fen=999 WHERE id=%s", attempt),
        ("DELETE FROM billing_operations WHERE id=%s", operation),
    ):
        with pytest.raises(psycopg.errors.RaiseException):
            with psycopg.connect(route_state) as raw:
                raw.execute(sql, (value,))


def test_tariff_save_rejects_stale_currency_conversion_without_repricing(
    pricing_client, route_state
):
    from uuid import uuid4

    from app.billing_routes import router

    client = pricing_client
    client.app.include_router(router)
    admin = admin_login(client, route_state)
    published = client.get("/api/control/billing/catalog", headers=admin)
    assert published.status_code == 200
    pricing = published.json()["pricing"]
    payload = {
        "confirm": True,
        "reason": "Currency display conversion test",
        "service": "oral",
        "expected_version": 0,
        "expected_pricing_version": pricing["version"],
        "tariff": {"enabled": True, "unit_credits": "12.5", "unit_cost_fen": "0.000001"},
    }
    with psycopg.connect(route_state) as raw:
        raw.execute("UPDATE customer_credit_pricing SET version=version+1 WHERE id=1")
    key = {**admin, "Idempotency-Key": str(uuid4())}
    stale = client.put("/api/control/billing/tariff", headers=key, json=payload)
    assert stale.status_code == 409
    assert "充值换算已变化" in stale.text
    with psycopg.connect(route_state) as raw:
        assert (
            raw.execute("SELECT count(*) FROM billing_tariffs WHERE service='oral'").fetchone()[0]
            == 0
        )
    payload["expected_pricing_version"] += 1
    saved = client.put("/api/control/billing/tariff", headers=key, json=payload)
    assert saved.status_code == 200, saved.text
    assert (
        client.put("/api/control/billing/tariff", headers=key, json=payload).json() == saved.json()
    )
    with psycopg.connect(route_state) as raw:
        row = raw.execute(
            "SELECT unit_credits,unit_cost_fen FROM billing_tariffs WHERE service='oral'"
        ).fetchone()
        assert row == (Decimal("12.5"), Decimal("0.000001"))


def test_microsecond_usage_and_fractional_cost_replay(client, route_state):
    _, uid = account(client)
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        raw.execute("INSERT INTO billing_tariffs(service,unit_cost_fen) VALUES('asr',0.000125)")
        operation = accept_operation(
            conn, user_id=uid, service="asr", source_id="precise", units="6.1234567"
        )
        for _ in range(2):
            record_attempt(
                conn, operation_id=operation, attempt_key="transcribe", usage="6.1234567"
            )
            finish_operation(conn, operation_id=operation, units="6.1234567", succeeded=True)
        assert raw.execute(
            "SELECT cost_fen FROM billing_attempts WHERE operation_id=%s", (operation,)
        ).fetchone()[0] == Decimal("0.00076543")


def test_admin_cost_evidence_resolves_unknown_profit_without_repricing(pricing_client, route_state):
    from uuid import uuid4

    from app.billing_routes import router

    pricing_client.app.include_router(router)
    customer, uid = account(pricing_client)
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        operation = accept_operation(
            conn, user_id=uid, service="analysis", source_id="bill", units=1
        )
        attempt = record_attempt(conn, operation_id=operation, attempt_key="paid-call", usage=1)
        finish_operation(conn, operation_id=operation, units=1, succeeded=True)
    admin = admin_login(pricing_client, route_state)
    body = {
        "confirm": True,
        "reason": "Supplier bill checked",
        "operation_id": operation,
        "attempt_id": attempt,
        "cost_fen": "0.01234567",
        "reference": "bill-line-1",
    }
    assert (
        pricing_client.post(
            "/api/control/billing/evidence",
            json=body,
            headers={**customer, "Idempotency-Key": str(uuid4())},
        ).status_code
        == 403
    )
    headers = {**admin, "Idempotency-Key": str(uuid4())}
    response = pricing_client.post("/api/control/billing/evidence", json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert (
        pricing_client.post("/api/control/billing/evidence", json=body, headers=headers).json()
        == response.json()
    )
    duplicate = pricing_client.post(
        "/api/control/billing/evidence",
        json=body,
        headers={**admin, "Idempotency-Key": str(uuid4())},
    )
    assert duplicate.status_code == 409
    detail = pricing_client.get(
        f"/api/control/billing/operations/{operation}", headers=admin
    ).json()
    assert Decimal(str(detail["profit_fen"])) == Decimal("-0.01234567")
    assert detail["attempts"][0]["unit_cost_fen"] is None
    assert len(detail["evidence"]) == 1
    with pytest.raises(psycopg.errors.RaiseException):
        with psycopg.connect(route_state) as raw:
            raw.execute("DELETE FROM billing_evidence WHERE operation_id=%s", (operation,))


@pytest.mark.parametrize(
    "grain,periods",
    [
        ("day", ["2024-02-29", "2024-03-01", "2024-03-04"]),
        ("week", ["2024-02-26", "2024-03-04"]),
        ("month", ["2024-02-01", "2024-03-01"]),
        ("year", ["2024-01-01"]),
    ],
)
def test_statistics_use_shanghai_calendar_and_keep_retries_out_of_revenue(
    client, route_state, grain, periods
):
    from uuid import uuid4

    _, uid = account(client)
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        for timestamp in ("2024-02-29T15:59:59Z", "2024-02-29T16:00:00Z", "2024-03-03T16:00:00Z"):
            op = str(uuid4())
            raw.execute(
                "INSERT INTO billing_operations(id,user_id,service,module,source_id,unit,"
                "budget_units,"
                "pricing_snapshot_json,state,actual_units,revenue_fen,completed_at) "
                "VALUES(%s,%s,'analysis','replica',%s,'call',1,'{}','SUCCEEDED',1,0,%s)",
                (op, uid, op, timestamp),
            )
            for attempt in ("first", "retry"):
                record_attempt(conn, operation_id=op, attempt_key=attempt, usage=0)
        report = statistics(
            conn, start=date(2024, 2, 1), end=date(2024, 3, 31), grain=grain, user_id=uid
        )
        assert [p["period"] for p in report["periods"]] == periods
        assert report["totals"]["operation_count"] == 3
        assert report["totals"]["provider_call_count"] == 6
        assert report["totals"]["profit_fen"] == 0


def test_actual_tikhub_transport_is_attributed_to_user_or_platform(client, route_state):
    from test_viral_tikhub import FakeTransport

    from app.billing_meter import billing_context
    from app.viral_tikhub import ViralSourceClient

    _, uid = account(client)
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        raw.execute(
            "INSERT INTO billing_tariffs(service,unit_cost_fen) VALUES('viral_data',0.0125)"
        )
        operation = accept_operation(
            conn, user_id=uid, service="viral_data", source_id="refresh-one", units=1
        )
    transport = FakeTransport([{"code": 200, "data": {}}, {"code": 200, "data": {}}])
    source = ViralSourceClient(api_key="test-key", transport=transport)
    with billing_context("refresh-one"):
        source._request(transport, "/fake/statistics", {})
    source._request(transport, "/fake/background", {})
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        finish_operation(conn, operation_id=operation, units=1, succeeded=True)
        attempts = raw.execute(
            "SELECT o.user_id,a.cost_fen FROM billing_operations o "
            "JOIN billing_attempts a ON a.operation_id=o.id ORDER BY o.user_id NULLS LAST"
        ).fetchall()
        assert [tuple(row) for row in attempts] == [
            (uid, Decimal("0.0125")),
            (None, Decimal("0.0125")),
        ]
        assert raw.execute("SELECT count(*) FROM wallet_transactions").fetchone()[0] == 0


@pytest.mark.parametrize("status", ["REQUEST_SENT", "FAILED_SAFE", "UNCERTAIN"])
def test_undelivered_link_receipts_recover_reserved_credits(client, route_state, status):
    from app.usage_billing import begin_source_attempt, reconcile_operations
    from app.viral_import_routes import _claim_link_receipt, _mark_link_request_sent

    _, uid = account(client)
    with psycopg.connect(route_state) as raw:
        conn = BusinessConnection.postgres(raw)
        raw.execute("UPDATE wallets SET available_credits=20 WHERE user_id=%s", (uid,))
        raw.execute(
            "INSERT INTO billing_tariffs(service,enabled,unit_credits) "
            "VALUES('link_resolution',true,5)"
        )
        receipt, claimed = _claim_link_receipt(
            conn,
            owner_user_id=uid,
            idempotency_key="crashed",
            normalized_url="https://v.douyin.com/test",
            purpose="replica",
        )
        assert claimed
        op = accept_operation(
            conn, user_id=uid, service="link_resolution", source_id=str(receipt["id"]), units=1
        )
        _mark_link_request_sent(
            conn, receipt_id=str(receipt["id"]), lease_owner=str(receipt["lease_owner"])
        )
        begin_source_attempt(conn, str(receipt["id"]))
        raw.execute(
            "UPDATE viral_link_resolution_receipts SET "
            "status=%s,lease_expires_at='2000-01-01T00:00:00Z' WHERE id=%s",
            (status, receipt["id"]),
        )
        assert reconcile_operations(conn) == 1
        assert reconcile_operations(conn) == 0
        assert tuple(
            raw.execute(
                "SELECT available_credits,reserved_credits FROM wallets WHERE user_id=%s", (uid,)
            ).fetchone()
        ) == (20, 0)
        assert (
            raw.execute(
                "SELECT charged_credits FROM billing_operations WHERE id=%s", (op,)
            ).fetchone()[0]
            == 0
        )
        assert (
            raw.execute(
                "SELECT cost_fen FROM billing_attempts WHERE operation_id=%s", (op,)
            ).fetchone()[0]
            is None
        )
        replay, claimed_again = _claim_link_receipt(
            conn,
            owner_user_id=uid,
            idempotency_key="crashed",
            normalized_url="https://v.douyin.com/test",
            purpose="replica",
        )
        assert claimed_again is False
        assert replay["id"] == receipt["id"]
