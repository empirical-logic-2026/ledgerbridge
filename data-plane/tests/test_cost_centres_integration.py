"""Cost centres, voucher references and bank instruments, end to end on MySQL (the test
stack's database; `./dev.ps1 up`, or only the test MySQL with migrations applied).

The recorded test company (tests/fixtures/tally) is synced, then the cost-centre recordings of
2026-11-05 (tests/fixtures/tally/rules/cost_centres: the cost categories and centres, and the
August and September vouchers through the sync's own request) are added and converted, as a
sync of the changed records would. In them:

- CC-1 (August): Electricity 3,000 to Head Office 2,000 and Branch 1,000;
- CC-2 (September): Electricity 4,000 in two categories: Head Office 4,000 (Primary Cost
  Category) and Project Alpha 1,500 and Alpha Phase 1 2,500 (Projects, Alpha Phase 1 under
  Project Alpha), paid by cheque 000451;
- CC-3: a purchase invoice whose item line allocates Purchases 600 to Branch 400 and Head
  Office 200 (Tally keeps them under the item's accounting allocation), reference
  SUP-INV-4471;
- BANK-1: rent by cheque 000452; BANK-2: a vendor paid by e-transfer NEFT-2026-0902, UTR
  UTR20260902000017.

Tally's own cost centre totals were recorded at 31 August and 30 September."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from connectors.base import SourceControls
from connectors.tally import envelopes, parser
from connectors.tally.connector import TallyConnector, _canonical
from connectors.tally.fixtures import DEFAULT_DIR, FixtureTransport
from core.db import get_engine
from core.models import accounting as A  # noqa: N812
from core.raw_store import RawStore
from core.transform import Transformer
from core.validation import Validator
from tests.conftest import FIXTURES
from tests.test_migrations_integration import _config
from tests.test_sync_integration import CONNECTION, _cleanup
from workers.extract import get_or_create_connection
from workers.sync import run_sync

pytestmark = pytest.mark.integration
RULES = FIXTURES / "tally" / "rules" / "cost_centres"
D = Decimal


# The vouchers of these recordings this test adds (the others name masters recorded after the
# main fixtures, 2026-10-12).
MARKERS = ("CC-1", "CC-2", "CC-3", "BANK-1", "BANK-2")


def _records(name: str, spec: envelopes.CollectionSpec, entity_key: str) -> list:
    records = parser.parse_records((RULES / name).read_bytes(), spec, entity_key)
    if spec is not envelopes.VOUCHERS:
        return list(records)
    return [r for r in records if any(f"[lb-seed:{m}]" in r.payload for m in MARKERS)]


def _tallys_totals(on: date) -> dict[str, Decimal]:
    """Tally's recorded cost centre totals at the date, as the connector reads them."""
    body = (RULES / f"cost_centre_balances_{on:%Y-%m-%d}.xml").read_bytes()
    return {
        parser.source_key(e): _canonical(e.findtext("CLOSINGBALANCE"))
        for e in parser.objects(parser.parse_response(body), "COSTCENTRE")
        if parser.source_key(e)
    }


@pytest.fixture(scope="module")
def synced() -> Iterator[int]:
    """The test company synced, plus the cost-centre recordings; its entity id."""
    if not (DEFAULT_DIR / "manifest.json").exists():
        pytest.skip("no recorded fixtures")
    command.upgrade(_config(), "head")
    patch = pytest.MonkeyPatch()
    patch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    connector = TallyConnector.from_config(
        {"url": "http://tally.test:9000"}, transport=FixtureTransport(DEFAULT_DIR)
    )
    with Session(get_engine()) as session:
        _cleanup(session)
        connection = get_or_create_connection(session, CONNECTION, "tally")
        session.commit()
        assert run_sync(session, connection, connector).status == "succeeded"
        entity_id, key = session.execute(
            select(A.EntitySource.entity_id, A.EntitySource.source_entity_key).where(
                A.EntitySource.connection_id == connection.id
            )
        ).one()
        held = list(session.scalars(select(A.Entity.id).where(A.Entity.id != entity_id)))
        for other in held:
            session.get_one(A.Entity, other).is_on_hold = True
        records = []
        for name, spec in (
            ("cost_categories.xml", envelopes.COST_CATEGORIES),
            ("cost_centres.xml", envelopes.COST_CENTRES),
            ("vouchers_2026-08.xml", envelopes.VOUCHERS),
            ("vouchers_2026-09.xml", envelopes.VOUCHERS),
        ):
            records += _records(name, spec, key)
        RawStore(session).add(records, connection.id)
        session.commit()
        result = Transformer(session, connection.id, connector).run()
        assert result.failed == 0, result
        session.commit()
        try:
            yield entity_id
        finally:
            for other in held:
                session.get_one(A.Entity, other).is_on_hold = False
            session.commit()
            _cleanup(session)
            session.commit()
    patch.undo()


def _voucher_id(session: Session, entity_id: int, marker: str) -> int:
    return session.scalar(
        select(A.Voucher.id).where(
            A.Voucher.entity_id == entity_id, A.Voucher.narration.like(f"%[lb-seed:{marker}]%")
        )
    )


def _allocations(session: Session, voucher_id: int) -> list[tuple]:
    rows = session.execute(
        select(A.Ledger.name, A.CostCategory.name, A.CostCentre.name, A.LineCostAllocation.amount)
        .join(A.VoucherLine, A.VoucherLine.id == A.LineCostAllocation.voucher_line_id)
        .join(A.Ledger, A.Ledger.id == A.VoucherLine.ledger_id)
        .join(A.CostCentre, A.CostCentre.id == A.LineCostAllocation.cost_centre_id)
        .outerjoin(A.CostCategory, A.CostCategory.id == A.LineCostAllocation.cost_category_id)
        .where(A.VoucherLine.voucher_id == voucher_id)
        .order_by(A.CostCategory.name, A.CostCentre.name)
    )
    return [(ledger, cat, centre, D(amount)) for ledger, cat, centre, amount in rows]


def test_masters_keep_their_categories_and_hierarchy(synced: int) -> None:
    with Session(get_engine()) as s:
        categories = set(
            s.scalars(select(A.CostCategory.name).where(A.CostCategory.entity_id == synced))
        )
        assert categories == {"Primary Cost Category", "Projects"}
        phase = s.scalar(
            select(A.CostCentre).where(
                A.CostCentre.entity_id == synced, A.CostCentre.name == "Alpha Phase 1"
            )
        )
        parent = s.get_one(A.CostCentre, phase.parent_id)
        category = s.get_one(A.CostCategory, phase.cost_category_id)
        assert (parent.name, category.name) == ("Project Alpha", "Projects")


def test_every_allocation_is_stored_with_its_category_and_the_lines_sign(synced: int) -> None:
    with Session(get_engine()) as s:
        # Two categories on one line, each allocating it in full; debits positive.
        assert _allocations(s, _voucher_id(s, synced, "CC-2")) == [
            ("Electricity", "Primary Cost Category", "Head Office", D("4000")),
            ("Electricity", "Projects", "Alpha Phase 1", D("2500")),
            ("Electricity", "Projects", "Project Alpha", D("1500")),
        ]
        # An item invoice: the allocations under the item's accounting allocation are the
        # Purchases line's.
        assert _allocations(s, _voucher_id(s, synced, "CC-3")) == [
            ("Purchases", "Primary Cost Category", "Branch", D("400")),
            ("Purchases", "Primary Cost Category", "Head Office", D("200")),
        ]


def test_the_reference_and_the_bank_instruments_are_stored(synced: int) -> None:
    with Session(get_engine()) as s:
        purchase = s.get_one(A.Voucher, _voucher_id(s, synced, "CC-3"))
        assert purchase.reference_number == "SUP-INV-4471"

        def bank_line(marker: str) -> tuple:
            return s.execute(
                select(A.VoucherLine.instrument_number, A.VoucherLine.transaction_reference).where(
                    A.VoucherLine.voucher_id == _voucher_id(s, synced, marker),
                    A.VoucherLine.instrument_number.is_not(None),
                )
            ).one()

        assert bank_line("CC-2") == ("000451", None)
        assert bank_line("BANK-1") == ("000452", None)
        assert bank_line("BANK-2") == ("NEFT-2026-0902", "UTR20260902000017")


def test_the_view_has_one_row_per_allocation_for_report_ro(synced: int) -> None:
    with Session(get_engine("report")) as s:
        rows = s.execute(
            text(
                "SELECT cost_category, cost_centre, SUM(amount), COUNT(*) "
                "FROM ledgerbridge_reporting.v_cost_allocations WHERE entity_id = :e "
                "GROUP BY cost_category, cost_centre"
            ),
            {"e": synced},
        ).all()
    found = {(cat, centre): (D(str(total)), count) for cat, centre, total, count in rows}
    assert found == {
        ("Primary Cost Category", "Head Office"): (D("6200"), 3),  # CC-1, CC-2, CC-3
        ("Primary Cost Category", "Branch"): (D("1400"), 2),  # CC-1, CC-3
        ("Projects", "Project Alpha"): (D("1500"), 1),
        ("Projects", "Alpha Phase 1"): (D("2500"), 1),
    }


@pytest.mark.parametrize("on", [date(2026, 8, 31), date(2026, 9, 30)])
def test_cost_centre_totals_match_tallys_own(synced: int, on: date) -> None:
    """Each cost centre's total (with the centres under it) equals Tally's, before and after
    the September vouchers; every line's allocations are within it."""
    with Session(get_engine()) as s:
        validator = Validator(s, synced, on)
        validator._allocations_within_lines()
        validator._cost_centre_totals(_tallys_totals(on))
        assert validator.findings == []
        s.rollback()


def test_a_wrong_allocation_is_found(synced: int) -> None:
    with Session(get_engine()) as s:
        line = s.scalar(
            select(A.LineCostAllocation.id)
            .join(A.CostCentre, A.CostCentre.id == A.LineCostAllocation.cost_centre_id)
            .where(A.CostCentre.entity_id == synced, A.CostCentre.name == "Branch")
            .limit(1)
        )
        s.execute(
            update(A.LineCostAllocation)
            .where(A.LineCostAllocation.id == line)
            .values(amount=A.LineCostAllocation.amount + 5000)
        )
        validator = Validator(s, synced, date(2026, 9, 30))
        validator._allocations_within_lines()
        validator._cost_centre_totals(_tallys_totals(date(2026, 9, 30)))
        codes = sorted(f.check_code for f in validator.findings)
        assert codes == ["cost_allocation_exceeds_line", "cost_centre_mismatch"]
        assert all("Branch" not in f.message for f in validator.findings)  # ids, not names
        s.rollback()


def test_the_source_controls_carry_the_totals() -> None:
    controls = SourceControls(cost_centre_totals={"k": D(1)})
    assert controls.cost_centre_totals == {"k": D(1)}


# --- the API -------------------------------------------------------------------------------


@pytest.fixture
def client(synced: int) -> TestClient:
    from api.main import create_app

    return TestClient(create_app(), base_url="http://localhost")


def _get(client: TestClient, path: str, **params: object) -> dict:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]


def test_the_cost_centres_page_and_its_drill_down(client: TestClient, synced: int) -> None:
    found = _get(client, "/api/v1/cost-centres", month=MONTHS)["centres"]
    by_name = {c["name"]: c for c in found}
    head = by_name["Head Office"]
    assert D(head["total"]) == D("6200") and head["allocations"] == 3
    months = {m["month"]: D(m["amount"]) for m in head["months"]}
    assert months["2026-08-01"] == D("2000") and months["2026-09-01"] == D("4200")
    assert by_name["Alpha Phase 1"]["parent"] == "Project Alpha"
    assert by_name["Alpha Phase 1"]["category"] == "Projects"
    page = _get(client, f"/api/v1/cost-centres/{head['centre_id']}", month=MONTHS)
    assert sum(D(a["amount"]) for a in page["allocations"]) == D("6200")
    assert {a["ledger"] for a in page["allocations"]} == {"Electricity", "Purchases"}
    assert client.get("/api/v1/cost-centres/999999999", params={"month": MONTHS}).status_code == 404


def test_the_explorer_filters_by_cost_centre_and_shows_the_instruments(
    client: TestClient, synced: int
) -> None:
    with Session(get_engine()) as s:
        branch = s.scalar(
            select(A.CostCentre.id).where(
                A.CostCentre.entity_id == synced, A.CostCentre.name == "Branch"
            )
        )
    lines = _get(
        client, "/api/v1/datasets/voucher_lines", cost_centre=branch,
        column=["voucher_number", "ledger"], measure="debit", page_size=500,
    )  # fmt: skip
    assert {r["keys"]["ledger"]["label"] for r in lines["rows"]} == {"Electricity", "Purchases"}
    register = _get(client, "/api/v1/registers/purchases", month="2026-09")["rows"]
    assert {r["reference"] for r in register if r["reference"]} >= {"SUP-INV-4471"}
    payments = _get(
        client, "/api/v1/datasets/voucher_lines", date_from="2026-09-01", date_to="2026-09-30",
        column=["voucher_number", "instrument_number", "transaction_reference"],
        measure="credit", page_size=500,
    )["rows"]  # fmt: skip
    utrs = {r["keys"]["transaction_reference"]["label"] for r in payments}
    assert "UTR20260902000017" in utrs
