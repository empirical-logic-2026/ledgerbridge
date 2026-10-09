# Docker in LedgerBridge: a guided tour

A learning guide to the Docker setup this project actually uses. It explains each file, part by part, and gives commands you can run to watch it work. It covers only the `test` environment: never run these commands with `-Env pilot`.

*Last updated: 2026-10-09 (M1, branch `feature/m1-tally-poc`).*

---

## 1. The five ideas you need

| Idea | What it means here |
| --- | --- |
| **Image** | A read-only template for a program and everything it needs, such as `mysql:8.4`. We download three images (MySQL, Redis and Qdrant) and build one ourselves (the data-plane API) from `data-plane/Dockerfile`. |
| **Container** | A running instance of an image, isolated from your PC. `ledgerbridge-test-mysql-1` is a container made from `mysql:8.4`. |
| **Volume** | Storage that outlives containers. Deleting the MySQL container doesn't delete your tables, because they live in the `mysql-data` volume. |
| **Port mapping** | Containers have their own network. Mapping `127.0.0.1:3307 → 3306` means "connections to port 3307 on my PC go to port 3306 inside the container". |
| **Compose** | One YAML file (`deploy/compose.yaml`) describing several containers that work together, started and stopped with one command. |

On Windows, Docker Desktop runs Linux containers inside a small Linux VM managed by **WSL 2**. That's why WSL had to be installed before Docker would start.

## 2. How the pieces fit together

```text
 Your Windows PC                                      Docker (Linux VM via WSL 2)
 ─────────────────                                    ──────────────────────────────────────────
                                                      network "ledgerbridge-test_default"
 pytest / alembic / CLI ── 127.0.0.1:3307 ──────────▶  mysql   :3306   ◀── volume mysql-data
 (run with uv on the host) 127.0.0.1:6380 ──────────▶  redis   :6379   ◀── volume redis-data
                           127.0.0.1:6333 ──────────▶  qdrant  :6333   ◀── volume qdrant-data
 browser / curl ────────── 127.0.0.1:8001 ──────────▶  api     :8000   (built from data-plane/)
                                                        │  talks to mysql / redis / qdrant by
                                                        │  service name, e.g. mysql:3306
 TallyPrime :9000  ◀──── host.docker.internal:9000 ─────┘
```

Two ways in:
- **From your PC** (tests, Alembic, the extraction CLI), you use `127.0.0.1` plus the *host* port from `.env.test`.
- **From inside a container** (the `api`), you use the *service name* plus the *container* port, for example `mysql:3306`. Compose provides a private network where service names work as hostnames.

Note that the API is `8001` on your PC but `8000` inside its container. The host port is just a door number on your PC: we moved it to 8001 because another local app already uses 8000, and nothing inside the container had to change.

## 3. `dev.ps1`: everyday commands

`dev.ps1` in the repo root is what you normally use. It's a thin layer over `deploy/stack.ps1` (next section), which does the actual Docker work.

| Command | Docker work it does |
| --- | --- |
| `./dev.ps1 up` | Checks the host ports in `.env.test` are free. Then runs `stack.ps1 up -d --build --wait`: **build** the API image, start all containers **d**etached (in the background), and **wait** until every healthcheck passes. Then `stack.ps1 exec -T api python -m alembic upgrade head` runs the database migrations *inside* the running API container. Finally it prints the dashboard, API health and API docs URLs. |
| `./dev.ps1 status` | `stack.ps1 ps` (containers, health, ports), plus a call to `/health/ready`. |
| `./dev.ps1 logs api` | `stack.ps1 logs -f --tail 200 api`: the last 200 lines, then **f**ollows new ones. |
| `./dev.ps1 tally-companies` | `stack.ps1 exec -T api python -m workers.cli entities ...`: runs our CLI inside the API container, which reaches TallyPrime on your PC through `host.docker.internal:9000`. |
| `./dev.ps1 extract -Company "..."` | The same pattern with `workers.cli extract`. |
| `./dev.ps1 seed-test-data` | No Docker at all: it runs on your PC with `.env.test`, because `devtools/` is deliberately not in the image (section 7). |
| `./dev.ps1 test` | Runs tests on your PC, not in Docker. It connects to the test containers through the host ports. Refuses `-Env pilot`. |
| `./dev.ps1 down` | `stack.ps1 down`: removes containers and the network, **keeps volumes**. |

Why run commands *inside* the container (`exec`) rather than on your PC? The container already has the selected environment's settings loaded through `env_file:`. Tools on your PC always default to `.env.test`, which would be wrong for `-Env pilot`.

`exec -T` means "run a command in a container that's already running, without a terminal (TTY)". `-T` makes the output plain text, so scripts can capture it.

## 4. `deploy/stack.ps1`: the front door to Docker Compose

Use it directly when you need a Compose command `dev.ps1` doesn't wrap:

```powershell
./deploy/stack.ps1 -Env test up -d --build
```

The script:
1. **Picks the environment** (`test` by default). It refuses to run if `.env.test` is missing.
2. **Runs** `docker compose -p ledgerbridge-test --env-file .env.test -f deploy/compose.yaml <your args>`.
   - `-p ledgerbridge-test` is the **project name**. Every container, volume and network gets this prefix, so `test` and `pilot` can never share data (ADR-012).
   - `--env-file .env.test` supplies the values for `${...}` placeholders in `compose.yaml`.
3. **Sets `LEDGERBRIDGE_ENV_FILE`** to the same file, so the `api` container also receives those settings, then restores the old value.

Anything after `-Env test` goes straight to `docker compose`: `up -d`, `down`, `ps`, `logs api` and so on.

Two PowerShell details, both learned the hard way:
- **It's deliberately a *simple* script, with no `[Parameter()]` attributes.** Those attributes would add PowerShell's built-in switches such as `-Debug` and `-Verbose`, which would swallow Docker's `-d` and `-v` flags. As a simple script, everything after `-Env` arrives untouched in `$args`.
- **`docker compose` writes its progress messages to stderr**, the error stream, even when nothing is wrong. Windows PowerShell 5.1 can treat those lines as errors and stop the script. So the script lets Docker run and judges success by its **exit code** (0 means success).

## 5. Env files: `.env.test.example` → `.env.test`

`.env.test` is git-ignored. You make it by copying `.env.test.example` and filling in passwords. It does two separate jobs:

1. **Fills in `compose.yaml` placeholders.** For example, `${MYSQL_HOST_PORT:?set MYSQL_HOST_PORT}` becomes `3307`. The `:?message` part means: stop with this message if the value is missing. That's a safety net against starting with half a configuration.
2. **Becomes environment variables inside the `api` container** (through `env_file:`). The Python settings (`core/config.py`) read them.

Host-side values such as `MYSQL_HOST=127.0.0.1` and `MYSQL_PORT=3307` suit tools on your PC. Containers need different addresses, so `compose.yaml` overrides them (section 6.5).

| Variable | Used for |
| --- | --- |
| `MYSQL_ROOT_PASSWORD`, `MYSQL_APP_USER`, `MYSQL_APP_PASSWORD` | MySQL admin and application logins |
| `MYSQL_HOST_PORT`, `REDIS_HOST_PORT`, `QDRANT_HOST_PORT`, `API_HOST_PORT` | Which ports on your PC map into the containers. Test uses 3307, 6380, 6333 and 8001; pilot uses 3317, 6390, 6343 and 8010. |
| `MYSQL_HOST`/`MYSQL_PORT`, `REDIS_URL`, `QDRANT_URL`, `TALLY_URL` | Where host-side tools connect |
| `FRONTEND_ORIGIN` | The only browser address the API accepts calls from (CORS): `http://localhost:5175` for test. The dashboard dev server is pinned to the same port in `frontend/vite.config.ts`. |

**After editing `.env.test`, run `./dev.ps1 up` again.** A container reads its environment once, when it's created. Compose notices the changed settings and *recreates* the `api` container; you'll see `Recreate` in the output. A plain restart would keep the old values.

## 6. `deploy/compose.yaml`, part by part

### 6.1 `services:` lists the containers

There are five: `mysql`, `redis`, `qdrant`, `api` and `worker`. The `worker` only starts when you ask for its profile (section 6.7).

### 6.2 `mysql`

```yaml
image: mysql:8.4
```
Uses the official MySQL 8.4 image, an LTS release of MySQL 8, which is what the docs require.

```yaml
command:
  - --character-set-server=utf8mb4
  - --collation-server=utf8mb4_0900_ai_ci
```
Extra start-up options for the MySQL server, so every database defaults to full Unicode (`utf8mb4`), matching `docs/schema.md` Section 1.

```yaml
environment:
  MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:?...}
  MYSQL_USER: ${MYSQL_APP_USER:?...}
  MYSQL_PASSWORD: ${MYSQL_APP_PASSWORD:?...}
```
The MySQL image reads these **on first start only** to set the root password and create our application user (`app_rw`).

```yaml
ports:
  - "127.0.0.1:${MYSQL_HOST_PORT}:3306"
```
Publishes MySQL on your PC at `127.0.0.1:3307` (test). Binding to `127.0.0.1` means only your own machine can connect, not other devices on your network.

```yaml
volumes:
  - mysql-data:/var/lib/mysql
  - ./mysql/init:/docker-entrypoint-initdb.d:ro
```
- **`mysql-data`** is a *named volume*. MySQL keeps its data files in `/var/lib/mysql`, so they survive restarts and `down`.
- **`./mysql/init`** is a *bind mount*: a folder from the repo shown inside the container, read-only (`:ro`). On the very first start, with an empty volume, the MySQL image runs every script in `/docker-entrypoint-initdb.d`. Ours is `01-schemas.sh` (section 8).

```yaml
healthcheck:
  test: ["CMD-SHELL", "mysqladmin ping -h 127.0.0.1 -uroot -p\"$$MYSQL_ROOT_PASSWORD\" --silent"]
```
Docker runs this check every 5 seconds inside the container. Once it passes, the container is **healthy**. `$$` is an escaped `$`, so the password is read from the container's own environment rather than written into the file. `start_period: 20s` gives MySQL time to initialise before failures count.

### 6.3 `redis`

```yaml
image: redis:7-alpine
```
Redis 7 on Alpine Linux, a very small image. Celery uses Redis as its job queue. Data lives in the `redis-data` volume, and the healthcheck runs `redis-cli ping` and expects `PONG`.

### 6.4 `qdrant`

```yaml
image: qdrant/qdrant:v1.15.4
```
The vector database for AI retrieval, used from M8. The version is pinned so everyone gets the same one. Its healthcheck uses a small bash trick to send an HTTP request to `/readyz`, because the image has no `curl`.

### 6.5 `api`: the container we build ourselves

```yaml
build:
  context: ../data-plane
```
There's no `image:` line. Instead, Compose **builds** an image from `data-plane/Dockerfile` (section 7). The *context* is the folder whose files the build may use.

```yaml
env_file: ${LEDGERBRIDGE_ENV_FILE:?run via deploy/stack.ps1}
```
Loads every variable from `.env.test` into the container. The path comes from `stack.ps1`. If you run plain `docker compose` without the script, this line stops you with a clear message.

```yaml
environment: &container-overrides
  MYSQL_HOST: mysql
  MYSQL_PORT: "3306"
  REDIS_URL: redis://redis:6379/0
  QDRANT_URL: http://qdrant:6333
  TALLY_URL: http://host.docker.internal:9000
```
- `environment:` wins over `env_file:`. These lines replace the host-side addresses with container-side ones, as described in section 2.
- `&container-overrides` is a YAML **anchor**, a label on this block. The `worker` reuses the same block with `*container-overrides`, so the two can't drift apart.

```yaml
ports:
  - "127.0.0.1:${API_HOST_PORT}:8000"
```
The API listens on 8000 inside the container, published on your PC at `127.0.0.1:${API_HOST_PORT}`, which is 8001 for test.

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```
Gives the container a hostname that points back to **your Windows PC**. That's how the API reaches TallyPrime on port 9000. Docker Desktop provides this name already; the line makes it work on Linux too.

```yaml
depends_on:
  mysql:
    condition: service_healthy
```
Don't start the API until MySQL, Redis and Qdrant pass their healthchecks.

### 6.6 `worker`

Built from the same Dockerfile as the API, but `command:` replaces the image's default and starts Celery (`celery -A workers.celery_app worker`) instead of the web server. It has no ports, because nothing connects *to* a worker; it pulls jobs from Redis.

### 6.7 `profiles: [workers]`

Services with a profile are skipped unless you ask for them. Nothing needs the worker yet, so it stays off by default:

```powershell
./deploy/stack.ps1 -Env test --profile workers up -d
```

### 6.8 Top-level `volumes:`

```yaml
volumes:
  mysql-data:
  redis-data:
  qdrant-data:
```
Declares the named volumes. Because of the project name, Docker actually creates `ledgerbridge-test_mysql-data` and so on, while pilot gets `ledgerbridge-pilot_mysql-data`. That's what keeps test and pilot data physically separate.

## 7. `data-plane/Dockerfile`, line by line

A Dockerfile is a recipe. Each instruction adds a **layer**, and Docker caches layers, so unchanged steps are skipped on rebuild.

| Line | What it does and why |
| --- | --- |
| `FROM python:3.12-slim` | Start from the official Python 3.12 image, slim variant (Debian with only the basics). This is the Python version the docs require. |
| `COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/` | Copy the `uv` tool out of its official image into ours. This is a *multi-stage copy*: we take two files without inheriting that image. It's pinned to 0.12, the uv that writes our `uv.lock`. |
| `ENV UV_COMPILE_BYTECODE=1` | Pre-compile Python files during install, for faster start-up. |
| `ENV UV_LINK_MODE=copy` | Copy packages instead of hard-linking, which avoids warnings inside Docker. |
| `ENV UV_PYTHON_DOWNLOADS=never` | Use the image's Python and never download another. |
| `ENV PATH="/app/.venv/bin:$PATH"` | Put the project's virtual environment first, so `uvicorn` and `celery` resolve to the installed versions. |
| `WORKDIR /app` | All later commands run in `/app`, which is created if needed. |
| `COPY pyproject.toml uv.lock .python-version ./` | Copy **only** the dependency files first… |
| `RUN uv sync --frozen --no-dev` | …and install dependencies. `--frozen` uses exactly what `uv.lock` says; `--no-dev` skips pytest and ruff. Because these two steps come before the code is copied, editing a `.py` file doesn't trigger a slow reinstall; Docker reuses the cached layer. |
| `COPY . .` | Now copy the application code. `.dockerignore` (below) controls what's excluded. |
| `RUN useradd --system --uid 10001 app && chown -R app /app` | Create an unprivileged user and give it the files. |
| `USER app` | Run everything after this as that user, not root, so a compromised app has fewer rights (SEC-008, least privilege). |
| `EXPOSE 8000` | Documents that the app listens on 8000. It doesn't publish anything by itself; `ports:` in Compose does that. |
| `CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]` | The default command: start the FastAPI app. `0.0.0.0` means "listen on all of the container's network interfaces", which is needed for port mapping to reach it. |

### `data-plane/.dockerignore`

These files are kept **out** of the build context, so they never get into the image:

```text
.venv/  __pycache__/  *.pyc  .pytest_cache/  .ruff_cache/   ← local junk, and Windows-built packages
tests/                                                      ← not needed at runtime
devtools/                                                   ← developer-only tools (ADR-014)
.env  .env.*                                                ← secrets never get baked into an image
```

`devtools/` holds the Tally seeding tool, the one piece of code allowed to *write* into Tally, and only into the test company. Leaving it out of the build context means it physically can't exist inside an image that might one day run at a client. Try `docker exec ledgerbridge-test-api-1 ls /app`: there's no `devtools` folder. `./dev.ps1 seed-test-data` therefore runs on your PC, not in a container.

## 8. `deploy/mysql/init/01-schemas.sh`

Runs **once**, when MySQL starts with an **empty** `mysql-data` volume:
- creates the four databases `raw`, `core`, `rpt` and `app` with the right character set (schema.md Section 2)
- gives `app_rw` full rights on them

In M2, proper per-role users (`migrator`, `report_ro`, `ai_ro`) replace these grants.

Things to know:
- **It won't run again** on an existing volume. To re-run it on **test only**, delete the volume with `./deploy/stack.ps1 -Env test down -v`. That erases the test database.
- The first line must be exactly `#!/bin/bash`.
- It must keep Linux line endings (LF). `.gitattributes` forces LF for `*.sh` so a Windows checkout can't break it.
- It uses the ordinary `mysql` client, logging in as root through the local socket, with the password passed in the `MYSQL_PWD` variable so it never appears on a command line. It doesn't use the image's `docker_process_sql` helper. That helper only exists when the image *sources* a script, and files bind-mounted from Windows look executable, so the image *runs* ours as a separate program instead. Our first version used the helper, and MySQL died with exit code 127 ("command not found").
- If it fails, MySQL stops and the container exits. `./deploy/stack.ps1 -Env test logs mysql` shows why.

## 9. Try it yourself (test environment)

Run these in PowerShell from the repo root. None of them print passwords.

```powershell
# The easy way
./dev.ps1 up                 # build, start, wait healthy, migrate, print URLs
./dev.ps1 status             # containers + API readiness
./dev.ps1 logs mysql         # follow one service's logs (Ctrl+C to stop)
./dev.ps1 tally-companies    # a command run inside the api container

# The same with plain Compose commands, through stack.ps1
./deploy/stack.ps1 -Env test up -d --build --wait
./deploy/stack.ps1 -Env test ps
./deploy/stack.ps1 -Env test logs --tail 50 mysql

# The API, through its published port (open /docs in a browser for the interactive API docs)
curl.exe http://127.0.0.1:8001/health
curl.exe http://127.0.0.1:8001/health/ready

# Look inside a container
docker exec ledgerbridge-test-redis-1 redis-cli ping
# SQL goes in through stdin: Windows PowerShell 5.1 mangles nested quotes in arguments.
# $MYSQL_USER and $MYSQL_PASSWORD are expanded inside the container, never on your screen.
"SHOW DATABASES;" | docker exec -i ledgerbridge-test-mysql-1 sh -c 'MYSQL_PWD=$MYSQL_PASSWORD mysql -u$MYSQL_USER -N'
"SELECT object_type, COUNT(*) FROM raw.raw_records GROUP BY object_type;" | docker exec -i ledgerbridge-test-mysql-1 sh -c 'MYSQL_PWD=$MYSQL_PASSWORD mysql -u$MYSQL_USER'
docker exec -it ledgerbridge-test-api-1 sh        # a shell inside the API container; `exit` to leave
docker exec ledgerbridge-test-api-1 whoami        # prints "app": not root

# Images, volumes and networks this project created
docker images
docker volume ls --filter name=ledgerbridge-test
docker network ls --filter name=ledgerbridge-test
docker inspect ledgerbridge-test-mysql-1 --format '{{json .State.Health.Status}}'

# The fully resolved compose file, after ${...} substitution. It includes the values
# from .env.test, passwords too, so only view it on your own screen; never paste or share it.
./deploy/stack.ps1 -Env test config

# Stop
./dev.ps1 down                         # same as stack.ps1 down: containers go, volumes stay
./deploy/stack.ps1 -Env test stop      # pause the containers; keep them and the data
./deploy/stack.ps1 -Env test down      # remove containers and network; KEEP volumes (data)
./deploy/stack.ps1 -Env test down -v   # also DELETE volumes: the test database is wiped
```

## 10. Problems we actually hit

| Symptom | Cause | Fix |
| --- | --- | --- |
| "Docker Desktop is unable to start" | WSL wasn't installed. Docker's log said `checking WSL version: wsl is not installed`. | Run `wsl --install --no-distribution` as admin, then restart Docker Desktop. |
| Still "unable to start" after installing WSL | Docker Desktop was started before WSL existed and doesn't retry | `docker desktop restart` |
| Dashboard can't reach the API, and the browser console shows a CORS error | The dashboard runs on a port that isn't `FRONTEND_ORIGIN` | Keep both at 5175. Vite's `strictPort` stops it from silently switching ports. |
| `bind: Only one usage of each socket address` on port 8000 | Another app (a Django dev server) already uses 8000 | We moved the test API to 8001 (`API_HOST_PORT`). `./dev.ps1 up` now checks ports first and names the program in the way. |
| New init script or grants not applied | Init scripts run only on an empty volume | `stack.ps1 -Env test down -v`, then `up` (test only) |
| MySQL exits with code 127, log says `docker_process_sql: command not found` | The init script was *run*, not *sourced*, so the image's helper wasn't available (section 8) | The script now uses the plain `mysql` client |
| `up -d` runs in the foreground and asks debug questions | `stack.ps1` was an advanced script, so PowerShell read `-d` as `-Debug` | `stack.ps1` is now a simple script (section 4) |
| Red `NativeCommandError` lines around normal Docker output | Windows PowerShell 5.1 shows anything written to stderr as an error when output is redirected | Harmless when the exit code is 0; `stack.ps1` checks the exit code |
| `docker` not found in an old terminal | PATH was updated after the terminal opened | Open a new terminal |

## Change log

| Date | Change |
| --- | --- |
| 2026-10-09 | First version: M0 stack, plus the M1 MySQL init script and `TALLY_URL` override. |
| 2026-10-09 | Added `dev.ps1` (section 3). `stack.ps1` is now a simple script and checks exit codes. The init script uses the `mysql` client. Test API moved to host port 8001. Fixed the MySQL example commands for PowerShell 5.1. |
| 2026-10-09 | Test dashboard moved to port 5175 (`FRONTEND_ORIGIN`). Explained why env changes need `up` to recreate containers. |
| 2026-10-09 | `.dockerignore` excludes `devtools/` (ADR-014); `seed-test-data` runs on the host. |
