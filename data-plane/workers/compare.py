"""`validate compare-ledger`: one ledger's vouchers in the source against ours, voucher by
voucher (source-independent here; the connector lists the source's vouchers).

The source's list is read with a read-only request per month (Tally: its ledger-voucher
collection). Vouchers are matched by the source's key (Tally's GUID), else by date, number
and voucher type. Printed output holds counts by voucher type and month, and kinds only:
never names, voucher numbers or amounts. The full details (dates, numbers, both amounts)
are returned separately as private lines, which the caller writes to a local file for the
developer only (dev.ps1: reports/<env>/private/); they are never printed or logged.
"""

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.base import Connector, SourceEntity, SourceRecord
from core.models import accounting as A  # noqa: N812
from core.names import normalise

ZERO = Decimal(0)
ROUND_OFF = re.compile(r"round", re.IGNORECASE)  # a ledger kind, never printed by name


@dataclass
class Entry:
    """One voucher's lines on the ledger, with what the comparison reports about it."""

    key: str
    on: date
    number: str
    voucher_type: str
    amount: Decimal
    kinds: set[str] = field(default_factory=set)


@dataclass
class Comparison:
    summary: list[str]
    private: list[str]  # full details: for the local private file only


def _month(on: date) -> str:
    return f"{on:%Y-%m}"


def source_entries(
    connector: Connector,
    entity: SourceEntity,
    ledger_names: Sequence[str],
    start: date,
    end: date,
    expense_ledgers: set[str],
) -> list[Entry]:
    """The source's vouchers of the ledger, each with its total on the ledger."""
    wanted = {normalise(n) for n in ledger_names}
    out = []
    for element in connector.ledger_vouchers(entity, ledger_names[0], start, end):  # type: ignore[attr-defined]
        record = SourceRecord(entity.key, "voucher", _guid(element), None, "xml", _xml(element))
        mapped = next((m for m in connector.to_canonical(record) if hasattr(m, "lines")), None)
        if mapped is None:
            continue
        mine = [line for line in mapped.lines if normalise(line.ledger_name) in wanted]
        others = [line for line in mapped.lines if normalise(line.ledger_name) not in wanted]
        entry = Entry(
            record.source_key,
            mapped.voucher_date,
            mapped.voucher_number,
            mapped.voucher_type_name,
            sum((line.amount for line in mine), ZERO),
        )
        if any(line.amount_fc for line in mapped.lines):
            entry.kinds.add("foreign-currency amounts")
        if any(line.bills for line in mine):
            entry.kinds.add("bill allocations")
        if any(ROUND_OFF.search(line.ledger_name) for line in others):
            entry.kinds.add("a line on a round-off ledger")
        if any(normalise(line.ledger_name) in expense_ledgers for line in others):
            entry.kinds.add("a line on an expense ledger")
        if mapped.is_optional:
            entry.kinds.add("optional")
        if mapped.is_cancelled:
            entry.kinds.add("cancelled")
        out.append(entry)
    return out


def our_entries(session: Session, ledger_id: int, start: date, end: date) -> list[Entry]:
    """Our vouchers with lines on the ledger dated start..end, their lines on it totalled."""
    L, V, T = A.VoucherLine, A.Voucher, A.VoucherType  # noqa: N806
    entries: dict[int, Entry] = {}
    for vid, key, on, number, kind, amount, fc, optional, cancelled, deleted, effective, rate in (
        session.execute(
            select(
                V.id, V.source_key, V.voucher_date, V.voucher_number, T.name, L.amount,
                L.amount_fc, V.is_optional, V.is_cancelled, V.is_deleted, L.is_effective,
                V.exchange_rate,
            )
            .join(L, L.voucher_id == V.id)
            .join(T, T.id == V.voucher_type_id)
            .where(L.ledger_id == ledger_id, V.voucher_date >= start, V.voucher_date <= end)
        )
    ):  # fmt: skip
        entry = entries.setdefault(vid, Entry(key, on, number, kind, ZERO))
        entry.amount += Decimal(amount)
        if fc is not None:
            entry.kinds.add("foreign-currency amounts")
        if rate is not None and Decimal(rate) != 1:
            entry.kinds.add("an exchange rate")
        for flag, label in ((optional, "optional"), (cancelled, "cancelled"),
                            (deleted, "deleted"), (not effective, "not counted here")):  # fmt: skip
            if flag:
                entry.kinds.add(label)
    if entries:
        with_bills = set(
            session.scalars(
                select(L.voucher_id)
                .join(A.BillAllocation, A.BillAllocation.voucher_line_id == L.id)
                .where(L.ledger_id == ledger_id, L.voucher_id.in_(list(entries)))
            )
        )
        for vid in with_bills:
            entries[vid].kinds.add("bill allocations")
        other_lines = session.execute(
            select(L.voucher_id, A.Ledger.name, A.AccountGroup.nature)
            .join(A.Ledger, A.Ledger.id == L.ledger_id)
            .join(A.AccountGroup, A.AccountGroup.id == A.Ledger.group_id)
            .where(L.voucher_id.in_(list(entries)), L.ledger_id != ledger_id)
        )
        for vid, name, nature in other_lines:
            if ROUND_OFF.search(name or ""):
                entries[vid].kinds.add("a line on a round-off ledger")
            if nature == "expense":
                entries[vid].kinds.add("a line on an expense ledger")
    return list(entries.values())


def compare(
    ours: list[Entry],
    theirs: list[Entry],
    tolerance: Decimal,
    calculated: Decimal | None,
    end: date,
) -> Comparison:
    """Match by key, else by (date, number, voucher type); count by voucher type and month."""
    by_key = {e.key: e for e in ours}
    by_fields: dict[tuple[date, str, str], list[Entry]] = {}
    for e in ours:
        by_fields.setdefault((e.on, e.number, e.voucher_type), []).append(e)
    matched: list[tuple[Entry, Entry, str]] = []
    only_theirs: list[Entry] = []
    used: set[str] = set()
    for t in theirs:
        mine = by_key.get(t.key)
        how = "key"
        if mine is None or mine.key in used:
            candidates = [
                e for e in by_fields.get((t.on, t.number, t.voucher_type), []) if e.key not in used
            ]
            mine, how = (candidates[0], "date, number and type") if candidates else (None, "")
        if mine is None:
            only_theirs.append(t)
            continue
        used.add(mine.key)
        matched.append((mine, t, how))
    only_ours = [e for e in ours if e.key not in used]
    exact = [(m, t, h) for m, t, h in matched if abs(m.amount - t.amount) <= tolerance]
    differ = [(m, t, h) for m, t, h in matched if abs(m.amount - t.amount) > tolerance]

    def by_type_month(entries: list[Entry]) -> str:
        counts = Counter(f"{e.voucher_type} {_month(e.on)}" for e in entries)
        return ", ".join(f"{k} {n:,}" for k, n in sorted(counts.items())) or "none"

    summary = [
        f"vouchers in the source {len(theirs):,}, here {len(ours):,}",
        f"matched {len(matched):,} (by key {sum(1 for *_, h in matched if h == 'key'):,}, "
        f"by date, number and type {sum(1 for *_, h in matched if h != 'key'):,}); "
        f"equal amounts {len(exact):,}",
        f"in the source, not here: {by_type_month(only_theirs)}",
        f"here, not in the source: {by_type_month(only_ours)}",
    ]
    kinds_only_ours = Counter(k for e in only_ours for k in e.kinds)
    if kinds_only_ours:
        summary.append(
            "  of those here only: "
            + ", ".join(f"{k} {n:,}" for k, n in sorted(kinds_only_ours.items()))
        )
    summary.append(f"amounts differ: {by_type_month([m for m, _, _ in differ])}")
    if differ:
        higher = sum(1 for m, t, _ in differ if m.amount > t.amount)
        summary.append(f"  ours higher {higher:,}, lower {len(differ) - higher:,}")
        kinds = Counter(k for m, t, _ in differ for k in m.kinds | t.kinds)
        summary.append(
            "  with: "
            + (
                ", ".join(f"{k} {n:,}" for k, n in sorted(kinds.items()))
                or "none of the tested kinds"
            )
        )
    if calculated is None:
        summary.append("the source's calculated Unadjusted Forex Gain/Loss line: not shown")
    else:
        side = "debit" if calculated > 0 else "credit" if calculated < 0 else "zero"
        summary.append(
            f"the source's calculated Unadjusted Forex Gain/Loss line: shown on {end} (the "
            f"report's To date), {side}; not a voucher, left out of the comparison"
        )
    total_ours = sum((e.amount for e in ours if "not counted here" not in e.kinds), ZERO)
    total_theirs = sum((e.amount for e in theirs), ZERO)
    summary.append(
        "vouchers' total on the ledger: "
        + ("equal" if abs(total_ours - total_theirs) <= tolerance else
           ("ours higher" if total_ours > total_theirs else "ours lower"))
    )  # fmt: skip
    private = ["status\tdate\tvoucher number\tvoucher type\tours\tsource\tmatched by\tkinds"]

    def row(*cells: object) -> str:
        return "\t".join("" if c is None else str(c) for c in cells)

    for m, t, how in sorted(matched, key=lambda x: x[1].on):
        status = "equal" if abs(m.amount - t.amount) <= tolerance else "differs"
        kinds = ", ".join(sorted(m.kinds | t.kinds))
        private.append(row(status, t.on, t.number, t.voucher_type, m.amount, t.amount, how, kinds))
    for t in sorted(only_theirs, key=lambda e: e.on):
        kinds = ", ".join(sorted(t.kinds))
        private.append(
            row("source only", t.on, t.number, t.voucher_type, None, t.amount, None, kinds)
        )
    for m in sorted(only_ours, key=lambda e: e.on):
        kinds = ", ".join(sorted(m.kinds))
        private.append(
            row("ours only", m.on, m.number, m.voucher_type, m.amount, None, None, kinds)
        )
    if calculated is not None:
        private.append(f"calculated line\t{end}\tUnadjusted Forex Gain/Loss\t\t\t{calculated}\t\t")
    private.append(f"total\t\t\t\t{total_ours}\t{total_theirs}\t\t")
    return Comparison(summary, private)


def _guid(element: Any) -> str:
    return (element.findtext("GUID") or "").strip()


def _xml(element: Any) -> str:
    import xml.etree.ElementTree as ET  # noqa: N817

    return ET.tostring(element, encoding="unicode")  # as stored: the voucher element


def compare_ledger(
    session: Session,
    connector: Connector,
    entity: SourceEntity,
    entity_id: int,
    ledger_id: int,
    start: date,
    end: date,
    tolerance: Decimal,
    progress: Callable[[str], None],
) -> Comparison:
    ledger = session.get_one(A.Ledger, ledger_id)
    if ledger.entity_id != entity_id:
        raise LookupError(f"ledger {ledger_id} isn't in this company")
    names = [ledger.name, *((ledger.extra or {}).get("_aliases") or [])]
    expense = {
        normalise(name)
        for (name,) in session.execute(
            select(A.Ledger.name)
            .join(A.AccountGroup, A.AccountGroup.id == A.Ledger.group_id)
            .where(A.Ledger.entity_id == entity_id, A.AccountGroup.nature == "expense")
        )
    }
    progress(f"reading the source's vouchers of ledger {ledger_id}, {start} to {end}")
    theirs = source_entries(connector, entity, names, start, end, expense)
    ours = our_entries(session, ledger_id, start, end)
    calculated = None
    read = getattr(connector, "unadjusted_forex", None)
    if read is not None:
        progress("reading the source's Ledger Vouchers report for its calculated lines")
        calculated = read(entity, ledger.name, (start, end))
    result = compare(ours, theirs, tolerance, calculated, end)
    opening = Decimal(ledger.opening_balance or 0)
    result.summary.insert(
        0, f"ledger {ledger_id}: opening " + ("zero" if not opening else "non-zero")
        + f"; compared {start} to {end}"
    )  # fmt: skip
    return result
