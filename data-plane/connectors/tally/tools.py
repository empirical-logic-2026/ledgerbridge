"""Tally developer tools (test environment only).

    python -m connectors.tally.tools capture-fixtures --company "LedgerBridge Test Co"
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
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx

from connectors.tally import envelopes, parser
from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import DEFAULT_DIR, FixtureTransport, load_manifest
from connectors.tally.signs import check_balance_sides, check_opening_balances, check_vouchers
from core.config import get_settings


def _connector(transport: httpx.BaseTransport | None = None) -> TallyConnector:
    return TallyConnector.from_config(TallyConnector.default_config(), transport=transport)


def capture_fixtures(company: str, directory: Path) -> int:
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

    directory.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    sizes: dict[str, int] = {}

    def save(name: str, body: bytes) -> None:
        (directory / name).write_bytes(body)
        sizes[name] = len(body)

    save("companies.xml", companies_body)
    files[envelopes.COMPANIES.collection_id] = "companies.xml"
    for spec in envelopes.MASTER_SPECS:
        name = f"{spec.object_type}s.xml"
        save(name, connector.client.post(envelopes.collection_request(spec, company=company)))
        files[spec.collection_id] = name

    balances_request = envelopes.collection_request(envelopes.LEDGER_BALANCES, company=company)
    save("ledger_balances.xml", connector.client.post(balances_request))
    files[envelopes.LEDGER_BALANCES.collection_id] = "ledger_balances.xml"

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
        return capture_fixtures(args.company, args.dir)
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
