# TallyPrime data-completeness audit

| Field | Value |
| --- | --- |
| Date | 2026-11-06 |
| Evidence | One full export of LedgerBridge Test Co (synthetic test data), recorded by `python -m devtools.tally_full_export` into `data-plane/tests/fixtures/tally/full-export/` |
| Every field, generated | [data-completeness-fields.md](data-completeness-fields.md) (`python -m devtools.tally_field_inventory`; a test fails when it is stale) |

This audit says, for every object type and every field TallyPrime exports, whether we store it
as a column, keep it in `extra`, or never fetch it; what it means; and what we recommend. It
proposes; it changes nothing (no behaviour changed with it).

## 0. How it was found, and what it can't show

**The export asks for everything, not for our field list.**

| File | What Tally was asked for | Objects |
| --- | --- | --- |
| `masters.xml` | Tally's own export of every master ("List of Accounts" with all masters): every field of every master of every type, empty ones included | 13 types, 231 masters |
| `company.xml` | The company object whole (Company collection, `NATIVEMETHOD *`) | 1 |
| `daybook.xml` | Tally's own Day Book export, whole vouchers with every sub-list | 5 |
| `vouchers.xml.gz` | Every voucher of every type (Voucher collection, books-from 1-Apr-2025 to 31-Mar-2027): `NATIVEMETHOD *` for the voucher's own fields and `<list>.*` for each of 174 sub-lists at every level | 79 |

Why vouchers come from a collection: Tally's Day Book export ignores the period asked for and
exports its current date only (2-Oct-2026: 5 vouchers), and Educational mode allows only the
1st, 2nd and 31st as dates. `NATIVEMETHOD *` alone leaves the sub-lists out (2026-11-05), so
the recorder fetches each sub-list by name. It finds them in rounds: first the Day Book's and
the connector's, then any nested list an answer shows; the second round found none new.

**The export is complete for the test company's vouchers:** for the 5 vouchers in both
files, every field the Day Book fills with a real value is also in `vouchers.xml`
(`python -m devtools.tally_field_inventory --check`: 0 problems). The only fields the Day
Book has in addition are values nobody set (`No`, `0`, "Not Applicable": e.g. cash
denomination counts and temporary GST rates); Tally writes those in its own export and
leaves them out of a collection.

**Not asked: one collection per master type.** Asked for a type name it didn't know,
TallyPrime stopped answering until someone attended to it (2026-11-06); the full masters
export covers every type the company has instead.

**What it can't show:**

- Fields of types the test company doesn't have (stock categories, budgets, price levels,
  payroll and so on, Section 1): Tally exports them only when they exist. Their meaning here
  is Tally's documentation and the field names, not observation.
- User-defined fields (UDFs, `UDF:` prefix): the test company has none. The connector keeps
  any it is sent in `extra`, but it only receives those under fields it fetches.
- What other companies fill. A field "set in 0 of 79" here may be filled by a client.

**How to read the field tables (Section 2).**

- *Status:* **column**: the mapping reads it (`mapping.USED_FIELDS`), stored as a column or
  used to derive one. **extra**: fetched but not read; kept in the object's `extra` JSON when
  it has a value. **raw only**: an attribute Tally sends without being asked; it stays in the
  raw record. **not fetched**: never asked for; not in the raw records either.
- *Set in:* how many of the type's objects in the test company give it a value other than
  empty, `No`, `0` or "Not Applicable" (Tally's values for "nobody set this").
- *Meaning:* plain words; **(from the name)** marks a meaning taken from the field's name
  and Tally's documentation, not confirmed on data.
- Identity fields every type has are described once: `GUID` (the object's permanent key:
  our `source_key`), `ALTERID` (Tally's change counter: incremental sync), `MASTERID` (an
  internal number; not part of the exported object, Tally works it out on request), `NAME`
  (an attribute in Tally's own export, an element in a collection), `LANGUAGENAME.LIST`
  (aliases), `UPDATEDDATETIME` (when it was last changed), `ASORIGINAL`,
  `OBJECTUPDATEACTION`, `TYPEOFUPDATEACTIVITY`, `OLDAUDITENTRYIDS.LIST`, `SORTPOSITION` and
  `ERRKEY` (Tally's own bookkeeping), `ENTEREDBY`/`ALTEREDBY` (the Tally user who made or
  changed it: empty here; a person's user name).

## 1. Object types

The list is Tally's own (the object types it counts in its answers, `CMPINFO`), plus the
objects that live inside others. "In the test company" is the count in the full export.

### Critical for accounting figures

| Tally type | In the test company | Fetched? | Meaning | Recommendation |
| --- | --- | --- | --- | --- |
| Company | 1 | Yes (`company`) | The books: name, books-from, financial-year start, features on or off | Keep; see Section 2.1 for flags worth storing |
| Group | 31 | Yes (`group`) | The chart of accounts' groups and their nature | Keep |
| Ledger | 46 | Yes (`ledger`, parties) | Accounts, with openings, party, tax and bank details | Keep |
| Voucher (all types) | 79 | Yes (`voucher`) | Every transaction, with its ledger, inventory, bill, cost-centre and bank lines | Keep; fetch the few fields in Section 4 |
| Voucher Type | 25 | Yes (`voucher_type`) | What kind of voucher (Sales, Payment, Stock Journal...) and whether it posts | Keep |
| Currency | 4 | Yes, whole (`currency`) | Currencies and their rates | Keep |
| Stock Item, Stock Group, Unit, Godown | 7, 2, 1, 3 | Yes | Inventory masters, openings, locations | Keep; fetch godown/batch openings (Section 4) |
| Batch (inside Stock Item and voucher lines) | 3 items with batch openings | Openings: **no**; voucher lines: yes | Stock by batch and godown | Fetch the batch openings (Section 4) |

### Useful for analysis

| Tally type | In the test company | Fetched? | Meaning | Recommendation |
| --- | --- | --- | --- | --- |
| Cost Category, Cost Centre | 2, 4 | Yes | Tracking by branch, project, department | Keep |
| Tax Unit | 2 | **No** | The company's tax registrations (GST registration and the default unit); a company can have several GSTINs | Fetch when GST analysis by registration is needed (each voucher names its registration, `GSTREGISTRATION`) |
| Voucher Number Series (inside Voucher Type) | 25 types, all "Default" | **No** | Numbering series of a voucher type (e.g. one per branch) | Fetch with voucher types when a client uses several series |
| Voucher Class (inside Voucher Type) | none | **No** | Preset entry templates of a voucher type | Not needed for figures; the vouchers carry the result |
| Budget (with scenarios) | none | **No** | Tally's own budgets and scenario (provisional) entries | Fetch when budgets (M7b) are built, if clients keep budgets in Tally |
| Price Level (company list; prices inside Stock Item) | none | **No** | Price lists by customer class | Fetch only for pricing analysis |
| Stock Category | none | **No** | A second classification of items, beside stock groups | Fetch when a client uses it (item `CATEGORY`) |
| GST Classification, Tax Classification | none | **No** | Reusable tax-rate settings for items and ledgers | Fetch with GST analysis |
| TDS rate / nature of payment, Deductee Type | none | **No** | TDS settings | Fetch with TDS analysis |
| Serial Number | none | **No** | Serial-number tracking of items | Fetch only if a client tracks serials |

### Not needed for accounting analytics

| Tally type | In the test company | Fetched? | Meaning | Recommendation |
| --- | --- | --- | --- | --- |
| Income Tax Classification, Income Tax Slab | 94, 10 | No | Tally's predefined income-tax tables for payroll | Not needed |
| Attendance Type; employees and employee groups (cost centres for payroll); pay heads (ledgers for payroll) | none | No | Payroll | Not needed; payroll is a separate scope. Payroll ledgers and vouchers are already fetched as ledgers and vouchers. |
| ST Category, FBT Category, FBT Assessee Type, Tariff Classification, Excise Duty Classification, LBT Classification, Adjustment Classification, Return Master | none | No | Tax regimes that predate GST, other countries' taxes, return filing | Not needed |
| State, Client Rule, Server Rule | none | No | Tally's lists and synchronisation rules | Not needed |
| BOM (inside Stock Item) | none | No | Bills of materials for manufacturing | Not needed for figures (manufacturing vouchers carry the result); fetch only for costing analysis |

## 2. Fields per object type

Every field is listed in [data-completeness-fields.md](data-completeness-fields.md). Below:
every field the test company sets, every field that can change figures, and the empty ones
by family.

### 2.1 Company (414 fields, 40 set)

**Critical for accounting figures**

| Field | Status | Meaning | Recommendation |
| --- | --- | --- | --- |
| `NAME`, `BASICCOMPANYFORMALNAME` | column | Name and legal name | Keep |
| `BOOKSFROM`, `STARTINGFROM` | column | Books start; financial-year start | Keep |
| `ENDINGAT`, `CURRENCYNAME` | extra | Year end; base currency. Not part of the exported object (Tally works them out on request) | Keep in extra |
| `ISINVENTORYON`, `ISACCOUNTINGON`, `ISINTEGRATED` | not fetched / extra | Inventory kept; accounts with inventory; inventory values integrated in the accounts | Store `ISINTEGRATED` (decides whether closing stock comes from the books); the others in extra |
| `ISBILLWISEON` | not fetched | Bill-by-bill tracking on | Keep in extra (each ledger has its own flag) |

**Useful for analysis**

| Field | Status | Meaning | Recommendation |
| --- | --- | --- | --- |
| `STATENAME`, `COUNTRYNAME`, `GSTREGISTRATIONNUMBER`, `INCOMETAXNUMBER` | column / extra | State, country, GSTIN, PAN | Keep |
| `ISCOSTCENTRESON`, `ISGSTON`, `ISJOBWORKON`, `ISEDITLOGON`, `ISFIFOAPPLIED`, `FIFOAPPLICABLEFROM` | extra / not fetched | Features on or off (cost centres, GST, job work, Edit Log, FIFO stock valuation and from when) | Keep in extra; `ISFIFOAPPLIED` explains stock values |
| `AUDITEDUPTO` | not fetched | Books audited up to this date (from the name) | Keep in extra: a useful "closed period" marker |

**Not needed:** company number, connection and download settings (`COMPANYNUMBER`,
`CONNECTNAME`, `CMPVCHSTATID`, `SEARCHMAXTERMLIMIT`, `ISGSTR*DOWNLOADEXCLUDED`,
`ISBANKINGVCHMIGRATED`, `SHOWBANKDETAILS`, `ISCHQPRINTINGON`, `ISTRANSFERMODEON`), e-way
bill thresholds, VAT/CST/FBT/service-tax settings, address, contact and bank-details lists
(empty here), and Tally's own bookkeeping.

### 2.2 Group (140 fields, 22 set)

| Field | Status | Set in | Meaning | Recommendation | Importance |
| --- | --- | --- | --- | --- | --- |
| `PARENT` | column | 16 of 31 | The group above | Keep | Critical |
| `RESERVEDNAME` | column (attribute) | 28 of 31 | Tally's built-in name of a predefined group (Sales Accounts...), even when renamed | Keep (our `predefined_role`) | Critical |
| `ISDEEMEDPOSITIVE`, `ISREVENUE`, `AFFECTSGROSSPROFIT` | column | 13, 6, 4 of 31 | Debit nature; P&L group; in gross profit | Keep | Critical |
| `ISSUBLEDGER` | not fetched | 3 of 31 | Behaves like a sub-ledger: its ledgers are shown as one in reports (from the name) | Keep in extra | Useful |
| `SORTPOSITION` | not fetched | 31 of 31 | Order of the group in Tally's reports | Store as a column: statements in Tally's order | Useful |
| `ISBILLWISEON`, `ISCOSTCENTRESON`, `AFFECTSSTOCK`, `ISADDABLE`, `TRACKNEGATIVEBALANCES` | not fetched | 1 to 6 of 31 | Defaults for its ledgers; "addable" (calculation) group; warn on negative balances | Not needed (each ledger has its own) | Not needed |

Empty families: GST, TDS, excise and VAT defaults for its ledgers, and bookkeeping: not needed.

### 2.3 Ledger (578 fields, 34 set)

**Critical for accounting figures**

| Field | Status | Set in | Meaning | Recommendation |
| --- | --- | --- | --- | --- |
| `PARENT` | column | 45 of 46 | Its group | Keep |
| `OPENINGBALANCE` | column | 10 of 46 | Opening at the books' start (foreign currency as `-$1000.00 @ ₹80/$ = -₹80000.00`) | Keep |
| `CURRENCYNAME` | column | 3 of 46 | The ledger's own currency | Keep |
| `RESERVEDNAME` | raw only | 1 of 46 | Built-in name (e.g. the Profit & Loss A/c) | Keep in the raw record; read already when listing names |
| `ISBILLWISEON`, `ISCOSTCENTRESON` | column | 8, 11 of 46 | Bill-by-bill and cost-centre tracking on | Keep |
| `AFFECTSSTOCK` | not fetched | 5 of 46 | Its entries change stock value (purchase/sales ledgers in an integrated company: "inventory values are affected") | Store as a column: explains where stock value moves |

**Useful for analysis**

| Field | Status | Set in | Meaning | Recommendation |
| --- | --- | --- | --- | --- |
| `TAXTYPE`, `GSTDUTYHEAD` | column | 46, 2 of 46 | Kind of tax ledger (GST, TDS, Others); GST head (CGST, SGST, IGST, Cess) | Keep |
| `PARTYGSTIN`, `LEDGSTREGDETAILS.LIST/GSTIN`, `INCOMETAXNUMBER`, `LEDSTATENAME`, `COUNTRYNAME`, `EMAIL`, `LEDGERPHONE`, `LEDGERMOBILE`, `BILLCREDITPERIOD`, `CREDITLIMIT` | column | 0 of 46 (synthetic parties have none) | Party's GSTIN, PAN, state, country, contact, credit days and limit. `LEDSTATENAME` and `COUNTRYNAME` aren't in the exported object; Tally works them out on request | Keep |
| `COUNTRYOFRESIDENCE`, `LEDMAILINGDETAILS.LIST/COUNTRY`, `/MAILINGNAME`, `/APPLICABLEFROM` | not fetched | 1 of 46 | The stored country and mailing name, with the date they apply from | Keep fetching `COUNTRYNAME` (it reads these); not needed separately |
| `LEDGSTREGDETAILS.LIST/GSTREGISTRATIONTYPE`, `/APPLICABLEFROM`; `GSTNATUREOFSUPPLY`, `LEDGSTREGDETAILS.LIST/PLACEOFSUPPLY` | not fetched | 1 of 46; 0 | Party's GST registration type (Regular, Composition, Unregistered...), place of supply | Keep in extra with GST analysis |
| `LEDMAILINGDETAILS.LIST/PINCODE`, `/CITY` (the address lines sit in an address list there, empty here), `CONTACTDETAILS.LIST` | not fetched | 0 of 46 (1 contact name) | Postal address, PIN code, contact persons | Keep PIN code/city in extra for regional analysis; not the full address |
| `SORTPOSITION` | not fetched | 46 of 46 | Order in Tally's reports | Store with the group's |
| `MSMEREGISTRATIONDETAILS.LIST`, `ISRELATEDPARTY` | not fetched | 0 | Supplier's MSME (Udyam) registration (45-day payment rule); related party | Keep in extra when a client needs MSME payables |
| `INTERESTCOLLECTION.LIST`, `ISINTERESTON` | not fetched | 0 | Interest calculation on the ledger | Not needed |

**Not needed:** bank details (`BANKDETAILS`, `IFSCODE`, account holder, MICR, SWIFT, e-banking
and cheque-printing settings: sensitive and not used for figures; **don't store**),
`ISCHEQUEPRINTINGENABLED` (44 of 46), TDS/TCS/excise/VAT/service-tax/FBT/UAE/Philippines
settings, payroll settings (`FORPAYROLL`, gratuity, pay types), `VATDEALERTYPE`,
`LEDGERCOUNTRYISDCODE`, bookkeeping.

### 2.4 Voucher type (148 fields, 37 set)

| Field | Status | Set in | Meaning | Recommendation | Importance |
| --- | --- | --- | --- | --- | --- |
| `PARENT`, `RESERVEDNAME` | column | 25, 24 of 25 | The type it was made from; Tally's built-in type: together our base type | Keep | Critical |
| `AFFECTSSTOCK` | column | 8 of 25 | Moves stock | Keep | Critical |
| `ISDEEMEDPOSITIVE` | not fetched | 17 of 25 | The type's default side (from the name) | Not needed (each line has its own) | Not needed |
| `ISACTIVE` | not fetched | 15 of 25 | Shown in Tally's voucher menu | Keep in extra | Useful |
| `VOUCHERNUMBERSERIES.LIST/NAME`, `/NUMBERINGMETHOD`, `/BEGINNINGNUMBER`, `/RESTARTFROMLIST.LIST/*`; `NUMBERINGMETHOD`, `BEGINNINGNUMBER`, `SHOWDELETEDVCHNUM` | not fetched | 25 of 25 | How vouchers are numbered (automatic, manual), restarts, series | Keep in extra; useful to explain gaps and duplicates in numbers | Useful |
| `MAILINGNAME`, `TAXUNITNAME`, `LASTGSTTAXUNIT*`, `LASTSERIESBYGSTTAXUNIT*`, `LASTVCHNUMSERIES`, `PREVNARRATION`, `COMMONNARRATION`, `EXCISEUNITNAME`, `VCHNUMSERIESID.LIST` | not fetched | 18 to 25 of 25 | Print name, the GST registration last used, the narration last typed | Not needed | Not needed |

Empty families: voucher classes (`VOUCHERCLASSLIST`), print settings, default
bank and accounting allocations: not needed.

### 2.5 Currency (32 fields, 13 set; fetched whole)

Everything is fetched. `NAME`, `ORIGINALNAME`, `EXPANDEDSYMBOL`, `ISOCURRENCYCODE`,
`MAILINGNAME`, `DECIMALPLACES` and the rate lists (`DAILYSTDRATES.LIST`,
`DAILYBUYINGRATES.LIST`, `DAILYSELLINGRATES.LIST`, empty here) are columns or rates; the
display settings (`DECIMALSYMBOL`, `HASSPACE`, `DECIMALPLACESFORPRINTING`) are in extra.
Recommendation: keep as is.

### 2.6 Stock item (228 fields, 23 set)

**Critical for accounting figures**

| Field | Status | Set in | Meaning | Recommendation |
| --- | --- | --- | --- | --- |
| `PARENT`, `BASEUNITS` | column | 1, 7 of 7 | Stock group; unit | Keep |
| `OPENINGBALANCE`, `OPENINGVALUE` | column | 3 of 7 | Opening quantity and value in total | Keep |
| `OPENINGRATE` | extra | 3 of 7 | Opening rate | Keep in extra (value ÷ quantity) |
| `BATCHALLOCATIONS.LIST/GODOWNNAME`, `/BATCHNAME`, `/OPENINGBALANCE`, `/OPENINGVALUE`, `/OPENINGRATE` | **not fetched** | 3 of 7 | The opening split by godown and batch | **Store** (new rows, by item, godown and batch): stock by godown and batch can't start from the right opening without it. Totals are unaffected. |

**Useful for analysis**

| Field | Status | Set in | Meaning | Recommendation |
| --- | --- | --- | --- | --- |
| `ADDITIONALUNITS`, `DENOMINATOR`, `CONVERSION` | not fetched | `DENOMINATOR` 7 of 7; no second unit here | A second unit and its conversion (e.g. box of 12) | Keep in extra |
| `CATEGORY` | not fetched | 0 | Stock category | Fetch with stock categories |
| `GSTDETAILS.LIST` (rates), `HSNDETAILS.LIST` (HSN code) | not fetched | 0 | Item's GST classification and HSN | Keep in extra with GST analysis (vouchers carry the rate used) |
| `MRPDETAILS.LIST`, `STANDARDCOSTLIST.LIST`, `STANDARDPRICELIST.LIST`, `FULLPRICELIST.LIST`, `PRICELEVELLIST.LIST`, `REORDERBASE`, `MINIMUMORDERBASE` | not fetched | 0 | MRP, standard cost and selling price, price levels, reorder level and minimum order | Fetch only for pricing or reorder analysis |
| `MULTICOMPONENTLIST.LIST` | not fetched | 0 | Bill of materials | Not needed for figures |

**Not needed:** excise, VAT and service-tax classifications, batch and expiry settings,
costing method flags, bookkeeping.

### 2.7 Stock group, unit, godown, cost category, cost centre

| Type | Field | Status | Set in | Meaning | Recommendation |
| --- | --- | --- | --- | --- | --- |
| Stock group | `PARENT` | column | 0 of 2 | The group above | Keep |
| Stock group | `BASEUNITS`, `ADDITIONALUNITS` | not fetched | 1 of 2 | Unit to add up quantities in ("addable" groups) | Not needed |
| Unit | `ORIGINALNAME`, `DECIMALPLACES` | column | 1 of 1 | Unit's formal name; decimals | Keep |
| Unit | `ISSIMPLEUNIT`, compound-unit fields | extra / not fetched | 1 of 1 | Simple or compound unit (box of 12 pcs) | Keep in extra |
| Godown | `PARENT`, `ISEXTERNAL`, `ISINTERNAL` | column | 0, 1, 1 of 3 | Location above; third party's stock with us; ours with a third party (our `holding`) | Keep |
| Cost category | `ALLOCATEREVENUE`, `ALLOCATENONREVENUE` | extra | 2, 1 of 2 | Used for revenue items; for non-revenue (balance sheet) items | Keep in extra |
| Cost centre | `PARENT`, `CATEGORY` | column | 1, 4 of 4 | Centre above; its category | Keep |
| Cost centre | payroll fields (`FORPAYROLL`, bank details, employee data) | not fetched | 0 | Employees are cost centres in Tally's payroll | **Don't fetch** (personal data, out of scope) |

### 2.8 Voucher (2,246 fields, 180 set)

**The voucher itself: critical for accounting figures**

| Field | Status | Set in | Meaning | Recommendation |
| --- | --- | --- | --- | --- |
| `DATE`, `EFFECTIVEDATE` | column | 79 of 79 | Voucher date (balances count by it); effective date | Keep |
| `VOUCHERTYPENAME`, `VOUCHERNUMBER`, `PARTYLEDGERNAME`, `NARRATION` | column | 79, 79, 67, 79 of 79 | Type, number, party, narration | Keep |
| `REFERENCE`, `REFERENCEDATE` | column | 2, 0 of 79 | The party's document number (e.g. supplier invoice) and its date | Keep |
| `ISCANCELLED`, `ISOPTIONAL`, `ISPOSTDATED` | column | 1, 3, 1 of 79 | Excluded from the books / memo / dated ahead | Keep |
| `ISDELETED` | extra | 0 | Deleted (when Tally sends it) | Keep |
| `ACTIVETO` | not fetched | 2 of 79 (Reversing Journals) | The date a reversing journal applies until | Keep in extra; reversing journals already stay out of the books |
| `ISINVOICE` | extra | 21 of 79 | Entered in invoice mode | Keep in extra |
| `VCHTYPE`, `VCHKEY`, `OBJVIEW`, `REMOTEID` | raw only | 79 of 79 | Attributes: type, Tally's internal key, entry screen, remote id | Not needed |

**The voucher itself: useful for analysis**

| Field | Status | Set in | Meaning | Recommendation |
| --- | --- | --- | --- | --- |
| `HASCASHFLOW` | not fetched | 24 of 79 | The voucher moves cash or bank | Keep in extra; a check for the cash movement |
| `VOUCHERNUMBERSERIES` | not fetched | 79 of 79 ("Default") | The numbering series used | Store with series (clients with several series have duplicate numbers across series) |
| `GSTREGISTRATION`, `CMPGSTREGISTRATIONTYPE` | not fetched | 79, 68 of 79 | Which of the company's GST registrations the voucher belongs to; its type | Store when GST analysis by registration is built |
| `VOUCHERTYPEORIGNAME`, `VCHSTATUSVOUCHERTYPE` | not fetched | 78, 79 of 79 | The voucher type's name when entered; Tally's status copy of it (from the name) | Not needed |
| `VCHSTATUSISCANCELLED`, `VCHSTATUSISOPTIONAL`, `VCHSTATUSDATE`, `VCHSTATUSTAXUNIT`, `VCHSTATUSTAXADJUSTMENT`, `VCHGSTSTATUS*` | not fetched | 1 to 79 of 79 | Tally's status copies of flags we already have, and GST return status | Not needed |
| `ISDEEMEDPOSITIVE`, `ISELIGIBLEFORITC`, `ISVATDUTYPAID`, `NUMBERINGSTYLE`, `PERSISTEDVIEW`, `VOUCHERKEY`, `VOUCHERRETAINKEY`, `IRNACKUPDATEDATETIME`, `UAEEINVUPLOADDATETIME`, `CSTFORM*`, `FBTPAYMENTTYPE`, `OLDAUDITENTRYIDS.LIST`, `PFTDLVERSIONINFO.LIST` | not fetched | 53 to 79 of 79 | Defaults and Tally's bookkeeping (e.g. "Auto Retain" numbering, the entry screen) | Not needed |

**Ledger entries (`ALLLEDGERENTRIES.LIST`; `LEDGERENTRIES.LIST` in invoices)**

| Field | Status | Set in | Meaning | Recommendation | Importance |
| --- | --- | --- | --- | --- | --- |
| `LEDGERNAME`, `AMOUNT`, `ISDEEMEDPOSITIVE`, `ISPARTYLEDGER` | column | 69 of 79 | Ledger, signed amount, side, the party's line | Keep | Critical |
| `RATEDETAILS.LIST/GSTRATEDUTYHEAD` and rates; `GSTCLASS`; `GSTOVRDN*`; `GSTHSNINFERAPPLICABILITY`, `GSTRATEINFERAPPLICABILITY` | not fetched | 9 to 69 of 79 | GST rate per head on the line, overrides and where the rate came from | Keep in extra with GST analysis | Useful |
| `INVENTORYALLOCATIONS.LIST/*` | not fetched | 26 of 79 | The item lines repeated under the ledger entry | Not needed (the same as `ALLINVENTORYENTRIES`) | Not needed |
| `ISLASTDEEMEDPOSITIVE`, `OLDAUDITENTRYIDS.LIST` | not fetched | 69 of 79 | Bookkeeping | Not needed | Not needed |

**Bill allocations (`…/BILLALLOCATIONS.LIST`)**

| Field | Status | Set in | Meaning | Recommendation | Importance |
| --- | --- | --- | --- | --- | --- |
| `NAME`, `BILLTYPE`, `AMOUNT` | column | 40 of 79 | Bill reference, New Ref / Agst Ref / Advance / On Account, amount | Keep | Critical |
| `BILLDATE` | **not fetched** | 35 of 79 | The bill's date | **Store** (`bill_allocations.bill_date`, a column we already have): ageing from the vouchers without asking Tally's bills report | Critical |
| `BILLCREDITPERIOD` | **not fetched** | 0 (exported, empty here) | Credit period or due date of a new bill | **Store** (`bill_allocations.due_date`): overdue and ageing by due date | Critical |
| `BILLCREATIONDATE`, `BILLID` | not fetched | 35 of 79 | When the bill was created; internal id | Not needed | Not needed |

**Cost-centre allocations (`…/CATEGORYALLOCATIONS.LIST`, also under an item's accounting allocations)**

| Field | Status | Set in | Meaning | Recommendation |
| --- | --- | --- | --- | --- |
| `CATEGORY`, `COSTCENTREALLOCATIONS.LIST/NAME`, `/AMOUNT` | column | 3 of 79 | Category, cost centre, amount | Keep (critical for cost-centre figures) |
| `ISDEEMEDPOSITIVE` | not fetched | 3 of 79 | The side (the line's) | Not needed: the amount takes the line's sign |

**Bank allocations (`…/BANKALLOCATIONS.LIST`)**

| Field | Status | Set in | Meaning | Recommendation | Importance |
| --- | --- | --- | --- | --- | --- |
| `INSTRUMENTNUMBER`, `UNIQUEREFERENCENUMBER` | column | 3, 1 of 79 | Cheque or transfer number; UTR | Keep | Useful |
| `NAME`, `DATE`, `TRANSACTIONTYPE`, `INSTRUMENTDATE`, `AMOUNT` | extra | 3 of 79 | Bank details' key, date, Cheque / e-Fund Transfer..., instrument date, amount | Keep in extra | Useful |
| `BANKERSDATE` | **not fetched** | 0 (exported, empty here) | The date the bank cleared it (bank reconciliation) | **Store** with bank reconciliation (CON-005): cleared and uncleared items | Useful |
| `BANKRECONSTATUS`, `PAYMENTMODE` | not fetched | 3 of 79 | Reconciliation status ("Available Only in Books"); "Transacted" | Keep in extra with bank reconciliation | Useful |
| `BANKPARTYNAME`, `PAYMENTFAVOURING`, account and IFSC fields | not fetched | 0 | Payee and beneficiary bank details | **Don't store** (personal, not needed for figures) | Not needed |

**Inventory entries (`ALLINVENTORYENTRIES.LIST`, `INVENTORYENTRIESIN.LIST`, `INVENTORYENTRIESOUT.LIST`)**

| Field | Status | Set in | Meaning | Recommendation | Importance |
| --- | --- | --- | --- | --- | --- |
| `STOCKITEMNAME`, `ACTUALQTY`, `BILLEDQTY`, `RATE`, `AMOUNT`, `ISDEEMEDPOSITIVE`, `DISCOUNT` | column | 35 of 79 (stock journal in/out: 1, 2) | Item, quantities, rate, value, direction, discount | Keep | Critical |
| `BATCHALLOCATIONS.LIST/GODOWNNAME`, `/BATCHNAME`, `/TRACKINGNUMBER`, `/ACTUALQTY` | column | 35 of 79 | Godown, batch, the delivery/receipt note it's tracked to, quantity | Keep | Critical |
| `BATCHALLOCATIONS.LIST/DESTINATIONGODOWNNAME`; the voucher's `DESTINATIONGODOWN` | **not fetched** | 2 of 79 (Material Out/In); 1 (Stock Journal) | Where the goods went: the job worker's godown, the transfer's destination | **Store** (`inventory_lines`): stock by godown and job-work stock need it; company totals are already validated without it | Critical (for stock by godown) |
| `BATCHALLOCATIONS.LIST/AMOUNT`, `/BILLEDQTY`, `/BATCHRATE` | not fetched | 35 of 79 | Value and quantity per batch line | Keep in extra (the entry's total is stored) | Useful |
| `BATCHALLOCATIONS.LIST/ORDERNO`, `/INDENTNO`; `INVOICEORDERLIST.LIST`, `BASICORDERREF` | not fetched | 0 | The sales/purchase order a line fulfils | Fetch when order analysis (pending orders) is built | Useful |
| `ACCOUNTINGALLOCATIONS.LIST/LEDGERNAME`, `/AMOUNT`, `/ISDEEMEDPOSITIVE` | column | 26 of 79 | The ledger an item line posts to | Keep | Critical |
| `RATEDETAILS.LIST/GSTRATEDUTYHEAD`, `GSTOVRDN*`, `*INFERAPPLICABILITY` | not fetched | 21 of 79 | GST rate per head of the item line and where it came from | Keep in extra with GST analysis | Useful |
| `BATCHID`, `TRACKID`, `ISLASTDEEMEDPOSITIVE`, `OLDAUDITENTRYIDS.LIST` | not fetched | 14 to 35 of 79 | Internal ids, bookkeeping | Not needed | Not needed |

**Empty in the test company, by family** (all **not fetched**; every field is in the generated list):

| Family | Examples | Meaning | Recommendation |
| --- | --- | --- | --- |
| E-invoice and e-way bill | `IRN`, `IRNACKNO`, `IRNACKDATE`, `EWAYBILLDETAILS.LIST`, `TEMPGSTEWAY*` | GST e-invoice registration number and e-way bill | Keep `IRN` and its date in extra if clients ask for e-invoice reconciliation; otherwise not needed |
| Buyer, consignee and dispatch | `BASICBUYERNAME`, `CONSIGNEE*`, `DISPATCH*`, `GSTBUYERADDRESS.LIST`, `PLACEOFSUPPLY` | Who received the goods and where from | Keep state and place of supply in extra (GST); not addresses |
| Orders, delivery notes, shipping | `INVOICEORDERLIST.LIST`, `INVOICEDELNOTES.LIST`, `BASICSHIPDOCUMENTNO`, `BILLOFLADING*`, `LORRYRECPT*` | Linked orders and notes, transport documents | Orders: with order analysis; the rest not needed |
| Foreign currency | in `AMOUNT` (`@` rate) | Rate and foreign amount on each line | Already read from `AMOUNT` |
| TDS, TCS and other taxes | `TDS*`, `TCS*`, `TAXOBJECTALLOCATIONS.LIST`, `DUTYHEADDETAILS.LIST`, VAT, excise, service tax, UAE VAT | Tax details per line | Not needed for figures (tax ledgers carry the amounts); TDS with TDS analysis |
| Payroll and attendance | `ATTENDANCEENTRIES.LIST`, `ATTDRECORDS.LIST`, `PAYROLLMODEOFPAYMENT.LIST` | Payroll vouchers' employee lines | **Don't fetch** (personal data; payroll out of scope) |
| Audit and users | `ENTEREDBY`, `ALTEREDBY`, `AUDITED`, `AUDITEDON`, `AUDITENTRIES.LIST` | Who entered or changed it, audit marks | Not needed; user names are personal data |
| User-defined fields | `UDF:*` | A client's own fields | Already kept in `extra` when sent under a fetched list; promote with `./dev.ps1 promote-field` |

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

## 4. Recommended follow-ups (proposals only)

In order of importance. Each needs a fetch change, so stored records need a re-fetch.

1. **Bill dates and due dates** on voucher bill allocations (`BILLDATE`, `BILLCREDITPERIOD`
   into the existing `bill_allocations.bill_date`, `due_date`): ageing and overdue from the
   vouchers.
2. **Where goods went** (`BATCHALLOCATIONS.DESTINATIONGODOWNNAME`, the voucher's
   `DESTINATIONGODOWN`) and **openings by godown and batch** (stock item
   `BATCHALLOCATIONS.LIST`): stock by godown, batch and job worker.
3. **`AFFECTSSTOCK` on ledgers** and **`ISINTEGRATED` as a company column**: explain how
   stock value enters the accounts.
4. **Report order** (`SORTPOSITION` of groups and ledgers): statements in Tally's order.
5. **Bank reconciliation** (`BANKERSDATE`, `BANKRECONSTATUS`) with CON-005.
6. **GST analysis** (voucher `GSTREGISTRATION`, line `RATEDETAILS`, party registration type
   and place of supply, Tax Units).
7. **Numbering series** (`VOUCHERNUMBERSERIES`, voucher type series).
8. **Don't fetch**: bank account details, payroll and employee data, user names.
