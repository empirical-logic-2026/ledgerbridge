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


def short_error(exc: BaseException, redact: bool = False) -> str:
    """'Type: first line of the message'. Never SQL or parameters. With redact, quoted
    values are removed too (messages can name companies or ledgers)."""
    name = type(exc).__name__
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
