"""Short, safe error descriptions for logs, CLI output and stored error summaries.

SQLAlchemy errors print the SQL statement and its parameters, which can hold names and
amounts from the books. `short_error` keeps the exception type and the first line of its
message only: for database errors, the driver's error code and message, with quoted values
removed (MySQL quotes the offending value, e.g. "Duplicate entry '...' for key ...").
"""

import re

from sqlalchemy.exc import DBAPIError, SQLAlchemyError

# A quoted value, not an apostrophe inside a word ("didn't ... isn't" is not a quote).
_QUOTED = re.compile(r"(?<![A-Za-z])'[^']*'(?![A-Za-z])|\"[^\"]*\"")
MAX_LENGTH = 300


def redact_quoted(text: str) -> str:
    """Replaces every quoted value ('...' or "...") with '…'."""
    return _QUOTED.sub("'…'", text)


# MySQL data errors: code -> kind of problem (ADR-025).
DATA_ERRORS = {
    1048: "missing value",
    1264: "out of range",
    1265: "doesn't fit (truncated)",
    1292: "invalid date or value",
    1366: "invalid characters or value",
    1406: "too long",
    1452: "refers to a missing row",
}
_COLUMN = re.compile(r"column '([^']+)'|Column '([^']+)'")
_TABLE = re.compile(r"(?:INSERT INTO|UPDATE|DELETE FROM)\s+(?:`?\w+`?\.)?`?(\w+)`?", re.IGNORECASE)


def describe_data_error(exc: DBAPIError) -> str | None:
    """'MySQL 1406 too long: vouchers.voucher_number (values up to 300 characters)' for the
    data errors above: code, kind, table, column and a size, never the value; None for other
    errors."""
    args = getattr(exc.orig, "args", ())
    if len(args) < 2 or args[0] not in DATA_ERRORS:
        return None
    code, message = args[0], str(args[1])
    match = _COLUMN.search(message)
    column = (match.group(1) or match.group(2)) if match else None
    table_match = _TABLE.search(str(exc.statement or ""))
    table = table_match.group(1) if table_match else None
    where = ".".join(part for part in (table, column) if part) or "unknown column"
    size = _size(exc.params, column) if column else None
    return f"MySQL {code} {DATA_ERRORS[code]}: {where}" + (f" ({size})" if size else "")


def _size(params: object, column: str) -> str | None:
    rows = params if isinstance(params, list | tuple) else [params]
    values = [row[column] for row in rows if isinstance(row, dict) and row.get(column) is not None]
    if not values:
        return None
    if all(isinstance(v, str) for v in values):
        return f"values up to {max(len(v) for v in values)} characters"
    digits = []
    for value in values:
        text = str(value).lstrip("-").split(".")[0]
        if text.isdigit():
            digits.append(len(text.lstrip("0")) or 1)
    return f"values up to {max(digits)} digits before the decimal point" if digits else None


def short_error(exc: BaseException, redact: bool = False) -> str:
    """'Type: first line of the message'. Never SQL or parameters. With redact, quoted
    values are removed too (messages can name companies or ledgers). MySQL data errors are
    described by kind, table, column and size (describe_data_error)."""
    name = type(exc).__name__
    if (
        isinstance(exc, DBAPIError)
        and exc.orig is not None
        and (described := describe_data_error(exc))
    ):
        return f"{name}: {described}"[:MAX_LENGTH]
    if isinstance(exc, DBAPIError) and exc.orig is not None:
        args = getattr(exc.orig, "args", ())
        if len(args) >= 2 and isinstance(args[0], int):
            message = f"MySQL {args[0]}: {args[1]}"
        else:
            message = str(exc.orig)
        message = redact_quoted(message.splitlines()[0] if message else "")
    elif isinstance(exc, SQLAlchemyError):
        head = str(exc).split("[SQL:", 1)[0].strip()
        message = redact_quoted(head.splitlines()[0]) if head else ""
    else:
        lines = str(exc).splitlines()
        message = lines[0] if lines else ""
        if redact:
            message = redact_quoted(message)
    return f"{name}: {message}"[:MAX_LENGTH] if message else name
