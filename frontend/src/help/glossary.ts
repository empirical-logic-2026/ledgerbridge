// What every card, column header, ratio and status means, in plain words with its formula and
// its ID in docs/formulas.md: shown on hover (components/Explained.tsx), so the client can see
// how each value or status is worked out. Keyed by the label as shown; a label that means
// different things on different pages is written out where it is used instead.

export interface Explanation {
  text: string // in plain words
  formula?: string // as an expression
  id?: string // in docs/formulas.md
}

const SALES = 'the entries on the ledgers under the Sales Accounts group (by its role, at any depth)'
const PURCHASES = 'the entries on the ledgers under the Purchase Accounts group'
const STATEMENT = 'From our stored Profit & Loss (checked against the source\'s): the statement at the period\'s end less the one before its start.'

export const GLOSSARY: Record<string, Explanation> = {
  // --- sales and purchases ---
  'Net sales': { text: `Sales after returns and adjustments: ${SALES}.`, formula: 'Gross sales + sales returns (negative) + other adjustments', id: 'F-SAL-004' },
  'Net purchases': { text: `Purchases after returns and adjustments: ${PURCHASES}.`, formula: 'Gross purchases + purchase returns (negative) + other adjustments', id: 'F-SAL-004' },
  Net: { text: 'Gross less returns plus other adjustments, for this row.', formula: 'Gross + Returns + Other adjustments', id: 'F-SAL-004' },
  Gross: { text: 'The invoices\' entries on the sales (purchase) ledgers, before returns.', formula: 'Σ entries of sales (purchase) invoices on those ledgers', id: 'F-SAL-001' },
  Returns: { text: 'Credit notes on the sales ledgers (debit notes for purchases); shown negative.', formula: 'Σ entries of credit (debit) notes on those ledgers', id: 'F-SAL-002' },
  'Sales returns': { text: 'Credit notes on the sales ledgers, shown as a positive amount: lower is better.', formula: '− (credit notes on the Sales Accounts ledgers)', id: 'F-SAL-007' },
  'Purchase returns': { text: 'Debit notes on the purchase ledgers, shown as a positive amount.', formula: '− (debit notes on the Purchase Accounts ledgers)', id: 'F-SAL-007' },
  'Other adjustments': { text: 'Entries on the sales (purchase) ledgers from any other voucher, e.g. journals.', id: 'F-SAL-003' },
  Invoices: { text: 'How many invoice vouchers have an entry on the sales (purchase) ledgers.', formula: 'Count of invoice vouchers', id: 'F-SAL-005' },
  'Average invoice': { text: 'Gross sales per invoice.', formula: 'Gross ÷ Invoices', id: 'F-SAL-006' },
  'Closing balance': { text: 'Net from the start of the month\'s financial year to the month\'s end, as the source\'s monthly summary shows it.', formula: 'Σ Net, first month of the year to this month', id: 'F-SAL-008' },
  Closing: { text: 'Net from the start of the month\'s financial year to the month\'s end.', formula: 'Σ Net, first month of the year to this month', id: 'F-SAL-008' },
  Share: { text: 'This row\'s part of the total net.', formula: 'Row net ÷ total net × 100', id: 'F-SAL-010' },
  Customers: { text: 'How many customers (by name, across the companies) had sales in the period; vouchers without a party aren\'t counted.', formula: 'Count of distinct customer names with sales', id: 'F-SAL-011' },
  'Last invoice': { text: 'The date of the party\'s latest invoice in the period.' },
  'Channel (voucher type)': { text: 'A channel is a voucher type, known by its name across the companies.' },
  Amount: { text: 'The invoice\'s entries on the sales (purchase) ledgers, before taxes and freight.', id: 'F-SAL-014' },
  'Before taxes': { text: 'The voucher\'s entries on the sales (purchase) ledgers only.', id: 'F-REG-002' },
  Debit: { text: 'The voucher\'s first ledger entry when it is a debit, as the source\'s Day Book shows it.', id: 'F-REG-001' },
  Credit: { text: 'The voucher\'s first ledger entry when it is a credit.', id: 'F-REG-001' },
  Particulars: { text: 'The voucher\'s first ledger (for an invoice, the party), as the Day Book shows it.' },
  Reference: { text: 'The voucher\'s reference as entered in the source, e.g. the supplier\'s own invoice number.' },
  'Cheque / transfer no.': { text: 'The instrument number on the voucher\'s bank line: a cheque number or a transfer\'s number.' },
  UTR: { text: 'The unique transaction reference the bank gave an electronic transfer (NEFT, RTGS, IMPS), from the bank line.' },

  // --- cost centres ---
  'Cost centre': { text: 'Where a cost or income is tracked (a branch, project or department), by name across the companies.' },
  'Cost category': { text: 'The set of cost centres an allocation belongs to; one voucher line can be allocated in several categories.' },
  Under: { text: 'The cost centre this one sits under in the source.' },
  Allocated: { text: 'The parts of voucher lines allocated to the cost centre, with the line\'s sign (debits positive); its own allocations only, not the ones under it.', formula: 'Σ allocation amounts', id: 'F-CC-001' },
  Allocations: { text: 'How many allocations were made to the cost centre in the period.', formula: 'Count of allocations', id: 'F-CC-003' },

  // --- transactions ---
  'Voucher Type': { text: 'The kind of voucher (Sales, Payment, Journal, ...), by name.' },
  'Voucher Number': { text: 'The voucher\'s number in the source.' },
  'Reference Number': { text: 'The voucher\'s reference as entered in the source, e.g. the supplier\'s own invoice number.' },
  'Party Name': { text: 'The voucher\'s party (customer or vendor), when it has one.' },
  'Ledger Name': { text: 'The ledger of this line.' },
  Narration: { text: 'The voucher\'s narration as entered in the source.' },

  // --- stock ---
  'Stock value': { text: 'The source\'s own value of all stock (its valuation method) at the last stored date within the period.', id: 'F-STK-007' },
  'Stock items': { text: 'How many stock items the companies have, by name.' },
  'Items with negative stock': { text: 'Items whose closing quantity is below zero: more went out than came in. Worth checking in the source.', id: 'F-STK-004' },
  'Opening qty': { text: 'The quantity at the period\'s start: the item\'s opening plus every movement before that day.', id: 'F-STK-001' },
  'Inward qty': { text: 'The quantity that came in during the period (purchases, receipts, production, transfers in).', id: 'F-STK-002' },
  'Outward qty': { text: 'The quantity that went out during the period (sales, deliveries, consumption, transfers out).', id: 'F-STK-003' },
  'Closing qty': { text: 'The quantity at the period\'s end, proven against the source\'s at each validation.', formula: 'Opening + Inward − Outward', id: 'F-STK-004' },
  'Closing quantity': { text: 'The quantity at the period\'s end, proven against the source\'s at each validation.', formula: 'Opening + Inward − Outward', id: 'F-STK-004' },
  'Balance qty': { text: 'The quantity after this movement.', id: 'F-STK-004' },
  Quantity: { text: 'The quantity this voucher moved: in positive, out negative.', id: 'F-STK-002' },
  Value: { text: 'The source\'s own closing value of the stock (its valuation method) at the last stored date within the period.', id: 'F-STK-005' },
  Rate: { text: 'The value per unit of the closing quantity.', formula: 'Value ÷ Closing quantity', id: 'F-STK-006' },
  'Voucher value': { text: 'The line\'s amount on the voucher (what it was bought or sold for), not the stock valuation.', id: 'F-STK-008' },
  'Stock group': { text: 'The stock group the item sits in.' },
  Godown: { text: 'The location the stock moved in or out of.' },

  // --- profit and loss ---
  Revenue: { text: `Net sales from the stored Profit & Loss. ${STATEMENT}`, id: 'F-PL-001' },
  'Gross profit': { text: `Net sales and direct incomes less cost of sales. ${STATEMENT}`, formula: 'Net sales + direct incomes − cost of sales', id: 'F-PL-003' },
  'Net profit': { text: `Gross profit plus indirect incomes less indirect expenses; negative for a loss. ${STATEMENT}`, formula: 'Gross profit + indirect incomes − indirect expenses', id: 'F-PL-004' },
  'Cost of sales': { text: `Opening stock + purchases + direct expenses − closing stock. ${STATEMENT}`, formula: 'Opening stock + purchases + direct expenses − closing stock', id: 'F-PL-002' },
  'Gross margin': { text: 'Gross profit as a percentage of net sales.', formula: 'Gross profit ÷ Net sales × 100', id: 'F-PL-005' },
  'Gross margin %': { text: 'Gross profit as a percentage of net sales.', formula: 'Gross profit ÷ Net sales × 100', id: 'F-PL-005' },
  'Net margin': { text: 'Net profit as a percentage of net sales.', formula: 'Net profit ÷ Net sales × 100', id: 'F-PL-006' },
  'Net profit %': { text: 'Net profit as a percentage of net sales.', formula: 'Net profit ÷ Net sales × 100', id: 'F-PL-006' },
  'Other costs': { text: 'Indirect expenses less indirect incomes, as a percentage of net sales.', formula: '(Gross profit − Net profit) ÷ Net sales × 100', id: 'F-PL-010' },
  '% of sales': { text: 'The line as a percentage of the same column\'s net sales.', formula: 'Line ÷ Net sales × 100', id: 'F-PL-008' },
  'This period': { text: 'The figure for the period chosen (the statement at its end less the one before its start).', id: 'F-PL-007' },
  'Last year': { text: 'The same figure for the same months or dates a year earlier.', id: 'F-CMP-002' },
  'Compared period': { text: 'The same figure for the period compared with: the previous period or last year (top bar).', id: 'F-CMP-002' },
  Change: { text: 'How much the figure moved against the period compared with; percentages move in points.', formula: '(This − Before) ÷ |Before| × 100', id: 'F-CMP-001' },
  'Change %': { text: 'How much the figure moved against the period compared with.', formula: '(This − Before) ÷ |Before| × 100', id: 'F-CMP-001' },
  Total: { text: 'The sum of the rows shown (after the filter). Balance columns aren\'t added up.', id: 'F-TBL-001' },

  // --- balances, parties, bills ---
  'Cash & bank': { text: 'The ledgers under Cash-in-Hand and Bank Accounts: opening balances plus every entry up to the date.', formula: 'Σ opening + Σ entries up to the date', id: 'F-BAL-002' },
  'Balance due': { text: 'What the customer owes at the period\'s end: their ledgers\' opening balance plus every entry up to that day.', formula: 'Opening + Σ entries up to the period end', id: 'F-PTY-001' },
  'Balance payable': { text: 'What we owe the vendor at the period\'s end: their ledgers\' balance, shown positive.', formula: '− (Opening + Σ entries up to the period end)', id: 'F-PTY-001' },
  Balance: { text: 'The running balance: the previous balance plus this entry (Dr: owed to us, Cr: we owe).', formula: 'Previous balance + entry', id: 'F-PTY-009' },
  Overdue: { text: 'Outstanding bills whose due date has passed at the period\'s end. A bill is due on its own due date, else its date plus the party\'s credit period.', formula: 'Σ outstanding bills with due date < period end', id: 'F-PTY-002' },
  'Over 90 days': { text: 'Outstanding bills more than 90 days past their due date.', id: 'F-PTY-012' },
  'Not due': { text: 'Outstanding bills whose due date hasn\'t come yet.', id: 'F-PTY-012' },
  '1–30 days': { text: 'Outstanding bills 1 to 30 days past their due date.', id: 'F-PTY-012' },
  '31–60 days': { text: 'Outstanding bills 31 to 60 days past their due date.', id: 'F-PTY-012' },
  '61–90 days': { text: 'Outstanding bills 61 to 90 days past their due date.', id: 'F-PTY-012' },
  'Not in bills': { text: 'The part of the balance the bills (opening bills and the vouchers\' bills) don\'t cover: amounts not split into bills, such as on account.', formula: 'Balance due − Σ outstanding bills', id: 'F-PTY-013' },
  Pending: { text: 'The bill\'s new reference less everything settled against it, up to the period\'s end.', id: 'F-PTY-004' },
  Due: { text: 'The bill\'s own due date, else its date plus the party\'s credit period.', id: 'F-PTY-005' },
  'Overdue by': { text: 'Days from the bill\'s due date to the period\'s end.', formula: 'Period end − due date', id: 'F-PTY-005' },
  'Average days to pay': { text: 'For bills settled in the period: the days from each bill\'s date to its settlement, weighted by amount.', formula: 'Σ(amount × days) ÷ Σ amount', id: 'F-PTY-007' },
  Receipts: { text: 'What receipt vouchers put on the customer\'s ledgers in the period.', id: 'F-PTY-006' },
  Payments: { text: 'What payment vouchers put on the vendor\'s ledgers in the period.', id: 'F-PTY-006' },

  // --- statuses ---
  Status: { text: 'Uses the remaining bill-wise amount and due date: overdue or pending when positive, advance when negative, settled at zero. Payables reverse the ledger debit/credit sign so amounts owed to suppliers are positive. Without bill details, the report does not guess a due-date status.', id: 'F-PTY-002' },
  'No bill details': { text: 'There is no bill-wise allocation to determine a payment status.', id: 'F-PTY-002' },
  'Multiple bill statuses': { text: 'The party has open bills with different due-date or credit states; inspect each bill for its own status.', id: 'F-PTY-002' },
  Paid: { text: 'Nothing of this invoice\'s bill is outstanding.', id: 'F-PTY-004' },

  // --- balance sheet and ratios ---
  'Current ratio': { text: 'Current assets over current liabilities: can short-term debts be paid from short-term assets?', formula: 'Current assets ÷ Current liabilities', id: 'F-RAT-001' },
  'Quick ratio': { text: 'As the current ratio, without the stock.', formula: '(Current assets − Closing stock) ÷ Current liabilities', id: 'F-RAT-002' },
  'Debt to equity': { text: 'Loans against the owners\' funds.', formula: 'Loans (Liability) ÷ (Capital Account + Profit & Loss A/c)', id: 'F-RAT-003' },
  'Receivable days': { text: 'How many days of sales are still to be collected.', formula: 'Receivables ÷ Net sales × days in the period', id: 'F-RAT-004' },
  'Payable days': { text: 'How many days of purchases are still to be paid.', formula: 'Payables ÷ Net purchases × days in the period', id: 'F-RAT-005' },
  'Inventory days': { text: 'How many days of cost of sales the closing stock covers.', formula: 'Closing stock ÷ Cost of sales × days in the period', id: 'F-RAT-006' },
  'Working-capital days': { text: 'How long money is tied up between paying for stock and collecting from customers.', formula: 'Receivable days + Inventory days − Payable days', id: 'F-RAT-007' },

  // --- cash ---
  'Money in': { text: 'Debits to the cash and bank ledgers in the period, by voucher.', id: 'F-CF-001' },
  'Money out': { text: 'Credits to the cash and bank ledgers in the period, shown positive.', id: 'F-CF-001' },
  'Cash & bank at the start': { text: 'Cash and bank the day before the period.', id: 'F-BAL-002' },
  'Cash & bank at the end': { text: 'Cash and bank at the period\'s end: the start plus money in less money out.', formula: 'Start + Money in − Money out', id: 'F-BAL-002' },
  For: { text: 'What the money was for: the group of the voucher\'s other ledgers (customers, suppliers, expenses, taxes, loans…), split by their amounts.', id: 'F-CF-001' },

  // --- data health ---
  Checks: { text: 'Whether our books and statements matched the source\'s own at the last validation.' },
  'Checks passed': { text: 'How many companies passed their latest checks against the source.' },
  'In the source': { text: 'Whether the source had the company loaded when last asked (a sync or the entity check).' },
  'Loaded in the source': { text: 'How many companies the source had loaded when last asked.' },
  'Checked up to': { text: 'The latest date the checks compared.' },
  'Last sync': { text: 'When the books were last brought up to date from the source.' },
}

/** The explanation of a label, as one line for a tooltip; undefined when there is none. */
export function explain(label: string): string | undefined {
  const found = GLOSSARY[label]
  if (!found) return undefined
  return [found.text, found.formula && `= ${found.formula}`, found.id && `(${found.id})`].filter(Boolean).join(' ')
}
