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
from core.models.source import RawRecord
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


def test_stock_by_godown_and_job_work(synced, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    """Items that differ are compared godown by godown with the source's own movement
    (closing minus opening); job work lines are counted by kind of godown."""
    db, connection, connector, entity, entity_id, _ = synced
    widget = db.scalar(select(A.Item))
    worker = A.Godown(
        entity_id=entity_id, connection_id=connection.id, source_key="gd-job-worker",
        origin="live", name="Job Worker", holding="ours_with_third_party",
    )  # fmt: skip
    db.add(worker)
    db.flush()
    voucher = db.scalar(select(A.Voucher).where(A.Voucher.source_key == "sim0-20260412-0000"))
    db.add(
        A.InventoryLine(
            voucher_id=voucher.id, entity_id=entity_id, voucher_date=voucher.voucher_date,
            line_no=1, item_id=widget.id, quantity=Decimal(5), amount=Decimal(0),
            godown_id=worker.id,
        )
    )  # fmt: skip
    db.add(
        A.InventoryLine(
            voucher_id=voucher.id, entity_id=entity_id, voucher_date=voucher.voucher_date,
            line_no=2, item_id=widget.id, quantity=Decimal(3), amount=Decimal(0),
        )
    )  # fmt: skip
    db.commit()
    connector.stock = {widget.source_key: Decimal(widget.opening_qty)}  # the source: no change
    # The source moved 5 at the job worker's godown, nothing elsewhere.
    monkeypatch.setattr(
        connector,
        "stock_by_godown",
        lambda entity, as_of, items: {(widget.name, "Job Worker"): (Decimal(0), Decimal(5))},
        raising=False,
    )
    out = "\n".join(_analyse(synced))
    assert "Stock quantities: 1 items differ" in out  # the 3 at no godown
    assert "by godown (1 of 1 differing items checked): (item, godown) movements that" in out
    assert "differ: own godown 1" in out
    assert "Job work:" in out
    assert "inventory lines at a job worker's godown: 1 (not in the source's stock" in out


class WithOpenings(Source):
    """The source also reports each ledger's opening at the books' beginning."""

    openings: dict[str, Decimal]

    def closing_balances(self, entity, as_of):  # noqa: ANN001, ANN201
        return SourceBalances(
            as_of, dict(self.balances[as_of]), ledger_openings=dict(self.openings)
        )


def test_ledger_profiles(synced) -> None:  # noqa: ANN001
    """Pilot 2026-10-15: two ledgers differed only by their opening; the profile says where
    they sit, what they are, whether the source's opening equals ours, when they differ
    and what the difference equals (anonymous: ledger A, B, ...)."""
    db, _, connector, _, _, ours = synced
    connector.__class__ = WithOpenings
    cash = _key(db, "Cash")
    opening = ours[AS_OF][cash].opening
    connector.openings = {cash: Decimal(0)}  # the source has no opening for it
    for when in (AS_OF, date(2027, 3, 31)):
        connector.balances[when][cash] -= opening
    out = "\n".join(_analyse(synced))
    assert "Ledger profiles (ledgers that differ today or at a year end: 1):" in out
    line = next(x for x in out.splitlines() if x.startswith("  ledger A: "))
    assert "primary group Current Assets" in line
    assert "kind cash" in line and "nature asset" in line
    assert "stored opening debit, different from the source's" in line
    assert "posted by: Payment" in line
    assert "differs today and at 1 of 1 year ends (first 2027-03-31, last 2027-03-31)" in line
    assert ", by the same amount" in line
    assert "minus its stored opening" in line and "the source's opening minus ours" in line
    assert "Cash" not in line  # anonymous


class Probing(Source):
    """The source's balances with set stock values, opening difference and first day."""

    stock_values: dict[date, Decimal]
    difference: Decimal | None
    stock_ledgers: Decimal

    def closing_balances(self, entity, as_of):  # noqa: ANN001, ANN201
        balances = self.balances.get(as_of)
        if balances is None:  # another date (e.g. the books' first day)
            balances = self.between(as_of)
        return SourceBalances(
            as_of,
            dict(balances),
            closing_stock=self.stock_values.get(as_of),
            opening_stock=Decimal(0),
            opening_difference=self.difference,
            stock_ledger_openings=self.stock_ledgers,
        )


def test_profile_probes_and_opening_difference(synced) -> None:  # noqa: ANN001
    """Pilot 2026-10-15 hypotheses: a stock ledger the source reports at the closing stock
    value; a ledger differing at one year end by one month's lines; the source's opening
    difference equal to its stock ledgers' openings."""
    db, connection, connector, entity, entity_id, ours = synced
    connector.__class__ = Probing
    year_end = date(2027, 3, 31)
    validator = Validator(db, entity_id, AS_OF, Decimal(0), connection.id)
    row = db.get_one(A.Entity, entity_id)
    row.books_from = row.books_from or date(2026, 4, 1)
    db.commit()
    cash, capital = _key(db, "Cash"), _key(db, "Capital")
    # Capital: the source reports it at the stock's value at each date (2,000 and 2,500).
    connector.stock_values = {year_end: Decimal(2000), AS_OF: Decimal(2500)}
    for when, value in connector.stock_values.items():
        connector.balances[when][capital] = value
    # Cash: differs at the year end only, by its Payment lines in March 2027 (one voucher
    # moved there: balances at the year end and today are unchanged by the move).
    moved = db.scalar(
        select(A.Voucher)
        .join(A.VoucherLine, A.VoucherLine.voucher_id == A.Voucher.id)
        .where(A.VoucherLine.ledger_id == ours[AS_OF][cash].id)
        .limit(1)
    )
    moved.voucher_date = date(2027, 3, 15)
    for line in db.scalars(select(A.VoucherLine).where(A.VoucherLine.voucher_id == moved.id)):
        line.voucher_date = moved.voucher_date
    db.commit()
    march = sum(
        db.scalars(
            select(A.VoucherLine.amount).where(
                A.VoucherLine.ledger_id == ours[AS_OF][cash].id,
                A.VoucherLine.voucher_date > date(2027, 2, 28),
                A.VoucherLine.voucher_date <= year_end,
            )
        ),
        Decimal(0),
    )
    assert march
    connector.balances[year_end][cash] -= march

    # Other dates: the source agrees with us, except that it counts Cash's March 2027 lines
    # only from the year end (so Cash starts to differ in March and matches again after).
    def between(on: date) -> dict[str, Decimal]:
        found = {lb.source_key: lb.balance for lb in validator.ledger_balances(on)}
        if date(2027, 2, 28) < on < year_end:
            found[cash] -= sum(
                db.scalars(
                    select(A.VoucherLine.amount).where(
                        A.VoucherLine.ledger_id == ours[AS_OF][cash].id,
                        A.VoucherLine.voucher_date > date(2027, 2, 28),
                        A.VoucherLine.voucher_date <= on,
                    )
                ),
                Decimal(0),
            )
        return found

    connector.between = between
    connector.difference = connector.stock_ledgers = Decimal(1234)
    out = "\n".join(_analyse(synced))
    lines = {x.split(":")[0].strip(): x for x in out.splitlines() if x.startswith("  ledger ")}
    stock_like = next(x for x in lines.values() if "the closing stock value minus" in x)
    assert "the closing stock value minus its stored opening (at every date)" in stock_like
    assert "by changing amounts" in stock_like
    one_year = next(x for x in lines.values() if "at 1 of 1 year ends" in x and "today" not in x)
    assert "Payment lines in the month up to 2027-03-31" in one_year
    assert "matches on the books' first day" in one_year
    # Narrowed to the day the moved voucher is dated, and to the day after the year end.
    assert "first differs between 2027-03-14 and 2027-03-15 (vouchers posting to it then 1: " \
        "regular 1; Payment 1;" in one_year  # fmt: skip
    assert "matches again between 2027-03-31 and 2027-04-01 (no vouchers" in one_year
    assert "one voucher's line on it (Payment, regular) (first differs window)" in one_year
    assert (
        "Opening difference (the source's own trial balance from the books' beginning): "
        "non-zero; it equals: the stock ledgers' openings" in out
    )


def test_special_vouchers_are_counted(synced) -> None:  # noqa: ANN001
    db, connection, connector, entity, entity_id, ours = synced
    cash = ours[AS_OF][_key(db, "Cash")]
    voucher = db.scalar(
        select(A.Voucher)
        .join(A.VoucherLine, A.VoucherLine.voucher_id == A.Voucher.id)
        .where(A.VoucherLine.ledger_id == cash.id)
        .limit(1)
    )
    voucher.is_optional = True
    db.commit()
    analyser = Analyser(db, connection, connector, entity, entity_id, AS_OF, Decimal(0), print)
    assert analyser._special_vouchers(cash.id) == {"optional": 1}


def test_differences_that_cancel_out_are_paired(synced) -> None:  # noqa: ANN001
    """Pilot 2026-10-16: two customers differed by opposite amounts (one amount posted to
    the wrong one of them?)."""
    db, _, connector, _, _, _ = synced
    cash, bank = _key(db, "Cash"), _key(db, "Test Bank Current A/c")
    for when in (AS_OF, date(2027, 3, 31)):
        connector.balances[when][cash] += Decimal("250")
        connector.balances[when][bank] -= Decimal("250")
    out = "\n".join(_analyse(synced))
    assert (
        "pairs of ledgers whose differences cancel out (one amount on the other ledger?): 1" in out
    )
    lines = [x for x in out.splitlines() if x.startswith("  ledger ")]
    assert any("the opposite of ledger B's difference" in x for x in lines)
    assert any("the opposite of ledger A's difference" in x for x in lines)
    assert all("stored vouchers naming it" in x for x in lines)


def test_lines_equal_to_the_difference_and_how_their_names_matched(synced) -> None:  # noqa: ANN001
    """For a ledger that starts to differ, the lines of any voucher in that window equal to
    the difference: which ledger we posted each to, and how its name was matched."""
    test_profile_probes_and_opening_difference(synced)
    db, connection, connector, entity, entity_id, _ = synced
    out = "\n".join(_analyse(synced))
    one_year = next(x for x in out.splitlines() if x.startswith("  ledger ") and "kind cash" in x)
    assert "lines of any voucher then equal to the difference: " in one_year
    assert "this ledger, name matched exact 1" in one_year


def test_stock_ledgers_at_the_stock_value_count_as_explained(synced) -> None:  # noqa: ANN001
    """As validation does (LB-VAL-021): a stock ledger the source reports at its closing
    stock value isn't a ledger that differs."""
    db, _, connector, _, _, ours = synced
    cash = _key(db, "Cash")
    connector.__class__ = StockValued
    connector.stock_keys = frozenset({cash})
    for when in (AS_OF, date(2027, 3, 31)):
        connector.balances[when][cash] = Decimal("4321")
    out = "\n".join(_analyse(synced))
    assert "0 ledgers differ" in out
    assert "stock ledgers at the source's closing stock value (compared with it, as " \
        "validation does; LB-VAL-021): 1" in out  # fmt: skip
    assert "2027-03-31: 0 ledgers differ" in out


class StockValued(Source):
    stock_keys: frozenset[str]

    def closing_balances(self, entity, as_of):  # noqa: ANN001, ANN201
        return SourceBalances(
            as_of,
            dict(self.balances[as_of]),
            closing_stock=Decimal("4321"),
            opening_stock=Decimal("4321"),
            stock_ledgers=self.stock_keys,
            integrated=True,
        )


class GroupOpenings(Source):
    groups: dict[str, Decimal]

    def closing_balances(self, entity, as_of):  # noqa: ANN001, ANN201
        return SourceBalances(
            as_of,
            dict(self.balances[as_of]),
            opening_difference=sum(self.groups.values(), Decimal(0)),
            group_openings=self.groups,
            reserved_groups=frozenset(self.groups),
            ledger_openings={k: lb.opening for k, lb in self.ours.items()},
            integrated=False,
            stock_ledger_openings=Decimal(0),
        )


def test_the_opening_difference_by_primary_group(synced) -> None:  # noqa: ANN001
    """Which primary group's own opening differs from its ledgers' openings, and whether
    the difference is one group's openings."""
    db, connection, connector, entity, entity_id, ours = synced
    connector.__class__ = GroupOpenings
    connector.ours = ours[AS_OF]
    totals: dict[str, Decimal] = {}
    primary = Analyser(
        db, connection, connector, entity, entity_id, AS_OF, Decimal(0), print
    )._primary_groups()
    for lb in ours[AS_OF].values():
        group = primary[lb.id]
        totals[group] = totals.get(group, Decimal(0)) + lb.opening
    totals["Current Assets"] += Decimal("77")  # the source's own figure differs by 77
    connector.groups = totals
    out = "\n".join(_analyse(synced))
    assert "Opening difference (the source's own trial balance from the books' beginning): " \
        "non-zero" in out  # fmt: skip
    assert "primary groups whose own opening differs from their ledgers' openings: " \
        "Current Assets (the gap equals:" in out  # fmt: skip
    assert "accounts not integrated with inventory" in out


def test_ledger_lines_outside_the_lists_read_are_counted(synced) -> None:  # noqa: ANN001
    """A party ledger named in a voucher list the mapping doesn't read: the census counts
    it by list and kind of ledger, and the ledger's profile says where it was named."""
    db, _, connector, _, _, _ = synced
    party = db.scalars(select(A.Ledger).where(A.Ledger.ledger_kind == "party")).first()
    cash = _key(db, "Cash")
    record = db.scalars(
        select(RawRecord)
        .join(A.Voucher, A.Voucher.raw_record_id == RawRecord.id)
        .join(A.VoucherLine, A.VoucherLine.voucher_id == A.Voucher.id)
        .join(A.Ledger, A.Ledger.id == A.VoucherLine.ledger_id)
        .where(A.Ledger.source_key == cash)
        .limit(1)
    ).one()
    extra = (
        f"<UDF:EXTRAENTRIES.LIST><LEDGERNAME>{party.name}</LEDGERNAME>"
        "<AMOUNT>-75.00</AMOUNT></UDF:EXTRAENTRIES.LIST>"
    )
    record.payload = record.payload.replace("</VOUCHER>", extra + "</VOUCHER>", 1)
    db.commit()
    connector.balances[AS_OF][party.source_key] += Decimal("75")
    out = "\n".join(_analyse(synced))
    assert "ledger lines outside the lists read: a custom (prefixed) list (a party ledger) 1" in out
    profile = next(x for x in out.splitlines() if x.startswith("  ledger A: "))
    assert "named in lists not read: a custom (prefixed) list 1" in profile


class Forex(Source):
    """A foreign-currency customer revalued by the source; its book value set by the test."""

    fx_key: str
    books: dict[date, Decimal]

    def closing_balances(self, entity, as_of):  # noqa: ANN001, ANN201
        return SourceBalances(
            as_of,
            dict(self.balances[as_of]),
            foreign_ledgers=frozenset({self.fx_key}),
            book_values={frozenset({self.fx_key}): self.books[as_of]},
        )


def test_foreign_ledgers_at_their_book_value_count_as_explained(synced) -> None:  # noqa: ANN001
    """Pilot 2026-10-16: three foreign-currency customers differed only because Tally's
    closing balance was revalued at current rates; their book value equals ours."""
    db, _, connector, _, _, ours = synced
    key = _key(db, "Cash")
    connector.__class__ = Forex
    connector.fx_key = key
    connector.books = {when: ours[when][key].balance for when in (AS_OF, date(2027, 3, 31))}
    for when in connector.books:
        connector.balances[when][key] += Decimal("321")  # revalued
    out = "\n".join(_analyse(synced))
    assert "0 ledgers differ" in out
    assert "foreign-currency ledgers: 1; matching the source's book value" in out
    assert "differing 0" in out
    # Off its book value too: profiled as a foreign-currency ledger.
    connector.books = {when: value - 1 for when, value in connector.books.items()}
    out = "\n".join(_analyse(synced))
    line = next(x for x in out.splitlines() if x.startswith("  ledger A: "))
    assert "kept in a foreign currency; its book value in the source differs from ours" in line
