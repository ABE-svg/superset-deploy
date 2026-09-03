#!/usr/bin/env bash
# Upgrade de versão do Superset (imagem oficial + nossa imagem com browser).
#
# Pré-requisitos (na ordem):
#   1. ./scripts/backup-db.sh                       (SEMPRE — a migração do banco não volta sozinha)
#   2. TAG e BROWSER_TAG apontando para a versão nova em docker/.env-local
#      (e o default no docker-compose.yml / ARG SUPERSET_VERSION no docker-browser/Dockerfile)
#   3. Ler o UPDATING.md da versão nova:
#      https://github.com/apache/superset/blob/<versão>/UPDATING.md
#
# O que faz: pull da imagem oficial, build da imagem com Chromium, `compose up -d`
# (o serviço superset-init roda `superset db upgrade` + `superset init`), espera o
# health e imprime a versão que subiu.
#
# Uso: sudo ./scripts/upgrade-superset.sh 6.1.0
set -euo pipefail

VERSION="${1:?uso: $0 <versão, ex: 6.1.0>}"
COMPOSE_DIR="${COMPOSE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$COMPOSE_DIR"

export TAG="$VERSION" BROWSER_TAG="$VERSION"

echo ">> pull apache/superset:$VERSION"
docker pull "apachesuperset.docker.scarf.sh/apache/superset:$VERSION"

echo ">> build astecha/superset-browser:$VERSION"
docker build --build-arg "SUPERSET_VERSION=$VERSION" -t "astecha/superset-browser:$VERSION" docker-browser/

echo ">> compose up (superset-init roda db upgrade + init)"
docker compose up -d --remove-orphans
docker compose logs -f superset-init 2>&1 | sed -n '1,200p' &
LOGPID=$!
docker wait "$(docker compose ps -q superset-init)" >/dev/null
kill $LOGPID 2>/dev/null || true

echo ">> esperando health do superset"
for i in $(seq 1 60); do
  if docker compose exec -T superset curl -sf http://localhost:8088/health >/dev/null 2>&1; then break; fi
  sleep 5
done
docker compose ps
docker compose exec -T superset /app/.venv/bin/python -c "from superset import config; print('VERSION_STRING =', config.VERSION_STRING)"
echo ">> ok. Rollback: TAG/BROWSER_TAG de volta + restore do dump (ver scripts/backup-db.sh)."
