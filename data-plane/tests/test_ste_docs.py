"""The documents written in ASD-STE100 Simplified Technical English keep its sentence lengths:
a procedural sentence (a numbered step) has 20 words at most, a descriptive sentence 25
(docs/formula-sheet.md, docs/dashboard-pages.md). Needs no database.

Text is read line by line and table cell by table cell; code (in backticks or fenced) counts
as one word; a link counts as its text. A word is a token with a letter or a digit in it.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / "docs" / "formula-sheet.md", ROOT / "docs" / "dashboard-pages.md"]
PROCEDURAL, DESCRIPTIVE = 20, 25

_CODE = re.compile(r"`[^`]*`")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_STEP = re.compile(r"(?:^|\s)(\d+)\.\s+(?=\S)")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"(“])")
_WORD = re.compile(r"[A-Za-z0-9₹]")


def _pieces(path: Path) -> list[tuple[int, str]]:
    """(line number, text) of every line or table cell outside fenced code."""
    found: list[tuple[int, str]] = []
    fenced = False
    for number, line in enumerate(path.read_text("utf-8").splitlines(), 1):
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced or not line.strip() or re.fullmatch(r"\|?[\s|:-]+\|?", line):
            continue
        text = _LINK.sub(r"\1", _CODE.sub("CODE", line)).lstrip("#").strip()
        cells = [c.strip() for c in text.strip("|").split("|")] if text.startswith("|") else [text]
        found.extend((number, cell) for cell in cells if cell)
    return found


def _sentences(text: str) -> list[tuple[bool, str]]:
    """(procedural, sentence): the text split into its numbered steps, then into sentences."""
    text = re.sub(r"^[-*]\s+", "", text)
    steps = _STEP.split(text)
    found: list[tuple[bool, str]] = [(False, s) for s in _SENTENCE_END.split(steps[0]) if s.strip()]
    for step in steps[2::2]:  # the text after each step number
        found.extend((True, s) for s in _SENTENCE_END.split(step) if s.strip())
    return found


def _words(sentence: str) -> int:
    return sum(1 for token in sentence.split() if _WORD.search(token))


def _too_long(path: Path) -> list[str]:
    found = []
    for number, text in _pieces(path):
        for procedural, sentence in _sentences(text):
            limit = PROCEDURAL if procedural else DESCRIPTIVE
            if (count := _words(sentence)) > limit:
                kind = "procedural" if procedural else "descriptive"
                found.append(f"{path.name}:{number}: {count} words > {limit} ({kind}): {sentence}")
    return found


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_sentences_keep_the_ste_lengths(path: Path) -> None:
    too_long = _too_long(path)
    assert not too_long, "\n".join(too_long)


def test_the_check_counts_steps_and_sentences() -> None:
    steps = _sentences("1. Open the report. 2. Set the period (F2). 3. Read the total.")
    assert steps == [
        (True, "Open the report."),
        (True, "Set the period (F2)."),
        (True, "Read the total."),
    ]
    assert _sentences("A short text. It has two sentences.") == [
        (False, "A short text."),
        (False, "It has two sentences."),
    ]
    assert _words("Divide CODE by ₹1,00,000 — then stop.") == 6  # the dash is no word


# Every page section of docs/dashboard-pages.md has the text of the note at the top of its page
# (the page's own note: shell/pageNotes.ts in the frontend).
PAGE_SECTIONS = [
    "## 2. Overview", "### 3.1 Sales dashboard", "### 3.2 Sales register", "### 3.3 Monthly sales",
    "### 3.4 Channels", "### 3.5 Customers and the page of a customer", "## 4. Purchases",
    "### 5.1 Profit & Loss", "### 5.2 Cost centres", "## 6. Balance Sheet", "### 7.1 Stock summary",
    "### 7.2 By godown", "### 7.3 Page of an item", "## 8. Cash Flow", "## 9. Parties",
    "### 10.1 Transactions", "### 10.2 Page of a voucher", "### 11.1 Data health and Companies",
    "### 11.2 Explore",
]  # fmt: skip


@pytest.mark.parametrize("heading", PAGE_SECTIONS)
def test_every_page_section_has_its_note(heading: str) -> None:
    text = (ROOT / "docs" / "dashboard-pages.md").read_text("utf-8")
    start = text.index(heading + "\n")
    ends = [i for i in (text.find("\n## ", start + 1), text.find("\n### ", start + 1)) if i != -1]
    section = text[start : min(ends)]
    assert "**Note at the top of the page.**" in section, heading
