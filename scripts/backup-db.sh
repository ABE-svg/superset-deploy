#!/usr/bin/env bash
#
# Optional: take a portable snapshot of the Superset metadata database.
#
# You do NOT need this for routine operation. OVHcloud already backs up the
# managed database automatically. The two cover different failures:
#
#   OVHcloud backups  restore the whole service to a point in time. They are
#                     your protection against infrastructure loss.
#   This script       produces a single portable .dump file you can inspect,
#                     copy elsewhere, or restore selectively. It is your
#                     protection against a bad Superset version upgrade, where
#                     `superset db upgrade` has already migrated the schema and
#                     there is no reverse migration.
#
# Run it BEFORE changing SUPERSET_VERSION. That is the moment it earns its keep.
#
# It needs no PostgreSQL client on the host: pg_dump runs inside a throwaway
# container. Connection details are read from the same .env the stack uses, so
# it can never dump a different database from the one Superset is using.
#
# Usage, from the project directory on the server:
#   ./scripts/backup-db.sh
#   BACKUP_DIR=/mnt/backups ./scripts/backup-db.sh
#
# Restoring is destructive and deliberately not automated. See the README,
# section "Backups and restore".
#
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
# Must match the managed server's major version: an older pg_dump refuses to run
# against a newer server.
PG_IMAGE="${PG_IMAGE:-postgres:16-alpine}"
TS="$(date +%Y%m%d-%H%M%S)"

if [ ! -f "$ENV_FILE" ]; then
  echo "!! $ENV_FILE not found. Run this from the project directory on the server," >&2
  echo "   where Dokploy has written the .env file." >&2
  exit 1
fi

# Read a value from the env file without sourcing it, so that a stray command
# in that file can never be executed by this script.
get_var() {
  grep -E "^${1}=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- | tr -d '"'"'"'\r'
}

DB_HOST="$(get_var POSTGRES_HOST)"
DB_PORT="$(get_var POSTGRES_PORT)"
DB_NAME="$(get_var POSTGRES_DB)"
DB_USER="$(get_var POSTGRES_USER)"
DB_PASS="$(get_var POSTGRES_PASSWORD)"
DB_SSLMODE="$(get_var POSTGRES_SSLMODE)"
DB_SSLMODE="${DB_SSLMODE:-require}"

for var in DB_HOST DB_PORT DB_NAME DB_USER DB_PASS; do
  if [ -z "${!var}" ]; then
    echo "!! ${var/DB_/POSTGRES_} is empty in $ENV_FILE - aborting" >&2
    exit 1
  fi
done

mkdir -p "$BACKUP_DIR"
OUT="$BACKUP_DIR/superset_${TS}.dump"

echo ">> Dumping ${DB_NAME} from ${DB_HOST}:${DB_PORT} (sslmode=${DB_SSLMODE})"
docker run --rm -i \
  -e PGPASSWORD="$DB_PASS" \
  -e PGSSLMODE="$DB_SSLMODE" \
  "$PG_IMAGE" \
  pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" \
          --format=custom --no-owner --no-acl "$DB_NAME" > "$OUT"

# A dump that "succeeded" but is empty is the failure this catches. Checking the
# table list is cheap and turns a silent disaster into a loud one.
echo ">> Verifying the dump contains Superset's core tables"
docker run --rm -i "$PG_IMAGE" pg_restore -l < "$OUT" \
  | grep -qE "TABLE DATA public (dashboards|slices|ab_user) " \
  || { echo "!! Dump is missing core tables - deleting it and aborting" >&2; rm -f "$OUT"; exit 1; }

chmod 600 "$OUT"
echo ">> OK: $OUT ($(du -h "$OUT" | cut -f1))"
echo
echo "   This file contains your dashboards, charts and user accounts."
echo "   Copy it OFF this server. A backup that only exists on the machine it"
echo "   protects is not a backup."
