#!/usr/bin/env bash
set -euo pipefail

: "${VIDEO_REPLICA_DATABASE_URL:?VIDEO_REPLICA_DATABASE_URL is required}"
: "${VIDEO_REPLICA_CUSTOMER_PRODUCTION:?VIDEO_REPLICA_CUSTOMER_PRODUCTION=true is required}"

case "${VIDEO_REPLICA_CUSTOMER_PRODUCTION,,}" in
    1|true|yes|on) ;;
    *)
        echo "customer migration requires VIDEO_REPLICA_CUSTOMER_PRODUCTION=true" >&2
        exit 64
        ;;
esac

# This is a host-local concurrency guard. The runbook designates exactly one
# migration host, so two deploy sessions on that host cannot race Alembic.
# Do not run this script concurrently from multiple hosts.
LOCK_FILE="${VIDEO_REPLICA_MIGRATION_LOCK_FILE:-/var/lock/video-replica-pg-migrate.lock}"
cd /opt/video-replica/app/server
# Alembic reads the DSN directly, so run the same customer-production database
# gate before it can touch any target. This rejects SQLite and libpq modes that
# permit plaintext fallback before the first migration statement executes.
.venv/bin/python -c \
    'from app.db_pg import resolve_database_config, validate_customer_production; validate_customer_production(resolve_database_config())'

# Not exec'd: a post-upgrade head check has to run in this same shell. `exec`
# replaces the process, so anything written after it would never execute.
flock -n "$LOCK_FILE" .venv/bin/alembic upgrade head

# Verify what is actually applied. `alembic upgrade head` exits 0 when the
# database is already at head, so a green run on its own cannot distinguish
# "just migrated" from "deployed new code against an old schema and did
# nothing" -- and the second case is the one that pages someone at 3am.
# Read-only, so it is safe to run after the lock is released.
EXPECTED_HEAD="$(.venv/bin/alembic heads | awk 'NR == 1 {print $1}')"
ACTUAL_HEAD="$(.venv/bin/alembic current | awk 'NR == 1 {print $1}')"
if [ -z "$EXPECTED_HEAD" ] || [ "$ACTUAL_HEAD" != "$EXPECTED_HEAD" ]; then
    echo "migration did not reach the expected head: current='${ACTUAL_HEAD}' expected head='${EXPECTED_HEAD}'" >&2
    exit 70
fi
echo "migration verified at expected head: ${ACTUAL_HEAD}"
