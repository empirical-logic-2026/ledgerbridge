"""`validate compare-ledger` (workers/compare.py): one ledger's vouchers in Tally against
ours, matched by GUID, else by date, number and type; counts by voucher type and month
printed, details (dates, numbers, amounts) only in the private lines (pilot 2026-10-16)."""

from datetime import date
from decimal import Decimal

from connectors.base import SourceEntity
from connectors.tally import parser
from connectors.tally.connector import TallyConnector
from tests.conftest import FIXTURES
from tests.test_cli import run_cli  # noqa: F401 - the fixture
from workers.compare import Entry, compare, source_entries

FOREX = FIXTURES / "tally" / "rules" / "forex"


def _e(key: str, on: date, number: str, kind: str, amount: str, *kinds: str) -> Entry:
    return Entry(key, on, number, kind, Decimal(amount), set(kinds))


def test_vouchers_are_matched_and_counted_without_numbers_or_amounts() -> None:
    ours = [
        _e("g1", date(2020, 6, 1), "S-1", "Sales", "100"),
        _e("g2", date(2020, 7, 1), "S-2", "Sales", "250", "foreign-currency amounts"),
        _e("x3", date(2020, 8, 1), "J-1", "Journal", "40"),  # another key: matched by fields
        _e("g9", date(2020, 9, 1), "J-9", "Journal", "5", "optional", "not counted here"),
    ]
    theirs = [
        _e("g1", date(2020, 6, 1), "S-1", "Sales", "100"),
        _e("g2", date(2020, 7, 1), "S-2", "Sales", "200", "foreign-currency amounts"),
        _e("g3", date(2020, 8, 1), "J-1", "Journal", "40"),
        _e("g4", date(2020, 6, 2), "R-1", "Receipt", "-60"),
    ]
    result = compare(ours, theirs, Decimal(0), Decimal("-50"), date(2020, 10, 1))
    text = "\n".join(result.summary)
    assert "vouchers in the source 4, here 4" in text
    assert "matched 3 (by key 2, by date, number and type 1); equal amounts 2" in text
    assert "in the source, not here: Receipt 2020-06 1" in text
    assert "here, not in the source: Journal 2020-09 1" in text
    assert "of those here only: not counted here 1, optional 1" in text
    assert "amounts differ: Sales 2020-07 1" in text
    assert "ours higher 1, lower 0" in text
    assert "with: foreign-currency amounts 1" in text
    assert (
        "Unadjusted Forex Gain/Loss line: shown on 2020-10-01 (the report's To date), credit"
        in text
    )
    for secret in ("S-1", "S-2", "J-1", "R-1", "250", "200", "-60"):
        assert secret not in text, secret  # never numbers or amounts in the summary
    private = "\n".join(result.private)
    assert "differs\t2020-07-01\tS-2\tSales\t250\t200\tkey" in private
    assert "source only\t2020-06-02\tR-1\tReceipt\t\t-60" in private


def test_the_source_vouchers_come_from_tallys_ledger_voucher_collection() -> None:
    """Recorded from the test company: Customer Beta Retail's May 2026 vouchers as Tally
    lists them (Child Of the ledger)."""
    body = (FOREX / "ledger_vouchers_2026-05.xml").read_bytes()

    class Recorded(TallyConnector):
        def ledger_vouchers(self, entity, ledger, start, end):  # noqa: ANN001, ANN201
            return parser.objects(parser.parse_response(body), "VOUCHER")

    connector = Recorded.from_config({"url": "http://tally.test:9000"})
    entity = SourceEntity("k", "LedgerBridge Test Co")
    (entry,) = source_entries(
        connector, entity, ["Customer Beta Retail"], date(2026, 5, 1), date(2026, 5, 31), set()
    )
    assert (entry.on, entry.voucher_type) == (date(2026, 5, 1), "Sales")
    assert entry.amount > 0 and "bill allocations" in entry.kinds


def test_details_are_printed_only_with_private(db, run_cli, monkeypatch) -> None:  # noqa: ANN001, F811
    """The CLI prints counts; the details only as PRIVATE lines with --private, which
    dev.ps1 writes to reports/<env>/private/ and never shows."""
    from sqlalchemy import select

    from core.models import accounting as A  # noqa: N812
    from tests.conftest import COMPANY
    from workers import cli

    run_cli("connect", "--connection", "tally-pilot", "--source", "tally",
            "--origin", "backup", "--entity", COMPANY, "--pause")  # fmt: skip
    run_cli("sync", "--connection", "tally-pilot", "--full")
    ledger = db.scalar(select(A.Ledger.id).where(A.Ledger.name == "Customer Beta Retail"))
    monkeypatch.setattr(
        cli, "compare_ledger",
        lambda *a, **k: compare([], [], Decimal(0), None, date(2026, 10, 2)),
    )  # fmt: skip
    code, out = run_cli("compare-ledger", "--connection", "tally-pilot", "--ledger", str(ledger))
    assert code == 0, out
    assert "PRIVATE" not in out and "Result: compare finished" in out
    code, out = run_cli("compare-ledger", "--connection", "tally-pilot", "--ledger", str(ledger),
                        "--private")  # fmt: skip
    assert code == 0 and "PRIVATE\tstatus\tdate" in out
