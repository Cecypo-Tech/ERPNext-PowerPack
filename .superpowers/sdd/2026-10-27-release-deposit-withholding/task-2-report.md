# Task 2 report: Release Withholding in the report

Built: status option Released (Unpaid now excludes released rows), `released_by` column after KRA Journal Entry, cards skip released rows, overdue 0 for released, "Release Withholding" button (Accounts Manager / System Manager) with dialog (title carries total, Posting Date, Reason), calls `release_withholding`, alert with JE link, refresh. Selected card also ignores released rows.

TDD: new `test_report_status_filter_and_cards_with_released_rows` in TestReleaseWithholding. RED: Unpaid still showed the released rows (failure, 14 tests). GREEN after implementation.

Tests (per class): TestCalculation 12 OK, TestPaymentEntry 34 (1 error: pre-existing test_usd_invoice_kes_bank), TestPayKRA 13 OK, TestItaxCsv 8 OK, TestScaffold 9 OK, TestDepositKRA 3 OK, TestReleaseWithholding 14 OK. `node --check` OK, `bench build` done.

Files: report .py, .js, tests/test_kenya_withholding.py.
Self-review: no blockers. Button shows no pre-filter of ticked rows; server refuses invalid ones. Browser check deferred to Task 3.
