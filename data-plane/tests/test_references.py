"""Resolving references by name and explaining the ones that don't resolve (ADR-027; pilot
2026-10-13: 29 ledgers failed for an unknown group and 369,740 vouchers for an unknown
ledger; 1,443 unbalanced vouchers of type "other")."""

from datetime import date

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from connectors.tally import mapping
from connectors.tally.connector import TallyConnector
from core import transform as T  # noqa: N812
from core.canonical import CanonicalVoucherType
from core.models import accounting as A  # noqa: N812
from core.models.source import RawRecord
from core.names import NameIndex, close_match, differences, normalise
from core.validation import Validator
from tests.sim_tally import MEMO_DAY, NAME_VARIANTS, NFC_NAME, NFD_NAME, SimTally
from workers import cli
from workers.extract import get_or_create_connection
from workers.references import explain_entity, lines
from workers.sync import run_sync

# --- the rules ------------------------------------------------------------------------------


def test_normalise_decodes_entities_unicode_spaces_and_case() -> None:
    assert normalise("  Sales  -\tGoods ") == "sales - goods"
    assert normalise("R&amp;amp;D") == normalise("R&D") == "r&d"
    assert normalise(NFD_NAME) == normalise(NFC_NAME)
    assert normalise("Cash" + chr(0xA0) + "A/c") == "cash a/c"  # no-break space


def test_exact_then_alias_then_normalised_and_only_one_candidate() -> None:
    index = NameIndex.build(
        [("Overheads", 1), ("Cash", 2), ("Sales - Goods", 3)],
        [("Indirect Expenses", 1)],
    )
    assert index.resolve("Cash").how == "exact"
    assert (index.resolve("Indirect Expenses").value, index.resolve("Indirect Expenses").how) == (
        1,
        "alias",
    )
    assert index.resolve("indirect  expenses").how == "normalised"
    assert index.resolve("CASH").value == 2
    assert not index.resolve("Sales-Goods").found  # punctuation is never matched
    assert not index.resolve("C" + chr(0x430) + "sh").found  # nor look-alike letters
    two = NameIndex.build([("Rent", 1), ("RENT", 2)])
    assert two.resolve("Rent").value == 1  # exact still wins
    found = two.resolve("rent")
    assert not found.found and found.ambiguous


def test_kinds_of_difference_never_name_the_value() -> None:
    assert differences(" Rent", "Rent") == ["leading/trailing spaces"]
    assert differences("Salary  Payable", "Salary Payable") == ["double or unusual spaces"]
    assert differences("rent", "Rent") == ["case"]
    assert differences("R&amp;D", "R&D") == ["XML entities"]
    assert differences(NFD_NAME, NFC_NAME) == ["Unicode normalisation"]
    assert differences("R" + chr(0x435) + "nt", "Rent") == ["look-alike characters"]
    assert differences("Sales-Goods", "Sales - Goods") == ["punctuation"]
    assert differences("Rent", "Rates") == ["other"]
    assert close_match("Sales-Goods", ["Sales - Goods", "Cash"]) == (
        "Sales - Goods",
        ["punctuation"],
    )
    assert close_match("Nowhere Ledger", ["Rent", "Cash"]) == (None, [])


# --- the transform --------------------------------------------------------------------------


@pytest.fixture
def sim(db: Session, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connection = get_or_create_connection(db, "tally-sim", "tally")
    connection.config = {**connection.config, "timeout_sec": 120}
    db.commit()
    transport = SimTally(per_day=1, name_variants=True)
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000", "timeout_sec": 120}, transport=transport
    )
    result = run_sync(db, connection, connector, full=True, sleep=lambda s: None)
    return connection, connector, transport, result


def _voucher_ledgers(db: Session, day: int) -> list[str]:
    voucher = db.scalar(
        select(A.Voucher).where(A.Voucher.source_key == f"sim0-202604{day:02d}-0000")
    )
    if voucher is None:
        return []
    return list(
        db.scalars(
            select(A.Ledger.name)
            .join(A.VoucherLine, A.VoucherLine.ledger_id == A.Ledger.id)
            .where(A.VoucherLine.voucher_id == voucher.id)
            .order_by(A.VoucherLine.line_no)
        )
    )


def test_references_resolve_by_alias_and_normalisation(db: Session, sim) -> None:  # noqa: ANN001
    connection, _, transport, result = sim
    assert result.status == "succeeded", result.error
    unresolved = sum(1 for _, ok in NAME_VARIANTS.values() if not ok)
    # Only the references no rule may match fail: 3 vouchers, and the ledger naming a
    # group that wasn't fetched.
    assert result.failed_by_object_type == {"voucher": unresolved, "ledger": 1}
    assert _voucher_ledgers(db, 5) == ["Rent", "Cash"]  # case
    assert _voucher_ledgers(db, 6) == ["Salary Payable", "Cash"]  # double space
    assert _voucher_ledgers(db, 7) == [NFC_NAME, "Cash"]  # Unicode NFD vs NFC
    assert _voucher_ledgers(db, 8) == ["Power & Fuel", "Cash"]  # entity escaped twice
    for day in (9, 10, 11):
        assert _voucher_ledgers(db, day) == []
    # The renamed reserved group is found by its reserved name, and keeps its hints.
    overheads = db.scalar(select(A.AccountGroup).where(A.AccountGroup.name == "Overheads"))
    rent = db.scalar(select(A.Ledger).where(A.Ledger.name == "Rent"))
    assert rent.group_id == overheads.id
    # Customers name their group "sundry  debtors": still parties, as customers.
    assert (
        db.scalar(select(func.count()).select_from(A.Party).where(A.Party.party_type == "customer"))
        == 3
    )
    warnings = dict(
        db.execute(
            select(RawRecord.source_key, RawRecord.process_warning).where(
                RawRecord.process_warning.is_not(None)
            )
        ).all()
    )
    assert (
        warnings["sim0-20260405-0000"] == "reference matched after normalisation: voucher -> ledger"
    )
    assert warnings[rent.source_key] == "reference matched by alias: ledger -> group"
    errors = set(
        db.scalars(select(RawRecord.process_error).where(RawRecord.process_status == "failed"))
    )
    assert errors == {
        "TransformError: voucher refers to an unknown ledger",
        "TransformError: ledger refers to an unknown group",
    }


def test_vouchers_of_types_that_dont_post_dont_count(db: Session, sim) -> None:  # noqa: ANN001
    connection, *_ = sim
    memo = db.scalar(select(A.VoucherType).where(A.VoucherType.name == "Payment Memo"))
    assert (memo.standard_type, memo.is_accounting, memo.base_type) == (
        "Memorandum",
        False,
        "other",
    )
    base = db.scalar(select(A.VoucherType).where(A.VoucherType.name == "Memo Base"))
    assert (base.standard_type, base.is_accounting) == ("Memorandum", False)
    payment = db.scalar(select(A.VoucherType).where(A.VoucherType.name == "Payment"))
    assert (payment.standard_type, payment.is_accounting, payment.base_type) == (
        "Payment",
        True,
        "payment",
    )
    voucher = db.scalar(
        select(A.Voucher).where(A.Voucher.source_key == f"sim0-202604{MEMO_DAY:02d}-0000")
    )
    effective = db.scalars(
        select(A.VoucherLine.is_effective).where(A.VoucherLine.voucher_id == voucher.id)
    ).all()
    assert effective and not any(effective)
    entity_id = db.scalar(select(A.Entity.id))
    report = Validator(db, entity_id, date.today()).run(None)
    assert "voucher_unbalanced" not in report.failed_by_code  # the memo doesn't count


def test_unbalanced_breakdown_by_standard_type(db: Session, sim) -> None:  # noqa: ANN001
    entity_id = db.scalar(select(A.Entity.id))
    line = db.scalar(
        select(A.VoucherLine)
        .join(A.Voucher)
        .where(A.Voucher.source_key == "sim0-20260420-0000")
        .limit(1)
    )
    line.amount += 1
    db.commit()
    report = Validator(db, entity_id, date.today()).run(None)
    assert report.unbalanced_by_type == {"Payment": 1}
    assert report.unbalanced_details == {}  # two lines, no inventory, not post-dated


def test_voucher_type_mapping_follows_parents() -> None:
    import xml.etree.ElementTree as ET  # noqa: N817

    def vt(xml: str) -> CanonicalVoucherType:
        return mapping.voucher_type(ET.fromstring(xml), "k")  # noqa: S314

    custom = vt('<VOUCHERTYPE NAME="Cash Sale 2"><PARENT>Cash Sale</PARENT></VOUCHERTYPE>')
    assert (custom.base_type, custom.is_accounting, custom.parent_name) == (None, None, "Cash Sale")
    sale = vt('<VOUCHERTYPE NAME="Cash Sale"><PARENT>Sales</PARENT></VOUCHERTYPE>')
    assert (sale.base_type, sale.standard_type, sale.is_accounting) == ("sales", "Sales", True)
    order = vt(
        '<VOUCHERTYPE NAME="Order" RESERVEDNAME="Sales Order">'
        "<PARENT>Sales Order</PARENT></VOUCHERTYPE>"
    )
    assert (order.standard_type, order.is_accounting) == ("Sales Order", False)
    tree = T._TypeTree([custom, sale])  # noqa: SLF001
    info = tree.info(custom)
    assert (info.base_type, info.is_accounting, info.standard_type) == ("sales", True, "Sales")


# --- the diagnostic ---------------------------------------------------------------------------


def _explain(db: Session, connection, connector, check_source: bool = False):  # noqa: ANN001, ANN202
    key = db.scalar(select(A.EntitySource.source_entity_key))
    entity_id = db.scalar(select(A.EntitySource.entity_id))
    entity = next(e for e in connector.list_entities() if e.key == key) if check_source else None
    return explain_entity(db, connection, connector, key, entity_id, "entity 1 (company 1)",
                          lambda m: None, entity)  # fmt: skip


def test_explain_kinds_without_names(db: Session, sim) -> None:  # noqa: ANN001
    connection, connector, *_ = sim
    explanation = _explain(db, connection, connector)
    by_label = {r.relation.label: r for r in explanation.relations}
    vouchers = by_label["voucher -> ledger"]
    assert vouchers.records == 3
    assert vouchers.names == {
        "not found; a close match exists": 2,
        "not found; no close match": 1,
    }
    assert vouchers.kinds == {"look-alike characters": 1, "punctuation": 1}
    group = by_label["ledger -> group"]
    assert group.names == {"a predefined name of the source (e.g. a reserved group), not stored": 1}
    output = "\n".join(lines(explanation))
    for secret in ("Rent", "Nowhere", "Suspense", "Sales", "Capital"):
        assert secret not in output


def test_explain_shows_what_resolves_now(db: Session, sim) -> None:  # noqa: ANN001
    """A voucher that failed under the old exact-only rule resolves now: rebuild fixes it."""
    connection, connector, *_ = sim
    db.execute(
        RawRecord.__table__.update()
        .where(RawRecord.source_key == "sim0-20260405-0000")
        .values(
            process_status="failed",
            process_error="TransformError: voucher refers to an unknown ledger",
        )
    )
    db.commit()
    report = {r.relation.label: r for r in _explain(db, connection, connector).relations}
    assert report["voucher -> ledger"].names["resolves now after normalisation"] == 1
    assert report["voucher -> ledger"].kinds["case"] == 1


def test_explain_checks_the_source(db: Session, sim) -> None:  # noqa: ANN001
    """With the source: the missing reserved group is listed by the source (our group request
    left it out here), and per master type listed vs stored."""
    from workers.references import completeness

    connection, connector, *_ = sim
    explanation = _explain(db, connection, connector, check_source=True)
    group = {r.relation.label: r for r in explanation.relations}["ledger -> group"]
    assert group.source == {"listed by the source now, but not stored (not fetched)": 1}
    key = db.scalar(select(A.EntitySource.source_entity_key))
    entity = next(e for e in connector.list_entities() if e.key == key)
    counts = completeness(db, connection, connector, entity)
    assert counts["group"] == (28, 27, 1)
    assert counts["ledger"][2] == 0


def test_explain_command_is_pilot_safe(engine: Engine, sim, monkeypatch, capsys) -> None:  # noqa: ANN001
    from core.config import Settings

    connection, connector, *_ = sim
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "_terminate_raises_system_exit", lambda: None)
    monkeypatch.setattr(cli, "connector_for", lambda session, connection: connector)
    settings = Settings(app_env="pilot", ai_provider="ollama")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    code = cli.main(["transform-explain", "--connection", "tally-sim", "--check-source"])
    out = capsys.readouterr().out
    assert code == 0
    assert (
        "entity 1 (company 1): voucher -> ledger: 3 failed records refer to 3 names that "
        "don't resolve exactly"
    ) in out
    assert "kinds of difference: look-alike characters 1, punctuation 1" in out
    assert (
        "entity 1 (company 1): group: the source lists 28, stored 27, listed but not stored 1"
        in out
    )
    assert "Result: explain finished" in out
    for secret in ("Rent", "Nowhere", "Suspense", "Sim Co", "Sales", NFC_NAME):
        assert secret not in out
