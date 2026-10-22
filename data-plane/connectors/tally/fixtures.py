"""Recorded Tally responses, replayed without Tally: the tests' stand-in for TallyPrime.

Where it fits: `FixtureTransport` plugs into `TallyClient` (as its httpx transport) and
answers each request from files recorded from LedgerBridge Test Co by
`python -m connectors.tally.tools capture-fixtures`, so the connector, sync and validation
run unchanged in tests and CI.

A fixture directory holds the raw response bytes for each request plus `manifest.json`:

    {"company": "...", "files": {"LBCompanies": "companies.xml", ...},
     "vouchers": [{"from": "2024-04-01", "to": "2024-04-30", "file": "vouchers_2024-04.xml"}]}
"""

import json
import re
import xml.etree.ElementTree as ET  # noqa: N817
from pathlib import Path
from typing import Any

import httpx

from connectors.tally import envelopes, parser

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "tally"

_ID = re.compile(r"<ID>([^<]+)</ID>")
_FROM = re.compile(r'<SVFROMDATE TYPE="Date">(\d{8})</SVFROMDATE>')
_ALTER = re.compile(r"\$AlterID &gt; (\d+)")

# Collections Tally knows: one the recording didn't include answers with no objects.
_KNOWN = frozenset(
    spec.collection_id
    for spec in (
        *envelopes.ALL_SPECS,
        envelopes.LEDGER_BALANCES,
        envelopes.STOCK_VALUES,
        envelopes.STOCK_GROUP_VALUES,
        envelopes.GODOWN_VALUES,
        envelopes.GROUP_BALANCES,
        envelopes.BILLS,
        envelopes.LEDGER_OPENING_BILLS,
    )
)


def load_manifest(directory: Path) -> dict[str, Any]:
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))


class FixtureTransport(httpx.BaseTransport):
    """Answers Tally export requests from a fixture directory."""

    def __init__(self, directory: Path = DEFAULT_DIR) -> None:
        self.directory = directory
        self.manifest = load_manifest(directory)
        self.requests: list[str] = []

    def _files_for(self, body: str) -> list[str] | None:
        """Recorded files that answer this request; None if the request isn't recognised."""
        match = _ID.search(body)
        if not match:
            return None
        # Keys-only and names-only listings answer with the same objects.
        collection_id = match.group(1).removesuffix("Keys").removesuffix("Names")
        # Voucher counts list the same vouchers (with their type only).
        if collection_id in (
            envelopes.VOUCHERS.collection_id,
            envelopes.VOUCHER_COUNTS.collection_id,
        ):
            vouchers = self.manifest.get("vouchers", [])
            start = _FROM.search(body)
            if not start:  # incremental or key listing: every recorded voucher
                return [str(entry["file"]) for entry in vouchers]
            month = f"{start.group(1)[:4]}-{start.group(1)[4:6]}"
            return [str(e["file"]) for e in vouchers if e["from"].startswith(month)]
        if collection_id in self.manifest["files"]:
            return [self.manifest["files"][collection_id]]
        # A type this fixture set didn't record answers like Tally with no such objects.
        return [] if collection_id in _KNOWN else None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        self.requests.append(body)
        files = self._files_for(body)
        if files is None:
            report = _ID.search(body)
            if report and report.group(1) in (
                envelopes.TRIAL_BALANCE,
                envelopes.BALANCE_SHEET,
                envelopes.PROFIT_AND_LOSS,
            ):
                # The baseline fixture set records collections, not statement exports. These
                # empty test reports keep collection-validation tests independent of report
                # fixtures; statement parsing uses the dedicated recorded report fixtures.
                content = (
                    b"<ENVELOPE><DSPACCNAME><DSPDISPNAME>Opening Stock</DSPDISPNAME>"
                    b"</DSPACCNAME><PLAMT><PLSUBAMT>0.00</PLSUBAMT></PLAMT>"
                    b"<DSPACCNAME><DSPDISPNAME>Less: Closing Stock</DSPDISPNAME>"
                    b"</DSPACCNAME><PLAMT><PLSUBAMT>0.00</PLSUBAMT></PLAMT></ENVELOPE>"
                    if report.group(1) == envelopes.PROFIT_AND_LOSS
                    else b"<ENVELOPE/>"
                )
                return httpx.Response(200, content=content)
            return httpx.Response(200, content=b"<RESPONSE>Unknown Request</RESPONSE>")
        changed_since = _ALTER.search(body)
        if len(files) == 1 and not changed_since:
            return httpx.Response(200, content=(self.directory / files[0]).read_bytes())
        since = int(changed_since.group(1)) if changed_since else None
        return httpx.Response(200, content=self._combined(files, since))

    def _combined(self, files: list[str], since: int | None) -> bytes:
        """The objects of several recorded files in one answer; with `since`, only those
        altered after that AlterID (an incremental request)."""
        objects = []
        for name in files:
            root = parser.parse_response((self.directory / name).read_bytes())
            for collection in root.iter("COLLECTION"):
                for child in collection:
                    alter = parser.alter_id(child)
                    if since is None or (alter is not None and alter > since):
                        child.tail = None
                        objects.append(ET.tostring(child, encoding="unicode"))
        content = "<ENVELOPE><COLLECTION>" + "".join(objects) + "</COLLECTION></ENVELOPE>"
        return content.encode("utf-8")
