"""No source file is ignored by git. The root .gitignore keeps private output out of git
(`reports/`, `backups/`); a source folder with such a name would silently never be committed
(D1 b, 2026-10-31: `frontend/src/apps/reports/` passed every local check and was missing in
CI). Skipped where git isn't available."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GIT = shutil.which("git")
SOURCE_DIRS = [
    REPO / "frontend" / "src",
    *(
        REPO / "data-plane" / d
        for d in ("api", "core", "connectors", "workers", "devtools", "migrations", "tests")
    ),
]
SKIP_PARTS = {"__pycache__", ".pytest_cache", "node_modules"}


@pytest.mark.skipif(
    GIT is None or not (REPO / ".git").exists(), reason="needs git and the repository"
)
def test_no_source_file_is_ignored_by_git() -> None:
    files = [
        str(path.relative_to(REPO)).replace("\\", "/")
        for folder in SOURCE_DIRS
        if folder.exists()
        for path in folder.rglob("*")
        if path.is_file() and not SKIP_PARTS & set(path.parts) and path.suffix != ".pyc"
    ]
    assert files
    done = subprocess.run(  # noqa: S603 - fixed arguments, no shell
        [str(GIT), "check-ignore", "--stdin"],
        input="\n".join(files), capture_output=True, text=True, cwd=REPO, check=False,
    )  # fmt: skip
    ignored = [line for line in done.stdout.splitlines() if line]
    assert ignored == [], f"source files ignored by .gitignore (rename the folder): {ignored}"
