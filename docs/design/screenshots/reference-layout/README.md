# The reference layout on the test company (2026-11-11)

Screenshots of the dashboard after the reference layout and pulse loading ([dashboard design](../../dashboard.md) Sections 0.4 and 0.5). Data: **LedgerBridge Test Co only**, loaded into the test database from its recorded Tally responses (`data-plane/tests/fixtures/tally`), without contacting Tally. Taken with Edge headless at 1440 px wide.

| File | Page |
| --- | --- |
| `00-loading-overview.png` | The Overview while its data loads: key cards, charts and tables as pulsing placeholders; the logo pulses (first load) |
| `00-loading-balance-sheet-dark.png` | The Balance Sheet while it loads, in dark mode: the statement table beside the ratio tiles |
| `01-overview.png` | Overview |
| `02-sales.png` | Sales dashboard |
| `03-purchases.png` | Purchases dashboard |
| `04-profit-loss.png` | P&L & KPIs |
| `05-cost-centres.png` | Cost centres |
| `06-balance-sheet.png` | Balance Sheet |
| `07-stock.png` | Stock summary |
| `08-cash-flow.png` | Cash Flow |
| `09-receivables.png` | Parties: receivables |
| `10-transactions.png` | Books: transactions |
| `11-data-health.png` | Data health |
| `12-error-with-retry.png` | A failed request (a customer that doesn't exist): the reason and Retry |
| `13-overview-dark.png` | The Overview in dark mode |

**What the recordings can't show:** the source's stored statements (`./dev.ps1 statements` reads them from Tally), so profit, the P&L statement and the Balance Sheet show their "no statement stored" messages here. The statement table itself is proven by the tests (`StatementTable.test.tsx` and the Overview and Balance Sheet tests in `App.test.tsx`).
