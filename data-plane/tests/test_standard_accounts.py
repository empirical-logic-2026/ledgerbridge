"""The default standard chart of accounts in migration 0003 is internally consistent."""

import importlib.util
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0003_seed_reference_data.py"
)


def seeded_accounts() -> list[tuple[str, str | None, str, str, str, str, str]]:
    spec = importlib.util.spec_from_file_location("seed_0003", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.STANDARD_ACCOUNTS


def test_codes_are_unique_and_parents_come_first() -> None:
    seen: dict[str, tuple] = {}
    for row in seeded_accounts():
        code, parent = row[0], row[1]
        assert code not in seen, f"duplicate code {code}"
        assert parent is None or parent in seen, f"{code}: parent {parent} must come first"
        seen[code] = row


def test_children_share_nature_and_statement_with_their_parent() -> None:
    by_code = {row[0]: row for row in seeded_accounts()}
    for code, parent, _name, nature, statement, _line, _cf in by_code.values():
        if parent:
            assert by_code[parent][3] == nature, code
            assert by_code[parent][4] == statement, code


def test_statements_match_natures() -> None:
    for code, _p, _n, nature, statement, _line, cash_flow in seeded_accounts():
        expected = "profit_loss" if nature in ("income", "expense") else "balance_sheet"
        assert statement == expected, code
        if statement == "profit_loss":
            # Profit is the starting point of the indirect cash flow method.
            assert cash_flow == "none", code


def test_cash_accounts_are_classified_as_cash() -> None:
    cash = [row for row in seeded_accounts() if row[6] == "cash"]
    assert {row[0] for row in cash} == {"1230", "1231", "1232"}


def test_suspense_and_inter_company_accounts() -> None:
    by_code = {row[0]: row for row in seeded_accounts()}
    expected = {
        # code: (parent, nature, statement_line, cash_flow_class)
        "1275": ("1200", "asset", "current_assets", "operating"),
        "3275": ("3200", "liability", "current_liabilities", "operating"),
        "3290": ("3200", "liability", "current_liabilities", "operating"),
    }
    for code, (parent, nature, line, cash_flow) in expected.items():
        _code, row_parent, _name, row_nature, _st, row_line, row_cf = by_code[code]
        assert (row_parent, row_nature, row_line, row_cf) == (parent, nature, line, cash_flow)
    assert len(by_code) == 75
