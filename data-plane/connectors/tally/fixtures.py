"""Recorded Tally responses: saving them, and replaying them without Tally.

A fixture directory holds the raw response bytes for each request plus `manifest.json`:

    {"company": "...", "files": {"LBCompanies": "companies.xml", ...},
     "vouchers": [{"from": "2024-04-01", "to": "2024-04-30", "file": "vouchers_2024-04.xml"}]}
"""

import json
import re
from pathlib import Path
from typing import Any

import httpx

from connectors.tally import envelopes

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "tally"

_ID = re.compile(r"<ID>([^<]+)</ID>")
_FROM = re.compile(r'<SVFROMDATE TYPE="Date">(\d{8})</SVFROMDATE>')


def load_manifest(directory: Path) -> dict[str, Any]:
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))


class FixtureTransport(httpx.BaseTransport):
    """Answers Tally export requests from a fixture directory."""

    def __init__(self, directory: Path = DEFAULT_DIR) -> None:
        self.directory = directory
        self.manifest = load_manifest(directory)
        self.requests: list[str] = []

    def _file_for(self, body: str) -> str | None:
        match = _ID.search(body)
        if not match:
            return None
        collection_id = match.group(1)
        if collection_id == envelopes.VOUCHERS.collection_id:
            start = _FROM.search(body)
            if not start:
                return None
            month = f"{start.group(1)[:4]}-{start.group(1)[4:6]}"
            for entry in self.manifest.get("vouchers", []):
                if entry["from"].startswith(month):
                    return str(entry["file"])
            return "__empty__"
        return self.manifest["files"].get(collection_id)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        self.requests.append(body)
        name = self._file_for(body)
        if name == "__empty__":
            # A month without recorded vouchers: answer with an empty collection.
            return httpx.Response(200, content=b"<ENVELOPE><COLLECTION></COLLECTION></ENVELOPE>")
        if name is None:
            return httpx.Response(200, content=b"<RESPONSE>Unknown Request</RESPONSE>")
        return httpx.Response(200, content=(self.directory / name).read_bytes())
