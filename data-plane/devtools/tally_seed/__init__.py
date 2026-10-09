"""Seeds LedgerBridge Test Co in TallyPrime with repeatable test data (ADR-014).

Run with `./dev.ps1 seed-test-data`. Writes to Tally, so it refuses to run unless
APP_ENV=test, exactly one company is loaded and its name matches the target exactly.
"""
