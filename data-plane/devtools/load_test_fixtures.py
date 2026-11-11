"""`./dev.ps1 load-test-fixtures`: fill the TEST database with LedgerBridge Test Co from its
recorded Tally responses (data-plane/tests/fixtures/tally), the recordings the tests and CI
replay, without Tally: every connector this tool builds answers from the recorded files
(FixtureTransport, an httpx transport that opens no socket). For the dashboard on the test
stack when Tally isn't available (or has other companies loaded).

Steps, as the CLI runs them: connect (paused, so the worker never syncs it), a full sync,
statements (where the recording has them) and validation. Running it again changes nothing
that is already stored.

Refuses unless APP_ENV is test and the database is the test one (port 3307), and unless the
recording is LedgerBridge Test Co's. A developer tool (ADR-014): product code never imports
it; it runs on the host, as the image has neither tests/ nor devtools/.
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from connectors import registry
from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import DEFAULT_DIR, FixtureTransport, load_manifest
from core.config import get_settings

COMPANY = "LedgerBridge Test Co"
CONNECTION = "tally-test"
TEST_PORT = 3307
RECORDINGS = {
    # The fullest recording (2026-11-06): own, branch, job worker's and others' godowns,
    # batches, orders, GST, bills; vouchers from 2025-06 to 2026-10.
    "data-completion": DEFAULT_DIR / "rules" / "data-completion",
    # The original recording most tests use (one godown, 2026-04 to 2026-09).
    "main": DEFAULT_DIR,
}

Run = Callable[[Sequence[str]], int]


class RefusedError(Exception):
    """The tool won't run here: the message says why."""


def check(recording: Path) -> None:
    """Raises RefusedError unless this is the test environment and the recording is the test
    company's."""
    settings = get_settings()
    if settings.app_env != "test" or settings.mysql_port != TEST_PORT:
        raise RefusedError("load-test-fixtures runs only on the test environment (APP_ENV=test).")
    if load_manifest(recording).get("company") != COMPANY:
        raise RefusedError(f"The recording isn't {COMPANY}'s; nothing was loaded.")


def replaying(recording: Path) -> Callable[[str, object], TallyConnector]:
    """A connector factory that only replays the recording, whatever a connection says."""

    def create(code: str, config: object) -> TallyConnector:
        if code != "tally":
            raise RefusedError(f"Unexpected source {code!r}; nothing was loaded.")
        return TallyConnector.from_config(
            {"url": "http://recorded.invalid:9000"}, transport=FixtureTransport(recording)
        )

    return create


def steps() -> list[list[str]]:
    """The CLI commands, in order."""
    entity = ["--entity", COMPANY]
    return [
        ["connect", "--connection", CONNECTION, "--source", "tally", "--origin", "live", *entity],
        ["sync", "--connection", CONNECTION, "--source", "tally", *entity],
        ["statements", "--connection", CONNECTION, *entity],
        ["validate", "--connection", CONNECTION, *entity],
    ]


def load(recording: Path, run: Run | None = None, out: Callable[[str], None] = print) -> int:
    """Checks, then runs each step with the replaying connector; the first failing step's
    exit code (1 means "ran, with problems", as the CLI's), else 0."""
    check(recording)
    registry.create_connector = replaying(recording)  # type: ignore[assignment]
    if run is None:
        from workers.cli import main as run  # noqa: PLC0415 - after the replacement above
    worst = 0
    for step in steps():
        out(f"== {step[0]}")
        code = run(step)
        out(f"== {step[0]}: exit code {code}")
        if code >= 2:
            return code
        worst = max(worst, code)
    return worst


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="load-test-fixtures", description=__doc__)
    parser.add_argument("--recording", choices=sorted(RECORDINGS), default="data-completion")
    args = parser.parse_args(argv)
    try:
        return load(RECORDINGS[args.recording])
    except RefusedError as refused:
        print(str(refused), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
