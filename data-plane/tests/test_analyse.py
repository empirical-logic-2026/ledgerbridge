"""`validate analyse` and the rules it pointed at (pilot 2026-10-14: closing, year-end and
stock mismatches remained after every record transformed)."""

import xml.etree.ElementTree as ET  # noqa: N817
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from connectors.base import SourceBalances
from connectors.tally import mapping
from connectors.tally.connector import TallyConnector
from connectors.tally.signs import tally_amount
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.validation import Validator
from tests.sim_tally import SimTally
from workers import cli
from workers.analyse import Analyser, fy_start
from workers.extract import get_or_create_connection
from workers.runs import ALIVE, JobLog
from workers.sync import run_sync

AS_OF = date(2027, 5, 1)  # in the next financial year: 2027-03-31 is a year end


class Source(TallyConnector):
    """A Tally connector whose own figures are set by the test."""

    balances: dict[date, dict[str, Decimal]]
    stock: dict[str, Decimal] | None = None

    def closing_balances(self, entity, as_of):  # noqa: ANN001, ANN201
        return SourceBalances(as_of, dict(self.balances[as_of]))

    def stock_quantities(self, entity, as_of):  # noqa: ANN001, ANN201
        return dict(self.stock or {})


@pytest.fixture
def synced(db: Session, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connection = get_or_create_connection(db, "tally-sim", "tally")
    connection.config = {**connection.config, "timeout_sec": 120}
    db.commit()
    transport = SimTally(per_day=1, bad_values=False)
    connector = Source.from_config(
        {"url": "http://tally.test:9000", "timeout_sec": 120}, transport=transport
    )
    run_sync(db, connection, connector, full=True, sleep=lambda s: None)
    entity_id = db.scalar(select(A.Entity.id))
    validator = Validator(db, entity_id, AS_OF, Decimal(0), connection.id)
    ours = {
        d: {lb.source_key: lb for lb in validator.ledger_balances(d)}
        for d in (AS_OF, date(2027, 3, 31))
    }
    connector.balances = {d: {k: lb.balance for k, lb in o.items()} for d, o in ours.items()}
    entity = next(e for e in connector.list_entities())
    return db, connection, connector, entity, entity_id, ours


def _analyse(synced) -> list[str]:  # noqa: ANN001
    db, connection, connector, entity, entity_id, _ = synced
    return Analyser(
        db, connection, connector, entity, entity_id, AS_OF, Decimal(0), lambda m: None
    ).run()


def _key(db: Session, name: str) -> str:
    return db.scalar(select(A.Ledger.source_key).where(A.Ledger.name == name))


def test_ledger_explanations(synced) -> None:  # noqa: ANN001
    db, _, connector, _, _, ours = synced
    today = connector.balances[AS_OF]
    cash, capital, rent = _key(db, "Cash"), _key(db, "Capital"), _key(db, "Rent")
    assert ours[AS_OF][cash].opening and ours[AS_OF][capital].opening
    # Cash: the source leaves the opening balance out; Capital: the sign is reversed;
    # Rent (an expense): the source restarts it at the start of the financial year, so
    # it holds nothing of the year before (this year has no vouchers yet).
    today[cash] -= ours[AS_OF][cash].opening
    today[capital] = -ours[AS_OF][capital].balance
    today[rent] = Decimal(0)
    connector.balances[date(2027, 3, 31)][capital] = -ours[date(2027, 3, 31)][capital].balance
    out = "\n".join(_analyse(synced))
    assert "3 ledgers differ; 3 have at least one explanation that fits" in out
    assert "the opening balance is counted twice here, or the source leaves it out: 1" in out
    assert "the sign is reversed: 1" in out
    assert "the source restarts income and expense ledgers each financial year: 1" in out
    assert "Payment vouchers counted here but not by the source: 1" in out  # Rent: all Payment
    assert "first differs at the year end 2027-03-31: 1" in out
    assert "first differs in the current financial year (every year end matches): 2" in out
    assert "2027-03-31: 1 ledgers differ" in out


def test_unexplained_ledgers_by_primary_group(synced) -> None:  # noqa: ANN001
    db, _, connector, _, _, _ = synced
    connector.balances[AS_OF][_key(db, "Cash")] += Decimal("123.45")
    out = "\n".join(_analyse(synced))
    assert "unexplained, by primary group: Current Assets 1" in out


def test_profit_carrier_and_unbalanced_patterns(synced) -> None:  # noqa: ANN001
    db, connection, connector, entity, entity_id, _ = synced
    line = db.scalar(
        select(A.VoucherLine)
        .join(A.Voucher)
        .where(A.Voucher.source_key == "sim0-20260410-0000")
        .order_by(A.VoucherLine.line_no)
        .limit(1)
    )
    line.amount += Decimal("0.5")  # rounding
    other = db.scalar(
        select(A.VoucherLine)
        .join(A.Voucher)
        .where(A.Voucher.source_key == "sim0-20260411-0000")
        .order_by(A.VoucherLine.line_no)
        .limit(1)
    )
    other.amount = -other.amount  # one line's sign reversed
    db.commit()
    out = "\n".join(_analyse(synced))
    assert "Unbalanced vouchers: 2" in out
    assert "by voucher type: Payment 2" in out
    assert "rounding (less than 1) 1" in out and "one line's sign reversed 1" in out
    assert "dates don't balance; explained by: the unbalanced vouchers" in out


def test_stock_explanations(synced) -> None:  # noqa: ANN001
    db, connection, connector, entity, entity_id, _ = synced
    widget = db.scalar(select(A.Item))
    voucher = db.scalar(select(A.Voucher).where(A.Voucher.source_key == "sim0-20260412-0000"))
    db.add(
        A.InventoryLine(
            voucher_id=voucher.id, entity_id=entity_id, voucher_date=voucher.voucher_date,
            line_no=1, item_id=widget.id, quantity=Decimal(5), amount=Decimal(0),
        )
    )  # fmt: skip
    db.commit()
    connector.stock = {widget.source_key: Decimal(widget.opening_qty)}  # the source: no movement
    out = "\n".join(_analyse(synced))
    assert "Stock quantities: 1 items differ" in out
    assert "Payment counted here but not by the source: 1" in out


def test_fy_start() -> None:
    assert fy_start(date(2027, 5, 1), 4) == date(2027, 4, 1)
    assert fy_start(date(2027, 3, 31), 4) == date(2026, 4, 1)
    assert fy_start(date(2027, 3, 31), 1) == date(2027, 1, 1)


def test_analyse_command_is_pilot_safe(synced, engine: Engine, monkeypatch, capsys) -> None:  # noqa: ANN001
    from core.config import Settings

    db, connection, connector, *_ = synced
    connector.balances[AS_OF][_key(db, "Rent")] = Decimal(0)
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "_terminate_raises_system_exit", lambda: None)
    monkeypatch.setattr(cli, "connector_for", lambda session, connection: connector)
    monkeypatch.setattr(
        cli, "get_settings", lambda: Settings(app_env="pilot", ai_provider="ollama")
    )
    code = cli.main(["validate-analyse", "--connection", "tally-sim", "--as-of", AS_OF.isoformat()])
    out = capsys.readouterr().out
    assert code == 0
    assert "entity 1 (company 1) as of 2027-05-01:" in out
    assert "Result: analyse finished" in out
    for secret in ("Rent", "Cash", "Sim Co", "Widget"):
        assert secret not in out


# --- the rules ---------------------------------------------------------------------------------


def test_foreign_currency_amounts_use_the_base_amount() -> None:
    assert tally_amount("-1000.00") == Decimal("-1000.00")
    assert tally_amount(
        "-$100.00 @ " + chr(0x20B9) + " 82.00/$ = -" + chr(0x20B9) + " 8200.00"
    ) == Decimal("-8200.00")
    assert tally_amount("$100.00 @ 82.00/$ = 8200.00") == Decimal("8200.00")
    assert tally_amount("1,00,000.50") == Decimal("100000.50")
    assert tally_amount("") is None and tally_amount("n/a") is None


def _voucher(xml: str):  # noqa: ANN202
    from connectors.base import SourceRecord

    record = SourceRecord("k", "voucher", "v1", 1, "xml", xml)
    (voucher,) = mapping.to_canonical(record)
    return voucher


def test_stock_journal_entries_are_read() -> None:
    voucher = _voucher(
        "<VOUCHER><GUID>v1</GUID><DATE>20260410</DATE>"
        "<VOUCHERTYPENAME>Stock Journal</VOUCHERTYPENAME>"
        "<INVENTORYENTRIESOUT.LIST><STOCKITEMNAME>Steel</STOCKITEMNAME>"
        "<ACTUALQTY> 10 Kg</ACTUALQTY><AMOUNT>500.00</AMOUNT>"
        "<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE></INVENTORYENTRIESOUT.LIST>"
        "<INVENTORYENTRIESIN.LIST><STOCKITEMNAME>Widget</STOCKITEMNAME>"
        "<ACTUALQTY> 4 Nos</ACTUALQTY><AMOUNT>-500.00</AMOUNT>"
        "<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE></INVENTORYENTRIESIN.LIST>"
        "</VOUCHER>"
    )
    moves = {line.item_name: line.quantity for line in voucher.inventory}
    assert moves == {"Steel": Decimal(-10), "Widget": Decimal(4)}
    assert voucher.extra is None  # nothing left unread


def test_orders_and_memorandum_dont_move_stock() -> None:
    def vt(xml: str):  # noqa: ANN202
        return mapping.voucher_type(ET.fromstring(xml), "k")  # noqa: S314

    order = vt('<VOUCHERTYPE NAME="Sales Order" RESERVEDNAME="Sales Order"/>')
    note = vt('<VOUCHERTYPE NAME="Delivery Note" RESERVEDNAME="Delivery Note"/>')
    custom = vt('<VOUCHERTYPE NAME="Web Order"><PARENT>Sales Order</PARENT></VOUCHERTYPE>')
    assert (order.moves_stock, note.moves_stock, custom.moves_stock) == (False, True, False)
    assert replace(order, moves_stock=None).moves_stock is None


def test_payload_hints_name_kinds_only() -> None:
    hints = TallyConnector.payload_hints(
        "voucher",
        "<VOUCHER><ALLLEDGERENTRIES.LIST><AMOUNT>-$1 @ 82/$ = -82</AMOUNT></ALLLEDGERENTRIES.LIST>"
        "<ALLINVENTORYENTRIES.LIST><ACTUALQTY> 1 Box = 12 Nos</ACTUALQTY>"
        "<BATCHALLOCATIONS.LIST><GODOWNNAME>A</GODOWNNAME></BATCHALLOCATIONS.LIST>"
        "<BATCHALLOCATIONS.LIST><GODOWNNAME>B</GODOWNNAME></BATCHALLOCATIONS.LIST>"
        "</ALLINVENTORYENTRIES.LIST><BILLEDQTY> 1 Box 5 Nos</BILLEDQTY>"
        "<PAYROLLENTRIES.LIST><AMOUNT>1</AMOUNT></PAYROLLENTRIES.LIST>"
        "<UDF:X.LIST><UDF:X>1</UDF:X></UDF:X.LIST>"
        "<COSTTRACKALLOCATIONS.LIST>      </COSTTRACKALLOCATIONS.LIST>"  # empty: not reported
        "<INVENTORYENTRIESIN.LIST></INVENTORYENTRIESIN.LIST></VOUCHER>",
    )
    assert hints == {
        "foreign currency amounts",
        "alternate units",
        "compound units",
        "several godowns or batches",
        "stock journal in/out entries",
        "unread list: PAYROLLENTRIES.LIST",
        "unread list: a custom (prefixed) list",
    }


# --- watching jobs that have no sync run ---------------------------------------------------------


def test_watch_keeps_following_a_busy_job(db: Session, engine: Engine, monkeypatch, capsys) -> None:  # noqa: ANN001
    connection = get_or_create_connection(db, "tally-job", "tally")
    db.commit()
    log = JobLog(engine, connection.id, "job-busy")
    log.write("explaining ...")
    polls = {"n": 0}

    def sleep(seconds: float) -> None:  # the job stays silent but alive, then finishes
        polls["n"] += 1
        if polls["n"] < 10:
            log.write(ALIVE)
        else:
            log.finish(0)

    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "_sleep", sleep)
    monkeypatch.setattr(cli, "_terminate_raises_system_exit", lambda: None)
    code = cli.main(["watch", "--connection", "tally-job", "--job", "job-busy",
                     "--poll-sec", "30", "--grace-sec", "60"])  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0 and "explaining ..." in out and ALIVE not in out
    assert db.scalar(select(S.SyncLog.id).where(S.SyncLog.line == ALIVE).limit(1))


class Monthly(Source):
    """The source's balances on any date: ours, plus a difference from a month on."""

    ours: object  # callable: date -> {source key: balance}
    shifted: dict[str, tuple[date, Decimal]]

    def closing_balances(self, entity, as_of):  # noqa: ANN001, ANN201
        if as_of in self.balances:
            return SourceBalances(as_of, dict(self.balances[as_of]))
        balances = dict(self.ours(as_of))  # type: ignore[operator]
        for key, (since, extra) in self.shifted.items():
            if as_of >= since:
                balances[key] += extra
        return SourceBalances(as_of, balances)


def test_pairs_groups_and_first_month(synced) -> None:  # noqa: ANN001
    db, connection, connector, entity, entity_id, ours = synced
    connector.__class__ = Monthly
    validator = Validator(db, entity_id, AS_OF, Decimal(0), connection.id)
    connector.ours = lambda d: {lb.source_key: lb.balance for lb in validator.ledger_balances(d)}
    cash, rent = _key(db, "Cash"), _key(db, "Rent")
    # Cash: the source leaves out its opening and one voucher type's lines (together only).
    analyser = Analyser(db, connection, connector, entity, entity_id, AS_OF, Decimal(0), print)
    analyser._prepare_lines()
    cash_id, opening = ours[AS_OF][cash].id, ours[AS_OF][cash].opening
    (kind, total), *_ = analyser.counted[cash_id].items()
    assert opening and total
    connector.balances[AS_OF][cash] -= opening + total
    # Rent differs by an amount nothing explains, from June 2026 on.
    extra = Decimal("123.45")
    connector.shifted = {rent: (date(2026, 6, 1), extra)}
    connector.balances[AS_OF][rent] += extra
    connector.balances[date(2027, 3, 31)][rent] += extra
    out = "\n".join(_analyse(synced))
    assert "2 ledgers differ; 0 have at least one explanation that fits; 1 more are" in out
    pair = sorted(
        (
            "the opening balance is counted twice here, or the source leaves it out",
            f"{kind} vouchers counted here but not by the source",
        )
    )
    assert f"{' + '.join(pair)}: 1" in out
    assert "by primary group (opening explains it / stored opening non-zero / zero):" in out
    assert "Current Assets: 0 / 1 / 0" in out  # Cash has an opening that doesn't explain it
    assert "unexplained, by primary group: Indirect Expenses 1" in out
    assert "first month end where they differ (first financial year):" in out
    assert "    2026-06: 1" in out.splitlines()
    assert "voucher types with lines in that month: Payment 1" in out
