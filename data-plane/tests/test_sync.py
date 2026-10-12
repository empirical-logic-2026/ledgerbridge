"""M3: sync and transform on the recorded LedgerBridge Test Co fixtures (SQLite, no Tally)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from connectors.base import SourceRecord
from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import DEFAULT_DIR
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.models.base import utcnow
from core.models.source import RawRecord
from core.raw_store import RawStore
from core.transform import Transformer, mark_deleted, trial_balance
from tests.conftest import COMPANY
from workers.sync import (
    deletion_check_interval,
    is_due,
    last_run,
    load_markers,
    run_deletion_check,
    run_sync,
)

pytestmark = pytest.mark.skipif(
    not (DEFAULT_DIR / "manifest.json").exists(), reason="no recorded fixtures"
)


def _count(db: Session, model: type, *where: object) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


def _entity(db: Session) -> A.Entity:
    return db.scalars(select(A.Entity)).one()


def _balances(db: Session) -> dict[str, Decimal]:
    return dict(trial_balance(db, _entity(db).id))


def test_entity_and_entity_source_created_from_company(db: Session, synced: S.Connection) -> None:
    entity = _entity(db)
    assert entity.name == COMPANY
    assert entity.code == "LEDGERBRIDGE_TEST_CO"
    assert entity.fy_start_month == 4
    assert entity.books_from is not None and entity.books_from.isoformat() == "2026-04-01"
    link = db.scalars(select(A.EntitySource)).one()
    assert (link.entity_id, link.connection_id, link.source_entity_name) == (
        entity.id,
        synced.id,
        COMPANY,
    )


def test_every_object_lands_in_its_table(db: Session, synced: S.Connection) -> None:
    counts = {
        "groups": _count(db, A.AccountGroup),
        "ledgers": _count(db, A.Ledger),
        "parties": _count(db, A.Party),
        "voucher_types": _count(db, A.VoucherType),
        "units": _count(db, A.Unit),
        "godowns": _count(db, A.Godown),
        "items": _count(db, A.Item),
        "cost_centres": _count(db, A.CostCentre),
        "vouchers": _count(db, A.Voucher),
        "cancelled": _count(db, A.Voucher, A.Voucher.is_cancelled.is_(True)),
        "cost_allocations": _count(db, A.LineCostAllocation),
        "inventory_lines": _count(db, A.InventoryLine),
    }
    assert counts == {
        "groups": 29,  # Tally's 28 + the synthetic Primary carrying Profit & Loss A/c
        "ledgers": 21,
        "parties": 6,
        "voucher_types": 24,
        "units": 1,
        "godowns": 1,
        "items": 1,
        "cost_centres": 2,
        "vouchers": 18,  # incl. ALTER-2; DEL-1 was deleted in Tally
        "cancelled": 1,
        "cost_allocations": 2,
        "inventory_lines": 1,
    }
    assert _count(db, RawRecord, RawRecord.process_status != "processed") == 0


def test_every_voucher_balances_and_lines_are_effective_only_when_they_count(
    db: Session, synced: S.Connection
) -> None:
    sums = db.execute(
        select(A.VoucherLine.voucher_id, func.sum(A.VoucherLine.amount)).group_by(
            A.VoucherLine.voucher_id
        )
    ).all()
    assert sums and all(total == 0 for _, total in sums)
    cancelled = db.scalars(select(A.Voucher).where(A.Voucher.is_cancelled.is_(True))).one()
    assert _count(db, A.VoucherLine, A.VoucherLine.voucher_id == cancelled.id) == 0


def test_trial_balance_matches_tally(db: Session, synced: S.Connection) -> None:
    balances = _balances(db)
    assert balances["Rent"] == Decimal("1000")
    assert balances["Cash"] == Decimal("27500")
    assert balances["Capital"] == Decimal("-50000")
    assert balances["Electricity"] == Decimal("4500")
    assert balances["Test Bank Current A/c"] == Decimal("25260")  # ALTER-2: +5,900
    assert sum(balances.values()) == 0


def test_standard_accounts_mapped_from_groups(db: Session, synced: S.Connection) -> None:
    rows = db.execute(
        select(
            A.Ledger.name, A.StandardAccount.code, A.Ledger.mapping_status, A.Ledger.ledger_kind
        ).outerjoin(A.StandardAccount, A.StandardAccount.id == A.Ledger.standard_account_id)
    ).all()
    by_name = {name: (code, status, kind) for name, code, status, kind in rows}
    assert by_name["Cash"] == ("1231", "auto", "cash")
    assert by_name["Test Bank Current A/c"] == ("1232", "auto", "bank")
    assert by_name["Capital"] == ("2100", "auto", "equity")
    assert by_name["Profit & Loss A/c"] == ("2200", "auto", "equity")
    assert by_name["Customer Alpha Traders"] == ("1220", "auto", "party")
    assert by_name["Vendor Delta Supplies"] == ("3220", "auto", "party")
    assert by_name["Sales - Goods"][:2] == ("4110", "auto")
    assert by_name["Salary Payable"][:2] == ("3270", "auto")
    # Duties & Taxes by tax type: GST on the debit side (1250) until M6 reclassifies credit
    # balances to 3230 at the reporting date.
    for name in ("Input CGST", "Input SGST", "Output CGST", "Output SGST"):
        assert by_name[name] == ("1250", "auto", "tax")
    unmapped = sorted(name for name, (_, status, _) in by_name.items() if status == "unmapped")
    assert unmapped == ["Electricity", "Rent", "Salary"]  # Indirect Expenses
    parties = dict(db.execute(select(A.Party.name, A.Party.party_type)).all())
    assert parties["Customer Beta Retail"] == "customer"
    assert parties["Vendor Zeta Services"] == "vendor"


def test_bills_tax_and_inventory_details(db: Session, synced: S.Connection) -> None:
    bills = dict(
        db.execute(
            select(A.BillAllocation.bill_name, A.BillAllocation.bill_type).where(
                A.BillAllocation.bill_name.in_(("SI-1", "PI-1"))
            )
        ).all()
    )
    assert set(bills.values()) <= {"new_ref", "against_ref"}
    assert _count(db, A.BillAllocation, A.BillAllocation.bill_type == "against_ref") == 5
    taxes = dict(
        db.execute(select(A.TaxLine.tax_type, func.count()).group_by(A.TaxLine.tax_type)).all()
    )
    assert taxes == {"cgst": 7, "sgst": 7}
    inv = db.scalars(select(A.InventoryLine)).one()
    assert (inv.quantity, inv.amount) == (Decimal("-10"), Decimal("-2000"))  # sale: stock out


def test_second_sync_is_incremental_and_changes_nothing(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    before = {m.__name__: _count(db, m) for m in (A.Voucher, A.VoucherLine, A.Ledger, RawRecord)}
    markers = load_markers(
        db, synced.id, db.scalars(select(A.EntitySource)).one().source_entity_key
    )
    assert markers["voucher"] and markers["ledger"]
    result = run_sync(db, synced, connector, [COMPANY])
    assert (result.status, result.run_type) == ("succeeded", "incremental")
    assert sum(n for t, n in result.fetched.items() if t != "company") == 0
    after = {m.__name__: _count(db, m) for m in (A.Voucher, A.VoucherLine, A.Ledger, RawRecord)}
    assert after == before


def _voucher_raw(db: Session, marker: str) -> RawRecord:
    return db.scalars(
        select(RawRecord).where(
            RawRecord.object_type == "voucher", RawRecord.payload.contains(f"[lb-seed:{marker}]")
        )
    ).first()


def _redeliver(
    db: Session, connection: S.Connection, row: RawRecord, payload: str, alter: int
) -> None:
    record = SourceRecord(row.source_entity_key, "voucher", row.source_key, alter, "xml", payload)
    RawStore(db).add([record], connection.id)
    db.commit()


def test_month_overlap_updates_never_duplicates(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    """A voucher delivered by two overlapping month requests is one voucher, once."""
    row = _voucher_raw(db, "PMT-ANCHOR")
    voucher = db.scalars(select(A.Voucher).where(A.Voucher.source_key == row.source_key)).one()
    lines_before = _count(db, A.VoucherLine, A.VoucherLine.voucher_id == voucher.id)
    # Two deliveries of the same voucher, pending at the same time (whitespace differs, so
    # the raw store keeps both, as overlapping requests would).
    for suffix in (" ", "  "):
        record = SourceRecord(
            row.source_entity_key,
            "voucher",
            row.source_key,
            row.source_alter_id,
            "xml",
            row.payload + suffix,
        )
        RawStore(db).add([record], synced.id)
    db.commit()
    result = Transformer(db, synced.id, connector).run()
    assert result.failed == 0 and result.processed == 2
    assert _count(db, A.Voucher, A.Voucher.source_key == row.source_key) == 1
    assert _count(db, A.VoucherLine, A.VoucherLine.voucher_id == voucher.id) == lines_before
    assert _balances(db)["Rent"] == Decimal("1000")


def test_altered_voucher_replaces_its_lines(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    row = _voucher_raw(db, "ALTER-1")
    voucher = db.scalars(select(A.Voucher).where(A.Voucher.source_key == row.source_key)).one()
    total_lines_before = _count(db, A.VoucherLine)
    altered = row.payload.replace("-1500.00", "-1700.00").replace(">1500.00<", ">1700.00<")
    assert altered != row.payload
    _redeliver(db, synced, row, altered, (row.source_alter_id or 0) + 100)
    Transformer(db, synced.id, connector).run()
    lines = db.scalars(select(A.VoucherLine).where(A.VoucherLine.voucher_id == voucher.id)).all()
    assert len(lines) == 2
    assert _count(db, A.VoucherLine) == total_lines_before  # replaced, not appended
    assert sorted(line.amount for line in lines) == [Decimal("-1700"), Decimal("1700")]
    balances = _balances(db)
    assert balances["Cash"] == Decimal("27300")
    assert balances["Electricity"] == Decimal("4700")


def test_full_sync_reapplies_mapping_to_unchanged_records(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    """A mapping rule change reaches existing data with a full sync, though Tally is unchanged."""
    ledger = db.scalars(select(A.Ledger).where(A.Ledger.name == "Input CGST")).one()
    ledger.standard_account_id, ledger.mapping_status = None, "unmapped"  # as under old rules
    db.commit()
    incremental = run_sync(db, synced, connector, [COMPANY])
    assert sum(incremental.transformed.values()) == 0
    full = run_sync(db, synced, connector, [COMPANY], full=True)
    assert full.status == "succeeded" and full.failed == 0
    assert full.stored == 0 and full.transformed["ledger"] == 21
    db.refresh(ledger)
    assert ledger.mapping_status == "auto"
    assert _count(db, A.Voucher) == 18 and sum(_balances(db).values()) == 0


def test_sync_alone_never_soft_deletes(
    db: Session, synced: S.Connection, connector: TallyConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(connector, "list_keys", lambda entity: pytest.fail("listed keys"))
    result = run_sync(db, synced, connector, [COMPANY], full=True)
    assert result.status == "succeeded" and result.deleted == {}


def test_deletion_check_run_soft_deletes_what_has_gone(
    db: Session, synced: S.Connection, connector: TallyConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _voucher_raw(db, "PMT-ANCHOR")
    list_keys = connector.list_keys

    def without_anchor(entity):  # noqa: ANN001, ANN202
        keys = list_keys(entity)
        keys["voucher"].discard(row.source_key)
        return keys

    monkeypatch.setattr(connector, "list_keys", without_anchor)
    result = run_deletion_check(db, synced, connector, [COMPANY])
    assert (result.status, result.run_type) == ("succeeded", "deletion_check")
    assert result.deleted == {"voucher:vouchers": 1}
    assert result.fetched["voucher"] == 17
    assert _balances(db)["Rent"] == Decimal("0")
    # Logged as its own run; the latest *sync* is still the first one.
    assert last_run(db, synced.id, ("deletion_check",)).id == result.sync_run_id
    assert last_run(db, synced.id).run_type == "full"


def test_voucher_deleted_in_source_is_soft_deleted(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    row = _voucher_raw(db, "PMT-ANCHOR")
    entity = _entity(db)
    keys = connector.list_keys(connector.list_entities()[0])
    keys["voucher"].discard(row.source_key)
    deleted = mark_deleted(db, synced.id, entity.id, keys)
    assert deleted == {"voucher:vouchers": 1}
    voucher = db.scalars(select(A.Voucher).where(A.Voucher.source_key == row.source_key)).one()
    assert voucher.is_deleted
    assert _balances(db)["Rent"] == Decimal("0")
    # Nothing else, in particular not the synthetic Primary group, was deleted.
    assert _count(db, A.AccountGroup, A.AccountGroup.is_deleted.is_(True)) == 0


def test_scheduler_is_due_logic() -> None:
    connection = S.Connection(status="active", sync_interval_sec=300)
    now = utcnow()
    assert is_due(connection, None, now)
    assert not is_due(connection, now - timedelta(seconds=299), now)
    assert is_due(connection, now - timedelta(seconds=300), now)
    connection.status = "paused"
    assert not is_due(connection, None, now)


def test_deletion_check_has_its_own_interval() -> None:
    connection = S.Connection(status="active", sync_interval_sec=300, config={})
    now = utcnow()
    hourly = deletion_check_interval(connection)
    assert hourly == 3600
    assert not is_due(connection, now - timedelta(seconds=600), now, hourly)
    assert is_due(connection, now - timedelta(seconds=3600), now, hourly)
    connection.config = {"deletion_check_interval_sec": 900}
    assert deletion_check_interval(connection) == 900
