# Finish — Kenya withholding at payment

Branch `feat/kenya-withholding` (from 88e34f2), 14 commits, NOT merged or pushed — browser verification outstanding.

## Verification run
- `bench --site dev.localhost run-tests --app cecypo_powerpack --module cecypo_powerpack.tests.test_kenya_withholding` → 55/55 OK
- `... --module cecypo_powerpack.tests.test_min_selling_price` → 46/46 OK
- `bench --site dev.localhost run-tests --app cecypo_powerpack` → all pass except 6 pre-existing errors in test_zero_allocate_paste ("Please set default Stock Received But Not Billed in Company Test Quality Company" — fixture, not this branch)
- `bench --site dev.localhost migrate`, `bench build --app cecypo_powerpack` → OK
- Browser end-to-end → NOT RUN (no dev.cecypo.tech login available to playwright)

## What changed
- PowerPack Settings → Withholding tab: enable flag, VAT Withholding Accounts, Withholding Rules (Item | Supplier | Rate | Account, stacking, duplicates highlighted), VAT WHT Exemptions (Supplier | Certificate | Valid Until)
- Payment Entry (supplier, Pay): per-invoice withholding computed from the amount being settled, Decimal ceil per invoice and rule, negative deduction rows, paid amount derived and read-only, Withholding Details table; live preview incl. Get Outstanding Invoices; USD invoices in KES at invoice rate; cancel refused once paid to KRA
- Report "Withholding Due to KRA": due dates (VAT +5 working days, income tax 20th next month), overdue flag, Pay KRA (one Bank Entry JE, PRN as cheque no, iTax bank figure, round-off diff, race-safe never-twice), Export iTax CSV (no header, CRLF, merged per invoice)
- Journal Entry: KRA JE cancel returns rows to Unpaid (desk Cancel-All handled); amending a KRA JE refused

## Review
Per-task reviews + final whole-branch review: 0 Critical; all Important fixed; parked minors with rulings in the ledger.

## Follow-ups
- Browser pass (checklist below), then land to upstream/main.
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
