# Dashboard pages

This document tells you what each page of the dashboard shows and how to check it against Tally.

| Field | Value |
| --- | --- |
| Version | 1.0 |
| Date | 2026-11-11 |
| Requirements | RPT-014 (layout and modules), RPT-015 (formulas), RPT-016 (periods and comparison) |
| Language | ASD-STE100 Simplified Technical English |
| Word and PDF | `docs/export/dashboard-pages.docx`, `docs/export/dashboard-pages.pdf` (`./dev.ps1 docs-export`) |
| Related | [formula-sheet.md](formula-sheet.md) (each formula ID and its terms), [design/dashboard.md](design/dashboard.md) (the design) |

The terms in this document have the meanings in the Terms section of the [formula sheet](formula-sheet.md#2-terms). A formula ID, for example `F-SAL-004`, refers to an entry in the formula sheet.

## 1. Parts that each page has

### 1.1 Top bar

The top bar is dark on each page. It has these parts, from left to right:

| Part | What it does |
| --- | --- |
| Logo and "LedgerBridge" | Opens the Overview. The logo pulses while the first data loads. |
| Period toggles | Select the period: MTD (month to date), QTD (quarter to date), YTD (year to date), FY (financial year) or Custom. Custom lets you select months or two dates. |
| Financial year | Selects the financial year for FY and for Custom months. |
| Comparison | Selects the comparison period: previous period, last year or no comparison (F-CMP-002). |
| Amounts | Shows amounts in lakhs or in full (F-FMT-001, F-FMT-002). The browser keeps the setting. |
| Light or dark | Changes the colours of the dashboard. |
| Module tabs | Open a module: Overview, Sales, Purchases, P&L & KPIs, Balance Sheet, Stock, Cash Flow, Parties, Books and Data. The tabs are on a row below the logo. |

### 1.2 Page header

| Part | What it does |
| --- | --- |
| Breadcrumbs | Show where you are. Click a breadcrumb to go back. |
| Title and period | Show the page, the period and the comparison. |
| Company chips | Select the companies. "All companies" selects each company. A dot shows if the source had the company loaded. |
| Filters | Pages that take filters show them here: customer, channel or voucher type. Other pages tell you why they take no filters. |
| "Updated N min ago" | Shows the time of the last sync. It is green when all is correct. It is crimson when a company is not loaded or a check failed. |
| Copy link | Copies a link to the page with all selections. |
| Page tabs | Open the other pages of the module. |

### 1.3 Shared components

| Component | What it shows |
| --- | --- |
| Key card | A label, a figure, the change against the comparison period and a small line of twelve months (F-OVR-001). Green shows a change that is good for the business. Crimson shows a change that is bad. |
| Statement table | Lines with this period, the comparison period and the change. |
| Ratio tiles | Ratios in a grid of two by two. On the Balance Sheet, hover a ratio to see its parts. |
| Status pill | A word for the state of a party or a bill, with its meaning. |
| Donut | The parts of a total as a ring. |
| Horizontal bars | The parts of a total as bars with a percentage. |
| Table explorer | A table. See section 1.4. |

Each figure has a formula ID. The hover text of a figure shows its formula and its ID. A test fails when a figure has no ID.

### 1.4 Table explorer

Each table has these controls:

| Control | What it does |
| --- | --- |
| Filter | Shows only the rows that contain the text. |
| Columns | Shows or hides columns. |
| Group by | Groups the rows and shows a subtotal for each group (F-TBL-002). |
| Saved views | Keeps the columns, the groups and the sort order in the browser. |
| Export CSV | Gives a file with the rows, the subtotals and the total. The file has exact amounts (F-FMT-002). |
| Column header | Sorts the rows. Click again to change the order. |
| Total row | Shows the total of each amount and count column (F-TBL-001). |

### 1.5 Loading and errors

All pages load and show errors in the same way:

- While data loads, the page shows grey shapes of its parts: key cards, charts, table rows and ratio tiles. The layout does not move when the data comes.
- The shapes show only when the load takes more than 150 ms. A fast load does not flicker.
- The shapes pulse slowly in the colours of the theme. With the "reduce motion" setting of your system, they do not move.
- The loading area has `aria-busy`. A screen reader says "Loading…".
- When a request fails, the page shows what failed and why. Click **Retry** to send the request again.

### 1.6 How to check a page against Tally

Use these steps for each page:

1. Select one company in the page header.
2. Write down the period and the dates on the page.
3. Open TallyPrime with the same company.
4. Set the same period in the Tally report (F2).
5. Compare each figure with the steps in its formula ID.

For a statement, use the statement date on the page. In Educational mode, the month end can be the 2nd of the next month (formula sheet, rule D6).

## 2. Overview

**Purpose:** The Overview shows the whole business on one page.

**Filters and controls:** The period, the comparison, the companies and Amounts. The page takes no filters.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Net sales (key card) | The net sales of the period. | F-SAL-004, F-OVR-001 |
| Gross profit (key card) | The gross profit, with the gross margin. | F-PL-003, F-PL-005 |
| Net profit (key card) | The net profit, with the net margin. | F-PL-004, F-PL-006 |
| Cash & bank (key card) | The cash and bank balances at the period end. | F-BAL-002 |
| Customers (key card) | The number of customers with sales in the period. | F-SAL-011 |
| Sales and purchases by month (chart) | Bars for sales and purchases. Lines for gross profit and net profit. | F-SAL-004, F-PUR-001, F-PL-003, F-PL-004 |
| Sales by channel (donut) | The four largest channels and "Others". | F-SAL-009, F-SAL-010 |
| Profit & Loss summary (statement table) | Six lines against last year, with the change. | F-OVR-003, F-PL-001 to F-PL-006, F-CMP-001, F-CMP-003 |
| Top customers (table) | The ten largest customers with their share, balance due and status. | F-OVR-002, F-OVR-004, F-PTY-001 |

**Drill-downs:**

| Click | Opens |
| --- | --- |
| Net sales label | The Sales dashboard. |
| Gross profit or net profit label | The Profit & Loss page. |
| Customers label | The Customers list. |
| A channel in the donut | The Sales register for that channel. "Others" has no link. |
| A line of the Profit & Loss summary, or "Open" | The Profit & Loss page. |
| A customer | The page of that customer. |
| "All customers" | The Customers list. |

**Loading and errors:** As section 1.5, with the Overview shapes: five key cards, two charts and two tables.

**Check against Tally:**

1. Open Profit & Loss A/c for the period. Compare net sales, gross profit and net profit.
2. Open the Balance Sheet at the period end. Add Cash-in-Hand and Bank Accounts.
3. Open the Sales Register. Compare the customers and the channels.

## 3. Sales

The Sales module has five pages: Sales dashboard, Sales register, Monthly sales, Channels and Customers.

**Filters for the Sales module:** Customer and channel (voucher type), except on the Customers list.

### 3.1 Sales dashboard

**Purpose:** The page shows the sales of the period, by month, by branch, by channel and by customer.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Net sales (key card) | The net sales of the period. | F-SAL-004 |
| Invoices (key card) | The number of sales invoices. | F-SAL-005 |
| Average invoice (key card) | Gross sales for each invoice. | F-SAL-006 |
| Sales returns (key card) | The sales returns as a positive number. Lower is better. | F-SAL-007 |
| Net sales by month (chart and table) | Each month with gross, returns, other adjustments, net and invoices. | F-SAL-001 to F-SAL-005 |
| Monthly net sales by branch (chart) | One line for each company. Shown for two or more companies. | F-SAL-004, F-SAL-015 |
| Sales mix (donut) | Net sales by channel. | F-SAL-009, F-SAL-010 |
| Top customers (table) | The customers with the largest net sales. | F-SAL-012, F-SAL-013, F-OVR-004 |
| Largest invoices (table) | The invoices with the largest amounts. | F-SAL-014 |

**Drill-downs:**

| Click | Opens |
| --- | --- |
| A month in the chart or in the table | The Sales register for that month. |
| A channel in the donut | The Sales register for that channel. |
| A customer | The page of that customer. |
| An invoice number | No link yet. The voucher page is planned. |

**Loading and errors:** As section 1.5, with four key cards, a chart and a table.

**Check against Tally:**

1. Open the Sales Register for the period. Compare gross sales and the number of invoices.
2. Open the Credit Note Register. Compare the returns.
3. Open the Profit & Loss A/c. Compare net sales with the Sales Accounts line.

### 3.2 Sales register

**Purpose:** The page lists each sales invoice and credit note, as the Day Book of Tally shows them.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Register (table) | Date, particulars, voucher type, voucher number, debit, credit, value and narration. Grouped by month, with subtotals. | F-REG-001, F-REG-002, F-TBL-001, F-TBL-002 |

**Drill-downs:** A voucher number has no link yet. The voucher page is planned.

**Loading and errors:** As section 1.5, with table rows.

**Check against Tally:**

1. Open Account Books › Sales Register for the period.
2. Compare the vouchers and the total.

### 3.3 Monthly sales

**Purpose:** The page shows the sales of each month and the closing balance from the start of the financial year.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Chart | Net sales for each month. | F-SAL-004 |
| Months (table) | Gross, returns, other adjustments, net, closing balance and invoices. | F-SAL-001 to F-SAL-005, F-SAL-008 |

**Drill-downs:** Click a month to open the Sales register for that month.

**Loading and errors:** As section 1.5, with a chart and table rows.

**Check against Tally:**

1. Open Account Books › Group Summary › Sales Accounts.
2. Open the monthly summary.
3. Compare each month and the closing balance.

### 3.4 Channels

**Purpose:** The page shows the sales of each channel (voucher type), with a column for each month.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Chart | Net sales of each channel. | F-SAL-009 |
| Channels (table) | Net sales, share, gross, returns, other adjustments, invoices and one column for each month. | F-SAL-001 to F-SAL-005, F-SAL-009, F-SAL-010 |

**Drill-downs:** Click a channel, or a month of a channel, to open the Sales register with that filter.

**Loading and errors:** As section 1.5, with a chart and table rows.

**Check against Tally:**

1. Open the Sales Register.
2. Select one voucher type.
3. Compare the total for the period.

### 3.5 Customers and the page of a customer

**Purpose:** The list shows each customer with sales in the period. The page of a customer shows its figures, invoices, payments, ledger, bills and months.

**Filters and controls:** No filters. The page has its own tabs: Invoices, Settlements, Statement, Bills and Monthly.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Customers (table) | Net sales, invoices, last invoice, balance due and companies. | F-SAL-012, F-SAL-005, F-PTY-001 |
| Balance due (key card) | The balance at the period end. | F-PTY-001 |
| Overdue (key card) | The bills past their due date. | F-PTY-002 |
| Net sales (key card) | The net sales of the customer, with a line of the months. | F-SAL-012 |
| Average days to pay (key card) | The days from bill to payment. | F-PTY-007 |
| Invoices (tab) | Each invoice with its status and days. | F-SAL-014, F-PTY-011 |
| Settlements (tab) | Each receipt. | F-PTY-006 |
| Statement (tab) | The ledger with a running balance. | F-PTY-008 to F-PTY-010 |
| Bills (tab) | Each outstanding bill with its due date. | F-PTY-003 to F-PTY-005, F-PTY-013 |
| Monthly (tab) | Net sales and receipts for each month. | F-SAL-012, F-PTY-006 |

**Drill-downs:** Click a customer in the list to open its page. A voucher number has no link yet.

**Loading and errors:** As section 1.5, with table rows (the list) or key cards, a chart and a table (the page).

**Check against Tally:**

1. Open Account Books › Ledger of the customer. Compare the balance and the statement.
2. Open Outstandings › Ledger. Compare the bills and the overdue amount.

## 4. Purchases

The Purchases module has four pages: Purchases dashboard, Purchase register, Monthly purchases and Vendors. They work as the Sales pages, for purchases. Read the formula sheet section 4 for the words that change.

**Filters for the Purchases module:** Voucher type, except on the Vendors list.

| Page | Same as | Formula IDs |
| --- | --- | --- |
| Purchases dashboard | Sales dashboard (3.1) | F-SAL-001 to F-SAL-007 for purchases, F-PUR-001 |
| Purchase register | Sales register (3.2) | F-REG-001, F-REG-002 |
| Monthly purchases | Monthly sales (3.3) | F-SAL-001 to F-SAL-005, F-SAL-008 for purchases |
| Vendors and the page of a vendor | Customers (3.5) | F-PTY-001 to F-PTY-013 for vendors |

**Drill-downs:** As the Sales pages.

**Loading and errors:** As section 1.5.

**Check against Tally:**

1. Open the Purchase Register for the period. Compare the totals.
2. Open the Debit Note Register. Compare the returns.
3. Open the Profit & Loss A/c. Compare the Purchase Accounts line.

## 5. P&L & KPIs

The module has two pages: Profit & Loss and Cost centres.

**Filters:** None. A statement covers each customer, channel and voucher type.

### 5.1 Profit & Loss

**Purpose:** The page shows the margins, the cost structure, the monthly trend and the full Profit & Loss.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Margins (ratio tiles) | Gross margin, net margin, cost of sales and other costs as percentages of net sales. | F-PL-005, F-PL-006, F-PL-010 |
| Expense structure (horizontal bars) | Each cost as a percentage of net sales. | F-PL-010, F-PL-008 |
| Net sales and profit by month (chart) | Net sales, gross profit and net profit for each month. | F-PL-001, F-PL-003, F-PL-004 |
| Goal tracker | A note. Goals need budgets (milestone M7b). | None |
| Profit & Loss (table) | Each line of the stored Profit & Loss, with the comparison and the change. | F-PL-001 to F-PL-004, F-PL-007, F-PL-008, F-CMP-001 |
| "Matches Tally" | Shows if our lines are equal to the lines of Tally at the dates used. | F-CHK-001 to F-CHK-003 |

**Controls:** The table can show company by company, month by month or quarter by quarter. It can show the percentage of net sales. Export CSV gives the table.

**Drill-downs:** Click "What is this?" to read how the page works.

**Loading and errors:** As section 1.5, with table rows.

**Check against Tally:**

1. Open Gateway of Tally › Profit & Loss A/c.
2. Set the same period and the same company.
3. Compare each line. In Educational mode, use the dates on the page.

### 5.2 Cost centres

**Purpose:** The page shows the allocations to each cost centre, for each month.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Cost centres (table) | Each cost centre with its category, the centre above it, the total, the count and one column for each month. | F-CC-001, F-CC-003 |
| Page of a cost centre (table) | Each allocation with its date, voucher, ledger and amount. | F-CC-002 |

**Drill-downs:** Click a cost centre to open its page. A voucher number has no link yet.

**Loading and errors:** As section 1.5, with table rows.

**Check against Tally:**

1. Open Statements of Accounts › Cost Centres › Category Summary.
2. Set the same period.
3. Compare each cost centre. Tally includes the centres below it.

## 6. Balance Sheet

**Purpose:** The page shows the Balance Sheet at the period end, against the end of the comparison period, with the ratios.

**Filters:** None. A statement covers each customer, channel and voucher type.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Balance Sheet (statement table) | Each line at the two dates, with the change and the totals of the two sides. | F-BS-005, F-BS-006, F-CMP-001 |
| Liquidity and leverage (ratio tiles) | Current ratio, quick ratio, debt to equity and working-capital days. | F-RAT-008, F-RAT-009, F-RAT-010, F-RAT-007 |
| Working capital (ratio tiles) | Receivable days, payable days and inventory days. | F-RAT-004, F-RAT-005, F-RAT-006 |
| Hover of a ratio | Current assets and current liabilities (or borrowings and equity) with their parts, the ledgers marked as short-term, the date, and a note for combined companies. | F-BS-004, F-BS-007 to F-BS-011 |

**Current assets and current liabilities.** The ratios use the form of Schedule III. Each ledger goes to the side of its balance. For example, a debtor with a credit balance is a liability. Bank OD A/c, banks in credit and marked loans are short-term borrowings. Thus the ratio can be different from Ratio Analysis in Tally. The formula sheet section 6.1 gives the rules.

**Mark a loan as short-term.** Secured, unsecured and term loans are not current. To count a loan ledger as a short-term borrowing, do these steps:

1. Run `./dev.ps1 loans -Company "<name>" -Date <yyyy-mm-dd>`.
2. Find the ledger in the list. The list shows the id, the group and the closing balance.
3. Run `./dev.ps1 loans mark -Ledger <id>`.
4. Open the Balance Sheet again. The hover shows "Includes 1 ledger marked as short-term".

To remove the mark, run `./dev.ps1 loans clear -Ledger <id>`. The audit log keeps each change. The list is on your screen only. The command does not keep it.

**Drill-downs:** Hover or focus a ratio to see its parts. Click "What is this?" to read how the page works.

**Loading and errors:** As section 1.5, with a statement table beside ratio tiles.

**Check against Tally:**

1. Open Gateway of Tally › Balance Sheet at the date on the page.
2. Compare each line and the two totals.
3. Expand Current Assets and Current Liabilities to ledgers (Alt+F1).
4. Add the balances as the hover shows. Compare the current ratio.

## 7. Stock

**Purpose:** The page shows the stock value, the stock by group and godown, and each item.

**Filters:** None. Use the filter of the table, or open an item.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Stock value (key card) | The closing stock at the last statement date, with a line of the dates. | F-STK-007 |
| Stock items (key card) | The number of stock items. | F-STK-009 |
| Items with negative stock (key card) | The number of items with a closing quantity below zero. | F-STK-004 |
| Stock value at the stored dates (chart) | The closing stock at each statement date. | F-STK-007 |
| By stock group, by godown (horizontal bars) | The value of each group and godown. | F-STK-005 |
| Stock items (table) | Opening, inward, outward, closing, value and rate of each item. | F-STK-001 to F-STK-006 |
| Page of an item | Closing quantity, value and rate (key cards), each movement and each month. | F-STK-001 to F-STK-008 |

**Drill-downs:** Click an item to open its page. A voucher number has no link yet.

**Loading and errors:** As section 1.5, with key cards, a chart and table rows.

**Check against Tally:**

1. Open Gateway of Tally › Stock Summary at the date on the page.
2. Compare the quantities, the values and the rates.
3. For godowns, open the Godown Summary.

## 8. Cash Flow

**Purpose:** The page shows the cash and bank at the start and the end of the period, and the money in and out by category.

**Filters:** None.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Cash & bank at the start (key card) | The balance on the day before the period start. | F-BAL-002 |
| Money in, money out (key cards) | The totals of the period, with a line of the months. | F-CF-001, F-CF-002 |
| Cash & bank at the end (key card) | The balance at the period end. | F-BAL-002 |
| From the opening to the closing (chart) | A waterfall from the opening, through each category, to the closing. | F-CF-001 |
| Money in and out by month (chart) | Bars for each month. | F-CF-002 |
| By what it was for (table) | In, out and net for each category. | F-CF-001 |

**Drill-downs:** None.

**Loading and errors:** As section 1.5, with four key cards, a chart and a table.

**Check against Tally:**

1. Open Display More Reports › Account Books › Cash/Bank Book(s).
2. Set the same period.
3. Compare the opening, the inward total, the outward total and the closing.

## 9. Parties

The module has two pages: Receivables and Payables.

**Purpose:** The pages show the amounts that customers must pay us and that we must pay vendors, by days past the due date.

**Filters:** None. Use the filter of the table, or open a party.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Balance due (key card) | The total at the period end. | F-PTY-001 |
| Overdue (key card) | The bills past their due date. | F-PTY-002 |
| Over 90 days (key card) | The bills more than 90 days past their due date. | F-PTY-012 |
| Not in bills (key card) | The balance that is not in bills. | F-PTY-013 |
| Outstanding bills by days past due (horizontal bars) | Not due, 1–30, 31–60, 61–90 and more than 90 days. | F-PTY-012 |
| Parties (table) | Each party with its balance, buckets, status and meaning. | F-PTY-001, F-PTY-012, F-PTY-013 |

**Drill-downs:** Click a party to open its page (section 3.5).

**Loading and errors:** As section 1.5, with four key cards, bars and a table.

**Check against Tally:**

1. Open Statements of Accounts › Outstandings › Ageing Analysis.
2. Set the same date and select ageing by due date.
3. Compare each bucket and each party.

## 10. Books

The module has one page: Transactions.

**Purpose:** The page lists each ledger line of the period.

**Filters:** None. Use the filter of the table, or group it.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Transactions (table) | Date, voucher type, voucher number, ledger, debit, credit, party, narration, cheque number, order number and more columns that you can show. | F-TRN-001, F-TBL-001 |

**Drill-downs:** A voucher number has no link yet. The voucher page is planned.

**Loading and errors:** As section 1.5, with table rows.

**Check against Tally:**

1. Open Display More Reports › Day Book.
2. Set the same dates.
3. Show the details (Alt+F1). Compare the lines.

## 11. Data

The module has two pages: Data health and Companies.

**Purpose:** The pages show if the data is complete and correct, and which companies the dashboard shows.

**Filters:** None. Data health covers each company.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Companies (key card) | The number of companies on the page. | F-DAT-001 |
| Checks passed (key card) | The companies with a passed validation. | F-DAT-002 |
| Loaded in the source (key card) | The companies that the source had loaded. | F-DAT-003 |
| Last sync (key card) | The time of the last sync. | F-DAT-004 |
| Data health by company (table) | Each company with its last sync and the status of its checks. It also shows the date that the checks cover and the status in the source. | F-DAT-002 to F-DAT-004 |
| Companies (table) | Each company with its name, code, start of the books, first month of the financial year and source. | None (no figures) |

**Drill-downs:** None.

**Loading and errors:** As section 1.5, with key cards and table rows.

**Check against Tally:**

1. Open TallyPrime and press F3. Compare the loaded companies.
2. Run `./dev.ps1 report`. Compare the validation of each company.

## Change log

| Version | Date | Change |
| --- | --- | --- |
| 1.0 | 2026-11-11 | First version: each page in the order of the top tabs, with its contents, formula IDs, drill-downs, loading and errors, and the check against Tally. |
