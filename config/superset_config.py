#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""
Production configuration for Apache Superset.

Baked into the image at /app/pythonpath/superset_config.py by the Dockerfile.
The official image already sets PYTHONPATH=/app/pythonpath, and Superset imports
`superset_config` from there automatically.

Every deployment-specific value comes from an environment variable. Nothing in
this file is a secret, and nothing here may ever become one.
"""

import logging
import os
from urllib.parse import quote_plus

from cachelib.redis import RedisCache


def _require(name: str) -> str:
    """Fail fast at boot with an actionable message instead of misbehaving later."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Required environment variable {name} is not set. "
            f"Add it in Dokploy under the application's Environment tab. "
            f"See .env.example for the full list."
        )
    return value


# =========================================================================
# SECRET KEY
# =========================================================================
# Encrypts session cookies AND the stored passwords of every database
# connection you create inside Superset.
#
# Changing it after first boot makes those stored passwords undecryptable; you
# then have to run `superset re-encrypt-secrets`. Choose it once, before the
# first deploy, and keep it in Dokploy only.
SECRET_KEY = _require("SUPERSET_SECRET_KEY")

# =========================================================================
# METADATA DATABASE - OVHcloud Managed PostgreSQL (external)
# =========================================================================
# There is no PostgreSQL container. The URI is assembled here rather than being
# passed whole so that no credential ever appears in docker-compose.yml.
POSTGRES_HOST = _require("POSTGRES_HOST")
# Required on purpose, with NO default. OVHcloud Managed PostgreSQL does not
# listen on 5432; it assigns a port in the 20000 range. Defaulting to 5432 would
# turn a typo into a connection timeout that looks like a firewall problem.
POSTGRES_PORT = _require("POSTGRES_PORT")
POSTGRES_DB = _require("POSTGRES_DB")
POSTGRES_USER = _require("POSTGRES_USER")
POSTGRES_PASSWORD = _require("POSTGRES_PASSWORD")

# OVHcloud requires TLS. `require` encrypts without validating the server
# certificate; `verify-full` also validates it and additionally needs
# POSTGRES_SSLROOTCERT to point at the CA file downloaded from the OVH panel.
POSTGRES_SSLMODE = os.environ.get("POSTGRES_SSLMODE", "require")
POSTGRES_SSLROOTCERT = os.environ.get("POSTGRES_SSLROOTCERT", "").strip()

# quote_plus on both user and password: OVHcloud generates passwords containing
# characters that are structural in a URI (@ : / ? #). Interpolating them raw
# produces a URI that either fails to parse or silently points somewhere else.
_db_query = f"sslmode={POSTGRES_SSLMODE}"
if POSTGRES_SSLROOTCERT:
    _db_query += f"&sslrootcert={quote_plus(POSTGRES_SSLROOTCERT)}"

SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://{quote_plus(POSTGRES_USER)}:{quote_plus(POSTGRES_PASSWORD)}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}?{_db_query}"
)

# A managed database closes idle connections. Without pre-ping, the first query
# after an idle period fails with "server closed the connection unexpectedly".
SQLALCHEMY_ENGINE_OPTIONS = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "pool_size": int(os.environ.get("DB_POOL_SIZE", "10")),
    "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "5")),
}

SQLALCHEMY_TRACK_MODIFICATIONS = False

# =========================================================================
# REDIS - cache and Celery broker
# =========================================================================
# Runs as a container on the internal Docker network only. It is never
# published to a host port and must never be reachable from the internet.
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

# Separate logical databases keep unrelated data from evicting each other.
REDIS_CELERY_DB = int(os.environ.get("REDIS_CELERY_DB", "0"))
REDIS_CACHE_DB = int(os.environ.get("REDIS_CACHE_DB", "1"))
REDIS_RESULTS_DB = int(os.environ.get("REDIS_RESULTS_DB", "2"))


def _cache(db: int, prefix: str, timeout: int) -> dict:
    return {
        "CACHE_TYPE": "RedisCache",
        "CACHE_DEFAULT_TIMEOUT": timeout,
        "CACHE_KEY_PREFIX": prefix,
        "CACHE_REDIS_HOST": REDIS_HOST,
        "CACHE_REDIS_PORT": REDIS_PORT,
        "CACHE_REDIS_DB": db,
    }


# General-purpose cache (24h).
CACHE_CONFIG = _cache(REDIS_CACHE_DB, "superset_", 60 * 60 * 24)
# Chart query results (24h). The big one: this is what makes dashboards fast.
DATA_CACHE_CONFIG = _cache(REDIS_CACHE_DB, "superset_data_", 60 * 60 * 24)
# Dashboard thumbnails (7 days) - only populated when Celery workers run.
THUMBNAIL_CACHE_CONFIG = _cache(REDIS_CACHE_DB, "superset_thumb_", 60 * 60 * 24 * 7)

# These two are the ones people forget, and the omission is subtle: they default
# to per-process storage. With more than one Gunicorn worker, a dashboard filter
# set on worker A is invisible to worker B, so filters appear to reset at random.
# Redis-backing them is what makes a multi-worker deployment behave correctly.
FILTER_STATE_CACHE_CONFIG = _cache(REDIS_CACHE_DB, "superset_filter_", 60 * 60 * 24 * 90)
EXPLORE_FORM_DATA_CACHE_CONFIG = _cache(REDIS_CACHE_DB, "superset_form_", 60 * 60 * 24 * 7)

# SQL Lab query results. Redis rather than the local filesystem, so results
# survive a redeploy and are shared across containers.
RESULTS_BACKEND = RedisCache(
    host=REDIS_HOST, port=REDIS_PORT, db=REDIS_RESULTS_DB, key_prefix="superset_results_"
)

# =========================================================================
# CELERY - async tasks
# =========================================================================
_REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}"


class CeleryConfig:
    broker_url = f"{_REDIS_URL}/{REDIS_CELERY_DB}"
    result_backend = f"{_REDIS_URL}/{REDIS_CELERY_DB}"
    imports = (
        "superset.sql_lab",
        "superset.tasks.scheduler",
        "superset.tasks.cache",
    )
    worker_prefetch_multiplier = 1
    task_acks_late = True
    # Ceiling for a single task. Long SQL Lab queries are the reason this is not
    # the 60s default.
    task_soft_time_limit = int(os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", "600"))
    task_time_limit = int(os.environ.get("CELERY_TASK_TIME_LIMIT", "1200"))


CELERY_CONFIG = CeleryConfig

# =========================================================================
# REVERSE PROXY AND HTTPS
# =========================================================================
# Traefik (managed by Dokploy) terminates TLS and forwards plain HTTP to
# port 8088 on the internal network.
#
# MANDATORY. Without it Flask only sees the proxy's plain-HTTP connection, so it
# builds every absolute URL as http://. The visible symptom is a login redirect
# loop: you submit the form, Superset redirects to an http:// URL, Traefik sends
# you back to https://, the session cookie is dropped, and you are returned to
# the login page with no error message.
#
# Safe only because Traefik sets X-Forwarded-Proto / X-Forwarded-For itself and
# Superset is not reachable except through it.
ENABLE_PROXY_FIX = True
PREFERRED_URL_SCHEME = "https"

# =========================================================================
# SESSION AND CSRF SECURITY
# =========================================================================
# Secure defaults to true: the cookie is then only ever sent over HTTPS.
# Set SESSION_COOKIE_SECURE=false ONLY for a local plain-HTTP test, never in
# production - it would allow the session cookie to travel in clear text.
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"
SESSION_COOKIE_HTTPONLY = True  # not readable from JavaScript, blunts XSS
SESSION_COOKIE_SAMESITE = "Lax"  # blunts cross-site request forgery

WTF_CSRF_ENABLED = True
# Sessions that outlive the CSRF token produce spurious "CSRF token expired"
# errors on long-lived dashboard tabs. None ties token validity to the session.
WTF_CSRF_TIME_LIMIT = None
# Endpoints that are exempt by necessity; keep this list as short as possible.
WTF_CSRF_EXEMPT_LIST = [
    "superset.views.core.log",
    "superset.charts.data.api.data",
]

# How long a user stays logged in.
PERMANENT_SESSION_LIFETIME = int(os.environ.get("SESSION_LIFETIME_SECONDS", str(60 * 60 * 12)))

# =========================================================================
# APPLICATION SETTINGS
# =========================================================================
APP_NAME = os.environ.get("APP_NAME", "Superset")

# Rows returned to the browser. Higher values mean slower dashboards and more
# memory per request, not more insight.
ROW_LIMIT = int(os.environ.get("ROW_LIMIT", "50000"))
SQL_MAX_ROW = int(os.environ.get("SQL_MAX_ROW", "100000"))

# Seconds a synchronous query may run before Gunicorn gives up. Must stay BELOW
# GUNICORN_TIMEOUT (set in docker-compose.yml), otherwise Gunicorn kills the
# worker before Superset can return a useful error.
SUPERSET_WEBSERVER_TIMEOUT = int(os.environ.get("SUPERSET_WEBSERVER_TIMEOUT", "300"))

# Superset stores all timestamps in UTC. This only affects how they are rendered.
# The container's TZ variable is set in docker-compose.yml.
MAPBOX_API_KEY = os.environ.get("MAPBOX_API_KEY", "")

FEATURE_FLAGS = {
    # Lets dashboard owners embed charts elsewhere; harmless and often wanted.
    "EMBEDDED_SUPERSET": False,
    # Alerts & Reports needs an SMTP or Slack channel AND a headless-browser
    # worker image. This deployment has neither, so it stays off. Turning it on
    # without them produces reports that render and then silently go nowhere.
    "ALERT_REPORTS": False,
    # Modern table chart: in-cell bars, per-row conditional formatting.
    "AG_GRID_TABLE_ENABLED": True,
}

# =========================================================================
# LOGGING
# =========================================================================
# To stdout, which is what `docker logs` and the Dokploy Logs tab read.
LOG_LEVEL = os.environ.get("SUPERSET_LOG_LEVEL", "INFO").upper()
ENABLE_TIME_ROTATE = False
logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")
