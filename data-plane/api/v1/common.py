"""What every `/api/v1` module shares: the read-only session (report_ro, ADR-049)."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from api.deps import get_report_session

ReportSession = Annotated[Session, Depends(get_report_session)]
