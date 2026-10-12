"""The repository's PowerShell scripts have no control characters or backslashes inside
string literals.

A path written as 'deploy\\new-env.ps1' by a tool that interprets escapes ends up with a
newline in the middle of the literal, and PowerShell then can't find the script. Paths are
built with Join-Path instead, so no literal needs a backslash at all.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = sorted(
    p for p in [*REPO.glob("*.ps1"), *REPO.glob("deploy/**/*.ps1")] if "node_modules" not in p.parts
)


def string_literals(source: str) -> list[tuple[int, str]]:
    """(line, content) of every ordinary '...' and "..." literal. Comments (# and <# #>)
    and here-strings (@'...'@, @"..."@) are skipped: they may span lines."""
    literals: list[tuple[int, str]] = []
    i, line, n = 0, 1, len(source)
    while i < n:
        c = source[i]
        if c == "\n":
            line += 1
            i += 1
        elif source.startswith("<#", i):
            end = source.find("#>", i + 2)
            end = n if end < 0 else end + 2
            line += source.count("\n", i, end)
            i = end
        elif c == "#":
            end = source.find("\n", i)
            i = n if end < 0 else end
        elif source.startswith(("@'", '@"'), i) and source[i + 2 : i + 4].lstrip(" \t")[:1] in (
            "\r",
            "\n",
        ):
            closing = "\n" + source[i + 1] + "@"
            end = source.find(closing, i + 2)
            end = n if end < 0 else end + len(closing)
            line += source.count("\n", i, end)
            i = end
        elif c in "'\"":
            start, j, text = line, i + 1, []
            while j < n:
                ch = source[j]
                if c == '"' and ch == "`" and j + 1 < n:  # backtick escape
                    text.append(source[j : j + 2])
                    j += 2
                    continue
                if ch == c:
                    if j + 1 < n and source[j + 1] == c:  # '' or "" inside the literal
                        text.append(ch)
                        j += 2
                        continue
                    break
                text.append(ch)
                j += 1
            content = "".join(text)
            literals.append((start, content))
            line += content.count("\n")
            i = j + 1
        else:
            i += 1
    return literals


def test_scripts_are_found() -> None:
    names = {p.relative_to(REPO).as_posix() for p in SCRIPTS}
    assert {"dev.ps1", "deploy/stack.ps1", "deploy/new-env.ps1"} <= names


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.relative_to(REPO).as_posix())
def test_no_control_characters_or_backslashes_in_string_literals(script: Path) -> None:
    source = script.read_text(encoding="utf-8").replace("\r\n", "\n")
    problems = [
        f"line {line}: {content[:60]!r}"
        for line, content in string_literals(source)
        if "\\" in content or any(ord(ch) < 32 and ch != "\t" for ch in content)
    ]
    assert problems == [], "build paths with Join-Path; no escapes in literals"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("$a = 'deploy\nnew-env.ps1'", ["deploy\nnew-env.ps1"]),  # the original bug
        ("$a = 'C:\\x'  # 'not \\ this'", ["C:\\x"]),
        ("$a = \"it`\"s\"; $b = 'it''s'", ['it`"s', "it's"]),
        ("$a = @'\nmulti\nline\n'@\n$b = 'x'", ["x"]),
        ("<# 'in a comment' #>\n$b = \"y\"", ["y"]),
    ],
)
def test_lexer(source: str, expected: list[str]) -> None:
    assert [content for _, content in string_literals(source)] == expected
