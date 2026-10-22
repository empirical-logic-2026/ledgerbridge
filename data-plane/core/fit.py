"""Fitting source values to their columns without losing them (ADR-025). Source-independent.

Where it fits: the transform (core/transform.py) passes every row through `fitter(model).fit`
before writing it.

Every row the transform writes is checked against its table's column types first, so the
database never rejects a value and one bad value can't fail a whole batch:

- a text value too long for its column, a number out of its column's range or with more
  decimals than it keeps, an invalid date, an unknown enum value or characters MySQL can't
  store: the full value is kept in the row's `extra` JSON under `_unfit` and the problem is
  reported as a warning (kind and column only, never the value). The column gets NULL
  (nullable columns), the rounded number (extra decimals), or a placeholder (required
  text). Nothing is truncated.
- a required amount, quantity or date that can't be stored fails only its own record:
  storing a substitute would silently make the books wrong.

Messages name the table, the column and the size of the problem (length, digits), never
the value itself, so they are safe outside the test environment.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, Enum, Integer, Numeric, String, Text
from sqlalchemy.dialects import mysql

UNFIT = "_unfit"
PLACEHOLDER = "(too long; kept in extra)"
TEXT_BYTES = 65_535  # MySQL TEXT
MIN_DATE = date(1000, 1, 1)  # MySQL DATE range
_SURROGATE = re.compile("[\ud800-\udfff]")
REPLACEMENT = chr(0xFFFD)  # shown instead of characters MySQL cannot store


class UnfitValueError(ValueError):
    """A required value needed for the books can't be stored: fails its own record only."""


@dataclass
class _Spec:
    name: str
    kind: str  # text / int / decimal / date / enum / skip
    nullable: bool
    length: int | None = None  # characters (VARCHAR) or bytes (TEXT)
    max_abs: Decimal | None = None
    scale: int | None = None
    choices: tuple[str, ...] = ()


@dataclass
class Fitted:
    row: dict[str, Any]
    unfit: dict[str, Any] = field(default_factory=dict)  # column -> full value (JSON-safe)
    warnings: list[str] = field(default_factory=list)


def _mysql_type(column: Any) -> Any:
    kind = column.type
    return getattr(kind, "_variant_mapping", {}).get("mysql", kind)


def _spec(column: Any) -> _Spec:
    kind = _mysql_type(column)
    name, nullable = column.name, bool(column.nullable)
    if column.foreign_keys or column.primary_key or isinstance(kind, Boolean):
        return _Spec(name, "skip", nullable)  # ids and flags are ours
    if isinstance(kind, Enum):
        return _Spec(name, "enum", nullable, choices=tuple(kind.enums))
    if isinstance(kind, mysql.LONGTEXT):
        return _Spec(name, "skip", nullable)
    if isinstance(kind, String) and not isinstance(kind, Text):
        return _Spec(name, "text", nullable, length=kind.length)
    if isinstance(kind, Text):
        return _Spec(name, "text", nullable, length=None)
    if isinstance(kind, Numeric) and not isinstance(kind, Integer):
        precision, scale = kind.precision or 20, kind.scale or 0
        return _Spec(
            name, "decimal", nullable, max_abs=Decimal(10) ** (precision - scale), scale=scale
        )
    if isinstance(kind, mysql.TINYINT):
        return _Spec(name, "int", nullable, max_abs=Decimal(128))
    if isinstance(kind, mysql.SMALLINT):
        return _Spec(name, "int", nullable, max_abs=Decimal(32_768))
    if isinstance(kind, BigInteger):
        return _Spec(name, "int", nullable, max_abs=Decimal(2) ** 63)
    if isinstance(kind, Integer):
        return _Spec(name, "int", nullable, max_abs=Decimal(2) ** 31)
    if isinstance(kind, Date):
        return _Spec(name, "date", nullable)
    return _Spec(name, "skip", nullable)


def _json_safe(value: Any) -> Any:
    """A value as JSON can hold it (numbers and dates as text)."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and _SURROGATE.search(value):
        return value.encode("utf-8", "backslashreplace").decode("utf-8")
    return value


def _digits(value: Decimal) -> int:
    """Digits before the decimal point (a size, not the value)."""
    exponent = value.adjusted()
    return max(exponent + 1, 1)


class ColumnFitter:
    """Checks rows for one table; built once per model."""

    def __init__(self, model: type) -> None:
        table = model.__table__  # type: ignore[attr-defined]
        self.table = table.name
        self.specs = {c.name: _spec(c) for c in table.columns}

    def fit(self, row: dict[str, Any]) -> Fitted:
        out = Fitted(dict(row))
        for name, value in row.items():
            spec = self.specs.get(name)
            if spec is None or value is None or spec.kind == "skip":
                continue
            problem = self._problem(spec, value)
            if problem is None:
                continue
            fixed, how = problem
            where = f"{self.table}.{name}"
            if how == "fatal":
                raise UnfitValueError(f"{fixed}: {where}")
            out.unfit[name] = _json_safe(value)
            out.row[name] = how
            out.warnings.append(f"{fixed}: {where}")
        return out

    def _problem(self, spec: _Spec, value: Any) -> tuple[str, Any] | None:
        """(description, replacement or 'fatal'), or None if the value fits."""
        if spec.kind == "text":
            return _text_problem(spec, str(value))
        if spec.kind == "enum":
            return None if str(value) in spec.choices else ("unknown value", _missing(spec))
        if spec.kind == "date":
            if not isinstance(value, date) or MIN_DATE <= value:
                return None
            return f"invalid date (year {value.year})", _missing(spec)
        if spec.kind in ("int", "decimal"):
            return _number_problem(spec, value)
        return None


def _missing(spec: _Spec) -> Any:
    """What a column gets instead of a value it can't store: NULL, or 'fatal' (the record
    fails) when the column is required."""
    return None if spec.nullable else "fatal"


def _text_problem(spec: _Spec, text: str) -> tuple[str, Any] | None:
    # Required text gets a placeholder when it can't be stored: the full value is in extra.
    missing = None if spec.nullable else PLACEHOLDER
    if _SURROGATE.search(text):
        cleaned = _SURROGATE.sub(REPLACEMENT, text)
        too_long = _too_long(spec, cleaned)  # the cleaned text must fit too
        if too_long is None:
            return f"invalid characters (length {len(text)})", cleaned
        return f"invalid characters and {too_long}", missing
    too_long = _too_long(spec, text)
    return None if too_long is None else (too_long, missing)


def _too_long(spec: _Spec, text: str) -> str | None:
    """How a text exceeds its column, or None when it fits."""
    if spec.length is not None and len(text) > spec.length:
        return f"too long (length {len(text)}, column allows {spec.length})"
    if spec.length is None and len(text.encode("utf-8")) > TEXT_BYTES:
        return f"too long ({len(text.encode('utf-8'))} bytes, column allows {TEXT_BYTES})"
    return None


def _number_problem(spec: _Spec, value: Any) -> tuple[str, Any] | None:
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return "not a number", _missing(spec)
    if not number.is_finite():
        return "not a finite number", _missing(spec)
    if spec.max_abs is None:
        return None
    if spec.kind == "int":
        if number != number.to_integral_value() or abs(number) >= spec.max_abs:
            return f"out of range ({_digits(number)} digits)", _missing(spec)
        return None
    rounded = number.quantize(Decimal(1).scaleb(-(spec.scale or 0)), ROUND_HALF_EVEN)
    if abs(rounded) >= spec.max_abs:
        kind = f"out of range ({_digits(number)} digits before the decimal point)"
        return kind, _missing(spec)
    if rounded != number:
        places = -number.as_tuple().exponent  # type: ignore[operator]
        return f"more decimals than the column keeps ({places} > {spec.scale})", rounded
    return None


def merge_extra(extra: dict[str, Any] | None, unfit: dict[str, Any]) -> dict[str, Any] | None:
    """The row's `extra`: the source's unmapped fields plus values that didn't fit."""
    merged = dict(extra or {})
    if unfit:
        merged[UNFIT] = {**merged.get(UNFIT, {}), **unfit}
    return merged or None


_FITTERS: dict[type, ColumnFitter] = {}


def fitter(model: type) -> ColumnFitter:
    if model not in _FITTERS:
        _FITTERS[model] = ColumnFitter(model)
    return _FITTERS[model]
