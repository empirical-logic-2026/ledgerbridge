"""Colours for terminal output, with a plain fallback (source-independent).

Output is always plain text whose status words carry the meaning on their own (OK, PASSED,
ATTENTION NEEDED, WARNING, FAILED, better, worse), so nothing is lost without colour.
When colours are on, those words are coloured as they are printed: green for good, yellow
for attention, red for failures.

Colours are on only when the caller asks with LB_COLOR=1 (dev.ps1 sets it when its
terminal supports colours, and never when the output is redirected) and NO_COLOR isn't set
(https://no-color.org). Inside `docker compose exec -T` the output is a pipe, so this
process can't tell by itself. Background jobs never colour what they write to sync_logs:
`watch` colours the lines when it prints them.
"""

import os
import re
import sys
from typing import TextIO

GREEN, YELLOW, RED, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[0m"

_WORDS = (
    (re.compile(r"\b(OK|PASSED|SUCCEEDED|better|fixed)\b"), GREEN),
    (
        re.compile(r"\b(ATTENTION NEEDED|WARNING|INTERRUPTED|RUNNING|UNVERIFIED|NOT VALIDATED)\b"),
        YELLOW,
    ),
    (re.compile(r"\b(FAILED|ERROR|worse|ROOT CAUSE)\b"), RED),
)


def enabled() -> bool:
    return os.environ.get("LB_COLOR") == "1" and "NO_COLOR" not in os.environ


def colorize(text: str) -> str:
    """Status words in colour. ATTENTION NEEDED is matched before its parts."""
    for pattern, colour in _WORDS:
        text = pattern.sub(lambda m, c=colour: f"{c}{m.group(0)}{RESET}", text)  # type: ignore[misc]
    return text


def plain(text: str) -> str:
    """Without colour codes (for files and the database)."""
    return re.sub(r"\033\[\d+m", "", text)


class ColorStream:
    """Wraps stdout or stderr, colouring status words as they are written."""

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream

    def write(self, text: str) -> int:
        self.stream.write(colorize(text))
        return len(text)

    def flush(self) -> None:
        self.stream.flush()

    def __getattr__(self, name: str) -> object:
        return getattr(self.stream, name)


def install() -> None:
    """Colour stdout and stderr when colours are on."""
    if enabled():
        for name in ("stdout", "stderr"):
            setattr(sys, name, ColorStream(getattr(sys, name)))
