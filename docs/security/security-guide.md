# Security guide

| | |
| --- | --- |
| Version | 0.1 |
| Date | 2026-10-19 |

How we keep LedgerBridge secure while building it. What we protect and from whom: [threat-model.md](threat-model.md).

## 1. Rules that always apply

- **Client data stays with the client.** It is never stored, logged or sent anywhere by the provider's control plane, by Claude Code or by CI. Claude Code works only with the `test` environment and LedgerBridge Test Co.
- **Sources are read-only.** We only export from Tally; only the test seeder writes, and only to LedgerBridge Test Co (ADR-014).
- **No secrets in git, logs or error messages.** Passwords and keys live in git-ignored `.env.<env>` files and are read as `SecretStr`.
- **Least privilege.** Each MySQL user and container has only the rights it needs (schema.md 2.1).
- **No new dependency** (library, tool, GitHub Action, Docker image) without the developer's approval.

## 2. Every change

1. Work on a branch from `dev`; never commit to `dev` or `main`.
2. Go through the security checklist in CLAUDE.md: authentication, authorisation, input validation, data exposure, secrets, logging and audit, dependencies, client data rules.
3. Open a pull request. Its description ends with **What changed**, **Why**, **Security impact** and **Code walkthrough**.
4. The checks workflow runs (README, "Automated checks"). **"All checks" must pass before merging**: branch protection on `dev` and `main` requires it.

## 3. What the automated checks catch

| Check | Catches | Blocks on |
| --- | --- | --- |
| Ruff (with its `S` security rules), unit tests | Bugs, unsafe calls (shell, `eval`, weak hashes, SQL built from strings) | Any finding or failure |
| Integration tests | Broken migrations, database grants, sync on MySQL | Any failure |
| pip-audit, npm audit | Known vulnerabilities in our dependencies | Python: any known vulnerability; npm: high or critical |
| Semgrep | Insecure code patterns in Python, TypeScript, Dockerfiles and workflows | High (ERROR) findings |
| gitleaks | Passwords, keys and tokens in any commit | Any finding |
| Trivy | Vulnerable packages in our Docker image | High or critical with a fix available |

When a check fails, **fix the cause** (upgrade the package, change the code, remove the secret and rotate it). Silencing a finding is the exception: it needs a comment saying why it is safe.

## 4. If something goes wrong

- **A secret was committed:** treat it as leaked. Rotate it first, then remove it from the code; deleting the commit is not enough.
- **Client data reached the wrong place** (a log, a fixture, a commit, a chat): stop, tell the developer, delete it there and record what happened.
- **A vulnerability with no fix yet:** record it in the PR, with why it doesn't affect us or when it will be fixed.

## Change log

| Date | Version | Change |
| --- | --- | --- |
| 2026-10-19 | 0.1 | First version. |
