"""The dashboard API, `/api/v1` (D1; ADR-049): read-only GET endpoints only, reading the
databases as report_ro, every one through the access dependency (api/access.py)."""

from fastapi import APIRouter, Depends

from api.access import current_access
from api.v1 import companies, datasets, home, reports

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_access)])
router.include_router(companies.router)
router.include_router(datasets.router)
router.include_router(home.router)
router.include_router(reports.router)
