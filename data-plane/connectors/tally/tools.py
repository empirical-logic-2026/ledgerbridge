"""Tally developer tools (test environment only): record fixtures, check sign conventions.

Where it fits: not part of the sync. `capture-fixtures` records Tally's answers for the
test company into tests/fixtures/tally (replayed by fixtures.FixtureTransport);
`sign-check` runs the checks in signs.py against Tally or the fixtures.

    python -m connectors.tally.tools capture-fixtures --company "LedgerBridge Test Co"
    python -m connectors.tally.tools capture-ledger-report --company "LedgerBridge Test Co" \
        --ledger "Test Bank Current A/c" --ledger "Sales - Goods" --from 2026-04-01 --to 2026-10-02
    python -m connectors.tally.tools capture-pl-layout --company "LedgerBridge Test Co" \
        --date 2026-10-02 --date 2026-11-02 --year-start 2026-04-01 --dir <folder>
    python -m connectors.tally.tools sign-check --company "LedgerBridge Test Co"
    python -m connectors.tally.tools sign-check --fixtures
    python -m connectors.tally.tools sign-check --company "LedgerBridge Test Co" \
        --anchor-voucher "[lb-seed:PMT-ANCHOR]" --anchor-ledger Rent \
        --anchor-opening-ledger Cash --anchor-balances Rent,Cash,Capital

Output is counts, file names and sizes, plus the closing balances of explicitly named
anchor ledgers (test company only); no other amounts or names from the books.
"""

import argparse
import json
import re
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import httpx

from connectors.tally import envelopes, parser
from connectors.tally.connector import TallyConnector, _period_for, month_end, month_periods
from connectors.tally.fixtures import DEFAULT_DIR, FixtureTransport, load_manifest
from connectors.tally.signs import check_balance_sides, check_opening_balances, check_vouchers
from core.config import get_settings


def _connector(transport: httpx.BaseTransport | None = None) -> TallyConnector:
    return TallyConnector.from_config(TallyConnector.default_config(), transport=transport)


def capture_fixtures(company: str, directory: Path, guid_prefix: str = "") -> int:
    settings = get_settings()
    if settings.app_env != "test":
        print("capture-fixtures runs only with APP_ENV=test", file=sys.stderr)
        return 2
    connector = _connector()
    companies_body = connector.client.post(envelopes.collection_request(envelopes.COMPANIES))
    entities = parser.parse_companies(companies_body)
    names = [e.name for e in entities]
    if names != [company]:
        # Fixtures may only ever contain the test company.
        print(
            f"Refusing: expected only '{company}' to be loaded, found {len(names)} companies",
            file=sys.stderr,
        )
        return 2
    entity = entities[0]
    if guid_prefix and not entity.key.startswith(guid_prefix):
        # Another company of the same name (e.g. a new empty one) is loaded.
        print(
            "Refusing: the loaded company's GUID doesn't start with --guid-prefix", file=sys.stderr
        )
        return 2

    directory.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    sizes: dict[str, int] = {}

    def save(name: str, body: bytes) -> None:
        (directory / name).write_bytes(body)
        sizes[name] = len(body)

    save("companies.xml", companies_body)
    files[envelopes.COMPANIES.collection_id] = "companies.xml"

    def request(spec: envelopes.CollectionSpec) -> str:
        """As the connector asks: masters with openings for the books' beginning, so their
        OPENINGBALANCE is their own opening, not the balance at the start of Tally's
        current year (a company with a year end, 2026-10-24)."""
        return envelopes.collection_request(
            spec, company=company, balances_period=_period_for(spec, entity)
        )

    for spec in envelopes.MASTER_SPECS:
        name = f"{spec.object_type}s.xml"
        save(name, connector.client.post(request(spec)))
        files[spec.collection_id] = name

    balances_request = envelopes.collection_request(envelopes.LEDGER_BALANCES, company=company)
    save("ledger_balances.xml", connector.client.post(balances_request))
    files[envelopes.LEDGER_BALANCES.collection_id] = "ledger_balances.xml"
    stock_request = envelopes.collection_request(envelopes.STOCK_VALUES, company=company)
    save("stock_values.xml", connector.client.post(stock_request))
    files[envelopes.STOCK_VALUES.collection_id] = "stock_values.xml"
    for spec, name in (
        (envelopes.BILLS, "bills.xml"),
        (envelopes.LEDGER_OPENING_BILLS, "ledger_opening_bills.xml"),
    ):
        save(name, connector.client.post(request(spec)))
        files[spec.collection_id] = name

    vouchers = []
    for month in connector.voucher_periods(entity):
        request = envelopes.collection_request(
            envelopes.VOUCHERS, company=company, period=(month.start, month.end)
        )
        body = connector.client.post(request)
        if not parser.objects(parser.parse_response(body), envelopes.VOUCHERS.object_tag):
            continue
        name = f"vouchers_{month.start:%Y-%m}.xml"
        save(name, body)
        vouchers.append(
            {"from": month.start.isoformat(), "to": month.end.isoformat(), "file": name}
        )

    manifest = {"company": company, "files": files, "vouchers": vouchers}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    print(f"Saved {len(sizes)} responses to {directory}:")
    for name, size in sizes.items():
        print(f"  {name}: {size:,} bytes")
    return 0


LEDGER_REPORTS = DEFAULT_DIR / "rules" / "ledger_report"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")


def _report_periods(start: date, end: date) -> list[tuple[date, date]]:
    """The months Tally's Ledger Vouchers report can be read for: its export lists only the
    To date's month, and in Educational mode a To date must be the 1st, 2nd or 31st. So the
    months that end on the 31st, and the last month when it ends on a valid day."""
    found = []
    for month in month_periods(start, end):
        if month.end.day in (1, 2, 31):
            found.append((month.start, month.end))
    return found


def capture_ledger_report(
    company: str, ledgers: Sequence[str], start: date, end: date, directory: Path,
    guid_prefix: str = "",
) -> int:  # fmt: skip
    """Records, for the Ledger statement's tests (ADR-055): the test company's books (as
    capture-fixtures, into books/), each ledger's vouchers as Tally lists them month by
    month (its ledger-voucher collection), Tally's own Ledger Vouchers report for the months
    it can be read for, and every ledger's opening and closing balance for the period.
    Read-only; test company only (the same guards as capture-fixtures)."""
    code = capture_fixtures(company, directory / "books", guid_prefix)
    if code:
        return code
    connector = _connector()
    files: dict[str, list[str]] = {}
    sizes: dict[str, int] = {}

    def save(name: str, body: bytes) -> str:
        (directory / name).write_bytes(body)
        sizes[name] = len(body)
        return name

    for ledger in ledgers:
        slug = _slug(ledger)
        names = []
        for month in month_periods(start, end):
            request = envelopes.collection_request(
                envelopes.LEDGER_VOUCHERS, company=company, period=(month.start, month.end),
                child_of=ledger,
            )  # fmt: skip
            names.append(save(f"{slug}_vouchers_{month.start:%Y-%m}.xml",
                              connector.client.post(request)))  # fmt: skip
        for period in _report_periods(start, end):
            body = connector.client.post(envelopes.ledger_report_request(company, ledger, period))
            names.append(save(f"{slug}_report_{period[1]}.xml", body))
        files[ledger] = names
    balances = envelopes.collection_request(
        envelopes.LEDGER_BALANCES, company=company, balances_period=(start, end)
    )
    save("ledger_balances.xml", connector.client.post(balances))
    manifest = {
        "company": company, "start": start.isoformat(), "end": end.isoformat(),
        "ledgers": files, "balances": "ledger_balances.xml",
    }  # fmt: skip
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    print(f"Saved {len(sizes)} responses to {directory} (and the books to books/):")
    for name, size in sizes.items():
        print(f"  {name}: {size:,} bytes")
    return 0


PL_LAYOUT = DEFAULT_DIR / "rules" / "pl_sides"
EXTENSIONS = {"XML": "xml", "HTML": "html", "ASCII": "txt"}


def capture_pl_layout(
    company: str, dates: Sequence[date], year_start: date | None, directory: Path,
    guid_prefix: str = "",
) -> int:  # fmt: skip
    """Records, for the Profit & Loss in Tally's layout (ADR-056): the test company's books
    (as capture-fixtures, into books/), and at each date Tally's Profit and Loss in each
    export format (XML, which the connector reads; HTML and ASCII, which may keep its two
    sides), its Balance Sheet and its group balances, for the period from the books'
    beginning and, after `year_start`, for the financial year (prefixed fy_). Read-only;
    test company only (the same guards as capture-fixtures)."""
    code = capture_fixtures(company, directory / "books", guid_prefix)
    if code:
        return code
    connector = _connector()
    entity = connector.list_entities()[0]
    if entity.books_from is None:
        print("Refusing: the company has no books-from date", file=sys.stderr)
        return 2
    sizes: dict[str, int] = {}

    def save(name: str, body: bytes) -> None:
        (directory / name).write_bytes(body)
        sizes[name] = len(body)

    for on in dates:
        periods = [("", (entity.books_from, on))]
        if year_start is not None and entity.books_from < year_start <= on:
            periods.append(("fy_", (year_start, on)))
        for prefix, period in periods:
            for export_format, extension in EXTENSIONS.items():
                request = envelopes.report_request(
                    envelopes.PROFIT_AND_LOSS, company, period, export_format=export_format
                )
                save(f"{prefix}profit_and_loss_{on}.{extension}", connector.client.post(request))
            sheet = envelopes.report_request(envelopes.BALANCE_SHEET, company, period)
            save(f"{prefix}balance_sheet_{on}.xml", connector.client.post(sheet))
            groups = envelopes.collection_request(
                envelopes.GROUP_BALANCES, company=company, balances_period=period
            )
            save(f"{prefix}group_balance_{on}.xml", connector.client.post(groups))
    manifest = {
        "company": company, "dates": [d.isoformat() for d in dates],
        "year_start": year_start.isoformat() if year_start else None,
    }  # fmt: skip
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    print(f"Saved {len(sizes)} responses to {directory} (and the books to books/):")
    for name, size in sizes.items():
        print(f"  {name}: {size:,} bytes")
    return 0


DAY_BOOKS = DEFAULT_DIR / "rules" / "day_book"


def capture_day_book(
    company: str, start: date, end: date, directory: Path, guid_prefix: str = ""
) -> int:
    """Records, for the Day Book page (ADR-057): the test company's books (as capture-fixtures,
    into books/), Tally's voucher list (date and type of each voucher) month by month, and
    Tally's own Day Book in XML and HTML for every day of the period with a voucher. Tally's
    Day Book lists one day, its current date, whatever the From and To dates (checked on the
    test company, 2026-11-13). Read-only; test company only (the guards of capture-fixtures)."""
    code = capture_fixtures(company, directory / "books", guid_prefix)
    if code:
        return code
    connector = _connector()
    sizes: dict[str, int] = {}

    def save(name: str, body: bytes) -> bytes:
        (directory / name).write_bytes(body)
        sizes[name] = len(body)
        return body

    days: set[date] = set()
    # Whole months, so Educational mode answers (as connector.voucher_counts asks).
    for month in month_periods(start.replace(day=1), month_end(end)):
        request = envelopes.collection_request(
            envelopes.VOUCHER_COUNTS, company=company, period=(month.start, month.end)
        )
        body = save(f"voucher_counts_{month.start:%Y-%m}.xml", connector.client.post(request))
        for element in parser.objects(
            parser.parse_response(body), envelopes.VOUCHER_COUNTS.object_tag
        ):
            on = parser.tally_date(parser.text_of(element, "DATE"))
            if on is not None and start <= on <= end:
                days.add(on)
    for on in sorted(days):
        for export_format in ("XML", "HTML"):
            request = envelopes.report_request(
                envelopes.DAY_BOOK, company, (on, on), export_format=export_format,
                current_date=on,
            )  # fmt: skip
            save(f"day_book_{on}.{EXTENSIONS[export_format]}", connector.client.post(request))
    manifest = {
        "company": company, "start": start.isoformat(), "end": end.isoformat(),
        "days": [d.isoformat() for d in sorted(days)],
    }  # fmt: skip
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    print(f"Saved {len(sizes)} responses to {directory} (and the books to books/):")
    for name, size in sizes.items():
        print(f"  {name}: {size:,} bytes")
    return 0


def sign_check(
    company: str | None,
    fixtures: Path | None,
    anchor_voucher: str | None,
    anchor_ledger: str | None,
    anchor_opening_ledger: str | None,
    anchor_balances: Sequence[str] = (),
) -> int:
    if fixtures is not None:
        transport = FixtureTransport(fixtures)
        company = load_manifest(fixtures)["company"]
        connector = _connector(transport)
    else:
        connector = _connector()
    entity = next((e for e in connector.list_entities() if e.name == company), None)
    if entity is None:
        print("Company not loaded in Tally", file=sys.stderr)
        return 2

    vouchers = connector.voucher_elements(entity)
    print("Voucher postings")
    for line in check_vouchers(vouchers, anchor_voucher, anchor_ledger).lines():
        print(f"  {line}")
    print("Ledger opening balances")
    ledgers = connector.ledger_elements(entity)
    for line in check_opening_balances(ledgers, anchor_opening_ledger).lines():
        print(f"  {line}")
    print("Tally's own Dr/Cr judgement ($$IsDr), independent of XML signs")
    sides = check_balance_sides(connector.ledger_balance_elements(entity), anchor_balances)
    for line in sides.lines():
        print(f"  {line}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    root = argparse.ArgumentParser(prog="python -m connectors.tally.tools")
    sub = root.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture-fixtures", help="record responses for the test company")
    capture.add_argument("--company", required=True)
    capture.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    capture.add_argument(
        "--guid-prefix", default="", help="refuse unless the company's GUID starts with this"
    )

    report = sub.add_parser(
        "capture-ledger-report", help="record ledgers as Tally reports them (test company)"
    )
    report.add_argument("--company", required=True)
    report.add_argument("--ledger", action="append", required=True, help="a ledger's name (list)")
    report.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    report.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    report.add_argument("--dir", type=Path, default=LEDGER_REPORTS)
    report.add_argument(
        "--guid-prefix", default="", help="refuse unless the company's GUID starts with this"
    )

    layout = sub.add_parser(
        "capture-pl-layout", help="record Tally's Profit & Loss in each format (test company)"
    )
    layout.add_argument("--company", required=True)
    layout.add_argument(
        "--date", dest="dates", action="append", type=date.fromisoformat, required=True
    )
    layout.add_argument("--year-start", type=date.fromisoformat, help="the financial year's start")
    layout.add_argument("--dir", type=Path, default=PL_LAYOUT)
    layout.add_argument(
        "--guid-prefix", default="", help="refuse unless the company's GUID starts with this"
    )

    day_book = sub.add_parser(
        "capture-day-book", help="record Tally's Day Book and voucher counts (test company)"
    )
    day_book.add_argument("--company", required=True)
    day_book.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    day_book.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    day_book.add_argument("--dir", type=Path, default=DAY_BOOKS)
    day_book.add_argument(
        "--guid-prefix", default="", help="refuse unless the company's GUID starts with this"
    )

    signs = sub.add_parser("sign-check", help="confirm how Tally signs debits and credits")
    source = signs.add_mutually_exclusive_group(required=True)
    source.add_argument("--company")
    source.add_argument(
        "--fixtures", nargs="?", const=DEFAULT_DIR, type=Path, help="use recorded fixtures"
    )
    signs.add_argument(
        "--anchor-voucher",
        help="number of, or narration text in, a voucher with a known debit line",
    )
    signs.add_argument("--anchor-ledger", help="ledger debited in the anchor voucher")
    signs.add_argument("--anchor-opening-ledger", help="ledger with a known debit opening balance")
    signs.add_argument(
        "--anchor-balances",
        default="",
        help="comma-separated ledgers whose closing balance to show",
    )

    args = root.parse_args(argv)
    if args.command == "capture-fixtures":
        return capture_fixtures(args.company, args.dir, args.guid_prefix)
    if args.command == "capture-day-book":
        return capture_day_book(args.company, args.start, args.end, args.dir, args.guid_prefix)
    if args.command == "capture-pl-layout":
        return capture_pl_layout(
            args.company, args.dates, args.year_start, args.dir, args.guid_prefix
        )
    if args.command == "capture-ledger-report":
        return capture_ledger_report(
            args.company, args.ledger, args.start, args.end, args.dir, args.guid_prefix
        )
    return sign_check(
        args.company,
        args.fixtures,
        args.anchor_voucher,
        args.anchor_ledger,
        args.anchor_opening_ledger,
        [name.strip() for name in args.anchor_balances.split(",") if name.strip()],
    )


if __name__ == "__main__":
    raise SystemExit(main())
