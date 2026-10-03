# Finish: Copy as Message in the print preview Powerup

## Summary of changes

- `cecypo_powerpack/copy_as_message.py` — new whitelisted
  `get_copy_message_script(doctype)`: hands the print preview the source of the
  site's enabled Form Client Script that adds the 'Copy as Message' button
  (seeded `PowerPack - Copy as Message (<doctype>)` name preferred, klik_pos's
  pattern reused as `COPY_MESSAGE_BUTTON`); None without read permission.
- `cecypo_powerpack/public/js/copy_as_image.js` — the print preview Powerup ▾ is
  now a two-item menu built once (`make_powerup_item` pairs each dropdown item
  with a narrow-screen page-menu twin): Copy as Image (rules unchanged, plus a
  docstatus-2 hide matching the form and the server's refusal to print cancelled
  documents) and Copy as Message, which fetches the site's script per doctype
  (cached) and runs it against a stub frm via `collect_copy_message` — only
  `frappe.ui.form.on` is intercepted, so the script's own refresh guards decide
  visibility and its action runs exactly as on the form.
- `cecypo_powerpack/tests/test_copy_as_message.py` — 7 new tests for the finder
  (TDD: written red first).
- README.md / CLAUDE.md — docs updated.

## Verification

- `bench run-tests --app cecypo_powerpack --module cecypo_powerpack.tests.test_copy_as_message`
  → OK (17 tests; red first, green after implementation).
- `bench run-tests --app cecypo_powerpack` → OK, 386 tests in 4 batches
  (63 skipped=1 / 10 / 230 / 83), no failures.
- `bench build --app cecypo_powerpack` → clean.
- Browser e2e on dev.localhost:
  - SI print preview: both items; Copy as Message copied the real message
    (customer, date, amount due, status, public link; no payment block on a
    paid invoice) with the 'Message copied' alert.
  - Customer print preview: group hidden.
  - Raw format (SI - ESC/P LX350): image hidden, message shown.
  - Cancelled SI: whole group hidden (message via the script's guard, image via
    the new docstatus check).

## Review pass

- Blocker/Major: none.
- Minor (accepted): async-registering site scripts would not be collected
  (seeded scripts are sync); Safari clipboard timing matches the form button.

## Follow-ups

- None required. Optional: the same collector could later mirror other site
  Powerup scripts if more appear.

## Manual validation on other sites

After deploying: `bench migrate` is NOT needed (no schema/fixture change), only
`bench build --app cecypo_powerpack` (Frappe Cloud does this on deploy). Open a
Sales Invoice print preview and check Powerup ▾ offers both actions.
