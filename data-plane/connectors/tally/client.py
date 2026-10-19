"""HTTP client for Tally's XML interface: the only code that talks to Tally over the network.

Where it fits: `connector.py` builds a request with `envelopes.py`, sends it through
`TallyClient.post`, and hands the raw bytes to `parser.py`. The client refuses anything but
an Export request, so the connector can never change data in Tally (CON-008).
"""

import logging
import time
from types import TracebackType
from typing import Self

import httpx

from connectors.base import SourceTimeoutError

logger = logging.getLogger(__name__)

EXPORT_MARKER = "<TALLYREQUEST>Export</TALLYREQUEST>"


class TallyError(RuntimeError):
    """Tally could not be reached or rejected a request."""


class TallySlowError(TallyError, SourceTimeoutError):
    """Tally didn't answer within the timeout. Not retried here: resending the same large
    request rarely helps; the sync checks Tally and splits the request instead (ADR-022)."""


def decode_response(body: bytes) -> str:
    """Decode a Tally response. Tally.ERP 9 commonly answers in UTF-16; TallyPrime in UTF-8."""
    if body.startswith((b"\xff\xfe", b"\xfe\xff")):
        return body.decode("utf-16")
    # UTF-16 without a byte order mark: one of the first two bytes of "<" is zero.
    if len(body) >= 2 and (body[0] == 0 or body[1] == 0):
        return body.decode("utf-16-be" if body[0] == 0 else "utf-16-le")
    if body.startswith(b"\xef\xbb\xbf"):
        return body[3:].decode("utf-8")
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        # Older Tally releases may emit Windows-1252 text without declaring it.
        return body.decode("cp1252", errors="replace")


class TallyClient:
    """Posts export requests to Tally and returns raw response bytes.

    A failed connection is retried (`retries` times, waiting 2 s, then 4 s, ...): Tally may be
    busy for a moment. A request Tally accepted but didn't answer in time is not retried
    (TallySlowError), and neither is an HTTP error status.
    """

    def __init__(
        self,
        url: str,
        timeout: float = 120.0,
        retries: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self._retries = retries
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def post(self, request_xml: str, timeout: float | None = None) -> bytes:
        """`timeout` overrides the client's for this request (e.g. a quick health check)."""
        if EXPORT_MARKER not in request_xml:
            # Read-only towards sources (CON-008): never send Import or other requests.
            raise ValueError("Only Tally Export requests are allowed")
        attempt = 0
        while True:
            try:
                return self._send(request_xml, timeout)
            except httpx.TimeoutException as exc:
                # Only a connect timeout is worth another try; Tally never saw the request.
                if not isinstance(exc, httpx.ConnectTimeout) or attempt >= self._retries:
                    limit = timeout if timeout is not None else self.timeout
                    raise TallySlowError(
                        f"Tally didn't answer within {limit:g} s ({type(exc).__name__})"
                    ) from exc
                attempt += 1
                logger.warning("Tally connect timed out; retry %d", attempt)
            except httpx.TransportError as exc:
                if attempt >= self._retries:
                    raise TallyError(
                        f"Tally not reachable at {self.url} ({type(exc).__name__})"
                    ) from exc
                attempt += 1
                logger.warning("Tally request failed (%s); retry %d", type(exc).__name__, attempt)
            except httpx.HTTPStatusError as exc:
                raise TallyError(f"Tally returned HTTP {exc.response.status_code}") from exc
            time.sleep(2**attempt)  # 2 s, then 4 s, ...

    def _send(self, request_xml: str, timeout: float | None) -> bytes:
        """One HTTP request; raises httpx's errors, including for an error status."""
        response = self._http.post(
            self.url,
            content=request_xml.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8"},
            timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
        )
        response.raise_for_status()
        return response.content

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
