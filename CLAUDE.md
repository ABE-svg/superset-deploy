# CLAUDE.md — architecture and design decisions

Context for future sessions working on this repository. The README is the user
guide; this file records *why* the repository looks the way it does.

## What this is

A production deployment of Apache Superset 6.1.0 on a single OVHcloud Public
Cloud instance, managed through Dokploy, with the metadata database on OVHcloud
Managed PostgreSQL.

Origin: a fork of `guica/superset-deploy`, a hardened Docker Compose deployment
written in Brazilian Portuguese for its author's own company. Almost nothing of
the original structure survives, but several of its hard-won lessons do, and
they are preserved as comments in the files they apply to.

## Target architecture

```
Internet → Traefik (Dokploy, TLS) → superset:8088
                                       ├── superset-worker (Celery)
                                       ├── superset-worker-beat
                                       └── redis (internal only)
                                              ↓ vRack
                            OVHcloud Managed PostgreSQL
```

| Item | Value |
| --- | --- |
| Host | One OVHcloud Public Cloud instance, Ubuntu 24.04 (public IPv4 kept out of this repository) |
| Orchestration | Docker Compose via Dokploy. No Kubernetes, no Swarm. |
| Public URL | `https://superset.superset-minard-test.fr` |
| TLS | Let's Encrypt, obtained and renewed by Dokploy's Traefik |
| Metadata DB | OVHcloud Managed PostgreSQL 16, reached over the vRack private network |
| Cache / broker | Redis container, internal network only |
| Scale target | Under 1000 registered users, roughly 30 concurrent sessions |
| Instance sizing | 2 vCPU / 8 GB assumed by the defaults in `.env.example` |

## Decisions and their reasons

**Dokploy instead of nginx + certbot.** Dokploy ships Traefik and handles
Let's Encrypt through its interface. Keeping the original nginx and certbot would
have put a second reverse proxy behind the first, doubling the places a header
can be lost for no benefit. All nginx and certbot files were deleted.

**A thin Dockerfile instead of bind mounts.** Dokploy's documentation warns
against bind-mounting repository files, because it runs `git clone` into the
project directory on every deployment. The original repository mounted `./docker`
over `/app/docker`, which also meant it had to vendor upstream's bootstrap
scripts to work at all. Baking the config into the image removed both problems:
the image's own `/app/docker` is used, and the running container cannot disagree
with the commit it was built from.

**`app-gunicorn`, not `app`.** The `app` branch of the image's bootstrap script
runs `flask run --reload --debugger`, the single-threaded development server with
the Werkzeug debugger exposed. The original fork used it in production.

**`POSTGRES_*` variable names.** Upstream Superset uses `DATABASE_*`, but this
repository ships its own config file, so the names are ours to choose and these
are the conventional ones.

**The database URI is assembled in the config file.** Upstream builds it as a
bare f-string with no hook for query parameters, so `sslmode` cannot be passed
through the `DATABASE_*` variables. It also does not URL-encode, and OVHcloud
generates passwords containing `@ : / ? #`, which silently corrupt a raw URI.
Both are fixed in `config/superset_config.py`, with `quote_plus` and an explicit
`sslmode`.

**`POSTGRES_PORT` has no default.** OVHcloud assigns a non-standard port, usually
in the 20000 range. A default of 5432 would turn a missing variable into a
connection timeout that looks like a firewall problem.

**Filter state and explore form data caches are Redis-backed.** Upstream defines
only `CACHE_CONFIG`, `DATA_CACHE_CONFIG` and `THUMBNAIL_CACHE_CONFIG`. The other
two fall back to per-process storage, so with more than one Gunicorn worker a
filter set on one worker is invisible to another and dashboards appear to reset
filters at random. This is a real bug at any worker count above one.

**`ENABLE_PROXY_FIX = True`.** Absent from both the original fork and upstream's
own Docker config. Without it Superset emits `http://` URLs behind the proxy and
login enters a redirect loop with no error message.

**Alerts and Reports are off.** The user has no SMTP server. The feature is
driven by a single flag so its absence never blocks a deploy. Enabling it later
needs a delivery channel and a headless-browser worker image; the original
fork's `docker-browser/` Dockerfile, which solved the Chromium problem well, was
deleted but is recoverable from git history if ever needed.

**Version pins.** The original author documented that Docker Hub's `latest` tag
moved from Superset 6.0.0 to 6.1.0 on 2026-08-31 without announcement, which
would have run a database migration nobody asked for. That reasoning is
preserved. Superset, Redis and the `pg_dump` image are all pinned.

## Traps worth remembering

- **Dokploy does not inject its UI environment variables into containers.** It
  writes a `.env` file; the Compose file must declare `env_file: .env`. Every
  service here does.
- **Services must join the external `dokploy-network`** or Traefik cannot route
  to them. Only the `superset` service does; everything else is internal.
- **Compose interpolates `${VAR}` from the shell or a project-root `.env` only.**
  It does not read arbitrary env files for interpolation. The original fork's
  README told users to change the image version in `docker/.env-local`, which had
  no effect whatsoever.
- **`superset fab create-admin` exits non-zero when the user exists**, which is
  the normal case on every redeploy. The init command tolerates it with `|| true`.
- **`GUNICORN_TIMEOUT` must exceed `SUPERSET_WEBSERVER_TIMEOUT`**, or Gunicorn
  kills the worker before Superset can return a useful error.
- **nginx resolves all upstreams when parsing its config.** Not relevant now that
  nginx is gone, but it is why the original repository had a careful reload
  script: a stopped upstream made a reload fail silently while the old
  certificate kept being served.

## Constraints from the user

- Everything in the repository is in **English**. Conversation may be in French.
- No secrets in git, ever. Real values live in Dokploy; committed files carry
  placeholders only.
- Never invent credentials, hostnames, ports or IPs. Use an obvious placeholder
  and ask.
- Prefer web interfaces over the command line in documentation. Exactly one
  terminal step is acceptable: installing Dokploy.
- Do not commit; the user commits and pushes.

## Still to be supplied by the user

`POSTGRES_HOST` (private vRack endpoint), `POSTGRES_PORT`, `POSTGRES_PASSWORD`,
`SUPERSET_SECRET_KEY` and `ADMIN_PASSWORD`. All are entered in Dokploy, never in
the repository.
