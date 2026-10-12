"""Describing how two names differ, without showing them (pilot diagnostics).

`differences(a, b)` names the kinds of difference between two names, such as "repeated
spaces" or "spacing around hyphens", by normalising both step by step until they match.
`features(name)` lists what's unusual about one name. Neither ever returns the names or
any part of them, only kinds, counts and Unicode character names.
"""

import re
import unicodedata
from collections.abc import Callable
from difflib import SequenceMatcher

_UNUSUAL_SPACES = re.compile(r"[\t\u00a0\u1680\u2000-\u200b\u202f\u205f\u3000\ufeff]")
_DASHES = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe63\uff0d"})

# Applied in order, each on top of the previous ones.
STEPS: list[tuple[str, Callable[[str], str]]] = [
    ("leading/trailing spaces", str.strip),
    ("unusual space characters (e.g. non-breaking space)", lambda s: _UNUSUAL_SPACES.sub(" ", s)),
    ("repeated spaces", lambda s: re.sub(r" {2,}", " ", s)),
    ("letter case", str.casefold),
    ("dash characters (e.g. en dash instead of hyphen)", lambda s: s.translate(_DASHES)),
    ("spacing around hyphens", lambda s: re.sub(r"\s*-\s*", "-", s)),
    ("spacing around brackets", lambda s: re.sub(r"\s*([()\[\]])\s*", r"\1", s)),
    ("dots", lambda s: s.replace(".", "")),
    ("a bracketed suffix such as '(from 1-Apr-23)'", lambda s: re.sub(r"\([^()]*\)$", "", s)),
    ("other punctuation", lambda s: re.sub(r"[^\w ]", "", s)),
]


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def differences(a: str, b: str) -> list[str] | None:
    """Kinds of difference between two names: [] if identical, None if they still differ
    after every normalisation (not the same name written differently)."""
    if a == b:
        return []
    kinds = []
    for label, step in STEPS:
        a2, b2 = step(a), step(b)
        if (a2, b2) != (a, b) and (a2 == b2 or _similarity(a2, b2) > _similarity(a, b)):
            kinds.append(label)
        a, b = a2, b2
        if a == b:
            return kinds
    return None


def characters(name: str) -> list[str]:
    """Unicode names of the characters outside plain ASCII, e.g. 'U+2013 EN DASH'."""
    seen = dict.fromkeys(c for c in name if ord(c) > 126 or (ord(c) < 32))
    return [f"U+{ord(c):04X} {unicodedata.name(c, 'UNNAMED')}" for c in seen]


def features(name: str) -> list[str]:
    """What's unusual about a name (kinds only)."""
    found = []
    if name != name.strip():
        found.append("starts or ends with a space")
    if "  " in name:
        found.append("repeated spaces")
    if _UNUSUAL_SPACES.search(name):
        found.append("unusual space characters")
    unusual = characters(name)
    if unusual:
        found.append("characters outside plain ASCII: " + ", ".join(unusual))
    return found
