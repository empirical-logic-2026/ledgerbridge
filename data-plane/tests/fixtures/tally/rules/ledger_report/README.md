# Ledger report recording (ADR-055)

Recorded 2026-11-12 from TallyPrime with only LedgerBridge Test Co loaded (Educational mode):

```
python -m connectors.tally.tools capture-ledger-report --company "LedgerBridge Test Co" \
    --ledger "Test Bank Current A/c" --ledger "Customer Alpha Traders" --ledger "Sales - Goods" \
    --from 2026-04-01 --to 2026-10-02
```

- `books/`: the company's books at that moment (as `capture-fixtures`), loaded by the test.
- `<ledger>_vouchers_<month>.xml`: Tally's ledger-voucher collection, month by month. The part
  month (1-2 October) is empty: in Educational mode Tally can't end a request on the 3rd.
- `<ledger>_report_<to>.xml`: Tally's Ledger Vouchers report for the months it can be read for
  (To date on the 1st, 2nd or 31st). Its export lists one month: the To date's, or, when the
  ledger has no entries in it, its last month with entries (the bank's "to 2 October" lists
  September).
- `ledger_balances.xml`: every ledger's opening and closing balance for the period.

Used by `tests/test_account_drill.py::test_each_recorded_ledger_equals_tallys_ledger_vouchers`.
