# Profit & Loss sides recording (ADR-056)

Recorded 2026-11-13 from TallyPrime with only LedgerBridge Test Co loaded (Educational mode),
after the seed cases PLS-* (`devtools/tally_seed/data.py`, 31 Oct and 1 Nov 2026):

```
python -m connectors.tally.tools capture-pl-layout --company "LedgerBridge Test Co" \
    --date 2025-12-31 --date 2026-05-31 --date 2026-10-02 --date 2026-10-31 --date 2026-11-02 \
    --year-start 2026-04-01 --dir tests/fixtures/tally/rules/pl_sides/<set>
```

`integrated/` with "Integrate Accounts with Inventory" on, `not_integrated/` with it off.

- `books/`: the company's books at that moment (as `capture-fixtures`).
- `profit_and_loss_<date>.xml|.html|.txt`: Tally's Profit and Loss from the books' beginning,
  in its three export formats. Only the **HTML** export keeps Tally's horizontal layout: the
  first column of the report's table is the left side, the second the right side, with Gross
  Profit/Loss c/o and b/f, Nett Profit/Loss, the subtotal and the Totals. XML and ASCII are the
  same single list (the vertical Cost of Sales form) without sides.
- `fy_*`: the same for the financial year from 1 April 2026.
- `balance_sheet_<date>.xml`, `group_balance_<date>.xml`: Tally's Balance Sheet and its group
  balances for the same period.
