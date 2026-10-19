# Threat model

| | |
| --- | --- |
| Version | 0.1 |
| Date | 2026-10-19 |
| Scope | Phase 1a local pilot (data plane, dashboard, developer tools) and the path to production |

What we protect, from whom, what protects it today, and what is still to do. How to work safely day to day: [security-guide.md](security-guide.md).

## 1. Assets

| Asset | Where it lives | Why it matters |
| --- | --- | --- |
| Client accounting data | MySQL `ledgerbridge_source` / `_accounting` / `_reporting` in the client's own deployment; Tally on the client's machine | Confidential books: parties, amounts, salaries, tax IDs. The product exists to keep it in the client's hands. |
| Credentials and keys | `.env.<env>` files on the host; encrypted connection credentials (from M5) | Give access to the databases, sources and AI provider. |
| Source systems (Tally) | Client machine | Must never be changed by us: read-only access only. |
| Code and releases | GitHub repository, Docker images | A tampered build would reach every client. |
| Audit trail | `ledgerbridge_system` (from M5) | Shows who saw and changed what. |

## 2. Threats and what protects against them today

| Threat | Protection today | Gap |
| --- | --- | --- |
| Client data leaves the client's environment (to the provider, the AI, logs, git) | Data plane / control plane split (the one rule in CLAUDE.md); `AI_PROVIDER=anthropic` refused with `APP_ENV=pilot` (PIL-005); pilot output shows counts and kinds only; private files only under `reports/<env>/private/`; `.gitignore` for env files and reports | Network egress allowlist (SEC-010) not built yet. |
| Writing to a source by mistake | Connectors send export requests only (CON-008); the only writer is the test seeder, guarded to LedgerBridge Test Co (ADR-014) | None known. |
| A secret committed or logged | `SecretStr` settings; env files git-ignored; gitleaks on every PR over the whole history; GitHub secret scanning and push protection | Secrets are plain text in env files on the host (encryption at rest: M9). |
| Too much database access | One MySQL user per role with least privilege (SEC-008, schema.md 2.1); containers never hold the root or migrator password | No per-user permissions in the app until M5. |
| Anyone on the machine reads the API | Ports bound to 127.0.0.1 only; `AUTH_MODE=local` for the pilot | **No login yet: M5.** |
| Malicious input (files, source XML, SQL) | Parsed with the standard library; SQLAlchemy bound parameters; Ruff security rules and Semgrep on every PR | AI-generated SQL guardrails arrive with M8. |
| A vulnerable dependency or base image | pip-audit, npm audit and Trivy on every PR; lock files (`uv.lock`, `package-lock.json`) | No automatic update PRs yet. |
| A tampered build or update | PRs reviewed and checked before merging; read-only CI token | Signed releases (SEC-004): M9. |

## 3. Security roadmap

| Milestone | Security work |
| --- | --- |
| M5 Login and permissions | Local login with Argon2id hashes, short-lived signed tokens, lockout and session expiry (AUTH-002, AUTH-007); roles, entity access and permissions checked in the data plane on every endpoint (ACC-001, ACC-002, ACC-004); audit log of logins and data access (AUD-001, AUD-002); connection credentials encrypted (SEC-003). |
| M6 Reporting | Every report endpoint behind its permission and entity filter; tests that a user can't read another entity's figures. |
| M7 / M7b Dashboard and budgets | Content Security Policy (SEC-005); no figures cached in the browser beyond the session; budget approval permissions (BUD-013). |
| M8 AI querying | SQL guardrails (single read-only SELECT on the semantic layer, `ai_ro` user, entity filters in code); privacy modes, masking and audit of every model call (AI-011 to AI-018); egress allowlist (SEC-010) with leak tests. |
| M9 Production hardening | TLS everywhere (SEC-001); encryption at rest for databases, backups and env secrets (SEC-002); signed images and bundles verified on update (SEC-004); backups and restore tested; an external penetration test before the first production client. |

## Change log

| Date | Version | Change |
| --- | --- | --- |
| 2026-10-19 | 0.1 | First version. |
