#!/usr/bin/env bash
#
# Renews the Let's Encrypt certificate and reloads nginx safely.
#
# Why a script instead of two loose commands: `nginx -s reload` re-parses the
# entire config, and nginx resolves ALL upstreams during that parse. If a
# container referenced as an upstream is stopped, the reload FAILS and nginx
# carries on serving the old certificate — with no visible error anywhere. That
# is why the `nginx -t` here is a blocking gate, and why the script checks what
# is REALLY being served at the end rather than trusting certbot's output.
#
set -euo pipefail

DOMAIN="${DOMAIN:-dashboard.astecha.com.br}"
COMPOSE="${COMPOSE:-docker compose}"

cd "$(dirname "$0")/.."

echo "### Current certificate"
$COMPOSE run --rm --entrypoint "certbot certificates" certbot 2>&1 \
  | grep -E "Certificate Name|Expiry Date" || true

echo
echo "### Dry run (does not consume the Let's Encrypt rate limit)"
$COMPOSE run --rm --entrypoint "certbot renew --dry-run" certbot

echo
echo "### Renewal"
$COMPOSE run --rm --entrypoint "certbot renew" certbot

echo
echo "### Testing the nginx config BEFORE reloading"
if ! $COMPOSE exec nginx nginx -t; then
  echo >&2
  echo "ERROR: the nginx config does not validate — reload aborted." >&2
  echo "Nginx stays up, still serving the OLD certificate." >&2
  echo "Common cause: 'host not found in upstream' because a container" >&2
  echo "referenced in conf/nginx/superset.conf is stopped." >&2
  exit 1
fi

$COMPOSE exec nginx nginx -s reload
echo "### nginx reloaded"

echo
echo "### What is being served right now (the source of truth)"
echo | openssl s_client -connect localhost:443 -servername "$DOMAIN" 2>/dev/null \
  | openssl x509 -noout -dates -subject
