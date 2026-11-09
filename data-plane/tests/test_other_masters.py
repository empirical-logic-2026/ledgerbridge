"""Other masters (data completion, part 7), on the seeded test company's recordings of
2026-11-06 (tests/fixtures/tally/rules/data-completion): the budget "FY27 Plan" with two
ledger lines, the stock category "Electronics" on Gizmo, Gizmo's reorder and minimum order
levels and its "Wholesale" price."""

import xml.etree.ElementTree as ET  # noqa: N817
from datetime import date
from decimal import Decimal

from connectors.tally import envelopes, mapping, parser
from core.canonical import CanonicalBudgetLine, CanonicalItem, CanonicalItemPrice
from tests.conftest import FIXTURES

RULES = FIXTURES / "tally" / "rules" / "data-completion"


def _objects(file: str, tag: str) -> list[ET.Element]:
    return parser.objects(parser.parse_response((RULES / file).read_bytes()), tag)


def _items() -> dict[str, CanonicalItem]:
    items = (
        mapping.stock_item(e, parser.source_key(e))
        for e in _objects("stock_items.xml", "STOCKITEM")
    )
    return {i.name: i for i in items}


def test_a_budget_with_its_ledger_lines() -> None:
    (element,) = _objects("budgets.xml", "BUDGET")
    budget = mapping.budget(element, parser.source_key(element))
    assert (budget.name, budget.parent_name, budget.use_actuals) == ("FY27 Plan", None, True)
    period = (date(2026, 4, 1), date(2027, 3, 31))
    assert budget.lines == (
        CanonicalBudgetLine("Electricity", *period, "net_transactions", Decimal(60000)),
        CanonicalBudgetLine("Courier Charges", *period, "net_transactions", Decimal(12000)),
    )


def test_a_stock_category_and_an_items_category() -> None:
    body = (RULES / "stock_categorys.xml").read_bytes()
    (raw,) = parser.parse_records(body, envelopes.STOCK_CATEGORIES, "e")
    (record,) = mapping.to_canonical(raw)
    assert (record.name, record.parent_name) == ("Electronics", None)
    items = _items()
    assert items["Gizmo"].category_name == "Electronics"
    assert items["Widget"].category_name is None  # Tally's "Not Applicable"


def test_an_items_reorder_and_minimum_order_levels() -> None:
    items = _items()
    assert (items["Gizmo"].reorder_level, items["Gizmo"].min_order_quantity) == (
        Decimal(10), Decimal(5)
    )  # fmt: skip
    assert (items["Widget"].reorder_level, items["Widget"].min_order_quantity) == (None, None)


def test_an_items_price_list() -> None:
    items = _items()
    assert items["Gizmo"].prices == (
        CanonicalItemPrice("Wholesale", date(2025, 4, 1), Decimal(35)),
    )
    assert items["Widget"].prices == ()  # an empty price list


def test_quantity_slabs_and_discounts_are_kept() -> None:
    element = ET.fromstring(  # noqa: S314 - a literal
        "<STOCKITEM NAME='X'><GUID>g</GUID><FULLPRICELIST.LIST><DATE>20260401</DATE>"
        "<PRICELEVEL>Retail</PRICELEVEL>"
        "<PRICELEVELLIST.LIST><STARTINGFROM> 1 Nos</STARTINGFROM><ENDINGAT> 10 Nos</ENDINGAT>"
        "<RATE>50.00/Nos</RATE></PRICELEVELLIST.LIST>"
        "<PRICELEVELLIST.LIST><STARTINGFROM> 10 Nos</STARTINGFROM><RATE>45.00/Nos</RATE>"
        "<DISCOUNT> 2</DISCOUNT></PRICELEVELLIST.LIST></FULLPRICELIST.LIST></STOCKITEM>"
    )
    assert mapping.item_prices(element) == (
        CanonicalItemPrice("Retail", date(2026, 4, 1), Decimal(50), Decimal(1), Decimal(10)),
        CanonicalItemPrice("Retail", date(2026, 4, 1), Decimal(45), Decimal(10), None, Decimal(2)),
    )


def test_categories_come_before_items_and_budgets_after_ledgers() -> None:
    specs = envelopes.MASTER_SPECS
    assert specs.index(envelopes.STOCK_CATEGORIES) < specs.index(envelopes.STOCK_ITEMS)
    assert specs.index(envelopes.BUDGETS) > specs.index(envelopes.LEDGERS)
    assert not envelopes.denied_in(envelopes.BUDGETS.fetch)
    assert not envelopes.denied_in(envelopes.STOCK_ITEMS.fetch)
