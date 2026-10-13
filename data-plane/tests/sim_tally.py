"""A simulated TallyPrime for large-sync tests (ADR-022).

Masters come from the recorded test-company fixtures. Vouchers are synthetic: a recorded
voucher cloned `per_day` times for every day of the books, with new GUIDs, AlterIDs, dates
and numbers. Behaviour can be made difficult:

- `max_days`: a voucher request covering more days than this times out (too large);
- `slow_months` / `slow_max_days`: in those months the limit is tighter;
- `fail_days`: a request including one of these days always times out;
- `dead_after`: after this many voucher requests, Tally stops answering anything (also the
  minimal check) until `revive()`;
- `empty_partial`: requests not aligned to whole months return nothing;
- `widen_partial`: requests not aligned to whole months return everything from the start of
  the books, like TallyPrime in Educational mode (seen 2026-10-12);
- `companies`: how many companies are listed (vouchers are generated per company);
- `needs_timeout`: month -> seconds; a request for that month times out unless the client
  allows at least that long (read timeout);
- `slow_listing`: months whose keys-only listing always times out;
- `missing_months`: months whose voucher request returns nothing (their listing doesn't).
- `busy_after_timeout`: after a voucher request times out, Tally is still busy with it: the
  next this many other requests (e.g. the source check) time out too;
- `udf`: masters and vouchers carry user-defined fields with an undeclared `UDF:` prefix,
  as TDL customisations export them (pilot 2026-10-13).

Keys-only listings never time out (they're small). Every voucher request is logged.
"""

import copy
import re
import xml.etree.ElementTree as ET  # noqa: N817
from datetime import date, datetime, timedelta

import httpx

from connectors.tally import envelopes, parser
from connectors.tally.fixtures import DEFAULT_DIR, FixtureTransport

_ID = re.compile(r"<ID>([^<]+)</ID>")
_FROM = re.compile(r'<SVFROMDATE TYPE="Date">(\d{8})</SVFROMDATE>')
_TO = re.compile(r'<SVTODATE TYPE="Date">(\d{8})</SVTODATE>')
_SINCE = re.compile(r"\$AlterID &gt; (\d+)")
_CURRENT = re.compile(r"<SVCURRENTCOMPANY>(.*?)</SVCURRENTCOMPANY>", re.S)

BOOKS_START = date(2026, 4, 1)
BOOKS_END = date(2026, 9, 30)


def _day(text: str) -> date:
    return datetime.strptime(text, "%Y%m%d").date()


class SimTally(FixtureTransport):
    def __init__(
        self,
        per_day: int = 2,
        companies: int = 1,
        max_days: int | None = None,
        slow_months: tuple[date, ...] = (),
        slow_max_days: int = 7,
        fail_days: tuple[date, ...] = (),
        dead_after: int | None = None,
        empty_partial: bool = False,
        widen_partial: bool = False,
        needs_timeout: dict[date, float] | None = None,
        slow_listing: tuple[date, ...] = (),
        missing_months: tuple[date, ...] = (),
        busy_after_timeout: int = 0,
        udf: bool = False,
    ) -> None:
        super().__init__(DEFAULT_DIR)
        self.per_day = per_day
        self.max_days = max_days
        self.slow_months = set(slow_months)
        self.slow_max_days = slow_max_days
        self.fail_days = set(fail_days)
        self.dead_after = dead_after
        self.empty_partial = empty_partial
        self.widen_partial = widen_partial
        self.needs_timeout = needs_timeout or {}
        self.slow_listing = set(slow_listing)
        self.missing_months = set(missing_months)
        self.busy_after_timeout = busy_after_timeout
        self.busy = 0
        self.udf = udf
        self.timeouts_seen: list[float | None] = []
        self.dead = False
        self.voucher_requests = 0
        self.log: list[tuple[str, date | None, date | None]] = []  # (kind, from, to incl.)
        root = parser.parse_response((DEFAULT_DIR / "companies.xml").read_bytes())
        self.company_template = parser.objects(root, "COMPANY")[0]
        self.names = [f"Sim Co {n}" for n in range(1, companies + 1)]
        self.guids = [f"sim-company-{n}" for n in range(1, companies + 1)]
        april = parser.parse_response((DEFAULT_DIR / "vouchers_2026-04.xml").read_bytes())
        self.voucher_template = parser.objects(april, "VOUCHER")[0]

    def revive(self) -> None:
        self.dead = False
        self.dead_after = None

    @property
    def total_vouchers(self) -> int:
        return ((BOOKS_END - BOOKS_START).days + 1) * self.per_day

    # --- responses --------------------------------------------------------------------

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.dead:
            raise httpx.ReadTimeout("simulated: Tally stopped answering", request=request)
        body = request.read().decode("utf-8")
        collection = (_ID.search(body) or [None, ""])[1]
        current = _CURRENT.search(body)
        if self.busy:
            self.busy -= 1
            raise httpx.ReadTimeout(
                "simulated: still busy with an abandoned request", request=request
            )
        if collection == envelopes.COMPANIES.collection_id and current is None:
            return self._xml(self._companies())
        if collection.startswith(envelopes.VOUCHERS.collection_id):
            try:
                return self._vouchers(
                    request, body, keys=collection.endswith("Keys"), current=current
                )
            except httpx.ReadTimeout:
                self.busy = self.busy_after_timeout
                raise
        response = super().handle_request(request)
        if self.udf:
            response = httpx.Response(200, content=self._with_udf(response.content))
        company = self.names.index(current.group(1)) if current else 0
        if company == 0:
            return response
        # Real GUIDs are unique per company: give the other companies' masters their own.
        content = re.sub(
            rb"<GUID([^>]*)>([^<]+)</GUID>", rb"<GUID\1>c%d-\2</GUID>" % company, response.content
        )
        return httpx.Response(200, content=content)

    def _companies(self) -> str:
        companies = []
        for name, guid in zip(self.names, self.guids, strict=True):
            company = copy.deepcopy(self.company_template)
            company.set("NAME", name)
            company.find("NAME").text = name
            company.find("GUID").text = guid
            companies.append(ET.tostring(company, encoding="unicode"))
        return "".join(companies)

    def _vouchers(
        self, request: httpx.Request, body: str, keys: bool, current: re.Match | None
    ) -> httpx.Response:
        start = _day(m.group(1)) if (m := _FROM.search(body)) else BOOKS_START
        end = _day(m.group(1)) - timedelta(days=1) if (m := _TO.search(body)) else BOOKS_END
        since = int(m.group(1)) if (m := _SINCE.search(body)) else None
        company = self.names.index(current.group(1)) if current else 0
        month = start.replace(day=1)
        whole = start.day == 1 and (end + timedelta(days=1)).day == 1
        if not keys:
            self.voucher_requests += 1
            self.log.append(("vouchers", start, end))
            read = (request.extensions.get("timeout") or {}).get("read")
            self.timeouts_seen.append(read)
            if self.dead_after is not None and self.voucher_requests > self.dead_after:
                self.dead = True
                raise httpx.ReadTimeout("simulated: Tally stopped answering", request=request)
            days = (end - start).days + 1
            limit = self.slow_max_days if month in self.slow_months else None
            limit = (
                min(x for x in (limit, self.max_days) if x) if (limit or self.max_days) else None
            )
            if limit is not None and days > limit:
                raise httpx.ReadTimeout("simulated: too large", request=request)
            if month in self.needs_timeout and (read is None or read < self.needs_timeout[month]):
                raise httpx.ReadTimeout("simulated: needs a longer timeout", request=request)
            if any(start <= d <= end for d in self.fail_days):
                raise httpx.ReadTimeout("simulated: this day never answers", request=request)
            if whole and month in self.missing_months:
                return self._xml("")
        else:
            self.log.append(("keys", start, end))
            if month in self.slow_listing:
                raise httpx.ReadTimeout("simulated: listing too slow", request=request)
        if self.empty_partial and not whole:
            return self._xml("")
        if self.widen_partial and not whole:
            start = BOOKS_START
        out = []
        day = max(start, BOOKS_START)
        while day <= min(end, BOOKS_END):
            for i in range(self.per_day):
                alter = 10_000 + ((day - BOOKS_START).days * self.per_day + i) * 2
                if since is not None and alter <= since:
                    continue
                guid = f"sim{company}-{day:%Y%m%d}-{i:04d}"
                if keys:
                    out.append(f"<VOUCHER><GUID>{guid}</GUID><ALTERID>{alter}</ALTERID></VOUCHER>")
                else:
                    out.append(self._voucher(guid, alter, day, i))
            day += timedelta(days=1)
        return self._xml("".join(out))

    def _voucher(self, guid: str, alter: int, day: date, number: int) -> str:
        voucher = copy.deepcopy(self.voucher_template)
        voucher.find("GUID").text = guid
        voucher.find("ALTERID").text = str(alter)
        voucher.find("DATE").text = f"{day:%Y%m%d}"
        voucher.find("VOUCHERNUMBER").text = f"S{day:%m%d}-{number}"
        narration = voucher.find("NARRATION")
        if narration is not None:
            narration.text = "synthetic"
        voucher.tail = None
        text = ET.tostring(voucher, encoding="unicode")
        if self.udf:
            text = text.replace(
                "</VOUCHER>",
                '<UDF:REFNO.LIST DESC="`RefNo`" ISLIST="YES" TYPE="String" INDEX="2">'
                f'<UDF:REFNO DESC="`RefNo`">R{number}</UDF:REFNO></UDF:REFNO.LIST>'
                '<TDL:FLAG.LIST TYPE="Logical"><TDL:FLAG>Yes</TDL:FLAG></TDL:FLAG.LIST></VOUCHER>',
            )
        return text

    @staticmethod
    def _with_udf(content: bytes) -> bytes:
        """Adds UDF-prefixed fields to every ledger and group, as a TDL customisation would."""
        udf = (
            b'<UDF:CUSTOMCODE.LIST DESC="`CustomCode`" ISLIST="YES" TYPE="String" INDEX="1">'
            b'<UDF:CUSTOMCODE DESC="`CustomCode`">X1</UDF:CUSTOMCODE></UDF:CUSTOMCODE.LIST>'
        )
        return re.sub(rb"(</(?:LEDGER|GROUP)>)", udf + rb"\1", content)

    @staticmethod
    def _xml(objects: str) -> httpx.Response:
        content = (
            f"<ENVELOPE><BODY><DATA><COLLECTION>{objects}</COLLECTION></DATA></BODY></ENVELOPE>"
        )
        return httpx.Response(200, content=content.encode("utf-8"))
