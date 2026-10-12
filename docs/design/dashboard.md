# Dashboard design: home page

| Field | Value |
| --- | --- |
| Version | 0.1 |
| Date | 2026-10-12 |
| Status | Approved design for M7 |
| Mockup | [dashboard-mockup.png](dashboard-mockup.png) |

The mockup is the approved design for the dashboard home page. M7 must match its **layout, wording and visual style**. The figures, company names, party names and voucher numbers in it are illustrative sample data; the built page shows real values from the reporting API (M6). The footer text "Illustrative mockup with sample figures" belongs to the mockup only and is not part of the product.

Requirements covered: RPT-001 (MIS dashboard), RPT-002 (health indicators with good/bad flags), RPT-006 (entity and consolidated), RPT-007 (drill-down), RPT-008 (period filters), AI-001 (questions in plain language, M8), VAL-* (data checks, M4).

![Dashboard home page mockup](dashboard-mockup.png)

## 1. Principles

- **Plain language for business owners.** Labels say what the user cares about ("Who owes us", "Needs your attention"), not accounting jargon ("Receivables ageing", "Exceptions"). Use the wording below exactly.
- **Every number is clickable** and opens the entries behind it (RPT-007).
- **Status at a glance.** Each figure carries a coloured status line: green good, amber watch, red act.
- **Generic, not Tally-specific (PIL-003).** Where the mockup says "Tally", the page shows the connection's source name (for example "Synced with Tally", later "Synced with Zoho Books"). Company names, the number of companies and the financial year all come from data.
- **Indian number format.** Amounts in rupees with lakh (L) and crore (Cr) units: `₹4.82 Cr`, `₹62.4 L`. Chart axes in ₹ lakh. Exact amounts in full Indian grouping (`₹16,20,000.00`) on hover and in drill-down.

## 2. Layout

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Top bar: LedgerBridge · company switcher · period switcher · sync status pill │
├──────┬───────────────────────────────────────────────────────────────────────┤
│ LIVE │ scrolling ticker of recent sync events                                │
├──────┴──────┬────────────────────────────────────────────────────────────────┤
│ Sidebar     │ Greeting line                                                  │
│             │ Hint line                                                      │
│ Home        │ [Health] [Sales] [Profit] [Cash & bank] [Overdue 60+]          │
│ Profit &    │ ┌ Sales vs expenses chart (≈60%) ┐ ┌ Needs your attention ┐     │
│ Loss  ...   │ └────────────────────────────────┘ └──────────────────────┘     │
│             │ ┌ Ask a question about your business (full width) ──────────┐  │
│             │ └────────────────────────────────────────────────────────────┘  │
└─────────────┴────────────────────────────────────────────────────────────────┘
```

- Fixed top bar and LIVE strip; fixed sidebar; the content area scrolls.
- Content order top to bottom: greeting, hint, five KPI cards in one row, then the chart and the attention panel side by side (chart about 60% of the width), then the full-width question panel.
- On narrow screens (tablet and phone) the sidebar collapses to a menu button, KPI cards wrap, and the chart and attention panel stack.

## 3. Elements

### 3.1 Top bar

Dark navy bar across the full width.

| Element | Content and behaviour |
| --- | --- |
| Product name | "LedgerBridge", bold white, left. |
| Company switcher | Dropdown showing the current selection: **"Consolidated: Company A + Company B"** or a single company name. Options: Consolidated (all companies the user may see) and each company. Lists only entities the user has access to (ACC-002). Consolidated appears only when the user has two or more. |
| Period switcher | Dropdown showing financial year and range, for example **"FY 2026-27 · Apr–Sep"**. Offers the current and previous financial years, quarters and months, and year to date. Defaults to the current financial year to date. |
| Sync status pill | Rounded dark-green pill on the right: green dot and **"Synced with Tally 1 min ago"** (source name and relative time from the last successful sync of the selected companies). If the last sync failed or is overdue the pill turns amber ("Last synced with Tally 2 h ago"); if a sync is running it says "Syncing with Tally…". Clicking it opens the sync detail (last runs, from `sync_runs`). |

### 3.2 LIVE strip

Thin full-width strip directly below the top bar.

- Left: a red block with a white dot and **"LIVE"**.
- Right: a continuously scrolling ticker of recent sync events, separated by "•", each starting with a time:
  - "10:42 New sales invoice SI-118 for ₹2.4 L synced from Tally"
  - "10:40 Payment of ₹5.0 L received from Customer B"
  - "10:36 Bank balance updated: ₹82.3 L"
  - GST payable changes, for example "GST payable now ₹3.1 L"
  - data checks passed, for example "Data checks passed for Company A"
- Event types: new vouchers (sales, purchases), payments received and made, bank balance updates, GST payable changes, data checks passed or failed.
- Events come from the recent-events feed (M6), filtered to the selected companies and the user's entity access. Clicking an event opens its voucher or check.
- The ticker pauses on hover and honours the "reduce motion" system setting (static list instead of scrolling).

### 3.3 Sidebar

Light background, icon plus label, in this order and with this wording:

| Item | Opens | Milestone |
| --- | --- | --- |
| Home | This page | M7 |
| Profit & Loss | P&L statement | M6/M7 |
| Balance Sheet | Balance sheet | M6/M7 |
| Cash Flow | Cash flow statement | M6/M7 |
| Who owes us | Receivables with ageing | M6/M7 |
| Who we owe | Payables with ageing | M6/M7 |
| Data checks | Validation results (data-quality page) | M4/M7 |
| Ask a question | Full-page AI questions | M8 |

The active item has a pale teal background with teal bold text. The Trial Balance page (RPT-003) is not in the mockup's sidebar; it is reached from Data checks and from the Balance Sheet page (see Section 6).

### 3.4 Greeting and hint

- Greeting, large bold: **"Good morning! Here's how your business is doing."** "Good morning", "Good afternoon" or "Good evening" by the user's local time.
- Hint, grey below it: **"Everything below updates automatically from Tally. Click any number to see the entries behind it."** ("Tally" replaced by the source name.)

### 3.5 KPI cards

Five equal white cards in one row. Each has a small grey label, a large value and a coloured status line.

| Card | Value | Status line (examples) |
| --- | --- | --- |
| **Business health** | A label (**Good**, in green) and **"78 / 100"** below it. The card has a pale green background and green border when Good; amber or red equivalents for the other bands. | The score out of 100. |
| **Sales** | Sales for the selected period, for example **₹4.82 Cr**. | **"▲ 12% vs last year"** (green when up, red when down). |
| **Profit** | Net profit for the period, for example **₹62.4 L**. | **"▲ 8% vs last year"**. |
| **Cash & bank** | Total cash and bank balance at the period end, for example **₹1.15 Cr**. | **"Enough for 4.2 months"** (months of cash cover), coloured by threshold (amber in the mockup). |
| **Overdue (60+ days)** | Customer bills overdue more than 60 days, for example **₹38.6 L**. | **"Needs follow-up"** in red when above threshold, green "All on time" otherwise. |

- Status colours come from `kpi_definitions` thresholds (RPT-002), not from the frontend.
- Clicking a value opens the drill-down (for example, Overdue opens "Who owes us" filtered to 60+ days).
- The business health score, its label bands and cash cover are computed in M6 (Section 4).

### 3.6 Sales vs expenses chart

White card titled **"Sales vs expenses, month by month (₹ lakh)"**.

- ECharts grouped bar chart, one group per month of the selected period (Apr … Sep): **Sales** dark teal bars, **Expenses** light grey-blue bars.
- **Profit** as an orange line with round markers over the bars.
- Legend at the top left in the order Profit, Sales, Expenses. Y axis in ₹ lakh from 0.
- Clicking a bar or point opens the entries for that month and measure.

### 3.7 "Needs your attention" panel

White card titled **"Needs your attention"**, beside the chart. A short list (up to five) of plain-language alerts, most severe first. Each alert has:

- a coloured dot: red (act now), amber (watch), green (all good);
- a bold one-line message, for example **"Customer A is 94 days overdue (₹16.2 L)"**, **"Rent and electricity up 18% this quarter"**, **"All entries match Tally for both companies"**;
- a grey suggested action or detail, for example "Send a reminder or review credit terms", "See the expense breakdown", "Last checked 1 min ago".

Alerts come from simple rules computed in M6 (Section 4). Clicking an alert opens the related page or entries. When nothing needs attention, the panel shows the green data-check line only.

### 3.8 "Ask a question" panel

Full-width white card.

- Title in teal: **"Ask a question about your business"**.
- Privacy note at the top right, grey: **"Private: answers come from your own books, nothing leaves your system"**. This text must match the client's actual AI privacy mode (AI-011): it is shown as written only in `private` mode; `schema-only` and `full` show their own accurate note.
- A text input (placeholder or last question, for example "Which customers are more than 60 days overdue?") with a teal **Ask** button.
- The answer below the input in plain text, for example "3 customers owe ₹38.6 lakh beyond 60 days. Customer A (₹16.2 L, 94 days), …", with a link to show the SQL and source records (M8).
- Suggested question chips, pale teal with teal text:
  - "What was profit last month?"
  - "Compare both companies" (shown only when two or more companies are selected; wording "Compare companies" when more than two)
  - "Top 5 expenses this quarter"
  - **"Who do we owe the most?"**: replaces the mockup's "Cash forecast for next month" chip, because forecasting (AI-009) is phase 3. Restore the forecast chip only when forecasting exists.
- M7 builds the panel; M8 connects it to the AI (see Section 6 for what it shows before M8).

## 4. Data the home page needs (M6)

| Element | Source in M6 |
| --- | --- |
| Sales, Profit, comparison with last year | P&L and sales views, current period vs same period last year. |
| Cash & bank | Balances of ledgers mapped to cash and bank standard accounts. |
| Cash cover in months | Cash & bank ÷ average monthly cash outflow; the exact definition (which outflows, how many months averaged) is documented in M6. |
| Overdue 60+ days | Receivables ageing, buckets above 60 days. |
| Business health score | A documented formula giving a score from 0 to 100 and a label (for example Good / Fair / Needs attention), built from KPIs with thresholds in `kpi_definitions`. The components, weights and bands are proposed in M6 and approved by the developer before they are built. |
| Monthly sales, expenses, profit | Monthly P&L views. |
| Needs your attention | Simple rule-based alerts (for example customers overdue beyond a threshold, an expense group up more than a threshold on the previous period, the latest validation result), each with severity, message and suggested action. Rules and thresholds are configurable. |
| LIVE ticker | Recent-events feed written after each sync (new vouchers, payments, bank balance and GST payable changes, data-check results). |
| Sync status pill | Last successful sync per connection (`sync_runs`). |

All of it respects the user's entity access and the selected companies and period.

## 5. Visual style

Approximate colours sampled from the mockup; define them once as Ant Design theme tokens.

| Use | Colour |
| --- | --- |
| Top bar background | Dark navy, about `#1F2937` |
| Primary (Sales bars, Ask button, active sidebar text, panel title) | Dark teal, about `#0F766E` |
| Active sidebar item, chips | Pale teal, about `#CCFBF1` background |
| LIVE block | Red, about `#C62828` |
| Sync pill | Dark green background, light green text |
| Page background | Light grey, about `#F5F6F8`; cards white with a light grey border and rounded corners (about 8 px) |
| Expenses bars | Light grey-blue, about `#CBD5E1` |
| Profit line, amber status | Orange, about `#B45309` |
| Good status | Green, about `#15803D` |
| Bad status | Red, about `#B91C1C` |
| Text | Near-black headings, grey secondary text |

Typography: the Ant Design sans-serif font stack; bold for card values and panel titles; small grey labels.

## 6. Open points for M7 planning

- Where the Trial Balance page lives (proposed: linked from Data checks and from Balance Sheet, not in the sidebar).
- Login, user menu and sign-out are not in the mockup; proposed in the top bar's right corner after the sync pill.
- What the "Ask a question" panel shows between M7 and M8: proposed hidden, so the page never offers something that does not work yet; the alternative is showing it with Ask disabled.

## Change log

| Date | Version | Change |
| --- | --- | --- |
| 2026-10-12 | 0.1 | Home page design described from the approved mockup. "Cash forecast for next month" chip replaced by "Who do we owe the most?" until forecasting (AI-009, phase 3). |
