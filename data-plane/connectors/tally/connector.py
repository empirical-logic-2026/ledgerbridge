"""Tally connector: implements connectors.base.Connector over Tally's XML interface."""

import xml.etree.ElementTree as ET  # noqa: N817
from collections.abc import Iterator, Mapping
from datetime import date, timedelta
from typing import Any, Self

import httpx

from connectors.base import ConnectionStatus, Markers, Period, SourceEntity, SourceRecord
from connectors.tally import envelopes, mapping, parser
from connectors.tally.client import TallyClient, TallyError
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

    def __init__(self, client: TallyClient) -> None:
        self.client = client

    @classmethod
    def from_config(
        cls, config: Mapping[str, Any], transport: httpx.BaseTransport | None = None
    ) -> Self:
        return cls(
            TallyClient(
                str(config["url"]),
                timeout=float(config.get("timeout_sec", 120)),
                transport=transport,
            )
        )

    @staticmethod
    def default_config() -> dict[str, Any]:
        return {"url": get_settings().tally_url, "timeout_sec": 120}

    def _post(self, request_xml: str) -> bytes:
        return self.client.post(request_xml)

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
            request = envelopes.collection_request(
                spec, company=entity.name, since_alter_id=_marker(markers, spec.object_type)
            )
            yield from parser.parse_records(self._post(request), spec, entity.key)

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
            request = envelopes.collection_request(
                envelopes.VOUCHERS, company=entity.name, period=(month.start, month.end)
            )
            yield self._post(request)

    def voucher_elements(
        self, entity: SourceEntity, period: Period | None = None
    ) -> Iterator[ET.Element]:
        for body in self.voucher_bodies(entity, period):
            yield from parser.objects(parser.parse_response(body), envelopes.VOUCHERS.object_tag)

    def ledger_balance_elements(self, entity: SourceEntity) -> list[ET.Element]:
        """Ledgers with opening/closing balances and Tally's own $$IsDr judgement, for
        Tally's current period (no explicit dates, so Educational mode cannot reject them)."""
        request = envelopes.collection_request(envelopes.LEDGER_BALANCES, company=entity.name)
        body = self._post(request)
        return parser.objects(parser.parse_response(body), envelopes.LEDGER_BALANCES.object_tag)

    def ledger_elements(self, entity: SourceEntity) -> list[ET.Element]:
        body = self._post(envelopes.collection_request(envelopes.LEDGERS, company=entity.name))
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
            request = envelopes.collection_request(
                envelopes.VOUCHERS, company=entity.name, since_alter_id=since
            )
            yield from parser.parse_records(self._post(request), envelopes.VOUCHERS, entity.key)
            return
        for body in self.voucher_bodies(entity, period):
            yield from parser.parse_records(body, envelopes.VOUCHERS, entity.key)

    def list_keys(self, entity: SourceEntity) -> dict[str, set[str]]:
        """GUIDs of every master and voucher that exists now (GUID-only exports)."""
        keys: dict[str, set[str]] = {}
        for spec in (*envelopes.MASTER_SPECS, envelopes.VOUCHERS):
            body = self._post(
                envelopes.collection_request(envelopes.keys_only(spec), company=entity.name)
            )
            keys[spec.object_type] = {
                parser.source_key(element)
                for element in parser.objects(parser.parse_response(body), spec.object_tag)
            }
        return keys

    def to_canonical(self, record: SourceRecord) -> list[CanonicalRecord]:
        return mapping.to_canonical(record)


def _marker(markers: Markers, object_type: str) -> int | None:
    value = markers.get(object_type)
    return int(value) if value is not None and value.lstrip("-").isdigit() else None
