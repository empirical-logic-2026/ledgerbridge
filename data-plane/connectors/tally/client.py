"""HTTP client for Tally's XML interface."""

import logging
import time
from types import TracebackType
from typing import Self

import httpx

from connectors.base import SourceTimeoutError

logger = logging.getLogger(__name__)


class TallyError(RuntimeError):
    """Tally could not be reached or rejected a request."""


class TallySlowError(TallyError, SourceTimeoutError):
    """Tally didn't answer within the timeout. Not retried here: resending the same large
    request rarely helps; the sync checks Tally and splits the request instead (ADR-022)."""


def decode_response(body: bytes) -> str:
    """Decode a Tally response. Tally.ERP 9 commonly answers in UTF-16; TallyPrime in UTF-8."""
    if body.startswith((b"\xff\xfe", b"\xfe\xff")):
        return body.decode("utf-16")
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
    """Posts export requests to Tally and returns raw response bytes."""

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
        if "<TALLYREQUEST>Export</TALLYREQUEST>" not in request_xml:
            # Read-only towards sources (CON-008): never send Import or other requests.
            raise ValueError("Only Tally Export requests are allowed")
        attempt = 0
        while True:
            try:
                response = self._http.post(
                    self.url,
                    content=request_xml.encode("utf-8"),
                    headers={"Content-Type": "text/xml; charset=utf-8"},
                    timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
                )
                response.raise_for_status()
                return response.content
            except httpx.TimeoutException as exc:
                if isinstance(exc, httpx.ConnectTimeout) and attempt < self._retries:
                    attempt += 1
                    logger.warning("Tally connect timed out; retry %d", attempt)
                    time.sleep(2**attempt)
                    continue
                limit = timeout if timeout is not None else self.timeout
                raise TallySlowError(
                    f"Tally didn't answer within {limit:g} s ({type(exc).__name__})"
                ) from exc
            except httpx.TransportError as exc:
                if attempt >= self._retries:
                    raise TallyError(
                        f"Tally not reachable at {self.url} ({type(exc).__name__})"
                    ) from exc
                attempt += 1
                logger.warning("Tally request failed (%s); retry %d", type(exc).__name__, attempt)
                time.sleep(2**attempt)
            except httpx.HTTPStatusError as exc:
                raise TallyError(f"Tally returned HTTP {exc.response.status_code}") from exc

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
