"""The docker compose arguments every `./dev.ps1` command builds (no Docker needed).

dev.ps1 runs a stand-in for deploy/stack.ps1 (LEDGERBRIDGE_DEV_STACK) that records each
call's arguments. Pilot 2026-10-15: `status` failed with `unknown docker command:
"compose p"` because a single argument (`ps`) came back from a helper as a string and was
splatted character by character. Every command is checked here for whole-word arguments.

Runs dev.ps1 through Windows PowerShell with `-Env test`; skipped elsewhere, and when
.env.test is missing (dev.ps1 requires it).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

POWERSHELL = shutil.which("powershell")
REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not POWERSHELL or not (REPO / ".env.test").exists(),
    reason="needs Windows PowerShell and .env.test",
)

FAKE_STACK = r"""
param([string]$Env = 'test')
$record = @{ env = $Env; args = @($args | ForEach-Object { "$_" }) } | ConvertTo-Json -Compress
Add-Content -Path $env:LEDGERBRIDGE_DEV_STACK_LOG -Value $record -Encoding UTF8
if (($args -join ' ') -eq 'ps --status running --services') { 'api'; 'mysql' }
exit 0
"""
GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
CLI = ["python", "-m", "workers.cli"]
SERVICES = ["ps", "--status", "running", "--services"]


def _calls(tmp_path: Path, *argv: str) -> list[list[str]]:
    stack, log = tmp_path / "fake-stack.ps1", tmp_path / "calls.jsonl"
    stack.write_text(FAKE_STACK, encoding="utf-8")
    log.unlink(missing_ok=True)
    env = {
        **__import__("os").environ,
        "LEDGERBRIDGE_DEV_STACK": str(stack),
        "LEDGERBRIDGE_DEV_STACK_LOG": str(log),
    }
    done = subprocess.run(  # noqa: S603 - fixed arguments, no shell
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(REPO / "dev.ps1"), *argv, "-Env", "test"],
        capture_output=True, text=True, timeout=120, check=False, env=env, cwd=REPO,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    calls = []
    for line in log.read_text(encoding="utf-8-sig").splitlines() if log.exists() else []:
        record = json.loads(line)
        assert record["env"] == "test"
        args = record["args"] if isinstance(record["args"], list) else [record["args"]]
        calls.append(["<job>" if GUID.match(a) else a for a in args])
    return calls


def _exec(*cli: str) -> list[str]:
    return ["exec", "-T", "api", *CLI, *cli]


def _job(*cli: str) -> list[str]:
    return ["exec", "-d", "api", *CLI, *cli, "--job", "<job>"]


WATCH_JOB = _exec("watch", "--connection", "tally-test", "--job", "<job>")

CASES = {
    "status": (["status"], [["ps"], SERVICES, _exec("status")]),
    "down": (["down"], [["down"]]),
    "logs": (["logs"], [["logs", "-f", "--tail", "200"]]),
    "logs api": (["logs", "api"], [["logs", "-f", "--tail", "200", "api"]]),
    "summary": (["summary"], [SERVICES, _exec("summary")]),
    "report": (
        ["report"],
        [SERVICES, _exec("report", "--format", "markdown"), _exec("report")],
    ),
    "report -Details": (
        ["report", "-Details"],
        [SERVICES, _exec("report", "--format", "markdown"), _exec("report", "--details")],
    ),
    "tally-companies": (
        ["tally-companies"],
        [SERVICES, _exec("entities", "--connection", "tally-test", "--source", "tally")],
    ),
    "entity-check": (
        ["entity-check"],
        [SERVICES, _exec("entity-check", "--connection", "tally-test", "--source", "tally")],
    ),
    "fields": (["fields"], [SERVICES, _exec("fields")]),
    "promote-field": (
        ["promote-field", "-FieldId", "12", "-Code", "SALESMAN", "-Name", "Sales person"],
        [
            SERVICES,
            _exec(
                "promote-field", "--field-id", "12", "--code", "SALESMAN", "--name", "Sales person"
            ),
        ],
    ),  # fmt: skip
    "connect": (
        ["connect", "-Origin", "live", "-Company", "LedgerBridge Test Co", "-Activate"],
        [
            SERVICES,
            _exec(
                "connect",
                "--connection",
                "tally-test",
                "--source",
                "tally",
                "--origin",
                "live",
                "--entity",
                "LedgerBridge Test Co",
                "--activate",
            ),
        ],
    ),  # fmt: skip
    "connect -Educational": (
        ["connect", "-Origin", "backup", "-All", "-Educational", "yes"],
        [
            SERVICES,
            _exec(
                "connect",
                "--connection",
                "tally-test",
                "--source",
                "tally",
                "--origin",
                "backup",
                "--all",
                "--educational",
                "yes",
            ),
        ],
    ),  # fmt: skip
    "extract": (
        ["extract", "-Company", "LedgerBridge Test Co"],
        [
            SERVICES,
            _exec(
                "extract",
                "--connection",
                "tally-test",
                "--source",
                "tally",
                "--entity",
                "LedgerBridge Test Co",
            ),
        ],
    ),  # fmt: skip
    "validate": (
        ["validate"],
        [SERVICES, _exec("validate", "--connection", "tally-test", "--source", "tally")],
    ),
    "validate -Quick": (
        ["validate", "-Quick"],
        [SERVICES, _exec("validate", "--connection", "tally-test", "--source", "tally", "--quick")],
    ),  # fmt: skip
    "validate compare-ledger": (
        ["validate", "compare-ledger", "-Ledger", "88", "-From", "2020-04-01", "-To", "2021-04-01"],
        [
            SERVICES,
            _exec(
                "compare-ledger",
                "--connection",
                "tally-test",
                "--ledger",
                "88",
                "--private",
                "--from",
                "2020-04-01",
                "--to",
                "2021-04-01",
            ),
        ],
    ),  # fmt: skip
    "validate analyse": (
        ["validate", "analyse"],
        [SERVICES, _job("validate-analyse", "--connection", "tally-test"), WATCH_JOB],
    ),
    "sync": (
        ["sync"],
        [SERVICES, _job("sync", "--connection", "tally-test", "--source", "tally"), WATCH_JOB],
    ),
    "sync full -Restart": (
        ["sync", "full", "-Restart"],
        [
            SERVICES,
            _job(
                "sync",
                "--connection",
                "tally-test",
                "--source",
                "tally",
                "--full",
                "--check-deletions",
                "--restart",
            ),
            WATCH_JOB,
        ],
    ),  # fmt: skip
    "sync deletions": (
        ["sync", "deletions"],
        [
            SERVICES,
            _job("check-deletions", "--connection", "tally-test", "--source", "tally"),
            WATCH_JOB,
        ],
    ),  # fmt: skip
    "sync watch": (
        ["sync", "watch"],
        [SERVICES, _exec("watch", "--connection", "tally-test")],
    ),
    "sync abandon": (
        ["sync", "abandon", "-Confirmation", "abandon"],
        [SERVICES, _exec("abandon", "--connection", "tally-test", "--yes")],
    ),
    "transform retry": (
        ["transform", "retry"],
        [SERVICES, _job("transform-retry", "--connection", "tally-test"), WATCH_JOB],
    ),
    "transform explain -CheckSource": (
        ["transform", "explain", "-CheckSource"],
        [
            SERVICES,
            _job("transform-explain", "--connection", "tally-test", "--check-source"),
            WATCH_JOB,
        ],
    ),  # fmt: skip
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_command_passes_whole_arguments(name: str, tmp_path: Path) -> None:
    argv, expected = CASES[name]
    calls = _calls(tmp_path, *argv)
    for call in calls:
        # Single characters only appear when an argument was split up (`ps` -> `p`, `s`).
        assert all(len(a) > 1 for a in call), call
    # `--job` comes last in the expected lists; dev.ps1 adds it before the entity options.
    assert [sorted(c) for c in calls] == [sorted(c) for c in expected], calls
    assert [c[:3] for c in calls] == [c[:3] for c in expected], calls


def test_a_single_argument_stays_one_argument(tmp_path: Path) -> None:
    """The exact pilot failure: `status` runs `ps` as one argument."""
    calls = _calls(tmp_path, "status")
    assert calls[0] == ["ps"]
