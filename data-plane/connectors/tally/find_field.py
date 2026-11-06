"""Which field of a voucher holds a given text (`./dev.ps1 find-field`): asks Tally for one
voucher with every field and sub-list, and gives the paths of the fields whose value contains
the text, never the values. Nothing is stored or logged. Read-only (Export requests only).

Also the requests behind the full test-company export (devtools/tally_full_export.py):
a collection of one type, each object whole (`NATIVEMETHOD *`) with every field of the named
sub-lists (`<list>.*`). `NATIVEMETHOD *` alone leaves the sub-lists out (2026-11-05), so they
are named: the sub-lists recorded on the test company (voucher_lists.txt) and the connector's,
then any nested list an answer shows, in rounds, until no new one appears.
"""

import xml.etree.ElementTree as ET  # noqa: N817
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from connectors.tally import envelopes, parser

MAX_ROUNDS = 5
KNOWN_LISTS = Path(__file__).with_name("voucher_lists.txt")


def _dates(start: date, end: date) -> str:
    return (
        f'<SVFROMDATE TYPE="Date">{start:%Y%m%d}</SVFROMDATE>'
        f'<SVTODATE TYPE="Date">{end:%Y%m%d}</SVTODATE>'
    )


def whole_collection_request(
    tally_type: str,
    company: str,
    period: tuple[date, date] | None = None,
    lists: Sequence[str] = (),
    voucher_number: str | None = None,
) -> str:
    """A collection of one Tally type (only types the connector already uses), each object
    whole (NATIVEMETHOD *) with every field of the `lists` (dotted paths, e.g.
    ALLLEDGERENTRIES.BANKALLOCATIONS). `period` (inclusive, its end a day Educational mode
    allows) limits objects by $Date; `voucher_number` to that voucher number."""
    name = "LBFull"
    static = (
        f"<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>"
        f"<SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY>"
    )
    conditions = []
    if period is not None:
        static += _dates(*period)
        conditions.append("$Date &gt;= ##SVFromDate AND $Date &lt;= ##SVToDate")
    if voucher_number is not None:
        if '"' in voucher_number:
            raise ValueError("A voucher number with a double quote can't be looked up")
        conditions.append(f'$VoucherNumber = "{escape(voucher_number)}"')
    filters = formula = ""
    if conditions:
        filters = "<FILTER>LBFullOnly</FILTER>"
        formula = f'<SYSTEM TYPE="Formulae" NAME="LBFullOnly">{" AND ".join(conditions)}</SYSTEM>'
    fetch = f"<FETCH>{', '.join(f'{path}.*' for path in lists)}</FETCH>" if lists else ""
    return (
        "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>"
        f"<TYPE>Collection</TYPE><ID>{name}</ID></HEADER><BODY><DESC>"
        f"<STATICVARIABLES>{static}</STATICVARIABLES>"
        f'<TDL><TDLMESSAGE><COLLECTION NAME="{name}" ISMODIFY="No"><TYPE>{tally_type}</TYPE>'
        f"<NATIVEMETHOD>*</NATIVEMETHOD>{fetch}{filters}</COLLECTION>{formula}"
        "</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"
    )


def list_paths(body: bytes, tag: str = "VOUCHER") -> set[str]:
    """Every sub-list of the objects, as a dotted path (ALLLEDGERENTRIES.BANKALLOCATIONS)."""
    found: set[str] = set()

    def walk(node: ET.Element, prefix: str) -> None:
        for child in node:
            if child.tag.endswith(".LIST"):
                path = f"{prefix}.{child.tag[:-5]}" if prefix else child.tag[:-5]
                found.add(path)
                walk(child, path)

    for element in parser.parse_response(body).iter(tag):
        if len(element):
            walk(element, "")
    return found


def connector_list_paths() -> set[str]:
    """The sub-lists the connector's voucher fetch names (upper case, dotted)."""
    return {
        ".".join(parts[:i]).upper()
        for field in envelopes.VOUCHERS.fetch
        if len(parts := field.split(".")) > 1
        for i in range(1, len(parts))
    }


def known_lists() -> set[str]:
    """The voucher sub-lists recorded on the test company, and the connector's."""
    recorded = {line.strip() for line in KNOWN_LISTS.read_text("utf-8").splitlines()}
    return (recorded - {""}) | connector_list_paths()


def whole_vouchers(
    post: Callable[[str], bytes],
    company: str,
    period: tuple[date, date],
    lists: set[str],
    voucher_number: str | None = None,
) -> tuple[bytes, set[str], int]:
    """Vouchers with every field and sub-list: the answer, the sub-lists asked for and the
    rounds it took."""
    lists = set(lists)
    rounds = 0
    while True:
        rounds += 1
        body = post(
            whole_collection_request("Voucher", company, period, sorted(lists), voucher_number)
        )
        new = list_paths(body) - lists
        if not new or rounds == MAX_ROUNDS:
            return body, lists, rounds
        lists |= new


def _paths(element: ET.Element, prefix: str = "") -> list[tuple[str, str]]:
    found = [
        (f"{prefix}/{name}" if prefix else name, value) for name, value in element.attrib.items()
    ]
    for child in element:
        tag = parser.restore_name(child.tag)
        path = f"{prefix}/{tag}" if prefix else tag
        if len(child):
            found += _paths(child, path)
        else:
            found.append((path, (child.text or "").strip()))
    return found


def paths_containing(body: bytes, text: str) -> list[str]:
    """The field paths of the answer's vouchers whose value contains the text (any case)."""
    needle = text.strip().lower()
    root = parser.parse_response(body)
    vouchers = [v for v in root.iter("VOUCHER") if len(v)]
    return sorted({path for v in vouchers for path, value in _paths(v) if needle in value.lower()})


def find_field(
    post: Callable[[str], bytes], company: str, on: date, voucher_number: str, text: str
) -> tuple[int, list[str]]:
    """How many vouchers matched, and the paths whose value contains the text."""
    if len(text.strip()) < 3:
        raise ValueError("Give at least 3 characters of the text to look for")
    body, _, _ = whole_vouchers(post, company, (on, on), known_lists(), voucher_number)
    count = sum(1 for v in parser.parse_response(body).iter("VOUCHER") if len(v))
    return count, paths_containing(body, text)
