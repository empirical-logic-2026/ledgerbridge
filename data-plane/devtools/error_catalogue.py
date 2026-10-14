"""Generates docs/error-catalogue.md from the problem registry (core/problems.py).

    python -m devtools.error_catalogue            # write the catalogue
    python -m devtools.error_catalogue --check    # exit 1 if it is out of date

The registry is the single source of every code's title, meaning, causes, how to
investigate and how to fix it, so the catalogue always matches what the commands print.
A test fails when the catalogue is stale. `./dev.ps1 diagrams` also regenerates it.

Developer tool (devtools/): never imported by product code.
"""

import argparse
import sys
from pathlib import Path

from core.problems import PROBLEMS, Problem

TARGET = Path(__file__).resolve().parents[2] / "docs" / "error-catalogue.md"

AREAS = (
    ("LB-SYNC", "Sync: fetching from the source"),
    ("LB-TRF", "Transform: converting stored records into the accounting tables"),
    ("LB-VAL", "Validation: our figures against the source's"),
    ("LB-CON", "Connection settings"),
    ("LB-SYS", "The system itself"),
)
SEVERITY = {"error": "Error", "warning": "Warning", "info": "Note"}

HEADER = """# Error catalogue

Every error and warning LedgerBridge reports has a stable code. Commands print the plain
name first, then the technical key and the code in brackets, for example
`Balances at year ends [year_end_mismatch, LB-VAL-006]`. Codes are never reused or
renumbered.

**Generated** from `data-plane/core/problems.py` by `python -m devtools.error_catalogue`
(also run by `./dev.ps1 diagrams`); don't edit this file by hand. A test fails when it is
out of date.

- **Error** (red, FAILED): something is wrong or missing; the overall verdict is FAILED.
- **Warning** (yellow, WARNING): needs attention; the overall verdict is ATTENTION NEEDED.
- **Note**: for information; doesn't change the verdict.

Start with `.\\dev.ps1 report -Env <env>`: it shows the overall verdict, every problem
found with its code, and the next step. **Consequences** name the problems they usually
follow from: when those are found too, fix them first.

Commands below use `-Env <env>`: `test` or `pilot`. Everything printed is counts, dates,
codes and labels such as `entity 3 (company 1)`: never names, values or amounts.
"""


def _entry(p: Problem) -> list[str]:
    out = [
        f"### {p.code}: {p.title}",
        "",
        f"`{p.key}` | {SEVERITY[p.severity]}",
        "",
        f"**What it means:** {p.meaning}",
        "",
    ]
    if p.consequence_of:
        out += [f"**Usually a consequence of:** {', '.join(p.consequence_of)}.", ""]
    for heading, items in (
        ("Common causes", p.causes),
        ("How to investigate", p.investigate),
        ("How to fix", p.fix),
    ):
        if items:
            out.append(f"**{heading}:**")
            out.append("")
            out += [f"- {item.replace('{env}', '<env>')}" for item in items]
            out.append("")
    out += [f"**Next step:** `{p.command('<env>')}`", ""]
    return out


def render() -> str:
    out = HEADER.splitlines() + [""]
    out += ["| Code | Name | Key | Severity |", "| --- | --- | --- | --- |"]
    out += [
        f"| [{p.code}](#{p.code.lower()}-{_anchor(p.title)}) | {p.title} | `{p.key}` | "
        f"{SEVERITY[p.severity]} |"
        for p in PROBLEMS
    ]
    for prefix, title in AREAS:
        out += ["", f"## {title}", ""]
        for p in PROBLEMS:
            if p.code.rsplit("-", 1)[0] == prefix:
                out += _entry(p)
    return "\n".join(out).rstrip() + "\n"


def _anchor(text: str) -> str:
    """GitHub's heading anchor for the part after the code."""
    kept = "".join(c for c in text.lower() if c.isalnum() or c in " -")
    return kept.replace(" ", "-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m devtools.error_catalogue")
    parser.add_argument("--check", action="store_true", help="exit 1 if out of date")
    args = parser.parse_args(argv)
    text = render()
    current = TARGET.read_text(encoding="utf-8").replace("\r\n", "\n") if TARGET.exists() else ""
    if args.check:
        if current != text:
            print(f"{TARGET.name} is out of date: run python -m devtools.error_catalogue")
            return 1
        return 0
    if current != text:
        TARGET.write_text(text, encoding="utf-8", newline="\n")
        print(f"Wrote {TARGET.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
