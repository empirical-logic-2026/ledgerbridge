"""The data-completion fields end to end on MySQL (sync, transform, API read as report_ro), on the
seeded test company's recordings of 2026-11-06 (tests/fixtures/tally/rules/data-completion,
recorded through the connector's requests with every field parts 1 to 7 fetch). Each part adds
its checks here."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, aliased

from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import FixtureTransport
from core.db import get_engine
from core.models import accounting as A  # noqa: N812
from core.transform import link_orders
from core.validation import ORDER_NOT_FOUND_CAUSES, Validator
from tests.conftest import FIXTURES
from tests.test_migrations_integration import _config
from tests.test_sync_integration import CONNECTION, _cleanup
from workers.extract import get_or_create_connection
from workers.sync import run_sync

pytestmark = pytest.mark.integration

RULES = FIXTURES / "tally" / "rules" / "data-completion"


@pytest.fixture(scope="module")
def synced() -> Iterator[int]:
    """The seeded test company synced from its recordings; its entity id."""
    command.upgrade(_config(), "head")
    patch = pytest.MonkeyPatch()
    patch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(RULES)
    )
    with Session(get_engine()) as session:
        _cleanup(session)
        connection = get_or_create_connection(session, CONNECTION, "tally")
        session.commit()
        assert run_sync(session, connection, connector).status == "succeeded"
        entity_id = session.scalar(
            select(A.EntitySource.entity_id).where(A.EntitySource.connection_id == connection.id)
        )
        assert entity_id is not None
        for other in session.scalars(select(A.Entity).where(A.Entity.id != entity_id)):
            other.is_on_hold = True
        session.commit()
        yield entity_id
        for other in session.scalars(select(A.Entity).where(A.Entity.id != entity_id)):
            other.is_on_hold = False
        session.commit()
        _cleanup(session)  # leaves nothing behind for the other tests
    patch.undo()


@pytest.fixture(scope="module")
def client(synced: int) -> TestClient:
    from api.main import create_app

    return TestClient(create_app(), base_url="http://localhost")


def _bank_line(session: Session, entity_id: int, marker: str) -> A.VoucherLine:
    voucher = session.scalar(
        select(A.Voucher.id).where(
            A.Voucher.entity_id == entity_id, A.Voucher.narration.like(f"%[lb-seed:{marker}]%")
        )
    )
    return session.scalars(
        select(A.VoucherLine).where(
            A.VoucherLine.voucher_id == voucher, A.VoucherLine.transaction_type.is_not(None)
        )
    ).one()


def test_part_1_bank_details_and_the_utr_are_stored(synced: int) -> None:
    with Session(get_engine()) as s:
        neft = _bank_line(s, synced, "BANK-3")
        assert (neft.utr, neft.utr_source) == ("HDFCN52026100112345", "narration")
        assert (neft.instrument_number, neft.transaction_type) == ("NEFT", "e-Fund Transfer")
        cheque = _bank_line(s, synced, "BANK-4")
        assert (cheque.instrument_number, cheque.utr) == ("000777", None)
        assert (cheque.instrument_date, cheque.bank_cleared_date) == (
            date(2026, 10, 1),
            date(2026, 10, 2),
        )
        assert cheque.bank_recon_status == "Reconciled"
        imps = _bank_line(s, synced, "BANK-5")
        assert (imps.utr, imps.utr_source) == ("629012345678", "bank_field")


def test_part_1_the_transactions_page_shows_cheque_and_utr_apart(
    client: TestClient, synced: int
) -> None:
    response = client.get("/api/v1/transactions", params={"month": ["2026-10"]})
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    utrs = {r["utr"]: r["utr_source"] for r in rows if r["utr"]}
    assert utrs == {"HDFCN52026100112345": "narration", "629012345678": "bank_field"}
    cheques = {r["cheque"] for r in rows if r["cheque"]}
    assert {"000777", "NEFT", "IMPS"} <= cheques
    assert all(
        r["tally_bank_entry_id"] is None or r["tally_bank_entry_id"] != r["utr"] for r in rows
    )


# --- part 2: bill dates, due dates, opening bills ---------------------------------------------


def _opening_bills(session: Session, entity_id: int, ledger: str) -> list[tuple]:
    return [
        (r.bill_name, r.bill_date, r.due_date, r.amount, r.party_id is not None)
        for r in session.scalars(
            select(A.OpeningBill)
            .join(A.Ledger, A.Ledger.id == A.OpeningBill.ledger_id)
            .where(A.OpeningBill.entity_id == entity_id, A.Ledger.name == ledger)
            .order_by(A.OpeningBill.bill_name)
        )
    ]


def test_part_2_opening_bills_are_stored_with_their_party(synced: int) -> None:
    with Session(get_engine()) as session:
        assert _opening_bills(session, synced, "Customer Theta GST") == [
            ("OB-T1", date(2025, 3, 1), date(2025, 3, 31), Decimal("10000.0000"), True),
            ("OB-T2", date(2025, 3, 31), None, Decimal("5000.0000"), True),
        ]
        assert _opening_bills(session, synced, "Vendor Iota GST") == [
            ("OB-I1", date(2025, 3, 1), date(2025, 4, 15), Decimal("-5000.0000"), True),
            ("OB-I2", date(2025, 3, 31), None, Decimal("-3000.0000"), True),
        ]


def test_part_2_voucher_bills_keep_their_date_and_due_date(synced: int) -> None:
    with Session(get_engine()) as session:
        rows = session.execute(
            select(
                A.BillAllocation.bill_name, A.BillAllocation.bill_date, A.BillAllocation.due_date
            )
            .join(A.VoucherLine, A.VoucherLine.id == A.BillAllocation.voucher_line_id)
            .join(A.Voucher, A.Voucher.id == A.VoucherLine.voucher_id)
            .where(
                A.Voucher.entity_id == synced,
                A.BillAllocation.bill_type == "new_ref",
                A.BillAllocation.bill_name.in_(("INV-T1", "PI-I2")),
            )
            .order_by(A.BillAllocation.bill_name)
        ).all()
        assert [tuple(r) for r in rows] == [
            ("INV-T1", date(2026, 10, 1), date(2026, 10, 31)),
            ("PI-I2", date(2026, 10, 2), date(2026, 10, 31)),
        ]


def test_part_2_ageing_counts_the_opening_bills(client: TestClient, synced: int) -> None:
    for kind, party in (("customers", "Customer Theta GST"), ("vendors", "Vendor Iota GST")):
        response = client.get(f"/api/v1/ageing/{kind}", params={"month": ["2026-10"]})
        assert response.status_code == 200, response.text
        (row,) = [r for r in response.json()["rows"] if r["name"] == party]
        # Every amount of these parties is in a bill: the opening ones included.
        assert Decimal(row["uncovered"]) == 0, (kind, row)
        # The opening bills, from March 2025, are over 90 days past due by October 2026.
        assert Decimal(row["buckets"]["over_90"]) > 0, (kind, row)


def test_part_2_opening_bills_add_up_to_the_openings(synced: int) -> None:
    """LB-VAL-041: database only, so it runs in every validation (nothing is committed)."""
    with Session(get_engine()) as session:
        report = Validator(session, synced, date(2026, 10, 31)).run(None)
        assert "opening_bills_differ" not in {f.check_code for f in report.findings}
        bill = session.scalars(
            select(A.OpeningBill).where(A.OpeningBill.entity_id == synced).limit(1)
        ).one()
        bill.amount += 1
        session.flush()
        report = Validator(session, synced, date(2026, 10, 31)).run(None)
        (found,) = [f for f in report.findings if f.check_code == "opening_bills_differ"]
        assert (found.object_type, found.object_id) == ("ledger", str(bill.ledger_id))
        session.rollback()


# --- part 3: stock by godown and batch -----------------------------------------------------


def test_part_3_item_openings_are_stored_by_godown_and_batch(synced: int) -> None:
    with Session(get_engine()) as session:
        rows = session.execute(
            select(A.Item.name, A.Godown.name, A.ItemOpeningBatch.batch_name,
                   A.ItemOpeningBatch.quantity, A.ItemOpeningBatch.value)
            .join(A.Item, A.Item.id == A.ItemOpeningBatch.item_id)
            .join(A.Godown, A.Godown.id == A.ItemOpeningBatch.godown_id)
            .where(A.ItemOpeningBatch.entity_id == synced, A.Item.name.in_(("Gizmo", "Gizmo Pro")))
            .order_by(A.Item.name, A.ItemOpeningBatch.id)
        ).all()  # fmt: skip
        assert [tuple(r) for r in rows] == [
            ("Gizmo", "Main Location", "Primary Batch", Decimal(20), Decimal(400)),
            ("Gizmo", "Branch Store", "Primary Batch", Decimal(10), Decimal(200)),
            ("Gizmo Pro", "Main Location", "Batch A", Decimal(8), Decimal(240)),
            ("Gizmo Pro", "Branch Store", "Batch B", Decimal(4), Decimal(120)),
        ]


def test_part_3_moves_between_godowns_keep_the_other_godown(synced: int) -> None:
    counterpart = aliased(A.Godown)
    with Session(get_engine()) as session:
        rows = session.execute(
            select(A.Godown.name, A.InventoryLine.quantity, counterpart.name)
            .join(A.Voucher, A.Voucher.id == A.InventoryLine.voucher_id)
            .join(A.Godown, A.Godown.id == A.InventoryLine.godown_id)
            .join(counterpart, counterpart.id == A.InventoryLine.counterpart_godown_id)
            .where(A.Voucher.entity_id == synced)
            .order_by(A.InventoryLine.voucher_date, A.InventoryLine.quantity)
        ).all()
        assert [tuple(r) for r in rows] == [
            ("Main Location", Decimal(-80), "Job Worker Alpha"),  # MAT-OUT-1: sent
            ("Main Location", Decimal(10), "Job Worker Alpha"),  # MAT-IN-2: returned
            ("Main Location", Decimal(-5), "Branch Store"),  # STK-1: leaves
            ("Branch Store", Decimal(5), "Main Location"),  # STK-1: arrives
        ]


def test_part_3_item_openings_add_up(synced: int) -> None:
    """LB-VAL-042: database only, so it runs in every validation (nothing is committed)."""
    with Session(get_engine()) as session:
        report = Validator(session, synced, date(2026, 10, 31)).run(None)
        assert "item_openings_differ" not in {f.check_code for f in report.findings}
        batch = session.scalars(
            select(A.ItemOpeningBatch).where(A.ItemOpeningBatch.entity_id == synced).limit(1)
        ).one()
        batch.quantity += 1
        session.flush()
        report = Validator(session, synced, date(2026, 10, 31)).run(None)
        (found,) = [f for f in report.findings if f.check_code == "item_openings_differ"]
        assert (found.object_type, found.object_id) == ("item", str(batch.item_id))
        session.rollback()


# --- part 4: orders --------------------------------------------------------------------------


def _voucher_id(session: Session, entity_id: int, marker: str) -> int:
    found = session.scalar(
        select(A.Voucher.id).where(
            A.Voucher.entity_id == entity_id, A.Voucher.narration.like(f"%[lb-seed:{marker}]%")
        )
    )
    assert found is not None, marker
    return found


def test_part_4_invoices_are_linked_to_their_orders(synced: int) -> None:
    with Session(get_engine()) as session:
        for invoice, order, number in (
            ("ORD-1-INV", "ORD-1", "SO-1"),
            ("ORD-2-INV", "ORD-2", "PO-1"),
        ):
            rows = session.execute(
                select(A.VoucherOrder.order_number, A.VoucherOrder.order_date,
                       A.VoucherOrder.order_voucher_id)
                .where(A.VoucherOrder.voucher_id == _voucher_id(session, synced, invoice))
            ).all()  # fmt: skip
            assert [tuple(r) for r in rows] == [
                (number, date(2026, 10, 1), _voucher_id(session, synced, order))
            ]
            due = session.scalars(
                select(A.InventoryLine.order_due_date).where(
                    A.InventoryLine.voucher_id == _voucher_id(session, synced, order)
                )
            ).all()
            assert set(due) == {date(2026, 10, 31)}


def test_part_4_the_transactions_page_shows_the_order_number(
    client: TestClient, synced: int
) -> None:
    response = client.get("/api/v1/transactions", params={"month": ["2026-10"]})
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    by_bill = {r["bills"]: r["order_number"] for r in rows if r["bills"] in ("INV-T2", "PI-I3")}
    assert by_bill == {"INV-T2": "SO-1", "PI-I3": "PO-1"}
    # Orders themselves don't post to the books: they aren't on the page.
    assert not any(r["voucher_type"].endswith("Order") for r in rows)


def test_part_4_an_order_not_stored_is_a_warning(synced: int) -> None:
    """LB-VAL-043: database only (nothing is committed)."""
    with Session(get_engine()) as session:
        report = Validator(session, synced, date(2026, 10, 31)).run(None)
        assert "order_not_found" not in {f.check_code for f in report.findings}
        invoice = _voucher_id(session, synced, "ORD-1-INV")
        session.execute(
            update(A.VoucherOrder)
            .where(A.VoucherOrder.voucher_id == invoice)
            .values(order_number="SO-404", order_voucher_id=None)
        )
        assert link_orders(session, synced) == 0  # no order SO-404
        report = Validator(session, synced, date(2026, 10, 31)).run(None)
        (found,) = [f for f in report.findings if f.check_code == "order_not_found"]
        assert (found.object_type, found.object_id) == ("voucher", str(invoice))
        assert found.message == ORDER_NOT_FOUND_CAUSES["not_stored"][0]
        session.rollback()
        purchase_type = session.scalar(
            select(A.Voucher.voucher_type_id).where(
                A.Voucher.id == _voucher_id(session, synced, "ORD-2")
            )
        )
    _set_orders(synced, {"order_number": "SO-1"}, purchase_type, "PO-1")  # validation commits


def _set_orders(entity_id: int, invoice: dict, order_type: int, order_lines: str) -> None:
    """Sets the invoice's order reference, and the purchase order's (ORD-2) voucher type and
    line order numbers, committed (validation may commit), then links orders again."""
    with Session(get_engine()) as session:
        purchase_order = _voucher_id(session, entity_id, "ORD-2")
        session.execute(
            update(A.Voucher).where(A.Voucher.id == purchase_order)
            .values(voucher_type_id=order_type)
        )  # fmt: skip
        session.execute(
            update(A.InventoryLine).where(A.InventoryLine.voucher_id == purchase_order)
            .values(order_number=order_lines)
        )  # fmt: skip
        session.execute(
            update(A.VoucherOrder)
            .where(A.VoucherOrder.voucher_id == _voucher_id(session, entity_id, "ORD-1-INV"))
            .values(order_voucher_id=None, **invoice)
        )
        link_orders(session, entity_id)
        session.commit()


def _order_findings(entity_id: int) -> dict[str, str]:
    """The order_not_found findings of a validation: voucher id -> message."""
    with Session(get_engine()) as session:
        report = Validator(session, entity_id, date(2026, 10, 31)).run(None)
        session.rollback()
    return {f.object_id: f.message for f in report.findings if f.check_code == "order_not_found"}


def test_part_4_why_an_order_wasnt_found(synced: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """LB-VAL-043 by cause: two stored sales orders with the invoice's order number (never
    guessed between), and a missing order while vouchers failed to convert. Everything
    changed is put back."""
    with Session(get_engine()) as session:
        invoice = str(_voucher_id(session, synced, "ORD-1-INV"))
        sales_type, purchase_type = (
            session.scalar(
                select(A.Voucher.voucher_type_id).where(
                    A.Voucher.id == _voucher_id(session, synced, marker)
                )
            )
            for marker in ("ORD-1", "ORD-2")
        )
    try:
        # The purchase order becomes a second sales order SO-1.
        _set_orders(synced, {"order_number": "SO-1"}, sales_type, "SO-1")
        assert _order_findings(synced)[invoice] == ORDER_NOT_FOUND_CAUSES["ambiguous"][0]
        _set_orders(synced, {"order_number": "SO-404"}, purchase_type, "PO-1")
        monkeypatch.setattr(Validator, "_failed_records", lambda self, kind: 1)
        assert _order_findings(synced)[invoice] == ORDER_NOT_FOUND_CAUSES["failed"][0]
    finally:
        _set_orders(synced, {"order_number": "SO-1"}, purchase_type, "PO-1")
    assert invoice not in _order_findings(synced)  # linked again


# --- part 5: GST details -----------------------------------------------------------------


def test_part_5_gst_details_are_stored(synced: int) -> None:
    with Session(get_engine()) as session:
        invoice = session.get_one(A.Voucher, _voucher_id(session, synced, "BILL-1"))
        assert (invoice.gst_registration, invoice.place_of_supply) == ("Registration", "Karnataka")
        assert (invoice.irn_ack_number, invoice.irn_date) == ("112610012345678", date(2026, 10, 1))
        assert (invoice.eway_bill_number, invoice.eway_bill_date) == (
            "331001234567",
            date(2026, 10, 1),
        )
        types = dict(
            session.execute(
                select(A.Party.name, A.Party.gst_registration_type).where(
                    A.Party.entity_id == synced,
                    A.Party.name.in_(("Customer Theta GST", "Vendor Iota GST")),
                )
            ).all()
        )
        assert types == {"Customer Theta GST": "Regular", "Vendor Iota GST": "Composition"}
        gizmo = session.scalars(
            select(A.Item).where(A.Item.entity_id == synced, A.Item.name == "Gizmo")
        ).one()
        assert (gizmo.hsn_code, gizmo.gst_rate, gizmo.gst_taxability) == (
            "8471",
            Decimal(18),
            "Taxable",
        )
        units = session.execute(
            select(A.TaxUnit.name, A.TaxUnit.used_for, A.TaxUnit.registration_type)
            .where(A.TaxUnit.entity_id == synced)
            .order_by(A.TaxUnit.name)
        ).all()
        assert [tuple(u) for u in units] == [
            ("Default Tax Unit", None, None),
            ("Registration", "GST", "Regular"),
        ]
        # The recorded invoices take their rates from the items: no line rates of their own.
        assert (
            session.scalar(
                select(func.count())
                .select_from(A.LineGstRate)
                .where(A.LineGstRate.entity_id == synced)
            )
            == 0
        )


def test_part_5_the_transactions_page_and_gst_dataset(client: TestClient, synced: int) -> None:
    response = client.get("/api/v1/transactions", params={"month": ["2026-10"]})
    assert response.status_code == 200, response.text
    rows = [r for r in response.json()["rows"] if r["bills"] == "INV-T1"]
    assert rows and all(r["place_of_supply"] == "Karnataka" for r in rows)
    assert {r["eway_bill_number"] for r in rows} == {"331001234567"}
    assert {r["party_gst_registration_type"] for r in rows} == {"Regular"}
    grouped = client.get(
        "/api/v1/datasets/gst",
        params={"group_by": "tax_head", "measure": ["credit"], "date_from": "2026-10-01",
                "date_to": "2026-10-31"},
    )  # fmt: skip
    assert grouped.status_code == 200, grouped.text
    body = grouped.json()
    assert Decimal(body["total"]["credit"]) > 0
    assert "CGST" in str(body["rows"]) and "SGST" in str(body["rows"])


# --- part 6: settings and order --------------------------------------------------------------


def test_part_6_settings_and_order_are_stored(synced: int) -> None:
    with Session(get_engine()) as session:
        entity = session.get_one(A.Entity, synced)
        assert (entity.is_integrated, entity.is_fifo, entity.audited_upto) == (
            True,
            True,
            date(2027, 1, 1),
        )
        positions = dict(
            session.execute(
                select(A.AccountGroup.name, A.AccountGroup.sort_position).where(
                    A.AccountGroup.entity_id == synced, A.AccountGroup.is_primary.is_(True)
                )
            ).all()
        )
        assert (positions["Capital Account"], positions["Indirect Expenses"]) == (10, 280)
        stock = session.scalar(
            select(func.count()).where(
                A.Ledger.entity_id == synced, A.Ledger.affects_stock.is_(True)
            )
        )
        assert stock == 5
        series = session.scalars(
            select(A.VoucherNumberSeries.name)
            .join(A.VoucherType, A.VoucherType.id == A.VoucherNumberSeries.voucher_type_id)
            .where(A.VoucherType.entity_id == synced, A.VoucherType.name == "Seed Sales")
            .order_by(A.VoucherNumberSeries.id)
        ).all()
        assert series == ["Default", "Branch"]
        branch = session.get_one(A.Voucher, _voucher_id(session, synced, "SER-1"))
        assert branch.number_series == "Branch"
        reversing = session.get_one(A.Voucher, _voucher_id(session, synced, "REV-JNL-1"))
        assert (reversing.active_to, reversing.has_cash_flow) == (date(2026, 10, 1), False)


# --- part 7: other masters -----------------------------------------------------------------


def test_part_7_budgets_categories_prices_and_reorder_levels(synced: int) -> None:
    with Session(get_engine()) as session:
        gizmo = session.scalars(
            select(A.Item).where(A.Item.entity_id == synced, A.Item.name == "Gizmo")
        ).one()
        category = session.get_one(A.StockCategory, gizmo.stock_category_id)
        assert category.name == "Electronics"
        assert (gizmo.reorder_level, gizmo.min_order_quantity) == (Decimal(10), Decimal(5))
        prices = session.execute(
            select(A.ItemPrice.price_level, A.ItemPrice.applicable_from, A.ItemPrice.rate).where(
                A.ItemPrice.item_id == gizmo.id
            )
        ).all()
        assert [tuple(p) for p in prices] == [("Wholesale", date(2025, 4, 1), Decimal(35))]
        budget = session.scalars(
            select(A.SourceBudget).where(A.SourceBudget.entity_id == synced)
        ).one()
        assert (budget.name, budget.use_actuals) == ("FY27 Plan", True)
        lines = session.execute(
            select(A.Ledger.name, A.SourceBudgetLine.basis, A.SourceBudgetLine.amount)
            .join(A.Ledger, A.Ledger.id == A.SourceBudgetLine.ledger_id)
            .where(A.SourceBudgetLine.budget_id == budget.id)
            .order_by(A.SourceBudgetLine.id)
        ).all()
        assert [tuple(x) for x in lines] == [
            ("Electricity", "net_transactions", Decimal(60000)),
            ("Courier Charges", "net_transactions", Decimal(12000)),
        ]
