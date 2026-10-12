"""Splits Tally XML responses into one record per object."""

import re
import xml.etree.ElementTree as ET  # noqa: N817
from collections.abc import Iterator
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


def parse_response(body: bytes) -> ET.Element:
    text = sanitize(decode_response(body))
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
    element.tail = None
    return ET.tostring(element, encoding="unicode")


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
