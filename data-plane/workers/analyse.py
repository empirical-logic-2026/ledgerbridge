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
  with lines in that month.
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
"""

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from connectors.base import Connector, SourceEntity
from core.models import Connection
from core.models import accounting as A  # noqa: N812
from core.models.source import RawRecord
from core.validation import PROFIT_NATURES, Validator, financial_year_ends

Progress = Callable[[str], None]
ZERO = Decimal(0)
SAMPLE = 500  # stored vouchers read per voucher type for the content census
PROFILE_LEDGERS = 26  # differing ledgers profiled (ledger A to Z)
EFFECTIVE_SAMPLE = 5_000  # vouchers per profiled ledger checked for their effective date
_DATE = re.compile(r"<DATE[^>]*>\s*(\d{8})\s*</DATE>")
_EFFECTIVE = re.compile(r"<EFFECTIVEDATE[^>]*>\s*(\d{8})\s*</EFFECTIVEDATE>")
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


def fy_start(on: date, fy_start_month: int) -> date:
    """First day of the financial year containing `on`."""
    year = on.year if on.month >= fy_start_month else on.year - 1
    return date(year, fy_start_month, 1)


class Analyser:
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
        self.validator = Validator(session, entity_id, as_of, tolerance, connection.id)
        self.row = self.validator.entity
        self.lines: list[str] = []
        self.year_end_diffs: dict[str, dict[date, Decimal]] = {}  # key -> year end -> diff
        self.mismatched: dict[str, Decimal] = {}

    def close(self, a: Decimal, b: Decimal) -> bool:
        return abs(Decimal(a) - Decimal(b)) <= self.tolerance

    def out(self, line: str) -> None:
        self.lines.append(line)

    def _read(self, method: str, *args: Any) -> Any:
        read = getattr(self.connector, method, None)
        if read is None:
            return None
        try:
            return read(*args)
        except Exception as exc:  # noqa: BLE001 - reported as unavailable
            return exc

    # --- driver -----------------------------------------------------------------------

    def run(self) -> list[str]:
        self.year_ends = financial_year_ends(
            self.row.books_from, self.row.fy_start_month, self.as_of
        )
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

    def _primary_groups(self) -> dict[int, str]:
        """Ledger id -> its primary group, by the source's reserved name or "custom"."""
        reserved = {
            n.casefold()
            for n in (getattr(self.connector, "reserved_names", None) or {}).get("group", ())
        }
        groups = {
            gid: (parent, name, (extra or {}).get("_aliases") or [])
            for gid, parent, name, extra in self.session.execute(
                select(
                    A.AccountGroup.id,
                    A.AccountGroup.parent_id,
                    A.AccountGroup.name,
                    A.AccountGroup.extra,
                ).where(A.AccountGroup.entity_id == self.entity_id)
            )
        }

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

    def _ledgers(self) -> None:
        self.out("Ledger closing balances as of the validation date:")
        if not hasattr(self.source, "ledgers"):
            self.out(f"  the source's balances couldn't be read ({type(self.source).__name__})")
            self.mismatched: dict[str, Decimal] = {}
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
        self.mismatched = {}
        self.unexplained_keys: list[str] = []
        explained = by_pair = 0
        twice = "the opening balance is counted twice here, or the source leaves it out"
        for key, lb in ours.items():
            theirs = self.source.ledgers.get(key)
            if theirs is None or key in carriers or self.close(theirs, lb.balance):
                continue
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
            end = following - timedelta(days=1)
            if end > self.as_of or following > first_year.replace(year=first_year.year + 1):
                break
            month_ends.append(end)
            current = following
        if not month_ends:
            return
        self.say("reading the source's balances at each month end of the first financial year")
        pending = set(self.unexplained_keys)
        first: dict[str, date] = {}
        for end in month_ends:
            source = self._read("closing_balances", self.entity, end)
            if not hasattr(source, "ledgers"):
                self.out(f"  first month: the source's balances at {end} couldn't be read")
                return
            here = {lb.source_key: lb for lb in self.validator.ledger_balances(end)}
            for key in list(pending):
                theirs, lb = source.ledgers.get(key), here.get(key)
                if theirs is not None and lb is not None and not self.close(theirs, lb.balance):
                    first[key] = end
                    pending.discard(key)
            if not pending:
                break
        months = Counter(f"{end:%Y-%m}" for end in first.values())
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
                        L.voucher_date >= end.replace(day=1),
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
            if not hasattr(source, "ledgers"):
                continue
            theirs = source.ledgers.get(key)
            ours = self._year_balances(year_end).get(key)
            if theirs is not None and ours is not None and not self.close(theirs, ours.balance):
                return f"first differs at the year end {year_end}"
        return "first differs in the current financial year (every year end matches)"

    def _year_balances(self, year_end: date) -> dict[str, Any]:
        cache = self.__dict__.setdefault("_year_cache", {})
        if year_end not in cache:
            cache[year_end] = {lb.source_key: lb for lb in self.validator.ledger_balances(year_end)}
        return cache[year_end]

    def _year_ends(self) -> None:
        if not self.year_ends:
            self.out("Year ends: the books have no financial year end before the validation date")
            return
        self.out("Ledger balances at each financial year end:")
        for year_end in self.year_ends:
            source = self.source_years.get(year_end)
            if not hasattr(source, "ledgers"):
                self.out(f"  {year_end}: the source's balances couldn't be read")
                continue
            ours = self._year_balances(year_end)
            start = fy_start(year_end, self.row.fy_start_month)
            differ, fits = 0, Counter()
            for key, lb in ours.items():
                theirs = source.ledgers.get(key)
                if (
                    theirs is None
                    or key in source.profit_carriers
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
        if not hasattr(self.source, "ledgers") or not self.source.profit_carriers:
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
        ours = getattr(self, "ours_today", {}) or {
            lb.source_key: lb for lb in self.validator.ledger_balances(self.as_of)
        }
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
        stock_opening = Decimal(
            self.session.scalar(
                select(func.coalesce(func.sum(A.Item.opening_value), 0)).where(
                    A.Item.entity_id == self.entity_id, A.Item.is_deleted.is_(False)
                )
            )
            or 0
        )
        source_openings = getattr(self.source, "ledger_openings", {}) or {}
        source_stock = getattr(self.source, "opening_stock", None)
        primary = self._primary_groups()
        tree = self._group_tree()
        self.out(f"Ledger profiles (ledgers that differ today or at a year end: {len(keys):,}):")
        for n, key in enumerate(keys[:PROFILE_LEDGERS]):
            lb = ours.get(key)
            if lb is None:
                continue
            kind, currency, bill_wise, group_id = rows.get(lb.id, (None, None, False, None))
            where = [f"primary group {primary.get(lb.id, 'unknown group')}"]
            renamed, direct = self._placement(tree, group_id)
            if renamed:
                where.append(f"under Tally's reserved group {renamed} (renamed)")
            if direct:
                where.append("directly under its primary group")
            facts = [f"kind {kind or 'unknown'}", f"nature {lb.nature or 'unknown'}"]
            if currency and currency != "INR":
                facts.append("foreign currency")
            if bill_wise:
                facts.append("bill-wise")
            opening = "zero" if not lb.opening else ("debit" if lb.opening > 0 else "credit")
            theirs = source_openings.get(key)
            if theirs is None:
                compared = "the source's opening unknown"
            elif self.close(theirs, lb.opening):
                compared = "equal to the source's"
            else:
                compared = "different from the source's"
            facts.append(f"stored opening {opening}, {compared}")
            posted = sorted({*self.counted.get(lb.id, {}), *self.excluded.get(lb.id, {})})
            facts.append("posted by: " + (", ".join(posted) if posted else "no vouchers"))
            dated = dict(self.year_end_diffs.get(key, {}))
            if key in self.mismatched:
                dated[self.as_of] = self.mismatched[key]
            amounts = set(dated.values())
            ends = [d for d in self.year_ends if d in dated]
            when = (
                f"differs {'today and ' if self.as_of in dated else ''}at "
                f"{len(ends)} of {len(self.year_ends)} year ends"
                + (f" (first {ends[0]}, last {ends[-1]})" if ends else "")
            )
            if len(dated) > 1:
                when += ", by the same amount" if len(amounts) == 1 else ", by changing amounts"
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
            effective = self._effective_dates(lb.id)
            if effective:
                facts.append(
                    f"vouchers whose effective date differs from their date: {effective:,}"
                )
            equals = [label for label, value in tests if value and self.close(first, value)]
            equals += self._stock_value_fits(dated, lb.opening)
            self.out(
                f"  ledger {_letter(n)}: {'; '.join(where)}; {'; '.join(facts)}; {when}; "
                f"the difference equals: {', '.join(equals) or 'none of the tested amounts'}"
            )
        if len(keys) > PROFILE_LEDGERS:
            self.out(f"  ({len(keys) - PROFILE_LEDGERS:,} more not profiled)")

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
        then against ours), read once."""
        if "_first_day" not in self.__dict__:
            books = self.row.books_from
            source = self._read("closing_balances", self.entity, books) if books else None
            ours = (
                {lb.source_key: lb.balance for lb in self.validator.ledger_balances(books)}
                if books
                else {}
            )
            self._first_day = (getattr(source, "ledgers", None), ours)
        theirs, ours = self._first_day
        if theirs is None or key not in theirs or key not in ours:
            return None
        return not self.close(theirs[key], ours[key])

    def _opening_bills_of(self, ledger_id: int) -> Decimal | None:
        """The source's opening bills of a bill-wise ledger, totalled (canonical sign)."""
        if "_opening_bills" not in self.__dict__:
            found = self._read("bill_outstanding", self.entity)
            self._opening_bills = found[1] if isinstance(found, tuple) else None
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

    def _effective_dates(self, ledger_id: int) -> int:
        """Vouchers posting to the ledger whose effective date (Tally's EFFECTIVEDATE) isn't
        their date (sampled: at most EFFECTIVE_SAMPLE vouchers)."""
        count = 0
        for (payload,) in self.session.execute(
            select(RawRecord.payload)
            .join(A.Voucher, A.Voucher.raw_record_id == RawRecord.id)
            .join(A.VoucherLine, A.VoucherLine.voucher_id == A.Voucher.id)
            .where(A.VoucherLine.ledger_id == ledger_id)
            .distinct()
            .limit(EFFECTIVE_SAMPLE)
        ):
            dated = _DATE.search(payload or "")
            effective = _EFFECTIVE.search(payload or "")
            if dated and effective and dated.group(1) != effective.group(1):
                count += 1
        return count

    def _group_tree(self) -> dict[int, tuple[int | None, str, list[str]]]:
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
        reserved = {
            n.casefold(): n
            for n in (getattr(self.connector, "reserved_names", None) or {}).get("group", ())
        }
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
        """The source's own difference in opening balances (as the opening check uses it)
        and what it equals: the stock ledgers' openings (the source counting them after
        all), the opening stock value, or our openings' differences."""
        difference = getattr(self.source, "opening_difference", None)
        if difference is None:
            return
        if self.close(difference, ZERO):
            self.out("Opening difference (the source's own figures): none")
            return
        stock_ledgers = getattr(self.source, "stock_ledger_openings", None) or ZERO
        opening_stock = getattr(self.source, "opening_stock", None) or ZERO
        ours = getattr(self, "ours_today", {}) or {}
        source_openings = getattr(self.source, "ledger_openings", {}) or {}
        ours_differ = sum(
            (source_openings[k] - lb.opening for k, lb in ours.items() if k in source_openings),
            ZERO,
        )
        tests = (
            ("the stock ledgers' openings", stock_ledgers),
            ("minus the stock ledgers' openings", -stock_ledgers),
            ("the opening stock value", opening_stock),
            ("minus the opening stock value", -opening_stock),
            ("the opening stock value minus the stock ledgers' openings",
             opening_stock - stock_ledgers),
            ("the source's openings minus ours", ours_differ),
        )  # fmt: skip
        fits = [label for label, value in tests if value and self.close(difference, value)]
        self.out(
            "Opening difference (the source's own figures): non-zero; it equals: "
            + (", ".join(fits) if fits else "none of the tested amounts")
        )

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
            parts = [f"{n:,} vouchers"]
            if standard in STOCK_TYPES or standard is None:
                parts.append(f"with inventory lines here {with_inventory.get(standard, 0):,}")
            if hints:
                parts.append(
                    f"of {sampled:,} read: "
                    + ", ".join(f"{k} {c:,}" for k, c in hints.most_common(8))
                )
            self.out(f"  {_type(standard, base)}: " + "; ".join(parts))

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
