#!/usr/bin/env bash
# Superset version upgrade (official image + our image with the browser).
#
# Prerequisites (in order):
#   1. ./scripts/backup-db.sh                       (ALWAYS — the database migration does not roll itself back)
#   2. TAG and BROWSER_TAG pointing at the new version in docker/.env-local
#      (and the default in docker-compose.yml / ARG SUPERSET_VERSION in docker-browser/Dockerfile)
#   3. Read the UPDATING.md for the new version:
#      https://github.com/apache/superset/blob/<version>/UPDATING.md
#
# What it does: pulls the official image, builds the image with Chromium, runs
# `compose up -d` (the superset-init service runs `superset db upgrade` +
# `superset init`), waits for health and prints the version that came up.
#
# The metadata database is OVHcloud Managed PostgreSQL, an external service, so
# `superset db upgrade` migrates a database this script does not control and
# cannot roll back. Two consequences:
#   - ./scripts/backup-db.sh is not optional. It is the only rollback path.
#   - `--remove-orphans` below will delete containers for services that no
#     longer exist in docker-compose.yml. That is intended (it retires the old
#     local `db` container if you are upgrading from a pre-managed-database
#     deployment), but be aware of it before running this on a host with other
#     compose services in the same project.
#
# Usage: sudo ./scripts/upgrade-superset.sh 6.1.0
set -euo pipefail

VERSION="${1:?usage: $0 <version, e.g. 6.1.0>}"
COMPOSE_DIR="${COMPOSE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$COMPOSE_DIR"

export TAG="$VERSION" BROWSER_TAG="$VERSION"

echo ">> pull apache/superset:$VERSION"
docker pull "apachesuperset.docker.scarf.sh/apache/superset:$VERSION"

echo ">> build astecha/superset-browser:$VERSION"
docker build --build-arg "SUPERSET_VERSION=$VERSION" -t "astecha/superset-browser:$VERSION" docker-browser/

echo ">> compose up (superset-init runs db upgrade + init)"
docker compose up -d --remove-orphans
docker compose logs -f superset-init 2>&1 | sed -n '1,200p' &
LOGPID=$!
docker wait "$(docker compose ps -q superset-init)" >/dev/null
kill $LOGPID 2>/dev/null || true

echo ">> waiting for the superset health check"
for i in $(seq 1 60); do
  if docker compose exec -T superset curl -sf http://localhost:8088/health >/dev/null 2>&1; then break; fi
  sleep 5
done
docker compose ps
docker compose exec -T superset /app/.venv/bin/python -c "from superset import config; print('VERSION_STRING =', config.VERSION_STRING)"

# Nginx resolves the `superset` upstream when it parses its config; the recreated
# container has a new IP and the site stays on 502 until the reload (pitfall 2 in
# the README).
echo ">> reloading nginx (the upstream was recreated)"
docker compose exec -T nginx nginx -t && docker compose exec -T nginx nginx -s reload
curl -sk -o /dev/null -w "health via nginx: %{http_code}\n" https://127.0.0.1/health || true
echo ">> ok. Rollback: put TAG/BROWSER_TAG back + restore the dump (see scripts/backup-db.sh)."
