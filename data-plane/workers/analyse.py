"""Why validation finds mismatches: `validate analyse` (source-independent; VAL-009).

For one entity, it compares our figures with the source's own ones again and tests, for
every mismatch, explanations that can be checked automatically, then reports how many
mismatches each explanation fits. Output is counts, patterns, dates and the source's own
standard names (voucher types, reserved groups, Tally's XML tag names) only: never ledger,
party or item names, and never amounts.

- **Ledgers** (closing balances today and at every financial year end): the opening balance
  missing or counted twice; the sign flipped; the lines of one voucher type counted here
  but not by the source, or the other way round (cancelled, optional, deleted vouchers and
  voucher types that don't post); post-dated vouchers; the source restarting income and
  expense ledgers each financial year; the first year end where the ledger differs; and
  pairs of these together. Differing ledgers are broken down by primary group and whether
  the opening explains them; unexplained ones get the first month of the first financial
  year where they differ (from the source's own monthly balances) and the voucher types
  with lines in that month. Each differing ledger gets an anonymous profile; for one that
  matches at a date and differs at the next (or the other way round), the dates are
  narrowed by asking the source for reliable dates in between, and the vouchers posting to
  it then are counted by kind, type and effective date, with any single voucher whose line,
  lines or total equal the difference.
- **Profit carrier**: differences of the income and expense ledgers, prior years' profit,
  the opening difference, the stock change.
- **Unbalanced vouchers and trial balance**: rounding, foreign currency, a reversed sign, a
  single line, on-account bills, inventory lines; the trial balance against the unbalanced
  vouchers and lines posted to ledgers deleted in the source.
- **Bills**: opening bills, on-account amounts, vouchers not counted here, post-dated ones.
- **Stock**: each voucher type counted here but not by the source and the other way round,
  lines tracked to a delivery or receipt note, lines at a job worker's godown (the source
  leaves them out), the opening quantity, physical stock
  vouchers, alternate or compound units, several
  godowns or batches; and, per voucher type, what the stored vouchers contain that the
  mapping doesn't read.

Where it fits: `./dev.ps1 validate analyse` runs it after validation reports mismatches. It
reads our balances through core/validation.py (the same figures validation compares) and
the source's through the connector, read-only. Everything it learns is printed as lines;
nothing is stored.
"""

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

from sqlalchemy import extract, func, or_, select
from sqlalchemy.orm import Session

from connectors.base import Connector, SourceEntity, SourceRecord
from core.dates import date_rule
from core.models import Connection
from core.models import accounting as A  # noqa: N812
from core.models.source import RawRecord
from core.names import normalise
from core.validation import (
    PROFIT_NATURES,
    Validator,
    at_book_value,
    at_stock_value,
    financial_year_ends,
)
from workers.entities import ensure_loaded

Progress = Callable[[str], None]
ZERO = Decimal(0)
SAMPLE = 500  # stored vouchers read per voucher type for the content census
PROFILE_LEDGERS = 26  # differing ledgers profiled (ledger A to Z)
EFFECTIVE_SAMPLE = 5_000  # vouchers per profiled ledger checked for their effective date
PROBES = 60  # extra dates asked of the source to narrow down when a ledger starts to differ
WINDOW_VOUCHERS = 5_000  # voucher lines read per window
EQUAL_LINES = 200  # lines equal to a difference whose reference is checked, per ledger
NAMED_VOUCHERS = 5_000  # stored vouchers naming a ledger read per profiled ledger
GODOWN_ITEMS = 200  # differing items checked godown by godown (one source request each)
GODOWN_KINDS = {
    "own": "own godown",
    "ours_with_third_party": "a job worker's godown",
    "third_party_with_us": "a principal's godown (their stock with us)",
}
JOB_WORK_TYPES = ("Material In", "Material Out", "Job Work In Order", "Job Work Out Order")
STOCK_TYPES = (
    "Stock Journal",
    "Physical Stock",
    "Delivery Note",
    "Receipt Note",
    "Rejections In",
    "Rejections Out",
    "Material In",
    "Material Out",
)


def _type(standard: str | None, base: str | None) -> str:
    """A voucher type as shown: the source's standard name, never a custom one."""
    return standard or f"custom ({base or 'other'})"


def _category(deleted: bool, cancelled: bool, optional: bool) -> str | None:
    """Why a voucher doesn't count in the books, or None when it does."""
    if deleted:
        return "deleted"
    if cancelled:
        return "cancelled"
    if optional:
        return "optional"
    return None


def _letter(n: int) -> str:
    """A, B, ..., Z, AA, AB, ...: anonymous labels."""
    out = ""
    n += 1
    while n:
        n, rest = divmod(n - 1, 26)
        out = chr(65 + rest) + out
    return out


def _like(text: str) -> str:
    """Text for a LIKE pattern, its wildcards escaped (used with ESCAPE '\\')."""
    return text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def fy_start(on: date, fy_start_month: int) -> date:
    """First day of the financial year containing `on`."""
    year = on.year if on.month >= fy_start_month else on.year - 1
    return date(year, fy_start_month, 1)


def _has_balances(source: Any) -> bool:
    """Whether the source's balances were read (a SourceBalances, not an error or None)."""
    return hasattr(source, "ledgers")


class Analyser:
    """The analysis of one entity as of a date: `run` returns the report's lines."""

    def __init__(
        self,
        session: Session,
        connection: Connection,
        connector: Connector,
        entity: SourceEntity,
        entity_id: int,
        as_of: date,
        tolerance: Decimal,
        progress: Progress,
    ) -> None:
        self.session = session
        self.connector = connector
        self.entity = entity
        self.entity_id = entity_id
        self.as_of = as_of
        self.tolerance = tolerance
        self.say = progress
        self.rule = date_rule(connector, entity)
        self.validator = Validator(session, entity_id, as_of, tolerance, connection.id)
        self.row = self.validator.entity
        self.lines: list[str] = []
        self.year_end_diffs: dict[str, dict[date, Decimal]] = {}  # key -> year end -> diff
        self.mismatched: dict[str, Decimal] = {}  # key -> difference as of the date
        self.unexplained_keys: list[str] = []
        self.ours_today: dict[str, Any] = {}  # key -> our balance as of the date
        # Ledger profiles: anonymous letters, and each ledger's row and primary group.
        self.letters: dict[str, str] = {}
        self.profile_rows: dict[int, tuple[Any, ...]] = {}
        self.profile_primary: dict[int, str] = {}
        # Read once and kept: our balances and the source's at a date, the differences
        # then, and how many extra dates have been asked of the source (at most PROBES).
        self._year_cache: dict[date, dict[str, Any]] = {}
        self._sources: dict[date, Any] = {}
        self._diffs: dict[date, dict[str, Decimal] | None] = {}
        self.probes = 0
        self._deleted: set[int] | None = None
        self._named: Counter[str] | None = None
        self._kinds_by_name: dict[str, str] | None = None
        self._effective_known: bool | None = None
        self._opening_bills_read = False
        self._opening_bills: dict[str, Decimal] | None = None

    def close(self, a: Decimal, b: Decimal) -> bool:
        return abs(Decimal(a) - Decimal(b)) <= self.tolerance

    def out(self, line: str) -> None:
        self.lines.append(line)

    def _read(self, method: str, *args: Any) -> Any:
        """A source figure (an exception it raised is reported as unavailable), read only
        while the expected company is loaded (LB-SYNC-011: never analyse another one)."""
        read = getattr(self.connector, method, None)
        if read is None:
            return None
        ensure_loaded(self.connector, self.entity)
        try:
            found = read(*args)
        except Exception as exc:  # noqa: BLE001 - reported as unavailable
            found = exc
        ensure_loaded(self.connector, self.entity)
        return found

    # --- driver -----------------------------------------------------------------------

    def run(self) -> list[str]:
        # Year ends at the source's next reliable period end (Educational mode, core/dates.py).
        self.year_ends = sorted(
            {
                used
                for ye in financial_year_ends(
                    self.row.books_from, self.row.fy_start_month, self.as_of
                )
                if (used := self.rule.period_end(ye)) <= self.as_of
            }
        )
        self.out(self._dates_used())
        self.say("reading the source's balances as of today and at every year end")
        self.source = self._read("closing_balances", self.entity, self.as_of)
        self.source_years = {
            ye: self._read("closing_balances", self.entity, ye) for ye in self.year_ends
        }
        self._prepare_lines()
        self._ledgers()
        self._year_ends()
        self._profit_carrier()
        self._unbalanced()
        self._bills()
        self._stock()
        self._job_work()
        self._profiles()
        self._opening()
        self._census()
        return self.lines

    # --- our figures --------------------------------------------------------------------

    def _prepare_lines(self) -> None:
        """Per ledger: line sums by voucher type and by why lines don't count, and monthly
        sums of counted lines (for year starts)."""
        self.say("summing voucher lines by ledger, voucher type and month")
        V, L, T = A.Voucher, A.VoucherLine, A.VoucherType  # noqa: N806
        self.counted: dict[int, Counter[str]] = defaultdict(Counter)
        self.excluded: dict[int, Counter[str]] = defaultdict(Counter)
        self.post_dated: Counter[int] = Counter()
        for (
            ledger_id,
            standard,
            base,
            deleted,
            cancelled,
            optional,
            post_dated,
            effective,
            total,
        ) in self.session.execute(
            select(
                L.ledger_id,
                T.standard_type,
                T.base_type,
                V.is_deleted,
                V.is_cancelled,
                V.is_optional,
                V.is_post_dated,
                L.is_effective,
                func.sum(L.amount),
            )
            .join(V, V.id == L.voucher_id)
            .join(T, T.id == V.voucher_type_id)
            .where(L.entity_id == self.entity_id, L.voucher_date <= self.as_of)
            .group_by(
                L.ledger_id,
                T.standard_type,
                T.base_type,
                V.is_deleted,
                V.is_cancelled,
                V.is_optional,
                V.is_post_dated,
                L.is_effective,
            )
        ):
            amount = Decimal(total or 0)
            kind = _type(standard, base)
            if effective:
                self.counted[ledger_id][kind] += amount
                if post_dated:
                    self.post_dated[ledger_id] += amount
            else:
                why = _category(deleted, cancelled, optional) or "not posting"
                self.excluded[ledger_id][f"{why} {kind}"] += amount
        self.monthly: dict[int, list[tuple[date, Decimal]]] = defaultdict(list)
        year, month = extract("year", L.voucher_date), extract("month", L.voucher_date)
        for ledger_id, y, m, total in self.session.execute(
            select(L.ledger_id, year, month, func.sum(L.amount))
            .where(
                L.entity_id == self.entity_id,
                L.is_effective.is_(True),
                L.voucher_date <= self.as_of,
            )
            .group_by(L.ledger_id, year, month)
        ):
            self.monthly[ledger_id].append((date(int(y), int(m), 1), Decimal(total or 0)))

    def _before(self, ledger_id: int, start: date) -> Decimal:
        return sum((t for month, t in self.monthly.get(ledger_id, []) if month < start), ZERO)

    def _reserved_groups(self) -> dict[str, str]:
        """The source's reserved group names, by their case-folded form."""
        names = (getattr(self.connector, "reserved_names", None) or {}).get("group", ())
        return {n.casefold(): n for n in names}

    def _primary_groups(self) -> dict[int, str]:
        """Ledger id -> its primary group, by the source's reserved name or "custom"."""
        reserved = self._reserved_groups()
        groups = self._group_tree()

        def top(gid: int) -> str:
            seen = set()
            while gid in groups and groups[gid][0] is not None and gid not in seen:
                seen.add(gid)
                gid = groups[gid][0]
            if gid not in groups:
                return "unknown group"
            _, name, aliases = groups[gid]
            for candidate in (name, *aliases):
                if candidate.casefold() in reserved:
                    return candidate
            return "custom primary group"

        return {
            lid: top(gid)
            for lid, gid in self.session.execute(
                select(A.Ledger.id, A.Ledger.group_id).where(A.Ledger.entity_id == self.entity_id)
            )
        }

    # --- ledgers ------------------------------------------------------------------------

    def _candidates(self, ledger: Any, start: date) -> list[tuple[str, Decimal]]:
        """Each explanation with the difference (theirs - ours) it would make."""
        out = []
        if ledger.opening:
            out.append(("the opening balance is missing here", ledger.opening))
            out.append(
                (
                    "the opening balance is counted twice here, or the source leaves it out",
                    -ledger.opening,
                )
            )
        for kind, total in self.counted.get(ledger.id, {}).items():
            if total:
                out.append((f"{kind} vouchers counted here but not by the source", -total))
        for kind, total in self.excluded.get(ledger.id, {}).items():
            if total:
                out.append((f"{kind} vouchers counted by the source but not here", total))
        post_dated = self.post_dated.get(ledger.id, ZERO)
        if post_dated:
            out.append(("post-dated vouchers counted here but not by the source", -post_dated))
        if ledger.nature in PROFIT_NATURES:
            prior = self._before(ledger.id, start)
            restarts = "the source restarts income and expense ledgers each financial year"
            if prior:
                out.append((restarts, -prior))
            if prior + ledger.opening and ledger.opening:
                out.append((restarts, -(prior + ledger.opening)))
        return out

    def _explain(self, ledger: Any, theirs: Decimal, ours: Decimal, start: date) -> list[str]:
        diff = theirs - ours
        fits = [
            label for label, value in self._candidates(ledger, start) if self.close(diff, value)
        ]
        if ours and self.close(theirs, -ours):
            fits.append("the sign is reversed")
        return list(dict.fromkeys(fits))

    def _pairs(self, ledger: Any, diff: Decimal, start: date) -> list[str]:
        """Two explanations that together make the difference (none fits alone)."""
        found = self._candidates(ledger, start)
        fits = []
        for i, (first, a) in enumerate(found):
            for second, b in found[i + 1 :]:
                if first != second and self.close(diff, a + b):
                    fits.append(" + ".join(sorted((first, second))))
        return list(dict.fromkeys(fits))

    def _dates_used(self) -> str:
        """The dates compared, and why (Educational mode moves them to reliable days)."""
        listed = ", ".join(str(d) for d in self.year_ends) or "none"
        rule = f"; {self.rule.describe()}" if self.rule.restricted else ""
        return f"Dates used: as of {self.as_of}; year ends {listed}{rule}"

    def _ledgers(self) -> None:
        self.out("Ledger closing balances as of the validation date:")
        if not _has_balances(self.source):
            self.out(f"  the source's balances couldn't be read ({type(self.source).__name__})")
            return
        carriers = self.source.profit_carriers
        ours = {lb.source_key: lb for lb in self.validator.ledger_balances(self.as_of)}
        self.ours_today = ours
        start = fy_start(self.as_of, self.row.fy_start_month)
        fits: Counter[str] = Counter()
        unexplained: Counter[str] = Counter()
        pairs: Counter[str] = Counter()
        by_group: dict[str, Counter[str]] = defaultdict(Counter)
        primary = self._primary_groups()
        explained = by_pair = 0
        twice = "the opening balance is counted twice here, or the source leaves it out"
        at_stock = self._at_stock_value(self.as_of)
        at_book = self._at_book_value(self.as_of)
        for key, lb in ours.items():
            theirs = self.source.ledgers.get(key)
            if theirs is None or key in carriers or self.close(theirs, lb.balance):
                continue
            if key in at_stock or key in at_book:
                continue  # compared as validation does: the stock value, or the book value
            diff = theirs - lb.balance
            self.mismatched[key] = diff
            found = self._explain(lb, theirs, lb.balance, start)
            first = self._first_year_end(key)
            fits[first] += 1
            group = primary.get(lb.id, "unknown group")
            opening = bool({"the opening balance is missing here", twice} & set(found))
            by_group[group][
                "the opening explains it"
                if opening
                else ("stored opening non-zero" if lb.opening else "stored opening zero")
            ] += 1
            if found:
                explained += 1
                fits.update(found)
                continue
            combined = self._pairs(lb, diff, start)
            if combined:
                by_pair += 1
                pairs.update(combined)
                continue
            unexplained[group] += 1
            self.unexplained_keys.append(key)
        self.out(
            f"  {len(self.mismatched):,} ledgers differ; {explained:,} have at least one "
            f"explanation that fits; {by_pair:,} more are explained by two together"
        )
        if at_stock:
            self.out(
                f"  stock ledgers at the source's closing stock value (compared with it, as "
                f"validation does; LB-VAL-021): {len(at_stock):,}"
            )
        foreign = getattr(self.source, "foreign_ledgers", frozenset()) or frozenset()
        if foreign:
            differing = sum(1 for k in self.mismatched if k in foreign)
            self.out(
                f"  foreign-currency ledgers: {len(foreign):,}; matching the source's book value "
                f"(its revaluation at current rates left out, as validation does; LB-VAL-022) "
                f"{len(at_book):,}; differing {differing:,}"
            )
        cancelling = self._cancelling(self.mismatched)
        if cancelling:
            self.out(
                f"  pairs of ledgers whose differences cancel out (one amount on the other "
                f"ledger?): {cancelling:,}"
            )
        for reason, n in fits.most_common():
            self.out(f"    {reason}: {n:,}")
        if pairs:
            self.out("  two explanations together:")
            for reason, n in pairs.most_common(12):
                self.out(f"    {reason}: {n:,}")
        if by_group:
            self.out("  by primary group (opening explains it / stored opening non-zero / zero):")
            for group, counts in sorted(by_group.items(), key=lambda g: -sum(g[1].values())):
                self.out(
                    f"    {group}: {counts['the opening explains it']:,} / "
                    f"{counts['stored opening non-zero']:,} / {counts['stored opening zero']:,}"
                )
        if unexplained:
            listed = ", ".join(f"{group} {n:,}" for group, n in unexplained.most_common())
            self.out(f"  unexplained, by primary group: {listed}")
            self._first_month(ours)

    def _first_month(self, ours: dict[str, Any]) -> None:
        """For unexplained ledgers: the first month end of the first financial year where
        the balance differs from the source's, and the voucher types with lines in that
        month (counts of ledgers; the source's standard type names only)."""
        books_from = self.row.books_from
        if books_from is None or not self.unexplained_keys:
            return
        first_year = fy_start(books_from, self.row.fy_start_month)
        month_ends = []
        current = books_from.replace(day=1)
        while True:
            following = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
            end = self.rule.on_or_after(following - timedelta(days=1))  # e.g. 30th -> 1st
            if end > self.as_of or following > first_year.replace(year=first_year.year + 1):
                break
            month_ends.append(end)
            current = following
        if not month_ends:
            return
        self.say("reading the source's balances at each month end of the first financial year")
        pending = set(self.unexplained_keys)
        first: dict[str, date] = {}
        previous: dict[date, date] = {}  # month end -> the month end checked before it
        starts = [books_from - timedelta(days=1), *month_ends]
        for before, end in zip(starts, month_ends, strict=False):
            previous[end] = before
            diffs = self._diffs_at(end)
            if diffs is None:
                self.out(f"  first month: the source's balances at {end} couldn't be read")
                return
            for key in list(pending):
                if key in diffs:
                    first[key] = end
                    pending.discard(key)
            if not pending:
                break
        months = Counter(f"{end:%Y-%m}" if end.day > 2 else f"{end}" for end in first.values())
        if pending:
            months["matches every month end of the first financial year"] = len(pending)
        self.out("  unexplained ledgers, first month end where they differ (first financial year):")
        for month, n in sorted(months.items()):
            self.out(f"    {month}: {n:,}")
        types: Counter[str] = Counter()
        no_lines = 0
        L, V, T = A.VoucherLine, A.Voucher, A.VoucherType  # noqa: N806
        for key, end in first.items():
            lb = ours.get(key)
            if lb is None:
                continue
            kinds = {
                _type(standard, base)
                for standard, base in self.session.execute(
                    select(T.standard_type, T.base_type)
                    .join(V, V.voucher_type_id == T.id)
                    .join(L, L.voucher_id == V.id)
                    .where(
                        L.ledger_id == lb.id,
                        L.voucher_date > previous[end],  # since the month end checked before
                        L.voucher_date <= end,
                    )
                    .distinct()
                )
            }
            if not kinds:
                no_lines += 1
            types.update(kinds)
        if types or no_lines:
            listed = ", ".join(f"{k} {n:,}" for k, n in types.most_common())
            extra = f"; no lines that month (the opening differs) {no_lines:,}" if no_lines else ""
            self.out(f"    voucher types with lines in that month: {listed or 'none'}{extra}")

    def _first_year_end(self, key: str) -> str:
        for year_end in self.year_ends:
            source = self.source_years.get(year_end)
            if not _has_balances(source):
                continue
            theirs = source.ledgers.get(key)
            ours = self._year_balances(year_end).get(key)
            if theirs is not None and ours is not None and not self.close(theirs, ours.balance):
                return f"first differs at the year end {year_end}"
        return "first differs in the current financial year (every year end matches)"

    def _year_balances(self, on: date) -> dict[str, Any]:
        """Our balances as of a date, by source key (read once)."""
        if on not in self._year_cache:
            self._year_cache[on] = {lb.source_key: lb for lb in self.validator.ledger_balances(on)}
        return self._year_cache[on]

    def _year_ends(self) -> None:
        if not self.year_ends:
            self.out("Year ends: the books have no financial year end before the validation date")
            return
        self.out("Ledger balances at each financial year end:")
        for year_end in self.year_ends:
            source = self.source_years.get(year_end)
            if not _has_balances(source):
                self.out(f"  {year_end}: the source's balances couldn't be read")
                continue
            ours = self._year_balances(year_end)
            start = fy_start(year_end, self.row.fy_start_month)
            differ, fits = 0, Counter()
            # Compared as validation does: at the stock value, or at the book value.
            explained = self._at_stock_value(year_end) | self._at_book_value(year_end)
            for key, lb in ours.items():
                theirs = source.ledgers.get(key)
                if (
                    theirs is None
                    or key in source.profit_carriers
                    or key in explained
                    or self.close(theirs, lb.balance)
                ):
                    continue
                differ += 1
                diff = theirs - lb.balance
                self.year_end_diffs.setdefault(key, {})[year_end] = diff
                if lb.opening and self.close(diff, -lb.opening):
                    fits["opening counted twice here, or left out by the source"] += 1
                if lb.nature in PROFIT_NATURES:
                    prior = self._before(lb.id, start)
                    if (prior or lb.opening) and (
                        self.close(diff, -prior) or self.close(diff, -(prior + lb.opening))
                    ):
                        fits["the source restarts income and expense ledgers each year"] += 1
            detail = "; ".join(f"{reason} {n:,}" for reason, n in fits.most_common())
            self.out(
                f"  {year_end}: {differ:,} ledgers differ" + (f" ({detail})" if detail else "")
            )

    # --- profit carrier ------------------------------------------------------------------

    def _profit_carrier(self) -> None:
        if not _has_balances(self.source) or not self.source.profit_carriers:
            return
        self.out("Profit carrier (e.g. Profit & Loss A/c):")
        ours = self.ours_today
        nominal = [lb for lb in ours.values() if lb.nature in PROFIT_NATURES]
        profit = sum((lb.balance for lb in nominal), ZERO)
        stock_change = ZERO
        if self.source.closing_stock is not None and self.source.opening_stock is not None:
            stock_change = self.source.closing_stock - self.source.opening_stock
        start = fy_start(self.as_of, self.row.fy_start_month)
        prior = sum((self._before(lb.id, start) + lb.opening for lb in nominal), ZERO)
        nominal_diffs = sum((self.mismatched.get(lb.source_key, ZERO) for lb in nominal), ZERO)
        opening_difference = sum((lb.opening for lb in ours.values()), ZERO)
        for key in self.source.profit_carriers:
            lb = ours.get(key)
            if lb is None:
                continue
            theirs = self.source.ledgers[key]
            expected = lb.balance + profit - stock_change
            diff = theirs - expected
            if self.close(diff, ZERO):
                self.out("  reconciles")
                continue
            tests = (
                ("the differences of the income and expense ledgers", -nominal_diffs),
                ("prior financial years' profit", prior),
                ("minus prior financial years' profit", -prior),
                ("the opening difference", opening_difference),
                ("minus the opening difference", -opening_difference),
                ("the change in stock value", stock_change),
                ("minus the change in stock value", -stock_change),
            )
            fits = [label for label, value in tests if value and self.close(diff, value)]
            self.out(
                "  differs; the difference equals: "
                + (", ".join(fits) if fits else "none of the tested explanations")
            )

    # --- unbalanced vouchers and the trial balance ----------------------------------------

    def _unbalanced(self) -> None:
        L, V, T = A.VoucherLine, A.Voucher, A.VoucherType  # noqa: N806
        sums = self.session.execute(
            select(L.voucher_id, func.sum(L.amount))
            .where(L.entity_id == self.entity_id, L.is_effective.is_(True))
            .group_by(L.voucher_id)
        ).all()
        unbalanced = {vid: Decimal(t) for vid, t in sums if Decimal(t) != ZERO}
        self.out(f"Unbalanced vouchers: {len(unbalanced):,}")
        patterns: Counter[str] = Counter()
        by_type: Counter[str] = Counter()
        dated: list[tuple[date, Decimal]] = []
        ids = list(unbalanced)
        for start in range(0, len(ids), 1_000):
            chunk = ids[start : start + 1_000]
            lines: dict[int, list[Decimal]] = defaultdict(list)
            for vid, amount in self.session.execute(
                select(L.voucher_id, L.amount).where(
                    L.voucher_id.in_(chunk), L.is_effective.is_(True)
                )
            ):
                lines[vid].append(Decimal(amount))
            on_account = set(
                self.session.scalars(
                    select(L.voucher_id)
                    .join(A.BillAllocation, A.BillAllocation.voucher_line_id == L.id)
                    .where(L.voucher_id.in_(chunk), A.BillAllocation.bill_type == "on_account")
                )
            )
            inventory = set(
                self.session.scalars(
                    select(A.InventoryLine.voucher_id).where(A.InventoryLine.voucher_id.in_(chunk))
                )
            )
            for vid, voucher_date, standard, base, post_dated, payload in self.session.execute(
                select(
                    V.id,
                    V.voucher_date,
                    T.standard_type,
                    T.base_type,
                    V.is_post_dated,
                    RawRecord.payload,
                )
                .join(T, T.id == V.voucher_type_id)
                .outerjoin(RawRecord, RawRecord.id == V.raw_record_id)
                .where(V.id.in_(chunk))
            ):
                total = unbalanced[vid]
                dated.append((voucher_date, total))
                by_type[_type(standard, base)] += 1
                found = []
                if abs(total) < 1:
                    found.append("rounding (less than 1)")
                hints = self._hints("voucher", payload)
                if "foreign currency amounts" in hints:
                    found.append("foreign currency amounts")
                if any(self.close(2 * amount, total) for amount in lines[vid]):
                    found.append("one line's sign reversed")
                if len(lines[vid]) == 1:
                    found.append("a single line (a line missing)")
                if vid in on_account:
                    found.append("on-account bill allocations")
                if vid in inventory:
                    found.append("inventory lines")
                if post_dated:
                    found.append("post-dated")
                patterns.update(found or ["none of the tested patterns"])
        if unbalanced:
            self.out(
                "  by voucher type: " + ", ".join(f"{k} {n:,}" for k, n in by_type.most_common())
            )
            self.out("  patterns: " + ", ".join(f"{k} {n:,}" for k, n in patterns.most_common()))
        self._trial_balance(dated)

    def _trial_balance(self, unbalanced: list[tuple[date, Decimal]]) -> None:
        deleted_lines = dict(
            self.session.execute(
                select(A.VoucherLine.voucher_date, func.sum(A.VoucherLine.amount))
                .join(A.Ledger, A.Ledger.id == A.VoucherLine.ledger_id)
                .where(
                    A.VoucherLine.entity_id == self.entity_id,
                    A.VoucherLine.is_effective.is_(True),
                    A.Ledger.is_deleted.is_(True),
                )
                .group_by(A.VoucherLine.voucher_date)
            ).all()
        )
        failing, fits = 0, Counter()
        for on in [*self.year_ends, self.as_of]:
            balances = self.validator.ledger_balances(on)
            opening = sum((lb.opening for lb in balances), ZERO)
            diff = sum((lb.balance for lb in balances), ZERO) - opening
            if self.close(diff, ZERO):
                continue
            failing += 1
            from_unbalanced = sum((t for d, t in unbalanced if d <= on), ZERO)
            on_deleted = sum((Decimal(t) for d, t in deleted_lines.items() if d <= on), ZERO)
            if from_unbalanced and self.close(diff, from_unbalanced):
                fits["the unbalanced vouchers"] += 1
            elif on_deleted and self.close(diff, -on_deleted):
                fits["lines posted to ledgers deleted in the source"] += 1
            elif self.close(diff, from_unbalanced - on_deleted):
                fits["both of these together"] += 1
            else:
                fits["none of the tested explanations"] += 1
        detail = ", ".join(f"{k} {n:,}" for k, n in fits.most_common())
        self.out(
            f"Trial balance: {failing:,} dates don't balance"
            + (f"; explained by: {detail}" if detail else "")
        )

    # --- bills ---------------------------------------------------------------------------

    def _bills(self) -> None:
        if self.as_of < date.today():
            return
        found = self._read("bill_outstanding", self.entity)
        if not isinstance(found, tuple):
            return
        outstanding, opening = found
        L, B, V = A.VoucherLine, A.BillAllocation, A.Voucher  # noqa: N806
        sums: dict[str, Counter[str]] = defaultdict(Counter)
        for name, bill_type, effective, post_dated, total in self.session.execute(
            select(A.Ledger.name, B.bill_type, L.is_effective, V.is_post_dated, func.sum(B.amount))
            .join(L, L.ledger_id == A.Ledger.id)
            .join(B, B.voucher_line_id == L.id)
            .join(V, V.id == L.voucher_id)
            .where(A.Ledger.entity_id == self.entity_id)
            .group_by(A.Ledger.name, B.bill_type, L.is_effective, V.is_post_dated)
        ):
            amount = Decimal(total or 0)
            if not effective:
                sums[name]["not counted"] += amount
            elif bill_type == "on_account":
                sums[name]["on account"] += amount
            else:
                sums[name]["counted"] += amount
                if post_dated:
                    sums[name]["post-dated"] += amount
        fits: Counter[str] = Counter()
        differ = 0
        for party in set(sums) | set(outstanding) | set(opening):
            ours = Decimal(opening.get(party, ZERO)) + sums[party]["counted"]
            diff = Decimal(outstanding.get(party, ZERO)) - ours
            if self.close(diff, ZERO):
                continue
            differ += 1
            tests = (
                (
                    "opening bills counted twice, or not in the source's list",
                    -Decimal(opening.get(party, ZERO)),
                ),
                ("on-account amounts (the source counts them)", sums[party]["on account"]),
                ("allocations of vouchers not counted here", sums[party]["not counted"]),
                (
                    "post-dated vouchers counted here but not by the source",
                    -sums[party]["post-dated"],
                ),
            )
            matched = [label for label, value in tests if value and self.close(diff, value)]
            fits.update(matched or ["none of the tested explanations"])
        if differ:
            self.out(f"Bill-wise outstanding: {differ:,} parties differ")
            for reason, n in fits.most_common():
                self.out(f"    {reason}: {n:,}")

    # --- stock -----------------------------------------------------------------------------

    def _stock(self) -> None:
        theirs = self._read("stock_quantities", self.entity, self.as_of)
        if not isinstance(theirs, dict):
            return
        Inv, V, T = A.InventoryLine, A.Voucher, A.VoucherType  # noqa: N806
        counted: dict[int, Counter[str]] = defaultdict(Counter)
        excluded: dict[int, Counter[str]] = defaultdict(Counter)
        physical: set[int] = set()
        for (
            item_id,
            standard,
            base,
            deleted,
            cancelled,
            optional,
            moves,
            total,
            tracked,
            holding,
        ) in self.session.execute(
            select(
                Inv.item_id,
                T.standard_type,
                T.base_type,
                V.is_deleted,
                V.is_cancelled,
                V.is_optional,
                T.moves_stock,
                func.sum(Inv.stock_quantity),
                func.sum(Inv.quantity - Inv.stock_quantity),
                A.Godown.holding,
            )
            .join(V, V.id == Inv.voucher_id)
            .join(T, T.id == V.voucher_type_id)
            .outerjoin(A.Godown, A.Godown.id == Inv.godown_id)
            .where(Inv.entity_id == self.entity_id, Inv.voucher_date <= self.as_of)
            .group_by(
                Inv.item_id,
                T.standard_type,
                T.base_type,
                V.is_deleted,
                V.is_cancelled,
                V.is_optional,
                T.moves_stock,
                A.Godown.holding,
            )
        ):
            kind = _type(standard, base)
            if standard == "Physical Stock":
                physical.add(item_id)
            why = _category(deleted, cancelled, optional) or (None if moves else "not moving stock")
            if why is None and holding == "ours_with_third_party":
                # Not in the source's stock balances: e.g. consumption at a job worker.
                why = "at a job worker's godown:"
            if why is None:
                counted[item_id][kind] += Decimal(total or 0)
                if tracked:
                    # Lines tracked to a delivery or receipt note: the note moves the stock.
                    excluded[item_id][f"tracked {kind} lines"] += Decimal(tracked)
            else:
                excluded[item_id][f"{why} {kind}"] += Decimal(total or 0)
        fits: Counter[str] = Counter()
        differ = 0
        mismatched: list[int] = []
        for item_id, key, opening in self.session.execute(
            select(A.Item.id, A.Item.source_key, A.Item.opening_qty).where(
                A.Item.entity_id == self.entity_id, A.Item.is_deleted.is_(False)
            )
        ):
            if key not in theirs:
                continue
            ours = Decimal(opening) + sum(counted[item_id].values(), ZERO)
            diff = Decimal(theirs[key]) - ours
            if diff == ZERO:
                continue
            differ += 1
            mismatched.append(item_id)
            matched = []
            for kind, total in counted[item_id].items():
                if total and diff == -total:
                    matched.append(f"{kind} counted here but not by the source")
            for kind, total in excluded[item_id].items():
                if total and diff == total:
                    matched.append(f"{kind} counted by the source but not here")
            if opening and diff == -Decimal(opening):
                matched.append("the opening quantity counted twice, or left out by the source")
            if opening and diff == Decimal(opening):
                matched.append("the opening quantity missing here")
            if item_id in physical:
                matched.append("has Physical Stock vouchers")
            fits.update(matched or ["none of the tested explanations"])
        if not differ:
            return
        self.out(f"Stock quantities: {differ:,} items differ")
        for reason, n in fits.most_common():
            self.out(f"    {reason}: {n:,}")
        hints: Counter[str] = Counter()
        for start in range(0, len(mismatched), 500):
            chunk = mismatched[start : start + 500]
            seen: dict[int, set[str]] = defaultdict(set)
            for item_id, payload in self.session.execute(
                select(Inv.item_id, RawRecord.payload)
                .join(V, V.id == Inv.voucher_id)
                .join(RawRecord, RawRecord.id == V.raw_record_id)
                .where(Inv.item_id.in_(chunk))
                .limit(SAMPLE * len(chunk))
            ):
                seen[item_id] |= self._hints("voucher", payload)
            for item_hints in seen.values():
                hints.update(h for h in item_hints if not h.startswith("unread list"))
        if hints:
            self.out(
                "    items whose vouchers have: "
                + ", ".join(f"{k} {n:,}" for k, n in hints.most_common())
            )
        self._godowns(mismatched)

    def _godowns(self, item_ids: list[int]) -> None:
        """Godown by godown, for items that differ (at most GODOWN_ITEMS): each godown's
        movement (closing minus opening) in the source's own figures against our lines at
        that godown. Counts by kind of godown only."""
        if not item_ids or not hasattr(self.connector, "stock_by_godown"):
            return
        Inv, V, T, G = A.InventoryLine, A.Voucher, A.VoucherType, A.Godown  # noqa: N806
        chosen = item_ids[:GODOWN_ITEMS]
        names = dict(
            self.session.execute(select(A.Item.id, A.Item.name).where(A.Item.id.in_(chosen))).all()
        )
        theirs = self._read("stock_by_godown", self.entity, self.as_of, list(names.values()))
        if not isinstance(theirs, dict):
            self.out("    by godown: the source's figures couldn't be read")
            return
        holdings = {
            name: holding
            for name, holding in self.session.execute(
                select(G.name, G.holding).where(G.entity_id == self.entity_id)
            )
        }
        ours: Counter[tuple[str, str]] = Counter()
        for item_id, godown, moved in self.session.execute(
            select(Inv.item_id, G.name, func.sum(Inv.stock_quantity))
            .join(V, V.id == Inv.voucher_id)
            .join(T, T.id == V.voucher_type_id)
            .outerjoin(G, G.id == Inv.godown_id)
            .where(
                Inv.item_id.in_(chosen),
                Inv.voucher_date <= self.as_of,
                V.is_deleted.is_(False),
                V.is_cancelled.is_(False),
                V.is_optional.is_(False),
                T.moves_stock.is_(True),
            )
            .group_by(Inv.item_id, G.name)
        ):
            ours[(names[item_id], godown or "")] += Decimal(moved or 0)
        differ: Counter[str] = Counter()
        for key in set(ours) | set(theirs):
            opening, closing = theirs.get(key, (ZERO, ZERO))
            if ours.get(key, ZERO) != closing - opening:
                differ[GODOWN_KINDS.get(holdings.get(key[1], "own"), "own godown")] += 1
        checked = f"{len(chosen):,} of {len(item_ids):,} differing items checked"
        if differ:
            listed = ", ".join(f"{kind} {n:,}" for kind, n in differ.most_common())
            self.out(f"    by godown ({checked}): (item, godown) movements that differ: {listed}")
        else:
            self.out(f"    by godown ({checked}): every godown's movement matches")

    def _profiles(self) -> None:
        """An anonymous profile of each ledger that differs today or at a year end (ledger A,
        B, ...): where it sits (primary group, a renamed reserved group, directly under the
        primary group), its kind and nature, its stored opening against the source's own,
        the voucher types posting to it, when it differs and whether by the same amount, and
        what the difference equals (its opening, the stock items' opening value). Kinds,
        standard names and dates only: never names or amounts."""
        keys = list(dict.fromkeys([*self.mismatched, *self.year_end_diffs]))
        if not keys:
            return
        ours = self.ours_today or self._year_balances(self.as_of)
        rows = {
            lid: (kind, currency, bill_wise, group_id)
            for lid, kind, currency, bill_wise, group_id in self.session.execute(
                select(
                    A.Ledger.id,
                    A.Ledger.ledger_kind,
                    A.Ledger.currency_code,
                    A.Ledger.is_bill_wise,
                    A.Ledger.group_id,
                ).where(A.Ledger.entity_id == self.entity_id)
            )
        }
        stock_opening = self._stored_items_opening()
        source_openings = getattr(self.source, "ledger_openings", {}) or {}
        source_stock = getattr(self.source, "opening_stock", None)
        stock_keys = getattr(self.source, "stock_ledgers", frozenset()) or frozenset()
        integrated = getattr(self.source, "integrated", None)
        primary = self._primary_groups()
        tree = self._group_tree()
        self.letters = {key: _letter(n) for n, key in enumerate(keys[:PROFILE_LEDGERS])}
        self.profile_rows = rows
        self.profile_primary = primary
        dated_by_key = {}
        for key in keys:
            found = dict(self.year_end_diffs.get(key, {}))
            if key in self.mismatched:
                found[self.as_of] = self.mismatched[key]
            dated_by_key[key] = found
        self.out(f"Ledger profiles (ledgers that differ today or at a year end: {len(keys):,}):")
        for n, key in enumerate(keys[:PROFILE_LEDGERS]):
            lb = ours.get(key)
            if lb is None:
                continue
            kind, currency, bill_wise, group_id = rows.get(lb.id, (None, None, False, None))
            where = self._where(lb.id, group_id, primary, tree)
            facts = [f"kind {kind or 'unknown'}", f"nature {lb.nature or 'unknown'}"]
            if currency and currency != "INR":
                facts.append("foreign currency")
            if bill_wise:
                facts.append("bill-wise")
            theirs = source_openings.get(key)
            facts.append(self._opening_fact(lb.opening, theirs))
            posted = sorted({*self.counted.get(lb.id, {}), *self.excluded.get(lb.id, {})})
            facts.append("posted by: " + (", ".join(posted) if posted else "no vouchers"))
            dated = dated_by_key[key]
            ends = [d for d in self.year_ends if d in dated]
            when = self._when(dated, ends)
            tests = (
                ("its stored opening", lb.opening),
                ("minus its stored opening", -lb.opening),
                ("the stock items' opening value", stock_opening),
                ("minus the stock items' opening value", -stock_opening),
                ("the source's opening stock value", source_stock or ZERO),
                ("minus the source's opening stock value", -(source_stock or ZERO)),
                (
                    "the source's opening minus ours",
                    (theirs - lb.opening) if theirs is not None else ZERO,
                ),
            )
            first = next(iter(dated.values()))
            all_dates = len(self.year_ends) + 1
            window: list[tuple[str, Decimal]] = []
            if len(dated) < all_dates and ends:
                facts.append(self._around(lb.id, ends[0]))
                window = self._window_sums(lb.id, ends[0])
                first = dated[ends[0]]
            special = self._special_vouchers(lb.id)
            if special:
                facts.append(
                    "vouchers posting to it: "
                    + ", ".join(f"{k} {n:,}" for k, n in sorted(special.items()))
                )
            day_one = self._first_day_differs(key, lb.id)
            if day_one is not None:
                facts.append(
                    "differs already on the books' first day"
                    if day_one
                    else "matches on the books' first day"
                )
            bills = self._opening_bills_of(lb.id) if bill_wise else None
            if bills is not None:
                facts.append(
                    "opening bills total "
                    + ("equal to" if self.close(bills, lb.opening) else "different from")
                    + " its opening"
                )
            tests += tuple(window)
            if bills is not None:
                tests += (("its opening bills minus its opening", bills - lb.opening),)
            effective = self._effective_across(key, lb.id)
            if effective:
                facts.append(effective)
            if key in getattr(self.source, "foreign_ledgers", frozenset()):
                facts.append("kept in a foreign currency; " + self._book_fact(key))
            if key in stock_keys:
                integration = {True: "integrated", False: "not integrated"}.get(
                    integrated, "integration unknown"
                )
                facts.append(
                    f"under the source's stock group (accounts {integration} with inventory)"
                )
            else:
                found, singles = self._windows(key, lb.id)
                facts += found
                tests += tuple(singles)
                elsewhere = self._named_elsewhere(lb.id)
                if elsewhere:
                    facts.append(elsewhere)
            equals = [label for label, value in tests if value and self.close(first, value)]
            equals += self._opposite_of(key, dated_by_key)
            equals += self._stock_value_fits(dated, lb.opening)
            self.out(
                f"  ledger {_letter(n)}: {'; '.join(where)}; {'; '.join(facts)}; {when}; "
                f"the difference equals: {', '.join(equals) or 'none of the tested amounts'}"
            )
        if len(keys) > PROFILE_LEDGERS:
            self.out(f"  ({len(keys) - PROFILE_LEDGERS:,} more not profiled)")

    def _where(
        self,
        ledger_id: int,
        group_id: int | None,
        primary: dict[int, str],
        tree: dict[int, tuple[int | None, str, list[str]]],
    ) -> list[str]:
        """Where a profiled ledger sits: its primary group, a renamed reserved group above
        it, and whether it's directly under its primary group."""
        where = [f"primary group {primary.get(ledger_id, 'unknown group')}"]
        renamed, direct = self._placement(tree, group_id)
        if renamed:
            where.append(f"under Tally's reserved group {renamed} (renamed)")
        if direct:
            where.append("directly under its primary group")
        return where

    def _opening_fact(self, ours: Decimal, theirs: Decimal | None) -> str:
        """The stored opening's side, and how it compares with the source's."""
        side = "zero" if not ours else ("debit" if ours > 0 else "credit")
        if theirs is None:
            compared = "the source's opening unknown"
        elif self.close(theirs, ours):
            compared = "equal to the source's"
        else:
            compared = "different from the source's"
        return f"stored opening {side}, {compared}"

    def _when(self, dated: dict[date, Decimal], ends: list[date]) -> str:
        """When a ledger differs: today, at how many year ends, by the same amount or not."""
        when = (
            f"differs {'today and ' if self.as_of in dated else ''}at "
            f"{len(ends)} of {len(self.year_ends)} year ends"
            + (f" (first {ends[0]}, last {ends[-1]})" if ends else "")
        )
        if len(dated) > 1:
            same = len(set(dated.values())) == 1
            when += ", by the same amount" if same else ", by changing amounts"
        return when

    def _opposite_of(self, key: str, dated_by_key: dict[str, dict[date, Decimal]]) -> list[str]:
        """Other differing ledgers whose difference is this one's opposite at every date both
        differ (one amount posted to the wrong one of the two)."""
        mine = dated_by_key.get(key, {})
        found = []
        for other, theirs in dated_by_key.items():
            common = set(mine) & set(theirs)
            if other == key or not common:
                continue
            if all(self.close(mine[d], -theirs[d]) for d in common):
                label = self.letters.get(other)
                found.append(
                    f"the opposite of ledger {label}'s difference"
                    if label
                    else "the opposite of an unprofiled ledger's difference"
                )
        return found

    def _lines_equal(self, key: str, ledger_id: int, start: date, end: date, diff: Decimal) -> str:
        """Lines of any voucher dated after `start` up to `end` whose amount equals the
        difference (either sign): which ledger we posted each to (this one, another differing
        ledger, another ledger by kind and primary group) and how the name in the voucher
        was matched to it (exact, alias, normalised). Counts and standard names only."""
        if not diff:
            return ""
        L, V = A.VoucherLine, A.Voucher  # noqa: N806
        size = abs(diff)
        rows = self.session.execute(
            select(L.ledger_id, L.line_no, V.raw_record_id)
            .join(V, V.id == L.voucher_id)
            .where(
                L.entity_id == self.entity_id,
                V.voucher_date > start,
                V.voucher_date <= end,
                func.abs(L.amount) >= size - self.tolerance,
                func.abs(L.amount) <= size + self.tolerance,
            )
            .limit(EQUAL_LINES)
        ).all()
        if not rows:
            return "lines of any voucher then equal to the difference: none"
        differing = {
            lb.id: k
            for k, lb in self.ours_today.items()
            if k in self.mismatched or k in self.year_end_diffs
        }
        found: Counter[str] = Counter()
        for line_ledger, line_no, raw_id in rows:
            if line_ledger == ledger_id:
                where = "this ledger"
            elif line_ledger in differing:
                letter = self.letters.get(differing[line_ledger])
                where = f"ledger {letter} (differs too)" if letter else "another differing ledger"
            elif line_ledger in self._deleted_ledgers():
                where = "a ledger deleted in the source"
            else:
                kind = (self.profile_rows.get(line_ledger) or (None,))[0]
                group = self.profile_primary.get(line_ledger, "unknown group")
                where = f"a {kind or 'unknown'} ledger in {group}"
            found[f"{where}, name matched {self._matched_how(line_ledger, line_no, raw_id)}"] += 1
        listed = ", ".join(f"{k} {n:,}" for k, n in sorted(found.items()))
        more = f" (first {EQUAL_LINES:,})" if len(rows) >= EQUAL_LINES else ""
        return f"lines of any voucher then equal to the difference{more}: {listed}"

    def _matched_how(self, ledger_id: int, line_no: int, raw_id: int | None) -> str:
        """How the name a stored voucher line used was matched to its ledger: exact, alias
        or normalised (core/names.py), from the voucher's stored record."""
        record = self.session.get(RawRecord, raw_id) if raw_id else None
        if record is None:
            return "unknown (no stored record)"
        try:
            mapped = self.connector.to_canonical(
                SourceRecord(
                    record.source_entity_key,
                    record.object_type,
                    record.source_key,
                    record.source_alter_id,
                    record.payload_format,
                    record.payload,  # type: ignore[arg-type]
                )
            )
        except Exception:  # noqa: BLE001 - reported as unknown
            return "unknown (record not readable)"
        voucher = next((m for m in mapped if hasattr(m, "lines")), None)
        if voucher is None or not 0 < line_no <= len(voucher.lines):
            return "unknown (line not found)"
        used = voucher.lines[line_no - 1].ledger_name
        name, *aliases = self._names_of(ledger_id)
        shared = self._ledgers_named().get(normalise(used), 0)
        note = f" (the name fits {shared:,} ledger rows here)" if shared > 1 else ""
        if used == name:
            return "exact" + note
        if used in aliases:
            return "by alias" + note
        if normalise(used) in {normalise(n) for n in (name, *aliases)}:
            return "after normalisation" + note
        return "otherwise" + note

    def _names_of(self, ledger_id: int) -> list[str]:
        """A ledger's name, then its aliases."""
        name, extra = self.session.execute(
            select(A.Ledger.name, A.Ledger.extra).where(A.Ledger.id == ledger_id)
        ).one()
        return [name, *((extra or {}).get("_aliases") or [])]

    def _deleted_ledgers(self) -> set[int]:
        if self._deleted is None:
            self._deleted = set(
                self.session.scalars(
                    select(A.Ledger.id).where(
                        A.Ledger.entity_id == self.entity_id, A.Ledger.is_deleted.is_(True)
                    )
                )
            )
        return self._deleted

    def _ledgers_named(self) -> Counter[str]:
        """Ledger rows (deleted ones too) per normalised name or alias."""
        if self._named is None:
            self._named = Counter()
            for name, extra in self.session.execute(
                select(A.Ledger.name, A.Ledger.extra).where(A.Ledger.entity_id == self.entity_id)
            ):
                names = {normalise(n) for n in (name, *((extra or {}).get("_aliases") or []))}
                self._named.update(names)
        return self._named

    def _named_elsewhere(self, ledger_id: int) -> str:
        """The stored vouchers that name the ledger (by its name or an alias) against those
        with lines on it here, and where it's named in lists the mapping doesn't read."""
        names = self._names_of(ledger_id)
        unread = getattr(self.connector, "unread_postings", None)
        if unread is None:
            return ""
        keys = select(A.EntitySource.source_entity_key).where(
            A.EntitySource.entity_id == self.entity_id
        )
        patterns = {
            "%>" + _like(written) + "</LEDGERNAME>%"
            for n in names
            for written in (escape(n), escape(n, {"'": "&apos;", '"': "&quot;"}))
        }
        naming = self.session.execute(
            select(RawRecord.source_key, RawRecord.payload)
            .where(
                RawRecord.source_entity_key.in_(keys),
                RawRecord.object_type == "voucher",
                or_(*(RawRecord.payload.like(pattern, escape="\\") for pattern in patterns)),
            )
            .limit(NAMED_VOUCHERS)
        ).all()
        posting = set(
            self.session.scalars(
                select(A.Voucher.source_key)
                .join(A.VoucherLine, A.VoucherLine.voucher_id == A.Voucher.id)
                .where(A.VoucherLine.ledger_id == ledger_id)
                .distinct()
            )
        )
        wanted = {normalise(n) for n in names}
        tags: Counter[str] = Counter()
        latest: dict[str, str] = {}
        for source_key, payload in naming:
            latest[source_key] = payload  # several stored versions: any one names it
        for payload in latest.values():
            for tag, used, _ in unread(payload):
                if normalise(used) in wanted:
                    tags[tag] += 1
        without = len(set(latest) - posting)
        text = (
            f"stored vouchers naming it {len(latest):,}, of them without a line on it here "
            f"{without:,}"
        )
        if tags:
            text += "; named in lists not read: " + ", ".join(
                f"{k} {n:,}" for k, n in sorted(tags.items())
            )
        return text

    def _stock_value_fits(self, dated: dict[date, Decimal], opening: Decimal) -> list[str]:
        """Whether, at every date the ledger differs, the difference is the source's closing
        stock value as of that date minus its stored opening (the source reports the ledger
        at the stock's value), or that value itself."""
        values = {}
        for on in dated:
            source = self.source if on == self.as_of else self.source_years.get(on)
            closing = getattr(source, "closing_stock", None)
            if closing is None:
                return []
            values[on] = Decimal(closing)
        fits = []
        if all(self.close(dated[d], values[d] - opening) for d in dated):
            fits.append("the closing stock value minus its stored opening (at every date)")
        if all(self.close(dated[d], values[d]) for d in dated):
            fits.append("the closing stock value (at every date)")
        return fits

    def _special_vouchers(self, ledger_id: int) -> Counter[str]:
        """Vouchers posting to the ledger that count differently: optional, cancelled,
        post-dated, and reversing journals or memorandum vouchers (also custom types under
        them)."""
        L, V, T = A.VoucherLine, A.Voucher, A.VoucherType  # noqa: N806
        found: Counter[str] = Counter()
        for optional, cancelled, post_dated, standard, n in self.session.execute(
            select(
                V.is_optional,
                V.is_cancelled,
                V.is_post_dated,
                T.standard_type,
                func.count(func.distinct(V.id)),
            )
            .join(L, L.voucher_id == V.id)
            .join(T, T.id == V.voucher_type_id)
            .where(L.ledger_id == ledger_id)
            .group_by(V.is_optional, V.is_cancelled, V.is_post_dated, T.standard_type)
        ):
            for flag, label in ((optional, "optional"), (cancelled, "cancelled"),
                                (post_dated, "post-dated")):  # fmt: skip
                if flag:
                    found[label] += n
            if standard in ("Reversing Journal", "Memorandum"):
                found[standard] += n
        return found

    def _window_sums(self, ledger_id: int, year_end: date) -> list[tuple[str, Decimal]]:
        """Tested amounts for a ledger that differs at one year end only: its lines of each
        voucher type and kind (counted, optional, ...) in the month up to that year end, and
        in the month after it, with either sign."""
        L, V, T = A.VoucherLine, A.Voucher, A.VoucherType  # noqa: N806
        sums: Counter[str] = Counter()
        before, after = year_end - timedelta(days=31), year_end + timedelta(days=31)
        for on, standard, base, deleted, cancelled, optional, effective, amount in (
            self.session.execute(
                select(
                    L.voucher_date, T.standard_type, T.base_type, V.is_deleted,
                    V.is_cancelled, V.is_optional, L.is_effective, L.amount,
                )
                .join(V, V.id == L.voucher_id)
                .join(T, T.id == V.voucher_type_id)
                .where(L.ledger_id == ledger_id, L.voucher_date > before, L.voucher_date <= after)
            )
        ):  # fmt: skip
            kind = _type(standard, base)
            why = "" if effective else (_category(deleted, cancelled, optional) or "not posting")
            side = "the month up to" if on <= year_end else "the month after"
            sums[f"{why + ' ' if why else ''}{kind} lines in {side} {year_end}"] += Decimal(amount)
        out = []
        for label, total in sorted(sums.items()):
            out += [(label, total), (f"minus {label}", -total)]
        return out

    def _first_day_differs(self, key: str, ledger_id: int) -> bool | None:
        """Whether the ledger already differs on the books' first day (the source's balance
        then against ours)."""
        books = self._books_day()
        diffs = self._diffs_at(books) if books else None
        if diffs is None:
            return None
        return key in diffs

    def _books_day(self) -> date | None:
        """The books' first day, or the first reliable date after it."""
        return self.rule.on_or_after(self.row.books_from) if self.row.books_from else None

    # --- balances at any date, and when a ledger starts or stops differing ----------------

    def _source_at(self, on: date) -> Any:
        """The source's balances as of a date (read once; extra dates count as probes)."""
        if on == self.as_of:
            return self.source
        if on in self.source_years:
            return self.source_years[on]
        if on not in self._sources:
            self.probes += 1
            self._sources[on] = self._read("closing_balances", self.entity, on)
        return self._sources[on]

    def _diffs_at(self, on: date) -> dict[str, Decimal] | None:
        """Ledgers that differ as of a date (source key -> theirs minus ours; profit carriers
        left out), or None when the source's balances couldn't be read."""
        if on not in self._diffs:
            source = self._source_at(on)
            if not _has_balances(source):
                self._diffs[on] = None
            else:
                explained = self._at_stock_value(on) | self._at_book_value(on)
                self._diffs[on] = {
                    key: source.ledgers[key] - lb.balance
                    for key, lb in self._year_balances(on).items()
                    if key in source.ledgers
                    and key not in source.profit_carriers
                    and key not in explained
                    and not self.close(source.ledgers[key], lb.balance)
                }
        return self._diffs[on]

    def _at_stock_value(self, on: date) -> set[str]:
        """Stock ledgers the source reports at its closing stock value as of a date: treated
        as explained, as validation compares them with that value (LB-VAL-021)."""
        source = self._source_at(on)
        if not _has_balances(source):
            return set()
        ours = {key: lb.balance for key, lb in self._year_balances(on).items()}
        return at_stock_value(ours, source, self.tolerance)

    def _at_book_value(self, on: date) -> set[str]:
        """Foreign-currency ledgers equal to the source's book value as of a date (their
        revaluation at current rates left out): explained, as in validation (LB-VAL-022)."""
        source = self._source_at(on)
        if not _has_balances(source):
            return set()
        ours = {key: lb.balance for key, lb in self._year_balances(on).items()}
        found: set[str] = set()
        for keys, (book, mine) in at_book_value(ours, source).items():
            if self.close(book, mine):
                found |= keys
        return found

    def _book_fact(self, key: str) -> str:
        """For a foreign-currency ledger that differs: whether the source gives a book value
        for it (alone or with others of its group) and whether ours equals it."""
        ours = {k: lb.balance for k, lb in self.ours_today.items()}
        for keys, (book, mine) in at_book_value(ours, self.source).items():
            if key in keys:
                alone = "its" if len(keys) == 1 else f"its group's ({len(keys):,} ledgers)"
                state = "equals" if self.close(book, mine) else "differs from"
                return f"{alone} book value in the source {state} ours"
        return "the source gives no book value for it (its closing balance is revalued)"

    def _cancelling(self, diffs: dict[str, Decimal]) -> int:
        """Pairs of ledgers whose differences are each other's opposite."""
        seen: Counter[Decimal] = Counter()
        pairs = 0
        for diff in diffs.values():
            for amount in list(seen):
                if seen[amount] and self.close(amount, -diff):
                    seen[amount] -= 1
                    pairs += 1
                    break
            else:
                seen[diff] += 1
        return pairs

    def _checked(self, key: str) -> list[tuple[date, bool]]:
        """Dates already compared, in order, with whether the ledger differs then."""
        dates = {*self.year_ends, self.as_of, *self._diffs}
        out = []
        for on in sorted(dates):
            diffs = self._diffs_at(on)
            if diffs is not None:
                out.append((on, key in diffs))
        return out

    def _narrow(self, key: str, start: date, end: date, differs_at_end: bool) -> tuple[date, date]:
        """The ledger's state changes between `start` and `end`: the narrowest (a, b] found
        by asking the source for reliable dates in between (at most PROBES dates in all)."""
        candidates = []
        on = start + timedelta(days=1)
        while on < end:
            if self.rule.reliable(on):
                candidates.append(on)
            on += timedelta(days=1)
        low, high = 0, len(candidates)  # candidates[low:high] lie strictly between
        while low < high:
            middle = (low + high) // 2
            probe = candidates[middle]
            known = probe in self._diffs
            if not known and self.probes >= PROBES:
                break
            diffs = self._diffs_at(probe)
            if diffs is None:
                break
            if (key in diffs) == differs_at_end:
                end, high = probe, middle
            else:
                start, low = probe, middle + 1
        return start, end

    def _windows(self, key: str, ledger_id: int) -> tuple[list[str], list[tuple[str, Decimal]]]:
        """When the ledger starts to differ after matching, and when it matches again after
        differing: each narrowed to the dates between which it changes, with the vouchers
        posting to it then (counts by kind, voucher type and effective date). Returns those
        facts and amounts to test (one voucher's figures that equal the difference)."""
        checked = self._checked(key)
        facts: list[str] = []
        tests: list[tuple[str, Decimal]] = []
        changes = list(zip(checked, checked[1:], strict=False))
        starts = next(((a, b) for (a, x), (b, y) in changes if not x and y), None)
        stops = next(((a, b) for (a, x), (b, y) in changes if x and not y), None)
        for label, found, differs_at_end in (
            ("first differs", starts, True),
            ("matches again", stops, False),
        ):
            if found is None:
                continue
            start, end = self._narrow(key, found[0], found[1], differs_at_end)
            diff = (self._diffs_at(end if differs_at_end else start) or {}).get(key, ZERO)
            described, fits = self._in_window(ledger_id, start, end, diff)
            if differs_at_end:
                equal = self._lines_equal(key, ledger_id, start, end, diff)
                described += f"; {equal}" if equal else ""
            facts.append(f"{label} between {start} and {end} ({described})")
            tests += [(f"{fit} ({label} window)", diff) for fit in fits]
        return facts, tests

    def _in_window(
        self, ledger_id: int, start: date, end: date, diff: Decimal
    ) -> tuple[str, list[str]]:
        """Vouchers posting to the ledger dated after `start` up to `end`: counts by kind,
        voucher type and effective date; and which single voucher's figures equal the
        difference (either sign): its line on the ledger, its lines on it together, or its
        total."""
        L, V, T = A.VoucherLine, A.Voucher, A.VoucherType  # noqa: N806
        vouchers: dict[int, dict[str, Any]] = {}
        for (
            vid, dated, effective, standard, base, deleted, cancelled, optional, post_dated,
            amount,
        ) in self.session.execute(
            select(
                V.id, V.voucher_date, V.effective_date, T.standard_type, T.base_type,
                V.is_deleted, V.is_cancelled, V.is_optional, V.is_post_dated, L.amount,
            )
            .join(L, L.voucher_id == V.id)
            .join(T, T.id == V.voucher_type_id)
            .where(L.ledger_id == ledger_id, V.voucher_date > start, V.voucher_date <= end)
            .limit(WINDOW_VOUCHERS)
        ):  # fmt: skip
            special = standard if standard in ("Reversing Journal", "Memorandum") else None
            kind = (
                _category(deleted, cancelled, optional)
                or special
                or ("post-dated" if post_dated else "regular")
            )
            entry = vouchers.setdefault(
                vid,
                {
                    "kind": kind,
                    "type": _type(standard, base),
                    "lines": [],
                    "effective": effective if effective and effective != dated else None,
                },
            )
            entry["lines"].append(Decimal(amount))
        if not vouchers:
            return "no vouchers posting to it then", []
        totals = dict(
            self.session.execute(
                select(L.voucher_id, func.sum(L.amount))
                .where(L.voucher_id.in_(list(vouchers)), L.amount > 0)
                .group_by(L.voucher_id)
            ).all()
        )
        fits: set[str] = set()
        if diff:
            for vid, v in vouchers.items():
                what = f"({v['type']}, {v['kind']})"
                if any(self.close(abs(diff), abs(a)) for a in v["lines"]):
                    fits.add(f"one voucher's line on it {what}")
                together = sum(v["lines"], ZERO)
                if len(v["lines"]) > 1 and together and self.close(abs(diff), abs(together)):
                    fits.add(f"one voucher's lines on it together {what}")
                total = Decimal(totals.get(vid) or 0)
                if total and self.close(abs(diff), total):
                    fits.add(f"one voucher's total {what}")
        kinds = Counter(v["kind"] for v in vouchers.values())
        types = Counter(v["type"] for v in vouchers.values())
        effective = [v["effective"] for v in vouchers.values() if v["effective"]]
        outside = sum(1 for e in effective if not start < e <= end)
        described = (
            f"vouchers posting to it then {len(vouchers):,}: "
            + ", ".join(f"{k} {n:,}" for k, n in sorted(kinds.items()))
            + "; "
            + ", ".join(f"{k} {n:,}" for k, n in sorted(types.items()))
            + f"; effective date differs {len(effective):,}"
            + (f", outside these dates {outside:,}" if outside else "")
        )
        return described, sorted(fits)

    def _effective_across(self, key: str, ledger_id: int) -> str | None:
        """Vouchers posting to the ledger whose effective date isn't their date, and how many
        have the two on different sides of a date compared (the source counts by the date:
        checked on the test company, 2026-10-15)."""
        if self._effective_known is None:
            self._effective_known = bool(
                self.session.scalar(
                    select(func.count())
                    .select_from(A.Voucher)
                    .where(
                        A.Voucher.entity_id == self.entity_id,
                        A.Voucher.effective_date.is_not(None),
                    )
                )
            )
        if not self._effective_known:
            return "effective dates not stored yet (run transform rebuild)"
        dates = [on for on, _ in self._checked(key)]
        differ = across = 0
        # One row per voucher (its id makes two vouchers with the same dates two rows).
        for _, dated, effective in self.session.execute(
            select(A.Voucher.id, A.Voucher.voucher_date, A.Voucher.effective_date)
            .join(A.VoucherLine, A.VoucherLine.voucher_id == A.Voucher.id)
            .where(
                A.VoucherLine.ledger_id == ledger_id,
                A.Voucher.effective_date.is_not(None),
                A.Voucher.effective_date != A.Voucher.voucher_date,
            )
            .distinct()
            .limit(EFFECTIVE_SAMPLE)
        ):
            differ += 1
            low, high = sorted((dated, effective))
            if any(low <= on < high for on in dates):
                across += 1
        if not differ:
            return None
        return (
            f"vouchers whose effective date isn't their date {differ:,}, the two on different "
            f"sides of a date compared {across:,}"
        )

    def _opening_bills_of(self, ledger_id: int) -> Decimal | None:
        """The source's opening bills of a bill-wise ledger, totalled (canonical sign)."""
        if not self._opening_bills_read:
            found = self._read("bill_outstanding", self.entity)
            self._opening_bills = found[1] if isinstance(found, tuple) else None
            self._opening_bills_read = True
        if self._opening_bills is None:
            return None
        name = self.session.scalar(select(A.Ledger.name).where(A.Ledger.id == ledger_id))
        total = self._opening_bills.get(name)
        return Decimal(total) if total is not None else Decimal(0)

    def _around(self, ledger_id: int, year_end: date) -> str:
        """For a ledger that differs at some dates only: the voucher types with lines in the
        last month up to that year end and the first month after it."""
        L, V, T = A.VoucherLine, A.Voucher, A.VoucherType  # noqa: N806
        start, after = year_end.replace(day=1), year_end + timedelta(days=31)
        kinds = sorted(
            {
                _type(standard, base)
                for standard, base in self.session.execute(
                    select(T.standard_type, T.base_type)
                    .join(V, V.voucher_type_id == T.id)
                    .join(L, L.voucher_id == V.id)
                    .where(
                        L.ledger_id == ledger_id, L.voucher_date >= start, L.voucher_date <= after
                    )
                    .distinct()
                )
            }
        )
        return f"lines around the year end {year_end} (its last month and the next): " + (
            ", ".join(kinds) if kinds else "none"
        )

    def _group_tree(self) -> dict[int, tuple[int | None, str, list[str]]]:
        """Group id -> (parent id, name, aliases)."""
        return {
            gid: (parent, name, list((extra or {}).get("_aliases") or []))
            for gid, parent, name, extra in self.session.execute(
                select(
                    A.AccountGroup.id,
                    A.AccountGroup.parent_id,
                    A.AccountGroup.name,
                    A.AccountGroup.extra,
                ).where(A.AccountGroup.entity_id == self.entity_id)
            )
        }

    def _placement(
        self, tree: dict[int, tuple[int | None, str, list[str]]], group_id: int | None
    ) -> tuple[str | None, bool]:
        """(the reserved name of a renamed reserved group above the ledger, whether the
        ledger sits directly under its primary group)."""
        reserved = self._reserved_groups()
        renamed, seen, gid = None, set(), group_id
        direct = gid in tree and tree[gid][0] is None
        while gid in tree and gid not in seen:
            seen.add(gid)
            parent, name, aliases = tree[gid]
            if renamed is None and name.casefold() not in reserved:
                renamed = next(
                    (reserved[a.casefold()] for a in aliases if a.casefold() in reserved), None
                )
            gid = parent
        return renamed, direct

    def _opening(self) -> None:
        """The source's own difference in opening balances, as its trial balance from the
        books' beginning shows it (what the opening check warns about), and what it equals:
        the stock items' opening value, the stock ledgers' openings or their difference.
        Then the same figure computed from the ledgers' and items' openings, and what the gap
        between the two equals (the stock the source's totals use against the items')."""
        difference = getattr(self.source, "opening_difference", None)
        if difference is None:
            return
        stock_ledgers = getattr(self.source, "stock_ledger_openings", None) or ZERO
        source_stock = getattr(self.source, "opening_stock", None) or ZERO
        items = getattr(self.source, "item_opening_value", None)
        stored_items = self._stored_items_opening()
        items = stored_items if items is None else items
        amounts = (
            ("the stock items' opening value", items),
            ("the stock ledgers' openings", stock_ledgers),
            ("the items' opening value minus the stock ledgers' openings", items - stock_ledgers),
            ("the source's opening stock", source_stock),
            ("the source's opening stock minus the items' opening value", source_stock - items),
            ("the items' opening value stored here", stored_items),
        )
        if self.close(difference, ZERO):
            self.out(
                "Opening difference (the source's own trial balance from the books' "
                "beginning): none"
            )
        else:
            self.out(
                "Opening difference (the source's own trial balance from the books' "
                "beginning): non-zero; it equals: " + self._fitting(difference, amounts)
            )
        integrated = getattr(self.source, "integrated", None)
        if integrated is False:
            self.out(
                "  accounts not integrated with inventory: the items' opening value minus the "
                "stock ledgers' openings is "
                + ("zero" if self.close(items, stock_ledgers) else "non-zero")
                + (
                    " (equal to the difference)"
                    if items != stock_ledgers and self.close(difference, items - stock_ledgers)
                    else ""
                )
            )
        self._opening_by_group(difference, amounts)
        stock_keys = getattr(self.source, "stock_ledgers", frozenset()) or frozenset()
        source_openings = getattr(self.source, "ledger_openings", {}) or {}
        if not source_openings:
            return
        computed = sum(
            (v for k, v in source_openings.items() if not (integrated and k in stock_keys)),
            ZERO,
        ) + (items if integrated else ZERO)
        if self.close(computed, difference):
            self.out("  from the ledgers' and items' openings: the same")
            return
        self.out(
            "  from the ledgers' and items' openings: "
            + ("none" if self.close(computed, ZERO) else "non-zero")
            + "; the gap to the trial balance's equals: "
            + self._fitting(computed - difference, amounts)
        )

    def _stored_items_opening(self) -> Decimal:
        """The stock items' opening value stored here, totalled."""
        total = self.session.scalar(
            select(func.coalesce(func.sum(A.Item.opening_value), 0)).where(
                A.Item.entity_id == self.entity_id, A.Item.is_deleted.is_(False)
            )
        )
        return Decimal(total or 0)

    def _opening_by_group(
        self, difference: Decimal, amounts: Iterable[tuple[str, Decimal]]
    ) -> None:
        """The source's own opening of each primary group: whether the difference equals one
        group's openings, and which groups' own openings differ from the total of their
        ledgers' openings (and what that gap equals). Reserved group names only."""
        groups = getattr(self.source, "group_openings", {}) or {}
        if not groups:
            return
        reserved = getattr(self.source, "reserved_groups", frozenset()) or frozenset()

        def label(name: str) -> str:
            return name if name in reserved else "custom primary group"

        theirs: Counter[str] = Counter()
        for name, opening in groups.items():
            theirs[label(name)] += opening
        if not self.close(difference, ZERO):
            self.out(
                "  equal to one primary group's openings: "
                + self._fitting(difference, [(f"primary group {k}", v) for k, v in theirs.items()])
            )
        source_openings = getattr(self.source, "ledger_openings", {}) or {}
        ours = self.ours_today
        primary = self._primary_groups()
        ledgers: Counter[str] = Counter()
        for key, opening in source_openings.items():
            lb = ours.get(key)
            if lb is not None:
                ledgers[primary.get(lb.id, "unknown group")] += opening
        differ = [
            f"{group} (the gap equals: {self._fitting(theirs[group] - ledgers[group], amounts)})"
            for group in sorted(theirs)
            if not self.close(theirs[group], ledgers[group])
        ]
        self.out(
            "  primary groups whose own opening differs from their ledgers' openings: "
            + ("; ".join(differ) if differ else "none")
        )

    def _fitting(self, value: Decimal, amounts: Iterable[tuple[str, Decimal]]) -> str:
        """The amounts (or minus them) that equal `value`, by label."""
        fits = []
        for label, amount in amounts:
            if amount and self.close(value, amount):
                fits.append(label)
            elif amount and self.close(value, -amount):
                fits.append(f"minus {label}")
        return ", ".join(fits) if fits else "none of the tested amounts"

    def _job_work(self) -> None:
        """Job work vouchers and where their stock sits (counts and standard names only)."""
        V, T, Inv, G = A.Voucher, A.VoucherType, A.InventoryLine, A.Godown  # noqa: N806
        vouchers = dict(
            self.session.execute(
                select(T.standard_type, func.count())
                .join(V, V.voucher_type_id == T.id)
                .where(V.entity_id == self.entity_id, T.standard_type.in_(JOB_WORK_TYPES))
                .group_by(T.standard_type)
            ).all()
        )
        lines = dict(
            self.session.execute(
                select(G.holding, func.count())
                .join(Inv, Inv.godown_id == G.id)
                .where(Inv.entity_id == self.entity_id, G.holding != "own")
                .group_by(G.holding)
            ).all()
        )
        if not vouchers and not lines:
            return
        self.out("Job work:")
        if vouchers:
            listed = ", ".join(f"{k} {n:,}" for k, n in sorted(vouchers.items()))
            self.out(f"  vouchers: {listed}")
        for holding, n in sorted(lines.items()):
            self.out(
                f"  inventory lines at {GODOWN_KINDS[holding]}: {n:,}"
                + (
                    " (not in the source's stock balances)"
                    if holding == "ours_with_third_party"
                    else ""
                )
            )

    def _census(self) -> None:
        """Per voucher type: what the stored vouchers contain that the mapping doesn't read,
        and whether stock vouchers have inventory lines here."""
        V, T = A.Voucher, A.VoucherType  # noqa: N806
        counts = self.session.execute(
            select(T.standard_type, T.base_type, func.count())
            .join(V, V.voucher_type_id == T.id)
            .where(V.entity_id == self.entity_id)
            .group_by(T.standard_type, T.base_type)
        ).all()
        with_inventory = dict(
            self.session.execute(
                select(T.standard_type, func.count(func.distinct(A.InventoryLine.voucher_id)))
                .join(V, V.id == A.InventoryLine.voucher_id)
                .join(T, T.id == V.voucher_type_id)
                .where(V.entity_id == self.entity_id)
                .group_by(T.standard_type)
            ).all()
        )
        self.out("Stored vouchers by type (sample of their content):")
        for standard, base, n in sorted(counts, key=lambda r: -r[2]):
            hints: Counter[str] = Counter()
            outside: Counter[str] = Counter()
            sampled = 0
            for (payload,) in self.session.execute(
                select(RawRecord.payload)
                .join(V, V.raw_record_id == RawRecord.id)
                .join(T, T.id == V.voucher_type_id)
                .where(
                    V.entity_id == self.entity_id,
                    T.standard_type.is_(None) if standard is None else T.standard_type == standard,
                    T.base_type == base,
                )
                .limit(SAMPLE)
            ):
                sampled += 1
                hints.update(self._hints("voucher", payload))
                outside.update(self._unread_postings(payload))
            parts = [f"{n:,} vouchers"]
            if standard in STOCK_TYPES or standard is None:
                parts.append(f"with inventory lines here {with_inventory.get(standard, 0):,}")
            if hints:
                parts.append(
                    f"of {sampled:,} read: "
                    + ", ".join(f"{k} {c:,}" for k, c in hints.most_common(8))
                )
            if outside:
                parts.append(
                    "ledger lines outside the lists read: "
                    + ", ".join(f"{k} {c:,}" for k, c in sorted(outside.items()))
                )
            self.out(f"  {_type(standard, base)}: " + "; ".join(parts))

    def _unread_postings(self, payload: str | None) -> Counter[str]:
        """Ledger lines of a stored voucher outside the lists the mapping reads, by list and
        the kind of ledger named (party or other; Tally's tag names only)."""
        unread = getattr(self.connector, "unread_postings", None)
        if unread is None or not payload:
            return Counter()
        if self._kinds_by_name is None:
            self._kinds_by_name = {}
            for name, extra, kind in self.session.execute(
                select(A.Ledger.name, A.Ledger.extra, A.Ledger.ledger_kind).where(
                    A.Ledger.entity_id == self.entity_id
                )
            ):
                for n in (name, *((extra or {}).get("_aliases") or [])):
                    self._kinds_by_name.setdefault(normalise(n), kind)
        found: Counter[str] = Counter()
        for tag, name, _ in unread(payload):
            kind = self._kinds_by_name.get(normalise(name), "unknown")
            found[f"{tag} ({'a party ledger' if kind == 'party' else 'another ledger'})"] += 1
        return found

    def _hints(self, object_type: str, payload: str | None) -> set[str]:
        hints = getattr(self.connector, "payload_hints", None)
        if hints is None or not payload:
            return set()
        return set(hints(object_type, payload))


def analyse(
    session: Session,
    connection: Connection,
    connector: Connector,
    entities: Iterable[tuple[SourceEntity, int, str]],
    as_of: date,
    tolerance: Decimal,
    progress: Progress,
) -> list[str]:
    """Analysis lines for each (source entity, entity id, label)."""
    out: list[str] = []
    for entity, entity_id, label in entities:
        progress(f"{label}: analysing the mismatches as of {as_of}")
        lines = Analyser(
            session,
            connection,
            connector,
            entity,
            entity_id,
            as_of,
            tolerance,
            lambda message, label=label: progress(f"{label}: {message}"),
        ).run()
        out.append(f"{label} as of {as_of}:")
        out += [f"  {line}" for line in lines]
    return out
