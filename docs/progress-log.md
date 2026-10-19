# Progress log

Dated entries of what was done, newest first. The full story so far, PR by PR, is in [project-history.md](project-history.md).

| Date | Entry |
| --- | --- |
| 2026-10-19 | TallyPrime Edit Log: the test company migrated with the same GUID; exports identical to TallyPrime's; no edit history in the XML export (only `UPDATEDDATETIME`, not fetched); full sync, validation (105 checks, 0 failed) and report OK. Seed case `EDITLOG-ALTER-1`, `tests/test_edit_log.py`. |
| 2026-10-16 | Knowledge base: [the rulebook](rules/validation-and-conversion-rules.md) (every conversion and validation rule with why, proof, code, tests, ADR and four flowcharts), [the schema reference](database/schema-reference.md) (generated from the models: 52 tables, their columns, keys, relationships, users and diagrams), [the project history](project-history.md) (M0 to M4, the pilot, PRs #1 to #33), Word and PDF copies in `docs/export/` (`./dev.ps1 docs-export`). Pilot: entity 2 passes; entity 1's last differences (foreign-currency ledgers, opening difference) fixed in PR #33, result to be recorded. |
