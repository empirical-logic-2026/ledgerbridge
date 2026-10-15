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
- `bad_values`: data that doesn't fit the accounting tables (pilot 2026-10-13): every
  ledger has a GSTIN of 40 characters; on the 1st of each month the first voucher has a
  voucher number and a reference of 300 characters and a reference date in year 1, on the
  2nd its rate is out of range, and on 2026-05-03 its amounts are too large to store at
  all (only that voucher may fail). See BAD_VOUCHER.
- `name_variants`: references that differ from the names they mean (ADR-027): the reserved
  group "Indirect Expenses" is renamed "Overheads" (its ledgers still name it), customers
  name their group as "sundry  debtors", the ledger "Capital" names a reserved group that
  isn't fetched ("Suspense A/c" is left out), two ledgers are renamed ("Salary" to an
  accented name, "Electricity" to one with "&"), and the first voucher of some April days
  names a ledger differently: see NAME_VARIANTS. Two custom voucher types are added,
  "Memo Base" under Tally's "Memorandum" and "Payment Memo" under "Memo Base"; the first
  voucher of 12 April is a "Payment Memo" that doesn't balance (memorandum vouchers don't
  post to the books, so it must not count).

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
BAD_VOUCHER = date(2026, 5, 3)  # with bad_values: amounts too large for DECIMAL(20,4)
LONG = 300
NFC_NAME = "Caf" + chr(0xE9) + " Salary"  # the ledger "Salary", renamed
NFD_NAME = "Cafe" + chr(0x301) + " Salary"  # the same name, decomposed
MEMO_DAY = 12
CUSTOM_TYPES = (
    '<VOUCHERTYPE NAME="Memo Base" RESERVEDNAME=""><GUID>vt-memo-base</GUID>'
    "<ALTERID>9001</ALTERID><PARENT>Memorandum</PARENT></VOUCHERTYPE>"
    '<VOUCHERTYPE NAME="Payment Memo" RESERVEDNAME=""><GUID>vt-payment-memo</GUID>'
    "<ALTERID>9002</ALTERID><PARENT>Memo Base</PARENT></VOUCHERTYPE>"
)
# April day -> (ledger named in the voucher's first entry instead of "Rent", resolves?)
NAME_VARIANTS = {
    5: ("rent", True),  # case
    6: ("Salary  Payable", True),  # double space
    7: (NFD_NAME, True),  # Unicode normalisation
    8: ("Power &amp;amp; Fuel", True),  # XML entity escaped twice
    9: ("R" + chr(0x435) + "nt", False),  # a Cyrillic look-alike letter
    10: ("Sales-Goods", False),  # punctuation ("Sales - Goods")
    11: ("Nowhere Ledger", False),  # no close match
}


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
        bad_values: bool = False,
        name_variants: bool = False,
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
        self.bad_values = bad_values
        self.name_variants = name_variants
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
        if collection == envelopes.VOUCHER_COUNTS.collection_id:
            return self._vouchers(request, body, keys=True, current=current, with_type=True)
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
        if self.name_variants:
            response = httpx.Response(200, content=self._vary(collection, response.content))
        if self.bad_values:
            content = re.sub(
                rb"(</LEDGER>)",
                b"<PARTYGSTIN>" + b"G" * 40 + b"</PARTYGSTIN>" + rb"\1",
                response.content,
            )
            response = httpx.Response(200, content=content)
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
        self,
        request: httpx.Request,
        body: str,
        keys: bool,
        current: re.Match | None,
        with_type: bool = False,
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
                    kind = (
                        f"<DATE>{day:%Y%m%d}</DATE><VOUCHERTYPENAME>"
                        f"{self.voucher_template.findtext('VOUCHERTYPENAME')}</VOUCHERTYPENAME>"
                        if with_type
                        else ""
                    )
                    out.append(
                        f"<VOUCHER><GUID>{guid}</GUID><ALTERID>{alter}</ALTERID>{kind}</VOUCHER>"
                    )
                else:
                    out.append(self._voucher(guid, alter, day, i))
            day += timedelta(days=1)
        return self._xml("".join(out))

    def _voucher(self, guid: str, alter: int, day: date, number: int) -> str:
        voucher = copy.deepcopy(self.voucher_template)
        voucher.find("GUID").text = guid
        voucher.find("ALTERID").text = str(alter)
        voucher.find("DATE").text = f"{day:%Y%m%d}"
        effective = voucher.find("EFFECTIVEDATE")
        if effective is not None:  # Tally's effective date: the voucher's own, as usual
            effective.text = f"{day:%Y%m%d}"
        voucher.find("VOUCHERNUMBER").text = f"S{day:%m%d}-{number}"
        narration = voucher.find("NARRATION")
        if narration is not None:
            narration.text = "synthetic"
        if self.bad_values and number == 0:
            self._spoil(voucher, day)
        variant = None
        if self.name_variants and number == 0 and day.month == 4:
            variant = NAME_VARIANTS.get(day.day)
        voucher.tail = None
        text = ET.tostring(voucher, encoding="unicode")
        if self.name_variants and number == 0 and day == date(2026, 4, MEMO_DAY):
            text = re.sub(r"(<VOUCHERTYPENAME[^>]*>)[^<]*", r"\g<1>Payment Memo", text, count=1)
            text = text.replace(">1000.00</AMOUNT>", ">999.00</AMOUNT>", 1)  # unbalanced
        if variant is not None:
            # As raw XML text: an entity escaped twice must stay so in the response.
            text = text.replace(">Rent</LEDGERNAME>", f">{variant[0]}</LEDGERNAME>", 1)
            if variant[0] == "Sales-Goods":  # the punctuation case replaces "Cash"
                text = text.replace(f">{variant[0]}</LEDGERNAME>", ">Rent</LEDGERNAME>", 1)
                text = text.replace(">Cash</LEDGERNAME>", ">Sales-Goods</LEDGERNAME>", 1)
        if self.udf:
            text = text.replace(
                "</VOUCHER>",
                '<UDF:REFNO.LIST DESC="`RefNo`" ISLIST="YES" TYPE="String" INDEX="2">'
                f'<UDF:REFNO DESC="`RefNo`">R{number}</UDF:REFNO></UDF:REFNO.LIST>'
                '<TDL:FLAG.LIST TYPE="Logical"><TDL:FLAG>Yes</TDL:FLAG></TDL:FLAG.LIST></VOUCHER>',
            )
        return text

    @staticmethod
    def _vary(collection: str, content: bytes) -> bytes:
        """Masters for `name_variants`."""
        text = content.decode("utf-8")
        if collection == envelopes.GROUPS.collection_id:
            text = text.replace('GROUP NAME="Indirect Expenses"', 'GROUP NAME="Overheads"')
            text = text.replace("<NAME>Indirect Expenses</NAME>", "<NAME>Overheads</NAME>")
            text = re.sub(r'<GROUP NAME="Suspense A/c".*?</GROUP>', "", text, flags=re.S)
        if collection == envelopes.VOUCHER_TYPES.collection_id:
            text = text.replace("</COLLECTION>", CUSTOM_TYPES + "</COLLECTION>", 1)
        if collection == envelopes.LEDGERS.collection_id:
            text = text.replace(
                '<PARENT TYPE="String">Sundry Debtors</PARENT>',
                '<PARENT TYPE="String">sundry  debtors</PARENT>',
            )
            text = text.replace(
                '<PARENT TYPE="String">Capital Account</PARENT>',
                '<PARENT TYPE="String">Suspense A/c</PARENT>',
            )
            for old, new in (("Salary", NFC_NAME), ("Electricity", "Power &amp; Fuel")):
                text = text.replace(f'LEDGER NAME="{old}"', f'LEDGER NAME="{new}"')
                text = text.replace(f"<NAME>{old}</NAME>", f"<NAME>{new}</NAME>")
        return text.encode("utf-8")

    @staticmethod
    def _spoil(voucher: ET.Element, day: date) -> None:
        """Values that don't fit the accounting tables (see `bad_values`)."""
        if day.day == 1:
            voucher.find("VOUCHERNUMBER").text = "N" * LONG
            voucher.find("REFERENCE").text = "R" * LONG
            voucher.find("REFERENCEDATE").text = "00010101"
        if day.day == 2:
            entry = voucher.find("ALLLEDGERENTRIES.LIST")
            ET.SubElement(entry, "RATE").text = "1" * 20  # not read for ledger entries
            stock = ET.SubElement(voucher, "ALLINVENTORYENTRIES.LIST")
            ET.SubElement(stock, "STOCKITEMNAME").text = "Widget"
            ET.SubElement(stock, "ACTUALQTY").text = " 1 Nos"
            ET.SubElement(stock, "RATE").text = "1" * 20 + "/Nos"
            ET.SubElement(stock, "AMOUNT").text = "0"
        if day == BAD_VOUCHER:
            for entry in voucher.findall("ALLLEDGERENTRIES.LIST"):
                amount = entry.find("AMOUNT")
                negative = (amount.text or "").strip().startswith("-")
                amount.text = ("-" if negative else "") + "9" * 18 + ".00"

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
