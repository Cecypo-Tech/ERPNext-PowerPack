# Execution — Kenya withholding (subagent-driven)

Branch feat/kenya-withholding from 88e34f2. Ledger: .superpowers/sdd/plan/progress.md

## Task 1 — scaffold (e3d53c2)
- 4 child doctypes, Withholding tab in PowerPack Settings, PE custom field cecypo_withholding via setup_custom_fields (after_install/after_migrate)
- Verify: bench --site dev.localhost run-tests --app cecypo_powerpack --module cecypo_powerpack.tests.test_kenya_withholding → pass; full suite pass
- Review: approved

## Task 2 — calculation (5d8646a)
- withheld (Decimal ceil), invoice_withholding, vat_due_date, income_tax_due_date
- Verify: test_kenya_withholding TestCalculation → pass; full suite 90 OK
- Review: approved

## Task 3 — Payment Entry hook (da35919, 42cf8df)
- before_validate apply_to_payment_entry, compute_for_payment_entry, before_cancel guard; paid amount counts other deductions
- Fixed Task 1 regression in test_min_selling_price EXPECTED_TABS
- Verify: test_kenya_withholding 23 OK, test_min_selling_price 46 OK
- Review: 1 Important fixed in round 1; re-review clean

## Task 4 — desk JS (af62b6d, f773bb3)
- PE live preview (doctype_js), recompute after Get Outstanding Invoices, payment_type/party_type triggers; settings duplicate-rule highlight
- Verify: bench build OK, node --check OK, test_kenya_withholding OK; browser checks deferred (login pending)
- Review: 2 Important fixed in round 1

## Task 5 — Due to KRA report + Pay KRA (3a4571d, c0a97df)
- Script report, pay_kra (FOR UPDATE guard, Bank Entry JE, iTax figure via merge_vat_rows, round-off diff), JE cancel unlink + desk Cancel-All fix, mixed-rate refusal
- Verify: test_kenya_withholding 35 OK, test_min_selling_price 46 OK
- Review: 1 Important + 2 hardening fixed round 1

## Task 6 — iTax CSV (417df5b)
- itax_csv_rows (reuses merge_vat_rows), export_itax_csv download, report button; shared _load_rows
- Verify: test_kenya_withholding 32+ OK
- Review: approved

## Task 7 — docs (bfab43c)
- CLAUDE.md Kenya Withholding section; full suite green except 6 pre-existing test_zero_allocate_paste errors (fixture company)

## Final whole-branch review + fix wave (d31ce07, 64d4c31, 8bf9fa3, 78178f2)
- 4 Important + 11 minor fixed: stale rows cleared when gate stops; KRA JE amend refused (cecypo_kra_payment marker); ceil once per invoice; read-only/feature-off preview gating; CSV refuses no-VAT / blank PIN; POST-only endpoints; PI read check; VAT vs income tax not mixed in one Pay KRA; account set_query; open_url_post; bank-figure preview; index; docs
- Verify: test_kenya_withholding 55/55, test_min_selling_price 46/46, full suite only the 6 known failures
- Re-review: 15/15 addressed; 3 minors parked with rulings
- Browser end-to-end: NOT RUN (login pending)
