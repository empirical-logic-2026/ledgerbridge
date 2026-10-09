"""MySQL database names, one per layer (schema.md Section 2, ADR-016).

Application code uses these constants. Migrations use the literal names, because a
migration must keep meaning what it meant when it was written.
"""

SOURCE = "ledgerbridge_source"  # raw layer: data exactly as received
ACCOUNTING = "ledgerbridge_accounting"  # canonical accounting model
REPORTING = "ledgerbridge_reporting"  # semantic layer; the only database the AI can read
SYSTEM = "ledgerbridge_system"  # connections, sync, validation, security, audit, settings

ALL = (SOURCE, ACCOUNTING, REPORTING, SYSTEM)
