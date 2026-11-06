# Full export of LedgerBridge Test Co (2026-11-06)

Everything TallyPrime has for the test company (synthetic test data only), not the connector's
field list. Recorded by `python -m devtools.tally_full_export` (APP_ENV=test, only the test
company loaded); read by `python -m devtools.tally_field_inventory`, which writes
`docs/data-completeness-fields.md`. Nothing replays it: it is not in `../manifest.json`.

| File | What Tally was asked for | Objects |
| --- | --- | --- |
| `company.xml` | The Company collection, each object whole (`NATIVEMETHOD *`) | 1 company |
| `masters.xml.gz` | Tally's own export of every master ("List of Accounts", all masters) | 242 masters of 15 types |
| `daybook.xml` | Tally's own Day Book export (it exports Tally's current date only: 2-Oct-2026) | 9 vouchers |
| `vouchers.xml.gz` | The Voucher collection, 1-Apr-2025 to 31-Mar-2027: `NATIVEMETHOD *` and `<list>.*` for every sub-list (found in rounds) | 85 vouchers |
| `export.json` | Counts by object type, sizes, the period and the rounds | |

TallyPrime ran in Educational mode. Files over 2 MB, or holding Tally's control-character
markers (e.g. U+0005), are stored gzip-compressed. Before it was
committed, the recording was searched for personal or licence data (user, machine, email,
licence serial, addresses): none.
