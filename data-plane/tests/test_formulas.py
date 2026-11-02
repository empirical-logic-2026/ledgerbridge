"""Every figure the dashboard shows has a formula in docs/formulas.md (RPT-015).

Walks the response models of every `/api/v1` module: each field holding a number (an amount,
percentage, ratio, days or a count, also in lists and dicts) must carry a formula ID
(`api.v1.common.formula`), and so must each field holding a `Comparable` (whose `value` and
`before` follow it). Identifiers and paging numbers are exempt, by name. Every ID used must
have its section in docs/formulas.md, and every ID there must be used somewhere in the code
(the data plane or the frontend), so the sheet and the code can't drift apart.
"""

import importlib
import inspect
import pkgutil
import re
import typing
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

import api.v1
from api.v1.common import Comparable

ROOT = Path(__file__).resolve().parents[2]
SHEET = ROOT / "docs" / "formulas.md"
ID = re.compile(r"F-[A-Z]{2,3}-\d{3}")
# Numbers that aren't figures: identifiers, source settings shown as they are, paging.
NOT_FIGURES = {
    "id", "company", "companies", "fy_start_month", "start_year", "credit_days",
    "page", "page_size", "total_rows", "level",
}  # fmt: skip


def _models() -> list[type[BaseModel]]:
    found = []
    for info in pkgutil.iter_modules(api.v1.__path__):
        module = importlib.import_module(f"api.v1.{info.name}")
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, BaseModel) and cls.__module__ == module.__name__:
                found.append(cls)
    return found


def _holds(annotation: object, test: typing.Callable[[object], bool]) -> bool:
    args = typing.get_args(annotation)
    if args:
        return any(_holds(a, test) for a in args)
    return test(annotation)


def _is_number(t: object) -> bool:
    return t in (int, float, Decimal)


def _is_comparable(t: object) -> bool:
    return isinstance(t, type) and issubclass(t, Comparable)


def _formula(model: type[BaseModel], name: str) -> str | None:
    extra = model.model_fields[name].json_schema_extra
    return extra.get("formula") if isinstance(extra, dict) else None  # type: ignore[return-value]


def _figure_fields() -> list[tuple[str, str | None]]:
    """(model.field, formula ID or None) for every field that must have one."""
    fields = []
    for model in _models():
        for name, info in model.model_fields.items():
            if name in NOT_FIGURES or name.endswith("_id"):
                continue
            if issubclass(model, Comparable) and name in ("value", "before"):
                continue  # these follow the field holding the figure
            if _holds(info.annotation, _is_number) or _holds(info.annotation, _is_comparable):
                fields.append((f"{model.__name__}.{name}", _formula(model, name)))
    return fields


def _sheet_ids() -> set[str]:
    """The IDs with an entry (a heading) in the formula sheet."""
    return set(re.findall(r"^#{2,4} (F-[A-Z]{2,3}-\d{3})\b", SHEET.read_text("utf-8"), re.M))


def _code_ids() -> set[str]:
    sources = [
        *(ROOT / "data-plane").glob("**/*.py"),
        *(ROOT / "frontend" / "src").glob("**/*.ts*"),
    ]
    found: set[str] = set()
    for path in sources:
        if ".venv" not in path.parts and "node_modules" not in path.parts:
            found |= set(ID.findall(path.read_text("utf-8")))
    return found


def test_every_figure_has_a_formula() -> None:
    missing = [field for field, formula in _figure_fields() if formula is None]
    assert not missing, f"figures without a formula ID (api.v1.common.formula): {missing}"


def test_every_formula_used_is_in_the_sheet() -> None:
    unknown = {f"{field}: {formula}" for field, formula in _figure_fields() if formula} - {
        f"{field}: {formula}" for field, formula in _figure_fields() if formula in _sheet_ids()
    }
    assert not unknown, f"formula IDs with no entry in docs/formulas.md: {sorted(unknown)}"


def test_every_formula_in_the_sheet_is_used_in_the_code() -> None:
    unused = _sheet_ids() - _code_ids()
    assert not unused, f"formulas in docs/formulas.md that no code refers to: {sorted(unused)}"


def test_a_formula_id_is_unique_in_the_sheet() -> None:
    headings = re.findall(r"^#{2,4} (F-[A-Z]{2,3}-\d{3})\b", SHEET.read_text("utf-8"), re.M)
    assert len(headings) == len(set(headings))


def test_the_check_finds_a_figure_without_a_formula() -> None:
    class Untagged(BaseModel):
        amount: Decimal

    assert _holds(Untagged.model_fields["amount"].annotation, _is_number)
    assert _formula(Untagged, "amount") is None
