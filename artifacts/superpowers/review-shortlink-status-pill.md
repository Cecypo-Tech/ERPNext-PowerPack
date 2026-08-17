# Review: document status pill on the public short-link page

Date: 2026-08-17
Branch: `feat/status-pill` (commit `b5e3950`)

## Goal

An expired quotation rendered with no Pay button and no explanation, so the
page read as broken. Show the document's own status beside the existing
amount-due pill so the absence explains itself.

Decision taken (user): show the status pill **always**, not only when nothing
is payable.

## Design

- `pay_by_link.document_status(doctype, docname) -> {"label", "tone"} | None`.
  Tone is `paid`, `closed` or `open`, and drives the pill colour.
- `www/s.py` sets `context.doc_status`.
- `www/s.html` renders one span reusing the existing `.pp-due` pill, plus two
  quiet tone variants. Tone `paid` deliberately falls through to the existing
  `.pp-due.is-paid` blue rather than defining a third colour.
- `PAYABLE_DOCTYPES` extracted from the tuple that was inline in `get_payable`,
  now shared by both functions.

## Findings by severity

### Blocker
None.

### Major

**1. A settled invoice read "Paid" twice — FIXED before commit**
`mpesa_receipt` already renders a "Paid" pill, and `document_status` returns
`Paid` for the same invoice, so `HOLD-2026-00001` rendered `Paid Paid`. The
status pill now stands down when it would only repeat the money pill. A settled
Sales Order still shows `Paid` + `Completed`, which are different facts.

Caught by rendering the real short links rather than by the unit tests — the
duplication only exists once both context values meet in the template.

### Minor

**2. `docstatus` has to outrank the `status` field**
A cancelled document keeps whatever status it held when it was cancelled, so
`docstatus == 2` forces `Cancelled` and `docstatus == 0` forces `Draft`.
Without this a cancelled invoice would have read `Overdue`.

**3. A paid quotation would have read "Open"**
`receipt_for()` only follows Sales Invoice and Sales Order, so a quotation
settled by a Completed Express Request has no receipt to show. The status pill
consults `_settled_by_a_previous_request()` for quotations only, and reads
`Paid`. The lookup is skipped for drafts — nothing can have been paid against a
document that was never submitted.

**4. Unknown statuses fall through to `open`, not to nothing**
An ERPNext upgrade that adds a status must not blank the pill. Pinned by a test.

**5. No regression test for the de-duplication rule**
It is a two-line condition inside `get_context`, which would need the short
link, company, PowerPack Settings and gateway lookups all stubbed to reach.
Covered instead by rendering all five live short links (below). Worth extracting
if `get_context` ever grows more of this kind of logic.

### Nit

**6. Repo test suites need a site**
`cecypo_powerpack/tests/*` patch `frappe.db.*`, which is a thread-local proxy,
so plain `pytest` fails on every test — the pre-existing suites included. Run
them with `bench --site <site> run-tests --module ...`.

## Verification

**Unit — 19 tests, all passing** (`bench --site dev.localhost run-tests --module
cecypo_powerpack.tests.test_pay_by_link_status`): expired / lost / ordered /
open quotation, draft and cancelled overriding the status field, quotation
settled by Express Request, the settled lookup skipped for drafts and not
applied to Sales Orders, overdue / partly paid / paid invoice, completed and
closed order, credit note issued, unknown status, unsupported doctype, missing
document, blank status.

**Rendered — every live short link on `dev.localhost`:**

| Document | Status | Pills rendered | Pay button |
| --- | --- | --- | --- |
| `SAL-QTN-2026-00002` (minted) | Expired | `Expired` | no |
| `HOLD-2026-00001` | Paid | `Paid` | no |
| `SAL-ORD-2026-00018` | Completed | `Paid` · `Completed` | no |
| `POS-00029` | Overdue | `Sh 300.00 due` · `Overdue` | yes |
| `POS-00028` | Credit Note Issued | `Paid` · `Credit Note Issued` | no |
| `X-POS-00008` | Return | `Paid` · `Return` | no |

The short link minted for the quotation was deleted afterwards; the site is back
to its original 5 links.

## Note on the original question

Nothing was broken. `pay_by_link.py` has supported Quotation since it was
written; both quotations on this site are `Expired` (`valid_till 2026-07-13`),
which is in `DEAD_STATUSES`, so `get_payable()` correctly returned `None`. The
pill makes that visible instead of leaving the payer to guess.
