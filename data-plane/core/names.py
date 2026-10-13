"""Resolving references by name (source-independent; ADR-027).

Sources such as Tally refer to masters by name (a ledger's group, a voucher's ledgers, cost
centres, stock items). A reference is resolved by these rules, in order:

1. **exact**: the name as the source wrote it;
2. **alias**: another name the target is known by (e.g. the reserved name of a Tally group
   the user renamed, or a ledger alias), only if exactly one target has it;
3. **normalised**: both sides normalised the same way (`normalise`: XML entities decoded,
   Unicode NFC, every kind of space as one space, trimmed, case folded), only if exactly
   one target matches. A normalised match is reported as a warning (kinds only).

Anything else does not resolve: no match, or several candidates (ambiguous). Look-alike
characters and punctuation are never matched automatically; `differences` names them for
the diagnostic (`transform explain`) only.
"""

import difflib
import html
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

EXACT, ALIAS, NORMALISED = "exact", "alias", "normalised"
_SPACES = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[\W_]+")
# Characters that look like ASCII letters or signs (a small, common set).
_LOOK_ALIKES = {
    chr(0x0430): "a", chr(0x0435): "e", chr(0x043E): "o", chr(0x0440): "p", chr(0x0441): "c",
    chr(0x0443): "y", chr(0x0445): "x", chr(0x0410): "A", chr(0x0412): "B", chr(0x0415): "E",
    chr(0x041A): "K", chr(0x041C): "M", chr(0x041D): "H", chr(0x041E): "O", chr(0x0420): "P",
    chr(0x0421): "C", chr(0x0422): "T", chr(0x0425): "X", chr(0x2010): "-", chr(0x2011): "-",
    chr(0x2012): "-", chr(0x2013): "-", chr(0x2014): "-", chr(0x2212): "-", chr(0x2018): "'",
    chr(0x2019): "'", chr(0x201C): '"', chr(0x201D): '"', chr(0xFF06): "&", chr(0x00B4): "'",
}  # fmt: skip


def _unescape(text: str) -> str:
    """Entities decoded until stable (`&amp;amp;` -> `&`)."""
    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text


def normalise(name: str) -> str:
    """The form both sides are compared in when an exact match fails."""
    text = unicodedata.normalize("NFC", _unescape(name))
    return _SPACES.sub(" ", text).strip().casefold()


def _look_alike(text: str) -> str:
    return "".join(_LOOK_ALIKES.get(c, c) for c in unicodedata.normalize("NFKC", text))


def differences(referenced: str, candidate: str) -> list[str]:
    """Kinds of difference between two names (never the names): leading/trailing spaces,
    double spaces, case, XML entities, Unicode normalisation, look-alike characters,
    punctuation, other."""
    if referenced == candidate:
        return []
    kinds = []
    if referenced != referenced.strip() or candidate != candidate.strip():
        kinds.append("leading/trailing spaces")
    if "  " in referenced or "  " in candidate or re.search(r"[^\S ]", referenced + candidate):
        kinds.append("double or unusual spaces")
    if _unescape(referenced) != referenced or _unescape(candidate) != candidate:
        kinds.append("XML entities")
    if (
        unicodedata.normalize("NFC", referenced) != referenced
        or unicodedata.normalize("NFC", candidate) != candidate
    ):
        kinds.append("Unicode normalisation")
    a, b = normalise(referenced), normalise(candidate)
    if a == b:
        flat = lambda s: _SPACES.sub(" ", unicodedata.normalize("NFC", _unescape(s))).strip()  # noqa: E731
        if flat(referenced) != flat(candidate):
            kinds.append("case")
        return kinds or ["other"]
    if _look_alike(a) == _look_alike(b):
        return [*kinds, "look-alike characters"]
    if _PUNCTUATION.sub("", _look_alike(a)) == _PUNCTUATION.sub("", _look_alike(b)):
        return [*kinds, "punctuation"]
    return [*kinds, "other"]


def close_match(referenced: str, candidates: Iterable[str]) -> tuple[str | None, list[str]]:
    """The closest candidate if it differs only slightly (look-alikes, punctuation or a
    ratio of at least 0.9), and the kinds of difference; (None, []) otherwise."""
    target = _PUNCTUATION.sub("", _look_alike(normalise(referenced)))
    best, best_ratio = None, 0.0
    for candidate in candidates:
        other = _PUNCTUATION.sub("", _look_alike(normalise(candidate)))
        if other == target:
            return candidate, differences(referenced, candidate)
        ratio = difflib.SequenceMatcher(None, target, other).ratio()
        if ratio > best_ratio:
            best, best_ratio = candidate, ratio
    if best is not None and best_ratio >= 0.9:
        return best, differences(referenced, best)
    return None, []


@dataclass(frozen=True)
class Resolution:
    value: Any = None
    how: str | None = None  # exact / alias / normalised; None when unresolved
    ambiguous: bool = False

    @property
    def found(self) -> bool:
        return self.how is not None


class NameIndex:
    """Targets by name, alias and normalised name; resolves references by the rules above."""

    def __init__(self) -> None:
        self.exact: dict[str, Any] = {}
        self.aliases: dict[str, set[Any]] = defaultdict(set)
        self.normalised: dict[str, set[Any]] = defaultdict(set)

    @classmethod
    def build(
        cls, entries: Iterable[tuple[str, Any]], aliases: Iterable[tuple[str, Any]] = ()
    ) -> "NameIndex":
        index = cls()
        for name, value in entries:
            index.add(name, value)
        for alias, value in aliases:
            index.add_alias(alias, value)
        return index

    def add(self, name: str, value: Any) -> None:
        self.exact[name] = value
        self.normalised[normalise(name)].add(value)

    def add_alias(self, alias: str, value: Any) -> None:
        if alias:
            self.aliases[alias].add(value)
            self.normalised[normalise(alias)].add(value)

    def resolve(self, name: str | None) -> Resolution:
        if name is None:
            return Resolution()
        if name in self.exact:
            return Resolution(self.exact[name], EXACT)
        by_alias = self.aliases.get(name, set())
        if len(by_alias) == 1 and name not in self.exact:
            return Resolution(next(iter(by_alias)), ALIAS)
        if len(by_alias) > 1:
            return Resolution(ambiguous=True)
        candidates = self.normalised.get(normalise(name), set())
        if len(candidates) == 1:
            return Resolution(next(iter(candidates)), NORMALISED)
        return Resolution(ambiguous=len(candidates) > 1)

    def get(self, name: str | None) -> Any:
        """The resolved value or None (any rule)."""
        return self.resolve(name).value

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.resolve(name).found

    def __len__(self) -> int:
        return len(self.exact)

    def names(self) -> list[str]:
        return list(self.exact)
