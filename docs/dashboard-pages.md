# Dashboard pages

This document tells you what each page of the dashboard shows and how to check it against Tally.

| Field | Value |
| --- | --- |
| Version | 1.5 |
| Date | 2026-11-12 |
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
| Status pill | A word for the state of a company on Data health. Hover it to see its meaning. |
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

The tables do not have a Status column or a Meaning column. Hover the name of a party, the number of an invoice or the name of a bill to see its payment status and its meaning. A dotted line under the name shows that it has this text. The CSV file does not contain the status. Only Data health has status columns, because the status is the purpose of that page.

### 1.5 Loading and errors

All pages load and show errors in the same way:

- While data loads, the page shows grey shapes of its parts: key cards, charts, table rows and ratio tiles. The layout does not move when the data comes.
- The shapes show only when the load takes more than 150 ms. A fast load does not flicker.
- The shapes pulse slowly in the colours of the theme. With the "reduce motion" setting of your system, they do not move.
- The loading area has `aria-busy`. A screen reader says "Loading…".
- When a request fails, the page shows what failed and why. Click **Retry** to send the request again.

### 1.6 The note at the top of each page

Each page has a small box at the top with the title "About this page" (or a title that tells what it explains). The box tells you what the page shows, where the figures come from and how the page works them out. It also tells you what can surprise you and which report of Tally to compare with.

The box is open the first time. Click its title, or press Enter or Space on it, to close it or to open it again. The browser keeps your choice for each page. A test fails if a page has no box.

### 1.7 How to check a page against Tally

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

**Note at the top of the page.** The box says:

- The page shows the business at a glance: sales, profit, cash and bank, and customers. It also shows the months, the channels, the Profit & Loss against last year and the top customers.
- Sales, purchases and customers come from the vouchers of the period (F-SAL-004, F-PUR-001, F-SAL-011). Cash and bank is the balance at the end of the period (F-BAL-002).
- Profit comes from our stored Profit & Loss statements (F-PL-003, F-PL-004). It goes to the last statement date in the period.
- In Educational mode, a month that ends on the 30th goes to the 2nd of the next month.
- The page adds the companies without inter-company eliminations.
- To compare, use the Profit & Loss A/c, the Sales Register and the Balance Sheet of Tally.

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
| Top customers (table) | The ten largest customers with their share and balance due. Hover a name to see the payment status. | F-OVR-002, F-OVR-004, F-PTY-001 |

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

**Note at the top of the page.** The box says:

- The page shows the sales of the period: net sales, invoices, average invoice and returns, by month and by company. It also shows the channels, the top customers and the largest invoices.
- The figures come from the vouchers on the ledgers under Sales Accounts. They do not need stored statements.
- Net sales are gross sales plus returns plus other adjustments (F-SAL-001 to F-SAL-004). The average invoice is gross sales divided by the invoices (F-SAL-006).
- The filters for customer and channel change each figure. The page adds the companies without inter-company eliminations.
- To compare, use the Sales Register of Tally and the Sales Accounts line of the Profit & Loss A/c.

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
| Top customers (table) | The customers with the largest net sales. Hover a name to see the payment status. | F-SAL-012, F-SAL-013, F-OVR-004 |
| Largest invoices (table) | The invoices with the largest amounts. | F-SAL-014 |

**Drill-downs:**

| Click | Opens |
| --- | --- |
| A month in the chart or in the table | The Sales register for that month. |
| A channel in the donut | The Sales register for that channel. |
| A customer | The page of that customer. |
| An invoice number | The page of the voucher (section 10.2). |

**Loading and errors:** As section 1.5, with four key cards, a chart and a table.

**Check against Tally:**

1. Open the Sales Register for the period. Compare gross sales and the number of invoices.
2. Open the Credit Note Register. Compare the returns.
3. Open the Profit & Loss A/c. Compare net sales with the Sales Accounts line.

### 3.2 Sales register

**Purpose:** The page lists each sales invoice and credit note, as the Day Book of Tally shows them.

**Note at the top of the page.** The box says:

- The page shows each sales invoice and credit note of the period, as the Day Book shows them, by month.
- Debit and credit are the first line of the voucher, usually the party (F-REG-001).
- Value is only the lines on the ledgers under Sales Accounts (F-REG-002). It does not include taxes and freight.
- The page does not show cancelled and optional vouchers.
- To compare, use the Sales Register of Tally.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Register (table) | Date, particulars, voucher type, voucher number, debit, credit, value and narration. Grouped by month, with subtotals. | F-REG-001, F-REG-002, F-TBL-001, F-TBL-002 |

**Drill-downs:** Click a voucher number to open the page of the voucher (section 10.2).

**Loading and errors:** As section 1.5, with table rows.

**Check against Tally:**

1. Open Account Books › Sales Register for the period.
2. Compare the vouchers and the total.

### 3.3 Monthly sales

**Purpose:** The page shows the sales of each month and the closing balance from the start of the financial year.

**Note at the top of the page.** The box says:

- The page shows the gross sales, returns, other adjustments, net sales and invoices of each month.
- The figures come from the vouchers on the ledgers under Sales Accounts (F-SAL-001 to F-SAL-005).
- The closing balance adds the net sales from the start of the financial year of each company (F-SAL-008).
- To compare, use the monthly Group Summary of Sales Accounts in Tally.

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

**Note at the top of the page.** The box says:

- The page shows the net sales of each channel, with a column for each month. A channel is a voucher type.
- The figures come from the vouchers on the ledgers under Sales Accounts (F-SAL-009, F-SAL-010).
- Voucher types with the same name in two companies are one channel.
- To compare, use the Sales Register of Tally for the same voucher type.

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

**Note at the top of the page.** The box says:

- The list shows each customer with sales in the period: net sales, invoices, the last invoice and the balance due (F-SAL-012, F-PTY-001).
- The page of a customer shows the balance, the overdue bills, the net sales, the days to pay and five tabs.
- The bills come from the opening bills and the bills of the vouchers, with their due dates (F-PTY-004).
- Amounts on account are not bills. Thus the bills can be less than the balance (F-PTY-013).
- A customer is identified by name in all the companies of the selection.
- To compare, use the ledger of the customer and Outstandings in Tally.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Customers (table) | Net sales, invoices, last invoice, balance due and companies. | F-SAL-012, F-SAL-005, F-PTY-001 |
| Balance due (key card) | The balance at the period end. | F-PTY-001 |
| Overdue (key card) | The bills past their due date. | F-PTY-002 |
| Net sales (key card) | The net sales of the customer, with a line of the months. | F-SAL-012 |
| Average days to pay (key card) | The days from bill to payment. | F-PTY-007 |
| Invoices (tab) | Each invoice. Hover its number to see its payment status and its days. | F-SAL-014, F-PTY-011 |
| Settlements (tab) | Each receipt. | F-PTY-006 |
| Statement (tab) | The ledger with a running balance. | F-PTY-008 to F-PTY-010 |
| Bills (tab) | Each outstanding bill with its due date. Hover a bill to see its payment status. | F-PTY-003 to F-PTY-005, F-PTY-013 |
| Monthly (tab) | Net sales and receipts for each month. | F-SAL-012, F-PTY-006 |

**Drill-downs:** Click a customer in the list to open its page. Click a voucher number to open the page of the voucher.

**Loading and errors:** As section 1.5, with table rows (the list) or key cards, a chart and a table (the page).

**Check against Tally:**

1. Open Account Books › Ledger of the customer. Compare the balance and the statement.
2. Open Outstandings › Ledger. Compare the bills and the overdue amount.

## 4. Purchases

The Purchases module has four pages: Purchases dashboard, Purchase register, Monthly purchases and Vendors. They work as the Sales pages, for purchases. Read the formula sheet section 4 for the words that change.

**Filters for the Purchases module:** Voucher type, except on the Vendors list.

**Note at the top of the page.** The box says:

- Each Purchases page has the note of the Sales page of the same name, for purchases.
- The figures come from the vouchers on the ledgers under Purchase Accounts.
- To compare, use the Purchase Register of Tally and the Purchase Accounts line of the Profit & Loss A/c.

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

**Note at the top of the page.** The box says:

- The page shows the margins, the cost structure, the months and the full Profit & Loss with the comparison period.
- Each line comes from our stored statements: the statement at the end of the period minus the statement before its start (F-PL-007).
- The margins and the cost structure are shares of net sales (F-PL-005, F-PL-006, F-PL-008, F-PL-010).
- "Matches Tally" shows only when each compared line is equal (F-CHK-001 to F-CHK-003).
- Profit needs the statements for those dates. In Educational mode, a month that ends on the 30th goes to the 2nd of the next month.
- To compare, use the Profit & Loss A/c of Tally.

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

**Note at the top of the page.** The box says:

- The list shows each cost centre with its allocations in the period, in total and month by month (F-CC-001, F-CC-003).
- The page of a cost centre shows each allocation (F-CC-002).
- A row shows only the allocations of that cost centre. Tally adds the cost centres below it.
- To compare, use the Category Summary of the cost centres in Tally.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Cost centres (table) | Each cost centre with its category, the centre above it, the total, the count and one column for each month. | F-CC-001, F-CC-003 |
| Page of a cost centre (table) | Each allocation with its date, voucher, ledger and amount. | F-CC-002 |

**Drill-downs:** Click a cost centre to open its page. Click a voucher number to open the page of the voucher.

**Loading and errors:** As section 1.5, with table rows.

**Check against Tally:**

1. Open Statements of Accounts › Cost Centres › Category Summary.
2. Set the same period.
3. Compare each cost centre. Tally includes the centres below it.

## 6. Balance Sheet

**Purpose:** The page shows the Balance Sheet at the period end, against the end of the comparison period, with the ratios.

**Filters:** None. A statement covers each customer, channel and voucher type.

**Note at the top of the page.** The box says:

- The page shows the Balance Sheet at the end of the period and at the end of the comparison period, with the ratios.
- The lines come from our stored Balance Sheet at the last statement date in the period (F-BS-005).
- The ratios follow Schedule III (F-RAT-008 to F-RAT-010). Hover a ratio to see its parts.
- Thus the ratios can be different from the Ratio Analysis of Tally.
- The page adds the companies without inter-company eliminations.
- To compare, use the Balance Sheet of Tally at the same date.

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

The module has two pages: Stock summary and By godown. Each item has its own page.

**Filters for the Stock module:** None. Use the filter of the table, or open an item.

### 7.1 Stock summary

**Purpose:** The page shows the stock value, the stock by group and godown, and each item.

**Note at the top of the page.** The box says:

- The page shows each stock item with its quantities, value and rate, and the stock value by date, group and godown.
- The quantities come from the vouchers. The tests check them against Tally item by item (F-STK-001 to F-STK-004).
- The values are the values of Tally at the last statement date in the period (F-STK-005 to F-STK-007).
- Stock at the godown of a job worker is not counted, as in Tally.
- To compare, use the Stock Summary of Tally at the same date.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Stock value (key card) | The closing stock at the last statement date, with a line of the dates. | F-STK-007 |
| Stock items (key card) | The number of stock items. | F-STK-009 |
| Items with negative stock (key card) | The number of items with a closing quantity below zero. | F-STK-004 |
| Stock value at the stored dates (chart) | The closing stock at each statement date. | F-STK-007 |
| By stock group, by godown (horizontal bars) | The value of each group and godown. | F-STK-005 |
| Stock items (table) | Opening, inward, outward, closing, value and rate of each item. | F-STK-001 to F-STK-006 |

**Drill-downs:** Click an item to open its page.

**Loading and errors:** As section 1.5, with key cards, a chart and table rows.

**Check against Tally:**

1. Open Gateway of Tally › Stock Summary at the date on the page.
2. Compare the quantities, the values and the rates.
3. For godowns, open the Godown Summary.

### 7.2 By godown

**Purpose:** The page shows where each item is at the end of the period: at each godown and batch, in three sections.

**Sections:**

| Section | What it holds | In the total |
| --- | --- | --- |
| Our stock | Our stock in our own godowns. | Yes. |
| Others' stock held with us (not ours) | Stock of others in our godowns. | Yes. The Stock Summary of Tally includes it. |
| Our stock at job workers (still ours) | Our stock at the godown of a job worker. | No. Tally leaves it out of the Stock Summary. Tally records there only what the job worker used, so the quantity can be negative. |

The total is equal to the Stock summary page and to the Stock Summary of Tally. The tests prove this on the test company.

**Note at the top of the page.** A small box with the title "How this page divides stock" explains the three sections. The box is open the first time. Click its title to close it or to open it again. The browser keeps your choice. The box says:

- Our stock: stock that we keep in our own godowns. It is in the total.
- Others' stock held with us (not ours): goods of other companies that we keep in our godowns. The Stock Summary of Tally counts them, so the total counts them too.
- Our stock at job workers (still ours): material that we sent out for processing. It is still ours. Tally keeps it at the godown that sent it. Tally records here only what the job worker used. Thus the quantity can be negative, and it is not in the total.
- The total on the page is equal to the Stock Summary of Tally at the same date.
- The value of each row is the quantity multiplied by the rate of the item. The value of each godown in Tally shows beside the rows.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Stock in the total (key card) | The quantity of our stock and of the stock of others held with us. | F-STK-013 |
| Value in the total (key card) | The value of that stock. | F-STK-013 |
| Others' stock held with us (key card) | The quantity of that section. | F-STK-012 |
| Our stock at job workers (key card) | The quantity of that section. | F-STK-012 |
| One table for each section | Item, godown, batch, quantity and value. The table is grouped by godown. Each section shows its total and if it is in the total. | F-STK-010, F-STK-011, F-STK-012 |
| Value by godown (table) | The value of each godown as Tally calculates it. | F-STK-005 |

A row value is the quantity multiplied by the rate of the item. Tally does not keep a value for each item at each godown. The rows of an item add up to its value on the Stock summary page. Rows at a job worker have no value. An opening that Tally does not split by godown shows as "(opening, not split by godown)".

**Drill-downs:** Click an item or a godown to open the page of the item at that godown.

**Loading and errors:** As section 1.5, with key cards and table rows.

**Check against Tally:**

1. Open Gateway of Tally › Stock Summary at the date on the page. Compare the total.
2. Open the Godown Summary at the same date.
3. Compare each godown with its rows.
4. For a job worker, compare the quantity of its godown. It is not in the Stock Summary.

### 7.3 Page of an item

**Purpose:** The page shows one item: its figures, each movement, each month, and where it is.

**Note at the top of the page.** The box says:

- The page shows one item: its figures, each movement, each month and the item at each godown and batch.
- The quantities come from the vouchers (F-STK-001 to F-STK-004). The values are the values of Tally (F-STK-005).
- The other godown of a movement is where the stock went, or where it came from.
- At one godown, a month has no value, because Tally keeps no value for each item at each godown.
- To compare, use the Stock Item Monthly Summary of Tally.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Closing quantity, value, rate (key cards) | The figures of the item at the end of the period. | F-STK-004 to F-STK-006 |
| Movements (tab) | Each movement with its godown, its other godown and the quantity after it. The other godown is where the stock went, or where it came from. | F-STK-002, F-STK-004, F-STK-008 |
| Month by month (tab) | In, out, closing quantity and value for each month. | F-STK-002 to F-STK-005 |
| By godown and batch (tab) | The item at each godown and batch, in the three sections of section 7.2. | F-STK-010 to F-STK-012 |

**One godown.** A link from section 7.2 opens the item at one godown. The page then shows "At" and the godown. The movements and the months are only at that godown. A month then has no value, because Tally keeps no value for each item at each godown. The key cards show the whole item. Click "Show every godown" to see all godowns again.

**Drill-downs:** Click a voucher number to open the page of the voucher (section 10.2).

**Loading and errors:** As section 1.5, with key cards and table rows.

**Check against Tally:**

1. Open Stock Summary › the item › Stock Item Monthly Summary for the same period.
2. For one godown, open the Godown Summary and select the godown and the item.

### 7.4 Inventory lines dataset

The table explorer API has a dataset of inventory lines (`/api/v1/datasets/inventory_lines`). It has one row for each inventory line of a voucher that moves stock. The dashboard has no page for the datasets yet.

| Columns | Formula IDs |
| --- | --- |
| Date, voucher type, voucher number, item, godown, holding, batch, other godown, order number, order due date | None (no figures) |
| Quantity | F-STK-014 |
| Rate | F-STK-015 |
| Amount | F-STK-008 |
| Lines | F-TBL-001 |

You can group the rows by item, godown, holding, batch, other godown, order number, voucher type, month, quarter and financial year. For each item, the opening plus the quantities up to a date is the closing quantity. Do not count the rows with the holding "Our stock at job workers".

## 8. Cash Flow

**Purpose:** The page shows the cash and bank at the start and the end of the period, and the money in and out by category.

**Filters:** None.

**Note at the top of the page.** The box says:

- The page shows the cash and bank at the start and at the end, and the money in and out by category and by month.
- The start plus the money in minus the money out is the end (F-CF-001, F-BAL-002).
- Each amount goes to the category of the other ledgers of its voucher.
- A move between cash and bank adds nothing. Bank OD accounts are loans, not cash.
- To compare, use the Cash/Bank Book(s) of Tally.

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

**Purpose:** The pages show the amounts that customers must pay us, or that we must pay vendors, at the end of the period. The pages show the amounts party by party and bill by bill.

**Filters and controls:** No filters. Use the filter of a table, or open a party. The control "Age by" selects the age of a bill: the days past its due date, or the days since its bill date.

**Note at the top of the page.** A small box with the title "How ageing is worked out" explains the page. The box is open the first time. Click its title to close it or to open it again. The browser keeps your choice. The box says:

- The page shows what the customers owe us (or what we owe the vendors) at the end of the period. The amounts come from the bills in Tally.
- The age of a bill is the number of days after its due date. A bill with no due date is due on its bill date plus the credit days of the party.
- The bills go into six groups: not due, 1–30, 31–60, 61–90, 91–180 and more than 180 days. A bill is overdue only after its due date.
- "Not in bills" is the part of the balance that no bill explains.
- The total is equal to the Sundry Debtors (or Sundry Creditors) balance on the Balance Sheet of Tally at the same date. The page adds the companies without inter-company eliminations.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Total outstanding (key card) | The total at the end of the period. It is equal to the Sundry Debtors (or Sundry Creditors) line of the Balance Sheet. | F-PTY-001 |
| Overdue (key card) | The bills after their due date. | F-PTY-002 |
| Over 90 days (key card) | The bills that are more than 90 days old. | F-PTY-018 |
| Average days to pay (key card) | The days from the bill date to the payment, for the bills paid in the period. | F-PTY-019 |
| Outstanding bills by age (horizontal bars) | The six groups of age, with the control "Age by". | F-PTY-014 |
| Not in bills (table) | Four parts, each with its meaning: on account, opening-bill difference, exchange-rate revaluation and other. Then the total. | F-PTY-013, F-PTY-015, F-PTY-016, F-PTY-017, F-PTY-020 |
| Parties (table) | Each party with its balance, its six groups and the part not in bills. Hover a name to see the payment status and its meaning. | F-PTY-001, F-PTY-013, F-PTY-014 |
| Outstanding bills (table) | Each open bill with its party, name, bill date, due date, age, days and amount. | F-PTY-004, F-PTY-005, F-PTY-014 |

**Exchange-rate revaluation.** For a party in a foreign currency, Tally shows the balance at the current rate. The page uses the same balance. The bills stay at their amounts in the books. Thus the difference goes into "Not in bills".

**Drill-downs:**

| Click | Opens |
| --- | --- |
| A party | The page of the party (section 3.5). |
| A bill | The page of the voucher that made the bill (section 10.2). An opening bill has no voucher. |

**Loading and errors:** As section 1.5, with four key cards, bars and tables.

**Check against Tally:**

1. Open Gateway of Tally › Balance Sheet at the same date. Compare the total with Sundry Debtors (or Sundry Creditors).
2. Open Statements of Accounts › Outstandings › Ageing Analysis.
3. Set the same date and select ageing by due date (or by bill date).
4. Compare each group and each party.

## 10. Books

The module has the page Transactions. Each voucher also has its own page.

**Filters for the Books module:** None. Use the filter of the table, or group it.

### 10.1 Transactions

**Purpose:** The page lists each ledger line of the period.

**Note at the top of the page.** The box says:

- The page shows each ledger line of the period, with its voucher, ledger, debit or credit and party.
- A positive amount is a debit. A negative amount is a credit (F-TRN-001).
- The page does not show cancelled and optional vouchers. It does not show the UTR.
- To compare, use the Day Book of Tally with details (Alt+F1).

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Transactions (table) | Date, voucher type, voucher number, ledger, debit, credit, party, narration, cheque number, order number and more columns that you can show. | F-TRN-001, F-TBL-001 |

**Drill-downs:** Click a voucher number to open the page of the voucher (section 10.2).

**Loading and errors:** As section 1.5, with table rows.

**Check against Tally:**

1. Open Display More Reports › Day Book.
2. Set the same dates.
3. Show the details (Alt+F1). Compare the lines.

### 10.2 Page of a voucher

**Purpose:** The page shows one voucher as Tally keeps it.

**How to open it:** Click a voucher number in a register or in Transactions. The pages of a stock item, a cost centre and a party also link to vouchers. You can also click a bill on Receivables or Payables. The page has no tab of its own.

**Note at the top of the page.** The box says:

- The page shows one voucher as Tally keeps it: its header, ledger lines, bills and stock lines.
- The debits and the credits of the lines are equal (F-VCH-001).
- A cancelled voucher has no lines. An optional voucher does not change the books.
- To compare, open the same voucher in the Day Book of Tally.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Voucher | Date, voucher type, voucher number, party, reference, company and narration. Then the total of the debits and the total of the credits. The two totals are equal. | F-VCH-001 |
| Ledger lines (table) | Each ledger with its debit or credit, and the cheque number. | F-TRN-001 |
| Bills (table) | The bills that the voucher makes or settles: the type, the bill, its dates and its amount. | F-TRN-001 |
| Stock (table) | Each stock line with its godown, other godown, batch, quantity, rate and amount. | F-STK-008, F-STK-014, F-STK-015 |

A cancelled voucher has no lines. An optional voucher does not change the books. The page tells you when this is so.

**Drill-downs:** Click a stock item to open its page.

**Loading and errors:** As section 1.5, with table rows. A voucher that is not in your companies shows an error.

**Check against Tally:**

1. Open Display More Reports › Day Book at the date of the voucher.
2. Open the voucher. Compare the lines, the bills and the stock.

## 11. Data

The module has three pages: Data health, Explore and Companies.

**Filters for the Data module:** None. Data health covers each company. Explore has its own filters.

### 11.1 Data health and Companies

**Purpose:** The pages show if the data is complete and correct, and which companies the dashboard shows.

**Note at the top of the page.** The box says:

- Data health shows the last sync, the checks and the status in Tally for each company (F-DAT-001 to F-DAT-004).
- The checks compare our figures with the figures of Tally, at the date that the page shows.
- Companies shows each company with the start of its books and its financial year. The name can be a display name, not the name in Tally.
- The pages do not show companies on hold.
- To compare, run ./dev.ps1 report, and press F3 in Tally.

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Companies (key card) | The number of companies on the page. | F-DAT-001 |
| Checks passed (key card) | The companies with a passed validation. | F-DAT-002 |
| Loaded in the source (key card) | The companies that the source had loaded. | F-DAT-003 |
| Last sync (key card) | The time of the last sync. | F-DAT-004 |
| Data health by company (table) | Each company with its last sync and the status of its checks. It also shows the date that the checks cover and the status in the source. Hover a status to see its meaning. | F-DAT-002 to F-DAT-004 |
| Companies (table) | Each company with its name, code, start of the books, first month of the financial year and source. | None (no figures) |

**Drill-downs:** None.

**Loading and errors:** As section 1.5, with key cards and table rows.

**Check against Tally:**

1. Open TallyPrime and press F3. Compare the loaded companies.
2. Run `./dev.ps1 report`. Compare the validation of each company.

### 11.2 Explore

**Purpose:** The page shows the datasets of the table explorer: voucher lines, vouchers, cost allocations, GST lines and inventory lines.

**Note at the top of the page.** A small box with the title "How this page works" explains the page. It is open the first time. The browser keeps your choice to close it.

**Controls:**

| Control | What it does |
| --- | --- |
| Dataset | Selects the dataset. |
| Group by | Groups the rows by up to four columns. The page then shows a subtotal for each group and a total. |
| Columns | Selects the columns when the rows are not grouped. |
| Measures | Selects the figures to show, for example debit and credit. |
| Sort by | Sorts the rows by a column or a measure. |
| Filters | Limit the rows: dates, amounts, and lists such as ledgers, parties, items or godowns. The dates follow the period in the top bar, unless you set them on the page. |
| Export CSV | Gives the same result as a file, with the subtotals and the total. |
| Save view | Keeps the choices with a name in this browser. Select a saved view to open the same choices again. |
| Previous, Next | Show the next page of 100 rows. |

**Contents:**

| Item | What it shows | Formula IDs |
| --- | --- | --- |
| Result (table) | The rows, the subtotals and the total. Each measure shows its formula ID in its column header. | F-TBL-001, F-TBL-002, F-TBL-003, F-TRN-001, F-CC-002, F-CC-003, F-STK-008, F-STK-014, F-STK-015 |

**Drill-downs:** None.

**Loading and errors:** As section 1.5, with table rows.

**Check against Tally:**

1. Open the Day Book or the register of the same vouchers.
2. Set the same dates.
3. Compare the totals.

## Change log

| Version | Date | Change |
| --- | --- | --- |
| 1.5 | 2026-11-12 | No Status column and no Meaning column in the tables (section 1.4). The status is on hover. Data health keeps its status columns. |
| 1.4 | 2026-11-12 | A note at the top of each page (section 1.6), and the text of each note in its page section. |
| 1.3 | 2026-11-12 | Parties: six groups of age, the age by bill date, the parts not in bills, the bills and the note. The page of a voucher. Data › Explore. |
| 1.2 | 2026-11-11 | Stock › By godown: the note "How this page divides stock". |
| 1.1 | 2026-11-11 | Stock: the By godown page and the page of an item at one godown. The inventory lines dataset. |
| 1.0 | 2026-11-11 | First version: each page in the order of the top tabs, with its contents, formula IDs, drill-downs, loading and errors, and the check against Tally. |
