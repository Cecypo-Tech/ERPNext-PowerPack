# Review: Copy as Message for Quotation / Sales Order / Sales Invoice

Branch: feat/copy-as-message

## What
- `cecypo_powerpack/client_scripts/copy_as_message_{quotation,sales_order,sales_invoice}.js`:
  Powerup > Copy as Message; copies customer, doc no., dates, amounts, status and the
  PowerPack short link. Empty `PAYMENT_DETAILS` block (per Company, `'*'` fallback) that
  the site fills in; appended when unpaid (SI: outstanding > 0; SO: advance < total and
  per_billed < 100; QT: always). Wrapped in an IIFE: frappe concatenates every enabled
  form script of a doctype into one `new Function`, so top-level `const`s would collide.
- `copy_as_message.py`: `seed_client_scripts()` creates the three Client Scripts named
  `PowerPack - Copy as Message (<DocType>)` only when missing; no module, so the
  Client Script fixture filter never exports them. Disables legacy
  `SI - Copy to Clipboard` only at the moment its replacement is created.
- hooks: `after_install` and `after_migrate` call it.

## Why not a fixture
`sync_fixtures()` runs on every migrate (frappe/migrate.py:171) and imports with
`force=True` (data_import.py:362): a site's edits and its Enabled=0 would be overwritten.

## Design change after approval
Approved design said "one-time patch + after_install" and "delete + migrate gets the
latest version" - contradictory, since a patch runs once. Switched to after_migrate
(creates only if missing), which makes the stated reset path true; patch dropped.
Legacy disabling limited to the moment of replacement so a re-enabled legacy script
is not switched off on every migrate.

## Verification
- `bench --site dev.localhost run-tests --module cecypo_powerpack.tests.test_copy_as_message`: 8 OK.
  Mutation: seeding that replaces existing scripts -> test fails. hooks change stashed -> test fails.
- Full app: `bench --site dev.localhost run-tests --app cecypo_powerpack`: 311 tests OK.
- `bench migrate` on dev: scripts created; second migrate left all three byte-identical
  (md5 + modified), including the SI script holding Cecypo's bank details.
- Playwright (clipboard stubbed): QT SAL-QTN-2026-00002, SO SAL-ORD-2026-00031 (fully
  advanced -> no bank block), SI POS-00239 (outstanding -> '*' bank block),
  SI POS-01231 (outstanding 0 -> no bank block). One Copy as Message per form.
- dev.localhost site data: Cecypo's two bank blocks moved from `SI - Copy to Clipboard`
  into the new SI script (extracted programmatically, every line asserted), legacy deleted.

## Findings
- Major (pre-existing, not changed): `api.get_document_public_link` has no permission
  check - `frappe.get_doc` does not check read access, so any desk user can mint a
  guest-viewable share link for any document of any doctype by name. These buttons
  only call it for the open document, but the endpoint is callable directly.
  Suggested fix: `doc.check_permission("read")` after `get_doc`.
- Minor (pre-existing): links come out as `https://dev.cecypo.tech:443/s/...` - the
  explicit :443 comes from the short-link URL builder, not from this change.
- Minor: shipped script improvements do not reach sites that already have a script;
  documented reset path is delete + migrate.
- Nit: amount format changed from `12,345/-` to `format_currency` (e.g. `Sh 12,345.00`)
  and dates to the user's date format.
