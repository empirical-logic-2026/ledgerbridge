"""Foreign currency beside the base-currency books (FX-001, FX-003, FX-006; ADR-037).
Source-independent.

Where it fits: the transform stores each foreign-currency line's currency, foreign amount
and rate as the source wrote them, and each ledger's currency and foreign opening
(core/transform.py). This module derives what they give:

- `refresh_voucher_rates`: one rate per currency and date from that day's foreign-currency
  lines, weighted by foreign amount (`exchange_rates`, source `vouchers`), next to the
  source's own rate lists (source `source_rate_list`, written with the currency masters);
- `refresh_ledger_currencies`: which ledgers are kept in a currency other than the base
  one (`ledgers.is_foreign_currency`) and their ISO codes. The base currency is the
  currency whose ISO code is the entity's base currency, else the one most ledgers are kept
  in (the source's company record doesn't say; pilot 2026-10-30: every ledger was marked
  INR because a company's currency masters gave no ISO code);
- `foreign_balances`: each ledger's balance in its own currency as of a date: its foreign
  opening plus the foreign amounts of its counted lines dated on or before it.

Base-currency figures are never read or changed here: they stay the books.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from core.models import accounting as A  # noqa: N812
from core.models.base import utcnow

ALIASES = "_aliases"  # a master's other names, in its extra (core/transform.py)

ZERO = Decimal(0)


def currency_codes(session: Session, entity_id: int) -> dict[str, str]:
    """Each name (and alias) the entity's source calls a currency by, with its ISO code where
    its master gives one."""
    found: dict[str, str] = {}
    for name, code, extra in session.execute(
        select(A.CurrencySource.name, A.CurrencySource.currency_code, A.CurrencySource.extra).where(
            A.CurrencySource.entity_id == entity_id, A.CurrencySource.is_deleted.is_(False)
        )
    ):
        if code:
            for n in (name, *((extra or {}).get(ALIASES) or [])):
                found[n] = code
    return found


def base_currency_name(session: Session, entity_id: int) -> str | None:
    """The name the entity's source calls its base currency by: the currency master whose
    ISO code is the entity's base currency, else the currency most of its ledgers are kept
    in; None when neither tells (no currency names at all)."""
    base = session.get_one(A.Entity, entity_id).base_currency_code
    named = next((n for n, c in currency_codes(session, entity_id).items() if c == base), None)
    if named is not None:
        return named
    return session.scalar(
        select(A.Ledger.currency_name)
        .where(A.Ledger.entity_id == entity_id, A.Ledger.currency_name.is_not(None))
        .group_by(A.Ledger.currency_name)
        .order_by(func.count().desc(), A.Ledger.currency_name)
        .limit(1)
    )


def refresh_ledger_currencies(session: Session, entity_id: int) -> int:
    """Marks the ledgers kept in another currency than the base one, and gives the others
    the base currency's code. Returns how many are foreign."""
    base_code = session.get_one(A.Entity, entity_id).base_currency_code
    base_name = base_currency_name(session, entity_id)
    names = {base_name}
    codes = currency_codes(session, entity_id)
    names |= {n for n, c in codes.items() if c == base_code}
    foreign = 0
    for ledger in session.scalars(select(A.Ledger).where(A.Ledger.entity_id == entity_id)):
        is_foreign = bool(ledger.currency_name) and ledger.currency_name not in names
        ledger.is_foreign_currency = is_foreign
        ledger.currency_code = codes.get(ledger.currency_name or "") if is_foreign else base_code
        foreign += is_foreign
    session.commit()
    return foreign


def refresh_voucher_rates(session: Session, entity_id: int) -> int:
    """Replaces the entity's voucher-derived rates: per currency and date, the base amount
    of its counted foreign-currency lines over their foreign amount (both taken as
    magnitudes), with how many lines gave it. Returns the number of rates written."""
    codes = dict(
        session.execute(
            select(A.CurrencySource.name, A.CurrencySource.currency_code).where(
                A.CurrencySource.entity_id == entity_id, A.CurrencySource.is_deleted.is_(False)
            )
        ).all()
    )
    rows = session.execute(
        select(
            A.VoucherLine.currency_name,
            A.VoucherLine.voucher_date,
            func.sum(func.abs(A.VoucherLine.amount)),
            func.sum(func.abs(A.VoucherLine.amount_fc)),
            func.count(),
        )
        .where(
            A.VoucherLine.entity_id == entity_id,
            A.VoucherLine.is_effective.is_(True),
            A.VoucherLine.currency_name.is_not(None),
            A.VoucherLine.amount_fc.is_not(None),
            A.VoucherLine.amount_fc != 0,
        )
        .group_by(A.VoucherLine.currency_name, A.VoucherLine.voucher_date)
    ).all()
    session.execute(
        delete(A.ExchangeRate).where(
            A.ExchangeRate.entity_id == entity_id, A.ExchangeRate.source == "vouchers"
        )
    )
    now = utcnow()
    for name, on, base, foreign, count in rows:
        session.add(
            A.ExchangeRate(
                entity_id=entity_id,
                currency_name=name,
                currency_code=codes.get(name),
                rate_date=on,
                rate=(Decimal(base) / Decimal(foreign)).quantize(Decimal("0.00000001")),
                rate_kind="vouchers",
                source="vouchers",
                voucher_count=count,
                created_at=now,
                updated_at=now,
            )
        )
    session.commit()
    return len(rows)


@dataclass(frozen=True)
class ForeignBalance:
    """A ledger's balance in a foreign currency as of a date (canonical sign)."""

    ledger_id: int
    currency_name: str | None
    balance_fc: Decimal


def foreign_balances(session: Session, entity_id: int, as_of: date) -> dict[int, ForeignBalance]:
    """Every ledger with a foreign opening or foreign-currency lines: its foreign opening
    plus the foreign amounts of its counted lines dated on or before `as_of` (FX-006). The
    currency is the ledger's own when it has one, else that of its lines."""
    moved = dict(
        session.execute(
            select(A.VoucherLine.ledger_id, func.sum(A.VoucherLine.amount_fc))
            .where(
                A.VoucherLine.entity_id == entity_id,
                A.VoucherLine.is_effective.is_(True),
                A.VoucherLine.amount_fc.is_not(None),
                A.VoucherLine.voucher_date <= as_of,
            )
            .group_by(A.VoucherLine.ledger_id)
        ).all()
    )
    line_currency = dict(
        session.execute(
            select(A.VoucherLine.ledger_id, func.max(A.VoucherLine.currency_name))
            .where(A.VoucherLine.entity_id == entity_id, A.VoucherLine.currency_name.is_not(None))
            .group_by(A.VoucherLine.ledger_id)
        ).all()
    )
    openings: Mapping[int, tuple[Decimal | None, str | None]] = {
        lid: (opening, name)
        for lid, opening, name in session.execute(
            select(
                A.Ledger.id,
                A.Ledger.opening_balance_fc,
                func.coalesce(A.Ledger.opening_currency_name, A.Ledger.currency_name),
            ).where(A.Ledger.entity_id == entity_id, A.Ledger.is_deleted.is_(False))
        )
    }
    found = {}
    for lid in set(moved) | {k for k, (o, _) in openings.items() if o is not None}:
        opening, name = openings.get(lid, (None, None))
        found[lid] = ForeignBalance(
            lid,
            line_currency.get(lid) or name,
            Decimal(opening or 0) + Decimal(moved.get(lid) or 0),
        )
    return found
