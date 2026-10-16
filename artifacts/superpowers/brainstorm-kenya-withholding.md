# Kenya Withholding at Payment — Design

- **Date:** 2026-10-16
- **Status:** Draft, pending builder check and user approval
- **App:** cecypo_powerpack
- **Scope:** (1) withholding calculated on supplier Payment Entries; (2) "Withholding Due to
  KRA" report with Pay KRA and the iTax VAT CSV export; (3) settings.

## Why

Kenyan companies appointed by KRA as VAT withholding agents must withhold, **at the time of
paying** a supplier (not at invoice time):

- **2% Withholding VAT** on the taxable value (excl. VAT) of what is paid, to KRA within
  **5 working days** of the payment (Tax Procedures Act s.42A).
- **Withholding income tax** on some items: **7.5%** on rent charged to us as tenants, **5%**
  on professional services (software implementation, consultancy). Due by the **20th of the
  following month**.

Today this is done in Excel (remittance advice) plus hand-made Journal Entries: one moving the
withheld amount from Creditors to a control account (e.g. `2330 - Rental Withholding Tax
7.5%`), and one paying KRA from the bank with the iTax PRN as reference. The VAT CSV for iTax
is built by hand.

Worked example (remittance advice 05/10/2026, Akshrap Holdings, INV60515):

| Line | Incl | Excl (÷1.16) | 7.5% rent | 2% VAT WHT | To pay |
|---|---|---|---|---|---|
| Rent | 308,792 | 266,200 | 19,965 | 5,324 | 283,503 |
| Other | 6,960 | 6,000 | — | 120 | 6,840 |

### Why not ERPNext's Tax Withholding Category (TDS)

Checked on this bench (ERPNext 16.50):

- On a Payment Entry it only withholds on **unallocated / advance** amounts, never on
  allocated invoice references (`tax_withholding_entry.py:1156`).
- It works from the payment amount (VAT-inclusive), not from specific item lines.
- Its rounding is nearest (`flt(amount, 0)`), not up.
- Setting a category on a Supplier makes every new Purchase Invoice tick Apply Tax
  Withholding (`purchase_invoice.js:713`) — invoice-time withholding, the Indian flow.

So it is not used, and must not be set on suppliers using this feature.

## Goals

1. When paying suppliers by Payment Entry, the withholding is calculated per invoice from
   configurable rules and posted through the Payment Entry's own **Deductions** table, in the
   same document. The bank pays the balance. No Journal Entry to move amounts to control
   accounts.
2. Every withheld amount is recorded per invoice, with what KRA needs, and its KRA status.
3. A report lists what is due to KRA with deadlines; selected lines are paid to KRA in one
   generated Journal Entry and can never be paid twice.
4. The iTax Withholding VAT CSV is exported from the same report.

## Non-goals

- Withholding on Journal Entry payments, Payment Reconciliation, or unallocated / advance
  amounts. Suppliers are paid by Payment Entry against Purchase Invoices.
- The iTax returns for withholding **income tax** (7.5% / 5%) — only the VAT CSV is in scope.
- Splitting VAT-exempt / zero-rated lines out of the 2% base. Every line's excl. value counts,
  as the current spreadsheet does (user did not object to this default).
- Enforcing the KRA deadline. Paying late or monthly stays possible; the report only warns.

## Anti-goals

- A withheld amount that differs from what iTax computes from the CSV. iTax computes
  `ceil(excl × 2%)` per row (verified against the 22/01/2026 upload: 126,316.5776 → 2,527).
  Our amount must match it to the shilling.
- Paying the same withheld line to KRA twice.
- Invoice-time withholding (the TDS flow).

## Settings (PowerPack Settings, new "Withholding" section)

- `enable_kenya_withholding` (Check) — feature gate, as every PowerPack feature.
- **Withholding Rules** (child table): `item` (Link Item, optional), `supplier` (Link
  Supplier, optional), `rate` (Percent), `account` (Link Account, required, non-group).
  - Blank item = any item. Blank supplier = any supplier. Both blank = everything.
  - **All matching rules apply (stacking).** A rent line matches the blank/blank 2% rule and
    the Rent 7.5% rule and gets both.
  - A rule applies only to Payment Entries of the account's company — no company column; the
    account carries it.
  - In the settings form, a row whose item or supplier also appears in another row is
    **highlighted** (warning only; the rent item legitimately appears twice).
- **VAT Withholding Accounts** (Table MultiSelect of Account, one per company). Rules posting
  to these accounts are VAT withholding: exemptions cancel them, the 5-working-day deadline
  applies, and they go in the CSV. Every other rule account is withholding income tax, due the
  20th of the following month. (User rejected a Type column as repetition of the account.)
- **VAT WHT Exemptions** (child table): `supplier`, `certificate_no`, `valid_until` (Date).
  While the Payment Entry's posting date ≤ `valid_until`, rules posting to a VAT withholding
  account are skipped for that supplier. Expired → the 2% resumes automatically.
- All Link fields in these child tables get `"ignore_user_permissions": 1` (see CLAUDE.md:
  Settings child rows are configuration).

## Calculation (Payment Entry, Pay, party type Supplier)

For each reference row of type Purchase Invoice with `allocated_amount > 0`:

```
share    = allocated_amount / invoice total (rounded_total if used, else grand_total)
for each rule matching ≥1 line of the invoice:
    base     = round(sum(matching lines' base_net_amount) × share, 2)
    withheld = ceil(base × rate / 100)      # computed on the 2dp base, as iTax does
```

Two rules to the same account matching one line both apply (highlighted in settings as a
likely mistake).

- `share` handles partial payments, disputes (allocate less than outstanding; the rest stays
  outstanding and its later payment gets its own withholding) and debit notes (they reduce
  outstanding, so the allocated amount — and the base — shrink). Matches the user's rules:
  "2% on any payment issued, also part payments" and "on the net after debit notes".
- **Foreign-currency suppliers** (user: Kenyan suppliers may bill in USD; withholding is
  still in KES). `share` is computed in the invoice's own currency (allocated ÷ invoice
  total, both party currency); the base uses the PI's `base_net_amount`, i.e. KES at the
  **invoice's** exchange rate (builder's call, recorded — the rate the invoice's VAT was
  declared at). Withholding and deduction rows are KES (Payment Entry Deduction amounts are
  company currency). Paid amount = (allocated at the Payment Entry's rate, in KES −
  withholding) converted to the paid-from account's currency; ERPNext's usual exchange
  gain/loss handling is untouched. The CSV amount is the KES base.
- Per-payment rounding up can over-withhold by a shilling across several part payments. That
  is what iTax does per CSV row; accepted.
- Check: INV60515 above, allocated 315,752 → withheld 19,965 (7.5%) + 5,444 (2%), bank pays
  290,343. (One PI: 2% of 272,200 = 5,444; as two PIs, 5,324 + 120 — same total.)

### Where it lands on the Payment Entry

- A new child table **Withholding Details** on Payment Entry (custom Table field, child
  doctype in this app), one row per (invoice, rule): `purchase_invoice`, `bill_no`,
  `bill_date`, `base_amount` (excl. VAT, 2dp), `rate`, `account`, `amount`, `is_vat`,
  `due_date`, `kra_journal_entry` (Link JE, allow on submit, read-only). This is the record
  the report and CSV read — no separate ledger doctype.
- **Deductions** table: one row per account with the sum, description
  "Withholding <rate>%…". **Rows are negative**: for Pay, `set_difference_amount` computes
  `paid − party − deductions` and `add_deductions_gl_entries` always debits the account, so a
  negative amount is what credits the control account and lowers the bank payment. Deduction
  rows on other accounts (round-off, exchange) are left alone. Paid amount is reduced by the
  total so the entry balances.
- **Paid amount is calculated, not typed** (user decision). Today users type the net
  (290,343) from the Excel remittance advice; ERPNext then re-spreads a typed paid amount over
  the references (`allocate_party_amount_against_ref_docs`, server side subtracts deductions,
  `payment_entry.py:1948`), which would fight the calculation. While withholding applies to
  the entry, `paid_amount` / `received_amount` are read-only and set to
  `total allocated − withholding`; the user drives the payment by the per-invoice
  allocated amounts (full outstanding, part, or less a disputed amount).
- Recalculated when references or allocated amounts change (client calls one whitelisted
  server method; the maths lives in Python only) and again server-side while draft, so a
  submitted entry always matches the rules in force at submit. A `validate` doc_event runs
  after Payment Entry's own `set_amounts` / `validate_allocated_amount`, so the hook must
  re-run the amount setters (unallocated, difference) after changing deductions. Disabled
  feature / no rules / not a supplier payment → nothing happens.
- Debit notes (builder's call, recorded): only notes that reduce the invoice's outstanding
  (`return_against` set, `update_outstanding_for_self` off) lower the base, through `share`,
  proportionally across all lines. Standalone / self-outstanding notes (negative reference
  rows) are not netted in v1.

### Due dates

- VAT: posting date + 5 working days. Working days skip Saturdays, Sundays and holidays in the
  company's default Holiday List, if one is set.
- Income tax: the 20th of the month after the posting date.

## Withholding Due to KRA (Script Report)

Filters: company (required), account, status (Unpaid / Paid / All, default Unpaid), date
range. Rows: one per Withholding Details row of submitted Payment Entries — supplier, PIN
(`tax_id`), invoice (bill no + PI link), invoice date, payment entry, payment date, base,
rate, amount, account, due date, KRA journal entry. Overdue unpaid rows are highlighted.
Checkbox column for selection.

- **Pay KRA** (selected unpaid rows): dialog for bank/cash account, posting date, PRN,
  reference date. Creates and submits one Journal Entry, voucher type Bank Entry: debit each
  withholding account with its selected total, credit the bank; `cheque_no` = PRN,
  `cheque_date` = reference date, user remark listing the payment entries. Sets
  `kra_journal_entry` on the selected rows. Rows already linked are refused (the twice-paid
  guard is server-side, not just in the UI).
- **Export iTax CSV** (selected rows, or all shown if none selected; VAT rows only): no header,
  CRLF, columns `PIN, Invoice No, Invoice Date (dd/mm/yyyy), Excl. amount, Payment Date
  (dd/mm/yyyy)`. Invoice No = PI `bill_no` (fallback PI name); Invoice Date = `bill_date`
  (fallback posting date); Payment Date = Payment Entry posting date. Amount = the stored
  `base_amount`, so iTax's `ceil(× 2%)` equals what we withheld. A row with no supplier PIN
  blocks the export with the supplier named.
- **iTax rejects repeated rows** (user confirmed). Rows with the same (PIN, invoice no) in one
  export are merged: amounts summed, payment date = the latest. Two part payments of one
  invoice in one batch can then differ from iTax's figure by ≤1 shilling (sum of ceils vs
  ceil of sum).
- **Pay KRA posts what iTax computes** (builder's call, recorded): the bank credit uses the
  merged-row `ceil` figures, so it equals the PRN; the selected rows' withheld totals clear
  the control accounts in full, and any shilling difference goes to the company's round-off
  account in the same Journal Entry.
- The same invoice number in *different* returns is accepted by iTax (user confirmed), so
  merging is only needed within one export.

## Integrity

- Cancelling a Payment Entry whose withholding rows are paid to KRA is refused (names the
  Journal Entry). Unpaid → cancels normally.
- Cancelling a KRA Journal Entry clears `kra_journal_entry` on its rows (they return to
  Unpaid). Frappe's linked-doc check would otherwise refuse the cancel (submitted Payment
  Entry child rows link to the JE), so Payment Entry goes in the JE's
  `ignore_linked_doctypes` for that cancel.

## Verification

- Python unit tests on the calculation: INV60515 example; the 22/01/2026 CSV rows
  (`ceil` matches iTax); part payment; dispute (allocate less); debit note; stacking 2% +
  7.5%; USD invoice paid from a KES bank; exemption valid / expired on the boundary date; blank-blank vs item vs supplier match;
  feature off.
- Integration tests: submit a Payment Entry → deductions, paid amount and GL correct; Pay KRA
  → JE balanced, rows linked, second pay refused; cancel paths above; CSV bytes exact.
- Browser check on dev: settings highlight, Payment Entry fill, report pay + export.

## Deploy

`bench migrate` (new child doctypes, custom fields, report), `bench build --app
cecypo_powerpack` (Payment Entry and settings JS in the bundle).
