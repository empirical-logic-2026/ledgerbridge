# Security review, 2026-10-30

Attacker-style, read-only review of the whole repository on branch `feat/dashboard-d1`
(commit `2a78810`), with the dashboard API `/api/v1` (ADR-049) as the newest part.
Reviewer: Claude Code (security-auditor). Nothing was changed except this file.

## Overall verdict

**The code is in good shape; the computer it runs on is not.** The new dashboard API is
carefully built: no SQL text ever comes from a request, every `/api/v1` route goes through
the access dependency, it reads as `report_ro`, CORS is GET-only and localhost-only, and the
CSV export escapes formulas. The serious problems are around it:

1. **Tally's XML port 9000 is open to the whole network right now** (listening on all
   addresses, allowed through the firewall on the Public profile, and the current network is
   Public). Tally has no login, so anyone on the same Wi-Fi can read every loaded company's
   books and also write to them.
2. **The "localhost-only" API can still be read by any website you visit** (DNS rebinding),
   because it accepts any `Host` header. This applies to the pilot API on 8010 too.
3. **The repository folder sits at `C:\ledgerbridge` and inherits Windows' permissive
   drive-root permissions**: every local account can read `.env.pilot`, `backups/` and
   `reports/*/private/`, and change the code.

Fix those three first (all small). Everything else is Medium or lower.

## Findings

| ID | Title | Severity | Where | Effort |
|----|-------|----------|-------|--------|
| SR-001 | Tally XML port 9000 reachable from the network | Critical | host: tally.exe (TallyPrime Edit Log) on 0.0.0.0:9000; firewall rules "TallyPrime Edit Log", "Tally Gateway Server 11.0" | small |
| SR-002 | Unauthenticated API open to DNS rebinding (no Host check) | High | data-plane/api/main.py:72-88 | small |
| SR-003 | Repo folder inherits Users-read / Authenticated-Users-modify ACL | High | C:\ledgerbridge (ACL), affects .env.pilot, backups/, reports/*/private/ | small |
| SR-004 | Backups and private reports are not encrypted at rest | Medium | dev.ps1:255-271, dev.ps1:600-604 | small |
| SR-005 | `/api/validation/*` and `/api/alerts` bypass the access dependency | Medium | data-plane/api/validation.py:17-22, 84, 123, 135, 151 | small |
| SR-006 | Tally seed guard isn't pinned to "LedgerBridge Test Co" | Medium | data-plane/devtools/tally_seed/seed.py:145-157; __main__.py:38; dev.ps1:754 | small |
| SR-007 | No Claude Code permission deny rules for client data | Medium | .claude/ (no settings.json); .claude/agents/security-auditor.md:4 | small |
| SR-008 | Export-only guard is a substring check | Low | data-plane/connectors/tally/client.py:19, 80 | small |
| SR-009 | Tally responses have no size limit; DTDs accepted | Low | data-plane/connectors/tally/client.py:120; parser.py:96-107 | small |
| SR-010 | Unicode digits / very long numbers cause a 500 | Low | data-plane/api/v1/dataset_query.py:337, 344 | small |
| SR-011 | No security headers; data cacheable; /docs open | Low | data-plane/api/main.py:74-88 | small |
| SR-012 | SQL parameters and unredacted Tally text can reach logs/DB | Low | data-plane/core/db.py:48; data-plane/workers/sync.py:648, 655 | small |
| SR-013 | `ai_ro` sees every view in reporting, incl. system data via DEFINER views | Low | deploy/mysql/init/01-schemas.sh:48; migrations/versions/0024_dashboard_views.py:36-50 | medium |
| SR-014 | Redis and Qdrant have no password/API key | Low | deploy/compose.yaml:37-60 | small |
| SR-015 | Weak local test passwords | Low | .env.test:8, .env.test:12 (not in git) | small |
| SR-016 | Actions and images pinned by tag, not by hash | Low | .github/workflows/checks.yml:35-36 etc.; deploy/compose.yaml:8, 38, 50; data-plane/Dockerfile:1, 4 | small |
| SR-017 | compare-ledger private TSV not formula-escaped | Low | data-plane/workers/compare.py:221-242; dev.ps1:604 | small |
| SR-018 | ADR-049 and code disagree; docstring names a missing test | Info | docs/architecture.md:409; frontend/vite.config.ts:9-14; data-plane/api/validation.py:4 | small |

---

### SR-001: Tally XML port 9000 reachable from the network

- **Severity: Critical.** Tally's XML server has no authentication at all, and it is
  reachable from other machines now, so client books can be read and changed by anyone on
  the same network.
- **Where:** host configuration, not repository code. Found with read-only listings
  (`netstat`, `netsh advfirewall ... show`), without contacting Tally:
  - port 9000 is listened on `0.0.0.0:9000` and `[::]:9000` by
    `C:\Program Files\TallyPrimeEditLog\tally.exe`;
  - inbound firewall rules "TallyPrime Edit Log" (that tally.exe) and
    "Tally Gateway Server 11.0" are **Allow, Public profile, any local port, any remote IP**
    (TCP and UDP);
  - the current network connection is categorised **Public**, so these rules apply.
  - (The rule for `C:\program files\tallyprime\tally.exe` is Block, which is right; the Edit
    Log edition is the one running.)
- **How an attacker would use it:** someone on the same Wi-Fi (office, cafe, hotel) sends an
  HTTP POST to `http://<this-pc>:9000` with an Export request and gets the loaded companies'
  masters and vouchers. With an Import request they can add, alter or cancel vouchers in the
  books. Our code is careful to be Export-only, but that does not protect Tally from others.
  During pilot work the loaded companies are client companies.
- **Fix:** in Windows Defender Firewall, disable (or delete) the two Allow rules for the
  Public profile, and add one inbound **Block** rule for TCP port 9000 from remote addresses
  on all profiles. Keep Tally running only while you sync. Docker reaches Tally through
  `host.docker.internal`; after the change, confirm `./dev.ps1 tally-companies` still works
  (if it doesn't, allow only the Docker/WSL virtual adapter's subnet, never "Any").
  Also document this in `docs/pilot-runbook.md` as a pre-flight step.
- **Test that proves it:** `netsh advfirewall firewall show rule name="TallyPrime Edit Log"`
  shows Action Block (or no Allow); from a second device you own on the same network,
  `Test-NetConnection <pc-ip> -Port 9000` reports `TcpTestSucceeded: False`; locally
  `./dev.ps1 tally-companies` still lists the test company.
- **Effort:** small.

### SR-002: Unauthenticated API open to DNS rebinding (no Host check)

- **Severity: High.** Binding to 127.0.0.1 stops other machines, but not a malicious web
  page in your own browser, and there is no login until M5.
- **Where:** `data-plane/api/main.py:72-88` (`create_app` adds CORS but no host check).
  Verified with one read-only request to the test API's `/health` on 127.0.0.1:8001 with a
  foreign `Host` header: answered `200`. The pilot API listens on 127.0.0.1:8010 with the same
  code (it was not contacted).
- **How an attacker would use it:** you open a web page on `evil.example`. Its DNS name first
  points to the attacker's server, then (short TTL) to `127.0.0.1`. The page now calls
  `http://evil.example:8010/api/v1/datasets/voucher_lines/csv` and the browser treats it as the
  page's own origin, so CORS doesn't apply; the API answers because it doesn't check the
  `Host` header. The page uploads every company's voucher lines to the attacker. (Newer
  Chrome "local network access" prompts reduce this, but not every browser has them.)
- **Fix:** add Starlette's built-in `TrustedHostMiddleware` (part of FastAPI, no new
  dependency) in `create_app`:
  `app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])`
  (it ignores the port). If any container-internal caller uses another host name, add it
  explicitly. Mention it in ADR-049.
- **Test:** with `TestClient(app)`, `GET /health` with `headers={"Host": "evil.example"}`
  returns 400, and with `Host: localhost:8001` returns 200; repeat for one `/api/v1` route.
- **Effort:** small.

### SR-003: Repository folder inherits permissive drive-root permissions

- **Severity: High.** Every account on this PC can read the pilot's secrets and data, and
  modify code that you then run.
- **Where:** `C:\ledgerbridge` (inherited ACL: `BUILTIN\Users:(OI)(CI)(RX)` and
  `NT AUTHORITY\Authenticated Users:(OI)(CI)(IO)(M)`). Because of `(OI)(CI)` this flows down
  to `.env.pilot` (all MySQL passwords incl. root), `backups/` (full database dumps),
  `reports/*/private/` (voucher-level details), and `dev.ps1` / `deploy/*.ps1` /
  `data-plane/**`. Only the root folder's ACL was listed; the protected folders were not
  opened.
- **How an attacker would use it:** another local user (a colleague's account, a guest
  account, malware running as a different user) copies `backups/pilot/*.sql.gz` and has every
  client's books; or edits `dev.ps1` so that your next `./dev.ps1 up` runs their code with your
  rights.
- **Fix (simplest):** move the clone under your profile (`C:\Users\<you>\src\ledgerbridge`),
  which only you, SYSTEM and Administrators can read. Or remove inheritance in place:
  `icacls C:\ledgerbridge /inheritance:r /grant:r "%USERNAME%:(OI)(CI)F" "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F"`.
  Add the check to `docs/pilot-runbook.md`.
- **Test:** `icacls C:\ledgerbridge` and `icacls C:\ledgerbridge\backups` show no `Users` or
  `Authenticated Users` entries. Optionally a `dev.ps1` check that warns on `up -Env pilot`
  when the repo root grants those groups access.
- **Effort:** small.

### SR-004: Backups and private reports are not encrypted at rest

- **Severity: Medium.** A lost or stolen laptop, or a copied folder, gives away every
  client's books in plain SQL.
- **Where:** `dev.ps1:255-271` (`Backup-Database` writes a plain `.sql.gz`),
  `dev.ps1:600-604` (compare-ledger details as plain `.tsv`).
- **How an attacker would use it:** take the disk (or a copy of the folder), unzip the dump,
  load it.
- **Fix:** first make sure BitLocker is on for drive C: (check as administrator with
  `manage-bde -status C:`). Then, with no new tools, mark the two folders for Windows EFS
  encryption (`cipher /e /s:<repo>\backups`, and the same for `reports`) so files are
  encrypted for your account. If backups are ever copied off the PC, encrypt them with a tool
  the developer approves.
- **Test:** `cipher /c <a backup file>` shows it as encrypted; `manage-bde -status C:` shows
  "Protection On".
- **Effort:** small.

### SR-005: `/api/validation/*` and `/api/alerts` bypass the access dependency

- **Severity: Medium.** These unauthenticated endpoints read as the read-write user and
  ignore "on hold" and, after M5, would ignore the user's companies too.
- **Where:** `data-plane/api/validation.py:17-22` (`get_session`, i.e. `app_rw`),
  `:84` (`/api/validation/status` lists every entity, names included, and the opening
  difference amount), `:123`, `:135` (any run id), `:151` (all alerts, all entities). Not
  under `api/v1`, so `current_access` (`api/access.py`) is not applied; the v1 test
  (`tests/test_api_v1.py:27`) only checks `/api/v1`.
- **How an attacker would use it:** today, the same as SR-002 (any page that reaches the API
  reads them). After M5, a logged-in user with access to one company calls
  `/api/validation/runs/<id>` for another company's run, because only `current_access` is
  replaced and these routes never call it. Entities on hold (SYN-007) still show here.
- **Fix:** route them through `CurrentAccess`: filter every query with
  `access.entities()` (status and runs by `entity_id`; a single run answers 404 when its
  entity is outside the access; alerts by `entity_id`, dropping alerts without one). Best:
  move them to `/api/v1` and read through a reporting view as `report_ro`, so HTTP requests
  never use a write user.
- **Test:** extend `test_every_v1_endpoint_is_a_get_behind_the_access_dependency` to every
  route under `/api/`; integration test: put an entity on hold, `GET /api/validation/status`
  doesn't list it and its runs answer 404.
- **Effort:** small.

### SR-006: Tally seed guard isn't pinned to the test company

- **Severity: Medium.** The only code allowed to write to Tally will write into whatever
  single company is loaded, if its name is passed.
- **Where:** `data-plane/devtools/tally_seed/seed.py:145-157` checks APP_ENV, "exactly one
  company loaded" and "loaded name equals `--company`", but not that `--company` is
  "LedgerBridge Test Co"; `data-plane/devtools/tally_seed/__main__.py:38` takes any name;
  `dev.ps1:754` only defaults it. Test and pilot both point at the same Tally
  (`.env.test.example:34`, `deploy/compose.yaml:75`), and `APP_ENV=test` is just a value in
  the test env file.
- **How an attacker would use it:** mostly an accident path: with a client company loaded
  alone, `./dev.ps1 seed-test-data -Company "<that company>"` imports seed vouchers,
  alterations and deletions into a client's books. CLAUDE.md says the seed may write to
  LedgerBridge Test Co **only**.
- **Fix:** a constant `TEST_COMPANY = "LedgerBridge Test Co"` in `devtools/tally_seed`;
  `check_guards` refuses any other name; `dev.ps1 seed-test-data` refuses `-Company`.
- **Test:** `check_guards(test_settings, "Other Co", ["Other Co"])` raises
  `SeedRefusedError`; a dev.ps1 test shows `seed-test-data -Company X` is refused before any
  call.
- **Effort:** small.

### SR-007: No Claude Code permission deny rules for client data

- **Severity: Medium.** The rules that keep AI agents away from `.env.pilot`, `backups/`,
  pilot ports and Tally exist only as text in prompts.
- **Where:** there is no `.claude/settings.json`; `.claude/agents/security-auditor.md:4`
  grants `Bash` without limits (so "read-only" is a request, not a control).
- **How an attacker would use it:** a prompt injection (text in a file, or later a narration
  shown to an agent) or a simple mistake leads an agent to print `.env.pilot`, read a backup
  or POST to port 9000.
- **Fix:** commit `.claude/settings.json` with `permissions.deny` entries such as
  `Read(./.env.pilot)`, `Read(./backups/**)`, `Read(./reports/*/private/**)`,
  `Read(C:/TallyClientData/**)`, and Bash deny patterns for `-Env pilot`, `:3317` and `:9000`.
  Bash patterns are prefix-based and can be bypassed, so treat them as a safety net.
- **Test:** in a new session, ask the agent to read `.env.pilot`; the tool call is denied.
- **Effort:** small.

### SR-008: Export-only guard is a substring check

- **Severity: Low.** Defence in depth for CON-008: today every envelope is built from
  constants with escaped names, so it isn't exploitable as written.
- **Where:** `data-plane/connectors/tally/client.py:19, 80`.
- **How an attacker would use it:** a future change that builds a request containing both
  `<TALLYREQUEST>Export</TALLYREQUEST>` (say in a comment or a field) and an Import header
  passes the guard.
- **Fix:** parse the request (`ET.fromstring`) and require exactly one
  `HEADER/TALLYREQUEST` whose text is `Export`.
- **Test:** a request with an `Import Data` header plus the Export marker elsewhere raises
  `ValueError`.
- **Effort:** small.

### SR-009: Tally responses have no size limit; DTDs accepted

- **Severity: Low.** Tally is a trusted local source, but whatever answers on port 9000 is
  believed (when Tally is closed, any local program can listen there).
- **Where:** `data-plane/connectors/tally/client.py:120` (`response.content`, unbounded),
  `data-plane/connectors/tally/parser.py:96-107` (decoded, rewritten by regex and parsed:
  several full copies in memory).
- **Already fine:** Python's expat (2.8.5 here) doesn't fetch external entities (no XXE) and
  limits entity expansion ("billion laughs"); names in requests are escaped
  (`envelopes.py:283-344`).
- **How an attacker would use it:** a fake service on 9000 returns gigabytes, or a DTD with
  entities; the worker runs out of memory and stops syncing.
- **Fix:** stream the response and stop past a configurable limit (for example
  `TALLY_MAX_RESPONSE_MB`); refuse bodies containing `<!DOCTYPE` or `<!ENTITY` before parsing
  (Tally never sends them).
- **Test:** a fake `httpx` transport returning an oversized body or a DOCTYPE raises
  `TallyError`.
- **Effort:** small.

### SR-010: Unicode digits or very long numbers cause a 500

- **Severity: Low.** Only a crash with a stack trace in the log, but that log line then holds
  the query value, which ADR-049 says never to log.
- **Where:** `data-plane/api/v1/dataset_query.py:337` (`_number`) and `:344` (ids).
  `str.isdigit()` is true for a superscript two and for a 5,000-digit string, but `int()`
  fails on both (checked locally in Python, not against the API).
- **How an attacker would use it:** such a `company` or `page` value gives a 500 instead of
  a 422.
- **Fix:** `re.fullmatch(r"[0-9]{1,18}", text)` before `int()`.
- **Test:** both requests answer 422 with the plain message.
- **Effort:** small.

### SR-011: No security headers; data responses cacheable; /docs open

- **Severity: Low.**
- **Where:** `data-plane/api/main.py:74-88`. `/docs` and `/openapi.json` answer 200 (checked
  on the test API).
- **How an attacker would use it:** the browser's disk cache keeps CSVs and JSON with figures
  after the tab is closed; the open API description maps every endpoint for an attacker who
  gets in (SR-002).
- **Fix:** a small middleware adding `Cache-Control: no-store` on `/api/`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and
  `Content-Security-Policy: frame-ancestors 'none'`; `docs_url=None, openapi_url=None` unless
  `APP_ENV=test` (the frontend's type generator uses the schema in test).
- **Test:** assert the headers on one `/api/v1` response; `/docs` is 404 with
  `APP_ENV=pilot`.
- **Effort:** small.

### SR-012: SQL parameters and unredacted Tally text can reach logs and the database

- **Severity: Low.**
- **Where:** `data-plane/core/db.py:48` (`create_engine` without `hide_parameters=True`: an
  unhandled database error in an API request is logged by uvicorn with the SQL and its bound
  values: dates, ids, amount filters); `data-plane/workers/sync.py:648, 655` and
  `data-plane/workers/extract.py:120` (`short_error(exc)` without `redact=True` stores, for
  example, Tally's `LINEERROR` text, up to 200 characters that can name companies or ledgers,
  in `sync_runs.error_summary`). The report doesn't print that note today
  (`workers/report.py:428`), so this is about stored data, not output.
- **Fix:** `create_engine(..., hide_parameters=True)`; `short_error(exc, redact=True)` in
  `_fail_run`, `_stop_run` and the extract path.
- **Test:** an endpoint test whose session raises `DBAPIError` asserts the captured log holds
  no parameter values; a sync test with a `TallyError` whose message quotes a ledger name
  asserts the stored summary has no quoted name.
- **Effort:** small.

### SR-013: `ai_ro` sees every view in reporting, including system data via DEFINER views

- **Severity: Low** (no AI code yet; this matters at M8).
- **Where:** `deploy/mysql/init/01-schemas.sh:48` grants `SELECT ON ledgerbridge_reporting.*`;
  views are created by the migrator and run with its rights (MySQL's default SQL SECURITY
  DEFINER), e.g. `v_data_health` (`data-plane/migrations/versions/0024_dashboard_views.py:36-50`)
  reads `ledgerbridge_system`; the views don't apply `is_on_hold`.
- **How an attacker would use it:** at M8, a prompt-injected or careless AI query reads any
  view added for the dashboard, not only the intended semantic layer (AI-003).
- **Fix:** before M8, grant `ai_ro` per view (an explicit allow-list), or put dashboard-only
  views in another schema; make the AI layer's entity filters exclude companies on hold.
- **Test:** `tests/test_grants_integration.py` asserts the exact set of objects `ai_ro` can
  select (from `information_schema.TABLE_PRIVILEGES`).
- **Effort:** medium.

### SR-014: Redis and Qdrant have no password or API key

- **Severity: Low.** Bound to 127.0.0.1, so only local programs can reach them.
- **Where:** `deploy/compose.yaml:37-60`.
- **How an attacker would use it:** any local process (or another local user, see SR-003)
  pushes Celery messages (JSON only, so only registered tasks, e.g. start syncs) or reads and
  writes Qdrant (at M8 it will hold embeddings of Tally text). Qdrant's HTTP API is also
  reachable by DNS rebinding (SR-002).
- **Fix:** if the host doesn't need them, remove their `ports:` (containers use the internal
  network). Otherwise `--requirepass` for Redis (password in the env file and `REDIS_URL`) and
  `QDRANT__SERVICE__API_KEY` for Qdrant. Update `docs/learning/docker.md`.
- **Test:** extend `test_api_binds_to_localhost_only`: Redis and Qdrant are either unpublished
  or configured with a secret.
- **Effort:** small.

### SR-015: Weak local test passwords

- **Severity: Low.** Test environment only and localhost only, but the MySQL root password
  is one of them.
- **Where:** `.env.test:8` (MySQL root password) and `.env.test:12` (app_rw password) are 8
  characters, not generated by `init-env` (the other three are 32). Values not shown. The file
  is git-ignored and was never committed.
- **Fix:** recreate `.env.test` with `./dev.ps1 init-env -Env test` (after
  `./dev.ps1 reset -Env test -Force`, because the volume holds the old passwords).
- **Effort:** small.

### SR-016: Actions and images pinned by tag, not by hash

- **Severity: Low.** A moved tag or a compromised publisher changes what runs in CI or in
  your containers.
- **Where:** `.github/workflows/checks.yml:35-36, 53-54, 91-92, 124-125, 167-168, 186, 206,
  224` (`actions/checkout@v7`, `astral-sh/setup-uv@v10.3.0`, `actions/setup-node@v7`); images
  at `checks.yml:72, 82, 88, 184, 212, 222`; `deploy/compose.yaml:8, 38, 50`;
  `data-plane/Dockerfile:1, 4`. `actions/checkout` keeps the token in `.git/config` by
  default (a read-only token here, so minor).
- **Already fine:** `permissions: contents: read`; the `pull_request` trigger (not
  `pull_request_target`), so forks get no secrets; `uv.lock` with `uv sync --frozen`;
  `package-lock.json` with `npm ci`.
- **Fix:** pin actions to commit SHAs and images to `@sha256:` digests (with the tag in a
  comment); `persist-credentials: false` on checkout. An update bot needs the developer's
  approval.
- **Effort:** small.

### SR-017: compare-ledger private TSV isn't formula-escaped

- **Severity: Low.**
- **Where:** `data-plane/workers/compare.py:221-242`, written by `dev.ps1:604`.
- **How an attacker would use it:** a voucher number or type typed in Tally as a formula
  (for example a `HYPERLINK` that sends a neighbouring cell to a web address) runs when the
  TSV is opened in Excel.
- **Fix:** run each text cell through the same escaping as `_safe` in
  `data-plane/api/v1/datasets.py:206` (move it to `core` and reuse it).
- **Test:** a comparison with the voucher number `=1+1` writes `'=1+1`.
- **Effort:** small.

### SR-018: ADR-049 and the code disagree; a docstring names a missing test

- **Severity: Info.** Wrong docs lead to wrong security assumptions.
- **Where:** `docs/architecture.md:409` says `./dev.ps1 dashboard` starts Vite on 127.0.0.1
  with an `/api` proxy and that CORS allows port 5173. The code: no `dashboard` command in
  `dev.ps1`; `frontend/vite.config.ts:9-14` uses port 5175, Vite's default host (`localhost`,
  which is loopback, so fine) and no proxy; CORS comes from `FRONTEND_ORIGIN`.
  `data-plane/api/validation.py:4` cites `tests/test_api_binding.py`, which doesn't exist (the
  test is `tests/test_validation.py:312`).
- **Fix:** bring the ADR and the docstring in line with the code (or the code with the ADR);
  set `server.host: '127.0.0.1'` explicitly in `vite.config.ts`.
- **Effort:** small.

---

## Areas checked and found fine

- **Exposure:** every port in `deploy/compose.yaml` is published on 127.0.0.1 only, and
  `tests/test_validation.py:312` enforces it; netstat confirms 3307, 3317, 6333, 6380, 8001
  and 8010 on 127.0.0.1. The container listens on 0.0.0.0 inside Docker only (needed). The
  startup warning (`api/main.py:46-59`) exists.
- **CORS:** only `http://localhost:<port>` and `http://127.0.0.1:<port>` from
  `FRONTEND_ORIGIN`, GET only, `Content-Type` only (`api/main.py:37-43, 75-81`), tested.
- **SQL injection:** no SQL is built from input anywhere in product code. The explorer maps
  only allow-listed keys to fixed SQLAlchemy expressions (`api/v1/dataset_specs.py`), refuses
  unknown parameters, accepts sort keys only from the shown columns and measures, binds every
  value (`api/v1/dataset_query.py:282-360`), and has a test
  (`test_requests_become_bound_sql_without_request_text`). The few f-string SQL statements are
  in applied migrations and tests, built from constant database names;
  `core/monthly_sales.py:145` uses a bound parameter.
- **Access dependency:** every `/api/v1` route depends on `current_access`
  (`api/v1/__init__.py`), companies outside it answer 404, companies on hold are excluded;
  tested. (The older `/api/validation` and `/api/alerts` routes are not: SR-005.)
- **Database users:** `app_rw` has no DDL; `report_ro` only SELECT on accounting and
  reporting; `migrator` is used only in the one-off `migrate` container; root and migrator
  passwords are blanked in `api` and `worker` (`deploy/compose.yaml:76-79`); `/api/v1` reads
  as `report_ro`.
- **Tally writes:** product code never imports `devtools`; `devtools/` is excluded from the
  image (`data-plane/.dockerignore`); the client refuses non-Export requests (see SR-008);
  names in envelopes are XML-escaped.
- **XML:** stdlib expat, no external entity resolution (no XXE), entity-expansion protection.
- **XSS:** the frontend has no `dangerouslySetInnerHTML`, `innerHTML` or HTML built from
  strings, and doesn't render Tally text yet (`frontend/src`).
- **CSV export:** cells starting with `=`, `+`, `-`, `@`, tab or CR get a `'` prefix
  (`api/v1/datasets.py:206-208`), tested; the file name is the fixed dataset key, so no header
  injection. (Good to know: in a CSV, Excel shows that `'` literally.)
- **Path traversal and command injection:** no file path is built from API input; `dev.ps1`
  and `deploy/*.ps1` pass arguments as arrays (no `Invoke-Expression`); the backup command
  string is constant and keeps the root password inside the container (`MYSQL_PWD`); no
  `subprocess` or `shell=True` in product code.
- **Secrets:** `.env*` (except the examples), `backups/` and `reports/` are git-ignored; no env
  file, dump or private report was ever committed (git history, all branches); the example
  files hold placeholders only; secrets are `SecretStr`; `init-env` uses a cryptographic
  random generator and never prints values; gitleaks runs with `--redact` in CI.
- **Logging:** the request log is method, path, status and time (`api/main.py:62-69`);
  uvicorn's access log is off; workers log errors as type and redacted message
  (`workers/celery_app.py`, `core/errors.py`); 500 responses carry no stack trace.
- **Docker:** the app image runs as a non-root user (`Dockerfile:79-80`); no secrets are baked
  in (env files excluded); only the read-only init folder is mounted from the host.
- **Celery:** JSON serializer only (no pickle).
- **CI:** read-only token, `pull_request` trigger, required "All checks", pip-audit, npm
  audit, Semgrep, gitleaks and Trivy.
- **Local tool runs:** `ruff --select S` (security rules): no findings. `npm audit` (frontend):
  0 vulnerabilities.

## Not checked, and why

- Anything in the pilot environment, `.env.pilot`, `backups/`, `reports/*/private/` and
  `C:\TallyClientData`: forbidden by the review rules. Their exposure was judged from the root
  folder's ACL only.
- Tally itself: not contacted. Which companies are loaded is unknown.
- Whether port 9000 is reachable from another machine: no scanning; judged from the listeners
  and the firewall rules.
- BitLocker status: needs administrator rights.
- Semgrep, pip-audit, gitleaks and Trivy: not installed locally; they run in CI.
- Docker Desktop settings (e.g. exposing the daemon on TCP) and user-level Claude Code
  plugins: outside the repository.

## Future risks (note, don't block)

- **AI assistant (M8):** narrations, ledger and party names come from Tally and will reach the
  model. Treat them as untrusted: keep them out of system instructions, pass them as quoted
  data, and rely on SQL validation, `ai_ro` and entity filters enforced in code, never on the
  model's obedience (see SR-013). Never let the model's output trigger actions.
- **Charts:** ECharts renders tooltip `formatter` strings as HTML. When Tally names are
  charted, use the default formatter or escape names (`echarts.format.encodeHTML`) in custom
  ones.
- **Login (M5):** replace `current_access` and also cover `/api/validation` and `/api/alerts`
  (SR-005); httpOnly, Secure, SameSite=Strict cookies or short-lived tokens; Argon2 or bcrypt
  password hashes in the control plane; TOTP two-factor; rate limiting and lockout on login;
  CSRF protection once any POST exists; audit permission changes (AUD-001). Keep the Host
  check (SR-002) after M5.

## Prioritised fix list

1. **SR-001 (Critical):** block inbound port 9000 from the network in the firewall, today.
2. **SR-002 (High):** add `TrustedHostMiddleware` to the API.
3. **SR-003 (High):** move the repo under your profile, or remove the inherited Users and
   Authenticated Users permissions.
4. **SR-005 (Medium):** put the validation and alerts endpoints behind the access dependency.
5. **SR-006 (Medium):** pin the seed tool to "LedgerBridge Test Co".
6. **SR-004 (Medium):** BitLocker on; EFS on `backups/` and `reports/`.
7. **SR-007 (Medium):** commit `.claude/settings.json` deny rules.
8. **SR-012, SR-010, SR-011, SR-008, SR-009 (Low):** logging redaction, number parsing,
   headers, the Export check, a response size limit (small code changes; one PR).
9. **SR-014, SR-015, SR-016, SR-017 (Low):** Redis/Qdrant secrets or unpublished ports, test
   passwords, hash pinning, TSV escaping.
10. **SR-013 (Low, before M8)** and **SR-018 (Info)**.
