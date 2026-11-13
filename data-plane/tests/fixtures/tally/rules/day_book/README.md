# Day Book recording (ADR-057)

Recorded 2026-11-13 from TallyPrime with only LedgerBridge Test Co loaded (Educational mode):

```
python -m connectors.tally.tools capture-day-book --company "LedgerBridge Test Co" \
    --from 2025-04-01 --to 2026-11-02
```

- `books/`: the company's books at that moment (as `capture-fixtures`).
- `voucher_counts_<month>.xml`: Tally's voucher list (date and type of each voucher), whole months.
- `day_book_<date>.xml|.html`: Tally's own Day Book for every day with a voucher (24 days).
  Tally's Day Book lists one day, its current date (`SVCURRENTDATE`), whatever the From and To
  dates. The HTML export keeps the columns as Tally shows them: Date, Particulars, Vch Type,
  Debit Amount (or Inwards Qty) and Credit Amount (or Outwards Qty); no voucher number.
