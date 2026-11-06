"""Records one full export of the test company: every field Tally has, not our field list
(docs/data-completeness.md is written from it). Development only, test company only.

    python -m devtools.tally_full_export [--company "LedgerBridge Test Co"] [--out DIR]

What it asks Tally for (Export requests only; TallyClient refuses anything else):

- every master of every type, as Tally's own export writes it (the "List of Accounts"
  report with all masters): a master type missing from it has no masters in the company;
- the company object whole;
- Tally's own Day Book export (`daybook.xml`): whole vouchers with every sub-list, also
  the empty ones, but only of Tally's current date (it ignores the period asked for, and
  Educational mode allows only the 1st, 2nd and 31st as dates);
- so every voucher of every type, whole, from the Voucher collection (`vouchers.xml`):
  NATIVEMETHOD * for the voucher's own fields and `<list>.*` for every sub-list, the lists
  found in rounds: the Day Book's and the connector's to start with, then any nested list a
  round's answer shows, until no new one appears (NATIVEMETHOD * alone leaves the sub-lists
  out, 2026-11-05).

Not asked: a collection per master type. Asked for a type name it doesn't know, TallyPrime
stopped answering until someone attended to it (2026-11-06).

The same guards as the seeder (ADR-014): APP_ENV=test, exactly one company loaded, its name
exactly the test company's. Prints counts and file sizes only.
"""

import argparse
import gzip
import json
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from connectors.tally import envelopes, parser
from connectors.tally.client import TallyClient
from connectors.tally.find_field import (  # noqa: F401 - whole_collection_request: tests
    connector_list_paths,
    list_paths,
    whole_collection_request,
    whole_vouchers,
)
from core.config import get_settings
from devtools.tally_seed.seed import SeedRefusedError, check_guards

COMPANY = "LedgerBridge Test Co"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tally" / "full-export"
GZIP_ABOVE = 2_000_000  # bytes: a larger file is stored gzip-compressed
TO_DATE = date(2027, 3, 31)  # a 31st: a date Educational mode allows


def _static(company: str, extra: str = "") -> str:
    return (
        "<STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>"
        f"<SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY>{extra}</STATICVARIABLES>"
    )


def _dates(start: date, end: date) -> str:
    return (
        f'<SVFROMDATE TYPE="Date">{start:%Y%m%d}</SVFROMDATE>'
        f'<SVTODATE TYPE="Date">{end:%Y%m%d}</SVTODATE>'
    )


def data_request(report: str, company: str, extra: str = "") -> str:
    """One of Tally's own exports (as its Export menu writes it: every field)."""
    return (
        "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>"
        f"<TYPE>Data</TYPE><ID>{escape(report)}</ID></HEADER><BODY><DESC>"
        f"{_static(company, extra)}</DESC></BODY></ENVELOPE>"
    )


def masters_request(company: str) -> str:
    return data_request("List of Accounts", company, "<ACCOUNTTYPE>All Masters</ACCOUNTTYPE>")


def daybook_request(company: str, start: date, end: date) -> str:
    return data_request("Day Book", company, f"{_dates(start, end)}<EXPLODEFLAG>Yes</EXPLODEFLAG>")


def object_counts(body: bytes) -> dict[str, int]:
    """How many objects of each type: the children of TALLYMESSAGE (Tally's own exports)
    or of COLLECTION (collection exports)."""
    root = parser.parse_response(body)
    found: Counter[str] = Counter()
    for holder in (*root.iter("TALLYMESSAGE"), *root.iter("COLLECTION")):
        found.update(child.tag for child in holder if len(child))
    return dict(sorted(found.items()))


def loaded_company(client: TallyClient, company: str) -> date:
    """The guards; the company's books-from date."""
    entities = parser.parse_companies(
        client.post(envelopes.collection_request(envelopes.COMPANIES))
    )
    check_guards(get_settings(), company, [e.name for e in entities])
    books_from = entities[0].books_from
    if books_from is None:
        raise SeedRefusedError("The company has no books-from date")
    return books_from


def _has_control_characters(body: bytes) -> bool:
    """Tally writes its own markers as control characters (e.g. U+0004, U+0005): such a file
    is kept exact, compressed (the repository's text files may not hold them)."""
    return any(b < 32 and b not in (9, 10, 13) for b in body)


class Recording:
    """Writes each answer as it arrives (a later failure keeps what came before)."""

    def __init__(self, out: Path) -> None:
        self.out = out
        self.counts: dict[str, dict[str, int]] = {}
        self.sizes: dict[str, int] = {}

    def save(self, name: str, body: bytes) -> None:
        self.counts[name] = object_counts(body)
        compress = len(body) > GZIP_ABOVE or _has_control_characters(body)
        path = self.out / (f"{name}.gz" if compress else name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(body, mtime=0) if compress else body)
        self.sizes[path.name] = path.stat().st_size


def record(client: TallyClient, company: str, out: Path) -> Recording:
    books_from = loaded_company(client, company)
    rec = Recording(out)
    rec.save("company.xml", client.post(whole_collection_request("Company", company)))
    rec.save("masters.xml", client.post(masters_request(company)))
    period = (books_from, TO_DATE)
    daybook = client.post(daybook_request(company, *period))
    rec.save("daybook.xml", daybook)

    vouchers, lists, rounds = whole_vouchers(
        client.post, company, period, list_paths(daybook) | connector_list_paths()
    )
    rec.save("vouchers.xml", vouchers)
    facts = {
        "company": company,
        "recorded_on": date.today().isoformat(),
        "period": [books_from.isoformat(), TO_DATE.isoformat()],
        "voucher_list_paths_fetched": len(lists),
        "voucher_rounds": rounds,
        "objects": rec.counts,
        "sizes": rec.sizes,
    }
    (out / "export.json").write_text(json.dumps(facts, indent=2) + "\n", "utf-8")
    return rec


def main(argv: Sequence[str] | None = None) -> int:
    args = argparse.ArgumentParser(prog="python -m devtools.tally_full_export")
    args.add_argument("--company", default=COMPANY)
    args.add_argument("--out", type=Path, default=DEFAULT_OUT)
    options = args.parse_args(argv)
    client = TallyClient(get_settings().tally_url, timeout=300, retries=0)
    try:
        rec = record(client, options.company, options.out)
    except SeedRefusedError as exc:
        print(f"Refusing: {exc}", file=sys.stderr)
        return 2
    for name, counts in rec.counts.items():
        print(f"  {name}: {counts}")
    for name, size in rec.sizes.items():
        print(f"  {name}: {size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
