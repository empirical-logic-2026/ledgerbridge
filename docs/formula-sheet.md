# Formula sheet

This sheet gives the formula of each figure that the dashboard shows. Use it to check a figure against the books or against Tally.

| Field | Value |
| --- | --- |
| Version | 2.1 |
| Date | 2026-11-11 |
| Requirement | RPT-015 |
| Language | ASD-STE100 Simplified Technical English |
| Word and PDF | `docs/export/formula-sheet.docx`, `docs/export/formula-sheet.pdf` (`./dev.ps1 docs-export`) |
| Related | [dashboard-pages.md](dashboard-pages.md) (each page and its figures) |

## 1. How to use this sheet

Each figure has a **formula ID**, for example `F-PL-003`. The dashboard shows the ID in the hover text of the figure. Find the ID in this sheet to read the formula.

Each entry has these items:

| Item | What it gives |
| --- | --- |
| Expression | The formula as an expression. |
| In words | The formula as text. |
| Data | The view or table, the columns and the group roles that the formula reads. |
| Signs | The sign rule. Section 3.1 gives the common sign rules. |
| Dates | The date rule. Section 3.2 gives the common date rules, with Educational mode. |
| Companies | The rule for one company and for combined companies. Section 3.3 gives the common rules. |
| Check in Tally | The steps to find the same figure in TallyPrime. |

**Rules for IDs:**

- The code that calculates a figure names its ID. The tests that prove the figure also name the ID.
- `data-plane/tests/test_formulas.py` fails when an API figure has no ID, or when an ID has no entry in this sheet.
- `frontend/src/App.test.tsx` fails when a figure on a page has no ID, or when its ID has no entry in this sheet.
- We never use an ID again for a different formula. A retired formula keeps its entry, with "(retired)" in its heading. No code can use a retired ID.

**Areas:**

| Prefix | Area |
| --- | --- |
| `F-SAL` | Sales, and purchases on the purchase side |
| `F-PUR` | Purchases |
| `F-PL` | Profit & Loss |
| `F-BS` | Balance Sheet |
| `F-RAT` | Ratios |
| `F-BAL` | Balances |
| `F-CF` | Cash movement |
| `F-CC` | Cost centres |
| `F-STK` | Stock |
| `F-TRN` | Transactions |
| `F-PTY` | Parties and bills |
| `F-REG` | Registers |
| `F-OVR` | Overview |
| `F-CMP` | Comparisons |
| `F-CHK` | Checks against the source |
| `F-DAT` | Data health |
| `F-TBL` | Tables |
| `F-FMT` | How the dashboard shows amounts |

## 2. Terms

Each term has one meaning in this sheet and in [dashboard-pages.md](dashboard-pages.md).

| Term | Meaning |
| --- | --- |
| Source | The accounting system that the data comes from. For the pilot, the source is TallyPrime ("Tally"). |
| Company | One set of books in the source. The database calls it an entity. |
| Selection | The companies that the user selects in the page header. |
| Combined | Two or more companies in the selection, added together. |
| Ledger | An account in the books. |
| Group | A group of ledgers. A group can contain other groups. |
| Primary group | A group at the top level of the chart of accounts. |
| Predefined role | The fixed name of a group that the source supplies, for example `sales_accounts`. The column is `account_groups.predefined_role`. |
| Ledgers under a group | The ledgers in a group, or in a group below it at any depth. We find a group by its predefined role, not by its name. The view is `v_group_ancestors`. |
| Stored amount | An amount as the database keeps it. A debit is positive. A credit is negative. |
| Debit balance | A ledger balance that is more than zero (stored amount). |
| Credit balance | A ledger balance that is less than zero (stored amount). |
| Effective entry | A voucher line that changes the books. The line has `voucher_lines.is_effective = 1` and its voucher has `vouchers.is_deleted = 0`. A cancelled or optional voucher has no effective entries. |
| Balance at a date | The opening balance of a ledger plus its effective entries up to and including the date. |
| Period | The months or the dates that the user selects with the period toggles. |
| Period start | The first day of the period. |
| Period end | The last day of the period. |
| Comparison period | The period that the dashboard compares with the period. Formula F-CMP-002 gives it. |
| Statement | A Profit & Loss or a Balance Sheet. |
| Stored statement | A statement that we calculate from the books and keep in `statement_lines` (`figures = 'ours'`). We compare each line with the statement of the source. |
| Statement date | A date with a stored statement. `./dev.ps1 statements` stores the month ends. |
| Line | One row of a statement. |
| Main line | A line for a primary group (`level = 'main'`). |
| Closing stock | The value of the stock at a date, as the source calculates it. The table is `stock_values`. |
| Educational mode | A mode of TallyPrime. In this mode, a report can only use the 1st, the 2nd or the 31st day of a month. |
| Party | A customer or a vendor. We identify a party by its name in all companies of the selection. |
| Bill | An amount that a party must pay, or that we must pay, with a name and a due date. |
| Due date | The date when a bill must be paid. |
| Outstanding bill | The part of a bill that is not paid at a date. |
| Lakh | One hundred thousand rupees (₹1,00,000). |
| Figure | A number that the dashboard shows. |

## 3. Common rules

### 3.1 Signs

| Rule | Text |
| --- | --- |
| S1 | The stored amount is positive for a debit and negative for a credit. |
| S2 | The dashboard shows sales, incomes and credits to a party as positive numbers. It multiplies the stored amount by −1. |
| S3 | The dashboard shows purchases, costs and debits as positive numbers. It uses the stored amount. |
| S4 | A profit is positive. A loss is negative. |
| S5 | A count, a percentage, a ratio or a number of days has no debit or credit. |

### 3.2 Dates

| Rule | Text |
| --- | --- |
| D1 | **Entries.** The formula reads effective entries with a voucher date in the period. Entries are correct for each date, so Educational mode has no effect. |
| D2 | **Balance at a date.** The formula reads the balance at the period end. Educational mode has no effect. |
| D3 | **Statement for a period.** The figure is the line at the period end minus the line on the day before the period start. At the start of the books, there is nothing to subtract. For two or more months, the formula adds each month. |
| D4 | **Statement at a date.** The figure is the line at one date. The formula never subtracts two dates. |
| D5 | **Which statement date.** For a month, the formula uses the statement on its last day. If that statement is not stored, it uses the first stored date that is not more than 2 days later. For a date range, it uses the end date if it is stored. If not, it uses the last statement date in the range. The page then shows "to" and that date. With no statement date in the period, the figure is "—" with the reason. |
| D6 | **Educational mode.** In Educational mode, Tally cannot use the 30th or the 28th as a report date. The stored month end for a month of 30 days, and for February, is then the 2nd of the next month. The page shows a note about this. To check in Tally, use the same dates. |
| D7 | **Stock values.** The source supplies stock values only on statement dates. Rules D5 and D6 apply. |

### 3.3 Companies

| Rule | Text |
| --- | --- |
| C1 | **Combined companies.** The formula calculates each company and adds the results. It does not remove amounts between the companies (no inter-company eliminations). |
| C2 | **Parties, items and cost centres.** The formula identifies them by name in all companies of the selection. |
| C3 | **Financial year.** Each company uses its own financial year. |
| C4 | **Ratios and percentages.** The formula adds the parts of all companies first. Then it divides. |

### 3.4 Precision

The database keeps amounts as `DECIMAL(20,4)`. The code uses exact decimals: `Decimal` in Python and BigInt in the browser. Charts use numbers in lakhs, only to draw (F-FMT-003). The dashboard rounds an amount only when it shows the amount.

## 4. Sales and purchases (`F-SAL`, `F-PUR`)

These formulas define the monthly sales views (`v_monthly_sales`, `v_monthly_sales_by_voucher_type`). The tests prove them against the Sales Accounts line of the source.

For purchases, read these words in each `F-SAL` entry:

| For sales | For purchases |
| --- | --- |
| Sales Accounts (`sales_accounts`) | Purchase Accounts (`purchase_accounts`) |
| Sales invoice (base type `sales`) | Purchase invoice (base type `purchase`) |
| Credit note (base type `credit_note`) | Debit note (base type `debit_note`) |
| Sign rule S2 | Sign rule S3 |

**Data for each `F-SAL` entry:** `voucher_lines` (`amount`, `ledger_id`, `voucher_date`, `is_effective`), `vouchers` (`is_deleted`, `party_id`) and `voucher_types` (`base_type`, `name`). The formulas read the ledgers under `sales_accounts`.

#### F-SAL-001 Gross sales

| Item | Value |
| --- | --- |
| Expression | `−Σ amount`, where base type = `sales` |
| In words | The entries of sales invoices on the ledgers under Sales Accounts. |
| Data | As for each `F-SAL` entry. |
| Signs | S1, S2. A sale is a credit. |
| Dates | D1. |
| Companies | C1. |
| Check in Tally | 1. Open Display More Reports › Account Books › Sales Register. 2. Set the same period (F2). 3. Read the total. |

#### F-SAL-002 Sales returns

| Item | Value |
| --- | --- |
| Expression | `−Σ amount`, where base type = `credit_note` |
| In words | The entries of credit notes on the ledgers under Sales Accounts. The figure is negative. |
| Data | As for each `F-SAL` entry. |
| Signs | S1, S2. A return is a debit to sales, so the figure is negative. |
| Dates | D1. |
| Companies | C1. |
| Check in Tally | 1. Open Account Books › Credit Note Register. 2. Set the same period. 3. Read the total. |

#### F-SAL-003 Other adjustments

| Item | Value |
| --- | --- |
| Expression | `−Σ amount`, where base type is not `sales` and not `credit_note` |
| In words | The entries of all other vouchers on the ledgers under Sales Accounts, for example journals. |
| Data | As for each `F-SAL` entry. |
| Signs | S1, S2. |
| Dates | D1. |
| Companies | C1. |
| Check in Tally | 1. Open Account Books › Group Vouchers. 2. Select Sales Accounts. 3. Do not count sales invoices and credit notes. |

#### F-SAL-004 Net sales

| Item | Value |
| --- | --- |
| Expression | `F-SAL-001 + F-SAL-002 + F-SAL-003` = `−Σ amount` on the ledgers under Sales Accounts |
| In words | Gross sales, plus sales returns, plus other adjustments. The dashboard shows net sales for each month, company and party. |
| Data | As for each `F-SAL` entry. |
| Signs | S1, S2. |
| Dates | D1. |
| Companies | C1. |
| Check in Tally | 1. Open Gateway of Tally › Profit & Loss A/c. 2. Set the same period. 3. Read the Sales Accounts line. |

#### F-SAL-005 Invoices

| Item | Value |
| --- | --- |
| Expression | `COUNT(DISTINCT voucher)`, where base type = `sales` |
| In words | The number of sales invoices with an entry on the ledgers under Sales Accounts. |
| Data | As for each `F-SAL` entry. |
| Signs | S5. |
| Dates | D1. |
| Companies | C1. |
| Check in Tally | 1. Open the Sales Register for the same period. 2. Count the vouchers. |

#### F-SAL-006 Average invoice

| Item | Value |
| --- | --- |
| Expression | `F-SAL-001 ÷ F-SAL-005`, to the paisa |
| In words | Gross sales for each invoice. With no invoices, the figure is "—". |
| Data | F-SAL-001 and F-SAL-005. |
| Signs | S2. |
| Dates | D1. |
| Companies | C1, C4. |
| Check in Tally | 1. Read the Sales Register total. 2. Divide it by the number of vouchers. |

#### F-SAL-007 Returns (key figure)

| Item | Value |
| --- | --- |
| Expression | `−F-SAL-002` |
| In words | The sales returns as a positive number. A lower number is better. |
| Data | F-SAL-002. |
| Signs | Positive. |
| Dates | D1. |
| Companies | C1. |
| Check in Tally | 1. Open the Credit Note Register for the same period. 2. Read the total. |

#### F-SAL-008 Closing balance (monthly)

| Item | Value |
| --- | --- |
| Expression | `Σ F-SAL-004`, from the first month of the financial year to the month |
| In words | The net sales from the start of the financial year to the end of the month. |
| Data | F-SAL-004. |
| Signs | S2. |
| Dates | D1. |
| Companies | C1, C3. Each company starts at its own financial year. |
| Check in Tally | 1. Open Account Books › Group Summary › Sales Accounts. 2. Open the monthly summary. 3. Read the Closing Balance column. |

#### F-SAL-009 Net sales by channel

| Item | Value |
| --- | --- |
| Expression | `F-SAL-004`, where `voucher_types.name` = the channel |
| In words | The net sales of one channel. A channel is one voucher type name. Voucher types with the same name in two companies are one channel. |
| Data | As for each `F-SAL` entry, with `voucher_types.name`. |
| Signs | S2. |
| Dates | D1. |
| Companies | C1, C2. |
| Check in Tally | 1. Open the Sales Register. 2. Select the voucher type. 3. Set the same period and read the total. |

On the Overview, the dashboard shows the four largest channels. It adds the other channels as "Others".

#### F-SAL-010 Channel share

| Item | Value |
| --- | --- |
| Expression | `F-SAL-009 ÷ Σ F-SAL-009 × 100`, one decimal |
| In words | The net sales of a channel as a percentage of the net sales of all channels. |
| Data | F-SAL-009. |
| Signs | S5. |
| Dates | D1. |
| Companies | C1, C4. |
| Check in Tally | 1. Read each voucher type in the Sales Register. 2. Divide the channel total by the sum of all totals. |

#### F-SAL-011 Customers

| Item | Value |
| --- | --- |
| Expression | `COUNT(DISTINCT parties.name)` over the entries of F-SAL-004 |
| In words | The number of customers with entries on the ledgers under Sales Accounts in the period. Vouchers with no party are not counted. |
| Data | As for each `F-SAL` entry, with `vouchers.party_id` and `parties.name`. |
| Signs | S5. |
| Dates | D1. |
| Companies | C2. A customer counts one time in all companies. |
| Check in Tally | 1. Open the Sales Register with details (Alt+F5). 2. Count each party one time. |

#### F-SAL-012 Customer net sales

| Item | Value |
| --- | --- |
| Expression | `F-SAL-004`, where `vouchers.party_id` = the party |
| In words | The net sales of the vouchers of one customer. |
| Data | As for each `F-SAL` entry, with `vouchers.party_id`. |
| Signs | S2. |
| Dates | D1. |
| Companies | C1, C2. |
| Check in Tally | 1. Open the Sales Register. 2. Filter it by the party. 3. Read the total. |

#### F-SAL-013 Other customers

| Item | Value |
| --- | --- |
| Expression | `F-SAL-004 − Σ F-SAL-012` over the top ten customers |
| In words | The net sales of all customers after the top ten, plus sales with no party. |
| Data | F-SAL-004 and F-SAL-012. |
| Signs | S2. |
| Dates | D1. |
| Companies | C1, C2. |
| Check in Tally | 1. Read the Sales Register total. 2. Subtract the totals of the top ten customers. |

#### F-SAL-014 Invoice amount (largest invoices)

| Item | Value |
| --- | --- |
| Expression | `−Σ amount` of the voucher on the ledgers under Sales Accounts |
| In words | The entries of one invoice on the ledgers under Sales Accounts. Taxes and freight on other ledgers are not included. |
| Data | As for each `F-SAL` entry. |
| Signs | S2. |
| Dates | D1. |
| Companies | The company of the invoice. |
| Check in Tally | 1. Open the voucher. 2. Add its lines on the sales ledgers. |

#### F-SAL-015 Share of sales by company

| Item | Value |
| --- | --- |
| Expression | `F-SAL-004 (company) ÷ F-SAL-004 (selection) × 100`, one decimal |
| In words | The net sales of one company as a percentage of the net sales of the selection. |
| Data | F-SAL-004. |
| Signs | S5. |
| Dates | D1. |
| Companies | Each company of the selection. |
| Check in Tally | 1. Read the Sales Accounts line of each company. 2. Divide one line by the sum of all lines. |

#### F-PUR-001 Net purchases

| Item | Value |
| --- | --- |
| Expression | `+Σ amount` on the ledgers under Purchase Accounts |
| In words | The net purchases of the period or month. It is F-SAL-004 for purchases. |
| Data | As for each `F-SAL` entry, on the ledgers under `purchase_accounts`. |
| Signs | S1, S3. A purchase is a debit. |
| Dates | D1. |
| Companies | C1. |
| Check in Tally | 1. Open the Profit & Loss A/c for the same period. 2. Read the Purchase Accounts line. |

## 5. Profit & Loss (`F-PL`)

**Data for each `F-PL` entry:** `statement_lines` (`statement = 'profit_loss'`, `figures = 'ours'`, `label`, `section`, `level`, `amount`, `as_of`), through the view `v_profit_loss`. We find the group of a line by its predefined role in `account_groups`.

**Dates for each `F-PL` entry:** D3, D5 and D6.

**Signs for each `F-PL` entry:** S1, S2, S3 and S4.

**Companies for each `F-PL` entry:** C1. Percentages also use C4.

#### F-PL-001 Revenue (net sales)

| Item | Value |
| --- | --- |
| Expression | `−(line at the end − line before the start)`, for the line of the group with role `sales_accounts` |
| In words | The Sales Accounts line of the stored Profit & Loss for the period. The tests prove that it is equal to F-SAL-004. |
| Data | As for each `F-PL` entry. |
| Signs | S2. |
| Dates | D3, D5, D6. |
| Companies | C1. |
| Check in Tally | 1. Open Gateway of Tally › Profit & Loss A/c. 2. Set the same period (F2). 3. Read the Sales Accounts line. |

#### F-PL-002 Cost of sales

| Item | Value |
| --- | --- |
| Expression | `Σ (line at the end − line before the start)`, for the main lines in the section `gross` that are not income |
| In words | The lines above gross profit that are not income. With stock, it is opening stock, plus purchases, plus direct expenses, minus closing stock. With no stock, it is the purchase lines and the direct expense lines. |
| Data | As for each `F-PL` entry. |
| Signs | S3. |
| Dates | D3, D5, D6. |
| Companies | C1. |
| Check in Tally | 1. Open the Profit & Loss A/c for the same period. 2. Add the expense lines above Gross Profit. |

#### F-PL-003 Gross profit

| Item | Value |
| --- | --- |
| Expression | `−(Gross Profit line at the end − line before the start)` |
| In words | Net sales, plus direct incomes, minus cost of sales. The formula reads the stored Gross Profit line. |
| Data | As for each `F-PL` entry. |
| Signs | S4. |
| Dates | D3, D5, D6. |
| Companies | C1. |
| Check in Tally | 1. Open the Profit & Loss A/c for the same period. 2. Read Gross Profit c/o. |

#### F-PL-004 Net profit or loss

| Item | Value |
| --- | --- |
| Expression | `−(Net Profit line at the end − line before the start)` |
| In words | Gross profit, plus indirect incomes, minus indirect expenses. The formula reads the stored Net Profit line. A loss is negative. |
| Data | As for each `F-PL` entry. |
| Signs | S4. |
| Dates | D3, D5, D6. |
| Companies | C1. |
| Check in Tally | 1. Open the Profit & Loss A/c for the same period. 2. Read Nett Profit or Nett Loss. |

#### F-PL-005 Gross margin %

| Item | Value |
| --- | --- |
| Expression | `F-PL-003 ÷ F-PL-001 × 100`, one decimal |
| In words | Gross profit as a percentage of net sales. When net sales is zero, the figure is "—". |
| Data | F-PL-001 and F-PL-003. |
| Signs | S5. |
| Dates | D3, D5, D6. |
| Companies | C1, C4. |
| Check in Tally | 1. Open Display More Reports › Ratio Analysis. 2. Set the same period. 3. Read Gross Profit %. |

#### F-PL-006 Net profit %

| Item | Value |
| --- | --- |
| Expression | `F-PL-004 ÷ F-PL-001 × 100`, one decimal |
| In words | Net profit as a percentage of net sales. When net sales is zero, the figure is "—". |
| Data | F-PL-001 and F-PL-004. |
| Signs | S5. |
| Dates | D3, D5, D6. |
| Companies | C1, C4. |
| Check in Tally | 1. Open Ratio Analysis for the same period. 2. Read Net Profit %. |

#### F-PL-007 Statement line for a period

| Item | Value |
| --- | --- |
| Expression | `line at the end − line before the start`, with the sign of the line |
| In words | One line of the Profit & Loss report for the period. The formula applies to each company column, month column, quarter column and the total. |
| Data | As for each `F-PL` entry. |
| Signs | S2 for income lines. S3 for cost lines. |
| Dates | D3, D5, D6. |
| Companies | C1. Each company column is one company. |
| Check in Tally | 1. Open the Profit & Loss A/c of the same company. 2. Set the same period. 3. Read the same line. |

#### F-PL-008 % of net sales

| Item | Value |
| --- | --- |
| Expression | `F-PL-007 ÷ F-PL-001 (same column) × 100`, one decimal |
| In words | A line as a percentage of the net sales in the same column. |
| Data | F-PL-001 and F-PL-007. |
| Signs | S5. |
| Dates | D3, D5, D6. |
| Companies | C1, C4. |
| Check in Tally | 1. Read the line and the Sales Accounts line. 2. Divide the line by sales. |

#### F-PL-009 Other costs (indirect expenses less indirect incomes)

| Item | Value |
| --- | --- |
| Expression | `F-PL-003 − F-PL-004` |
| In words | The amount between gross profit and net profit. |
| Data | F-PL-003 and F-PL-004. |
| Signs | S3. |
| Dates | D3, D5, D6. |
| Companies | C1. |
| Check in Tally | 1. Open the Profit & Loss A/c. 2. Subtract the indirect incomes from the indirect expenses below Gross Profit. |

#### F-PL-010 Cost structure (% of net sales)

| Item | Value |
| --- | --- |
| Expression | `cost ÷ F-PL-001 × 100`, one decimal |
| In words | Cost of sales (F-PL-002) or other costs (F-PL-009) as a percentage of net sales. The P&L page also shows each expense line (F-PL-008). |
| Data | F-PL-001, F-PL-002, F-PL-008 and F-PL-009. |
| Signs | S5. |
| Dates | D3, D5, D6. |
| Companies | C1, C4. |
| Check in Tally | 1. Read the cost lines and the Sales Accounts line. 2. Divide each cost by sales. |

## 6. Balance Sheet (`F-BS`)

**Data for the lines:** `statement_lines` (`statement = 'balance_sheet'`, `figures = 'ours'`) at one statement date, through the view `v_balance_sheet`.

**Dates for each `F-BS` entry:** D4, D5 and D6. A Balance Sheet shows the position at a date.

**Signs for each `F-BS` entry:** assets are debits. Liabilities and capital are credits. The dashboard shows both as positive numbers.

#### F-BS-001 Total assets

| Item | Value |
| --- | --- |
| Expression | `Σ amount` of the main lines in the section `assets` |
| In words | The main lines on the assets side, added. |
| Data | As for the lines. |
| Signs | Debit, shown positive. |
| Dates | D4, D5, D6. |
| Companies | C1. |
| Check in Tally | 1. Open Gateway of Tally › Balance Sheet. 2. Set the same date. 3. Read the assets total. |

#### F-BS-002 Current assets (statement line)

| Item | Value |
| --- | --- |
| Expression | The main line of the group with role `current_assets` |
| In words | The Current Assets line of the statement. The source adds all balances under the group, debit and credit. The ratios do not use this line (see F-BS-007). |
| Data | As for the lines. |
| Signs | Debit, shown positive. |
| Dates | D4, D5, D6. |
| Companies | C1. |
| Check in Tally | 1. Open the Balance Sheet at the same date. 2. Read Current Assets. |

#### F-BS-003 Current liabilities (statement line)

| Item | Value |
| --- | --- |
| Expression | `−amount` of the main line of the group with role `current_liabilities` |
| In words | The Current Liabilities line of the statement. The source adds all balances under the group, debit and credit. The ratios do not use this line (see F-BS-008). |
| Data | As for the lines. |
| Signs | Credit, shown positive. |
| Dates | D4, D5, D6. |
| Companies | C1. |
| Check in Tally | 1. Open the Balance Sheet at the same date. 2. Read Current Liabilities. |

#### F-BS-004 Capital and reserves (with the profit to date)

| Item | Value |
| --- | --- |
| Expression | `−Σ amount` of the Capital Account line and the Profit & Loss A/c line |
| In words | The Capital Account line plus the Profit & Loss A/c line. Reserves & Surplus is a group under Capital Account. The ratios call this figure equity. |
| Data | As for the lines. Roles `capital_account` and the Profit & Loss A/c line. |
| Signs | Credit, shown positive. A loss makes it smaller. |
| Dates | D4, D5, D6. |
| Companies | C1. |
| Check in Tally | 1. Open the Balance Sheet at the same date. 2. Add Capital Account and Profit & Loss A/c. |

#### F-BS-005 Balance Sheet line at a date

| Item | Value |
| --- | --- |
| Expression | `amount` (assets) or `−amount` (liabilities and capital), at the date |
| In words | One line of the stored Balance Sheet at the date. The page also shows the line at the end of the comparison period. |
| Data | As for the lines. |
| Signs | Debit for assets and credit for liabilities, both shown positive. |
| Dates | D4, D5, D6. |
| Companies | C1. |
| Check in Tally | 1. Open the Balance Sheet at the same date. 2. Read the same line. |

#### F-BS-006 Total assets, total liabilities

| Item | Value |
| --- | --- |
| Expression | `Σ` of the main lines of each side |
| In words | The main lines of each side, added. The two totals are equal. |
| Data | As for the lines. |
| Signs | Shown positive. |
| Dates | D4, D5, D6. |
| Companies | C1. |
| Check in Tally | 1. Open the Balance Sheet at the same date. 2. Read the two totals. |

### 6.1 Current assets and current liabilities in the form of Schedule III

Schedule III of the Companies Act 2013 shows each balance on its own side. The source nets each group. For example, a debtor with a credit balance makes the debtors smaller. Thus F-BS-007 to F-BS-011 classify each ledger by itself. The code is in `data-plane/core/ratios.py`.

**Data:** the balance of each ledger at the statement date: `ledgers.opening_balance` plus the effective `voucher_lines` up to the date. For a foreign-currency ledger, the formula uses the revalued balance of the source at that date (`fx_revaluation_snapshots.revalued_value`). The closing stock is `stock_values.closing_value` (`scope = 'total'`) at the date. Marked loans are in `short_term_borrowings`. The roles of a ledger are the predefined roles of its group and of all groups above it.

**Where a balance goes.** The formula uses the first row that applies to the ledger:

| Ledger under (role) | Debit balance | Credit balance |
| --- | --- | --- |
| Stock-in-Hand (`stock_in_hand`) | Not counted: the closing stock replaces it. | Not counted. |
| Bank OD A/c (`bank_od_a_c`) | Current asset: bank balances | Current liability: short-term borrowings |
| Loans (Liability) (`loans_liability`), marked as short-term | Current asset: other | Current liability: short-term borrowings |
| Loans (Liability), not marked | Not counted. | Borrowings that are not current |
| Bank Accounts (`bank_accounts`) | Current asset: bank balances | Current liability: short-term borrowings |
| Sundry Debtors (`sundry_debtors`) | Current asset: trade receivables | Current liability: advances from customers |
| Sundry Creditors (`sundry_creditors`) | Current asset: advances to suppliers | Current liability: trade payables |
| Current Assets (`current_assets`), other | Current asset: cash (`cash_in_hand`), deposits (`deposits_asset`), loans and advances (`loans_advances_asset`) or other | Current liability: other |
| Current Liabilities (`current_liabilities`), other | Current asset: other | Current liability: duties and taxes (`duties_taxes`), provisions (`provisions`) or other |

**Short-term borrowings.** By default, these are the Bank OD A/c ledgers and the bank accounts with a credit balance. Secured loans, unsecured loans and term loans are not current. A person can mark a ledger under Loans (Liability) as short-term, for example a cash-credit loan. Use `./dev.ps1 loans` (see F-BS-011).

**Closing stock.** The formula adds the closing stock one time, at the value of the source at the date. If the source supplies no value, the formula uses the balances of the Stock-in-Hand ledgers.

**Companies.** The formula classifies the ledgers of each company. Then it adds the companies (C1). It does not remove balances between the companies.

#### F-BS-007 Current assets (Schedule III)

| Item | Value |
| --- | --- |
| Expression | `Σ debit balances that go to current assets + closing stock` |
| In words | The parts of current assets in section 6.1, added. |
| Data | As in section 6.1. |
| Signs | Debit, shown positive. |
| Dates | D4, D5, D6, D7. |
| Companies | C1. |
| Check in Tally | 1. Open the Balance Sheet at the same date. 2. Expand Current Assets to ledgers (Alt+F1). 3. Add the debit balances. 4. Add the creditors with a debit balance. 5. Add the closing stock. |

#### F-BS-008 Current liabilities (Schedule III)

| Item | Value |
| --- | --- |
| Expression | `Σ credit balances that go to current liabilities` |
| In words | The parts of current liabilities in section 6.1, added. Short-term borrowings are included. |
| Data | As in section 6.1. |
| Signs | Credit, shown positive. |
| Dates | D4, D5, D6. |
| Companies | C1. |
| Check in Tally | 1. Open the Balance Sheet at the same date. 2. Expand Current Liabilities to ledgers. 3. Add the credit balances. 4. Add the debtors with a credit balance. 5. Add Bank OD A/c, banks in credit and marked loans. |

**Check:** the rules move each amount to the two sides together. So F-BS-007 − F-BS-008 is equal to F-BS-002 − F-BS-003. This is not true when a ledger under Loans (Liability) counts as current.

#### F-BS-009 Borrowings

| Item | Value |
| --- | --- |
| Expression | `Σ credit balances under Loans (Liability) + Σ credit balances of bank accounts` |
| In words | All loans: short-term borrowings and the borrowings that are not current. Debt to equity uses this figure. |
| Data | As in section 6.1. |
| Signs | Credit, shown positive. |
| Dates | D4, D5, D6. |
| Companies | C1. |
| Check in Tally | 1. Open the Balance Sheet at the same date. 2. Read Loans (Liability). 3. Add the bank accounts with a credit balance. |

#### F-BS-010 A part of current assets, current liabilities or borrowings

| Item | Value |
| --- | --- |
| Expression | `Σ` of the balances that section 6.1 puts in the part |
| In words | One row of the ratio hover, for example "Trade receivables (debtors in debit)". |
| Data | As in section 6.1. |
| Signs | Shown positive. |
| Dates | D4, D5, D6, D7. |
| Companies | C1. |
| Check in Tally | 1. Open the group of the part in the Balance Sheet. 2. Expand it to ledgers. 3. Add the balances on the side of the part. |

#### F-BS-011 Ledgers marked as short-term

| Item | Value |
| --- | --- |
| Expression | `COUNT(short_term_borrowings)` for the companies of the selection |
| In words | The number of ledgers under Loans (Liability) that a person marked as short-term. The ratio hover shows "Includes N ledgers marked as short-term". |
| Data | `short_term_borrowings` (`entity_id`, `ledger_id`). Each change is in `audit_log`. |
| Signs | S5. |
| Dates | Not applicable. A mark applies to all dates. |
| Companies | C1. |
| Check in Tally | Tally has no such mark. 1. Run `./dev.ps1 loans -Company "<name>"`. 2. Count the rows with "yes (marked)". |

## 7. Ratios (`F-RAT`)

**Dates for each `F-RAT` entry:** D4, D5 and D6. The ratio is at the date of the Balance Sheet. The page also shows the ratio at the end of the comparison period.

**Signs:** S5.

**Companies:** C1 and C4.

#### F-RAT-000 A ratio at a date

| Item | Value |
| --- | --- |
| Expression | One of F-RAT-004 to F-RAT-010. The change is `value − before`, in the unit of the ratio. |
| In words | A ratio at the date and at the end of the comparison period. When the divisor is zero or a statement is missing, the figure is "—". |
| Data | As in each ratio. |
| Signs | S5. |
| Dates | D4, D5, D6. |
| Companies | C1, C4. |
| Check in Tally | Use the check of each ratio. |

#### F-RAT-001 Current ratio, from the statement lines (retired)

Retired on 2026-11-11. Replaced by F-RAT-008. The old formula divided the Current Assets line by the Current Liabilities line (F-BS-002 ÷ F-BS-003). It did not count Bank OD A/c, and it netted debtors and creditors with balances on the other side.

#### F-RAT-002 Quick ratio, from the statement lines (retired)

Retired on 2026-11-11. Replaced by F-RAT-009. The old formula was (F-BS-002 − F-BAL-005) ÷ F-BS-003.

#### F-RAT-003 Debt to equity, from the Loans (Liability) line (retired)

Retired on 2026-11-11. Replaced by F-RAT-010. The old formula divided the Loans (Liability) line by F-BS-004. It did not count bank accounts with a credit balance.

#### F-RAT-004 Receivable days

| Item | Value |
| --- | --- |
| Expression | `F-BAL-003 ÷ F-SAL-004 × days`, whole days |
| In words | Receivables divided by net sales, multiplied by the days from the period start to the date. |
| Data | F-BAL-003 and F-SAL-004. |
| Signs | S5. |
| Dates | D2 and D1 to the date of the Balance Sheet. |
| Companies | C1, C4. |
| Check in Tally | 1. Open Ratio Analysis for the same period. 2. Read Recv. Turnover in days. |

#### F-RAT-005 Payable days

| Item | Value |
| --- | --- |
| Expression | `F-BAL-004 ÷ F-PUR-001 × days`, whole days |
| In words | Payables divided by net purchases, multiplied by the days from the period start to the date. |
| Data | F-BAL-004 and F-PUR-001. |
| Signs | S5. |
| Dates | D2 and D1 to the date of the Balance Sheet. |
| Companies | C1, C4. |
| Check in Tally | 1. Read Sundry Creditors and the Purchase Accounts line for the same period. 2. Calculate the expression. |

#### F-RAT-006 Inventory days

| Item | Value |
| --- | --- |
| Expression | `F-BAL-005 ÷ F-PL-002 × days`, whole days |
| In words | Closing stock divided by cost of sales, multiplied by the days from the period start to the date. |
| Data | F-BAL-005 and F-PL-002. |
| Signs | S5. |
| Dates | D3, D5, D6, D7. |
| Companies | C1, C4. |
| Check in Tally | 1. Read the closing stock and the cost of sales in the Profit & Loss A/c. 2. Calculate the expression. |

#### F-RAT-007 Working-capital days

| Item | Value |
| --- | --- |
| Expression | `F-RAT-004 + F-RAT-006 − F-RAT-005` |
| In words | Receivable days plus inventory days minus payable days. |
| Data | F-RAT-004, F-RAT-005 and F-RAT-006. |
| Signs | S5. |
| Dates | As in the three ratios. |
| Companies | C1, C4. |
| Check in Tally | Calculate the expression from the three ratios. |

#### F-RAT-008 Current ratio

| Item | Value |
| --- | --- |
| Expression | `F-BS-007 ÷ F-BS-008`, two decimals |
| In words | Current assets divided by current liabilities, in the form of Schedule III (section 6.1). The hover shows the parts. |
| Data | F-BS-007, F-BS-008 and F-BS-010. |
| Signs | S5. |
| Dates | D4, D5, D6, D7. |
| Companies | C1, C4. No inter-company eliminations. The hover tells you when the companies are combined. |
| Check in Tally | 1. Calculate F-BS-007 and F-BS-008 with their checks. 2. Divide F-BS-007 by F-BS-008. Note: Ratio Analysis in Tally uses the netted lines and leaves out Bank OD A/c. |

#### F-RAT-009 Quick ratio

| Item | Value |
| --- | --- |
| Expression | `(F-BS-007 − closing stock) ÷ F-BS-008`, two decimals |
| In words | Current assets without the closing stock, divided by current liabilities. |
| Data | F-BS-007, F-BS-008 and the closing stock of section 6.1. |
| Signs | S5. |
| Dates | D4, D5, D6, D7. |
| Companies | C1, C4. |
| Check in Tally | 1. Calculate F-BS-007 and F-BS-008. 2. Subtract the closing stock from F-BS-007. 3. Divide the result by F-BS-008. |

#### F-RAT-010 Debt to equity

| Item | Value |
| --- | --- |
| Expression | `F-BS-009 ÷ F-BS-004`, two decimals |
| In words | Borrowings divided by equity (capital and reserves with the profit to date). |
| Data | F-BS-009 and F-BS-004. |
| Signs | S5. When equity is negative, the ratio is negative. |
| Dates | D4, D5, D6. |
| Companies | C1, C4. |
| Check in Tally | 1. Calculate F-BS-009. 2. Add Capital Account and Profit & Loss A/c in the Balance Sheet. 3. Divide F-BS-009 by that sum. |

## 8. Balances (`F-BAL`)

**Data for F-BAL-001 to F-BAL-004:** `ledgers` (`opening_balance`, `group_id`, `is_deleted`) and the effective `voucher_lines` up to the date.

#### F-BAL-001 Balance of the ledgers under a group, at a date

| Item | Value |
| --- | --- |
| Expression | `Σ opening_balance + Σ amount`, where `voucher_date ≤ date` |
| In words | The balance at a date of the ledgers under a group. |
| Data | As for F-BAL entries. |
| Signs | S1. |
| Dates | D2. |
| Companies | C1. |
| Check in Tally | 1. Open Account Books › Group Summary of the group. 2. Set the same date. 3. Read the closing balance. |

#### F-BAL-002 Cash & bank

| Item | Value |
| --- | --- |
| Expression | F-BAL-001 for the roles `cash_in_hand` and `bank_accounts` |
| In words | The cash and bank balances at the period end. Bank OD A/c ledgers are loans, so this figure does not include them. A negative figure shows an overdrawn ledger. |
| Data | As for F-BAL entries. |
| Signs | S1. |
| Dates | D2. |
| Companies | C1. |
| Check in Tally | 1. Open the Balance Sheet at the same date. 2. Add Cash-in-Hand and Bank Accounts. |

#### F-BAL-003 Receivables

| Item | Value |
| --- | --- |
| Expression | F-BAL-001 for the role `sundry_debtors` |
| In words | The amount that customers must pay us at the period end. |
| Data | As for F-BAL entries. |
| Signs | S1. Debit, positive. |
| Dates | D2. |
| Companies | C1. |
| Check in Tally | 1. Open the Group Summary of Sundry Debtors. 2. Set the same date. 3. Read the closing balance. |

#### F-BAL-004 Payables

| Item | Value |
| --- | --- |
| Expression | `−F-BAL-001` for the role `sundry_creditors` |
| In words | The amount that we must pay to vendors at the period end. |
| Data | As for F-BAL entries. |
| Signs | S2. Credit, shown positive. |
| Dates | D2. |
| Companies | C1. |
| Check in Tally | 1. Open the Group Summary of Sundry Creditors. 2. Set the same date. 3. Read the closing balance. |

#### F-BAL-005 Stock value

| Item | Value |
| --- | --- |
| Expression | `Σ stock_values.closing_value`, where `scope = 'total'` and `as_of` = the date |
| In words | The closing stock that the source supplies for the date. If one company has no value, the figure is "—". |
| Data | `stock_values` (`scope`, `closing_value`, `as_of`). |
| Signs | Positive. |
| Dates | D7. |
| Companies | C1. Each company must have a value. |
| Check in Tally | 1. Open Gateway of Tally › Stock Summary. 2. Set the same date. 3. Read the closing value. |

## 9. Cash movement (`F-CF`)

#### F-CF-001 Money in and out by category

| Item | Value |
| --- | --- |
| Expression | `F-BAL-002 (opening) + Σ in − Σ out = F-BAL-002 (closing)` |
| In words | The effective entries on the cash and bank ledgers in the period, by voucher. Each cash amount goes to the category of the other ledgers in its voucher. A voucher with only cash and bank ledgers is a transfer. A transfer adds to zero. |
| Data | `voucher_lines` on the ledgers under `cash_in_hand` and `bank_accounts`. The category comes from the nearest group with a known role: customers, suppliers, income, expenses, taxes, loans, capital, assets or other. |
| Signs | Money in is a debit to cash or bank. Money out is a credit, shown positive. |
| Dates | D1 for the movements. D2 for the opening and the closing. |
| Companies | C1. |
| Check in Tally | 1. Open Display More Reports › Account Books › Cash/Bank Book(s). 2. Set the same period. 3. Read the inward and outward totals. |

#### F-CF-002 Monthly in and out

| Item | Value |
| --- | --- |
| Expression | `Σ debits` (in) and `Σ credits` (out) for each month |
| In words | The money in and the money out of each month on the cash and bank ledgers. |
| Data | As for F-CF-001. |
| Signs | As for F-CF-001. |
| Dates | D1. |
| Companies | C1. |
| Check in Tally | 1. Open Display More Reports › Statements of Accounts › Cash Flow. 2. Read each month. |

## 10. Cost centres (`F-CC`)

#### F-CC-001 Cost centre allocations (by month, total)

| Item | Value |
| --- | --- |
| Expression | `Σ amount` of the allocations to the cost centre in the period |
| In words | The amounts of voucher lines that the books allocate to the cost centre. A cost centre below it has its own row. |
| Data | `v_cost_allocations` (`cost_centre_id`, `voucher_date`, `amount`), effective lines only. |
| Signs | S1. An expense is positive. |
| Dates | D1. |
| Companies | C1, C2. A cost centre is identified by its name and its category. |
| Check in Tally | 1. Open Statements of Accounts › Cost Centres › Category Summary. 2. Set the same period. 3. Read the cost centre. Note: Tally includes the centres below it. |

#### F-CC-002 An allocation

| Item | Value |
| --- | --- |
| Expression | `amount` of one allocation |
| In words | The amount of one line that the books allocate to the cost centre, in one cost category. |
| Data | `v_cost_allocations`. |
| Signs | S1. |
| Dates | D1. |
| Companies | The company of the voucher. |
| Check in Tally | 1. Open the voucher. 2. Read the cost centre allocation of the line. |

#### F-CC-003 Allocations (count)

| Item | Value |
| --- | --- |
| Expression | `COUNT` of the allocations to the cost centre in the period |
| In words | The number of allocations to the cost centre in the period. |
| Data | `v_cost_allocations`. |
| Signs | S5. |
| Dates | D1. |
| Companies | C1, C2. |
| Check in Tally | 1. Open the breakup of the cost centre. 2. Count the entries. |

## 11. Stock (`F-STK`)

**Quantities** are ours. A quantity is the opening of the item plus the movements of vouchers that move stock. The formula does not count deleted, cancelled or optional vouchers. It does not count stock at a job worker. A line moves its `stock_quantity`. Validation proves the quantities against Tally for each item (VAL-006).

**Values** come from the source. The source uses its own valuation method. For a period, the value is the value at the last statement date in the period (D5, D7).

**Companies:** C1 and C2. An item is identified by its name.

#### F-STK-001 Opening quantity

| Item | Value |
| --- | --- |
| Expression | `items.opening_qty + Σ stock_quantity`, where `voucher_date` is before the period start |
| In words | The quantity of the item at the period start. |
| Data | `items.opening_qty` and `inventory_lines.stock_quantity`. |
| Signs | A quantity in is positive. A quantity out is negative. |
| Dates | D1. |
| Companies | C1, C2. |
| Check in Tally | 1. Open Stock Summary › the item. 2. Set the same period. 3. Read the opening quantity. |

#### F-STK-002 Inward

| Item | Value |
| --- | --- |
| Expression | `Σ positive stock_quantity` in the period |
| In words | The quantity that came in during the period. |
| Data | `inventory_lines.stock_quantity`. |
| Signs | Positive. |
| Dates | D1. |
| Companies | C1, C2. |
| Check in Tally | 1. Open the Stock Item Monthly Summary. 2. Read the Inwards column. |

#### F-STK-003 Outward

| Item | Value |
| --- | --- |
| Expression | `−Σ negative stock_quantity` in the period |
| In words | The quantity that went out during the period, shown positive. |
| Data | `inventory_lines.stock_quantity`. |
| Signs | Shown positive. |
| Dates | D1. |
| Companies | C1, C2. |
| Check in Tally | 1. Open the Stock Item Monthly Summary. 2. Read the Outwards column. |

#### F-STK-004 Closing quantity

| Item | Value |
| --- | --- |
| Expression | `F-STK-001 + F-STK-002 − F-STK-003` |
| In words | The quantity at the period end. On the page of an item, the quantity after each movement. A negative quantity shows that more went out than came in. |
| Data | As F-STK-001 to F-STK-003. |
| Signs | As F-STK-001. |
| Dates | D1. |
| Companies | C1, C2. |
| Check in Tally | 1. Open the Stock Summary. 2. Set the same date. 3. Read the closing quantity. |

#### F-STK-005 Value (item, stock group, godown)

| Item | Value |
| --- | --- |
| Expression | `stock_values.closing_value` at the last statement date in the period |
| In words | The closing value that the source supplies for an item, a stock group or a godown. A stock group or a godown includes those below it. |
| Data | `stock_values` (`scope` = `item`, `stock_group` or `godown`; `scope_name`; `closing_value`). |
| Signs | Positive. |
| Dates | D5, D6, D7. |
| Companies | C1, C2. |
| Check in Tally | 1. Open the Stock Summary (or the Godown Summary). 2. Set the same date. 3. Read the closing value. |

#### F-STK-006 Rate

| Item | Value |
| --- | --- |
| Expression | `F-STK-005 ÷ F-STK-004`, two decimals |
| In words | The value for each unit. When the value is missing or the quantity is zero, the figure is "—". |
| Data | F-STK-004 and F-STK-005. |
| Signs | Positive. |
| Dates | D5, D7. |
| Companies | C1, C2, C4. |
| Check in Tally | 1. Open the Stock Summary. 2. Read the rate of the item. |

#### F-STK-007 Stock value (total, by date)

| Item | Value |
| --- | --- |
| Expression | F-BAL-005 at the last statement date in the period, and at each of the last twelve statement dates |
| In words | The total closing stock at the period end, and for the chart at earlier dates. |
| Data | `stock_values` (`scope = 'total'`). |
| Signs | Positive. |
| Dates | D5, D6, D7. |
| Companies | C1. |
| Check in Tally | 1. Open the Stock Summary. 2. Set each date. 3. Read the closing value. |

#### F-STK-008 Value of a movement

| Item | Value |
| --- | --- |
| Expression | `inventory_lines.amount` |
| In words | The amount of the stock line on the voucher. It is the purchase value or the sale value, not the stock valuation. |
| Data | `inventory_lines.amount`. |
| Signs | As the quantity. |
| Dates | D1. |
| Companies | The company of the voucher. |
| Check in Tally | 1. Open the voucher. 2. Read the amount of the stock item line. |

#### F-STK-009 Stock items (count)

| Item | Value |
| --- | --- |
| Expression | `COUNT(DISTINCT items.name)` |
| In words | The number of stock items in the selection. |
| Data | `items` (`name`, `is_deleted`). |
| Signs | S5. |
| Dates | Not applicable. |
| Companies | C2. An item counts one time in all companies. |
| Check in Tally | 1. Open List of Accounts › Stock Items. 2. Count the items. |

### 11.1 Stock by godown and batch (F-STK-010 to F-STK-015)

**Sections.** The godown tells whose stock it holds (`godowns.holding`, from the godown settings in Tally):

| Section | Holding | In the total | Why |
| --- | --- | --- | --- |
| Our stock | `own` | Yes | It is our stock in our godowns. |
| Others' stock held with us (not ours) | `third_party_with_us` | Yes | It is not ours, but the Stock Summary of Tally includes it. The total must agree with Tally. |
| Our stock at job workers (still ours) | `ours_with_third_party` | No | Tally leaves it out of the Stock Summary and of the closing stock. Tally records there only what the job worker used. |

The tests prove these rules on the test company against the Stock Summary and the Godown Summary of Tally at 02-Oct-2026 (`data-plane/tests/test_stock_godowns.py`).

#### F-STK-010 Quantity at a godown and batch, at a date

| Item | Value |
| --- | --- |
| Expression | `opening at the godown and batch + Σ stock_quantity at the godown and batch`, where `voucher_date ≤ date` |
| In words | The quantity of an item at one godown and batch at the end of the date. An opening that Tally does not split by godown shows on a row with no godown. |
| Data | `item_opening_batches` (`godown_id`, `batch_name`, `quantity`), `items.opening_qty` and `inventory_lines` (`godown_id`, `batch_name`, `stock_quantity`) of vouchers that move stock. |
| Signs | A quantity in is positive. A quantity out is negative. A godown can show a negative quantity when more went out than came in. |
| Dates | D1. |
| Companies | C1, C2. The rows add the companies by item, godown and batch name. |
| Check in Tally | 1. Open Gateway of Tally › Godown Summary. 2. Set the same date. 3. Open the godown and read the item. |

#### F-STK-011 Value at a godown and batch

| Item | Value |
| --- | --- |
| Expression | `F-STK-010 × F-STK-006`, to the paisa. The last row of the item takes the rounding difference. |
| In words | The quantity at the godown and batch multiplied by the rate of the item. Tally does not keep a value for each item at each godown. The rows of an item add up to its stored value (F-STK-005). Rows at a job worker have no value. |
| Data | F-STK-005, F-STK-006 and F-STK-010. |
| Signs | Positive for a positive quantity. |
| Dates | D5, D7 for the rate. D1 for the quantity. |
| Companies | C1, C2, C4. |
| Check in Tally | 1. Open the Godown Summary at the same date. 2. Compare the value of the godown with the sum of its rows. Note: Tally values each godown with its own method. The two can differ a little. |

#### F-STK-012 Section total

| Item | Value |
| --- | --- |
| Expression | `Σ F-STK-010` and `Σ F-STK-011` of the rows of the section |
| In words | The quantity and the value of one section: our stock, others' stock held with us, or our stock at job workers. |
| Data | F-STK-010 and F-STK-011. |
| Signs | As F-STK-010. |
| Dates | As F-STK-010 and F-STK-011. |
| Companies | C1, C2. |
| Check in Tally | 1. Open the Godown Summary at the same date. 2. Add the godowns of the section. |

#### F-STK-013 Stock in the total

| Item | Value |
| --- | --- |
| Expression | `F-STK-012 (our stock) + F-STK-012 (others' stock held with us)` |
| In words | The stock that Tally counts. It is equal to the closing quantities of the Stock page (F-STK-004), item by item, and to the Stock Summary of Tally. Our stock at job workers is not in it. |
| Data | F-STK-012. |
| Signs | As F-STK-010. |
| Dates | As F-STK-010 and F-STK-011. |
| Companies | C1, C2. |
| Check in Tally | 1. Open Gateway of Tally › Stock Summary. 2. Set the same date. 3. Read the closing quantity and the closing value. |

#### F-STK-014 Quantity of an inventory line

| Item | Value |
| --- | --- |
| Expression | `inventory_lines.stock_quantity` |
| In words | The quantity that one inventory line moves in stock, in the inventory lines dataset. It is the quantity, minus a part that a delivery note or a receipt note already moved. For each item, the opening plus the lines up to a date, outside job workers, is the closing quantity (F-STK-004). |
| Data | `inventory_lines` of vouchers that move stock and are not deleted, cancelled or optional. |
| Signs | A quantity in is positive. A quantity out is negative. |
| Dates | D1. |
| Companies | The company of the voucher. |
| Check in Tally | 1. Open the voucher. 2. Read the quantity of the stock item line. |

#### F-STK-015 Rate of inventory lines

| Item | Value |
| --- | --- |
| Expression | For one line: `inventory_lines.rate`. For a group: `Σ amount ÷ Σ stock_quantity`. |
| In words | The rate of one line, or the average rate of a group of lines. With no quantity, there is no rate. |
| Data | `inventory_lines` (`rate`, `amount`, `stock_quantity`). |
| Signs | Positive. |
| Dates | D1. |
| Companies | C1, C2, C4. |
| Check in Tally | 1. Open the voucher. 2. Read the rate of the stock item line. |

## 12. Transactions (`F-TRN`)

#### F-TRN-001 Debit or credit of a line

| Item | Value |
| --- | --- |
| Expression | Debit = `amount` when it is positive. Credit = `−amount` when it is negative. |
| In words | Each effective line of the period, with one row for each line. The debits of a voucher are equal to its credits. |
| Data | `voucher_lines.amount` (`is_effective`), with the voucher, its type, its party and the ledger of the line. |
| Signs | S1. |
| Dates | D1. |
| Companies | The company of the voucher. |
| Check in Tally | 1. Open Display More Reports › Day Book. 2. Set the same dates. 3. Show the details (Alt+F1). |

## 13. Parties and bills (`F-PTY`)

**Data for each `F-PTY` entry:** the ledgers of the party (`parties`, `ledgers.party_id`). Bills come from `opening_bills` and from `bill_allocations` (`bill_name`, `bill_type`, `bill_date`, `due_date`, `amount`) of effective vouchers. A bill with no due date is due on its bill date plus the credit days of the party.

**Companies for each `F-PTY` entry:** C1 and C2.

#### F-PTY-001 Balance due

| Item | Value |
| --- | --- |
| Expression | F-BAL-001 for the ledgers of the party |
| In words | The balance of the party at the period end. |
| Data | As for each `F-PTY` entry. |
| Signs | Customers: S1, debit positive. Vendors: S2, credit shown positive. |
| Dates | D2. |
| Companies | C1, C2. |
| Check in Tally | 1. Open Account Books › Ledger of the party. 2. Read the closing balance. |

#### F-PTY-002 Overdue

| Item | Value |
| --- | --- |
| Expression | `Σ F-PTY-004`, where the due date is before the period end and the amount is positive |
| In words | The outstanding bills that are past their due date. |
| Data | As for each `F-PTY` entry. |
| Signs | As F-PTY-001. |
| Dates | D2. |
| Companies | C1, C2. |
| Check in Tally | 1. Open Outstandings › Ledger of the party. 2. Read the overdue amount at the date. |

#### F-PTY-003 Bills cover

| Item | Value |
| --- | --- |
| Expression | `Σ F-PTY-004` |
| In words | All outstanding bills, with the opening bills. It is less than the balance when some amounts are not in bills. |
| Data | As for each `F-PTY` entry. |
| Signs | As F-PTY-001. |
| Dates | D2. |
| Companies | C1, C2. |
| Check in Tally | 1. Open Outstandings › Ledger of the party. 2. Read the total pending. |

#### F-PTY-004 Outstanding bill

| Item | Value |
| --- | --- |
| Expression | `sign × Σ allocation amount`, for each ledger and bill name |
| In words | The new reference of a bill minus all amounts against it, up to the period end. "On account" amounts are not bills. An amount of less than half a paisa counts as paid. |
| Data | As for each `F-PTY` entry. |
| Signs | As F-PTY-001. |
| Dates | D2. |
| Companies | The company of the ledger. |
| Check in Tally | 1. Open Outstandings › Ledger of the party. 2. Read the pending amount of the bill. |

#### F-PTY-005 Overdue days of a bill

| Item | Value |
| --- | --- |
| Expression | `max(0, period end − due date)` |
| In words | The days from the due date to the period end. A bill that is not due has 0 days. |
| Data | As for each `F-PTY` entry. |
| Signs | S5. |
| Dates | D2. |
| Companies | The company of the ledger. |
| Check in Tally | 1. Open Outstandings. 2. Read the "Overdue by days" column. |

#### F-PTY-006 Receipts (payments)

| Item | Value |
| --- | --- |
| Expression | `Σ amount` of receipt vouchers (payment vouchers for vendors) on the ledgers of the party |
| In words | The money from the party (to the party) in the period. For each month, or for one voucher. |
| Data | As for each `F-PTY` entry, with `voucher_types.base_type`. |
| Signs | Shown positive. |
| Dates | D1. |
| Companies | C1, C2. |
| Check in Tally | 1. Open the ledger of the party. 2. Read the receipt (payment) vouchers in the period. |

#### F-PTY-007 Average days to pay

| Item | Value |
| --- | --- |
| Expression | `Σ(abs(amount) × days) ÷ Σ abs(amount)`, whole days |
| In words | For each amount against a bill in the period, the days from the bill date to the payment. The formula weights each amount. |
| Data | As for each `F-PTY` entry. |
| Signs | S5. |
| Dates | D1. |
| Companies | C1, C2, C4. |
| Check in Tally | Tally has no such report. 1. Open the bill-wise ledger of the party. 2. Calculate the expression. |

#### F-PTY-008 Ledger statement entry (debit, credit)

| Item | Value |
| --- | --- |
| Expression | Debit = `amount` when it is positive. Credit = `−amount` when it is negative. |
| In words | One effective entry on the ledgers of the party. The particulars are the first ledger on the other side. |
| Data | As for each `F-PTY` entry. |
| Signs | S1. |
| Dates | D1. |
| Companies | The company of the voucher. |
| Check in Tally | 1. Open Account Books › Ledger of the party. 2. Read the voucher. |

#### F-PTY-009 Running balance

| Item | Value |
| --- | --- |
| Expression | `balance(n) = balance(n − 1) + amount(n)`, from F-PTY-010 |
| In words | The balance after each entry. |
| Data | F-PTY-008 and F-PTY-010. |
| Signs | S1. |
| Dates | D1. |
| Companies | C1, C2. |
| Check in Tally | 1. Open the ledger of the party. 2. Show the running balance (F12). |

#### F-PTY-010 Statement opening

| Item | Value |
| --- | --- |
| Expression | F-BAL-001 for the ledgers of the party, on the day before the period start |
| In words | The balance of the party at the start of the period. |
| Data | As for each `F-PTY` entry. |
| Signs | S1. |
| Dates | D2, on the day before the period start. |
| Companies | C1, C2. |
| Check in Tally | 1. Open the ledger of the party for the period. 2. Read the opening balance. |

#### F-PTY-011 Invoice days (due in, or overdue by)

| Item | Value |
| --- | --- |
| Expression | Due: `due date − period end`. Overdue: `period end − due date`. |
| In words | For the bill of an invoice: the days until the due date, or the days after it. |
| Data | As for each `F-PTY` entry. |
| Signs | S5. |
| Dates | D2. |
| Companies | The company of the invoice. |
| Check in Tally | 1. Open Outstandings. 2. Read the due date of the bill. |

#### F-PTY-012 Ageing bucket

| Item | Value |
| --- | --- |
| Expression | `Σ F-PTY-004` for each bucket of days past the due date |
| In words | The outstanding bills at the date, by the days after their due date. The buckets are: not due, 1–30, 31–60, 61–90 and more than 90 days. |
| Data | As for each `F-PTY` entry. |
| Signs | As F-PTY-001. |
| Dates | D2. |
| Companies | C1, C2. |
| Check in Tally | 1. Open Statements of Accounts › Outstandings › Ageing Analysis. 2. Set the same date. 3. Select ageing by due date. |

#### F-PTY-013 Not in bills

| Item | Value |
| --- | --- |
| Expression | `F-PTY-001 − F-PTY-003` |
| In words | The balance that is not in bills. It includes amounts on account, and differences between an opening balance and its opening bills. Validation gives a warning for such a difference (LB-VAL-041). |
| Data | F-PTY-001 and F-PTY-003. |
| Signs | As F-PTY-001. |
| Dates | D2. |
| Companies | C1, C2. |
| Check in Tally | 1. Read the closing balance of the party. 2. Subtract the total pending in Outstandings. |

## 14. Registers (`F-REG`)

**Data for each `F-REG` entry:** `vouchers` and their first effective `voucher_lines` (by `line_no`), with the entries of the voucher on the ledgers of the side.

#### F-REG-001 Debit or credit (Day Book)

| Item | Value |
| --- | --- |
| Expression | Debit = `amount` when it is positive. Credit = `−amount` when it is negative. |
| In words | The first ledger entry of the voucher, as the Day Book of the source shows it. For an invoice, it is the party. |
| Data | As for each `F-REG` entry. |
| Signs | S1. |
| Dates | D1. |
| Companies | The company of the voucher. |
| Check in Tally | 1. Open Display More Reports › Day Book. 2. Find the same voucher. |

#### F-REG-002 Value (on the sales or purchase ledgers)

| Item | Value |
| --- | --- |
| Expression | `−Σ amount` (sales) or `+Σ amount` (purchases), for each voucher |
| In words | The entries of the voucher on the ledgers under Sales Accounts (Purchase Accounts). A return is negative. The total of the register is F-SAL-001 + F-SAL-002. |
| Data | As for each `F-REG` entry. |
| Signs | S2 for sales. S3 for purchases. |
| Dates | D1. |
| Companies | The company of the voucher. |
| Check in Tally | 1. Open the Sales (Purchase) Register. 2. Find the same voucher. |

## 15. Overview (`F-OVR`)

#### F-OVR-001 Twelve-month trend (sparklines)

| Item | Value |
| --- | --- |
| Expression | For each of the twelve months to the month of the period end: F-SAL-004, F-PL-003, F-PL-004, F-BAL-002 and F-SAL-011 |
| In words | The small line in a key card. It shows the last twelve months. The line only draws. It does not give a figure. |
| Data | As in each formula. |
| Signs | As in each formula. |
| Dates | As in each formula, for each month. |
| Companies | C1. |
| Check in Tally | Check each month with the formula of the card. |

#### F-OVR-002 Top customers

| Item | Value |
| --- | --- |
| Expression | The ten largest F-SAL-012, each with F-PTY-001 and F-PTY-002 |
| In words | The ten customers with the largest net sales, each with the balance due and the overdue amount at the period end. |
| Data | As in each formula. |
| Signs | As in each formula. |
| Dates | D1 for the sales. D2 for the balances. |
| Companies | C1, C2. |
| Check in Tally | 1. Sort the Sales Register by party. 2. Read the ten largest. 3. Read their balances. |

#### F-OVR-003 Profit & Loss summary against last year

| Item | Value |
| --- | --- |
| Expression | F-PL-001 to F-PL-006 for the period and for the same months or dates last year, with F-CMP-001 (F-CMP-003 for a percentage) |
| In words | Net sales, cost of sales, gross profit, gross margin %, net profit and net profit %, with last year and the change. |
| Data | As in each formula. |
| Signs | As in each formula. |
| Dates | D3, D5, D6. |
| Companies | C1, C4. |
| Check in Tally | 1. Open the Profit & Loss A/c for the period. 2. Open it for the same period last year. 3. Compare the lines. |

#### F-OVR-004 Customer share of net sales

| Item | Value |
| --- | --- |
| Expression | `F-SAL-012 ÷ F-SAL-004 × 100`, one decimal |
| In words | The net sales of a customer as a percentage of all net sales. |
| Data | F-SAL-004 and F-SAL-012. |
| Signs | S5. |
| Dates | D1. |
| Companies | C1, C2, C4. |
| Check in Tally | 1. Read the total of the customer in the Sales Register. 2. Divide it by the register total. |

## 16. Comparisons (`F-CMP`)

#### F-CMP-001 Change %

| Item | Value |
| --- | --- |
| Expression | `(value − before) ÷ abs(before) × 100`, one decimal |
| In words | How much a figure changed against the comparison period. With no comparison figure, or when it is zero, there is no change. The colour is green when the change is good for the business, crimson when it is bad and grey for a cost that goes up. |
| Data | The figure in the period and in the comparison period. |
| Signs | S5. |
| Dates | F-CMP-002. |
| Companies | As the figure. |
| Check in Tally | Calculate the expression from the two figures. |

#### F-CMP-002 The comparison period

| Item | Value |
| --- | --- |
| Expression | The table below |
| In words | The period that the dashboard compares with. A month end stays a month end (31 May to 30 April). 29 February becomes 28 February. |
| Data | `core/report_periods.py` (`Period.previous`, `Period.last_year`). |
| Signs | Not applicable. |
| Dates | The table below. |
| Companies | The same companies. |
| Check in Tally | Set the period in Tally to the same comparison period. |

| Selected | Previous period | Last year |
| --- | --- | --- |
| MTD | The same days of the month before | The same dates one year before |
| QTD | The same days of the quarter before | The same dates one year before |
| YTD | The same dates one year before | The same dates one year before |
| FY | The financial year before | The financial year before |
| Months | The same number of months just before | The same months one year before |
| Dates | The same number of days just before | The same dates one year before |

#### F-CMP-003 Change in percentage points

| Item | Value |
| --- | --- |
| Expression | `value − before`, shown as "▼ 1.1 pts" |
| In words | For a percentage (a margin), the difference between the period and the comparison period. |
| Data | The percentage in the two periods. |
| Signs | S5. |
| Dates | F-CMP-002. |
| Companies | As the percentage. |
| Check in Tally | Subtract the two percentages. |

## 17. Checks against the source (`F-CHK`)

**Data for each `F-CHK` entry:** `statement_lines` at the dates used. The formula compares ours (`figures = 'ours'`) with the statement of the source (`figures = 'source'`), line by line and in total.

#### F-CHK-001 Lines that differ

| Item | Value |
| --- | --- |
| Expression | `COUNT` of the compared lines where our amount is not equal to the amount of the source |
| In words | The lines and totals (company × date × line) that are different from the source. |
| Data | As for each `F-CHK` entry. |
| Signs | S5. |
| Dates | The statement dates of the period. |
| Companies | Each company. |
| Check in Tally | Run `./dev.ps1 statements`. It prints the counts. |

#### F-CHK-002 Lines compared

| Item | Value |
| --- | --- |
| Expression | `COUNT` of the compared lines and totals |
| In words | The lines and totals that the check compared at the dates used. |
| Data | As for each `F-CHK` entry. |
| Signs | S5. |
| Dates | The statement dates of the period. |
| Companies | Each company. |
| Check in Tally | Run `./dev.ps1 statements`. |

#### F-CHK-003 Company dates that are not checked

| Item | Value |
| --- | --- |
| Expression | `COUNT` of the company and date pairs with no statement of the source |
| In words | The pairs of company and date that the check could not compare. "Matches Tally" shows only when F-CHK-002 is more than 0, F-CHK-001 is 0 and F-CHK-003 is 0. |
| Data | As for each `F-CHK` entry. |
| Signs | S5. |
| Dates | The statement dates of the period. |
| Companies | Each company. |
| Check in Tally | Run `./dev.ps1 statements` for the missing dates. |

## 18. Data health (`F-DAT`)

**Data for each `F-DAT` entry:** the view `v_data_health` and `entity_sources.source_loaded`, through `GET /api/v1/companies`. A company on hold is not shown.

#### F-DAT-001 Companies

| Item | Value |
| --- | --- |
| Expression | `COUNT` of the companies that the user can see |
| In words | The number of companies on the page. Companies on hold are not counted. |
| Data | As for each `F-DAT` entry. |
| Signs | S5. |
| Dates | Not applicable. |
| Companies | All companies that the user can see. |
| Check in Tally | Tally has no such figure. Run `./dev.ps1 on-hold` to see the companies on hold. |

#### F-DAT-002 Checks passed

| Item | Value |
| --- | --- |
| Expression | `COUNT` of the companies with `validation_status = 'passed'` |
| In words | The number of companies with a passed last validation. |
| Data | As for each `F-DAT` entry. |
| Signs | S5. |
| Dates | The last validation of each company. |
| Companies | All companies that the user can see. |
| Check in Tally | Tally has no such figure. Run `./dev.ps1 report` to see the validation of each company. |

#### F-DAT-003 Loaded in the source

| Item | Value |
| --- | --- |
| Expression | `COUNT` of the companies with `source_loaded = true` |
| In words | The number of companies that the source had loaded when we last asked it. |
| Data | As for each `F-DAT` entry. |
| Signs | S5. |
| Dates | The last check of each company. |
| Companies | All companies that the user can see. |
| Check in Tally | 1. Open TallyPrime. 2. Press F3 (Select Company). 3. Count the loaded companies. |

#### F-DAT-004 Last sync

| Item | Value |
| --- | --- |
| Expression | `MAX(last_sync_at)` of the companies |
| In words | The time of the most recent sync, shown as "N min ago" with the date. |
| Data | As for each `F-DAT` entry. |
| Signs | Not applicable. |
| Dates | The time of the sync, in UTC, shown in local time. |
| Companies | All companies that the user can see. |
| Check in Tally | Tally has no such figure. Run `./dev.ps1 status` to see the syncs. |

## 19. Tables (`F-TBL`)

#### F-TBL-001 Total

| Item | Value |
| --- | --- |
| Expression | `Σ value` of the rows that the table shows, as exact decimals |
| In words | The sum of an amount column or a count column after the filter. The table does not add balance columns, because a sum of balances has no meaning. |
| Data | The rows of the table. |
| Signs | As the column. |
| Dates | As the column. |
| Companies | As the column. |
| Check in Tally | Add the same rows in the report of Tally. |

#### F-TBL-002 Subtotal

| Item | Value |
| --- | --- |
| Expression | F-TBL-001 in each group |
| In words | The total of each group when the user groups a table. The CSV file contains the subtotals and the total. |
| Data | The rows of the group. |
| Signs | As the column. |
| Dates | As the column. |
| Companies | As the column. |
| Check in Tally | Add the rows of the group. |

## 20. How the dashboard shows amounts (`F-FMT`)

#### F-FMT-001 Amounts in lakhs

| Item | Value |
| --- | --- |
| Expression | `amount ÷ 1,00,000`, two decimals, with Indian grouping and "L" |
| In words | The Amounts setting in the top bar is Lakhs or Full. Lakhs is the default. With Lakhs, each amount shows in lakhs, for example "₹12.35 L". The hover shows the exact amount. The rounding is half away from zero. |
| Data | Each amount. |
| Signs | As the amount. A negative amount is crimson. |
| Dates | Not applicable. |
| Companies | Not applicable. |
| Check in Tally | Divide the amount in Tally by 1,00,000. |

#### F-FMT-002 Exact amounts (Full, hover, CSV)

| Item | Value |
| --- | --- |
| Expression | The amount to the paisa, with Indian grouping, for example "₹4,82,00,000.00" |
| In words | Each amount when the setting is Full, in the hover with Lakhs, and in each CSV file. Sums use the amounts before rounding. |
| Data | Each amount. |
| Signs | As the amount. |
| Dates | Not applicable. |
| Companies | Not applicable. |
| Check in Tally | Compare the amount with Tally directly. |

#### F-FMT-003 Chart amounts

| Item | Value |
| --- | --- |
| Expression | `amount ÷ 1,00,000` as a number |
| In words | Charts use amounts in lakhs only to draw. The dashboard never adds them and never shows them as figures. |
| Data | Each amount in a chart. |
| Signs | As the amount. |
| Dates | Not applicable. |
| Companies | Not applicable. |
| Check in Tally | Read the figure in the table below the chart. |

## Change log

| Version | Date | Change |
| --- | --- | --- |
| 2.1 | 2026-11-11 | Stock by godown and batch (F-STK-010 to F-STK-013), the inventory lines dataset (F-STK-014, F-STK-015), and the three sections proved against Tally. |
| 2.0 | 2026-11-11 | Moved from `formulas.md` to `formula-sheet.md`. Written again in ASD-STE100, with a Terms section, common rules and one table for each figure. Current ratio, quick ratio and debt to equity in the form of Schedule III (F-BS-007 to F-BS-011, F-RAT-008 to F-RAT-010). F-RAT-001 to F-RAT-003 retired. Stock items (F-STK-009). Data health (F-DAT-001 to F-DAT-004). A test fails when a figure on a page has no ID. |
| 1.2 | 2026-11-06 | Transactions (`F-TRN-001`). |
| 1.1 | 2026-11-06 | Stock (`F-STK-001` to `F-STK-008`); the Amounts setting (F-FMT-001, F-FMT-002). |
| 1.0 | 2026-11-02 | Rewritten as the formula sheet (RPT-015): an ID for each figure, with the formula, data, signs, Educational mode and the check in Tally. |
| 0.1 | 2026-11-02 | First version. |
