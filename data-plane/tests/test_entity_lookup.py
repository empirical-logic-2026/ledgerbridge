"""Company names like the pilot's (2026-10-12), and how commands find the companies.

The pilot companies' names contain patterns the test company lacks: a hyphen right after a
word ("Limited- New - (from 1-Apr-23)"), a space then a hyphen ("Ltd -(from 1-Apr-20)"),
parentheses and dots; here also double and trailing spaces. `connect` found both, yet
sync, the deletion check and validation then failed with "2 requested entities are not
available in the source".

`TallyLikeTransport` serves the recorded test company under such a name and behaves like
Tally where it matters: a request's SVCURRENTCOMPANY must match a loaded company's name
exactly, or Tally answers "Could not set 'SVCurrentCompany'". With `rename_after_select`
it also models the symptom seen: Tally reporting the name differently after the company
has been selected by a request.
"""

import copy
import re
import xml.etree.ElementTree as ET  # noqa: N817
from collections.abc import Callable
from xml.sax.saxutils import escape, unescape

import httpx
import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from connectors.tally import parser
from connectors.tally.connector import TallyConnector
from connectors.tally.fixtures import DEFAULT_DIR, FixtureTransport
from core.config import Settings
from core.models import system as S  # noqa: N812
from workers import cli

ALPHA = "Alpha Traders Limited- New - (from 1-Apr-23)"  # the recorded company's data
BETA = "Beta  Exports Pvt. Ltd -(from 1-Apr-20) "  # double and trailing space; no data
_CURRENT = re.compile(r"<SVCURRENTCOMPANY>(.*?)</SVCURRENTCOMPANY>", re.S)


class TallyLikeTransport(FixtureTransport):
    def __init__(self, rename_after_select: Callable[[str], str] | None = None) -> None:
        super().__init__(DEFAULT_DIR)
        self.names = [ALPHA, BETA]
        self.rename = rename_after_select
        self.selected: list[str] = []
        root = parser.parse_response((DEFAULT_DIR / "companies.xml").read_bytes())
        self.template = parser.objects(root, "COMPANY")[0]
        self.guids = [self.template.findtext("GUID").strip(), "beta-company-guid"]

    def _companies(self) -> bytes:
        companies = []
        for name, guid in zip(self.names, self.guids, strict=True):
            company = copy.deepcopy(self.template)
            company.set("NAME", name)
            company.find("NAME").text = name
            company.find("GUID").text = guid
            companies.append(ET.tostring(company, encoding="unicode"))
        return f"<ENVELOPE><COLLECTION>{''.join(companies)}</COLLECTION></ENVELOPE>".encode()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        current = _CURRENT.search(body)
        if current is None:  # the company list
            return httpx.Response(200, content=self._companies())
        name = unescape(current.group(1))
        if name not in self.names:
            error = f"Could not set 'SVCurrentCompany' to '{escape(name)}'"
            return httpx.Response(
                200, content=f"<ENVELOPE><LINEERROR>{error}</LINEERROR></ENVELOPE>".encode()
            )
        self.selected.append(name)
        if self.rename is not None:
            self.names = [self.rename(n) for n in self.names]
        if name != self.names[0] and name != ALPHA:  # Beta has no recorded data
            return httpx.Response(200, content=b"<ENVELOPE><COLLECTION/></ENVELOPE>")
        return super().handle_request(request)


@pytest.fixture
def pilot_cli(engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch, capsys):  # noqa: ANN001, ANN201
    """Runs workers.cli in the pilot environment against a TallyLikeTransport."""
    state: dict[str, TallyConnector] = {}
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr(cli, "connector_for", lambda session, connection: state["connector"])
    monkeypatch.setattr(cli.registry, "create_connector", lambda code, cfg: state["connector"])
    monkeypatch.setattr(
        "connectors.registry.default_config", lambda code: {"url": "http://tally.test:9000"}
    )
    settings = Settings(app_env="pilot", ai_provider="ollama")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    def use(transport: TallyLikeTransport) -> None:
        state["connector"] = TallyConnector.from_config(
            {"url": "http://tally.test:9000"}, transport=transport
        )

    def run(*argv: str) -> tuple[int, str]:
        code = cli.main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out + captured.err

    run.use = use  # type: ignore[attr-defined]
    return run


def _connect_sync_validate(pilot_cli) -> tuple[str, str, str]:  # noqa: ANN001
    code, connected = pilot_cli("connect", "--connection", "tally-pilot", "--source", "tally",
                                "--origin", "backup", "--entity", ALPHA)  # fmt: skip
    assert code == 0, connected
    assert "1 entities configured, 1 found in the source" in connected
    code, synced = pilot_cli("sync", "--connection", "tally-pilot", "--full", "--check-deletions")
    _, validated = pilot_cli("validate", "--connection", "tally-pilot")
    return connected, synced, validated


def test_pattern_names_sync_and_validate(pilot_cli) -> None:  # noqa: ANN001
    pilot_cli.use(TallyLikeTransport())
    _, synced, validated = _connect_sync_validate(pilot_cli)
    assert "(full): succeeded" in synced and "(deletion_check): succeeded" in synced
    assert "PASSED" in validated, validated


@pytest.mark.parametrize(
    "rename",
    [
        pytest.param(lambda n: n.replace(" (from 1-Apr-23)", ""), id="suffix-dropped"),
        pytest.param(lambda n: n.replace("- ", " - ", 1), id="space-added-before-hyphen"),
        pytest.param(lambda n: n.replace(" (from", "  (from"), id="space-added-before-paren"),
    ],
)
def test_name_reported_differently_after_selection(pilot_cli, rename) -> None:  # noqa: ANN001
    """The pilot symptom: connect finds the company, later lookups by name don't."""
    transport = TallyLikeTransport(rename_after_select=rename)
    pilot_cli.use(transport)
    _, synced, validated = _connect_sync_validate(pilot_cli)
    assert "not available in the source" not in synced + validated
    assert "(full): succeeded" in synced and "(deletion_check): succeeded" in synced
    assert "PASSED" in validated, validated


def test_exact_name_with_trailing_and_double_spaces(pilot_cli, db: Session) -> None:  # noqa: ANN001
    """A name is used exactly as Tally reports it: trailing and double spaces included."""
    transport = TallyLikeTransport()
    transport.names = [BETA, ALPHA]  # the recorded data now sits under the awkward name
    transport.guids.reverse()
    pilot_cli.use(transport)
    code, out = pilot_cli("connect", "--connection", "tally-pilot", "--source", "tally",
                          "--origin", "backup", "--entity", BETA)  # fmt: skip
    assert code == 0 and "1 found in the source" in out, out
    code, synced = pilot_cli("sync", "--connection", "tally-pilot", "--full", "--no-validate")
    assert code == 0 and "(full): succeeded" in synced, synced
    assert BETA in transport.selected and BETA.strip() not in transport.selected
    (connection,) = db.scalars(select(S.Connection)).all()
    assert connection.config["origin"] == "backup"


# --- connect stores keys; --all --------------------------------------------------------


def test_connect_stores_keys_and_all_takes_every_loaded_company(pilot_cli, db: Session) -> None:  # noqa: ANN001
    transport = TallyLikeTransport()
    pilot_cli.use(transport)
    code, out = pilot_cli("connect", "--connection", "tally-pilot", "--source", "tally",
                          "--origin", "backup", "--all")  # fmt: skip
    assert code == 0 and "2 entities configured, 2 found in the source (2 loaded there)" in out
    (connection,) = db.scalars(select(S.Connection)).all()
    db.refresh(connection)
    assert connection.config["entities"] == [
        {"key": transport.guids[0], "name": ALPHA},
        {"key": transport.guids[1], "name": BETA},
    ]
    assert ALPHA not in out and BETA.strip() not in out


def test_connector_retries_with_the_current_name_after_a_rename() -> None:
    transport = TallyLikeTransport(rename_after_select=lambda n: n.replace("- ", " - ", 1))
    connector = TallyConnector.from_config({"url": "http://tally.test:9000"}, transport=transport)
    alpha = connector.list_entities()[0]
    records = list(connector.fetch_masters(alpha))
    assert records
    renamed = ALPHA.replace("- ", " - ", 1)
    assert transport.selected[0] == ALPHA and renamed in transport.selected


# --- 3: validation failing never fails the sync ---------------------------------------


def test_failed_validation_is_not_a_failed_sync(
    pilot_cli,  # noqa: ANN001
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from workers import validate
    from workers.entities import EntityLookupError

    pilot_cli.use(TallyLikeTransport())
    pilot_cli("connect", "--connection", "tally-pilot", "--source", "tally",
              "--origin", "backup", "--entity", ALPHA)  # fmt: skip

    def unavailable(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise EntityLookupError(2, 2)

    monkeypatch.setattr(validate, "run_validation", unavailable)
    code, out = pilot_cli("sync", "--connection", "tally-pilot", "--full", "--check-deletions")
    assert code == 1
    assert "Result: full succeeded; deletion_check succeeded; validation failed" in out
    assert "Validation couldn't run: EntityLookupError" in out
    runs = db.scalars(select(S.SyncRun).order_by(S.SyncRun.id)).all()
    assert [(r.run_type, r.status) for r in runs] == [
        ("full", "succeeded"),
        ("deletion_check", "succeeded"),
    ]
    open_alerts = db.scalars(select(S.Alert).where(S.Alert.resolved_at.is_(None))).all()
    assert {a.kind for a in open_alerts} == {"validation_failed"}


# --- 4: progress and a final result ---------------------------------------------------


def test_sync_prints_progress_and_a_result(pilot_cli) -> None:  # noqa: ANN001
    pilot_cli.use(TallyLikeTransport())
    pilot_cli("connect", "--connection", "tally-pilot", "--source", "tally",
              "--origin", "backup", "--entity", ALPHA)  # fmt: skip
    _, out = pilot_cli("sync", "--connection", "tally-pilot", "--full", "--check-deletions")
    new, known = "company 1 (no entity yet)", "entity 1 (company 1)"
    steps = [
        f"1 companies in this run: {new}",
        f"{new}: fetching (full)",
        f"{new}: ledger: 21 received, 21 stored, 0 unchanged (chunk 3 of",
        f"{new}: voucher 2026-04-01..2026-04-30:",
        f"{new}: fetched ",
        f"{new}: transforming into the accounting tables",
        f"{new} is now {known}",
        f"{known}: transformed ",
        f"{known}: validating as of",  # right after its transform
        f"{known}: checking for deletions",
        f"{known}: SUCCEEDED: fetched",
        f"Validation run 1 of {known} as of",
        "Result: full succeeded; deletion_check succeeded; validation passed",
    ]
    positions = [out.index(step) for step in steps]
    assert positions == sorted(positions), out
    assert re.search(rf"^\[\d\d:\d\d:\d\d\] {re.escape(new)}: fetching", out, re.M)
    assert ALPHA not in out


# --- 5: status of a paused connection ---------------------------------------------------


def test_status_of_a_paused_connection_shows_paused(pilot_cli) -> None:  # noqa: ANN001
    pilot_cli.use(TallyLikeTransport())
    pilot_cli("connect", "--connection", "tally-pilot", "--source", "tally",
              "--origin", "backup", "--entity", ALPHA)  # fmt: skip
    _, before = pilot_cli("status")
    assert "next: none (paused)" in before
    pilot_cli("sync", "--connection", "tally-pilot", "--full", "--check-deletions")
    _, after = pilot_cli("status")
    assert "next: none, the connection is paused (no scheduled runs)" in after
    assert "next: in about" not in after and "due now" not in after


# --- 6: entity-check ------------------------------------------------------------------


def test_entity_check_explains_a_name_mismatch_without_names(pilot_cli, db: Session) -> None:  # noqa: ANN001
    pilot_cli.use(TallyLikeTransport())
    pilot_cli("connect", "--connection", "tally-pilot", "--source", "tally",
              "--origin", "backup", "--all")  # fmt: skip
    # As the first pilot attempt stored them: plain names, typed slightly differently.
    (connection,) = db.scalars(select(S.Connection)).all()
    connection.config = {
        **connection.config,
        "entities": [ALPHA.replace("- New", " - New"), BETA.strip()],
    }
    db.commit()
    code, out = pilot_cli("entity-check", "--connection", "tally-pilot", "--no-probe")
    assert code == 1
    assert "Source: 2 entities loaded" in out
    assert "starts or ends with a space; repeated spaces" in out  # Beta's own features
    legacy = "(by name only (stored before keys were)): NOT FOUND; "
    assert f"entity 1 {legacy}source entity 1 differs only by: spacing around hyphens" in out
    assert f"entity 2 {legacy}source entity 2 differs only by: leading/trailing spaces" in out
    assert "Result: 2 problem(s) found" in out
    for name in (ALPHA, BETA.strip(), "Alpha", "Beta"):
        assert name not in out


def test_entity_check_selection_probe_reports_renames(pilot_cli) -> None:  # noqa: ANN001
    pilot_cli.use(TallyLikeTransport(rename_after_select=lambda n: n.replace("- ", " - ", 1)))
    pilot_cli("connect", "--connection", "tally-pilot", "--source", "tally",
              "--origin", "backup", "--all")  # fmt: skip
    code, out = pilot_cli("entity-check", "--connection", "tally-pilot")
    assert code == 1
    assert "source entity 1: selected" in out
    assert "afterwards source entity 1 differs by: spacing around hyphens" in out
    assert "Alpha" not in out


def test_entity_check_all_good(pilot_cli) -> None:  # noqa: ANN001
    pilot_cli.use(TallyLikeTransport())
    pilot_cli("connect", "--connection", "tally-pilot", "--source", "tally",
              "--origin", "backup", "--all")  # fmt: skip
    code, out = pilot_cli("entity-check", "--connection", "tally-pilot")
    assert code == 0, out
    assert out.count("FOUND as source entity") == 2 and "names unchanged" in out
    assert "Result: no problems found" in out
