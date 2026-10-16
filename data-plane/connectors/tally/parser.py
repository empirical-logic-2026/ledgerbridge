"""Splits Tally XML responses into one record per object."""

import re
import xml.etree.ElementTree as ET  # noqa: N817
from collections.abc import Callable, Iterator
from datetime import date, datetime

from connectors.base import SourceEntity, SourceRecord
from connectors.tally.client import TallyError, decode_response
from connectors.tally.envelopes import CollectionSpec

_CHAR_REF = re.compile(r"&#(x[0-9a-fA-F]+|[0-9]+);")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _valid_xml_char(code: int) -> bool:
    return (
        code in (0x9, 0xA, 0xD)
        or 0x20 <= code <= 0xD7FF
        or 0xE000 <= code <= 0xFFFD
        or 0x10000 <= code <= 0x10FFFF
    )


def sanitize(text: str) -> str:
    """Remove characters XML 1.0 forbids. Tally emits some (e.g. `&#4;`) in names and narrations."""

    def replace(match: re.Match[str]) -> str:
        ref = match.group(1)
        code = int(ref[1:], 16) if ref[0] == "x" else int(ref)
        return match.group(0) if _valid_xml_char(code) else ""

    return _CONTROL_CHARS.sub("", _CHAR_REF.sub(replace, text))


# Names with a namespace prefix Tally doesn't declare: TDL customisations export
# user-defined fields such as <UDF:FIELD>, which a namespace-aware parser rejects ("unbound
# prefix"). Inside tags only, such names are rewritten as PREFIX<MARK>LOCAL before parsing and
# written back when a payload is stored, so payloads keep their original names (pilot
# 2026-10-13). The mark is a middle dot: valid inside XML names, never in Tally's own.
_MARK = chr(0x00B7)
PREFIX_MARK = _MARK  # in element names that had a prefix
_TAG = re.compile(r"<(/?)([^\s/>!?]+)([^>]*)>")
_ATTR = re.compile(r"(\s+)([^\s=/>]+)(\s*=\s*)(\"[^\"]*\"|'[^']*')")
_RESERVED_PREFIXES = {"xml", "xmlns"}
_PREFIXED_ELEMENT = re.compile(r"</?([A-Za-z_][\w.-]*):[A-Za-z_]")


def undeclared_prefixes(body: bytes) -> set[str]:
    """Names of the prefixes used in a response's element names (e.g. UDF): names only."""
    text = decode_response(body)
    if ":" not in text:
        return set()
    return {p for p in _PREFIXED_ELEMENT.findall(text) if p not in _RESERVED_PREFIXES}


def _rename(name: str) -> str:
    prefix, colon, local = name.partition(":")
    if not colon or prefix in _RESERVED_PREFIXES or not local:
        return name
    return f"{prefix}{_MARK}{local}"


def restore_name(name: str) -> str:
    """A parsed element's name as the source wrote it (UDF:FIELD, not the internal form)."""
    return _restore(name)


def _restore(name: str) -> str:
    return name.replace(_MARK, ":", 1) if _MARK in name else name


def _rewrite_tags(text: str, rename: Callable[[str], str]) -> str:
    def tag(match: re.Match[str]) -> str:
        closing, name, rest = match.groups()
        rest = _ATTR.sub(lambda a: a[1] + rename(a[2]) + a[3] + a[4], rest)
        return f"<{closing}{rename(name)}{rest}>"

    return _TAG.sub(tag, text)


_PREFIXED_ATTRIBUTE = re.compile(r"\s[A-Za-z_][\w.-]*:[\w.-]+\s*=\s*[\"']")


def neutralise_prefixes(text: str) -> str:
    """Undeclared prefixed names (e.g. UDF:FIELD) made parseable; see _MARK. Responses
    without any prefixed name (most) are returned as they are, without rewriting."""
    if ":" not in text or not (_PREFIXED_ELEMENT.search(text) or _PREFIXED_ATTRIBUTE.search(text)):
        return text
    return _rewrite_tags(text, _rename)


def parse_response(body: bytes) -> ET.Element:
    text = neutralise_prefixes(sanitize(decode_response(body)))
    # Drop any XML declaration: the text is already decoded.
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    try:
        # Local, trusted source; Python's expat limits entity expansion.
        root = ET.fromstring(text)  # noqa: S314
    except ET.ParseError as exc:
        raise TallyError(f"Tally response is not valid XML ({exc})") from exc
    error = root.findtext(".//LINEERROR")
    if error:
        raise TallyError(f"Tally reported an error: {error.strip()[:200]}")
    if root.tag == "RESPONSE":
        raise TallyError(f"Tally rejected the request: {(root.text or '').strip()[:200]}")
    return root


def objects(root: ET.Element, tag: str) -> list[ET.Element]:
    """Top-level objects of one type in a collection export.

    Only direct children of COLLECTION count: Tally also puts per-type count elements such as
    <CMPINFO><VOUCHER>0</VOUCHER></CMPINFO> in the response, which are not objects.
    """
    collections = list(root.iter("COLLECTION"))
    if collections:
        return [child for collection in collections for child in collection if child.tag == tag]
    return [element for element in root.iter(tag) if len(element)]


def text_of(element: ET.Element, tag: str) -> str | None:
    value = element.findtext(tag)
    return value.strip() if value is not None and value.strip() else None


def tally_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y%m%d").date()
    except ValueError:
        return None


def object_name(element: ET.Element) -> str | None:
    return text_of(element, "NAME") or element.get("NAME")


def source_key(element: ET.Element) -> str:
    key = text_of(element, "GUID") or element.get("REMOTEID")
    if not key:
        raise TallyError(f"{element.tag} without GUID in Tally response")
    return key


def alter_id(element: ET.Element) -> int | None:
    value = text_of(element, "ALTERID")
    return int(value) if value and value.lstrip("-").isdigit() else None


def payload(element: ET.Element) -> str:
    """The object's XML as received, with any prefixed names as Tally wrote them."""
    element.tail = None
    text = ET.tostring(element, encoding="unicode")
    return _rewrite_tags(text, _restore) if _MARK in text else text


def exact_name(element: ET.Element) -> str | None:
    """The NAME exactly as Tally reports it, spaces included (None if blank).

    Company names go back to Tally in SVCURRENTCOMPANY, which must match exactly: a name
    with a trailing or double space must not be tidied (pilot run, 2026-10-12).
    """
    value = element.findtext("NAME")
    if value is None or not value.strip():
        value = element.get("NAME")
    return value if value is not None and value.strip() else None


def parse_companies(body: bytes) -> list[SourceEntity]:
    entities = []
    for element in objects(parse_response(body), "COMPANY"):
        name = exact_name(element)
        if not name:
            continue
        entities.append(
            SourceEntity(
                key=source_key(element),
                name=name,
                books_from=tally_date(text_of(element, "BOOKSFROM"))
                or tally_date(text_of(element, "STARTINGFROM")),
                books_to=tally_date(text_of(element, "ENDINGAT")),
            )
        )
    return entities


def parse_records(
    body: bytes,
    spec: CollectionSpec,
    entity_key: str,
    period: tuple[date, date] | None = None,
) -> Iterator[SourceRecord]:
    """With `period`, only objects dated within it (inclusive). TallyPrime in Educational mode
    answers a request for part of a month with everything from the start of the books: the
    request's dates are a request, the objects' own dates decide (checked 2026-10-12)."""
    for element in objects(parse_response(body), spec.object_tag):
        if period is not None:
            dated = tally_date(text_of(element, "DATE"))
            if dated is not None and not period[0] <= dated <= period[1]:
                continue
        yield SourceRecord(
            source_entity_key=entity_key,
            object_type=spec.object_type,
            source_key=source_key(element),
            source_alter_id=alter_id(element),
            payload_format="xml",
            payload=payload(element),
        )
