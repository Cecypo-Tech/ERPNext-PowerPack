# Finish — Kenya withholding at payment

Branch `feat/kenya-withholding` (from 88e34f2) merged to main as a67fc06+ and pushed to upstream/main after the browser pass.

## Verification run
- `bench --site dev.localhost run-tests --app cecypo_powerpack --module cecypo_powerpack.tests.test_kenya_withholding` → 55/55 OK
- `... --module cecypo_powerpack.tests.test_min_selling_price` → 46/46 OK
- `bench --site dev.localhost run-tests --app cecypo_powerpack` → all pass except 6 pre-existing errors in test_zero_allocate_paste ("Please set default Stock Received But Not Billed in Company Test Quality Company" — fixture, not this branch)
- `bench --site dev.localhost migrate`, `bench build --app cecypo_powerpack` → OK
- Browser end-to-end (temporary users, since deleted) → 8/9 first pass; defects D1 Settings form blank, D2 PE never clean (no Submit), D3 preview ignored user deductions, D4 CSV refusal opened error tab — all fixed (1b24c43..7f4b958), re-verified in browser, re-reviewed clean. INV60515 on Dev Co: paid 290,343, deductions −5,444/−19,965, submitted from the UI (PAY-26-00747); CSV row `P051140936Z,INV60515,16/10/2026,272200.00,16/10/2026`.
- E2E data left on dev for inspection: Dev Co WHT accounts, RENT-E2E item, supplier WHT E2E Landlord, PI INV60515 + payments; Dev Co withholding settings enabled (list in the session's e2e report).

## What changed
- PowerPack Settings → Withholding tab: enable flag, VAT Withholding Accounts, Withholding Rules (Item | Supplier | Rate | Account, stacking, duplicates highlighted), VAT WHT Exemptions (Supplier | Certificate | Valid Until)
- Payment Entry (supplier, Pay): per-invoice withholding computed from the amount being settled, Decimal ceil per invoice and rule, negative deduction rows, paid amount derived and read-only, Withholding Details table; live preview incl. Get Outstanding Invoices; USD invoices in KES at invoice rate; cancel refused once paid to KRA
- Report "Withholding Due to KRA": due dates (VAT +5 working days, income tax 20th next month), overdue flag, Pay KRA (one Bank Entry JE, PRN as cheque no, iTax bank figure, round-off diff, race-safe never-twice), Export iTax CSV (no header, CRLF, merged per invoice)
- Journal Entry: KRA JE cancel returns rows to Unpaid (desk Cancel-All handled); amending a KRA JE refused

## Review
Per-task reviews + final whole-branch review: 0 Critical; all Important fixed; parked minors with rulings in the ledger.

## Follow-ups
- Deferred minors: scaffold tests don't assert field attributes; shared debounce across PE forms; preview doesn't mark draft dirty; Status=All drops ticked paid rows silently; FOR UPDATE join may deadlock (fails safe); report lists rows across companies without company user-permission check.

## Manual validation (browser checklist)
1. Settings: duplicate highlight add/edit/delete, light+dark; VAT accounts picker excludes group/Payable.
2. INV60515 with 16% VAT on Dev Co: paid 290,343 read-only, deductions −5,444/−19,965, Difference 0; re-edit allocations twice.
3. Get Outstanding Invoices with/without Allocate Payment Amount.
4. Add bank-charge deduction; switch payment type on draft; open draft as read-only user.
5. Feature off: no compute errors.
6. Real 2330-style rent account type (must not be Payable).
7. Pay KRA from report → JE lines; cancel KRA JE from desk → rows Unpaid; amend refused; PE cancel refused while paid.
8. CSV export ticked/none ticked through Cloudflare; bytes + CRLF.
9. USD supplier; USD bank.

## Follow-up 2026-10-16: Get Outstanding Invoices before a paid amount (3302358)

- Cause (PAY-26-00799): ERPNext showed References only after a paid amount; typing 1 then fetching allocated 1 shilling, giving -1/-1 withholding and paid -1.
- Fix: Property Setter on Payment Entry `section_break_14` depends_on (all Payment Entries); with withholding on, a typed paid amount is zeroed before Get Outstanding Invoices; save refuses paid <= 0 under withholding (not in preview).
- Verified: withholding tests 58/58; browser on Dev Co: button shows with paid empty; typed 1 then fetch gave full allocations; allocated 1 shows the refusal; full allocation saved clean at 290,343 (-5,444 / -19,965), Submit shown. Test draft and temp user deleted.
- Review: no Blocker/Major; minors 1-4 and the test nit fixed. Left: section also shows for manual-reference entries with paid 0 (save then asks for paid); a user's own positive deduction present at fetch time shortens the last allocation (ERPNext behaviour); migrate re-applies the depends_on.

## Follow-up 2026-10-16: Withheld total beside Paid Amount (921b66b)

- `cecypo_total_withheld` custom field (Currency, read-only, after column_break_21, hidden at 0), set by apply_to_payment_entry and the form preview; backfilled from withholding rows in setup_custom_fields.
- Verified: withholding tests 58/58; browser: PAY-26-00801 shows Withheld 25,409 beside Paid 290,343 after backfill; on a new draft paid + withheld = allocated before and after removing an invoice row. Temp user deleted.
- Review: no Blocker/Major. Minor: the backfill query runs on every migrate (touches only mismatched rows).
