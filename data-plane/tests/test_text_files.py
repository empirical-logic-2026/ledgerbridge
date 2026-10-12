"""Every text file in the repository is free of unintended control and invisible characters.

They are what a mis-written escape sequence leaves behind: a tool that interprets "\\n",
"\\t", "\\b" or "\\u200b" while writing a file puts a real newline, tab, backspace or
zero-width space where the escape was meant (dev.ps1's 'deploy<newline>ew-env.ps1',
2026-10-12). Such characters are invisible in an editor and change what the code does.

Rules, for every tracked or new (not ignored) file that isn't binary:
- valid UTF-8, without a byte-order mark;
- no control characters except newline, and carriage return directly before a newline;
  tabs only in shell scripts (a `<<-` heredoc strips leading tabs, so they're needed);
- no invisible or direction-changing Unicode characters (no-break space, soft hyphen,
  zero-width characters, byte-order mark, line/paragraph separators, bidirectional
  controls): write them as escapes, e.g. "\\u00a0".

A newline inside a string literal looks like an ordinary line break at file level: for
PowerShell that is checked by tests/test_scripts.py (string literals may not contain
control characters or backslashes); in Python it is a syntax error.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GIT = shutil.which("git")
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".woff", ".woff2", ".pdf"}
TABS_ALLOWED = {".sh"}
INVISIBLE = {
    0x00A0: "NO-BREAK SPACE",
    0x00AD: "SOFT HYPHEN",
    0x200B: "ZERO WIDTH SPACE",
    0x200C: "ZERO WIDTH NON-JOINER",
    0x200D: "ZERO WIDTH JOINER",
    0x200E: "LEFT-TO-RIGHT MARK",
    0x200F: "RIGHT-TO-LEFT MARK",
    0x2028: "LINE SEPARATOR",
    0x2029: "PARAGRAPH SEPARATOR",
    **{c: "BIDIRECTIONAL CONTROL" for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))},
    **{c: "INVISIBLE OPERATOR / WORD JOINER" for c in range(0x2060, 0x2065)},
    0xFEFF: "BYTE ORDER MARK / ZERO WIDTH NO-BREAK SPACE",
}


def repo_files() -> list[Path]:
    out = subprocess.run(  # noqa: S603 - fixed arguments, no shell
        [str(GIT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPO,
        capture_output=True,
        check=True,
    ).stdout
    return sorted({REPO / name for name in out.decode("utf-8").split("\0") if name})


def problems(path: Path, data: bytes) -> list[str]:
    """Each unintended character as 'line L, column C: U+XXXX NAME'."""
    if data.startswith(b"\xef\xbb\xbf"):
        return ["starts with a UTF-8 byte-order mark"]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"not valid UTF-8 at byte {exc.start}"]
    found = []
    line, column = 1, 0
    for index, char in enumerate(text):
        column += 1
        code = ord(char)
        if char == "\n":
            line, column = line + 1, 0
            continue
        if char == "\r" and text[index + 1 : index + 2] == "\n":
            continue
        if char == "\t" and path.suffix in TABS_ALLOWED:
            continue
        if code < 0x20 or 0x7F <= code <= 0x9F:
            found.append(f"line {line}, column {column}: control character U+{code:04X}")
        elif code in INVISIBLE:
            found.append(f"line {line}, column {column}: U+{code:04X} {INVISIBLE[code]}")
    return found


def _is_binary(path: Path, data: bytes) -> bool:
    return path.suffix.lower() in BINARY_SUFFIXES or b"\0" in data[:8192]


@pytest.mark.skipif(GIT is None, reason="needs git")
def test_every_text_file_is_clean() -> None:
    files = repo_files()
    assert len(files) > 50  # really scanning the repository
    report = {}
    for path in files:
        if not path.is_file():
            continue  # deleted in the working tree
        data = path.read_bytes()
        if _is_binary(path, data):
            continue
        found = problems(path, data)
        if found:
            report[path.relative_to(REPO).as_posix()] = found[:5]
    assert report == {}, "write these characters as escape sequences (e.g. \\u00a0) or remove them"


@pytest.mark.parametrize(
    ("name", "content", "expected"),
    [
        ("ok.py", "x = 'a\\tb'  # escapes are fine\r\n", []),
        # mis-written paths: Python\\bin and deploy\\tools with their escapes interpreted
        (
            "bug.ps1",
            "$p = 'Python\bin\\python.exe'\n",
            ["line 1, column 13: control character U+0008"],
        ),
        ("bug.yaml", "path: deploy\tools\n", ["line 1, column 13: control character U+0009"]),
        ("tab.py", "x = 'a\tb'\n", ["control character U+0009"]),
        ("tab.sh", "cat <<-EOF\n\tindented\nEOF\n", []),
        ("bell.md", "ring\a\n", ["control character U+0007"]),
        ("nbsp.py", "x = 'a\u00a0b'\n", ["U+00A0 NO-BREAK SPACE"]),
        ("zw.md", "a\u200bb\n", ["U+200B ZERO WIDTH SPACE"]),
        ("bom.py", "\ufeffx = 1\n", ["starts with a UTF-8 byte-order mark"]),
        ("lone-cr.txt", "a\rb\n", ["control character U+000D"]),
        ("ok.md", "dash \u2013 and arrow \u2192 are fine\n", []),
    ],
)
def test_problems(name: str, content: str, expected: list[str]) -> None:
    found = problems(Path(name), content.encode("utf-8"))
    assert len(found) == len(expected)
    for got, want in zip(found, expected, strict=True):
        assert want in got
