"""`GET /api/v1/facets/{kind}`: the choices of the top filter bar's facets (docs/design/
dashboard.md Section 0.2) for the selected companies: customers, channels (the voucher types
of sales), ledger groups and voucher types.

Values are names, so that the same customer or voucher type in several companies is one
choice; the pages that apply a facet filter by these names. At most 200 values, the first by
name, narrowed with `search` (part of the name, any case).
"""

from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from api.access import CurrentAccess
from api.v1.common import ReportSession
from core.models import accounting as A  # noqa: N812

router = APIRouter(prefix="/facets", tags=["facets"])
LIMIT = 200
Kind = Literal["customer", "channel", "ledger_group", "voucher_type"]


class FacetValue(BaseModel):
    value: str  # the name: what the pages filter by
    companies: int  # in how many of the selected companies it exists


def _name_query(kind: Kind) -> tuple[Any, Any, list[Any]]:
    """(name column, company column, conditions) of a facet's masters."""
    if kind == "customer":
        return A.Party.name, A.Party.entity_id, [
            A.Party.party_type.in_(("customer", "both")), A.Party.is_deleted.is_(False),
        ]  # fmt: skip
    if kind == "channel":
        return A.VoucherType.name, A.VoucherType.entity_id, [
            A.VoucherType.base_type == "sales", A.VoucherType.is_deleted.is_(False),
        ]  # fmt: skip
    if kind == "ledger_group":
        return A.AccountGroup.name, A.AccountGroup.entity_id, [A.AccountGroup.is_deleted.is_(False)]
    return A.VoucherType.name, A.VoucherType.entity_id, [A.VoucherType.is_deleted.is_(False)]


@router.get("/{kind}")
def facet_values(
    kind: Kind,
    session: ReportSession,
    access: CurrentAccess,
    company: list[int] | None = Query(default=None),  # noqa: B008
    search: str | None = Query(default=None, max_length=100),
) -> list[FacetValue]:
    companies = access.entities(company)
    name, entity, conditions = _name_query(kind)
    query = (
        select(name, func.count(func.distinct(entity)))
        .where(entity.in_(companies), *conditions)
        .group_by(name)
        .order_by(name)
        .limit(LIMIT)
    )
    if search:
        query = query.where(func.lower(name).contains(search.lower(), autoescape=True))
    return [FacetValue(value=v, companies=n) for v, n in session.execute(query)]
