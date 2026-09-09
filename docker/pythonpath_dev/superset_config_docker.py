# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
Superset Docker Configuration - Production
This file overrides settings from superset_config.py for production deployment
"""

import os
from urllib.parse import quote_plus

# =========================================================================
# METADATA DATABASE - OVHcloud Managed PostgreSQL
# =========================================================================
# The metadata database is an external managed service, not a container.
#
# Why this URI is built here instead of being left to upstream:
# docker/pythonpath_dev/superset_config.py assembles it as a bare f-string,
#
#     f"{DATABASE_DIALECT}://{DATABASE_USER}:{DATABASE_PASSWORD}"
#     f"@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_DB}"
#
# with no hook for query parameters and no SQLALCHEMY_ENGINE_OPTIONS. There is
# therefore no way to get `sslmode` through the DATABASE_* variables alone, and
# TLS to a managed database over the public internet is mandatory. This file is
# imported at the END of the upstream config (`from superset_config_docker import *`),
# so the value below wins.
#
# Two further details this fixes:
#   1. The password is URL-encoded. OVHcloud generates passwords containing
#      characters that are significant in a URI (@ : / ? #); the upstream
#      f-string does not encode them, which produces a URI that either fails to
#      parse or silently connects to the wrong host.
#   2. `sslmode` is a variable, so moving to `verify-full` later (with the CA
#      certificate downloaded from the OVH control panel and DATABASE_SSLROOTCERT
#      pointing at it) needs no code change.
#
# Note: nothing else reuses this database. RESULTS_BACKEND is a filesystem cache
# under /app/superset_home/sqllab, and the Celery broker and result backend are
# both Redis, so this is the only place TLS has to be enforced.


def _require_db_env(name: str) -> str:
    """Fail fast, with an actionable message, rather than building a broken URI."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. The metadata database is external (OVHcloud "
            f"Managed PostgreSQL) and has no default. Set {name} in "
            f"docker/.env-local — see docker/.env-local.example and DEPLOYMENT.md."
        )
    return value


DATABASE_HOST = _require_db_env("DATABASE_HOST")
# OVHcloud does NOT use 5432. It assigns a non-standard port, typically in the
# 20000 range; take the exact value from the service page in the control panel.
DATABASE_PORT = _require_db_env("DATABASE_PORT")
DATABASE_DB = _require_db_env("DATABASE_DB")
DATABASE_USER = _require_db_env("DATABASE_USER")
DATABASE_PASSWORD = _require_db_env("DATABASE_PASSWORD")

# require  = encrypt, but do not verify the server certificate (default here)
# verify-ca / verify-full = also verify it; both need DATABASE_SSLROOTCERT
DATABASE_SSLMODE = os.getenv("DATABASE_SSLMODE", "require")
DATABASE_SSLROOTCERT = os.getenv("DATABASE_SSLROOTCERT", "")

SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://{quote_plus(DATABASE_USER)}:{quote_plus(DATABASE_PASSWORD)}"
    f"@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_DB}"
    f"?sslmode={DATABASE_SSLMODE}"
    + (f"&sslrootcert={quote_plus(DATABASE_SSLROOTCERT)}" if DATABASE_SSLROOTCERT else "")
)

# Recycle connections before the managed service's idle timeout closes them, and
# check liveness before handing a connection to a request. Without pre-ping, the
# first query after an idle period fails with "server closed the connection".
SQLALCHEMY_ENGINE_OPTIONS = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

# =========================================================================
# ALERTS AND REPORTS CONFIGURATION
# =========================================================================
# Disabled by default: this deployment has NO SMTP server, so a report would
# have no delivery channel. The whole feature is driven by one variable so that
# its absence never blocks a deploy.
#
# To enable it later you need all three of:
#   1. ALERT_REPORTS=true in docker/.env-local
#   2. an SMTP server configured (SMTP_HOST/SMTP_PORT/SMTP_USER/... below,
#      which are intentionally not defined here yet)
#   3. the Chromium worker image running, for chart screenshots
#      (docker compose --profile reports up -d)
ALERT_REPORTS_ENABLED = os.getenv("ALERT_REPORTS", "false").strip().lower() == "true"

FEATURE_FLAGS = {
    "ALERT_REPORTS": ALERT_REPORTS_ENABLED,
    # Playwright + Chromium ship in the browser image (see docker-browser/Dockerfile),
    # used by the superset-worker service under the "reports" profile. With this
    # flag on, WEBDRIVER_TYPE below no longer has any effect: Playwright is always
    # Chromium.
    #
    # Tied to the same switch: turning it on while the worker is running the plain
    # image (no Chromium) makes every screenshot and thumbnail fail.
    "PLAYWRIGHT_REPORTS_AND_THUMBNAILS": ALERT_REPORTS_ENABLED,
    # ---- Charts (6.x) ----
    # Table V2 with AG Grid: in-cell bars, per-row conditional formatting,
    # per-column pinning/filtering, time shift. Ships in the image but is off
    # by default.
    "AG_GRID_TABLE_ENABLED": True,
    # Enables the experimental plugins (currently: period-over-period Big Number).
    "CHART_PLUGINS_EXPERIMENTAL": True,
    # Dashboard reports that honour the state saved in `extra.dashboard`
    # (tabs and native filters). Without this the worker ignores `nativeFilters`
    # and sends the dashboard unfiltered.
    "ALERT_REPORT_TABS": ALERT_REPORTS_ENABLED,
}

# =========================================================================
# WEBDRIVER CONFIGURATION
# =========================================================================

# Internal base URL (for the worker to reach Superset)
# Uses the Docker service name
WEBDRIVER_BASEURL = os.getenv(
    "SUPERSET_WEBDRIVER_BASEURL",
    "http://superset:8088/"
)

# User-friendly base URL (the link that goes into the email)
# Uses the public domain
WEBDRIVER_BASEURL_USER_FRIENDLY = os.getenv(
    "WEBDRIVER_BASEURL_USER_FRIENDLY",
    "http://dashboard.astecha.com.br/"
)

# Ignored while PLAYWRIGHT_REPORTS_AND_THUMBNAILS is True.
# Kept only as a fallback in case the flag is turned off.
WEBDRIVER_TYPE = os.getenv("WEBDRIVER_TYPE", "chrome")

# Chrome arguments for headless mode
WEBDRIVER_OPTION_ARGS = [
    "--force-device-scale-factor=2.0",
    "--high-dpi-support=2.0",
    "--headless",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-extensions",
]

# Screenshot wait times
SCREENSHOT_LOCATE_WAIT = 100
SCREENSHOT_LOAD_WAIT = 600

# -------------------------------------------------------------------------
# Playwright waiting: making sure the charts have finished loading their data
# before the screenshot is taken. The sequence in utils/webdriver.py is:
#   goto(wait_until=WAIT_EVENT) -> sleep(HEADSTART) -> wait for .chart-container
#   -> wait for the .loading elements to disappear -> sleep(ANIMATION_WAIT)
#   -> screenshot
#
# The default "domcontentloaded" fires as soon as the HTML is parsed, that is
# BEFORE any query has come back. "networkidle" waits for the network to fall
# silent, which is the practical proxy for "the chart queries have finished".
SCREENSHOT_PLAYWRIGHT_WAIT_EVENT = "networkidle"

# Ceiling for each individual Playwright wait. If the network never falls
# silent, `goto` exceeds this timeout, that is logged, and the flow carries on
# anyway (the screenshot is not lost) — BUT the next wait, `element.wait_for()`
# on the .standalone selector, times out for real and brings the report down
# ("Failed taking a screenshot").
#
# 60s was not enough for the human-use dashboard (20 charts, ~5.3k px tall, so
# it falls into the tiled screenshot path) with force_screenshot on, which
# re-runs all 20 queries. Measured on 2026-09-03: 3 manual attempts, 2 of which
# blew past 60s. 150s covers the worst observed case with room to spare.
#
# This does not conflict with the Celery limit: for SCHEDULED reports the
# scheduler (tasks/scheduler.py) sets soft_time_limit = working_timeout + 1 =
# 3601s per task, ignoring the 180s global. The global only applies to a manual
# call of the task, and the thumbnail task has a fixed soft_time_limit of 300s —
# 150s fits inside both.
SCREENSHOT_PLAYWRIGHT_DEFAULT_TIMEOUT = 150000

# The wait on .loading only covers the elements that exist AT THAT MOMENT: a
# chart that has not started rendering yet (lazy-loaded below the fold) has no
# .loading element, so nothing waits for it. These two fixed sleeps are the
# slack that covers that gap.
SCREENSHOT_SELENIUM_HEADSTART = 10
SCREENSHOT_SELENIUM_ANIMATION_WAIT = 10


# =========================================================================
# EXECUTORS CONFIGURATION
# =========================================================================

# By default, alerts run as the owner of the alert/report.
# To use a fixed user instead, uncomment and configure:
# from superset.tasks.types import FixedExecutor
# ALERT_REPORTS_EXECUTORS = [FixedExecutor("admin")]

# =========================================================================
# ADDITIONAL FEATURES
# =========================================================================

# No notification method is configured: this deployment has no SMTP server.
# Slack is the alternative that needs no mail server — to use it, set a token and
# enable the flag here, and set ALERT_REPORTS=true in docker/.env-local:
# SLACK_API_TOKEN = os.getenv("SLACK_API_TOKEN", "")
# FEATURE_FLAGS["ALERT_REPORT_SLACK_V2"] = True
# ALERT_REPORTS_NOTIFICATION_METHODS = ["Slack"]

# =========================================================================
# BRANDING, THEME AND PALETTES (Superset 6.x)
# =========================================================================
# The theme lives in version-controlled JSON (docker/themes/*.json) and is
# loaded here so that this config remains the single source of truth. On app
# startup Superset upserts these two themes as "THEME_DEFAULT"/"THEME_DARK"
# (is_system=True) into the `themes` table — see superset/commands/theme/seed.py.
# As long as no theme is marked as "system default" in the UI
# (Settings > Themes), the one from this config is what applies.
#
# Logos and other static assets: docker/assets/ is mounted at
# /app/superset/static/assets/astecha (see docker-compose.yml), so the public
# path is /static/assets/astecha/<file>.
#
# Fonts: Superset's CSP (TALISMAN_CONFIG) only allows fonts.googleapis.com,
# fonts.gstatic.com and use.typekit.*; that is why Fira Sans/Fira Code come from
# Google Fonts rather than being self-hosted (THEME_FONT_URL_ALLOWED_DOMAINS).

import json as _json
from pathlib import Path as _Path

_THEMES_DIR = _Path(__file__).resolve().parent.parent / "themes"  # /app/docker/themes


def _load_theme(filename: str) -> dict:
    return _json.loads((_THEMES_DIR / filename).read_text(encoding="utf-8"))


APP_NAME = "Astecha Dashboard"
APP_ICON = "/static/assets/astecha/astecha-logo-light.png"

THEME_DEFAULT = _load_theme("astecha-light.json")
THEME_DARK = _load_theme("astecha-dark.json")

# Categorical palette = the same ASTECHA_PALETTE used by the home-app charts
# (frontend/src/lib/echarts.js), so that the Superset dashboards and the app
# read as a single product. isDefault=True makes it the default scheme for every
# new chart and for every chart that has not pinned a scheme of its own.
EXTRA_CATEGORICAL_COLOR_SCHEMES = [
    {
        "id": "astecha",
        "label": "Astecha",
        "description": "Institutional categorical palette (the same one as the home-app)",
        "isDefault": True,
        "colors": [
            "#0D0D38",  # near-black blue — anchor
            "#001EAF",  # deep blue
            "#2044DC",  # blue
            "#4571FF",  # light blue
            "#88AAFF",  # pastel blue
            "#FF6B06",  # orange
            "#FFBB8D",  # pastel orange
            "#F8485E",  # red
            "#FF99AF",  # pink
            "#46E8E0",  # turquoise
            "#B6FFE3",  # aqua green
            "#A6A6A6",  # grey
            "#118680",  # petrol green
            "#DBDBF7",  # light lilac
            "#C65000",  # burnt orange
        ],
    },
]

# Sequential/diverging scales derived from the brand's purple/red scale
# (astecha.css --purple-* / --red-*) and from the risk ramp (--risk-0..5).
EXTRA_SEQUENTIAL_COLOR_SCHEMES = [
    {
        "id": "astechaPurple",
        "label": "Astecha — purple",
        "description": "Sequential light-to-dark on the brand's purple scale",
        "isDiverging": False,
        "isDefault": True,
        "colors": [
            "#EFEAFB", "#D4C6F4", "#AD95E8", "#8463DB", "#5A33CC",
            "#3B0FAA", "#270173", "#1F015C", "#170144",
        ],
    },
    {
        "id": "astechaRedPurple",
        "label": "Astecha — red ↔ purple",
        "description": "Diverging: brand red ↔ brand purple",
        "isDiverging": True,
        "isDefault": False,
        "colors": [
            "#A91718", "#D21D1E", "#F64A4B", "#FBA3A4", "#FEECEC",
            "#EFEAFB", "#AD95E8", "#5A33CC", "#270173",
        ],
    },
    {
        "id": "astechaRisk",
        "label": "Astecha — risk (ok → critical)",
        "description": "Muted severity ramp: sage → amber → brick → brown",
        "isDiverging": False,
        "isDefault": False,
        "colors": ["#4E7A63", "#B08A4A", "#A8703E", "#A85D4A", "#8A4438", "#6E3530"],
    },
]

# =========================================================================
# DISTRIBUTED COORDINATION (new in 6.1 — Global Task Framework)
# =========================================================================
# Unified Redis backend for locks and pub/sub between workers. The 6.1.0
# UPDATING.md recommends configuring this on every production installation that
# has Redis. It reuses the same Redis host/DB as the upstream CACHE_CONFIG
# (docker/pythonpath_dev/superset_config.py).
DISTRIBUTED_COORDINATION_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_KEY_PREFIX": "signal_",
    "CACHE_REDIS_URL": (
        f"redis://{os.getenv('REDIS_HOST', 'redis')}:{os.getenv('REDIS_PORT', '6379')}/"
        f"{os.getenv('REDIS_RESULTS_DB', '1')}"
    ),
    "CACHE_DEFAULT_TIMEOUT": 300,
}

# =========================================================================
# LOGGING
# =========================================================================

# Raise the log level if you need to debug
# import logging
# LOG_LEVEL = logging.DEBUG
