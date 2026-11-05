# TallyPrime data-completeness audit

This audit describes the collections and fields the checked-in Tally connector requests;
it does not claim to enumerate every collection TallyPrime offers. The evidence is
`data-plane/connectors/tally/envelopes.py`, `mapping.py`, and the recordings listed in
`data-plane/tests/fixtures/tally/manifest.json`. No live or pilot export was used.

The recordings use LedgerBridge's selected field lists. They cannot establish which
additional fields or object types exist in a particular company. A true all-fields
inventory requires a separate, approved full export from the test company. Do not treat
an absent fixture collection as a confirmed zero: the fixture transport answers recognized
but unrecorded collections with an empty response.

## 1. Object-type coverage

Importance is based on whether omission can change accounting figures, support analysis,
or is outside the current analytics scope. “Not confirmed” means neither the connector
projection nor the checked-in recordings establish that Tally offers/has that object in
the test company.

### Critical for accounting figures

| Object / meaning | Fetched? | Stored as | Count difference | Recommendation |
|---|---|---|---|---|
| Company identity and selected settings | Partly. Company export includes name, books-from/start dates, formal name, state, GSTIN, PAN, country, currency, cost-centre and inventory-integration flags. | `accounting.entities` and `accounting.entity_sources`; unmapped non-empty settings go to `extra`. | `0` in the recorded test fixture (1 source company, 1 stored link). | Keep settings in `extra` until a requirement needs a typed column. |
| Account groups | Yes (`Group`). | `accounting.account_groups`; synthetic `Primary` is excluded from counts. | `0` in the recorded test fixture. | Store as columns; already implemented. |
| Ledgers / accounts | Yes (`Ledger`). | `accounting.ledgers`; party details also populate `accounting.parties`. | `0` in the recorded test fixture. | Store as columns; already implemented. |
| Vouchers, of every type returned by Tally's Voucher collection | Yes, without a type filter; fetched by month or by AlterID. This includes order, delivery/receipt note, job-work, physical-stock, memorandum, optional and post-dated vouchers when returned by that collection. | `accounting.vouchers`, `voucher_lines`, bill/cost/tax allocations, inventory lines, and voucher `extra`. | `0` for each recorded month/type row (April–September 2026); cancelled, optional and non-accounting rows are listed separately; soft-deleted vouchers are excluded from active counts and listed separately. | Store as columns/child rows; already implemented. |
| Currency masters and exchange rates | Currency master requested using `NATIVEMETHOD *`; its rate lists are parsed. Voucher-derived and source-listed rates are stored. No currency-master response is present in the current fixture manifest. | `accounting.currency_sources`, `accounting.exchange_rates`; unmatched fields in `extra`. | Not recorded in the current fixtures; not treated as zero. | Keep rates in the existing rate model; confirm the source export before assessing coverage. |

### Useful for analysis

| Object / meaning | Fetched? | Stored as | Count difference | Recommendation |
|---|---|---|---|---|
| Voucher types | Yes (`VoucherType`). | `accounting.voucher_types`. | `0` in the recorded test fixture. | Store as columns; already implemented. |
| Cost categories and cost centres | Yes (`CostCategory`, `CostCentre`); the cost-category collection is absent from the current fixture manifest. | `accounting.cost_categories`, `accounting.cost_centres`. | Cost categories are not recorded; cost-centre difference is `0` in the recorded test fixture. | Store as columns; already implemented. |
| Stock groups, stock items, units and godowns | Yes (`StockGroup`, `StockItem`, `Unit`, `Godown`). | `accounting.item_groups`, `items`, `units`, `godowns`. | `0` in the recorded test fixture. | Store as columns; already implemented. |
| Batch allocations on voucher inventory entries | Read where included in a voucher export. | Batch name and quantity are on `accounting.inventory_lines`; no separate batch-master table. | No separate batch-master count. | Keep the current line detail unless batch-master analytics are required. |
| GST identity and tax details on ledgers | Ledger GSTIN, tax type and duty head are requested. | GSTIN on ledger/party; tax type on `accounting.ledgers`; voucher tax postings on `accounting.tax_lines`. | Included in ledger/voucher counts. | Keep typed fields already used in accounting; other registration details need evidence and a requirement. |

### Not needed for current accounting analytics, or not confirmed

| Object / meaning | Fetched? | Stored as | Count difference | Recommendation |
|---|---|---|---|---|
| Stock categories | Not requested or recorded. | None. | Not countable. | Not needed for current accounting analytics unless a reporting requirement emerges. |
| Voucher classes | No separate collection/request or recording. | No separate class table; voucher type and unrecognized fields may be in `extra`. | Not countable. | Confirm through a test-company export before deciding. |
| Price lists and price levels | Not requested or recorded. | None. | Not countable. | Not needed for current accounting analytics. |
| Bills of materials (BOMs) | Not requested or recorded. | None. | Not countable. | Not needed for current accounting analytics. |
| Budgets and scenarios | Not requested or recorded. | Planned budget tables are not part of this extraction. | Not countable. | Separate planned feature; confirm source objects when scoped. |
| Employee groups, employees, pay heads, attendance types and payroll units | No collections or recordings for these types. | None. | Not countable. | Not needed for current accounting analytics; payroll is a separate scope. |
| Separate GST registrations, TDS/TCS natures and interest parameters | No dedicated collections or recordings. Some ledger GST/tax fields are fetched as described above. | Only fields used by the current ledger/tax mapping; other returned non-empty fields may be in `extra`. | Not countable as separate objects. | Confirm the exact source objects and accounting use before adding tables. |
| Batch masters | No separate persistent batch-master collection. | Voucher batch allocations only, on inventory lines. The connector also has a batch-balance report for validation. | No batch-master count. | Keep line-level batch details unless master-level reporting is required. |

The source also provides validation-only exports (for example balances, stock values,
bills and cost-centre totals). These are comparison inputs, not additional persistent
master tables. Their presence does not mean that a corresponding Tally object is fully
stored.

## 2. Field coverage

“Requested fields” below are the explicit collection projection in `envelopes.py`;
`Currency` is the exception and uses `NATIVEMETHOD *`. Fields shown as `extra` are stored
under their original path in the object's JSON `extra`. The raw XML remains in
`ledgerbridge_source.raw_records` regardless of whether a field maps, is kept in `extra`,
or is omitted from the canonical model. The catalogue (`./dev.ps1 fields`) records fields
found in `extra`; it does not catalogue fields that were mapped or deliberately excluded.

For brevity, `GUID` and `ALTERID` mean the source-tracking `source_key` and
`source_alter_id` columns where the target is source-tracked. `MASTERID` is not a canonical
column and is excluded from `extra`, but remains in the raw payload. The `LANGUAGENAME`
name path is consumed for aliases when present; the projections do not request it.
`LANGUAGEID` and currency `PARENT` are marked as used by the mapping registry but have no
canonical destination, so they are not copied to `extra`.
`ISDEEMEDPOSITIVE` on ledger postings is used by the sign-check diagnostic, not stored as a
column; canonical ledger amounts use the signed `AMOUNT`.

### Company and masters

| Object type | Requested fields and destination |
|---|---|
| Company | `NAME` → `entities.name`; `GUID` → `entity_sources.source_entity_key`; `ALTERID` → raw record tracking; `BOOKSFROM` → `entities.books_from`; `STARTINGFROM` → `entities.fy_start_month`; `BASICCOMPANYFORMALNAME` → `entities.legal_name`; `STATENAME` → `entities.state_code`; `GSTREGISTRATIONNUMBER` → `entities.gstin`; `INCOMETAXNUMBER` → `entities.pan`. `MASTERID` is dropped from canonical data. Non-empty `COUNTRYNAME`, `CURRENCYNAME`, `ISCOSTCENTRESON` and `ISINTEGRATED` values go to `extra`. |
| Group | `GUID`, `ALTERID`, `NAME`, `PARENT`, `ISREVENUE`, `ISDEEMEDPOSITIVE`, `AFFECTSGROSSPROFIT` → `account_groups` source tracking, name/parent, nature, gross-profit flag and derived group role. `MASTERID` is dropped. |
| Ledger | `GUID`, `ALTERID`, `NAME`, `PARENT`, `OPENINGBALANCE`, `ISBILLWISEON`, `ISCOSTCENTRESON`, `CURRENCYNAME`, `TAXTYPE`, `GSTDUTYHEAD`, `PARTYGSTIN`, `LEDGSTREGDETAILS.LIST/GSTIN`, `INCOMETAXNUMBER`, `LEDSTATENAME`, `LEDMAILINGDETAILS.LIST/STATE`, `COUNTRYNAME`, `EMAIL`, `LEDGERPHONE`, `LEDGERMOBILE`, `BILLCREDITPERIOD`, `CREDITLIMIT` → source tracking, ledger opening/currency/flags/tax fields and party GSTIN/PAN/state/country/contact/credit fields. `GSTDUTYHEAD` helps derive `tax_type`; it has no separate column. `MASTERID` is dropped. |
| Currency | `NATIVEMETHOD *` requests the whole object. `GUID`, `ALTERID`, `NAME`, `ORIGINALNAME`, `EXPANDEDSYMBOL`, `ISOCURRENCYCODE`, `MAILINGNAME`, `DECIMALPLACES` and rate-list values → `currency_sources`, `exchange_rates`, or source tracking. `MASTERID` and `PARENT` have no canonical destination; other non-empty paths go to `extra`. Full field coverage is unconfirmed because the fixture has no currency-master export. |
| Voucher type | `GUID`, `ALTERID`, `NAME`, `PARENT`, `AFFECTSSTOCK` → `voucher_types` source tracking, name, parent and `is_inventory`; the standard/base type and `moves_stock` are derived from known Tally type names. `MASTERID` is dropped. `RESERVEDNAME`, if returned though it is not explicitly projected, contributes to type mapping and is retained in `extra`. |
| Unit | `GUID`, `ALTERID`, `NAME`, `ORIGINALNAME`, `DECIMALPLACES` → `units` source tracking, symbol, name and decimal places. `MASTERID` is dropped; `ISSIMPLEUNIT` goes to `extra` if returned. |
| Stock group | `GUID`, `ALTERID`, `NAME`, `PARENT` → `item_groups` source tracking, name and parent. `MASTERID` is dropped. |
| Godown | `GUID`, `ALTERID`, `NAME`, `PARENT`, `ISEXTERNAL`, `ISINTERNAL` → `godowns` source tracking, name/parent and derived holding. `MASTERID` is dropped. |
| Stock item | `GUID`, `ALTERID`, `NAME`, `PARENT`, `BASEUNITS`, `OPENINGBALANCE`, `OPENINGVALUE` → `items` source tracking, name/group/unit/opening quantity/opening value. `MASTERID` is dropped; `OPENINGRATE` goes to `extra` if returned. |
| Cost category | `GUID`, `ALTERID`, `NAME` → `cost_categories` source tracking and name. `MASTERID` is dropped. |
| Cost centre | `GUID`, `ALTERID`, `NAME`, `PARENT`, `CATEGORY` → `cost_centres` source tracking, name/parent/category. `MASTERID` is dropped. |

### Vouchers and nested lines

| Object type | Requested fields and destination |
|---|---|
| Voucher header | `GUID`, `ALTERID`, `DATE`, `EFFECTIVEDATE`, `UPDATEDDATETIME`, `VOUCHERTYPENAME`, `VOUCHERNUMBER`, `REFERENCE`, `REFERENCEDATE`, `PARTYLEDGERNAME`, `NARRATION`, `ISCANCELLED`, `ISOPTIONAL`, `ISPOSTDATED` → `vouchers` source tracking, date/effective/alteration dates, type, number, reference, party, narration and flags. `MASTERID` is not canonical. `ISDELETED` is treated as Tally bookkeeping and omitted from `extra`, while the raw payload retains it. `ISINVOICE` has no dedicated mapping and goes to `extra` when non-empty. |
| Ledger entries | `AllLedgerEntries.LedgerName`, `.Amount`, `.IsDeemedPositive`, `.IsPartyLedger` → `voucher_lines` (ledger, canonical signed amount, party-line flag); supported `LedgerEntries` aliases use the same mapping. `.IsDeemedPositive` is not a stored column; it is used by the sign-check diagnostic. |
| Bill allocations | `AllLedgerEntries.BillAllocations.Name`, `.BillType`, `.Amount` → `bill_allocations` (bill reference/type/amount). |
| Cost-centre allocations | `AllLedgerEntries.CategoryAllocations.Category`, `.CostCentreAllocations.Name`, `.Amount` → `line_cost_allocations`. The same paths under `AllInventoryEntries.AccountingAllocations` are mapped to the item posting's ledger lines. |
| Bank allocations | `AllLedgerEntries.BankAllocations.InstrumentNumber` and `.UniqueReferenceNumber` → voucher-line instrument and transaction-reference columns. `.Name`, `.Date`, `.TransactionType`, `.InstrumentDate` and `.Amount` have no dedicated mapping and go to `extra` when non-empty. |
| Inventory entries | `AllInventoryEntries.StockItemName`, `.ActualQty`, `.BilledQty`, `.Rate`, `.Amount`, `.IsDeemedPositive`, `.Discount`, `BatchAllocations.GodownName`, `.BatchName`, `.TrackingNumber`, `.ActualQty` → `inventory_lines` item, signed quantity/value, rate, discount, batch/godown and tracking-derived quantities. |
| Inventory accounting allocations | `AllInventoryEntries.AccountingAllocations.LedgerName`, `.Amount`, `.IsDeemedPositive`, plus `.CategoryAllocations.Category`, `.CostCentreAllocations.Name`, `.Amount` → ledger postings and their cost allocations. |
| Stock-journal in/out entries | `StockItemName`, `ActualQty`, `BilledQty`, `Rate`, `Amount`, `IsDeemedPositive`, `BatchAllocations.GodownName`, `BatchName` → `inventory_lines`; direction is determined by the `InventoryEntriesIn` or `InventoryEntriesOut` list. |

For every selected object, any other non-empty returned path not consumed by the mapping is
kept in `extra` using the source path (including any `UDF:` prefix). Tally internal
bookkeeping paths and duplicate inventory-allocation subtrees are omitted from `extra` but
remain in raw XML. Since the recordings were made with these selected fields, they cannot
show fields Tally would return only if explicitly requested. A full export is needed to
answer that question; do not infer missing fields from an empty `extra`.

## 3. Record-count comparison

Run `./dev.ps1 audit counts` against an explicitly selected environment. The command reads
the configured Tally connection and its linked companies, requests source master counts
and monthly voucher counts, and compares them with active canonical records. It prints
counts, company/entity labels, object kinds, months and internal voucher-type ids only;
it does not print company, ledger or voucher-type names, amounts, payloads or credentials.

Master counts cover the company record and each persistent master type. The synthetic
`Primary` group is excluded. Voucher counts cover `books_from` through the current date and
are grouped by calendar month and voucher-type id; unmatched source types are numbered
without exposing their names. A positive difference means fewer active rows are stored.
Soft-deleted vouchers are excluded from the active comparison and counted separately.

The report separately counts cancelled, optional and non-accounting-type vouchers that
are retained but excluded from financial postings, plus soft-deleted vouchers. Some
non-accounting types (for example delivery/receipt notes) can still move stock. These
categories can overlap; they are not added together. Optional, memorandum and reversing
journal vouchers do not count in financial postings; post-dated vouchers count from their
voucher date. This distinction prevents a deliberate accounting exclusion from appearing
as a data-completeness gap.

The command is read-only toward Tally and does not change canonical data. Current fixture
tests replay the synthetic LedgerBridge Test Co recordings through in-memory SQLite.
Collections absent from the manifest are reported as unavailable by the fixture tests,
not as zero. The test recordings cover April–September 2026 only; they do not prove
completeness beyond those months or for other companies.
