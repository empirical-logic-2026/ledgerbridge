"""Which source entities (companies) a connection works with: one lookup for every command.

A connection stores each entity's **key** (for Tally, the company GUID) together with the
name it had when it was configured, in `connections.config.entities`:

    [{"key": "<guid>", "name": "<name as the source reported it>"}, ...]

Every command (sync, deletion check, validation, extract) finds the entities by key, so a
source that reports a name slightly differently later (spacing, punctuation; pilot run,
2026-10-12) still finds them. Names are only compared when a person types them, and then
exactly as the source reports them: no trimming, no case or whitespace folding.

Older connections stored plain names; those are still found by exact name until
`connect` stores their keys.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from connectors.base import Connector, SourceEntity
from core.models import Connection


@dataclass(frozen=True)
class ConfiguredEntity:
    key: str | None  # None for entries stored before keys were (plain names)
    name: str


class EntityLookupError(LookupError):
    """Some entities aren't available in the source. Counts only: never names."""

    def __init__(self, missing: int, wanted: int) -> None:
        super().__init__(
            f"{missing} of {wanted} configured entities are not available in the source "
            "(run entity-check for details)"
        )
        self.missing = missing


def configured(connection: Connection) -> list[ConfiguredEntity]:
    entries = []
    for item in connection.config.get("entities") or []:
        if isinstance(item, dict):
            entries.append(ConfiguredEntity(item.get("key"), str(item.get("name", ""))))
        else:
            entries.append(ConfiguredEntity(None, str(item)))
    return entries


def to_config(entities: Iterable[SourceEntity]) -> list[dict[str, str]]:
    return [{"key": e.key, "name": e.name} for e in entities]


def by_names(
    available: Sequence[SourceEntity], names: Sequence[str]
) -> tuple[list[SourceEntity], list[str]]:
    """Entities whose name is exactly one of `names` (as typed), and the names not found."""
    exact = {e.name: e for e in available}
    found = [exact[n] for n in dict.fromkeys(names) if n in exact]
    return found, [n for n in dict.fromkeys(names) if n not in exact]


def resolve(
    available: Sequence[SourceEntity], wanted: Sequence[ConfiguredEntity]
) -> tuple[list[SourceEntity], list[ConfiguredEntity]]:
    """Configured entities as the source reports them now (by key; legacy: exact name),
    and those it doesn't have."""
    by_key = {e.key: e for e in available}
    exact = {e.name: e for e in available}
    found, missing = [], []
    for entry in wanted:
        entity = by_key.get(entry.key) if entry.key else exact.get(entry.name)
        if entity is None:
            missing.append(entry)
        elif entity not in found:
            found.append(entity)
    return found, missing


def select_entities(
    connector: Connector,
    connection: Connection,
    names: Sequence[str] | None = None,
    keys: Sequence[str] | None = None,
) -> list[SourceEntity]:
    """The entities to work with: by `keys` (e.g. those a sync just ran), else by `names`
    typed on the command line, else those configured on the connection, else all."""
    available = connector.list_entities()
    if keys:
        wanted = [ConfiguredEntity(k, "") for k in keys]
    elif names:
        found, missing_names = by_names(available, names)
        if missing_names:
            raise EntityLookupError(len(missing_names), len(names))
        return found
    else:
        wanted = configured(connection)
        if not wanted:
            return list(available)
    found, missing = resolve(available, wanted)
    if missing:
        raise EntityLookupError(len(missing), len(wanted))
    return found
