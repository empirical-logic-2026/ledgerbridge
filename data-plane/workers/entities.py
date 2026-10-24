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
from typing import TYPE_CHECKING

from connectors.base import Connector, SourceEntity
from core.models import Connection

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


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


class ExpectedEntityNotLoadedError(RuntimeError):
    """The source doesn't have the expected company loaded: nothing is compared or stored
    for it. Kinds only, never names (LB-SYNC-011)."""


def ensure_loaded(connector: Connector, entity: SourceEntity) -> None:
    """Stops unless the source has this entity loaded, by its key (the company GUID the
    entity was synced from), and no other loaded entity has the same name. Requests name
    the company, so with it missing or a namesake loaded an answer could come from another
    company (pilot 2026-10-23: a run with another company loaded reported 3,742 ledgers
    missing). Called before every step that reads the source to compare or store, and
    again after reading."""
    available = connector.list_entities()
    if not any(e.key == entity.key for e in available):
        raise ExpectedEntityNotLoadedError(
            "expected company not loaded: the source doesn't have the company this entity "
            "was synced from (by its key); nothing was compared"
        )
    if any(e.name == entity.name and e.key != entity.key for e in available):
        raise ExpectedEntityNotLoadedError(
            "expected company not loaded alone: another loaded company has the same name, so "
            "requests could reach it; nothing was compared"
        )


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


class Labels:
    """One way to refer to a company in every output (sync, transform, validation, status,
    summary): `entity <id> (company <n>)`.

    - `entity <id>` is the entity's id in ledgerbridge_accounting, the same everywhere.
    - `company <n>` is the company's number on its connection, given once and kept
      (`connections.config.company_numbers`, stored by `connect`): synced companies in the
      order they were first synced, then configured ones in the configured order. It never
      depends on which companies a run includes, nor on the order `connect` lists them in.

    A company not transformed yet has no entity id: `company <n> (no entity yet)`. Names are
    never part of a label (callers add them in the test environment only).
    """

    def __init__(self, session: "Session", connection: Connection) -> None:
        from sqlalchemy import select

        from core.models.accounting import EntitySource

        self.session = session
        self.connection = connection
        links = session.execute(
            select(EntitySource.source_entity_key, EntitySource.entity_id)
            .where(EntitySource.connection_id == connection.id)
            .order_by(EntitySource.id)
        ).all()
        self.entity_ids = {key: entity_id for key, entity_id in links}
        # Numbers already given (stored by `connect`) never change (pilot, 2026-10-15: after
        # a reconnect listed the companies in another order, entity 1 became company 2).
        # Others follow: synced companies in the order first synced, then configured ones.
        stored = connection.config.get("company_numbers") or {}
        self.numbers: dict[str, int] = {str(k): int(n) for k, n in stored.items()}
        for key, _ in links:
            self.number(key)
        for entry in configured(connection):
            if entry.key:
                self.number(entry.key)
        self.keys_by_id = {entity_id: key for key, entity_id in links}

    def refresh(self) -> "Labels":
        return Labels(self.session, self.connection)

    def number(self, key: str) -> int:
        if key not in self.numbers:
            self.numbers[key] = max(self.numbers.values(), default=0) + 1
        return self.numbers[key]

    def for_key(self, key: str, entity_id: int | None = None) -> str:
        entity_id = entity_id if entity_id is not None else self.entity_ids.get(key)
        if entity_id is None:
            return f"company {self.number(key)} (no entity yet)"
        return f"entity {entity_id} (company {self.number(key)})"

    def for_entity(self, entity_id: int) -> str:
        key = self.keys_by_id.get(entity_id)
        if key is None:
            return f"entity {entity_id}"
        return f"entity {entity_id} (company {self.number(key)})"
