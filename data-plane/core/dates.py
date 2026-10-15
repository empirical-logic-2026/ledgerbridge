"""Dates a source answers reliably (source-independent).

TallyPrime in Educational mode computes balances correctly only for dates on the 1st, 2nd
or 31st of a month: for the 30th it was seen to include later vouchers (checked on the test
company, 2026-10-15). Validation and analysis therefore pick their dates through a
`DateRule`: "as of" moves back to the latest reliable date, and a month or year end moves
forward to the next reliable one (the 31st, or the 1st of the next month). Both sides are
compared as of the date actually used, and the output shows it.
"""

from dataclasses import dataclass
from datetime import date, timedelta

EDUCATIONAL_DAYS = frozenset({1, 2, 31})


@dataclass(frozen=True)
class DateRule:
    days: frozenset[int] | None = None  # days of the month that are reliable; None: all
    reason: str = ""  # why, for the output (e.g. "Educational mode")

    @property
    def restricted(self) -> bool:
        return self.days is not None

    def reliable(self, on: date) -> bool:
        return self.days is None or on.day in self.days

    def on_or_before(self, on: date) -> date:
        """The latest reliable date on or before `on` (an "as of" date)."""
        while not self.reliable(on):
            on -= timedelta(days=1)
        return on

    def on_or_after(self, on: date) -> date:
        """The earliest reliable date on or after `on` (a month or year end)."""
        while not self.reliable(on):
            on += timedelta(days=1)
        return on

    def describe(self) -> str:
        if self.days is None:
            return "every date"
        days = ", ".join(str(d) for d in sorted(self.days))
        return f"{self.reason}: only days {days} of a month give reliable balances"


EVERY_DAY = DateRule()
EDUCATIONAL = DateRule(EDUCATIONAL_DAYS, "Educational mode")


def date_rule(connector: object, entity: object) -> DateRule:
    """The connector's rule for an entity (connectors without one: every date)."""
    rule = getattr(connector, "date_rule", None)
    if rule is None:
        return EVERY_DAY
    try:
        return rule(entity)
    except Exception:  # noqa: BLE001 - unknown: every date, as before
        return EVERY_DAY
