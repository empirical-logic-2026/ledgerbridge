"""The dashboard API's rules that need no database (D1; ADR-049): every /api/v1 endpoint is a
GET behind the access dependency; CORS is limited to localhost; the explorer accepts only
allow-listed keys and turns them into bound SQL; CSV cells can't run as formulas; request
logs carry no query strings."""

import logging
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.dialects import mysql

from api.access import Access, current_access
from api.deps import get_report_session
from api.main import allowed_origins, create_app, exposure_warnings
from api.v1.dataset_query import RequestError, _grouped, _listed, parse_request
from api.v1.dataset_specs import DATASETS
from api.v1.datasets import _safe
from core.config import Settings

LINES = DATASETS["voucher_lines"]


def test_every_v1_endpoint_is_a_get_behind_the_access_dependency() -> None:
    """From the OpenAPI schema: GET only. With access refused, every endpoint refuses: none
    answers without going through `current_access`."""
    app = create_app()
    paths = {p: set(ops) for p, ops in app.openapi()["paths"].items() if p.startswith("/api/v1")}
    assert set(paths) >= {
        "/api/v1/companies", "/api/v1/periods", "/api/v1/datasets",
        "/api/v1/datasets/{name}", "/api/v1/datasets/{name}/csv",
    }  # fmt: skip
    assert all(ops == {"get"} for ops in paths.values()), paths

    def refused() -> Access:
        raise HTTPException(status_code=401, detail="refused")

    app.dependency_overrides[current_access] = refused
    app.dependency_overrides[get_report_session] = lambda: None
    client = TestClient(app)
    for path in paths:
        assert client.get(path.replace("{name}", "voucher_lines")).status_code == 401, path


def test_cors_allows_only_the_dashboard_on_localhost() -> None:
    local = Settings(frontend_origin="http://localhost:5175")
    assert allowed_origins(local) == ["http://localhost:5175", "http://127.0.0.1:5175"]
    assert exposure_warnings(local) == []
    for origin in ("http://192.168.1.20:5175", "https://localhost:5175", "http://example.com"):
        settings = Settings(frontend_origin=origin)
        assert allowed_origins(settings) == []
        assert any("FRONTEND_ORIGIN" in w for w in exposure_warnings(settings))
    exposed = Settings(api_published_address="0.0.0.0")  # noqa: S104 - the case warned about
    assert any("no login yet" in w for w in exposure_warnings(exposed))


def test_cors_preflight_refuses_other_origins_and_methods() -> None:
    client = TestClient(create_app())
    asked = {"Access-Control-Request-Method": "GET"}
    ok = client.options("/api/v1/datasets", headers={"Origin": "http://localhost:5175", **asked})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5175"
    other = client.options("/api/v1/datasets", headers={"Origin": "http://evil.test", **asked})
    assert "access-control-allow-origin" not in other.headers
    post = client.options(
        "/api/v1/datasets",
        headers={"Origin": "http://localhost:5175", "Access-Control-Request-Method": "POST"},
    )
    assert post.status_code == 400


def _parse(*params: tuple[str, str]) -> object:
    return parse_request(LINES, list(params))


def test_defaults_and_a_grouped_request() -> None:
    plain = parse_request(LINES, [])
    assert plain.group_by == [] and plain.columns == list(LINES.default_columns)
    assert plain.measures == ["debit", "credit"] and plain.page_size == 100
    asked = parse_request(LINES, [
        ("group_by", "company"), ("group_by", "month"), ("measure", "net"),
        ("measure", "voucher_count"), ("company", "3"), ("company", "4"),
        ("date_from", "2026-04-01"), ("amount_min", "1000.50"), ("sort", "-net"),
        ("ledger_group", "12"),
    ])  # fmt: skip
    assert asked.group_by == ["company", "month"] and asked.columns == []
    assert asked.filters == {
        "company": [3, 4], "date_from": date(2026, 4, 1), "amount_min": Decimal("1000.50"),
        "ledger_group": [12],
    }  # fmt: skip
    assert (asked.sort, asked.descending) == ("net", True)


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ([("sql", "SELECT 1")], "Unknown parameter 'sql'"),
        ([("order_by", "name")], "Unknown parameter 'order_by'"),
        ([("group_by", "narration")], "can't be grouped by"),
        ([("group_by", "voucher_number")], "can't be grouped by"),  # a list column only
        ([("group_by", "ledger; DROP TABLE x")], "can't be grouped by"),
        ([("column", "amount_fc")], "Unknown column"),
        ([("measure", "SUM(amount)")], "Unknown measure"),
        ([("measure", "net"), ("measure", "net")], "names a key twice"),
        ([("group_by", g) for g in ("company", "month", "quarter", "ledger", "party")],
         "At most 4"),
        ([("sort", "ledger_group")], "Sort by a shown column"),
        ([("company", "3 OR 1=1")], "takes ids"),
        ([("date_from", "yesterday")], "must be a date"),
        ([("date_from", "2026-01-01"), ("date_from", "2026-02-01")], "may be given once"),
        ([("amount_min", "-5")], "0 or more"),
        ([("amount_max", "NaN")], "0 or more"),
        ([("amount_max", "1e999999")], "0 or more"),
        ([("page_size", "501")], "page_size"),
        ([("page", "0")], "page"),
    ],
)  # fmt: skip
def test_anything_outside_the_allow_lists_is_refused(
    params: list[tuple[str, str]], message: str
) -> None:
    with pytest.raises(RequestError, match=message.replace("(", r"\(")):
        parse_request(LINES, params)


def test_the_vouchers_dataset_has_its_own_allow_list() -> None:
    vouchers = DATASETS["vouchers"]
    with pytest.raises(RequestError, match="Unknown parameter 'ledger'"):
        parse_request(vouchers, [("ledger", "5")])
    assert parse_request(vouchers, [("group_by", "party")]).measures == ["amount"]


def test_requests_become_bound_sql_without_request_text() -> None:
    asked = parse_request(LINES, [
        ("group_by", "ledger_group"), ("group_by", "month"), ("measure", "debit"),
        ("company", "7"), ("date_to", "2026-09-30"), ("sort", "-debit"),
    ])  # fmt: skip
    for statement in (_grouped(LINES, asked, _conditions(asked)), _listed(LINES, asked, [])):
        sql = str(statement.compile(dialect=mysql.dialect()))
        assert "2026-09-30" not in sql and "%s" in sql  # values are bound parameters
    grouped = str(_grouped(LINES, asked, _conditions(asked)).compile(dialect=mysql.dialect()))
    assert "GROUP BY" in grouped and "ORDER BY" in grouped


def _conditions(asked: object) -> list[object]:
    from api.v1.dataset_query import _conditions as conditions

    return conditions(LINES, asked, [7])


def test_csv_cells_cannot_run_as_formulas() -> None:
    assert _safe("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert _safe("+91 cash") == "'+91 cash"
    assert _safe("@sum") == "'@sum"
    assert _safe("Rent") == "Rent"


@pytest.fixture
def client_without_db() -> Iterator[TestClient]:
    """The app with access to companies 3 and 4 and no database (requests refused before
    any query)."""
    app = create_app()
    app.dependency_overrides[current_access] = lambda: Access(frozenset({3, 4}))
    app.dependency_overrides[get_report_session] = lambda: None
    yield TestClient(app)


def test_refusals_over_http(client_without_db: TestClient) -> None:
    bad = client_without_db.get("/api/v1/datasets/voucher_lines?select=*")
    assert bad.status_code == 422 and bad.json()["detail"] == "Unknown parameter 'select'."
    assert client_without_db.get("/api/v1/datasets/users").status_code == 404
    other = client_without_db.get("/api/v1/datasets/voucher_lines?company=9")
    assert other.status_code == 404 and other.json()["detail"] == "Company not found."
    assert client_without_db.post("/api/v1/datasets/voucher_lines").status_code == 405


def test_the_catalogue_lists_only_allow_listed_keys(client_without_db: TestClient) -> None:
    catalogue = {d["key"]: d for d in client_without_db.get("/api/v1/datasets").json()}
    assert set(catalogue) == {"voucher_lines", "vouchers"}
    lines = catalogue["voucher_lines"]
    assert {d["key"] for d in lines["dimensions"]} == set(LINES.dimensions)
    assert {m["key"] for m in lines["measures"]} == {"debit", "credit", "net", "voucher_count"}


def test_request_logs_have_no_query_strings(
    client_without_db: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="uvicorn.error.ledgerbridge"):
        client_without_db.get("/api/v1/datasets/voucher_lines?amount_min=123456.78&sort=xx")
    lines = [r.getMessage() for r in caplog.records if r.name == "uvicorn.error.ledgerbridge"]
    assert lines and lines[-1].startswith("GET /api/v1/datasets/voucher_lines 422 ")
    assert all("123456" not in line and "amount_min" not in line for line in lines)
