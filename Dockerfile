# syntax=docker/dockerfile:1
#
# Apache Superset, production image.
#
# Deliberately thin: the official image plus our configuration file, nothing
# else. We do NOT rebuild Superset, and we do NOT override /app/docker, so the
# image's own entrypoint scripts stay intact and a version upgrade is a one-line
# change to the tag below.
#
# Why a Dockerfile at all rather than bind-mounting the config?
# Dokploy runs `git clone` into the project directory on every deployment, and
# its documentation warns against bind-mounting repository files for that
# reason. Baking the config into the image is both safer and reproducible: the
# running container can never disagree with the commit it was built from.
#
# Superset picks the file up automatically because the official image already
# sets PYTHONPATH=/app/pythonpath, and Superset imports `superset_config` from
# the Python path at startup.

# PINNED, never `latest`. On 2026-08-31 the Docker Hub `latest` tag moved from
# 6.0.0 to 6.1.0 with no announcement; a routine image pull would have run a
# database migration nobody asked for. Upgrading is an explicit edit here.
ARG SUPERSET_VERSION=6.1.0
FROM apache/superset:${SUPERSET_VERSION}

# Root only for the two steps below, then straight back to the unprivileged user
# the base image defines (uid 1000, `superset`).
USER root

# PostgreSQL driver. The official image does NOT ship it: upstream installs it at
# container start, inside docker-bootstrap.sh, but only when the container runs
# as root. This deployment runs as the unprivileged `superset` user, so that
# branch never fires and Superset dies with "ModuleNotFoundError: No module
# named 'psycopg2'" the moment it tries to reach the metadata database.
#
# Installing it here is also better than upstream's approach regardless of the
# user: baking it into the image means no network call and no package
# installation on every single container start.
#
# `pip` on PATH is the SYSTEM python, but Superset runs from the /app/.venv
# virtualenv, so the interpreter must be named explicitly or the package lands
# where nothing will import it.
ARG PSYCOPG2_VERSION=2.9.12
RUN uv pip install --python /app/.venv/bin/python --no-cache \
        "psycopg2-binary==${PSYCOPG2_VERSION}" \
    && /app/.venv/bin/python -c "import psycopg2; print('psycopg2', psycopg2.__version__)"

COPY --chown=superset:superset config/superset_config.py /app/pythonpath/superset_config.py

# Fail the BUILD, not the 3am deploy, if the config has a syntax error.
# It is only compiled, not executed, so no environment variables are needed.
RUN /app/.venv/bin/python -m py_compile /app/pythonpath/superset_config.py \
    && rm -rf /app/pythonpath/__pycache__

USER superset
