"""Tally connector: implements connectors.base.Connector over Tally's XML interface."""

import re
import xml.etree.ElementTree as ET  # noqa: N817
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Self

import httpx

from connectors.base import (
    Chunk,
    ConnectionStatus,
    Markers,
    Period,
    SourceBalances,
    SourceEntity,
    SourceRecord,
)
from connectors.tally import envelopes, mapping, parser
from connectors.tally.client import TallyClient, TallyError
from connectors.tally.signs import tally_amount
from core.canonical import CanonicalRecord
from core.config import get_settings


def month_end(value: date) -> date:
    return (value.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def month_periods(start: date, end: date) -> Iterator[Period]:
    """Calendar-month chunks covering [start, end]."""
    current = start
    while current <= end:
        next_month = (current.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield Period(current, min(end, next_month - timedelta(days=1)))
        current = next_month


class TallyConnector:
    source_code = "tally"
    # Transform order: each type may refer to the ones before it.
    object_types = (
        envelopes.COMPANIES.object_type,
        *(spec.object_type for spec in envelopes.MASTER_SPECS),
        envelopes.VOUCHERS.object_type,
    )

    # The source's own predefined names per object type (Tally's reserved groups and voucher
    # types): the reference diagnostic says when a missing name is one of them.
    reserved_names = {
        "group": mapping.RESERVED_GROUPS,
        "voucher_type": mapping.STANDARD_VOUCHER_TYPES,
    }

    def __init__(self, client: TallyClient) -> None:
        self.client = client
        self._names: dict[str, str] = {}  # company GUID -> name Tally accepted last
        self._prefixes: set[str] = set()  # undeclared XML prefixes met (names only)

    @classmethod
    def from_config(
        cls, config: Mapping[str, Any], transport: httpx.BaseTransport | None = None
    ) -> Self:
        return cls(
            TallyClient(
                str(config["url"]),
                # The connection's own timeout, else the TALLY_TIMEOUT_SEC setting (ADR-023).
                timeout=float(config.get("timeout_sec") or get_settings().tally_timeout_sec),
                transport=transport,
            )
        )

    @staticmethod
    def default_config() -> dict[str, Any]:
        # No timeout stored: a connection follows TALLY_TIMEOUT_SEC until one is set on it
        # (connect --timeout-sec).
        return {"url": get_settings().tally_url}

    def _post(self, request_xml: str, timeout: float | None = None) -> bytes:
        body = self.client.post(request_xml, timeout=timeout)
        self._prefixes |= parser.undeclared_prefixes(body)
        return body

    def test_connection(self) -> ConnectionStatus:
        try:
            companies = self.list_entities()
        except TallyError as exc:
            return ConnectionStatus(ok=False, detail=str(exc))
        return ConnectionStatus(ok=True, info={"companies_loaded": str(len(companies))})

    def list_entities(self) -> list[SourceEntity]:
        """Companies currently loaded in Tally."""
        return parser.parse_companies(self._post(envelopes.collection_request(envelopes.COMPANIES)))

    def fetch_masters(
        self, entity: SourceEntity, markers: Markers | None = None
    ) -> Iterator[SourceRecord]:
        """The company record, then masters changed after their AlterID marker (all of them
        on the first sync). Tally keeps one AlterID counter for masters, so each type's
        marker is the highest AlterID already stored for it."""
        markers = markers or {}
        companies = self._post(envelopes.collection_request(envelopes.COMPANIES))
        yield from (
            record
            for record in parser.parse_records(companies, envelopes.COMPANIES, entity.key)
            if record.source_key == entity.key
        )
        for spec in envelopes.MASTER_SPECS:
            since = _marker(markers, spec.object_type)
            body = self._company_post(
                entity,
                lambda name, spec=spec, since=since: envelopes.collection_request(
                    spec,
                    company=name,
                    since_alter_id=since,
                    balances_period=_period_for(spec, entity),
                ),
            )
            yield from parser.parse_records(body, spec, entity.key)

    def voucher_periods(self, entity: SourceEntity, period: Period | None = None) -> list[Period]:
        if period is not None:
            return list(month_periods(period.start, period.end))
        if entity.books_from is None:
            raise TallyError(f"Company '{entity.name}' has no books-from date; pass a period")
        # Tally's ENDINGAT is not a reliable "books to" date (TallyPrime can report the
        # books-from date), so never stop before today. Always end on a month end, so every
        # request's exclusive end date is the 1st of a month (see envelopes.collection_request).
        end = max(entity.books_to or date.today(), date.today())
        return list(month_periods(entity.books_from, month_end(end)))

    def voucher_bodies(self, entity: SourceEntity, period: Period | None = None) -> Iterator[bytes]:
        """Raw voucher export responses, one per calendar month."""
        for month in self.voucher_periods(entity, period):
            yield self._company_post(
                entity,
                lambda name, month=month: envelopes.collection_request(
                    envelopes.VOUCHERS, company=name, period=(month.start, month.end)
                ),
            )

    def voucher_elements(
        self, entity: SourceEntity, period: Period | None = None
    ) -> Iterator[ET.Element]:
        for body in self.voucher_bodies(entity, period):
            yield from parser.objects(parser.parse_response(body), envelopes.VOUCHERS.object_tag)

    def ledger_balance_elements(self, entity: SourceEntity) -> list[ET.Element]:
        """Ledgers with opening/closing balances and Tally's own $$IsDr judgement, for
        Tally's current period (no explicit dates, so Educational mode cannot reject them)."""
        body = self._company_post(
            entity,
            lambda name: envelopes.collection_request(envelopes.LEDGER_BALANCES, company=name),
        )
        return parser.objects(parser.parse_response(body), envelopes.LEDGER_BALANCES.object_tag)

    def closing_balances(self, entity: SourceEntity, as_of: date) -> SourceBalances:
        """Tally's own closing balances for the period books-from .. as_of (inclusive).

        *Profit & Loss A/c* (directly under Primary) carries the period's computed profit;
        Tally computes that profit with the stock items' opening and closing values.
        """
        if entity.books_from is None:
            raise TallyError(f"Company '{entity.name}' has no books-from date")
        period = (entity.books_from, as_of)
        ledgers: dict[str, Decimal] = {}
        carriers: set[str] = set()
        openings = Decimal(0)  # at the books' beginning: the period starts there
        body = self._company_post(
            entity,
            lambda name: envelopes.collection_request(
                envelopes.LEDGER_BALANCES, company=name, balances_period=period
            ),
        )
        for element in parser.objects(parser.parse_response(body), "LEDGER"):
            key = parser.source_key(element)
            ledgers[key] = _canonical(element.findtext("CLOSINGBALANCE"))
            openings += _canonical(element.findtext("OPENINGBALANCE"))
            if (element.findtext("PARENT") or "").strip() in ("", mapping.PRIMARY):
                carriers.add(key)
        body = self._company_post(
            entity,
            lambda name: envelopes.collection_request(
                envelopes.STOCK_VALUES, company=name, balances_period=period
            ),
        )
        items = parser.objects(parser.parse_response(body), "STOCKITEM")
        return SourceBalances(
            as_of=as_of,
            ledgers=ledgers,
            profit_carriers=frozenset(carriers),
            opening_stock=sum((_canonical(i.findtext("OPENINGVALUE")) for i in items), Decimal(0)),
            closing_stock=sum((_canonical(i.findtext("CLOSINGVALUE")) for i in items), Decimal(0)),
            opening_ledgers=openings,
        )

    # --- figures that prove the books complete (VAL-005 to VAL-008) ---------------------

    def voucher_counts(
        self, entity: SourceEntity, start: date, end: date
    ) -> dict[tuple[date, str], int]:
        """(month start, voucher type name) -> vouchers dated start..end, from a small
        listing per month (whole months, so Educational mode answers them)."""
        counts: Counter[tuple[date, str]] = Counter()
        for month in month_periods(start.replace(day=1), month_end(end)):
            body = self._company_post(
                entity,
                lambda name, month=month: envelopes.collection_request(
                    envelopes.VOUCHER_COUNTS, company=name, period=(month.start, month.end)
                ),
            )
            for element in parser.objects(
                parser.parse_response(body), envelopes.VOUCHER_COUNTS.object_tag
            ):
                dated = parser.tally_date(parser.text_of(element, "DATE"))
                if dated is None or not start <= dated <= end:
                    continue
                kind = parser.text_of(element, "VOUCHERTYPENAME") or ""
                counts[(dated.replace(day=1), kind)] += 1
        return dict(counts)

    def stock_quantities(self, entity: SourceEntity, as_of: date) -> dict[str, Decimal]:
        """Stock item GUID -> Tally's closing quantity as of `as_of` (from books-from)."""
        if entity.books_from is None:
            raise TallyError(f"Company '{entity.name}' has no books-from date")
        body = self._company_post(
            entity,
            lambda name: envelopes.collection_request(
                envelopes.STOCK_VALUES, company=name, balances_period=(entity.books_from, as_of)
            ),
        )
        quantities = {}
        for element in parser.objects(parser.parse_response(body), "STOCKITEM"):
            quantity, _ = mapping.quantity(parser.text_of(element, "CLOSINGBALANCE"))
            quantities[parser.source_key(element)] = quantity
        return quantities

    def stock_by_godown(
        self, entity: SourceEntity, as_of: date, items: Iterable[str]
    ) -> dict[tuple[str, str], tuple[Decimal, Decimal]]:
        """(stock item name, godown name) -> (opening, closing) quantity for books-from ..
        as_of, from Tally's batches of each named item (one small request per item). Names
        are only used to match our own records, never shown."""
        if entity.books_from is None:
            raise TallyError(f"Company '{entity.name}' has no books-from date")
        out: dict[tuple[str, str], tuple[Decimal, Decimal]] = {}
        for item in items:
            body = self._company_post(
                entity,
                lambda name, item=item: envelopes.collection_request(
                    envelopes.BATCHES,
                    company=name,
                    balances_period=(entity.books_from, as_of),
                    child_of=item,
                ),
            )
            for batch in parser.objects(parser.parse_response(body), envelopes.BATCHES.object_tag):
                godown = parser.text_of(batch, "GODOWNNAME") or ""
                opening, _ = mapping.quantity(parser.text_of(batch, "OPENINGBALANCE"))
                closing, _ = mapping.quantity(parser.text_of(batch, "CLOSINGBALANCE"))
                before = out.get((item, godown), (Decimal(0), Decimal(0)))
                out[(item, godown)] = (before[0] + opening, before[1] + closing)
        return out

    def bill_outstanding(
        self, entity: SourceEntity
    ) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
        """(outstanding bills now, opening bills): party ledger name -> total, canonical
        sign. Tally reports bills outstanding as of its latest date, whatever the period."""
        outstanding: Counter[str] = Counter()
        body = self._company_post(
            entity, lambda name: envelopes.collection_request(envelopes.BILLS, company=name)
        )
        for bill in parser.objects(parser.parse_response(body), envelopes.BILLS.object_tag):
            party = parser.text_of(bill, "PARENT") or ""
            outstanding[party] += _canonical(bill.findtext("CLOSINGBALANCE"))
        opening: Counter[str] = Counter()
        body = self._company_post(
            entity,
            lambda name: envelopes.collection_request(
                envelopes.LEDGER_OPENING_BILLS,
                company=name,
                balances_period=_period_for(envelopes.LEDGER_OPENING_BILLS, entity),
            ),
        )
        for ledger in parser.objects(parser.parse_response(body), "LEDGER"):
            bills = ledger.findall("BILLALLOCATIONS.LIST")
            if bills:
                name = parser.object_name(ledger) or ""
                for bill in bills:
                    opening[name] += _canonical(bill.findtext("OPENINGBALANCE"))
        return dict(outstanding), dict(opening)

    # --- diagnostics: what the source lists now (read-only) -----------------------------

    master_types = tuple(spec.object_type for spec in envelopes.MASTER_SPECS)

    # Lists the mapping reads in a voucher; others are reported by `validate analyse`.
    _READ_LISTS = frozenset((
        "ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST", "ALLINVENTORYENTRIES.LIST",
        "INVENTORYENTRIES.LIST", "INVENTORYENTRIESIN.LIST", "INVENTORYENTRIESOUT.LIST",
        "BILLALLOCATIONS.LIST", "CATEGORYALLOCATIONS.LIST", "COSTCENTREALLOCATIONS.LIST",
        "BATCHALLOCATIONS.LIST", "ACCOUNTINGALLOCATIONS.LIST", "LANGUAGENAME.LIST",
        "NAME.LIST",
        # A ledger entry's copy of the inventory entries: read from ALLINVENTORYENTRIES.
        "INVENTORYALLOCATIONS.LIST",
    ))  # fmt: skip

    @classmethod
    def payload_hints(cls, object_type: str, payload: str) -> set[str]:
        """Patterns in a stored record that can explain a mismatch (kinds only, never
        values): foreign currency amounts, alternate or compound units, several godowns or
        batches, and lists of Tally's own that the mapping doesn't read (Tally's tag names;
        custom, prefixed ones are counted, not named)."""
        hints: set[str] = set()
        if object_type != envelopes.VOUCHERS.object_type:
            return hints
        if _FOREX.search(payload):
            hints.add("foreign currency amounts")
        for quantity in _QUANTITY.findall(payload):
            if "=" in quantity:
                hints.add("alternate units")
            elif len(_NUMBERS.findall(quantity)) > 1:
                hints.add("compound units")
        if len(set(_GODOWN.findall(payload))) > 1 or len(set(_BATCH.findall(payload))) > 1:
            hints.add("several godowns or batches")
        if "INVENTORYENTRIESIN.LIST" in payload or "INVENTORYENTRIESOUT.LIST" in payload:
            hints.add("stock journal in/out entries")
        for tag in set(_LIST_TAG.findall(payload)):  # lists with content only
            if ":" in tag:
                hints.add("unread list: a custom (prefixed) list")
            elif tag not in cls._READ_LISTS:
                hints.add(f"unread list: {tag}")
        return hints

    def master_keys(self, entity: SourceEntity, object_type: str) -> set[str]:
        """GUIDs of every master of a type that Tally lists now (are our requests
        complete?)."""
        spec = envelopes.SPEC_BY_OBJECT_TYPE[object_type]
        body = self._company_post(
            entity,
            lambda name: envelopes.collection_request(envelopes.keys_only(spec), company=name),
        )
        return {
            parser.source_key(element)
            for element in parser.objects(parser.parse_response(body), spec.object_tag)
        }

    def master_names(self, entity: SourceEntity, object_type: str) -> set[str]:
        """Names (and alias names) of every master of a type that Tally lists now."""
        spec = envelopes.SPEC_BY_OBJECT_TYPE[object_type]
        listing = replace(spec, collection_id=f"{spec.collection_id}Names", fetch=("GUID", "NAME"))
        body = self._company_post(
            entity, lambda name: envelopes.collection_request(listing, company=name)
        )
        names: set[str] = set()
        for element in parser.objects(parser.parse_response(body), spec.object_tag):
            names.add(parser.object_name(element) or "")
            names.update(
                (n.text or "").strip() for n in element.findall("LANGUAGENAME.LIST/NAME.LIST/NAME")
            )
            reserved = (element.get("RESERVEDNAME") or "").strip()
            if reserved:
                names.add(reserved)
        return names - {""}

    def ledger_elements(self, entity: SourceEntity) -> list[ET.Element]:
        body = self._company_post(
            entity,
            lambda name: envelopes.collection_request(
                envelopes.LEDGERS,
                company=name,
                balances_period=_period_for(envelopes.LEDGERS, entity),
            ),
        )
        return parser.objects(parser.parse_response(body), envelopes.LEDGERS.object_tag)

    def fetch_transactions(
        self,
        entity: SourceEntity,
        markers: Markers | None = None,
        period: Period | None = None,
    ) -> Iterator[SourceRecord]:
        """With a voucher marker: one request for every voucher altered since, whatever its
        date (an old voucher can be altered today). Otherwise month by month."""
        since = _marker(markers or {}, envelopes.VOUCHERS.object_type)
        if since is not None and period is None:
            body = self._company_post(
                entity,
                lambda name: envelopes.collection_request(
                    envelopes.VOUCHERS, company=name, since_alter_id=since
                ),
            )
            yield from parser.parse_records(body, envelopes.VOUCHERS, entity.key)
            return
        for body in self.voucher_bodies(entity, period):
            yield from parser.parse_records(body, envelopes.VOUCHERS, entity.key)

    # --- chunked fetching (ADR-022) ----------------------------------------------------

    def fetch_plan(
        self, entity: SourceEntity, markers: Markers | None, period: Period | None
    ) -> list[Chunk]:
        """The company record, each master type, then vouchers: by AlterID in one request
        when there's a voucher marker, otherwise month by month."""
        markers = markers or {}
        chunks = [Chunk(envelopes.COMPANIES.object_type)]
        chunks += [Chunk(spec.object_type) for spec in envelopes.MASTER_SPECS]
        voucher = envelopes.VOUCHERS.object_type
        if period is None and _marker(markers, voucher) is not None:
            return [*chunks, Chunk(voucher)]
        return chunks + [Chunk(voucher, month) for month in self.voucher_periods(entity, period)]

    def fetch_chunk(
        self,
        entity: SourceEntity,
        chunk: Chunk,
        markers: Markers | None,
        timeout: float | None = None,
    ) -> list[SourceRecord]:
        markers = markers or {}
        if chunk.object_type == envelopes.COMPANIES.object_type:
            body = self._post(envelopes.collection_request(envelopes.COMPANIES), timeout)
            return [
                r
                for r in parser.parse_records(body, envelopes.COMPANIES, entity.key)
                if r.source_key == entity.key
            ]
        spec = envelopes.SPEC_BY_OBJECT_TYPE[chunk.object_type]
        since = _marker(markers, chunk.object_type)
        period = (chunk.period.start, chunk.period.end) if chunk.period else None
        body = self._company_post(
            entity,
            lambda name: envelopes.collection_request(
                spec,
                company=name,
                period=period,
                since_alter_id=since,
                balances_period=_period_for(spec, entity),
            ),
            timeout,
        )
        return list(parser.parse_records(body, spec, entity.key, period))

    def chunk_keys(
        self, entity: SourceEntity, chunk: Chunk, timeout: float | None = None
    ) -> set[str]:
        spec = envelopes.SPEC_BY_OBJECT_TYPE[chunk.object_type]
        period = (chunk.period.start, chunk.period.end) if chunk.period else None
        body = self._company_post(
            entity,
            lambda name: envelopes.collection_request(
                envelopes.keys_only(spec), company=name, period=period
            ),
            timeout,
        )
        return {r.source_key for r in parser.parse_records(body, spec, entity.key, period)}

    def ping(self) -> None:
        """The company list with a short timeout: does Tally answer at all?"""
        body = self.client.post(
            envelopes.collection_request(envelopes.COMPANIES),
            timeout=get_settings().tally_ping_timeout_sec,
        )
        parser.parse_response(body)

    def list_keys(self, entity: SourceEntity) -> dict[str, set[str]]:
        """GUIDs of every master and voucher that exists now (GUID-only exports). Voucher
        GUIDs are listed month by month: one listing of a large company would be too big."""
        keys: dict[str, set[str]] = {}
        for spec in envelopes.MASTER_SPECS:
            body = self._company_post(
                entity,
                lambda name, spec=spec: envelopes.collection_request(
                    envelopes.keys_only(spec), company=name
                ),
            )
            keys[spec.object_type] = {
                parser.source_key(element)
                for element in parser.objects(parser.parse_response(body), spec.object_tag)
            }
        voucher = envelopes.VOUCHERS.object_type
        keys[voucher] = set()
        for month in self.voucher_periods(entity):
            keys[voucher] |= self.chunk_keys(entity, Chunk(voucher, month))
        return keys

    def to_canonical(self, record: SourceRecord) -> list[CanonicalRecord]:
        return mapping.to_canonical(record)

    @property
    def xml_prefixes_seen(self) -> set[str]:
        """Undeclared namespace prefixes met in Tally's answers (e.g. UDF from TDL
        customisations): names only. Their fields are stored unchanged, not mapped yet."""
        return set(self._prefixes)

    def probe_entity(self, entity: SourceEntity) -> int:
        """Diagnostics: select the company by its name exactly as listed, the way every sync
        request does, and count its groups. No retry, so a rejected name shows up as an
        error. Read-only (an Export request)."""
        body = self._post(
            envelopes.collection_request(envelopes.keys_only(envelopes.GROUPS), company=entity.name)
        )
        return len(parser.objects(parser.parse_response(body), envelopes.GROUPS.object_tag))

    def _company_post(
        self, entity: SourceEntity, build: Callable[[str], str], timeout: float | None = None
    ) -> bytes:
        """Posts a request for one company, built with the company's name exactly as Tally
        lists it. If Tally rejects the name (it may list a company slightly differently
        later, e.g. spacing; pilot run 2026-10-12), looks up the company's current name by
        its GUID and retries once."""
        name = self._names.get(entity.key, entity.name)
        body = self._post(build(name), timeout)
        if not _rejected_company(body):
            return body
        current = next((e.name for e in self.list_entities() if e.key == entity.key), None)
        if current is None or current == name:
            return body  # parsing it raises Tally's own error
        self._names[entity.key] = current
        return self._post(build(current), timeout)


_FOREX = re.compile(r"<AMOUNT[^>]*>[^<]*=")
_QUANTITY = re.compile(r"<(?:ACTUALQTY|BILLEDQTY)[^>]*>([^<]*)<")
_NUMBERS = re.compile(r"\d+(?:\.\d+)?")
_GODOWN = re.compile(r"<GODOWNNAME[^>]*>([^<]*)<")
_BATCH = re.compile(r"<BATCHNAME[^>]*>([^<]*)<")
# A list element with content (Tally writes some lists empty in every voucher).
_LIST_TAG = re.compile(r"<([A-Za-z][\w.:]*\.LIST)(?:\s[^>]*)?>\s*<(?!/)")


def _period_for(spec: envelopes.CollectionSpec, entity: SourceEntity) -> tuple[date, date] | None:
    """For masters with openings: a period starting on the books-beginning date, so
    OPENINGBALANCE is the master's own opening, not the balance at the start of Tally's
    current period (envelopes.OPENING_SPECS). One day is enough: only the start matters."""
    if spec.collection_id not in envelopes.OPENING_SPECS or entity.books_from is None:
        return None
    return (entity.books_from, entity.books_from)


def _canonical(text: str | None) -> Decimal:
    """Tally amount → canonical sign (schema.md 7.1); empty means zero."""
    value = tally_amount(text)
    return -value if value else Decimal(0)


def _rejected_company(body: bytes) -> bool:
    """Tally's answer to a SVCURRENTCOMPANY it can't select (a short error response)."""
    if len(body) > 16_384:
        return False
    try:
        parser.parse_response(body)
    except TallyError as exc:
        return "svcurrentcompany" in str(exc).lower()
    return False


def _marker(markers: Markers, object_type: str) -> int | None:
    value = markers.get(object_type)
    return int(value) if value is not None and value.lstrip("-").isdigit() else None
