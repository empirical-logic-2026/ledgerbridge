# Control plane (placeholder)

Provider-hosted service for login, MFA, licence checks and the client registry (architecture.md §3, requirements AUTH-001 to AUTH-007). Deferred to Phase 1b; during the pilot the data plane runs with `AUTH_MODE=local` (ADR-010).

**The rule that must never be broken:** the control plane stores only user login credentials, user-to-client mapping and licence data. It must never store, log, cache, proxy or receive client accounting data, files, query results, reports, AI prompts or usage analytics (PM-003, ADR-001).
