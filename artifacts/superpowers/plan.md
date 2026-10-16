# Kenya Withholding at Payment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Withhold Kenyan 2% VAT / 7.5% rent / 5% professional tax on supplier Payment Entries, track what is due to KRA, pay it in one generated Journal Entry, and export the iTax Withholding VAT CSV.

**Architecture:** Pure calculation functions in one new module `cecypo_powerpack/kenya_withholding.py` (no DB), wrapped by a Payment Entry `before_validate` hook that fills a new per-invoice child table and the PE's own Deductions table. A Script Report reads those child rows for the KRA due list, Pay KRA and the CSV. Configuration lives in PowerPack Settings.

**Tech Stack:** Frappe v16 / ERPNext 16.50, Python (`decimal`, `csv`), desk JS (doctype_js, Script Report JS).

**Spec:** `docs/superpowers/specs/2026-10-16-kenya-withholding-at-payment-design.md` — read it first; this plan does not repeat its reasoning.

## Global Constraints

- Feature gate field: `enable_kenya_withholding`; every server entry point returns early via `is_feature_enabled("enable_kenya_withholding")` (`cecypo_powerpack/utils.py:80`).
- Withheld amount = `ceil(base × rate / 100)` computed with `decimal.Decimal(str(...))`, never float (266,200 × 7.5% must give 19,965, not 19,966).
- `base = round(sum(matching lines' base_net_amount) × share, 2)`; `share = allocated_amount / (rounded_total or grand_total)` of the invoice, both in invoice currency.
- All matching rules stack. Blank item = any item; blank supplier = any supplier.
- Deduction rows written by this feature are **negative** amounts.
- VAT rules = rules whose account is in `withholding_vat_accounts`. Exemption skips VAT rules only, while `posting_date <= valid_until`.
- VAT due = posting date + 5 working days (skip Sat/Sun and the company's `default_holiday_list` holidays). Income tax due = 20th of the month after posting date.
- CSV: no header, CRLF, `PIN,Invoice No,dd/mm/yyyy,amount,dd/mm/yyyy`; rows merged by (PIN, invoice no) within one export.
- Every Link field in the new Settings child tables: `"ignore_user_permissions": 1`.
- Run tests: `cd ~/frappe-bench && bench --site dev.localhost run-tests --app cecypo_powerpack --module <module>`. Check no other run-tests is active first (CLAUDE.md).
- Commits: no `Co-Authored-By` lines (user's global CLAUDE.md overrides the harness attribution).

## Review Focus

1. **User types an allocated amount, then edits it again** — the paid amount must follow, never trigger ERPNext's re-spread (`allocate_party_amount_against_ref_docs`). Test: Task 4 browser step re-edits allocation twice.
2. **Rules changed between draft save and submit** — submit must use the rules in force at submit. Test: Task 3 `test_submit_recomputes_with_current_rules`.
3. **Feature disabled after payments were made** — report, Pay KRA and CSV still work on existing rows; only new calculation stops. Test: Task 5 `test_pay_kra_works_with_feature_disabled`.
4. **Supplier with no `tax_id`** — CSV export refuses and names the supplier. Test: Task 6 `test_export_blocks_missing_pin`.
5. **Payment Entry with a non-PI reference (Journal Entry opening balance) or an unallocated advance** — no withholding on those parts; the PI parts still withhold. Test: Task 3 `test_non_pi_reference_ignored`.

---

### Task 1: Doctypes, settings fields, Payment Entry custom field

**Files:**
- Create: `cecypo_powerpack/cecypo_powerpack/doctype/withholding_rule/{__init__.py,withholding_rule.json,withholding_rule.py}`
- Create: `cecypo_powerpack/cecypo_powerpack/doctype/withholding_vat_account/{...}`
- Create: `cecypo_powerpack/cecypo_powerpack/doctype/withholding_vat_exemption/{...}`
- Create: `cecypo_powerpack/cecypo_powerpack/doctype/payment_entry_withholding/{...}`
- Create: `cecypo_powerpack/kenya_withholding.py` (only `setup_custom_fields` in this task)
- Modify: `cecypo_powerpack/cecypo_powerpack/doctype/powerpack_settings/powerpack_settings.json` (new tab at the end, before `system_tab`)
- Modify: `cecypo_powerpack/hooks.py` (`after_install`, `after_migrate`)
- Test: `cecypo_powerpack/tests/test_kenya_withholding.py`

**Interfaces:**
- Produces child doctypes (all `istable: 1`, module `Cecypo PowerPack`):
  - `Withholding Rule`: `item` (Link Item), `supplier` (Link Supplier), `rate` (Percent, reqd), `account` (Link Account, reqd), all in list view.
  - `Withholding VAT Account`: `account` (Link Account, reqd) — for Table MultiSelect.
  - `Withholding VAT Exemption`: `supplier` (Link Supplier, reqd), `certificate_no` (Data, reqd), `valid_until` (Date, reqd).
  - `Payment Entry Withholding`: `purchase_invoice` (Link Purchase Invoice), `bill_no` (Data), `bill_date` (Date), `base_amount` (Currency), `rate` (Percent), `account` (Link Account), `amount` (Currency), `is_vat` (Check), `due_date` (Date), `kra_journal_entry` (Link Journal Entry). All read-only.
- Settings fields: `withholding_tab` (Tab Break "Withholding"), `kenya_withholding_section`, `enable_kenya_withholding` (Check), `withholding_vat_accounts` (Table MultiSelect → Withholding VAT Account, label "VAT Withholding Accounts"), `withholding_rules` (Table → Withholding Rule), `withholding_exemptions` (Table → Withholding VAT Exemption, label "VAT WHT Exemptions"). Tables `depends_on: enable_kenya_withholding`.
- `kenya_withholding.setup_custom_fields()` — idempotent `create_custom_fields` (pattern: `price_approval.py:123`) adding to Payment Entry: `cecypo_withholding` (Table → Payment Entry Withholding, label "Withholding Details", `insert_after: "deductions"`, `read_only: 1`, `no_copy: 1`, `print_hide: 1`).

- [ ] **Step 1: Write the failing test** `TestScaffold` in `test_kenya_withholding.py`: each of the 4 doctypes exists, `istable`, has exactly the fieldnames above; the 6 settings fieldnames exist; `frappe.get_meta("Payment Entry").get_field("cecypo_withholding").options == "Payment Entry Withholding"`; every Link field in the three settings child tables has `ignore_user_permissions == 1`.
- [ ] **Step 2: Run** `bench --site dev.localhost run-tests --app cecypo_powerpack --module cecypo_powerpack.tests.test_kenya_withholding` → FAIL (doctype missing).
- [ ] **Step 3: Create the doctypes, settings fields, `setup_custom_fields`; add `"cecypo_powerpack.kenya_withholding.setup_custom_fields"` to `after_install` and `after_migrate` in `hooks.py`.**
- [ ] **Step 4: Run** `bench --site dev.localhost migrate` then the test → PASS.
- [ ] **Step 5: Commit** `feat(withholding): doctypes, settings and Payment Entry field`.

### Task 2: Pure calculation

**Files:**
- Modify: `cecypo_powerpack/kenya_withholding.py`
- Test: `cecypo_powerpack/tests/test_kenya_withholding.py` (class `TestCalculation`, plain `unittest.TestCase` — no DB)

**Interfaces:**
- Produces:
  - `withheld(base: float, rate: float) -> int` — Decimal ceil.
  - `invoice_withholding(invoice: dict, allocated: float, supplier: str, rules: list[dict], vat_accounts: set[str], exempt: bool) -> list[dict]` — `invoice` = `{"name", "bill_no", "bill_date", "total", "items": [{"item_code", "base_net_amount"}]}` where `total` is rounded_total-or-grand_total. Rule dicts have `item, supplier, rate, account`. Returns one dict per matching rule: `{"purchase_invoice", "bill_no", "bill_date", "base_amount", "rate", "account", "amount", "is_vat"}`. Zero-amount rows dropped. Rules in settings order.
  - `vat_due_date(posting_date: date, holidays: set[date]) -> date` and `income_tax_due_date(posting_date: date) -> date`.

- [ ] **Step 1: Write failing tests** (values from the spec):
  - `test_withheld_rounds_up_like_itax`: `withheld(126316.58, 2) == 2527`; `withheld(251195.14, 2) == 5024`; `withheld(4310.34, 2) == 87`; `withheld(266200, 7.5) == 19965`; `withheld(6000, 2) == 120`.
  - `test_inv60515_full_payment`: invoice total 315,752, items rent 266,200 + other 6,000, rules `[{"item":None,"supplier":None,"rate":2,"account":"VAT"}, {"item":"RENT","supplier":None,"rate":7.5,"account":"RENT"}]`, allocated 315,752 → rows `{VAT: base 272200, amount 5444, is_vat 1}`, `{RENT: base 266200, amount 19965, is_vat 0}`.
  - `test_partial_payment_scales_base`: same invoice, allocated 157,876 → VAT base 136,100.00, amount 2,722.
  - `test_exempt_skips_vat_only`: `exempt=True` → only the RENT row.
  - `test_supplier_and_item_matching`: rule `{item:"X", supplier:"S1"}` matches X from S1 only; `{supplier:"S1"}` matches all S1 lines; two rules same account both apply (two rows).
  - `test_due_dates`: `vat_due_date(Thu 2026-01-22, set())` == Thu 2026-01-29; with 2026-01-26 a holiday → Fri 2026-01-30; `income_tax_due_date(2026-10-05) == 2026-11-20`; `income_tax_due_date(2026-12-31) == 2027-01-20`.
- [ ] **Step 2: Run** → FAIL (import error).
- [ ] **Step 3: Implement the four functions.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(withholding): calculation`.

### Task 3: Payment Entry hook

**Files:**
- Modify: `cecypo_powerpack/kenya_withholding.py`, `cecypo_powerpack/hooks.py` (`doc_events["Payment Entry"]`)
- Test: `cecypo_powerpack/tests/test_kenya_withholding.py` (class `TestPaymentEntry(FrappeTestCase)`)

**Interfaces:**
- Consumes: Task 2 functions.
- Produces:
  - `apply_to_payment_entry(doc, method=None) -> None` — `before_validate` hook. Runs before ERPNext's `validate()` so its `set_amounts` / `validate_allocated_amount` see our values (avoids recomputing setters). Only when feature on, `docstatus == 0`, `payment_type == "Pay"`, `party_type == "Supplier"`, and settings have at least one rule for an account of `doc.company`. Rebuilds `doc.cecypo_withholding` (adds `due_date`), removes deduction rows whose account is any rule account, appends one negative row per account (`cost_center` = company default cost center, `description` "Withholding {rate}% …"), sets `paid_amount = (Σ allocated × target_exchange_rate − total withholding) / source_exchange_rate` (KES result converted to the paid-from account's currency) and `received_amount = paid_amount × source_exchange_rate / target_exchange_rate`. The tests (`difference_amount == 0`, `unallocated_amount == 0`) are the arbiter. Exemption from settings by `doc.supplier`/`posting_date`. If nothing withholds, clears its own rows only.
  - `@frappe.whitelist() compute_for_payment_entry(doc: str|dict) -> dict` — runs the same hook on an unsaved copy, returns `{"cecypo_withholding", "deductions", "paid_amount", "received_amount"}`. Checks `frappe.has_permission("Payment Entry", "write")`.
  - `prevent_cancel_if_paid_to_kra(doc, method=None)` — `before_cancel`; throws naming the Journal Entry if any `cecypo_withholding` row has `kra_journal_entry`.
- Test fixture (setUpClass): `_Test Company`; create accounts `_Test VAT WHT - _TC`, `_Test Rent WHT - _TC` under `Duties and Taxes - _TC`; item `_Test WHT Rent` (non-stock); settings saved with feature on, VAT account set, rules [blank 2% VAT, Rent 7.5% Rent]. Restore settings in tearDownClass. PIs via `_make_pi` pattern (`tests/test_zero_allocate_paste.py`) extended to two items; PEs via `erpnext...payment_entry.get_payment_entry("Purchase Invoice", pi.name)`.

- [ ] **Step 1: Write failing tests:**
  - `test_full_payment_posts_withholding`: PI rent 266,200 + other 6,000 at 0 tax (base_net = rate); PE from PI, set `paid_from = "_Test Bank - _TC"`, insert, submit → `paid_amount == 272200 - 5444 - 19965`; deductions `{VAT: -5444, Rent: -19965}`; GL credit 5,444 to VAT WHT, 19,965 to Rent WHT; PI `outstanding_amount == 0`.
  - `test_dispute_allocates_less`: allocate 100,000 of 272,200 → rows on base 100,000 shares; PI outstanding 172,200 after submit.
  - `test_debit_note_reduces_base`: debit note (`is_return`, `return_against` the PI, −72,200 on the other-item line) → outstanding 200,000; PE allocates 200,000 → VAT base `round(272200 × 200000/272200, 2)` = 200,000.00, rent base `round(266200 × 200000/272200, 2)`.
  - `test_exemption_valid_then_expired`: exemption `valid_until = posting_date` → no VAT row; `valid_until = posting_date - 1` → VAT row.
  - `test_feature_off_does_nothing`: no rows, deductions untouched, paid amount untouched.
  - `test_submit_recomputes_with_current_rules`: save draft, change VAT rate to 3 in settings, submit → VAT row rate 3.
  - `test_non_pi_reference_ignored`: PE with PI row and an unallocated amount → withholding from PI row only.
  - `test_usd_invoice_kes_bank`: `_Test Supplier USD` PI at conversion 100, PE from `_Test Bank - _TC` → base from PI `base_net_amount`, `difference_amount == 0`, `unallocated_amount == 0`.
  - `test_cancel_blocked_when_paid_to_kra`: set `kra_journal_entry` on a row via `db.set_value` → `pe.cancel()` raises with that JE name.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement; register `"before_validate"` and `"before_cancel"` under `"Payment Entry"` in `doc_events`.** If `test_usd_invoice_kes_bank` leaves a non-zero `difference_amount`, adjust the paid/received computation, not the test.
- [ ] **Step 4: Run** → PASS; also run the whole app suite to confirm no regression.
- [ ] **Step 5: Commit** `feat(withholding): apply on supplier Payment Entries`.

### Task 4: Desk JS — Payment Entry and Settings

**Files:**
- Create: `cecypo_powerpack/public/js/kenya_withholding_payment_entry.js`
- Modify: `cecypo_powerpack/hooks.py` (`doctype_js["Payment Entry"]`)
- Modify: `cecypo_powerpack/cecypo_powerpack/doctype/powerpack_settings/powerpack_settings.js`

**Interfaces:**
- Consumes: `compute_for_payment_entry`.
- PE JS: on `refresh`, `allocated_amount` / `references_remove` (Payment Entry Reference), `party`, `posting_date`, call `compute_for_payment_entry` (debounced 300 ms) when `docstatus == 0` and `payment_type == "Pay"`. Assign results with `frm.doc.x = …` / `frm.clear_table` + `add_child` + `refresh_field` — **never `frm.set_value("paid_amount")`**, which fires ERPNext's re-spread. Then call `frm.events.set_unallocated_amount(frm)` and `frm.events.set_difference_amount(frm)`. When `cecypo_withholding` has rows: `paid_amount` and `received_amount` read-only.
- Settings JS: on `refresh` and on changes in `withholding_rules`, add class `pp-wht-dup` (yellow-tinted row via `--bg-yellow`, per CLAUDE.md dark-mode note) to grid rows whose non-blank `item` or `supplier` appears in another row. Put the SCSS rule in `public/css/cecypo_powerpack.scss`.

- [ ] **Step 1: Build:** `bench build --app cecypo_powerpack` → no errors.
- [ ] **Step 2: Browser check (playwright, `https://dev.cecypo.tech`)** with the Task 3 fixture data on `_Test Company`: open a new PE from a rent PI → withholding rows + negative deductions appear, paid amount = 246,791 read-only; change allocated to 100,000 then to 150,000 → paid amount follows each time, allocations unchanged (Review Focus 1); save + submit succeed.
- [ ] **Step 3: Browser check settings:** add a second row with the rent item → both rows highlighted; delete it → highlight gone; check in dark mode.
- [ ] **Step 4: Commit** `feat(withholding): Payment Entry and settings UI`.

### Task 5: Withholding Due to KRA report and Pay KRA

**Files:**
- Create: `cecypo_powerpack/cecypo_powerpack/report/__init__.py`, `report/withholding_due_to_kra/{__init__.py, withholding_due_to_kra.json, .py, .js}` (Script Report, ref doctype Payment Entry, roles Accounts User, Accounts Manager)
- Modify: `cecypo_powerpack/kenya_withholding.py`, `hooks.py` (`doc_events["Journal Entry"]`)
- Test: `cecypo_powerpack/tests/test_kenya_withholding.py` (class `TestPayKRA`)

**Interfaces:**
- `execute(filters) -> (columns, data)`: filters `company` (reqd), `account`, `status` (Unpaid/Paid/All, default Unpaid), `from_date`, `to_date` (PE posting date). Rows = `Payment Entry Withholding` joined to submitted PE: `row_name` (child name, hidden), supplier, `tax_id`, purchase_invoice, bill_no, bill_date, payment_entry, posting_date, base_amount, rate, amount, account, is_vat, due_date, kra_journal_entry, `overdue` (unpaid and due_date < today).
- JS: `get_datatable_options` → `checkboxColumn: true`; overdue rows styled; buttons "Pay KRA" and "Export iTax CSV" act on checked rows' `row_name`.
- `@frappe.whitelist() pay_kra(row_names: list[str], bank_account: str, posting_date: str, prn: str, reference_date: str) -> str` — `frappe.only_for(["Accounts Manager", "Accounts User", "System Manager"])`; locks rows (`for_update`); throws if any already has `kra_journal_entry`, or rows span companies; builds and submits a Journal Entry `voucher_type="Bank Entry"`, `cheque_no=prn`, `cheque_date=reference_date`, `user_remark` listing PEs: debit each account its selected Σ `amount`, credit bank with the iTax figure (VAT rows merged by (tax_id, bill_no) then `withheld(Σ base, rate)`; income tax rows Σ amount); difference to company `round_off_account` with `round_off_cost_center`. Sets `kra_journal_entry` on rows. Returns JE name. **Works regardless of the feature flag.**
- `clear_kra_link(doc, method=None)` — Journal Entry `on_cancel`: clears `kra_journal_entry` where it equals `doc.name`. Journal Entry `before_cancel`: append `"Payment Entry"` to `doc.ignore_linked_doctypes`.

- [ ] **Step 1: Write failing tests:** `test_report_lists_unpaid_rows` (two PEs → rows, due dates per type); `test_pay_kra_posts_and_links` (JE debit VAT 5,444 + Rent 19,965, credit bank 25,409, `cheque_no` = PRN, rows linked, report Unpaid now empty); `test_pay_kra_refuses_twice`; `test_pay_kra_merges_part_payments` (two PEs paying one PI at bases 50,000.25 and 50,000.25 → withheld 1,001 + 1,001; bank credit `withheld(100000.50, 2)` = 2,001; 1 to round-off; JE balanced); `test_cancel_kra_je_unlinks` (cancel succeeds, rows Unpaid); `test_pay_kra_works_with_feature_disabled`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS, then `bench migrate` and open `/app/query-report/Withholding Due to KRA` in the browser: tick rows, Pay KRA dialog (bank, date, PRN, reference date) creates the JE.
- [ ] **Step 5: Commit** `feat(withholding): due-to-KRA report and Pay KRA`.

### Task 6: iTax Withholding VAT CSV

**Files:**
- Modify: `cecypo_powerpack/kenya_withholding.py`, the report JS
- Test: `cecypo_powerpack/tests/test_kenya_withholding.py` (class `TestItaxCsv`)

**Interfaces:**
- `itax_csv_rows(rows: list[dict]) -> list[list[str]]` (pure): VAT rows only; merge by (`tax_id`, `bill_no`): base summed, payment date = latest; formats dates `dd/mm/yyyy`, amount as `f"{base:.2f}"`; `bill_no` fallback PI name, `bill_date` fallback PI posting date (resolved by caller).
- `@frappe.whitelist() export_itax_csv(row_names: list[str]) -> None` — same role check as `pay_kra`; throws listing suppliers with no `tax_id`; responds with a download: `frappe.response.filename = "WHT-VAT-<dd-mm-yyyy>.csv"`, `type = "download"`, content written with `csv.writer(..., lineterminator="\r\n")`. JS opens it with `window.open` on the `/api/method/...` URL (GET, `row_names` JSON).

- [ ] **Step 1: Write failing tests:** `test_csv_rows_match_itax_upload` — two rows reproducing lines 1–2 of the 22/01/2026 upload → `[["P051163409Z","LPO/26/01/012","19/01/2026","126316.58","22/01/2026"], ...]`; `test_csv_merges_same_invoice`; `test_csv_skips_income_tax_rows`; `test_export_blocks_missing_pin`; `test_export_bytes_crlf_no_header`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS; browser: Export iTax CSV downloads a file whose lines match the format.
- [ ] **Step 5: Commit** `feat(withholding): iTax VAT CSV export`.

### Task 7: Docs and full verification

**Files:**
- Modify: `CLAUDE.md` (Key Files row for `kenya_withholding.py`, Public JS entry, Server-Side Extension Points: Payment Entry `before_validate`/`before_cancel`, Journal Entry `before_cancel`/`on_cancel`, the custom field and deploy needs)

- [ ] **Step 1:** Update `CLAUDE.md`.
- [ ] **Step 2:** Full suite: `bench --site dev.localhost run-tests --app cecypo_powerpack` → all pass.
- [ ] **Step 3:** End-to-end in browser on `Dev Co` with the user's real-looking setup (VAT WHT + 2330-style rent account, rent item): reproduce INV60515 → paid 290,343; Pay KRA with a PRN; Export CSV.
- [ ] **Step 4: Commit** `docs: kenya withholding`.
