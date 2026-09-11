#!/usr/bin/env bash
# CW-032 — build the FIRST customer app image on a blank host.
#
# deploy/customer-git-rollout.sh builds every subsequent release FROM the
# previous image (OLD_IMAGE); this script produces that first image from a
# clean base using only registered in-repo artifacts, so a blank isolated
# directory can rebuild API/Worker/Admin without any unregistered host file
# or pre-existing image.
#
# Usage:  bootstrap-base-image.sh <git-short-sha>
# Result: video-replica-rehearsal-app:<sha>  (then point APP_IMAGE at it in
#         deploy/customer/.env and `docker compose up -d`; see README.md)
#
# The in-image checks mirror the rollout's Dockerfile contract exactly:
# ffmpeg/ffprobe present, locked dependencies, python compileall, the four
# runtime imports, and the CW-060 historical-tooling physical scan.
set -euo pipefail

SHORT_SHA="${1:?usage: bootstrap-base-image.sh <git-short-sha>}"
[[ "$SHORT_SHA" =~ ^[A-Za-z0-9_.-]{1,64}$ ]] || {
    echo "invalid image tag fragment: $SHORT_SHA" >&2
    exit 1
}
SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_CTX="$(mktemp -d)"
trap 'rm -rf -- "$BUILD_CTX"' EXIT

mkdir -p "$BUILD_CTX/server"
cp -a "$SOURCE/server/app" "$BUILD_CTX/server/app"
cp -a "$SOURCE/server/migrations" "$BUILD_CTX/server/migrations"
cp -a "$SOURCE/server/alembic.ini" "$BUILD_CTX/server/alembic.ini"
cp -a "$SOURCE/server/pyproject.toml" "$SOURCE/server/uv.lock" "$BUILD_CTX/server/"
# CW-060 / PG-09: historical SQLite operator tooling never enters the
# customer image (defense in depth — the rollout applies the same scan).
rm -f "$BUILD_CTX/server/app/backup.py"

cat > "$BUILD_CTX/Dockerfile" <<'DOCKERFILE'
FROM python:3.12-slim
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv
COPY server /opt/video-replica/server
RUN cd /opt/video-replica/server \
    && uv sync --locked --no-dev \
    && .venv/bin/python -m compileall -q app migrations \
    && command -v ffmpeg && command -v ffprobe \
    && .venv/bin/python -c "import app.main, app.admin_customer_routes, app.customer_fence, app.generation_worker" \
    && ! test -e /opt/video-replica/server/app/backup.py \
    && ! test -e /opt/video-replica/server/scripts/sqlite_to_postgres.py \
    && ! test -e /opt/video-replica/server/scripts/reconcile_customer_billing.py \
    && .venv/bin/python -c "import pathlib, sys; forbidden = {'backup.py', 'sqlite_to_postgres.py', 'reconcile_customer_billing.py'}; found = [str(p) for p in pathlib.Path('/opt/video-replica/server').rglob('*') if p.is_file() and p.name in forbidden]; sys.exit('historical SQLite tooling in the customer image: ' + repr(found) if found else 0)"
ENV PATH="/opt/video-replica/server/.venv/bin:$PATH"
WORKDIR /opt/video-replica/server
DOCKERFILE

docker build \
    --label "org.opencontainers.image.revision=$SHORT_SHA" \
    -t "video-replica-rehearsal-app:$SHORT_SHA" \
    "$BUILD_CTX"
printf 'base image ready: video-replica-rehearsal-app:%s\n' "$SHORT_SHA"
printf 'next: set APP_IMAGE in deploy/customer/.env, then docker compose up -d (see README.md)\n'
