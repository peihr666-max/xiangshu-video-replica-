#!/usr/bin/env bash
# Deploy one audited Git commit to the existing customer stack.
set -Eeuo pipefail

usage() {
  echo "usage: $0 --commit <40-character-git-sha>" >&2
  exit 2
}

RELEASE_SHA=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --commit)
      RELEASE_SHA="${2:-}"
      shift 2
      ;;
    *) usage ;;
  esac
done
[[ "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]] || usage

ROOT="/opt/video-replica-candidate"
REPO_URL="${VIDEO_REPLICA_GIT_REPO_URL:-https://github.com/phlong026/xiangshu-video-replica.git}"
SOURCE="$ROOT/releases/$RELEASE_SHA"
SITE="/www/wwwroot/video.zszhj.cn"
COMPOSE="$ROOT/compose.yaml"
CUSTOMER_ENV="/etc/video-replica/customer.env"
SERVICE_USER="video-replica"
PUBLIC_ORIGIN="https://video.zszhj.cn"
NODE_BUILD_IMAGE="node:24-bookworm-slim"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
SHORT_SHA="${RELEASE_SHA:0:7}"
BACKUP="$ROOT/backups/git-$SHORT_SHA-$STAMP"
BUILD_CTX="$ROOT/build-git-$SHORT_SHA-$STAMP"
STAGE_SITE="$ROOT/site-git-$SHORT_SHA-$STAMP"
LOG="$ROOT/deploy-git-$SHORT_SHA-$STAMP.log"
STATUS="$ROOT/deploy-git-$SHORT_SHA-$STAMP.status"
NEW_IMAGE="video-replica-rehearsal-app:$SHORT_SHA-git"
SERVICES=(api-1 api-2 worker-1 worker-2 worker-3 worker-4)
ROLLOUT_STARTED=0

exec > >(tee -a "$LOG") 2>&1

mark() {
  printf '%s\n' "$1" > "$STATUS"
}

wait_ready() {
  local service="$1"
  for _ in $(seq 1 90); do
    local cid state
    cid=$(docker compose -f "$COMPOSE" ps -q "$service")
    if [[ -n "$cid" ]]; then
      state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid")
      if [[ "$state" == "healthy" || "$state" == "running" ]]; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

rollback() {
  local code="$1"
  local failed_line="$2"
  local failed_command="$3"
  trap - ERR
  printf 'DEPLOY_FAILED exit=%s line=%s command=%q\n' "$code" "$failed_line" "$failed_command"
  mark ROLLING_BACK
  if [[ -f "$BACKUP/compose-before.yaml" ]]; then
    cp -a "$BACKUP/compose-before.yaml" "$COMPOSE"
  fi
  if [[ -f "$BACKUP/site-before.tar.gz" ]]; then
    find "$SITE" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    tar -xzf "$BACKUP/site-before.tar.gz" -C "$SITE"
  fi
  if [[ "$ROLLOUT_STARTED" == "1" ]]; then
    docker compose -f "$COMPOSE" up -d --no-deps "${SERVICES[@]}" || true
  fi
  mark FAILED_ROLLED_BACK
  printf 'ROLLBACK_IMAGE=%s\nDATABASE_BACKUP=%s\nDATABASE_HEAD_LEFT_FORWARD_COMPATIBLE=%s\n' \
    "${OLD_IMAGE:-unknown}" "$BACKUP/database-before.dump" "${IMAGE_DB_HEAD:-unknown}"
  exit "$code"
}
trap 'rollback "$?" "$LINENO" "$BASH_COMMAND"' ERR

require_command() {
  command -v "$1" >/dev/null || {
    echo "PRECHECK_FAILED: missing required command: $1" >&2
    exit 1
  }
}

dependency_manifest_hash() {
  python3 -c '
import hashlib
import json
import sys
import tomllib

path = sys.argv[1]
format_path = sys.argv[2]
stream = sys.stdin.buffer if path == "-" else open(path, "rb")
with stream:
    document = tomllib.load(stream)
if format_path.endswith("pyproject.toml"):
    project = document["project"]
    manifest = {
        "requires-python": project["requires-python"],
        "dependencies": project.get("dependencies", []),
        "optional-dependencies": project.get("optional-dependencies", {}),
    }
else:
    manifest = {key: value for key, value in document.items() if key != "package"}
    manifest["package"] = [
        package for package in document.get("package", [])
        if package["name"] != "video-replica-api"
    ]
print(hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
' "$1" "$2"
}

cd "$ROOT"
mark PREFLIGHT
for command in git docker curl python3; do
  require_command "$command"
done
[[ -f "$COMPOSE" && -d "$SITE" && -r "$CUSTOMER_ENV" ]]
[[ ! -e "$BUILD_CTX" && ! -e "$STAGE_SITE" && ! -e "$BACKUP" ]]
[[ "$(df -Pk "$ROOT" | awk 'NR == 2 {print $4}')" -gt 4194304 ]]
docker compose -f "$COMPOSE" config --quiet
curl -fsS --max-time 20 "$PUBLIC_ORIGIN/health?preflight=$STAMP" >/dev/null
id "$SERVICE_USER" >/dev/null
docker image inspect "$NODE_BUILD_IMAGE" >/dev/null 2>&1 || docker pull "$NODE_BUILD_IMAGE"
docker run --rm --entrypoint node "$NODE_BUILD_IMAGE" -e \
  'process.exit(Number(process.versions.node.split(".")[0]) >= 24 ? 0 : 1)'

if [[ ! -d "$SOURCE/.git" ]]; then
  mkdir -p "$SOURCE"
  git -C "$SOURCE" init --quiet
  git -C "$SOURCE" remote add origin "$REPO_URL"
fi
[[ "$(git -C "$SOURCE" remote get-url origin)" == "$REPO_URL" ]]
git -C "$SOURCE" fetch --depth=1 origin "$RELEASE_SHA"
git -C "$SOURCE" checkout --detach --force FETCH_HEAD
[[ "$(git -C "$SOURCE" rev-parse HEAD)" == "$RELEASE_SHA" ]]
git -C "$SOURCE" diff --quiet
[[ -z "$(git -C "$SOURCE" status --porcelain)" ]]
RELEASE_TREE=$(git -C "$SOURCE" rev-parse 'HEAD^{tree}')

python3 "$SOURCE/scripts/customer_release_preflight.py" \
  --env-file "$CUSTOMER_ENV" \
  --service-user "$SERVICE_USER"
docker run --rm -v "$SOURCE:/workspace" -w /workspace \
  -e "VITE_API_BASE_URL=$PUBLIC_ORIGIN" "$NODE_BUILD_IMAGE" sh -lc \
  'npm ci --ignore-scripts && npm run build --workspace client'
[[ -s "$SOURCE/client/dist/index.html" && -d "$SOURCE/client/dist/assets" ]]
EXPECTED_ASSET=$(grep -oE 'assets/[^" ]+\.js' "$SOURCE/client/dist/index.html" | head -n 1)
[[ -n "$EXPECTED_ASSET" ]]

API_CONTAINER=$(docker compose -f "$COMPOSE" ps -q api-1)
DB_CONTAINER=$(docker compose -f "$COMPOSE" ps -q db)
[[ -n "$API_CONTAINER" && -n "$DB_CONTAINER" ]]
OLD_IMAGE=$(docker inspect -f '{{.Config.Image}}' "$API_CONTAINER")
OLD_IMAGE_USER=$(docker image inspect -f '{{.Config.User}}' "$OLD_IMAGE")
OLD_IMAGE_DB_HEAD=$(docker image inspect -f '{{index .Config.Labels "video-replica.database-head"}}' "$OLD_IMAGE")
[[ -n "$OLD_IMAGE_DB_HEAD" ]]
[[ -z "$OLD_IMAGE_USER" || "$OLD_IMAGE_USER" =~ ^[A-Za-z0-9_.:-]+$ ]]
for dependency_file in server/pyproject.toml server/uv.lock; do
  source_hash=$(dependency_manifest_hash "$SOURCE/$dependency_file" "$dependency_file")
  image_hash=$(docker run --rm --entrypoint sh "$OLD_IMAGE" -c 'cat "$1"' sh "/opt/video-replica/$dependency_file" | dependency_manifest_hash - "$dependency_file")
  [[ "$source_hash" == "$image_hash" ]] || {
    echo "PRECHECK_FAILED: Python dependency change requires a base-image release: $dependency_file" >&2
    exit 1
  }
done
HEADS_OUTPUT=$(docker run --rm -v "$SOURCE/server:/source:ro" --entrypoint sh "$OLD_IMAGE" -lc \
  'cd /source && alembic heads')
HEAD_COUNT=$(printf '%s\n' "$HEADS_OUTPUT" | awk '/\(head\)/ {count++} END {print count + 0}')
EXPECTED_DB_HEAD=$(printf '%s\n' "$HEADS_OUTPUT" | awk '/\(head\)/ {print $1}' | tail -n 1)
[[ "$HEAD_COUNT" == "1" && -n "$EXPECTED_DB_HEAD" ]]

mark BACKUP
mkdir -p "$BACKUP"
cp -a "$COMPOSE" "$BACKUP/compose-before.yaml"
printf '%s\n' "$OLD_IMAGE" > "$BACKUP/previous-image.txt"
printf '%s\n' "$RELEASE_SHA" > "$BACKUP/release-sha.txt"
printf '%s\n' "$RELEASE_TREE" > "$BACKUP/release-tree.txt"
docker compose -f "$COMPOSE" ps > "$BACKUP/compose-before.txt"
tar -czf "$BACKUP/site-before.tar.gz" -C "$SITE" .
CURRENT_HEAD_BEFORE=$(docker compose -f "$COMPOSE" exec -T db sh -lc \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT version_num FROM alembic_version"')
[[ "$CURRENT_HEAD_BEFORE" == "$OLD_IMAGE_DB_HEAD" ]]
printf '%s\n' "$CURRENT_HEAD_BEFORE" > "$BACKUP/database-revision-before.txt"
docker compose -f "$COMPOSE" exec -T db sh -lc \
  'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$BACKUP/database-before.dump"
[[ -s "$BACKUP/database-before.dump" ]]
docker exec -i "$DB_CONTAINER" pg_restore --list < "$BACKUP/database-before.dump" >/dev/null
sha256sum "$BACKUP/site-before.tar.gz" "$BACKUP/database-before.dump" > "$BACKUP/BACKUP-SHA256SUMS"

mark BUILD
mkdir -p "$BUILD_CTX/server" "$BUILD_CTX/scripts"
cp -a "$SOURCE/server/app" "$BUILD_CTX/server/app"
cp -a "$SOURCE/server/migrations" "$BUILD_CTX/server/migrations"
cp -a "$SOURCE/server/alembic.ini" "$BUILD_CTX/server/alembic.ini"
cp -a "$SOURCE/scripts/customer_release_preflight.py" "$BUILD_CTX/scripts/customer_release_preflight.py"
{
  printf 'FROM %s\n' "$OLD_IMAGE"
  cat <<'DOCKERFILE'
USER root
RUN rm -rf /opt/video-replica/server/app /opt/video-replica/server/migrations
COPY server/app /opt/video-replica/server/app
COPY server/migrations /opt/video-replica/server/migrations
COPY server/alembic.ini /opt/video-replica/server/alembic.ini
COPY scripts/customer_release_preflight.py /opt/video-replica/scripts/customer_release_preflight.py
RUN command -v ffmpeg \
    && command -v ffprobe \
    && chmod 0755 /opt/video-replica/scripts/customer_release_preflight.py \
    && python -m compileall -q /opt/video-replica/server/app /opt/video-replica/server/migrations \
    && cd /opt/video-replica/server \
    && python -c "import app.main, app.admin_customer_routes, app.customer_fence, app.generation_worker"
DOCKERFILE
  if [[ -n "$OLD_IMAGE_USER" ]]; then
    printf 'USER %s\n' "$OLD_IMAGE_USER"
  fi
} > "$BUILD_CTX/Dockerfile"

docker build \
  --label "org.opencontainers.image.revision=$RELEASE_SHA" \
  --label "org.opencontainers.image.source-tree=$RELEASE_TREE" \
  --label "video-replica.database-head=$EXPECTED_DB_HEAD" \
  -t "$NEW_IMAGE" \
  "$BUILD_CTX"
HEADS_OUTPUT=$(docker run --rm --entrypoint sh "$NEW_IMAGE" -lc 'cd /opt/video-replica/server && alembic heads')
HEAD_COUNT=$(printf '%s\n' "$HEADS_OUTPUT" | awk '/\(head\)/ {count++} END {print count + 0}')
IMAGE_DB_HEAD=$(printf '%s\n' "$HEADS_OUTPUT" | awk '/\(head\)/ {print $1}' | tail -n 1)
[[ "$HEAD_COUNT" == "1" && "$IMAGE_DB_HEAD" == "$EXPECTED_DB_HEAD" ]]

mark MIGRATE
python3 - "$COMPOSE" "$OLD_IMAGE" "$NEW_IMAGE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
old = sys.argv[2]
new = sys.argv[3]
text = path.read_text(encoding="utf-8")
if old not in text:
    raise SystemExit("current image is not present in compose.yaml")
path.write_text(text.replace(old, new), encoding="utf-8")
PY
docker compose -f "$COMPOSE" config --quiet
docker compose -f "$COMPOSE" run --rm --no-deps api-1 \
  sh -lc 'cd /opt/video-replica/server && alembic upgrade head'

mark ROLL_API
ROLLOUT_STARTED=1
for service in api-1 api-2; do
  mark "ROLLING_$service"
  docker compose -f "$COMPOSE" up -d --no-deps "$service"
  wait_ready "$service"
done

mark ROLL_WORKERS
for service in worker-1 worker-2 worker-3 worker-4; do
  mark "ROLLING_$service"
  docker compose -f "$COMPOSE" up -d --no-deps "$service"
  wait_ready "$service"
done

CURRENT_DB_HEAD=$(docker compose -f "$COMPOSE" exec -T api-1 \
  sh -lc 'cd /opt/video-replica/server && alembic current' \
  | awk '/\(head\)/ {print $1}' | tail -n 1)
[[ "$CURRENT_DB_HEAD" == "$IMAGE_DB_HEAD" ]]

mark SITE
mkdir -p "$STAGE_SITE"
cp -a "$SOURCE/client/dist"/. "$STAGE_SITE"/
grep -q "$EXPECTED_ASSET" "$STAGE_SITE/index.html"
find "$SITE" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
cp -a "$STAGE_SITE"/. "$SITE"/

mark VERIFY
for service in "${SERVICES[@]}"; do
  cid=$(docker compose -f "$COMPOSE" ps -q "$service")
  [[ -n "$cid" ]]
  [[ "$(docker inspect -f '{{.Config.Image}}' "$cid")" == "$NEW_IMAGE" ]]
  [[ "$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$cid")" == "$RELEASE_SHA" ]]
done
grep -q "$EXPECTED_ASSET" "$SITE/index.html"
curl -fsS --max-time 20 "$PUBLIC_ORIGIN/health?release=$SHORT_SHA" >/dev/null
CUSTOMER_HTML=$(curl -fsS --max-time 20 "$PUBLIC_ORIGIN/customer?release=$SHORT_SHA")
grep -q "$EXPECTED_ASSET" <<< "$CUSTOMER_HTML"
docker compose -f "$COMPOSE" exec -T api-1 sh -lc \
  "cd /opt/video-replica/server && python -c 'from app.main import app; assert \"/api/control/customer-sessions/live\" in app.openapi()[\"paths\"]'"

trap - ERR
mark SUCCESS
printf 'DEPLOYED=%s\nRELEASE_SHA=%s\nRELEASE_TREE=%s\nPREVIOUS_IMAGE=%s\nNEW_IMAGE=%s\nDATABASE_HEAD_BEFORE=%s\nDATABASE_HEAD_AFTER=%s\nCLIENT_ASSET=%s\nDATABASE_BACKUP=%s\n' \
  "$STAMP" "$RELEASE_SHA" "$RELEASE_TREE" "$OLD_IMAGE" "$NEW_IMAGE" \
  "$CURRENT_HEAD_BEFORE" "$CURRENT_DB_HEAD" "$EXPECTED_ASSET" "$BACKUP/database-before.dump"
