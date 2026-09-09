#!/usr/bin/env bash
# Superset backup, to be taken BEFORE any upgrade/migration.
#
# The metadata database is OVHcloud Managed PostgreSQL, an external service, so
# there is no local container to exec into. pg_dump therefore runs inside a
# throwaway postgres container on the compose network, connecting over TLS. No
# PostgreSQL client needs to be installed on the host.
#
# Why keep this at all when OVHcloud already backs the service up: their
# automated backups restore the whole instance to a point in time. They do not
# give you a portable artifact you can inspect, diff or restore selectively
# after a bad `superset db upgrade`, and their schedule is not synchronised with
# your upgrades. This script is the pre-migration safety net; OVH's backups are
# the infrastructure-loss safety net. They cover different failures.
#
# Produces the following in /home/ubuntu/backups (or $BACKUP_DIR):
#   superset_meta_<ts>.dump   pg_dump -Fc of the metadata DB (dashboards, charts,
#                             datasets, users, alerts, themes...) — this is the
#                             one that matters
#   superset_home_<ts>.tgz    the superset_home volume (thumbnails, SQL Lab cache,
#                             Playwright cache). Not critical; skip it with
#                             SKIP_HOME=1 if the volume has grown large.
#   env-local_<ts>.bak        copy of docker/.env-local (secrets — chmod 600)
#   checksums_<ts>.txt        sha256 of the files produced
#
# Note: there is no pg_dumpall --globals-only step any more. Roles and tablespaces
# are managed by OVHcloud and a managed user cannot read them.
#
# Usage (inside the compose directory):
#   ./scripts/backup-db.sh
#   SKIP_HOME=1 ./scripts/backup-db.sh
#
# Restoring the metadata DB (DESTRUCTIVE — only in a disaster, and only into a
# database created for the purpose):
#   docker run --rm -i --network <project>_superset \
#     -e PGPASSWORD -e PGSSLMODE=require postgres:16 \
#     pg_restore -h <host> -p <port> -U <user> -d <db> --clean --if-exists < superset_meta_<ts>.dump
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/home/ubuntu/backups}"
TS="$(date +%Y%m%d-%H%M%S)"

cd "$COMPOSE_DIR"

# Connection details come from docker/.env-local, the same file the stack uses,
# so the backup can never silently target a different database.
ENV_LOCAL="${ENV_LOCAL:-docker/.env-local}"
if [ ! -f "$ENV_LOCAL" ]; then
  echo "!! $ENV_LOCAL not found — cannot determine the database to back up" >&2
  exit 1
fi

get_var() {
  # Last occurrence wins, matching how docker compose layers env files.
  grep -E "^${1}=" "$ENV_LOCAL" | tail -n 1 | cut -d= -f2- | tr -d '"'"'"'\r'
}

DB_HOST="$(get_var DATABASE_HOST)"
DB_PORT="$(get_var DATABASE_PORT)"
DB_NAME="$(get_var DATABASE_DB)"
DB_USER="$(get_var DATABASE_USER)"
DB_PASS="$(get_var DATABASE_PASSWORD)"
DB_SSLMODE="$(get_var DATABASE_SSLMODE)"
DB_SSLMODE="${DB_SSLMODE:-require}"

for v in DB_HOST DB_PORT DB_NAME DB_USER DB_PASS; do
  if [ -z "${!v}" ]; then
    echo "!! ${v/DB_/DATABASE_} is empty in $ENV_LOCAL — aborting" >&2
    exit 1
  fi
done

# Pinned to match the managed server's major version. A pg_dump older than the
# server refuses to run; a newer one is fine but produces a dump the older
# pg_restore cannot read.
PG_IMAGE="${PG_IMAGE:-postgres:16}"

mkdir -p "$BACKUP_DIR"

echo ">> pg_dump ${DB_NAME} @ ${DB_HOST}:${DB_PORT} (sslmode=${DB_SSLMODE}) -> $BACKUP_DIR/superset_meta_$TS.dump"
docker run --rm -i \
  -e PGPASSWORD="$DB_PASS" \
  -e PGSSLMODE="$DB_SSLMODE" \
  "$PG_IMAGE" \
  pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -Fc --no-owner --no-acl "$DB_NAME" \
  > "$BACKUP_DIR/superset_meta_$TS.dump"

# Sanity check: the dump must list the core tables. A dump that "succeeded" but
# contains nothing is the failure mode this catches.
docker run --rm -i "$PG_IMAGE" pg_restore -l < "$BACKUP_DIR/superset_meta_$TS.dump" \
  | grep -E "TABLE DATA public (dashboards|slices|tables|dbs|ab_user) " >/dev/null \
  || { echo "!! dump is missing the core tables — aborting"; exit 1; }

BACKED_UP=("superset_meta_$TS.dump")

if [ "${SKIP_HOME:-0}" != "1" ]; then
  # Resolve the volume name from compose rather than hardcoding a project prefix:
  # the project name defaults to the directory name, so it is not always "superset".
  HOME_VOLUME="${HOME_VOLUME:-$(docker compose config --volumes >/dev/null 2>&1 && docker volume ls -q | grep -E '_superset_home$' | head -n 1)}"
  if [ -n "$HOME_VOLUME" ]; then
    echo ">> tar of the $HOME_VOLUME volume"
    docker run --rm -v "$HOME_VOLUME:/v:ro" -v "$BACKUP_DIR:/b" alpine \
      tar czf "/b/superset_home_$TS.tgz" -C /v .
    BACKED_UP+=("superset_home_$TS.tgz")
  else
    echo ">> superset_home volume not found — skipping (set HOME_VOLUME to override)"
  fi
fi

if [ -f "$ENV_LOCAL" ]; then
  cp "$ENV_LOCAL" "$BACKUP_DIR/env-local_$TS.bak"
  chmod 600 "$BACKUP_DIR/env-local_$TS.bak"
fi

( cd "$BACKUP_DIR" && sha256sum "${BACKED_UP[@]}" > "checksums_$TS.txt" )
ls -la "$BACKUP_DIR" | grep "$TS"
echo ">> ok: $TS"
