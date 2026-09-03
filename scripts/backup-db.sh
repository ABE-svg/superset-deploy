#!/usr/bin/env bash
# Backup do Superset ANTES de qualquer upgrade/migração.
#
# Gera em /home/ubuntu/backups (ou $BACKUP_DIR):
#   superset_meta_<ts>.dump   pg_dump -Fc do metadata DB (dashboards, charts,
#                             datasets, usuários, alertas, temas...) — é o que importa
#   superset_globals_<ts>.sql roles/globals do Postgres
#   superset_home_<ts>.tgz    volume superset_home (thumbnails, cache do SQL Lab,
#                             cache do Playwright). Não é crítico; pode ser pulado
#                             com SKIP_HOME=1 se o volume estiver grande.
#   env-local_<ts>.bak        cópia do docker/.env-local (segredos — chmod 600)
#   checksums_<ts>.txt        sha256 dos arquivos
#
# Uso (na EC2 dashboards-prod, dentro do diretório do compose):
#   sudo ./scripts/backup-db.sh
#
# Restore do metadata DB (destrutivo — só em desastre):
#   docker exec -i superset-db-1 pg_restore -U superset -d superset --clean --if-exists < superset_meta_<ts>.dump
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/home/ubuntu/backups}"
DB_CONTAINER="${DB_CONTAINER:-superset-db-1}"
DB_USER="${DB_USER:-superset}"
DB_NAME="${DB_NAME:-superset}"
HOME_VOLUME="${HOME_VOLUME:-superset_superset_home}"
TS="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"
cd "$COMPOSE_DIR"

echo ">> pg_dump $DB_NAME -> $BACKUP_DIR/superset_meta_$TS.dump"
docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -Fc --no-owner "$DB_NAME" > "$BACKUP_DIR/superset_meta_$TS.dump"
docker exec "$DB_CONTAINER" pg_dumpall -U "$DB_USER" --globals-only > "$BACKUP_DIR/superset_globals_$TS.sql"

# Sanity check: o dump precisa listar as tabelas centrais.
docker exec -i "$DB_CONTAINER" pg_restore -l < "$BACKUP_DIR/superset_meta_$TS.dump" \
  | grep -E "TABLE DATA public (dashboards|slices|tables|dbs|ab_user) " >/dev/null \
  || { echo "!! dump sem as tabelas centrais — abortando"; exit 1; }

if [ "${SKIP_HOME:-0}" != "1" ]; then
  echo ">> tar do volume $HOME_VOLUME"
  docker run --rm -v "$HOME_VOLUME:/v:ro" -v "$BACKUP_DIR:/b" alpine \
    tar czf "/b/superset_home_$TS.tgz" -C /v .
fi

if [ -f docker/.env-local ]; then
  cp docker/.env-local "$BACKUP_DIR/env-local_$TS.bak"
  chmod 600 "$BACKUP_DIR/env-local_$TS.bak"
fi

( cd "$BACKUP_DIR" && sha256sum superset_meta_"$TS".dump superset_home_"$TS".tgz 2>/dev/null > "checksums_$TS.txt" ) || true
ls -la "$BACKUP_DIR" | grep "$TS"
echo ">> ok: $TS"
