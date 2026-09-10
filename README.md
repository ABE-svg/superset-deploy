# Apache Superset — Production Deployment on OVHcloud

A production-ready Apache Superset 6.1.0 deployment, designed to be installed
through web interfaces rather than a terminal. You will use the OVHcloud control
panel and the Dokploy dashboard. Exactly one step requires a command line, and
it is clearly marked.

The metadata database is **OVHcloud Managed PostgreSQL**, an external service.
There is no database container to operate, patch or back up yourself.

---

## 1. Architecture

```
                        GitHub (this repository)
                                  │
                                  │  Dokploy pulls on deploy
                                  ▼
      ┌──────────────────────────────────────────────────────┐
      │        OVHcloud Public Cloud instance (Ubuntu)        │
      │                                                       │
      │   Traefik  ── TLS termination, Let's Encrypt          │
      │      │        (installed and managed by Dokploy)      │
      │      ▼                                                │
      │   superset  ── Gunicorn, port 8088, not published     │
      │      │                                                │
      │      ├── superset-worker  ── Celery, async tasks      │
      │      ├── superset-beat    ── Celery scheduler         │
      │      └── redis            ── cache + broker           │
      │                                                       │
      │   internal Docker network, nothing published          │
      └───────────────────────────┬───────────────────────────┘
                                  │  vRack private network
                                  ▼
                OVHcloud Managed PostgreSQL (metadata)
```

**What each component does.**

| Component | Role | Where it runs |
| --- | --- | --- |
| Traefik | Receives HTTPS traffic, obtains and renews the certificate, forwards to Superset | Installed by Dokploy |
| Superset | The web application itself | Container, port 8088, never published |
| Celery worker | Async SQL Lab queries, dashboard thumbnails, cache warm-up | Container |
| Celery beat | Triggers scheduled tasks; exactly one instance | Container |
| Redis | Query result cache, dashboard filter state, Celery broker | Container, internal network only |
| PostgreSQL | Dashboards, charts, users, permissions | OVHcloud managed service |

Only Traefik is reachable from the internet. Superset, Redis and the workers sit
on an internal Docker network with no published ports.

---

## 2. Prerequisites

| You need | Notes |
| --- | --- |
| An OVHcloud account | With a payment method registered |
| A Public Cloud project | Created from the OVHcloud control panel |
| A domain name | This guide uses `superset.example.com` |
| A GitHub account | To fork or host this repository |

### Choosing the instance size

These are practical recommendations, not official Superset requirements.
Consumption depends on how many people use it at once, how heavy the dashboards
are, and how many Celery tasks run.

| Profile | vCPU | RAM | Disk | Suitable for |
| --- | --- | --- | --- | --- |
| Minimum | 2 | 4 GB | 40 GB | A handful of users, light dashboards. Dokploy itself needs 2 GB, so this is tight. |
| **Recommended** | **2** | **8 GB** | **80 GB** | **Up to ~30 concurrent sessions. The default values in `.env.example` are sized for this.** |
| Comfortable | 4 | 16 GB | 160 GB | Heavy SQL Lab use, large dashboards, many scheduled tasks |

Dokploy's own documented minimum is 2 GB RAM and 30 GB disk, before Superset.
The disk fills with Docker images and build layers, so do not undersize it.

---

## 3. What this repository already does for you

You do not need to write any Docker or Superset configuration. Already prepared:

- **Pinned Superset 6.1.0.** Never `latest`, so an image pull cannot trigger an
  unrequested database migration.
- **Production web server.** Gunicorn with an explicit worker count, not Flask's
  development server.
- **External database wiring.** The connection URI is built from your variables,
  with TLS enforced and passwords URL-encoded.
- **Redis caching**, including the dashboard filter state cache that most
  deployments forget and that breaks filters when running more than one worker.
- **Reverse proxy support.** `ENABLE_PROXY_FIX` is set, so Superset generates
  `https://` URLs instead of falling into a login redirect loop.
- **Security defaults.** Secure, HTTP-only, SameSite cookies. CSRF enabled.
  Containers run as an unprivileged user. Nothing but the web service is on the
  proxy network.
- **Healthchecks** on Superset, Redis and the Celery worker.
- **Automatic initialisation.** Migrations, roles and the first admin account
  are created on the first deploy.
- **Memory limits** on every service, so one runaway query cannot take the host
  down.

---

## 4. What you have to do

```
[ ] 1. Create the OVHcloud instance
[ ] 2. Install Dokploy                  ← the only terminal step
[ ] 3. Create the Managed PostgreSQL service
[ ] 4. Create the database and note the credentials
[ ] 5. Attach both to the private network and authorise access
[ ] 6. Point your domain at the instance
[ ] 7. Connect GitHub to Dokploy
[ ] 8. Create the Compose application
[ ] 9. Enter the environment variables
[ ] 10. Add the domain and enable HTTPS
[ ] 11. Deploy
[ ] 12. Log in and verify
```

---

## Step 1 — Create the instance (OVHcloud)

**Go to:** [ovh.com/manager](https://www.ovh.com/manager) → **Public Cloud** →
select your project → **Instances** → **Create an instance**

| Field | Value |
| --- | --- |
| Region | Pick one close to you, for example Gravelines (GRA) |
| Image | **Ubuntu 24.04** |
| Model | **B3-8** (2 vCPU, 8 GB) — the recommended size |
| SSH key | Add your public key. You cannot connect without it. |
| Public network | Enabled, with a public IPv4 |
| Private network | Enabled, on the vRack you will also attach the database to |

**Do not** install any pre-configured application. Dokploy installs what it needs.

When it is ready, note two addresses from the instance list:

- the **public IPv4**, for DNS and for reaching the Dokploy panel
- the **private IP** on the vRack, which the database will authorise

### Open the required ports

Three ports must be reachable from the internet, or the next steps fail in ways
that look like something else:

| Port | Needed for | Symptom if closed |
| --- | --- | --- |
| 22 | SSH, for the single install step | You cannot connect at all |
| 80 | Let's Encrypt validation | The certificate is never issued |
| 443 | HTTPS traffic | The site is unreachable |
| 3000 | The Dokploy panel | You cannot open the dashboard |

Port 80 is required **even though the site is HTTPS-only**, because the ACME
challenge that proves you own the domain arrives over plain HTTP.

OVHcloud Public Cloud instances do not apply a restrictive firewall by default,
so usually there is nothing to do. Check under **Public Cloud** → your instance →
**Security groups** if one is attached. If you have enabled `ufw` on the instance
yourself, allow those four ports.

> **Port 3000 exposes the Dokploy panel to the internet.** Give it a strong
> password immediately in the next step. Once your domain works, you can attach a
> domain to Dokploy itself and close 3000 to the public.

---

## Step 2 — Install Dokploy

> ### ⚠️ The only step that requires a terminal
>
> Dokploy is the tool that gives you a web interface for everything else. It
> cannot install itself through a web interface, so this one command is
> unavoidable. Everything after this point is done by clicking.

Connect to the instance over SSH and run:

```bash
curl -sSL https://dokploy.com/install.sh | sh
```

The script installs Docker and Traefik if they are not already present. It fails
if ports 80, 443 or 3000 are already in use.

### Claim the administrator account NOW

> ### ⚠️ Do this within a minute of the install finishing
>
> Port 3000 is open to the entire internet, and Dokploy hands the administrator
> account to **whoever reaches `/register` first**. That is not a bug; it is how
> first-run setup works. Until you claim it, your server is unowned.

As soon as the script finishes, open:

```
http://YOUR_PUBLIC_IPv4:3000
```

You will land on the registration form. Fill in an e-mail and a strong password
and submit. **Do not go and read the rest of this guide first.**

This account is Dokploy's own, and it has nothing to do with the Superset admin
account created later in step 11. They are two different logins on two different
applications.

### If you see "Admin is already created" or "Invalid email or password"

An administrator account already exists on that Dokploy instance. Registration is
a one-time event: once claimed, `/register` redirects to `/` and only the login
form remains.

There are two possibilities, and only one of them is safe.

**You created it yourself and mistyped the password.** Sign in at the root URL,
not `/register`:

```
http://YOUR_PUBLIC_IPv4:3000/
```

If you cannot remember the password, Dokploy documents a reset procedure at
[docs.dokploy.com/docs/core/reset-password](https://docs.dokploy.com/docs/core/reset-password),
which requires SSH access to the server.

**You never created it.** Then somebody else claimed your server. Do not try to
recover the account and do not continue on that instance: you have no way of
knowing what was changed while it was under someone else's control.

Since nothing of value is installed yet, the fastest and safest fix is to start
over:

1. In **Public Cloud** → **Instances**, delete the instance.
2. Create a new one, following step 1 again.
3. Re-run the install script.
4. **Claim the account immediately**, before doing anything else.

Rebuilding takes about twenty minutes. Recovering an instance whose admin account
you do not control is never worth the doubt.

### Reducing the exposure afterwards

Once your domain works, you can attach a domain to Dokploy itself under
**Settings** → **Web Server** and then close port 3000 to the public, so the
panel is no longer reachable by IP.

---

## Step 3 — Create the Managed PostgreSQL service (OVHcloud)

**Go to:** **Public Cloud** → your project → **Databases** → **Create a database
service**

| Field | Value |
| --- | --- |
| Engine | **PostgreSQL**, version **16** |
| Plan | **Essential** is enough for this workload |
| Region | **The same region as your instance** |
| Nodes | 1 |
| Network | **Private network (vRack)** — the same one as the instance |

Creation takes roughly fifteen minutes.

> Choosing a different region from the instance sends your database traffic
> across the public internet and adds latency to every query.

---

## Step 4 — Create the database and the user (OVHcloud)

Open the service once it is active.

**Tab "Users":** OVHcloud has already created an administrator user called
`avnadmin`. Use the three-dot menu → **Reset password**, and copy the password
immediately. It is displayed once and never shown again.

> **Use `avnadmin` rather than creating your own user.** Since PostgreSQL 15, a
> non-owner user cannot create tables in the `public` schema. A freshly created
> user would make `superset db upgrade` fail with a permission error that is
> tedious to diagnose. You can tighten this later, once everything works.

**Tab "Databases":** click **Add a database** and name it `superset`. Do not
reuse `defaultdb`.

**Tab "General information":** note the **hostname** and the **port**.

> The port is **not** 5432. OVHcloud assigns a non-standard port, usually in the
> 20000 range. Copy the exact value.

Use the **private (vRack) endpoint** hostname, not the public one.

---

## Step 5 — Authorise network access (OVHcloud)

**Tab "Authorised IPs":** the database refuses every connection from an address
that is not listed here, *before* checking the password. A missing entry looks
exactly like a wrong password.

Add the instance's **private vRack IP**, as a `/32`, for example
`10.0.0.5/32`. Alternatively add the vRack subnet if you prefer.

Do not add `0.0.0.0/0`. That would expose your database to the entire internet.

---

## Step 6 — Point your domain at the instance (OVHcloud)

**Go to:** **Web Cloud** → **Domain names** → your domain → **DNS zone** →
**Add an entry**

| Field | Value |
| --- | --- |
| Type | **A** |
| Subdomain | `superset` |
| Target | your instance's **public IPv4** |
| TTL | Default |

This creates `superset.example.com`.

**Verify propagation before continuing.** Let's Encrypt validates your domain by
connecting to it; if DNS has not propagated, certificate issuance fails and
repeated failures hit rate limits.

Check with an online tool such as [dnschecker.org](https://dnschecker.org), or
from any terminal:

```bash
dig +short superset.example.com
```

It must return your instance's public IPv4. Propagation usually takes minutes,
occasionally hours. **Do not proceed until it does.**

---

## Step 7 — Connect GitHub to Dokploy

Push this repository to your own GitHub account first.

**In Dokploy:** **Settings** → **Git** → **GitHub** → **Connect**

Authorise the Dokploy GitHub App and grant it access to the repository. This is
what lets Dokploy pull your code and, optionally, redeploy automatically when you
push.

---

## Step 8 — Create the application

**In Dokploy:** **Projects** → **Create project** → name it `superset` →
**Create service** → **Compose**

| Field | Value |
| --- | --- |
| Provider | **GitHub** |
| Repository | your fork of this repository |
| Branch | `main` |
| Compose Path | `./docker-compose.yml` |
| Compose Type | **Docker Compose** |

> **Choose "Docker Compose", not "Docker Stack".** Stack mode runs Docker Swarm,
> which does not support the `build` directive this repository relies on.

### Why Compose from GitHub, and not a prebuilt image

**This is the recommended option, and here is why.**

The stack is four coordinated containers — web, Celery worker, Celery beat and
Redis — that must share a network, a volume and one set of environment
variables. Compose describes all of that in a single reviewed file. Publishing a
prebuilt image to a registry would add a build pipeline, a registry account and
credentials to manage, and would still leave you needing this same Compose file
to run the four services.

The image itself is built on the server from a deliberately thin `Dockerfile`:
the official `apache/superset:6.1.0` image plus one configuration file. Superset
is not rebuilt from source, so the build takes seconds.

**When you would use a prebuilt image instead:** if you deploy the same stack to
several servers and want them to run a byte-identical image, or if your instance
is too small to build. Neither applies to a single instance of this size.

---

## Step 9 — Enter the environment variables

**In Dokploy:** open your application → **Environment** tab.

Paste the variables there. Dokploy writes them to a `.env` file on the server,
which the Compose file reads via `env_file`.

> Dokploy does **not** inject interface variables into containers automatically.
> This repository's Compose file declares `env_file: .env` on every service
> precisely so that it does.

Start from [`.env.example`](.env.example), which documents every variable. The
minimum you must provide:

```env
SUPERSET_SECRET_KEY=<paste a generated key>
POSTGRES_HOST=<private vRack hostname from step 4>
POSTGRES_PORT=<the non-5432 port from step 4>
POSTGRES_DB=superset
POSTGRES_USER=avnadmin
POSTGRES_PASSWORD=<the password from step 4>
ADMIN_EMAIL=admin@superset-minard-test.fr
ADMIN_PASSWORD=<choose a strong password>
```

**Generating the secret key.** Run this anywhere, including your own laptop:

```bash
openssl rand -hex 32
```

> **Choose the secret key once, before the first deploy.** It encrypts the stored
> passwords of every database connection you later create inside Superset.
> Changing it afterwards makes them undecryptable and forces you to run
> `superset re-encrypt-secrets`.

---

## Step 10 — Add the domain and enable HTTPS

> ### ⚠️ Deploy once first, or you will see "service not found"
>
> Dokploy only learns the service names inside `docker-compose.yml` (`superset`,
> `redis`, and so on) once it has actually deployed the stack. Adding a domain
> before that first deploy fails, because there is nothing yet to attach it to.
>
> **Do this instead:** jump to [Step 11](#step-11--deploy) now, click **Deploy**,
> and wait for it to finish — Superset will come up reachable only inside
> Dokploy's network, with no domain and no HTTPS yet, which is safe. Then come
> back here to attach the domain. The deploy in Step 11 is safe to run again
> afterwards, once the domain is in place.

**In Dokploy:** your application → **Domains** tab → **Add Domain**

| Field | Value |
| --- | --- |
| Host | `superset.example.com` |
| Path | `/` |
| Container Port | **8088** |
| HTTPS | **Enabled** |
| Certificate | **Let's Encrypt** |
| Service Name | `superset` |

Dokploy generates the Traefik routing labels for you at deploy time. You never
write them by hand.

> Pick the service named **`superset`**. The worker, beat and Redis services must
> never be exposed.

Certificates renew automatically. Traefik requests a new one well before the
90-day expiry, with no action from you.

---

## Step 11 — Deploy

Click **Deploy**.

Watch the **Logs** tab. The order to expect:

1. Docker builds the image, a few seconds
2. `redis` starts and becomes healthy
3. `superset-init` runs the migrations — **this is the long step**, one to three
   minutes on an empty database. It prints `Initialisation complete`.
4. `superset`, `superset-worker` and `superset-worker-beat` start
5. The Superset healthcheck turns green

The first deploy is the slow one. Later deploys skip most of this.

---

## Step 12 — Log in and verify

Open `https://superset.example.com`.

Log in with the username `admin` and the `ADMIN_PASSWORD` you set. **Change that
password immediately**, from the user menu → **Info** → **Reset my password**.

### Verification checklist

| What | How |
| --- | --- |
| **HTTPS** | The padlock is present. Click it: the certificate is issued by Let's Encrypt and valid. |
| **No redirect loop** | You reach the dashboard list after login rather than returning to the login page. This is what `ENABLE_PROXY_FIX` prevents. |
| **PostgreSQL is in use** | Create a dashboard, then in Dokploy click **Redeploy**. If the dashboard is still there, your data is in the managed database and not in a container. |
| **Redis** | Dokploy → your app → the `redis` service shows *healthy*. |
| **Celery** | The `superset-worker` service shows *healthy*. |
| **Services** | All show *running* except `superset-init`, which correctly shows *exited (0)*. |

---

## 🔐 Secrets — important

**Never commit a `.env` file.** It is in `.gitignore`. Only `.env.example`, which
contains placeholders, belongs in Git.

**Never put a password in `docker-compose.yml`.** That file is committed. Every
credential reaches the containers through Dokploy's environment variables.

**Use different secrets per environment.** A test instance and a production
instance must not share a secret key or a database password.

**Before your first push**, confirm nothing sensitive is staged:

```bash
git status
git ls-files | grep -E '\.env$|\.pem$|\.key$'
```

The second command must print nothing.

If you ever commit a secret by accident, treat it as compromised: rotate it in
the OVHcloud panel and in Dokploy. Removing the file in a later commit does not
remove it from the repository history.

---

## 🔄 Updating

### Updating your configuration

```
edit → commit → push → Dokploy → Redeploy
```

You can enable **Auto Deploy** in the application settings so that every push to
`main` redeploys automatically. Convenient, but it means a mistaken push reaches
production immediately. For a production instance, deploying manually is the
safer habit.

### Updating Superset itself

1. **Take a backup first.** See below. A schema migration has no reverse.
2. Read the release's `UPDATING.md` in the
   [Superset repository](https://github.com/apache/superset/blob/master/UPDATING.md).
3. Change `SUPERSET_VERSION` in the Dokploy **Environment** tab.
4. Click **Deploy**. `superset-init` runs the migration automatically.

### Rolling back

Dokploy keeps previous deployments; redeploy an earlier one from the
**Deployments** tab. **This is not enough on its own after a version upgrade**:
the database schema has already been migrated forward and the older Superset
will not understand it. A rollback across versions also requires restoring the
database dump you took beforehand.

---

## Backups and restore

**What OVHcloud does for you.** The managed PostgreSQL service is backed up
automatically, with point-in-time restore from the control panel. This covers
your dashboards, charts, users and permissions — everything that matters.

**What is not backed up.**

| Item | Status |
| --- | --- |
| Dashboards, charts, users, permissions | Backed up by OVHcloud |
| `superset_home` volume (uploads, runtime files) | **Not backed up.** Lost if the instance is destroyed. |
| Redis cache | Not backed up, and does not need to be. Rebuilds itself. |
| Environment variables and secrets | **Not backed up.** Keep them in a password manager. |

> A Docker volume is not a backup. It lives on the same machine as the thing it
> would protect against losing.

**Before a version upgrade**, take a portable dump. This is the one case
OVHcloud's automatic backups do not cover well, because their schedule is not
synchronised with your upgrade:

```bash
./scripts/backup-db.sh
```

It writes a timestamped `.dump` file to `./backups/`. **Copy it off the server.**
Restoring is destructive and deliberately not automated; the command is
documented at the top of the script.

---

## ✅ Final security checklist

```
[ ] HTTPS active, padlock shown in the browser
[ ] Certificate valid and issued by Let's Encrypt
[ ] Database reachable only from the private vRack IP, never 0.0.0.0/0
[ ] Redis not published on any host port
[ ] Superset port 8088 not published, reachable only through Traefik
[ ] SUPERSET_SECRET_KEY randomly generated, never the example value
[ ] Strong PostgreSQL password, taken from the OVHcloud panel
[ ] Default admin password changed after first login
[ ] No secret committed: `git ls-files | grep -E '\.env$'` prints nothing
[ ] Dokploy panel protected by a strong password
[ ] OVHcloud account protected by two-factor authentication
[ ] Superset version pinned, no `latest` anywhere
[ ] A database dump taken before the last version upgrade
```

---

## Versions

| Component | Version | Why |
| --- | --- | --- |
| Apache Superset | `6.1.0` | Pinned. On 2026-08-31 the `latest` tag moved from 6.0.0 to 6.1.0 unannounced; anyone tracking it would have run an unrequested database migration. |
| PostgreSQL | `16` | OVHcloud managed. `scripts/backup-db.sh` uses a matching `pg_dump`. |
| Redis | `7.4-alpine` | Pinned. Alpine keeps the image small. |
| Python | Provided by the Superset image | Not chosen independently, to avoid dependency mismatches. |
| Traefik | Provided by Dokploy | Managed for you, including certificates. |

Changing the Superset version means changing `SUPERSET_VERSION`. The Dockerfile
takes it as a build argument, so image and configuration never drift apart.

---

## Repository layout

| Path | Purpose |
| --- | --- |
| `docker-compose.yml` | The production stack. This is what Dokploy runs. |
| `Dockerfile` | Official Superset image plus the configuration file. |
| `config/superset_config.py` | All Superset production settings. |
| `.env.example` | Every variable, documented, with placeholders. |
| `scripts/backup-db.sh` | Optional pre-upgrade database dump. |
| `CLAUDE.md` | Architecture notes and the reasoning behind the design choices. |

---

## Troubleshooting

### `superset-init` fails, or the database connection is refused

Almost always one of four things, in order of likelihood:

1. **The port is wrong.** OVHcloud does not use 5432. Check `POSTGRES_PORT`
   against the control panel.
2. **The IP is not authorised.** The instance's private vRack IP must be in the
   database's authorised IPs. This is refused before authentication, so it looks
   like a wrong password.
3. **The wrong endpoint.** Use the private vRack hostname, not the public one.
4. **The password is wrong.** Reset it in the panel and update it in Dokploy.

### You log in and land back on the login page

A redirect loop, caused by the proxy header configuration. `ENABLE_PROXY_FIX` is
already set in `config/superset_config.py`, so check instead that the Dokploy
domain has **HTTPS enabled** and that **Container Port** is `8088`.

### The certificate is not issued

Check DNS first: `dig +short superset.example.com` must return your public IPv4.
Let's Encrypt cannot validate a domain that does not resolve.

Also confirm ports 80 and 443 are open on the instance. Port 80 is required even
for an HTTPS-only site, because the ACME challenge uses it.

**Beware of rate limits.** Let's Encrypt allows five failed attempts per hostname
per hour. If you hit that, fix the cause and wait; retrying makes it worse.

### The worker restarts in a loop

Look at the `superset-worker` logs in Dokploy. Usually it started before the
migrations finished. The Compose file already gates it on `superset-init`
completing successfully, so if this persists the real cause is in the init logs.

### Dashboard filters reset at random

This is the symptom of an unconfigured filter state cache with several Gunicorn
workers. Already fixed here by `FILTER_STATE_CACHE_CONFIG` on Redis. If you see
it, check that the `redis` service is healthy.

### Out of memory, containers being killed

Lower `SUPERSET_MEMORY_LIMIT` and `WORKER_MEMORY_LIMIT`, or move to a larger
instance. Confirm the totals leave room for the operating system, Docker and
Dokploy, which need roughly 2 GB between them.

---

## Testing locally before deploying

Optional, and it does require a terminal. Useful for checking your configuration
against a throwaway database rather than the managed one.

```bash
cp .env.example .env
# Edit .env: point POSTGRES_* at any test PostgreSQL,
# and set SESSION_COOKIE_SECURE=false since there is no HTTPS locally.

docker network create dokploy-network   # normally created by Dokploy
docker compose up -d
```

Superset is not published on a host port by design, so to reach it locally add
`ports: ["8088:8088"]` to the `superset` service temporarily. **Never commit
that change.**

---

## Licence

Files derived from Apache Superset keep their original Apache 2.0 licence.
