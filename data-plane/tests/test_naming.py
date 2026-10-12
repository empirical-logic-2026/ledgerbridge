"""Kinds of difference between names, never the names themselves."""

import pytest

from core.naming import characters, differences, features

BASE = "Alpha Traders Limited- New - (from 1-Apr-23)"


@pytest.mark.parametrize(
    ("other", "kinds"),
    [
        (BASE, []),
        (BASE + " ", ["leading/trailing spaces"]),
        (BASE.replace("Traders ", "Traders  "), ["repeated spaces"]),
        (BASE.replace(" ", "\u00a0", 1), ["unusual space characters (e.g. non-breaking space)"]),
        (BASE.upper(), ["letter case"]),
        (BASE.replace("- New", "\u2013 New"), ["dash characters (e.g. en dash instead of hyphen)"]),
        (BASE.replace("Limited- New", "Limited - New"), ["spacing around hyphens"]),
        (BASE.replace("(from", "( from"), ["spacing around brackets"]),
        (BASE.replace(" (from 1-Apr-23)", ""), ["a bracketed suffix such as '(from 1-Apr-23)'"]),
        ("Ltd -(from 1-Apr-20)", None),
    ],
)
def test_differences(other: str, kinds: list[str] | None) -> None:
    assert differences(BASE, other) == kinds


def test_several_kinds_at_once() -> None:
    other = " " + BASE.replace("Limited- New", "LIMITED - New") + " "
    assert differences(BASE, other) == [
        "leading/trailing spaces",
        "letter case",
        "spacing around hyphens",
    ]


def test_features_and_characters() -> None:
    assert features(BASE) == []
    assert features(" Beta  Co\u2013x ") == [
        "starts or ends with a space",
        "repeated spaces",
        "characters outside plain ASCII: U+2013 EN DASH",
    ]
    assert characters("a\u00a0b") == ["U+00A0 NO-BREAK SPACE"]
