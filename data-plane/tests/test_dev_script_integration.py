"""`./dev.ps1 reset` and `sync abandon` refuse unless asked properly (test environment only;
never pilot).

Runs dev.ps1 through Windows PowerShell; skipped elsewhere.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

POWERSHELL = shutil.which("powershell")
DOCKER = shutil.which("docker")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (POWERSHELL and DOCKER), reason="needs Windows PowerShell and Docker"),
]

REPO = Path(__file__).resolve().parents[2]


def _dev(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed arguments, no shell
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            # For this child process only, so the test doesn't depend on how pytest was started.
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO / "dev.ps1"),
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _test_volumes() -> list[str]:
    out = subprocess.run(  # noqa: S603 - fixed arguments, no shell
        [
            str(DOCKER),
            "volume",
            "ls",
            "--quiet",
            "--filter",
            "label=com.docker.compose.project=ledgerbridge-test",
        ],  # fmt: skip
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(out.split())


def test_reset_of_test_needs_force() -> None:
    result = _dev("reset", "-Env", "test", "-Confirmation", "delete test")
    assert result.returncode != 0
    assert "add -Force" in result.stdout + result.stderr


def test_reset_needs_the_exact_confirmation() -> None:
    before = _test_volumes()
    result = _dev("reset", "-Env", "test", "-Force", "-Confirmation", "delete pilot")
    assert result.returncode == 2
    assert "nothing was deleted" in result.stdout
    assert _test_volumes() == before


def test_sync_abandon_needs_the_exact_confirmation() -> None:
    result = _dev("sync", "abandon", "-Env", "test", "-Confirmation", "yes")
    assert result.returncode == 2
    assert "Not confirmed: nothing changed." in result.stdout
