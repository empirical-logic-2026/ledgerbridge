"""Short, safe error text: never SQL statements, parameters or quoted values."""

import pymysql
from sqlalchemy.exc import IntegrityError, OperationalError, StatementError

from core.errors import redact_quoted, short_error

SQL = "INSERT INTO ledgerbridge_accounting.parties (name) VALUES (%s)"
PARAMS = ("Secret Client Pvt Ltd",)


def test_database_errors_keep_code_and_message_only() -> None:
    locked = OperationalError(SQL, PARAMS, pymysql.err.OperationalError(1205, "Lock wait"))
    assert short_error(locked) == "OperationalError: MySQL 1205: Lock wait"
    duplicate = IntegrityError(
        SQL, PARAMS, pymysql.err.IntegrityError(1062, "Duplicate entry 'Secret Client' for key")
    )
    text = short_error(duplicate)
    assert text == "IntegrityError: MySQL 1062: Duplicate entry '…' for key"
    assert "Secret" not in text and "INSERT" not in text


def test_statement_errors_drop_the_sql() -> None:
    error = StatementError("A value is required", SQL, PARAMS, None)
    text = short_error(error)
    assert text.startswith("StatementError:") and "INSERT" not in text and "Secret" not in text


def test_other_errors_first_line_and_optional_redaction() -> None:
    error = LookupError("Company 'Secret Client' not loaded\nsecond line")
    assert short_error(error) == "LookupError: Company 'Secret Client' not loaded"
    assert short_error(error, redact=True) == "LookupError: Company '…' not loaded"
    assert short_error(RuntimeError()) == "RuntimeError"
    assert redact_quoted("a \"b\" 'c'") == "a '…' '…'"
