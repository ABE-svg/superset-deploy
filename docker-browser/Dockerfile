# syntax=docker/dockerfile:1
#
# Superset image with a headless browser for Alerts & Reports (chart screenshots).
#
# The official `apache/superset` image is the "lean" flavour: it ships no browser
# at all. Without one, every Report that sends a screenshot dies with
#   "Failed taking a screenshot ... chromedriver unexpectedly exited. Status code was: 127"
# (127 = missing shared library — libglib/libnss/libxcb/libdbus).
#
# Here we use Playwright + Chromium, which has been the project's recommended
# approach since 4.1.x and is what the official Dockerfile itself does via
# --build-arg INCLUDE_CHROMIUM=true. Playwright downloads a self-contained
# Chromium and `install-deps` installs the system libraries that were missing.
#
# Paired with FEATURE_FLAGS["PLAYWRIGHT_REPORTS_AND_THUMBNAILS"] = True in
# docker/pythonpath_dev/superset_config_docker.py. With Playwright active,
# WEBDRIVER_TYPE no longer has any effect (Playwright is always Chromium).
#
# Build:
#   docker compose --profile browser build superset-worker
# or:
#   docker build --build-arg SUPERSET_VERSION=6.1.0 -t astecha/superset-browser:6.1.0 docker-browser/
#
# The version here must be the SAME as the TAG in docker-compose.yml / .env-local.
ARG SUPERSET_VERSION=6.1.0
FROM apache/superset:${SUPERSET_VERSION}

USER root

# Browsers outside $HOME: compose runs the services as root, but the base image
# has USER superset. A system-wide path works for both — otherwise Playwright
# would look in ~/.cache/ms-playwright belonging to the wrong user.
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright-browsers

# The `pip` on PATH is the system one (/usr/local/bin/pip), but Superset runs in
# the /app/.venv virtualenv. Installing with plain pip would put the package in
# the wrong interpreter and the import would only fail at runtime — hence the
# explicit --python.
# Pinned so the build is reproducible: Chromium is downloaded by the Playwright
# CLI, so the package version determines the browser version
# (1.62.0 -> Chromium 151.0.7922.34, validated in this image).
ARG PLAYWRIGHT_VERSION="1.62.0"
RUN set -eux; \
    uv pip install --python /app/.venv/bin/python --no-cache \
        "playwright${PLAYWRIGHT_VERSION:+==${PLAYWRIGHT_VERSION}}"; \
    playwright install-deps chromium; \
    playwright install chromium; \
    chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}"; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /root/.cache/*; \
    /app/.venv/bin/python -c "import playwright; print('playwright ok')"

USER superset
