"""Maps a source code to its connector factory (MNT-002: add a source without touching others)."""

from collections.abc import Callable, Mapping
from typing import Any

from connectors.base import Connector

ConnectorFactory = Callable[[Mapping[str, Any]], Connector]


def _tally(config: Mapping[str, Any]) -> Connector:
    from connectors.tally.connector import TallyConnector

    return TallyConnector.from_config(config)


_FACTORIES: dict[str, ConnectorFactory] = {"tally": _tally}

# Human-readable names and versions for app.sources rows.
SOURCE_INFO: dict[str, tuple[str, str]] = {"tally": ("Tally (XML over HTTP)", "0.1.0")}


def available_sources() -> list[str]:
    return sorted(_FACTORIES)


def create_connector(source_code: str, config: Mapping[str, Any]) -> Connector:
    try:
        factory = _FACTORIES[source_code]
    except KeyError:
        raise ValueError(f"Unknown source '{source_code}'") from None
    return factory(config)


def default_config(source_code: str) -> dict[str, Any]:
    """Connection config for a new connection, taken from settings."""
    if source_code == "tally":
        from connectors.tally.connector import TallyConnector

        return TallyConnector.default_config()
    raise ValueError(f"Unknown source '{source_code}'")
