"""Readable output: the problem registry and its codes, the health report's layout, trends
against the previous validation, root causes before consequences, colours with a plain
fallback, and the error catalogue (core/problems.py, workers/report.py, workers/style.py)."""

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.tally.connector import TallyConnector
from core.models import accounting as A  # noqa: N812
from core.models import system as S  # noqa: N812
from core.problems import BY_CODE, PROBLEMS, for_error, for_key, title
from devtools import error_catalogue
from tests.conftest import COMPANY
from workers import style
from workers.entities import Labels
from workers.report import (
    ATTENTION,
    FAILED,
    OK,
    HealthReport,
    Occurrence,
    Section,
    build,
    cause_line,
    next_step,
    ordered,
    render_markdown,
    render_text,
    trend,
    validation_lines,
    verdict,
)
from workers.validate import run_validation

ROOT = Path(__file__).resolve().parents[2]
CODE = re.compile(r"^LB-(SYNC|TRF|VAL|CON|SYS)-\d{3}$")


# --- the registry -------------------------------------------------------------------------


def test_codes_are_stable_unique_and_well_formed() -> None:
    codes = [p.code for p in PROBLEMS]
    keys = [p.key for p in PROBLEMS]
    assert len(set(codes)) == len(codes) and len(set(keys)) == len(keys)
    assert all(CODE.match(c) for c in codes), codes
    # Codes are never renumbered: a few anchors pin the numbering.
    assert BY_CODE["LB-VAL-006"].key == "year_end_mismatch"
    assert BY_CODE["LB-VAL-004"].key == "closing_mismatch"
    assert BY_CODE["LB-TRF-001"].key == "records_failed"
    assert BY_CODE["LB-SYNC-002"].key == "full_sync_unfinished"
    for p in PROBLEMS:
        assert p.severity in ("error", "warning", "info")
        assert all(c in BY_CODE for c in p.consequence_of), p.code
        assert p.meaning and p.causes and p.investigate and p.fix, p.code


def test_every_validation_check_has_a_plain_name_and_code() -> None:
    """Each check code the validator can store maps to a catalogued problem."""
    source = (ROOT / "data-plane" / "core" / "validation.py").read_text(encoding="utf-8")
    checks = set(re.findall(r'Finding\(\s*"([a-z_]+)"', source))
    checks |= set(re.findall(r'code(?:, object_id)? = "([a-z_]+)"', source))
    for what in re.findall(r'self\._unavailable\("([a-z_]+)"', source):
        checks |= {f"{what}_unavailable", f"{what}_not_supported"}
    assert {"year_end_mismatch", "closing_mismatch", "voucher_unbalanced"} <= checks
    for check in checks:
        assert for_key(check).code != "LB-VAL-099", check


def test_names_and_next_steps_are_plain_safe_commands() -> None:
    commands = set(
        re.search(r"ValidateSet\(([^)]*)\)", (ROOT / "dev.ps1").read_text(encoding="utf-8"))
        .group(1)
        .replace("'", "")
        .replace(" ", "")
        .split(",")
    )
    for p in PROBLEMS:
        command = p.command("pilot")
        assert command.startswith(".\\dev.ps1 ") and "-Env pilot" in command, p.code
        assert command.split()[1] in commands, (p.code, command)
        for text in (p.title, p.meaning, *p.causes, *p.investigate, *p.fix, command):
            assert text.isascii(), (p.code, text)
    assert title("year_end_mismatch") == "Balances at year ends [year_end_mismatch, LB-VAL-006]"
    assert for_key("stock_values_not_compared").code == "LB-VAL-017"  # aliases share one


def test_stored_errors_get_the_code_of_their_type() -> None:
    assert for_error("EntityLookupError: 1 of 2 configured", "LB-SYNC-001").code == "LB-SYNC-006"
    assert for_error("SourceUnresponsiveError: no answer", "LB-SYNC-001").code == "LB-SYNC-005"
    assert for_error("KeyError: x", "LB-SYNC-001").code == "LB-SYNC-001"
    assert for_error(None, "LB-SYNC-003").code == "LB-SYNC-003"


def test_error_catalogue_is_up_to_date() -> None:
    assert error_catalogue.main(["--check"]) == 0, "run python -m devtools.error_catalogue"
    text = (ROOT / "docs" / "error-catalogue.md").read_text(encoding="utf-8")
    for p in PROBLEMS:
        assert f"### {p.code}: {p.title}" in text


# --- trends, verdicts and causes ----------------------------------------------------------


def test_trend_against_the_previous_run() -> None:
    assert trend(5, 8) == "better, was 8"
    assert trend(0, 8) == "fixed, was 8"
    assert trend(9, 8) == "worse, was 8"
    assert trend(8, 8) == "unchanged"
    assert trend(8, None) == "first result"
    assert trend(8, 2, comparable=False).startswith("not compared")


def _occ(code: str, count: int | None = 1, where: str = "entity 1 (company 1)") -> Occurrence:
    return Occurrence(BY_CODE[code], where, count, previous=None)


def test_verdict_is_the_worst_severity_found_now() -> None:
    assert verdict([]) == OK
    assert verdict([_occ("LB-TRF-006", None)]) == OK  # a note
    assert verdict([_occ("LB-SYNC-002", 3)]) == ATTENTION
    assert verdict([_occ("LB-SYNC-002", 3), _occ("LB-VAL-004", 2)]) == FAILED
    assert verdict([_occ("LB-VAL-004", 0)]) == OK  # fixed since the previous run


def test_root_causes_come_first_and_consequences_point_at_them() -> None:
    found = [_occ("LB-VAL-006", 3609), _occ("LB-VAL-004", 602), _occ("LB-TRF-001", 12)]
    assert [g[0].problem.code for g in ordered(found)] == [
        "LB-TRF-001",  # the root cause
        "LB-VAL-004",
        "LB-VAL-006",
    ]
    present = {"LB-TRF-001", "LB-VAL-004", "LB-VAL-006"}
    assert cause_line(BY_CODE["LB-TRF-001"], present).startswith("ROOT CAUSE: 2 other")
    assert cause_line(BY_CODE["LB-VAL-004"], present).startswith(
        "Consequence: likely follows from Records that failed to convert [LB-TRF-001]"
    )
    # Without the root cause present, the problem's own likely causes are given.
    assert cause_line(BY_CODE["LB-VAL-004"], {"LB-VAL-004"}) == BY_CODE["LB-VAL-004"].causes[0]


def _report() -> HealthReport:
    validation = Section(
        "Validation per company",
        lines=["Validation of entity 1 (company 1) as of 2026-10-14: FAILED"],
        occurrences=[
            Occurrence(BY_CODE["LB-VAL-006"], "entity 1 (company 1)", 3609, 3700),
            Occurrence(BY_CODE["LB-VAL-003"], "entity 1 (company 1)", 1, 1),
        ],
    )
    progress = Section(
        "Work in progress",
        lines=["entity 1 (company 1): unfinished full sync; resume: .\\dev.ps1 sync full"],
        occurrences=[Occurrence(BY_CODE["LB-SYNC-002"], "entity 1 (company 1)", 4)],
    )
    from datetime import datetime

    return HealthReport(
        "pilot",
        datetime(2026, 10, 14, 9, 30),
        [Section("Connection", lines=["connection 1"]), progress, validation, Section("Warnings")],
    )


def test_text_report_has_verdict_sections_problems_and_next_steps() -> None:
    text = render_text(_report())
    lines = text.splitlines()
    assert lines[1].startswith("Overall: FAILED  (1 problem(s), 2 warning(s))")
    # The unfinished full sync comes first: its results change the validation (LB-SYNC-002).
    assert lines[2] == r"Next step: .\dev.ps1 sync full -Env pilot"
    assert "== Validation per company: FAILED ==" in text
    assert "== Work in progress: ATTENTION NEEDED ==" in text
    assert "== Warnings: ATTENTION NEEDED ==" in text
    assert "FAILED  Balances at year ends [year_end_mismatch, LB-VAL-006]" in text
    assert "  Where: entity 1 (company 1): 3,609 (better, was 3,700)" in text
    assert "  What this means: Some ledgers' balances at past financial year ends" in text
    assert "  Likely cause: " in text and "  Next step: .\\dev.ps1 validate analyse" in text
    assert "Investigate:" not in text  # -Details only
    assert "More: .\\dev.ps1 report -Env pilot -Details" in text
    detailed = render_text(_report(), details=True)
    assert "  Investigate: .\\dev.ps1 validate analyse -Env pilot shows the first" in detailed
    assert "More:" not in detailed


def test_markdown_report_is_complete_and_plain() -> None:
    md = render_markdown(_report())
    assert md.startswith("# LedgerBridge health report (pilot)\n")
    assert "**Overall: FAILED**" in md and "## Validation per company: FAILED" in md
    assert "- **FAILED  Balances at year ends [year_end_mismatch, LB-VAL-006]**" in md
    assert "  - Next step: `.\\dev.ps1 validate analyse -Env pilot`" in md
    assert "  - Investigate:" in md  # always with details
    assert "\033[" not in md and md.isascii()


# --- colours ------------------------------------------------------------------------------


def test_colours_only_when_asked_and_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LB_COLOR", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert not style.enabled()
    monkeypatch.setenv("LB_COLOR", "1")
    assert style.enabled()
    monkeypatch.setenv("NO_COLOR", "1")
    assert not style.enabled()

    line = "Overall: ATTENTION NEEDED; validation PASSED; stock FAILED (worse, was 2)"
    coloured = style.colorize(line)
    assert f"{style.YELLOW}ATTENTION NEEDED{style.RESET}" in coloured
    assert f"{style.GREEN}PASSED{style.RESET}" in coloured
    assert f"{style.RED}FAILED{style.RESET}" in coloured
    assert f"{style.RED}worse{style.RESET}" in coloured
    assert style.plain(coloured) == line  # the words carry the meaning without colour


def test_jobs_never_colour_what_they_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Background jobs write plain lines to sync_logs; only the printing process colours."""
    import sys

    from workers import cli

    monkeypatch.setenv("LB_COLOR", "1")
    installed = []
    monkeypatch.setattr(style, "install", lambda: installed.append(True))
    monkeypatch.setattr(cli, "_run", lambda session, args: 0)
    monkeypatch.setattr(cli, "_start_job_log", lambda session, args: None)
    monkeypatch.setattr(cli, "get_engine", lambda: None)
    monkeypatch.setattr(cli, "Session", _NoSession)
    cli.main(["transform-retry", "--connection", "c", "--job", "j"])
    assert installed == []
    cli.main(["summary"])
    assert installed == [True]
    assert not isinstance(sys.stdout, style.ColorStream)


class _NoSession:
    def __init__(self, *args: object) -> None:
        pass

    def __enter__(self) -> "_NoSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None


# --- validation compared with the previous run --------------------------------------------


def test_validation_counts_are_compared_with_the_previous_run(
    db: Session, synced: S.Connection, connector: TallyConnector
) -> None:
    labels = Labels(db, synced)
    rent = db.scalars(select(A.Ledger).where(A.Ledger.name == "Rent")).one()
    line = db.scalars(select(A.VoucherLine).where(A.VoucherLine.ledger_id == rent.id)).first()
    line.amount += Decimal("1")
    db.commit()
    (first,) = run_validation(db, synced, connector, [COMPANY])
    run = db.get_one(S.ValidationRun, first.validation_run_id)
    assert run.thorough is False  # no source controls: a quick run
    lines = validation_lines(db, run, "entity 1 (company 1)")
    assert lines[0].startswith("Validation of entity 1 (company 1) as of ")
    assert ": FAILED (" in lines[0]
    assert (
        "  Vouchers that don't balance [voucher_unbalanced, LB-VAL-001]: 1 (first result)" in lines
    )
    assert "  note: Quick validation [source_controls_not_checked, LB-VAL-018]" in lines

    line.amount -= Decimal("1")
    db.commit()
    (second,) = run_validation(db, synced, connector, [COMPANY])
    run = db.get_one(S.ValidationRun, second.validation_run_id)
    lines = validation_lines(db, run, "entity 1 (company 1)")
    assert ": PASSED (" in lines[0]
    assert (
        "  Vouchers that don't balance [voucher_unbalanced, LB-VAL-001]: 0 (fixed, was 1)" in lines
    )

    report = build(db, "test")
    assert report.verdict in (OK, ATTENTION)  # passed; notes or warnings at most
    text = render_text(report, details=True)
    assert labels.for_entity(first.entity_id) in text
    assert COMPANY not in text and COMPANY not in render_markdown(report)
    assert date.today().isoformat() in text


def test_unfinished_work_comes_before_analysis() -> None:
    """Pilot 2026-10-15: with a full sync unfinished and 168,306 records waiting, the next
    step said `validate analyse`. Resuming the sync comes first, then converting."""
    found = [
        _occ("LB-VAL-004", 602),
        _occ("LB-VAL-006", 3609),
        _occ("LB-TRF-002", 168_306, "connection 2"),
        _occ("LB-SYNC-002", 40, "entity 4 (company 2)"),
    ]
    assert next_step(found, "pilot") == r".\dev.ps1 sync full -Env pilot"
    assert [g[0].problem.code for g in ordered(found)][:2] == ["LB-SYNC-002", "LB-TRF-002"]
    present = {"LB-VAL-004", "LB-VAL-006", "LB-TRF-002", "LB-SYNC-002"}
    assert cause_line(BY_CODE["LB-VAL-004"], present).startswith("Consequence:")
    assert "Unfinished full sync [LB-SYNC-002]" in cause_line(BY_CODE["LB-VAL-004"], present)
    assert "Unfinished full sync" in cause_line(BY_CODE["LB-TRF-002"], present)
    # Records waiting with no unfinished sync: convert them before analysing.
    assert next_step(found[:3], "pilot") == r".\dev.ps1 transform retry -Env pilot"
    # A job still running: follow it first (a note, but still the next step).
    running = [*found, Occurrence(BY_CODE["LB-SYNC-007"], "connection 2")]
    assert next_step(running, "pilot") == r".\dev.ps1 sync watch -Env pilot"
    text = render_text(
        HealthReport("pilot", datetime(2026, 10, 15), [Section("X", occurrences=found)])
    )
    assert r"Next step: .\dev.ps1 sync full -Env pilot" in text
