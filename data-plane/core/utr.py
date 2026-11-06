"""Finding a bank transfer's UTR (unique transaction reference) in text a source keeps, without
mistaking anything else for one. Source-independent and pure; tested in tests/test_utr.py.

A UTR is taken only when it looks like one:

- **NEFT / RTGS:** four letters (the bank's IFSC prefix), N or R, then 10 to 17 letters or
  digits (e.g. HDFCN52026100112345);
- **IMPS / UPI:** exactly 12 digits (e.g. 629012345678);
- **labelled:** a value written after "UTR" (e.g. "UTR: 1234ABCD5678"), 8 to 30 letters or
  digits.

A source's own generated identifiers (Tally's UNIQUEREFERENCENUMBER, a random code) are never
read as a UTR.
"""

import re

NEFT_RTGS = re.compile(r"[A-Z]{4}[NR][A-Z0-9]{10,17}")
IMPS_UPI = re.compile(r"\d{12}")
_LABELLED = re.compile(r"\bUTR\s*(?:NO\.?|NUMBER)?\s*[:#\-.]?\s*([A-Z0-9]{8,30})\b", re.IGNORECASE)
_IN_TEXT = re.compile(r"(?<![A-Z0-9])([A-Z]{4}[NR][A-Z0-9]{10,17}|\d{12})(?![A-Z0-9])")


def as_utr(value: str | None) -> str | None:
    """The value itself when it is a UTR (a whole NEFT/RTGS or IMPS/UPI reference), else None."""
    if not value:
        return None
    text = value.strip().upper()
    if NEFT_RTGS.fullmatch(text) or IMPS_UPI.fullmatch(text):
        return text
    labelled = _LABELLED.fullmatch(text) or _LABELLED.search(text)
    return labelled.group(1).upper() if labelled else None


def in_text(text: str | None) -> str | None:
    """The UTR written in free text (a narration): a labelled one first, else the first value
    of either format standing on its own."""
    if not text:
        return None
    labelled = _LABELLED.search(text)
    if labelled:
        return labelled.group(1).upper()
    found = _IN_TEXT.search(text.upper())
    return found.group(1) if found else None
