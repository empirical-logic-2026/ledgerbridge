"""Centralizes optional dashboard display labels without changing stored entity names."""

from typing import Any

from sqlalchemy import case
from sqlalchemy.sql import ColumnElement

from core.config import get_settings


def display_company_name(name: str) -> str:
    """Return the configured dashboard label, or the unchanged entity name."""
    return get_settings().company_display_names.get(name, name)


def display_company_name_expression(name: ColumnElement[Any]) -> ColumnElement[Any]:
    """Apply the same exact-name mapping to API query labels, using bound SQL values."""
    mapping = get_settings().company_display_names
    if not mapping:
        return name
    return case(mapping, value=name, else_=name)
