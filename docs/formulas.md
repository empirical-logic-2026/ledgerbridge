# Formula sheet

Every figure the dashboard shows, and how it is calculated: totals, net amounts, margins,
balances, bills, comparisons and counts. Use it to check a figure against the books or
against Tally, and as the reference for each page's "What is this?" help.

| Field | Value |
| --- | --- |
| Version | 1.0 |
| Date | 2026-11-02 |
| Requirement | RPT-015 |
| Word and PDF | `docs/export/formulas.docx`, `docs/export/formulas.pdf` (`./dev.ps1 docs-export`) |

**How IDs are used.** Every figure has an ID such as `F-PL-003`:

- The code that returns it names the ID (`formula("F-PL-003")` in `data-plane/api/v1`).
- The tests that prove it cite the same ID.
- `data-plane/tests/test_formulas.py` fails when:
  - a figure has no ID;
  - an ID used in code has no entry here;
  - an entry here is used nowhere.
- IDs are never reused or renumbered. A retired formula keeps its entry, marked retired.

**Areas:**

| Prefix | Area |
| --- | --- |
| `F-SAL` | Sales, and purchases on the purchase side |
| `F-PUR` | Purchases on their own |
| `F-PL` | Profit & Loss |
| `F-BS` | Balance Sheet |
| `F-BAL` | Balances |
| `F-PTY` | Parties and bills |
| `F-REG` | Registers |
| `F-CMP` | Comparisons |
| `F-CHK` | Checks against the source |
| `F-TBL` | Tables |
| `F-FMT` | How amounts are shown |

Later modules add `F-RAT` (ratios), `F-CF` (cash flow) and ageing in `F-PTY`.

**What each entry gives:**

- **In words** and as an **expression**.
- **Source:** the table or view and the columns it reads. Tables are in `ledgerbridge_accounting`, statements in `ledgerbridge_reporting`.
- **Sign:** the debit/credit rule.
- **Educational mode:** the date rule when the source runs in Tally's Educational mode.
- **Check in Tally:** where to find the same figure in TallyPrime.

## 1. Rules every formula follows

| Rule | Meaning |
| --- | --- |
| **Stored sign** | `voucher_lines.amount` and `ledgers.opening_balance` are **debit positive, credit negative** (schema.md §7). Each formula turns them into the sign people read: sales positive, purchases positive, a profit positive, a loss negative. |
| **Effective entry** | A voucher line that posts to the books: `voucher_lines.is_effective = 1` (not cancelled, not optional) and `vouchers.is_deleted = 0`. Only effective entries are counted. |
| **Ledgers under a group** | The ledgers whose group is, at any depth, under a group with a given **predefined role** (`account_groups.predefined_role`, e.g. `sales_accounts`), through `v_group_ancestors`. Groups are found by role, never by name, so a renamed group still counts. |
| **Period** | Whole months (adjacent or not), or a date range. MTD, QTD, YTD and FY are date ranges or months picked by the period toggles (RPT-016). |
| **Several companies** | Added together: combined, **without inter-company eliminations**. |
| **Currency** | The books' base currency, as the source keeps it. |
| **Precision** | Exact decimals: `DECIMAL(20,4)` in MySQL, `Decimal` in Python, BigInt in the browser. Never floating point, except chart drawing (F-FMT-003). |

### 1.1 Figures from the stored statements

Profit figures come from **our stored statements**, `statement_lines` (`figures = 'ours'`),
read through `v_profit_loss` and `v_balance_sheet`. They are built from the books and checked
line by line against the source's own statements (ADR-040, RPT-012). A stored Profit & Loss
runs from the books' beginning to its date, so:

```text
figure for a period = statement at the period's end − statement on the day before its start
```

At the books' beginning there is nothing to subtract. Several months are added month by
month. **A month's statement** is the one on its last day, or the first stored date up to
2 days later. **A date range** runs to its end date when that statement is stored, else to
the **last stored date within it**, and the page says "to 31-Oct-2026". MTD, QTD and YTD
therefore show profit to the last month end. With no stored date at all, the figure is "—"
with the reason. `./dev.ps1 statements` stores the month ends.

**Educational mode (all statement figures).** Tally's Educational mode allows only the 1st,
2nd and 31st of a month as report dates. The month ends stored for a 30-day month (and
February) are then the 2nd of the next month. The page says "Months ending on the 30th run to
the 2nd of the next month". When checking in Tally, use the same dates.

## 2. Sales and purchases (`F-SAL`, `F-PUR`)

These are the definitions of the monthly sales views (migration 0021, RPT-013), proven against
the source's Sales Accounts figure (`core/sales.py`). The same formulas apply to purchases:
read **Purchase Accounts** for Sales Accounts, **purchase invoices** (base type `purchase`) for
sales invoices, and **debit notes** for credit notes. Sales are positive as credits, purchases
as debits.

Source for every `F-SAL` entry: `voucher_lines` (`amount`, `ledger_id`, `voucher_date`,
`is_effective`) joined to `vouchers` (`is_deleted`, `party_id`) and `voucher_types`
(`base_type`, `name`), on the ledgers under `sales_accounts`.

#### F-SAL-001 Gross sales

- **In words:** the entries on the Sales Accounts ledgers made by sales invoices.
- **Expression:** `−Σ amount` where base type = `sales`. Purchases: `+Σ amount` where base type = `purchase`.
- **Sign:** a sale is a credit, so the stored amount is negative and is turned positive.
- **Educational mode:** none (entries are exact for any date).
- **Check in Tally:** Display More Reports › Account Books › Sales Register, the same period (F2). Purchases: the Purchase Register.

#### F-SAL-002 Sales returns

- **In words:** the entries on the Sales Accounts ledgers made by credit notes. Negative.
- **Expression:** `−Σ amount` where base type = `credit_note`. Purchases: `+Σ amount` where base type = `debit_note`.
- **Sign:** a return is a debit to sales, so it is shown negative.
- **Educational mode:** none.
- **Check in Tally:** Account Books › Credit Note Register (Debit Note Register for purchases).

#### F-SAL-003 Other adjustments

- **In words:** entries on the Sales Accounts ledgers from any other voucher (journals and the like).
- **Expression:** `−Σ amount` where base type ∉ {`sales`, `credit_note`}.
- **Sign:** as F-SAL-001.
- **Educational mode:** none.
- **Check in Tally:** Account Books › Group Vouchers of Sales Accounts, leaving out sales and credit notes.

#### F-SAL-004 Net sales

- **In words:** gross sales, plus returns, plus other adjustments.
- **Expression:** `F-SAL-001 + F-SAL-002 + F-SAL-003`, i.e. `−Σ amount` on the Sales Accounts ledgers.
- **Sign:** positive for sales.
- **Educational mode:** none.
- **Check in Tally:** the Sales Accounts line of the Profit & Loss A/c for the same period. Or Account Books › Group Summary › Sales Accounts. Month by month: the group's monthly summary.
- **Shown as:** the net per month, per company, per party, and in the lists.

#### F-SAL-005 Invoices

- **In words:** the number of invoice vouchers with an entry on the Sales Accounts ledgers.
- **Expression:** `COUNT(DISTINCT voucher)` where base type = `sales` (purchases: `purchase`).
- **Sign:** a count.
- **Educational mode:** none.
- **Check in Tally:** the number of vouchers in the Sales Register.

#### F-SAL-006 Average invoice

- **In words:** gross sales per invoice.
- **Expression:** `F-SAL-001 ÷ F-SAL-005`, rounded to the paisa. "—" without invoices.
- **Sign:** positive.
- **Educational mode:** none.
- **Check in Tally:** the Sales Register total ÷ its number of vouchers.

#### F-SAL-007 Returns (key figure)

- **In words:** the sales returns as a positive amount (lower is better).
- **Expression:** `−F-SAL-002`.
- **Sign:** positive.
- **Educational mode:** none.
- **Check in Tally:** the Credit Note Register total.

#### F-SAL-008 Closing balance (monthly)

- **In words:** net sales from the start of the month's financial year to the month's end. Each company uses its own financial year, and the companies are then added together.
- **Expression:** `Σ F-SAL-004` from the first month of the financial year to the month.
- **Sign:** positive.
- **Educational mode:** none.
- **Check in Tally:** the Closing Balance column of the Sales Accounts group's monthly summary.

#### F-SAL-009 Net sales by channel

- **In words:** net sales of one channel, i.e. one voucher type name. Types with the same name in several companies count as one channel.
- **Expression:** `F-SAL-004` restricted to `voucher_types.name = channel`.
- **Sign:** positive.
- **Educational mode:** none.
- **Check in Tally:** the Sales Register for that voucher type.
- **On the Overview:** the four largest channels are shown, and the rest are added together as "Others".

#### F-SAL-010 Channel share

- **In words:** a channel's net as a percentage of all channels' net.
- **Expression:** `F-SAL-009 ÷ Σ F-SAL-009 × 100`, one decimal.
- **Sign:** a percentage.
- **Educational mode:** none.
- **Check in Tally:** from the Sales Registers by voucher type.

#### F-SAL-011 Customers

- **In words:** how many customers had entries on the Sales Accounts ledgers in the period. A customer is known by **name** across the selected companies. Vouchers without a party aren't counted.
- **Expression:** `COUNT(DISTINCT parties.name)` over the entries of F-SAL-004 (`vouchers.party_id → parties.name`).
- **Sign:** a count.
- **Educational mode:** none.
- **Check in Tally:** the parties listed in the Sales Register (Alt+F5 detailed), counted once each.

#### F-SAL-012 Customer net sales

- **In words:** net sales of one customer's vouchers.
- **Expression:** `F-SAL-004` restricted to `vouchers.party_id` = the party.
- **Sign:** positive.
- **Educational mode:** none.
- **Check in Tally:** Sales Register filtered by party, or the party's ledger vouchers for Sales Accounts.

#### F-SAL-013 Other customers

- **In words:** net sales of every customer after the top ten, plus sales without a party.
- **Expression:** `F-SAL-004 − Σ F-SAL-012` over the top ten.
- **Sign:** positive.
- **Educational mode:** none.
- **Check in Tally:** the Sales Register total less the top ten customers'.

#### F-SAL-014 Invoice amount (largest invoices)

- **In words:** one invoice's entries on the Sales Accounts ledgers. Taxes and freight on other ledgers aren't included.
- **Expression:** `−Σ amount` of that voucher on the Sales Accounts ledgers.
- **Sign:** positive.
- **Educational mode:** none.
- **Check in Tally:** the voucher's sales ledger lines.

#### F-SAL-015 Share of sales by company

- **In words:** one company's net sales as a percentage of the selection's.
- **Expression:** `F-SAL-004 (company) ÷ F-SAL-004 (all selected) × 100`, one decimal.
- **Sign:** a percentage.
- **Educational mode:** none.
- **Check in Tally:** each company's Sales Accounts line.

#### F-PUR-001 Net purchases

- **In words:** the net purchases of the period or month. This is F-SAL-004 on the purchase side.
- **Expression:** `+Σ amount` on the ledgers under `purchase_accounts`.
- **Sign:** a purchase is a debit, so positive.
- **Educational mode:** none.
- **Check in Tally:** the Purchase Accounts line of the Profit & Loss A/c, or the Purchase Accounts group summary.

## 3. Profit & Loss (`F-PL`)

Source for every `F-PL` entry: `statement_lines` (`statement = 'profit_loss'`,
`figures = 'ours'`, `label`, `section`, `level`, `amount`, `as_of`) through `v_profit_loss`.
Groups are matched by predefined role (`account_groups`), and §1.1 gives the period rule.

**Sign:** a stored line is debit positive. Income and profit are shown positive, and costs are shown positive when spent. A loss is negative.

**Educational mode:** §1.1 applies to every `F-PL` entry.

#### F-PL-001 Revenue (net sales)

- **In words:** the Sales Accounts line of the stored Profit & Loss for the period. It equals F-SAL-004, as the tests prove.
- **Expression:** `−(line at end − line before start)`, for the line whose group has role `sales_accounts`.
- **Check in Tally:** Gateway of Tally › Profit & Loss A/c, period (F2), the Sales Accounts line.

#### F-PL-002 Cost of sales

- **In words:** the lines above gross profit that aren't income: the source's Cost of Sales block (opening stock + purchases + direct expenses − closing stock), or, without stock, its purchase and direct expense lines.
- **Expression:** `Σ (line at end − line before start)`, for main lines in the `gross` section whose group nature isn't income.
- **Check in Tally:** Profit & Loss A/c, the lines above Gross Profit on the expense side.

#### F-PL-003 Gross profit

- **In words:** net sales + direct incomes − cost of sales. It comes from the stored Gross Profit line, for the period or for one month.
- **Expression:** `−(Gross Profit line at end − before start)`.
- **Check in Tally:** Profit & Loss A/c, Gross Profit c/o (or b/f).

#### F-PL-004 Net profit or loss

- **In words:** gross profit + indirect incomes − indirect expenses. It comes from the stored Net Profit line, for the period or for one month. Negative for a loss.
- **Expression:** `−(Net Profit line at end − before start)`.
- **Check in Tally:** Profit & Loss A/c, Nett Profit (or Nett Loss).

#### F-PL-005 Gross margin %

- **In words:** gross profit as a percentage of net sales.
- **Expression:** `F-PL-003 ÷ F-PL-001 × 100`, one decimal. "—" when net sales is zero.
- **Check in Tally:** Display More Reports › Ratio Analysis, Gross Profit %.

#### F-PL-006 Net profit %

- **In words:** net profit as a percentage of net sales.
- **Expression:** `F-PL-004 ÷ F-PL-001 × 100`, one decimal. "—" when net sales is zero.
- **Check in Tally:** Ratio Analysis, Net Profit %.

#### F-PL-007 Statement line for a period

- **In words:** any line of the Profit & Loss report: the line at the period's end less the line before its start. It applies per company, month or quarter column, and to the total.
- **Expression:** `line at end − line before start`, signed as above.
- **Check in Tally:** the same line of the Profit & Loss A/c for the same period and company.

#### F-PL-008 % of net sales

- **In words:** a line as a percentage of the same column's net sales.
- **Expression:** `F-PL-007 ÷ F-PL-001 (same column) × 100`, one decimal.
- **Check in Tally:** Profit & Loss A/c with percentages (Alt+F5 in some releases), or by hand.

#### F-PL-009 Other costs (indirect expenses less indirect incomes)

- **In words:** what lies between gross profit and net profit.
- **Expression:** `F-PL-003 − F-PL-004`.
- **Check in Tally:** Profit & Loss A/c, the indirect expenses less the indirect incomes below Gross Profit.

#### F-PL-010 Cost structure (% of net sales)

- **In words:** cost of sales (F-PL-002), or other costs (F-PL-009), as a percentage of net sales; on the P&L page also each expense line (F-PL-008).
- **Expression:** `cost ÷ F-PL-001 × 100`, one decimal.

## 4. Balance Sheet (`F-BS`)

Source for every `F-BS` entry: `statement_lines` (`statement = 'balance_sheet'`, `figures = 'ours'`)
at one date, the period's end or the last stored date within it (§1.1), through
`v_balance_sheet`. A Balance Sheet is the position **at** a date, not a difference.

**Sign:** assets are positive (debit). Liabilities and capital are shown positive (credit).

**Educational mode:** the date rule of §1.1 applies to every `F-BS` entry.

#### F-BS-001 Total assets

- **In words:** the assets side's main lines added up.
- **Expression:** `Σ amount` of main lines with section `assets`.
- **Check in Tally:** Gateway of Tally › Balance Sheet, at the same date, the assets total.

#### F-BS-002 Current assets

- **In words:** the Current Assets line.
- **Expression:** the main line of the group with role `current_assets`.
- **Check in Tally:** Balance Sheet, Current Assets.

#### F-BS-003 Current liabilities

- **In words:** the Current Liabilities line, shown positive.
- **Expression:** `−amount` of the main line of the group with role `current_liabilities`.
- **Check in Tally:** Balance Sheet, Current Liabilities.

#### F-BS-004 Capital and reserves (incl. profit to date)

- **In words:** the Capital Account line plus the Profit & Loss A/c line.
- **Expression:** `−Σ amount` of those main lines.
- **Check in Tally:** Balance Sheet, Capital Account plus Profit & Loss A/c.

## 5. Balances (`F-BAL`)

Source for every `F-BAL` entry: `ledgers` (`opening_balance`, `group_id`, `is_deleted`) and the
effective `voucher_lines` up to the date.

**Educational mode:** none for F-BAL-001 to F-BAL-004, because entries are exact for any date.

#### F-BAL-001 Balance of ledgers under a group (as at a date)

- **In words:** the ledgers' opening balances plus their effective entries up to and including the date.
- **Expression:** `Σ opening_balance + Σ amount (voucher_date ≤ date)`.
- **Sign:** debit positive.
- **Check in Tally:** Account Books › Group Summary of that group, at the date.

#### F-BAL-002 Cash & bank

- **In words:** F-BAL-001 for the groups with roles `cash_in_hand` and `bank_accounts`, at the period's end. Bank OD and OCC accounts are loans, so they aren't included.
- **Sign:** debit positive. A negative figure means an overdrawn ledger.
- **Check in Tally:** Balance Sheet › Current Assets › Cash-in-Hand plus Bank Accounts. Or Account Books › Cash/Bank Book(s).

#### F-BAL-003 Receivables

- **In words:** F-BAL-001 for the group `sundry_debtors`, at the period's end.
- **Sign:** debit positive: owed to us.
- **Check in Tally:** Group Summary of Sundry Debtors. Or Statements of Accounts › Outstandings › Receivables (bill-wise totals).

#### F-BAL-004 Payables

- **In words:** −F-BAL-001 for the group `sundry_creditors`, so that an amount we owe shows positive.
- **Sign:** a credit, shown positive.
- **Check in Tally:** Group Summary of Sundry Creditors. Or Outstandings › Payables.

#### F-BAL-005 Stock value

- **In words:** the source's closing stock, stored with the statements for that date. "—" unless every selected company has one.
- **Source:** `stock_values` (`scope = 'total'`, `closing_value`, `as_of`).
- **Sign:** positive.
- **Educational mode:** stored only on statement dates (§1.1).
- **Check in Tally:** Gateway of Tally › Stock Summary, closing value at the date. It is also the Closing Stock in the Profit & Loss A/c.

## 6. Parties and bills (`F-PTY`)

A party is known by **name** across the selected companies, and its ledgers are those linked
to any party of that name (`parties`, `ledgers.party_id`). Bills come from
`bill_allocations` (`bill_name`, `bill_type`, `bill_date`, `due_date`, `amount`) of effective
vouchers.

**Opening bills** (from before the books' beginning) aren't stored yet, so the bills can
cover less than the balance. Every page says so.

#### F-PTY-001 Balance due

- **In words:** the party's ledgers at the period's end (F-BAL-001 for those ledgers). A customer's is owed to us. A vendor's credit is shown positive, as an amount we owe.
- **Sign:** customers: debit positive. Vendors: `−` (credit shown positive).
- **Educational mode:** none.
- **Check in Tally:** the party ledger's closing balance (Account Books › Ledger).

#### F-PTY-002 Overdue

- **In words:** the outstanding bills (F-PTY-004) whose due date is before the period's end.
- **Expression:** `Σ F-PTY-004` where `due < period end` and the amount is positive.
- **Educational mode:** none.
- **Check in Tally:** Outstandings › Ledger (party), the overdue column at the date.

#### F-PTY-003 Bills cover

- **In words:** all outstanding bills added up. It is less than the balance when opening bills are missing.
- **Expression:** `Σ F-PTY-004`.
- **Check in Tally:** Outstandings › Ledger (party), the total pending.

#### F-PTY-004 Outstanding bill

- **In words:** per ledger and bill name, the new reference less everything settled against it, up to the period's end. "On account" is excluded. Amounts below half a paisa count as settled.
- **Expression:** `sign × Σ allocation amount` per (ledger, bill name).
- **Sign:** customers debit positive. Vendors are shown positive.
- **Check in Tally:** Outstandings › Ledger (party), the bill's pending amount.

#### F-PTY-005 Overdue days (a bill)

- **In words:** the days from the bill's due date to the period's end, or 0 when not yet due. The due date is the allocation's due date, else the bill's date plus the party's credit days.
- **Expression:** `max(0, period end − due date)`.
- **Check in Tally:** Outstandings, the "Overdue by days" column.

#### F-PTY-006 Receipts (payments)

- **In words:** what receipt (payment) vouchers put on the party's ledgers in the period. As a monthly figure: per month. As one settlement: that voucher.
- **Expression:** `Σ amount` of receipt-type vouchers (payment-type for vendors) on the party's ledgers, shown positive.
- **Check in Tally:** the party ledger's receipt (payment) vouchers in the period.

#### F-PTY-007 Average days to pay

- **In words:** for settlements in the period ("against" allocations), the days from the bill's date to the settlement, weighted by amount.
- **Expression:** `Σ(|amount| × days) ÷ Σ |amount|`, rounded to whole days.
- **Check in Tally:** not a Tally report. Check by hand from the bill-wise ledger.

#### F-PTY-008 Ledger statement entry (debit, credit)

- **In words:** one effective entry on the party's ledgers. The particulars are the other side's first ledger.
- **Expression:** debit = `amount` when positive; credit = `−amount` when negative.
- **Check in Tally:** the party ledger's vouchers (Account Books › Ledger).

#### F-PTY-009 Running balance

- **In words:** the previous balance plus this entry.
- **Expression:** `balance(n) = balance(n−1) + amount(n)`, starting from F-PTY-010.
- **Check in Tally:** the party ledger, running balance shown (F12: Show running balance).

#### F-PTY-010 Statement opening

- **In words:** the party's ledgers at the day before the period's start (F-BAL-001).
- **Check in Tally:** the party ledger's Opening Balance for the period.

#### F-PTY-011 Invoice days (due in or overdue by)

- **In words:** for an invoice's bill at the period's end: the days until it is due, or the days it is overdue.
- **Expression:** due: `due − period end`; overdue: `period end − due`.
- **Check in Tally:** Outstandings, the due date of the bill.

#### F-PTY-012 Ageing bucket

- **In words:** a party's outstanding bills (F-PTY-004) at the day, by the days from each bill's due date to that day: not due, 1-30, 31-60, 61-90 and over 90 days past due.
- **Check in Tally:** Display More Reports › Statements of Accounts › Outstandings › Ageing Analysis (Receivables or Payables), at the same date, by due date.

#### F-PTY-013 Uncovered by bills

- **In words:** the balance due (F-PTY-001) less the outstanding bills (F-PTY-003). It is the part from before the books' beginning (opening bills aren't stored yet), plus anything posted without a bill.

## 7. Registers (`F-REG`)

Source for every `F-REG` entry: `vouchers` and their first effective `voucher_lines`
(`line_no` order), with the vouchers' entries on the side's ledgers.

#### F-REG-001 Debit or credit (Day Book)

- **In words:** the voucher's first ledger entry, as the source's Day Book shows it. For an invoice, that is the party.
- **Expression:** debit = `amount` when positive; credit = `−amount` when negative.
- **Check in Tally:** Display More Reports › Day Book, the same voucher.

#### F-REG-002 Value (on sales or purchase ledgers)

- **In words:** the voucher's entries on the Sales (Purchase) Accounts ledgers. Positive for an invoice, negative for a return. The register's total is gross plus returns (F-SAL-001 + F-SAL-002).
- **Expression:** `−Σ amount` (sales) or `+Σ amount` (purchases), per voucher.
- **Check in Tally:** the Sales (Purchase) Register, voucher by voucher.

## 7a. Overview (`F-OVR`)

#### F-OVR-001 Twelve-month trend (sparklines)

- **In words:** the twelve months up to the period's end month, each with its net sales (F-SAL-004), gross and net profit (F-PL-003, F-PL-004), cash and bank at the month's end (F-BAL-002) and customers (F-SAL-011).

#### F-OVR-002 Top customers

- **In words:** the ten customers, by name across the companies, with the largest net sales (F-SAL-012), each with its balance due (F-PTY-001) and overdue (F-PTY-002) at the period's end. The status is "overdue" when anything is overdue, else "current".

#### F-OVR-003 Profit & Loss summary against last year

- **In words:** net sales, cost of sales, gross profit, gross margin %, net profit and net profit % (F-PL-001 to F-PL-006) for the period and for the same months or dates last year, with the change (F-CMP-001, or F-CMP-003 for a percentage).

#### F-OVR-004 Customer share of net sales

- **Expression:** `F-SAL-012 ÷ F-SAL-004 × 100`, one decimal.

## 8. Comparisons (`F-CMP`)

#### F-CMP-001 Change %

- **In words:** how much a figure moved against the comparison period.
- **Expression:** `(value − before) ÷ |before| × 100`, one decimal. None without a comparison figure, or when it is zero.
- **Colour:** green when the change is good for the business, crimson when sales or profit fall, and neutral when a cost rises.

#### F-CMP-002 The comparison period

- **In words:** what "before" means.

| Selected | Previous period | Last year |
| --- | --- | --- |
| MTD | the same days of the month before | the same dates a year earlier |
| QTD | the same days of the quarter before | the same dates a year earlier |
| YTD | the same dates a year earlier | the same dates a year earlier |
| FY | the previous financial year | the previous financial year |
| Months chosen | as many months just before | the same months a year earlier |
| Dates chosen | as many days just before | the same dates a year earlier |

- **Month ends:** a month end stays a month end (31-May → 30-Apr), and 29-Feb becomes 28-Feb.
- **Source:** `core/report_periods.py` (`Period.previous`, `Period.last_year`).

#### F-CMP-003 Change in percentage points

- **In words:** for a percentage (a margin), the difference between this period's and the comparison's.
- **Expression:** `value − before`, shown as "▼ 1.1 pts".

## 9. Checks against the source (`F-CHK`)

Source for every `F-CHK` entry: `statement_lines` at the dates used, ours (`figures = 'ours'`)
against the source's own (`figures = 'source'`), line by line and in total.

#### F-CHK-001 Lines that differ

- **In words:** compared lines and totals (company × date × line) whose amounts differ from the source's.

#### F-CHK-002 Lines compared

- **In words:** the lines and totals compared at the dates used.

#### F-CHK-003 Unchecked company-dates

- **In words:** company and date pairs without the source's own statement to compare.

**"Matches Tally"** holds when F-CHK-002 > 0, F-CHK-001 = 0 and F-CHK-003 = 0.

## 10. Tables (`F-TBL`)

#### F-TBL-001 Total

- **In words:** the sum of an amount or count column over the rows shown, after the filter. Used by the table explorer's total row and the dataset explorer's total.
- **Expression:** `Σ value`, as exact decimals (BigInt).
- **Not summed:** balance columns (a closing or running balance), because adding balances means nothing.

#### F-TBL-002 Subtotal

- **In words:** F-TBL-001 within each group when a table is grouped. The CSV carries the subtotals and the total.

## 11. Showing amounts (`F-FMT`)

#### F-FMT-001 Short amounts (cards)

- ₹1 crore and above: crores to 2 decimals ("₹4.82 Cr").
- ₹1 lakh and above: lakhs to 1 decimal ("₹62.4 L").
- Below that: whole rupees with Indian grouping ("₹45,300").
- Rounding is half away from zero, and applies only when the amount is shown.

#### F-FMT-002 Exact amounts (hover, tables, CSV)

- To the paisa with Indian grouping ("₹4,82,00,000.00"). Sums use the unrounded amounts.

#### F-FMT-003 Chart amounts

- In ₹ lakh, for drawing only. Never used for sums or for the figures shown.

## Change log

| Version | Date | Change |
| --- | --- | --- |
| 1.0 | 2026-11-02 | Rewritten as the formula sheet (RPT-015): an ID per figure with words, expression, source, sign, Educational-mode rule and the check in Tally; the comparison with the previous period (F-CMP-002, RPT-016); date ranges to the last stored date; `test_formulas.py`; Word and PDF copies. |
| 0.1 | 2026-11-02 | First version: building blocks, sales and purchases, the Dashboard's key figures, registers, parties, tables, showing amounts. |
