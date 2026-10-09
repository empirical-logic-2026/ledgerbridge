"""Idempotent seeding of the test company (ADR-014).

Reads Tally's current state with the connector's Export-only client, works out what is
missing, imports only that, then applies the cancellation and the alteration and checks
that both took effect.
"""

import re
import xml.etree.ElementTree as ET  # noqa: N817
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

import httpx

from connectors.tally import envelopes, parser
from connectors.tally.client import TallyClient, decode_response
from connectors.tally.envelopes import CollectionSpec
from connectors.tally.signs import postings, tally_amount
from core.config import Settings
from devtools.tally_seed import requests as rq
from devtools.tally_seed.data import SeedData, Voucher

UNITS = CollectionSpec("LBSeedUnits", "Unit", "UNIT", "unit", ("NAME",))
STOCK_ITEMS = CollectionSpec("LBSeedItems", "StockItem", "STOCKITEM", "stock_item", ("NAME",))
COST_CENTRES = CollectionSpec(
    "LBSeedCostCentres", "CostCentre", "COSTCENTRE", "cost_centre", ("NAME",)
)
_MARKER = re.compile(r"\[lb-seed:([A-Z0-9-]+)\]")


class SeedRefusedError(RuntimeError):
    """A safety guard failed; nothing was written."""


class ImportFailedError(RuntimeError):
    """Tally rejected an import; carries Tally's own messages."""

    def __init__(self, what: str, messages: Sequence[str]) -> None:
        super().__init__(f"{what}: {'; '.join(messages) or 'rejected without a message'}")
        self.messages = list(messages)


@dataclass
class ImportResult:
    created: int = 0
    altered: int = 0
    cancelled: int = 0
    errors: int = 0
    exceptions: int = 0
    messages: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.errors == 0 and self.exceptions == 0 and not self.messages


def parse_import_response(body: bytes) -> ImportResult:
    root = ET.fromstring(parser.sanitize(decode_response(body)).lstrip("﻿"))  # noqa: S314

    def count(tag: str) -> int:
        value = root.findtext(f".//{tag}")
        return int(value.strip()) if value and value.strip().lstrip("-").isdigit() else 0

    messages = [m.text.strip() for m in root.iter("LINEERROR") if m.text and m.text.strip()]
    return ImportResult(
        created=count("CREATED"),
        altered=count("ALTERED"),
        cancelled=count("CANCELLED"),
        errors=count("ERRORS"),
        exceptions=count("EXCEPTIONS"),
        messages=messages,
    )


class TallyImporter:
    """Posts Import requests. Developer-only (ADR-014); connectors stay Export-only."""

    def __init__(self, url: str, transport: httpx.BaseTransport | None = None) -> None:
        self._http = httpx.Client(timeout=120, transport=transport)
        self.url = url

    def post(self, request_xml: str) -> ImportResult:
        if "<TALLYREQUEST>Import Data</TALLYREQUEST>" not in request_xml:
            raise ValueError("TallyImporter only sends Import requests")
        response = self._http.post(
            self.url,
            content=request_xml.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8"},
        )
        response.raise_for_status()
        return parse_import_response(response.content)


@dataclass
class VoucherState:
    master_id: int
    cancelled: bool
    amounts: dict[str, Decimal]  # ledger -> signed Tally amount (sum)


@dataclass
class TallyState:
    ledgers: dict[str, Decimal]  # name -> signed opening balance
    units: set[str]
    stock_items: set[str]
    cost_centres: set[str]
    cost_centres_enabled: bool
    vouchers: dict[str, VoucherState]  # marker -> state


@dataclass
class SeedReport:
    created: dict[str, int] = field(default_factory=dict)
    altered: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def add(self, kind: str) -> None:
        self.created[kind] = self.created.get(kind, 0) + 1


def check_guards(settings: Settings, company: str, loaded: list[str]) -> None:
    """Every guard from ADR-014. Raises SeedRefusedError before anything is written."""
    if settings.app_env != "test":
        raise SeedRefusedError(
            f"APP_ENV is '{settings.app_env}'; seeding runs only with APP_ENV=test"
        )
    if len(loaded) != 1:
        raise SeedRefusedError(
            f"{len(loaded)} companies are loaded in Tally; load only the test company"
        )
    if loaded[0] != company:
        raise SeedRefusedError(
            "The loaded company's name does not exactly match the target company"
        )


def _names(root: ET.Element, tag: str) -> set[str]:
    return {name for o in parser.objects(root, tag) if (name := parser.object_name(o))}


def _voucher_amounts(voucher: ET.Element) -> dict[str, Decimal]:
    amounts: dict[str, Decimal] = {}
    for entry in postings(voucher):
        ledger = (entry.findtext("LEDGERNAME") or "").strip()
        value = tally_amount(entry.findtext("AMOUNT"))
        if value is not None:
            amounts[ledger] = amounts.get(ledger, Decimal(0)) + value
    return amounts


def read_state(client: TallyClient, company: str) -> TallyState:
    def export(spec: CollectionSpec) -> ET.Element:
        return parser.parse_response(
            client.post(envelopes.collection_request(spec, company=company))
        )

    companies = parser.objects(export(envelopes.COMPANIES), "COMPANY")
    cc_enabled = any(
        parser.object_name(c) == company and (c.findtext("ISCOSTCENTRESON") or "").strip() == "Yes"
        for c in companies
    )
    ledgers = {
        name: tally_amount(o.findtext("OPENINGBALANCE")) or Decimal(0)
        for o in parser.objects(export(envelopes.LEDGERS), "LEDGER")
        if (name := parser.object_name(o))
    }
    vouchers: dict[str, VoucherState] = {}
    for v in parser.objects(export(envelopes.VOUCHERS), "VOUCHER"):
        match = _MARKER.search(v.findtext("NARRATION") or "")
        if not match:
            continue
        vouchers[match.group(1)] = VoucherState(
            master_id=int((v.findtext("MASTERID") or "0").strip() or 0),
            cancelled=(v.findtext("ISCANCELLED") or "").strip() == "Yes",
            amounts=_voucher_amounts(v),
        )
    return TallyState(
        ledgers=ledgers,
        units=_names(export(UNITS), "UNIT"),
        stock_items=_names(export(STOCK_ITEMS), "STOCKITEM"),
        cost_centres=_names(export(COST_CENTRES), "COSTCENTRE"),
        cost_centres_enabled=cc_enabled,
        vouchers=vouchers,
    )


def _is_altered(voucher: Voucher, state: VoucherState) -> bool:
    for entry in voucher.alter_to or ():
        expected = -entry.amount if entry.side == "Dr" else entry.amount
        if state.amounts.get(entry.ledger) != expected:
            return False
    return True


def seed(
    seed_data: SeedData,
    company: str,
    reader: Callable[[], TallyState],
    importer: TallyImporter,
    log: Callable[[str], None] = print,
) -> SeedReport:
    report = SeedReport()

    def run(what: str, kind: str, report_name: str, body: str) -> ImportResult:
        result = importer.post(rq.envelope(company, report_name, body))
        if not result.ok:
            raise ImportFailedError(what, result.messages)
        log(f"  {kind}: {what}")
        return result

    state = reader()

    for unit in seed_data.units:
        if unit not in state.units:
            run(unit, "unit", "All Masters", rq.unit_create(unit))
            report.add("units")
    for name, unit in seed_data.stock_items:
        if name not in state.stock_items:
            run(name, "stock item", "All Masters", rq.stock_item_create(name, unit))
            report.add("stock items")
    if state.cost_centres_enabled:
        for centre in seed_data.cost_centres:
            if centre not in state.cost_centres:
                run(centre, "cost centre", "All Masters", rq.cost_centre_create(centre))
                report.add("cost centres")
    else:
        report.skipped.append(
            "cost centres (feature off in TallyPrime: F11 > Maintain cost centres)"
        )

    for ledger in seed_data.ledgers:
        wanted = -ledger.opening if ledger.opening_side == "Dr" else ledger.opening
        if ledger.name not in state.ledgers:
            if ledger.predefined:
                raise ImportFailedError(ledger.name, ["predefined ledger is missing in Tally"])
            run(ledger.name, "ledger", "All Masters", rq.ledger_create(ledger))
            report.add("ledgers")
        elif state.ledgers[ledger.name] != wanted:
            run(ledger.name, "opening balance", "All Masters", rq.ledger_set_opening(ledger))
            report.altered.append(f"opening balance of {ledger.name}")

    for voucher in seed_data.vouchers:
        if voucher.marker in state.vouchers:
            continue
        if voucher.needs_cost_centres and not state.cost_centres_enabled:
            report.skipped.append(f"voucher {voucher.marker} (needs cost centres)")
            continue
        run(voucher.marker, "voucher", "Vouchers", rq.voucher_create(voucher))
        report.add("vouchers")

    # Post-creation changes need the MasterIDs Tally assigned.
    state = reader()
    for voucher in seed_data.vouchers:
        current = state.vouchers.get(voucher.marker)
        if current is None:
            continue
        if voucher.alter_to is not None and not _is_altered(voucher, current):
            run(voucher.marker, "altered", "Vouchers", rq.voucher_alter(voucher, current.master_id))
            report.altered.append(f"voucher {voucher.marker}")
        if voucher.cancel and not current.cancelled:
            run(
                voucher.marker,
                "cancelled",
                "Vouchers",
                rq.voucher_cancel(voucher, current.master_id),
            )
            report.cancelled.append(voucher.marker)

    # Prove the post-creation changes landed, rather than trusting the import counts.
    final = reader()
    for voucher in seed_data.vouchers:
        current = final.vouchers.get(voucher.marker)
        if current is None:
            continue
        if voucher.alter_to is not None and not _is_altered(voucher, current):
            raise ImportFailedError(voucher.marker, ["alteration did not take effect"])
        if voucher.cancel and not current.cancelled:
            raise ImportFailedError(voucher.marker, ["cancellation did not take effect"])
    return report
