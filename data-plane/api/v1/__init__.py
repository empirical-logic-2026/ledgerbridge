"""The dashboard API, `/api/v1` (D1; ADR-049): read-only GET endpoints only, reading the
databases as report_ro, every one through the access dependency (api/access.py)."""

from fastapi import APIRouter, Depends

from api.access import current_access
from api.v1 import (
    ageing,
    cash_flow,
    companies,
    cost_centres,
    datasets,
    facets,
    home,
    monthly,
    parties,
    registers,
    reports,
    sales,
    stock,
    transactions,
)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_access)])
router.include_router(companies.router)
router.include_router(datasets.router)
router.include_router(home.router)
router.include_router(reports.router)
router.include_router(facets.router)
router.include_router(sales.router)
router.include_router(sales.purchases_router)
router.include_router(registers.router)
router.include_router(monthly.router)
router.include_router(parties.router)
router.include_router(ageing.router)
router.include_router(cash_flow.router)
router.include_router(cost_centres.router)
router.include_router(stock.router)
router.include_router(transactions.router)
