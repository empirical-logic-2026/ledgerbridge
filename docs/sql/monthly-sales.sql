-- Monthly sales report (RPT-013): one company, one financial year.
--
-- Rows: Gross Sales, Sales Returns, Other Adjustments, Net Sales. Columns: one per month of
-- the financial year (Apr-26, May-26, ... for a year starting in April), then Total.
-- Amounts as an accountant reads them: sales positive, returns negative; the four rows add
-- up (Gross Sales + Sales Returns + Other Adjustments = Net Sales).
--
-- How to run (MySQL Workbench, connected to the client's own LedgerBridge database):
--   1. Set @entity and @fy below. Nothing else needs changing.
--   2. Run the whole script (the lightning bolt, not "run the statement under the cursor").
-- Each run starts afresh: every other variable is set again from those two, so nothing left
-- over from an earlier run can change the result.
--
-- What the figures are (ledgerbridge_reporting.v_monthly_sales, migration 0021):
--   Net Sales          Every effective entry on the ledgers under the source's own Sales
--                      Accounts group (renamed or not) and its sub-groups, by voucher date.
--                      Not counted: cancelled, optional and memorandum vouchers, vouchers
--                      deleted in the source.
--   Gross Sales        The part posted by vouchers of a Sales voucher type.
--   Sales Returns      The part posted by vouchers of a Credit Note voucher type.
--   Other Adjustments  The part posted by every other voucher type (e.g. debit notes such as
--                      e-commerce adjustments, journals). Part 2 lists them by voucher type.
--
-- Compare in Tally (one month at a time):
--   Net Sales          Gateway of Tally > Profit & Loss A/c, period (F2) from the 1st to the
--                      last day of the month: the Sales Accounts line. Must be equal to the
--                      paisa. `./dev.ps1 validate monthly-sales` proves this for every stored
--                      period (counts only).
--   Gross Sales,       Tally has no line of its own for these: open the Sales Accounts line
--   Sales Returns,     for the same period and check the vouchers by voucher type against
--   Other Adjustments  part 2 below.
--   Educational mode:  TallyPrime in Educational mode gives reliable figures only up to the
--                      31st, 1st or 2nd of a month (docs/rules, Educational mode). For a month
--                      ending on the 30th or in February, compare Tally's 1st to the 2nd of
--                      the next month with part 3 below for the same days.

SET @entity = 2;   -- the company: ledgerbridge_accounting.entities.id
SET @fy = 2026;    -- the financial year by the calendar year it starts in: 2026 = Apr-26 to Mar-27

-- ---------------------------------------------------------------------------------------
-- Nothing below needs changing.
-- ---------------------------------------------------------------------------------------

-- The year's first day, from the company's own financial-year start month.
SET @fy_start = (
    SELECT DATE_ADD(MAKEDATE(@fy, 1), INTERVAL fy_start_month - 1 MONTH)
    FROM ledgerbridge_accounting.entities
    WHERE id = @entity
);

-- One column per month of the year, headed like Tally (Apr-26).
SET SESSION group_concat_max_len = 16384;
SET @month_columns = (
    WITH RECURSIVE months (n, month_start) AS (
        SELECT 0, @fy_start
        UNION ALL
        SELECT n + 1, DATE_ADD(month_start, INTERVAL 1 MONTH) FROM months WHERE n < 11
    )
    SELECT GROUP_CONCAT(
        CONCAT(
            'COALESCE(SUM(CASE WHEN month_start = ''', month_start, ''' THEN amount END), 0) AS `',
            DATE_FORMAT(month_start, '%b-%y'), '`'
        )
        ORDER BY n SEPARATOR ', '
    )
    FROM months
);

-- Part 1: the report. (Without a company of that @entity, a line saying so instead.)
SET @report = COALESCE(CONCAT(
    'SELECT line AS `Particulars`, ', @month_columns, ', COALESCE(SUM(amount), 0) AS `Total` ',
    'FROM (',
    '  SELECT 1 AS sort, ''Gross Sales'' AS line, month_start, gross_sales AS amount',
    '    FROM ledgerbridge_reporting.v_monthly_sales WHERE entity_id = @entity AND financial_year = @fy',
    '  UNION ALL SELECT 2, ''Sales Returns'', month_start, sales_returns',
    '    FROM ledgerbridge_reporting.v_monthly_sales WHERE entity_id = @entity AND financial_year = @fy',
    '  UNION ALL SELECT 3, ''Other Adjustments'', month_start, other_adjustments',
    '    FROM ledgerbridge_reporting.v_monthly_sales WHERE entity_id = @entity AND financial_year = @fy',
    '  UNION ALL SELECT 4, ''Net Sales'', month_start, net_sales',
    '    FROM ledgerbridge_reporting.v_monthly_sales WHERE entity_id = @entity AND financial_year = @fy',
    ') AS report_lines ',
    'GROUP BY sort, line ORDER BY sort'
), 'SELECT ''No company with this @entity: check ledgerbridge_accounting.entities'' AS `Problem`');
PREPARE report FROM @report;
EXECUTE report;
DEALLOCATE PREPARE report;

-- Part 2: net sales by voucher type (the channel breakdown). The rows add up to Net Sales.
SET @by_type = COALESCE(CONCAT(
    'SELECT voucher_type AS `Voucher type`, base_type AS `Kind`, ', @month_columns,
    ', COALESCE(SUM(amount), 0) AS `Total` ',
    'FROM (SELECT voucher_type, base_type, month_start, net_sales AS amount',
    '  FROM ledgerbridge_reporting.v_monthly_sales_by_voucher_type',
    '  WHERE entity_id = @entity AND financial_year = @fy) AS by_type ',
    'GROUP BY voucher_type, base_type ORDER BY base_type, voucher_type'
), 'SELECT ''No company with this @entity'' AS `Problem`');
PREPARE by_type FROM @by_type;
EXECUTE by_type;
DEALLOCATE PREPARE by_type;

-- Part 3: net sales for any days you choose (e.g. to compare with a Tally period in
-- Educational mode). Both dates are included.
SET @from_day = @fy_start;                                  -- change as needed
SET @to_day = LAST_DAY(@fy_start);                          -- change as needed
SELECT @from_day AS `From`, @to_day AS `To`, COALESCE(SUM(net_sales), 0) AS `Net Sales`
FROM ledgerbridge_reporting.v_daily_sales
WHERE entity_id = @entity AND on_date BETWEEN @from_day AND @to_day;
