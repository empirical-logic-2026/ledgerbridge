"""`./dev.ps1 validate currencies`: what each company's ledgers say about their own currency
(FX-001; core/fx.py). Reads the database only. Counts and ISO codes only, never names or
amounts.

Per company: the currency masters and how many give an ISO code; how the base currency was
found; the ledgers kept in another currency (by ISO code); the ledgers holding foreign amounts
and which of them are kept in the base currency; and the ledgers the source revalues (its
statements' snapshots) that aren't marked foreign, a warning.
"""

from collections import Counter
from collections.abc import Callable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from core import fx
from core.models import accounting as A  # noqa: N812
from core.problems import title

Print = Callable[[str], None]


def run(session: Session, entities: list[tuple[int, str]], out: Print = print) -> int:
    for entity_id, label in entities:
        for line in lines(session, entity_id, label):
            out(line)
    return 0


def lines(session: Session, entity_id: int, label: str) -> list[str]:
    masters = session.execute(
        select(A.CurrencySource.currency_code).where(
            A.CurrencySource.entity_id == entity_id, A.CurrencySource.is_deleted.is_(False)
        )
    ).all()
    codes = sorted({c for (c,) in masters if c})
    without = sum(1 for (c,) in masters if not c)
    base_code = session.get_one(A.Entity, entity_id).base_currency_code
    by_code = base_code in fx.currency_codes(session, entity_id).values()
    base = fx.base_currency_name(session, entity_id)
    how = "by its ISO code" if by_code else "as most ledgers' currency" if base else "not found"
    out = [
        f"{label}: {len(masters):,} currency masters ({len(masters) - without:,} with an ISO "
        f"code: {', '.join(codes) or 'none'}; {without:,} without); base currency {base_code} "
        f"found {how}"
    ]
    ledgers = session.execute(
        select(A.Ledger.id, A.Ledger.is_foreign_currency, A.Ledger.currency_code).where(
            A.Ledger.entity_id == entity_id, A.Ledger.is_deleted.is_(False)
        )
    ).all()
    foreign = {lid for lid, is_foreign, _ in ledgers if is_foreign}
    kinds = Counter(code or "no ISO code" for _, is_foreign, code in ledgers if is_foreign)
    listed = ", ".join(f"{k} {n:,}" for k, n in sorted(kinds.items())) or "none"
    out.append(
        f"  ledgers: {len(ledgers):,}; kept in another currency than the base one: "
        f"{len(foreign):,} ({listed})"
    )
    if kinds.get("no ISO code"):
        out.append(
            f"  WARNING {title('foreign_currency_without_iso_code')}: "
            f"{kinds['no ISO code']:,} ledgers"
        )
    holding = set(
        session.scalars(
            select(A.VoucherLine.ledger_id)
            .where(A.VoucherLine.entity_id == entity_id, A.VoucherLine.amount_fc.is_not(None))
            .distinct()
        )
    ) | set(
        session.scalars(
            select(A.Ledger.id).where(
                A.Ledger.entity_id == entity_id,
                or_(
                    A.Ledger.opening_balance_fc.is_not(None),
                    A.Ledger.opening_currency_name.is_not(None),
                ),
            )
        )
    )
    out.append(
        f"  ledgers holding foreign amounts: {len(holding):,} ({len(holding & foreign):,} kept "
        f"in another currency, {len(holding - foreign):,} kept in the base currency)"
    )
    latest = session.scalar(
        select(func.max(A.FxRevaluationSnapshot.as_of)).where(
            A.FxRevaluationSnapshot.entity_id == entity_id
        )
    )
    if latest is not None:
        revalued = set(
            session.scalars(
                select(A.FxRevaluationSnapshot.ledger_id).where(
                    A.FxRevaluationSnapshot.entity_id == entity_id,
                    A.FxRevaluationSnapshot.as_of == latest,
                )
            )
        )
        missing = len(revalued - foreign)
        line = (
            f"  ledgers the source revalues (as of {latest}): {len(revalued):,}, "
            f"{len(revalued & foreign):,} of them kept in another currency"
        )
        out.append(
            f"{line} [{title('revalued_ledger_not_foreign')}: {missing:,}]"
            if missing
            else f"{line} (OK)"
        )
    return out
