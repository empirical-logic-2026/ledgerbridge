"""Recorded Tally responses: saving them, and replaying them without Tally.

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
        known = {spec.collection_id for spec in envelopes.ALL_SPECS}
        known.update(
            spec.collection_id
            for spec in (
                envelopes.LEDGER_BALANCES,
                envelopes.STOCK_VALUES,
                envelopes.BILLS,
                envelopes.LEDGER_OPENING_BILLS,
            )
        )
        # A type this fixture set didn't record answers like Tally with no such objects.
        return [] if collection_id in known else None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        self.requests.append(body)
        files = self._files_for(body)
        if files is None:
            return httpx.Response(200, content=b"<RESPONSE>Unknown Request</RESPONSE>")
        if len(files) == 1 and not _ALTER.search(body):
            return httpx.Response(200, content=(self.directory / files[0]).read_bytes())
        since = int(match.group(1)) if (match := _ALTER.search(body)) else None
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
        return httpx.Response(200, content=content.encode("utf-8"))
