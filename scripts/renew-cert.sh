#!/usr/bin/env bash
#
# Renova o certificado Let's Encrypt e recarrega o nginx com segurança.
#
# Por que um script em vez de dois comandos soltos: o `nginx -s reload` re-parseia
# a config inteira, e o nginx resolve TODOS os upstreams nesse parse. Se um
# container referenciado como upstream estiver parado, o reload FALHA e o nginx
# segue servindo o certificado antigo — sem erro visível em lugar nenhum. Por
# isso o `nginx -t` aqui é bloqueante e o script verifica o que está REALMENTE
# sendo servido no fim, em vez de confiar na saída do certbot.
#
set -euo pipefail

DOMAIN="${DOMAIN:-dashboard.astecha.com.br}"
COMPOSE="${COMPOSE:-docker compose}"

cd "$(dirname "$0")/.."

echo "### Certificado atual"
$COMPOSE run --rm --entrypoint "certbot certificates" certbot 2>&1 \
  | grep -E "Certificate Name|Expiry Date" || true

echo
echo "### Simulação (não gasta rate limit do Let's Encrypt)"
$COMPOSE run --rm --entrypoint "certbot renew --dry-run" certbot

echo
echo "### Renovação"
$COMPOSE run --rm --entrypoint "certbot renew" certbot

echo
echo "### Testando a config do nginx ANTES de recarregar"
if ! $COMPOSE exec nginx nginx -t; then
  echo >&2
  echo "ERRO: a config do nginx não valida — reload abortado." >&2
  echo "O nginx continua no ar servindo o certificado ANTIGO." >&2
  echo "Causa comum: 'host not found in upstream' porque algum container" >&2
  echo "referenciado em conf/nginx/superset.conf está parado." >&2
  exit 1
fi

$COMPOSE exec nginx nginx -s reload
echo "### nginx recarregado"

echo
echo "### O que está sendo servido agora (fonte da verdade)"
echo | openssl s_client -connect localhost:443 -servername "$DOMAIN" 2>/dev/null \
  | openssl x509 -noout -dates -subject
