"""Every field of every Tally object type in the full test-company export
(devtools/tally_full_export.py), with how often the test company fills it and what the
connector does with it. Writes docs/data-completeness-fields.md (a test fails when it is
stale) and checks that the export is complete. Development only.

    python -m devtools.tally_field_inventory [--check]

A field's status comes from the code, not by hand:

- **column**: the mapping reads it (`mapping.USED_FIELDS`): stored as a column or used to
  derive one (e.g. a ledger's tax type from its GST duty head);
- **extra**: fetched (in the collection's field list, or the collection is read whole) but not
  read by the mapping: kept in the object's `extra` JSON when it has a value;
- **not fetched**: the connector never asks Tally for it; it is not in the raw records either.
- **raw only**: Tally sends it (as an attribute) without being asked; it stays in the raw
  record, not in `extra`.

Fields are paths below the object, list levels included, as `USED_FIELDS` writes them:
`ALLLEDGERENTRIES.LIST/BANKALLOCATIONS.LIST/UNIQUEREFERENCENUMBER`.
"""

import argparse
import gzip
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from connectors.tally import envelopes, parser
from connectors.tally.mapping import USED_FIELDS
from devtools.tally_full_export import DEFAULT_OUT

# Values Tally's own export writes for a field nobody set (a collection leaves them out;
# "Not Applicable" comes with a control character the parser removes).
DEFAULTS = frozenset(("No", "0", "Not Applicable"))
RESERVEDNAME_READ = frozenset(("group", "voucher_type"))
DOC = Path(__file__).resolve().parents[2] / "docs" / "data-completeness-fields.md"

# Tally's tag of each object type the connector fetches, and the collection it uses.
# Every collection the connector fetches, per object tag (a ledger's opening bills are
# fetched as LEDGER too); the first is the type's own.
SPECS: dict[str, list[envelopes.CollectionSpec]] = {}
for _spec in (envelopes.COMPANIES, *envelopes.MASTER_SPECS, envelopes.VOUCHERS):
    SPECS.setdefault(_spec.object_tag, []).append(_spec)
FETCHED: dict[str, envelopes.CollectionSpec] = {tag: specs[0] for tag, specs in SPECS.items()}
# Where each type is in the recording.
SOURCES = {"COMPANY": "company.xml", "VOUCHER": "vouchers.xml"}  # the rest: masters.xml


@dataclass
class TypeFields:
    tag: str
    objects: int
    filled: Counter[str]  # path -> objects that set it (a value other than empty, No or 0)
    paths: set[str]  # every path exported, set or not
    attributes: set[str]  # the object's attributes (NAME, RESERVEDNAME, VCHTYPE, ...)


def read(directory: Path, name: str) -> bytes:
    plain = directory / name
    if plain.exists():
        return plain.read_bytes()
    return gzip.decompress((directory / f"{name}.gz").read_bytes())


def top_objects(body: bytes) -> list[ET.Element]:
    root = parser.parse_response(body)
    holders = (*root.iter("TALLYMESSAGE"), *root.iter("COLLECTION"))
    return [child for holder in holders for child in holder if len(child)]


def leaf_paths(element: ET.Element, prefix: str = "") -> Iterable[tuple[str, str]]:
    """Every field below the object, with its value ("" when empty). Attributes count as
    fields: Tally's own export writes a master's NAME as one (<LEDGER NAME="...">), a
    collection export as an element."""
    for name, value in element.attrib.items():
        if name != "ACTION":  # Tally's import instruction, not a field
            yield (f"{prefix}/{name}" if prefix else name), value.strip()
    for child in element:
        tag = parser.restore_name(child.tag)
        path = f"{prefix}/{tag}" if prefix else tag
        if len(child):
            yield from leaf_paths(child, path)
        else:
            yield path, (child.text or "").strip()


def inventory(directory: Path) -> dict[str, TypeFields]:
    found: dict[str, TypeFields] = {}
    for name in ("company.xml", "masters.xml", "vouchers.xml"):
        for element in top_objects(read(directory, name)):
            if name == "masters.xml" and element.tag in SOURCES:
                continue
            fields = found.setdefault(
                element.tag, TypeFields(element.tag, 0, Counter(), set(), set())
            )
            fields.objects += 1
            fields.attributes.update(a for a in element.attrib if a != "ACTION")
            seen: set[str] = set()
            for path, value in leaf_paths(element):
                fields.paths.add(path)
                if value and value not in DEFAULTS and path not in seen:
                    seen.add(path)
                    fields.filled[path] += 1
    return dict(sorted(found.items()))


def fetch_paths(spec: envelopes.CollectionSpec) -> set[str]:
    """A collection's field list as paths (AllLedgerEntries.Amount becomes
    ALLLEDGERENTRIES.LIST/AMOUNT)."""
    paths = set()
    for field in spec.fetch:
        parts = field.upper().split(".")
        paths.add("/".join([*(f"{p}.LIST" for p in parts[:-1]), parts[-1]]))
    return paths


def status(tag: str, path: str, attribute: bool = False) -> str:
    specs = SPECS.get(tag, [])
    if not specs:
        return "not fetched"
    if any(path in USED_FIELDS.get(spec.object_type, frozenset()) for spec in specs):
        return "column"
    if path == "RESERVEDNAME" and specs[0].object_type in RESERVEDNAME_READ:
        return "column"  # mapping._reserved: a group's role, a voucher type's base type
    if attribute:
        # Tally sends an object's attributes with every collection, asked for or not.
        return "raw only"
    if any(spec.native or path in fetch_paths(spec) for spec in specs):
        return "extra"
    return "not fetched"


def _alias(path: str) -> str:
    """Tally's own export writes an invoice's ledger entries as LEDGERENTRIES, the
    collection as ALLLEDGERENTRIES: the same entries."""
    return "ALL" + path if path.startswith("LEDGERENTRIES.LIST") else path


def _values(element: ET.Element, prefix: str = "") -> Iterable[tuple[str, str]]:
    for child in element:
        path = f"{prefix}/{child.tag}" if prefix else child.tag
        if len(child):
            yield from _values(child, path)
        elif (child.text or "").strip():
            yield _alias(path), (child.text or "").strip()


def completeness_problems(directory: Path) -> list[str]:
    """What would show the export is incomplete: a voucher field Tally's own Day Book export
    fills with something other than a default that the recorded vouchers don't fill."""
    problems = []
    recorded = {parser.source_key(v): v for v in top_objects(read(directory, "vouchers.xml"))}
    for voucher in top_objects(read(directory, "daybook.xml")):
        ours = recorded.get(parser.source_key(voucher))
        if ours is None:
            problems.append("a Day Book voucher is missing from vouchers.xml")
            continue
        have = {path for path, _ in _values(ours)}
        problems += sorted(
            {f"VOUCHER {path}: filled in the Day Book only"
             for path, value in _values(voucher) if path not in have and value not in DEFAULTS}
        )  # fmt: skip
    return problems


def computed_on_request(tag: str, fields: TypeFields) -> list[str]:
    """Fields the connector asks for that aren't part of the object Tally exports: Tally
    works them out when asked by name (e.g. MASTERID, a ledger's COUNTRYNAME)."""
    spec = FETCHED.get(tag)
    if spec is None or spec.native:
        return []
    return sorted(fetch_paths(spec) - fields.paths)


def markdown(fields: dict[str, TypeFields]) -> str:
    lines = [
        "<!-- Generated by `python -m devtools.tally_field_inventory` from the full export in",
        "data-plane/tests/fixtures/tally/full-export/. Do not edit by hand. -->",
        "",
        "# Tally fields, every one (generated)",
        "",
        "Every field of every object type in the full export of LedgerBridge Test Co, with how",
        "many of the type's objects set it (a value other than empty, No or 0) and what the",
        "connector does with it (column / extra / not fetched; see",
        "`devtools/tally_field_inventory.py`). Meanings and recommendations:",
        "[data-completeness.md](data-completeness.md).",
        "",
    ]
    for tag, f in fields.items():
        spec = FETCHED.get(tag)
        how = f"fetched as `{spec.object_type}`" if spec else "**not fetched**"
        filled = [p for p in sorted(f.paths) if f.filled[p]]
        empty = [p for p in sorted(f.paths) if not f.filled[p]]
        lines += [
            f"## {tag}",
            "",
            f"{f.objects} objects; {how}; {len(f.paths)} fields, "
            f"{len(filled)} set in the test company.",
            "",
            "| Field | Set in | Status |",
            "| --- | --- | --- |",
            *(
                f"| `{p}` | {f.filled[p]} of {f.objects} | {status(tag, p, p in f.attributes)} |"
                for p in filled
            ),
            "",
        ]
        if empty:
            by_status: dict[str, list[str]] = {}
            for p in empty:
                by_status.setdefault(status(tag, p, p in f.attributes), []).append(f"`{p}`")
            lines.append("Empty, No or 0 in every object of the test company:")
            lines.append("")
            for state, paths in sorted(by_status.items()):
                lines.append(f"- {state} ({len(paths)}): {', '.join(paths)}")
            lines.append("")
        computed = computed_on_request(tag, f)
        if computed:
            names = ", ".join(f"`{p}`" for p in computed)
            lines += [f"Fetched by the connector but not part of the exported object (Tally works "
                      f"them out when asked by name): {names}.", ""]  # fmt: skip
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = argparse.ArgumentParser(prog="python -m devtools.tally_field_inventory")
    args.add_argument("--recording", type=Path, default=DEFAULT_OUT)
    args.add_argument("--check", action="store_true", help="only check the export is complete")
    options = args.parse_args(argv)
    fields = inventory(options.recording)
    problems = completeness_problems(options.recording)
    for problem in problems:
        print(f"  {problem}")
    print(f"{len(fields)} object types; {len(problems)} completeness problems")
    if not options.check:
        DOC.write_text(markdown(fields) + "\n", "utf-8")
        print(f"Wrote {DOC.relative_to(DOC.parents[1])}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
