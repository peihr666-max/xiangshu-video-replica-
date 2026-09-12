"""Bounded PostgreSQL upload reclamation. CLI defaults to a read-only preview.

Run repeated pages (then restart from the beginning on the next sweep). The
append-only upload-intent audit receipt survives project and identity deletion.
No bucket lifecycle configuration is changed by this command.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.db_pg import resolve_cli_pg_dsn
from app.storage import (
    StorageAdapter,
    StorageBackendUnavailable,
    require_storage_match,
    storage_object_ref_from_uri,
)


def cleanup_upload_page(
    dsn: str,
    *,
    storage: StorageAdapter,
    after_asset_id: str = "",
    object_cursor: str = "",
    object_asset_id: str = "",
    limit: int = 100,
    apply: bool = False,
    grace: timedelta = timedelta(hours=1),
) -> dict[str, Any]:
    if not 1 <= limit <= 1000 or grace < timedelta(hours=1):
        raise ValueError("cleanup requires a bounded page and at least one hour grace")
    if bool(object_cursor) != bool(object_asset_id):
        raise ValueError("an object cursor must name its asset")
    result: dict[str, Any] = {
        "scanned": 0,
        "eligible": 0,
        "deleted": 0,
        "failed": 0,
        "next_asset_id": None,
        "next_object_cursor": "",
        "next_object_asset_id": "",
        "apply": apply,
    }
    with psycopg.connect(resolve_cli_pg_dsn(dsn), autocommit=True, row_factory=dict_row) as conn:
        rows = conn.execute(
            "SELECT DISTINCT ON (id) id, metadata_json FROM ("
            "SELECT id, metadata_json, 0 AS priority FROM assets "
            "WHERE (id > %s AND (%s = '' OR id >= %s)) "
            "AND metadata_json::jsonb ? 'upload_source_uri' UNION ALL "
            "SELECT entity_id AS id, metadata_json, 1 AS priority FROM audit_logs "
            "WHERE (entity_id > %s AND (%s = '' OR entity_id >= %s)) "
            "AND action IN ('asset.upload_intent.create', "
            "'studio.material.upload_intent', 'person_identity.source_upload_intent.create', "
            "'person_identity.authorization_upload_intent.create') "
            "AND metadata_json::jsonb ? 'upload_source_uri') AS receipts "
            "ORDER BY id, priority LIMIT %s",
            (
                after_asset_id,
                object_asset_id,
                object_asset_id,
                after_asset_id,
                object_asset_id,
                object_asset_id,
                limit,
            ),
        ).fetchall()
        last_complete = after_asset_id
        for identity in rows:
            asset_id = str(identity["id"])
            before_asset = last_complete
            last_complete = asset_id
            result["scanned"] += 1
            with conn.transaction():
                row = conn.execute(
                    "SELECT * FROM assets WHERE id = %s FOR UPDATE", (asset_id,)
                ).fetchone()
                metadata = json.loads(str(identity["metadata_json"]))
                expiry = metadata.get("intent_expires_at")
                source_uri = metadata.get("upload_source_uri")
                if not isinstance(expiry, str) or not isinstance(source_uri, str):
                    continue  # Legacy rows without a grant lifetime need an explicit inventory.
                try:
                    expires = datetime.fromisoformat(expiry)
                    if expires.tzinfo is None:
                        continue
                    source = storage_object_ref_from_uri(source_uri)
                    require_storage_match(storage, source)
                except (ValueError, StorageBackendUnavailable):
                    continue
                now_row = conn.execute("SELECT clock_timestamp() AS now").fetchone()
                assert now_row is not None
                if expires.astimezone(UTC) + grace > now_row["now"]:
                    continue
                status = (
                    json.loads(str(row["metadata_json"])).get("upload_status") if row else "EXPIRED"
                )
                if status not in {"PENDING", "EXPIRED", "COMPLETE", "READY"}:
                    continue
                result["eligible"] += 1
                if status == "PENDING" and apply:
                    metadata["upload_status"] = "EXPIRED"
                    conn.execute(
                        "UPDATE assets SET metadata_json = %s WHERE id = %s",
                        (json.dumps(metadata, sort_keys=True), asset_id),
                    )
            # The state transition commits before any storage I/O. All completion
            # writers lock/recheck EXPIRED, so a previously prepared probe cannot win.
            try:
                cursor = object_cursor if asset_id == object_asset_id else ""
                keys = storage.list_upload_keys(asset_id, after=cursor, limit=100)
                for key in dict.fromkeys([source.key, *keys]):
                    uri = f"{storage.provider}://{storage.bucket}/{key}"
                    # Only the expired pending asset's zero-byte staging reference
                    # is disposable; every ready reference (including another asset)
                    # protects the object from deletion.
                    referenced = conn.execute(
                        "SELECT 1 FROM assets WHERE storage_uri = %s "
                        "AND NOT (id = %s AND size_bytes = 0 AND sha256 = '') LIMIT 1",
                        (uri, asset_id),
                    ).fetchone()
                    if referenced is not None or not apply:
                        continue
                    if storage.head_object(key) is not None:
                        storage.delete_object(key)
                        result["deleted"] += 1
                if len(keys) == 100:
                    result["next_asset_id"] = before_asset
                    result["next_object_cursor"] = keys[-1]
                    result["next_object_asset_id"] = asset_id
                    return result
                object_cursor = ""
            except StorageBackendUnavailable:
                result["failed"] += 1
                result["next_asset_id"] = before_asset
                result["next_object_cursor"] = object_cursor
                result["next_object_asset_id"] = object_asset_id if object_cursor else ""
                return result  # Retry this page, including deleted-asset receipts.
        if len(rows) == limit:
            result["next_asset_id"] = str(rows[-1]["id"])
    return result


def main() -> int:
    from app.db_portable import BusinessConnection
    from app.media_routes import get_media_storage

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--after-asset-id", default="")
    parser.add_argument("--object-cursor", default="")
    parser.add_argument("--object-asset-id", default="")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    dsn = resolve_cli_pg_dsn()
    with psycopg.connect(dsn) as raw:
        storage = get_media_storage(BusinessConnection.postgres(raw))
    result = cleanup_upload_page(
        dsn,
        storage=storage,
        apply=args.apply,
        limit=args.limit,
        after_asset_id=args.after_asset_id,
        object_cursor=args.object_cursor,
        object_asset_id=args.object_asset_id,
    )
    print(json.dumps(result, sort_keys=True))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
