"""Admin fee catalog and economics, customer-safe tariff publication and quotes."""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from typing import Any
from uuid import uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import Field

from app.admin_auth_routes import AdminReader, AdminWriter
from app.admin_write_contract import AdminWriteContract, write_with_idempotency
from app.billing_catalog import SERVICES, Tariff, read_tariff, retail_snapshot
from app.billing_reports import operation_rows, statistics
from app.customer_fence import customer_read_transaction
from app.db_pg import pg_transaction
from app.db_portable import BusinessConnection

router = APIRouter(tags=["itemized-billing"])


def catalog(conn: BusinessConnection, *, admin: bool) -> list[dict[str, Any]]:
    result = []
    for key, service in SERVICES.items():
        tariff = read_tariff(conn, key)
        item: dict[str, Any] = {
            "service": key,
            "name": service.name,
            "unit": service.unit,
            "module": service.module,
            "customer_charge_allowed": service.customer_charge_allowed,
            "configured": tariff is not None,
        }
        if admin:
            item["provider"] = service.provider
            item["tariff"] = (tariff or Tariff()).model_dump(mode="json")
        else:
            item["quote"] = retail_snapshot(conn, key, 1)
        result.append(item)
    return result


class TariffUpdate(AdminWriteContract):
    service: str
    expected_version: int = Field(ge=0)
    tariff: Tariff


@router.get("/api/control/billing/catalog")
def admin_catalog(_actor: AdminReader, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    with pg_transaction() as raw:
        return {"services": catalog(BusinessConnection.postgres(raw), admin=True)}


@router.put("/api/control/billing/tariff")
def update_tariff(
    payload: TariffUpdate, request: Request, response: Response, actor: AdminWriter
) -> dict[str, Any]:
    if payload.service not in SERVICES:
        raise HTTPException(422, detail="未知计费科目")
    if payload.tariff.enabled and (
        payload.tariff.unit_credits is None or not SERVICES[payload.service].customer_charge_allowed
    ):
        raise HTTPException(422, detail="该科目不允许启用用户收费，或尚未填写售价")
    if payload.service in {"cos", "zpay"} and payload.tariff.unit_cost_fen not in {None, 0}:
        raise HTTPException(422, detail="云存储和支付通道按零费用核算")

    def business(raw: psycopg.Connection, request_id: str) -> dict[str, Any]:
        conn = BusinessConnection.postgres(raw)
        # Serialize missing-row inserts as well as updates; one publication truth per subject.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("billing:tariffs",))
        old = read_tariff(conn, payload.service)
        if (old.version if old else 0) != payload.expected_version:
            raise HTTPException(
                409,
                detail={
                    "code": "PRICING_VERSION_CONFLICT",
                    "message": "价格已变化，请刷新后重试。",
                },
            )
        tariff = payload.tariff
        conn.execute(
            """
            INSERT INTO billing_tariffs(service,enabled,unit_credits,unit_cost_fen,unit_rounding,updated_by_user_id)
            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(service) DO UPDATE SET
              enabled=excluded.enabled,unit_credits=excluded.unit_credits,unit_cost_fen=excluded.unit_cost_fen,
              unit_rounding=excluded.unit_rounding,updated_by_user_id=excluded.updated_by_user_id,
              version=billing_tariffs.version+1,updated_at=now()
        """,
            (
                payload.service,
                tariff.enabled,
                tariff.unit_credits,
                tariff.unit_cost_fen,
                tariff.unit_rounding,
                actor.user_id,
            ),
        )
        conn.execute(
            "INSERT INTO audit_logs(id,actor_user_id,action,entity_type,entity_id,metadata_json) "
            "VALUES (%s,%s,'billing.tariff.update','billing_tariff',%s,%s)",
            (
                str(uuid4()),
                actor.user_id,
                payload.service,
                json.dumps(
                    {
                        "old": old.model_dump(mode="json") if old else None,
                        "new": tariff.model_dump(mode="json"),
                        "reason": payload.reason,
                        "request_id": request_id,
                    }
                ),
            ),
        )
        return {"services": catalog(conn, admin=True)}

    return write_with_idempotency(
        request,
        response,
        actor,
        payload,
        business,
        success_status=200,
        unavailable_code="PRICING_UNAVAILABLE",
        unavailable_message="计价配置暂不可用。",
    )


@router.get("/api/customer/billing/catalog")
def customer_catalog(request: Request, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    with customer_read_transaction(request) as (raw, _):
        return {"services": catalog(BusinessConnection.postgres(raw), admin=False)}


@router.get("/api/customer/billing/quote")
def customer_quote(
    request: Request, response: Response, service: str, units: str = "1"
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    try:
        with customer_read_transaction(request) as (raw, _):
            return retail_snapshot(BusinessConnection.postgres(raw), service, units)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.get("/api/control/billing/operations")
def operations(
    _actor: AdminReader,
    start: date,
    end: date,
    user_id: str | None = None,
    service: str | None = None,
    module: str | None = None,
    provider: str | None = None,
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    with pg_transaction() as raw:
        rows = operation_rows(
            BusinessConnection.postgres(raw),
            start=start,
            end=end,
            user_id=user_id,
            service=service,
            module=module,
            provider=provider,
            limit=limit,
            offset=offset,
        )
        return {"items": rows, "total": rows[0]["total_count"] if rows else 0}


@router.get("/api/control/billing/statistics")
def report(
    _actor: AdminReader,
    start: date,
    end: date,
    grain: str = "day",
    user_id: str | None = None,
    service: str | None = None,
    module: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    with pg_transaction() as raw:
        return statistics(
            BusinessConnection.postgres(raw),
            start=start,
            end=end,
            grain=grain,
            user_id=user_id,
            service=service,
            module=module,
            provider=provider,
        )


@router.get("/api/control/billing/operations/{operation_id}")
def operation_detail(operation_id: str, _actor: AdminReader) -> dict[str, Any]:
    with pg_transaction() as raw:
        conn = BusinessConnection.postgres(raw)
        rows = operation_rows(
            conn, start=date(2000, 1, 1), end=date(9998, 12, 31), operation_id=operation_id
        )
        if not rows:
            raise HTTPException(404, detail="计费请求不存在")
        rows[0]["attempts"] = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM billing_attempts WHERE operation_id=%s ORDER BY created_at,id",
                (operation_id,),
            ).fetchall()
        ]
        return rows[0]


@router.get("/api/control/billing/export")
def export(
    _actor: AdminReader,
    start: date,
    end: date,
    user_id: str | None = None,
    service: str | None = None,
    module: str | None = None,
    provider: str | None = None,
) -> Response:
    with pg_transaction() as raw:
        rows = operation_rows(
            BusinessConnection.postgres(raw),
            start=start,
            end=end,
            user_id=user_id,
            service=service,
            module=module,
            provider=provider,
            limit=5000,
        )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    keys = [
        "id",
        "username",
        "service",
        "state",
        "unit",
        "actual_units",
        "charged_credits",
        "revenue_fen",
        "cost_fen",
        "profit_fen",
        "completed_at",
    ]
    writer.writerow(keys)
    for row in rows:
        writer.writerow(
            [
                ("'" + str(row[key]))
                if str(row[key]).startswith(("=", "+", "-", "@"))
                else row[key]
                for key in keys
            ]
        )
    return Response(
        "\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=billing-operations.csv",
            "X-Export-Truncated": str(bool(rows and rows[0]["total_count"] > 5000)).lower(),
        },
    )
