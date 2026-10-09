"""Tally connector: implements connectors.base.Connector over Tally's XML interface."""

import xml.etree.ElementTree as ET  # noqa: N817
from collections.abc import Iterator, Mapping
from datetime import date, timedelta
from typing import Any, Self

import httpx

from connectors.base import ConnectionStatus, Period, SourceEntity, SourceRecord
from connectors.tally import envelopes, parser
from connectors.tally.client import TallyClient, TallyError
from core.config import get_settings


def month_periods(start: date, end: date) -> Iterator[Period]:
    """Calendar-month chunks covering [start, end]."""
    current = start
    while current <= end:
        next_month = (current.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield Period(current, min(end, next_month - timedelta(days=1)))
        current = next_month


class TallyConnector:
    source_code = "tally"

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
        self, entity: SourceEntity, since_marker: str | None = None
    ) -> Iterator[SourceRecord]:
        # since_marker (AlterID) is used from M3; M1 always fetches everything.
        for spec in envelopes.MASTER_SPECS:
            body = self._post(envelopes.collection_request(spec, company=entity.name))
            yield from parser.parse_records(body, spec, entity.key)

    def voucher_periods(self, entity: SourceEntity, period: Period | None = None) -> list[Period]:
        if period is not None:
            return list(month_periods(period.start, period.end))
        if entity.books_from is None:
            raise TallyError(f"Company '{entity.name}' has no books-from date; pass a period")
        # Tally's ENDINGAT is not a reliable "books to" date (TallyPrime can report the
        # books-from date), so never stop before today.
        end = max(entity.books_to or date.today(), date.today())
        return list(month_periods(entity.books_from, end))

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

    def ledger_elements(self, entity: SourceEntity) -> list[ET.Element]:
        body = self._post(envelopes.collection_request(envelopes.LEDGERS, company=entity.name))
        return parser.objects(parser.parse_response(body), envelopes.LEDGERS.object_tag)

    def fetch_transactions(
        self,
        entity: SourceEntity,
        since_marker: str | None = None,
        period: Period | None = None,
    ) -> Iterator[SourceRecord]:
        for body in self.voucher_bodies(entity, period):
            yield from parser.parse_records(body, envelopes.VOUCHERS, entity.key)

    def to_canonical(self, record: SourceRecord) -> object:
        raise NotImplementedError("Tally to canonical mapping is built in M3")
