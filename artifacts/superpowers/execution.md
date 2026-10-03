# Execution notes: Copy as Message in print preview Powerup

## Step 1 — server endpoint (TDD)
- Files: `cecypo_powerpack/copy_as_message.py`, `cecypo_powerpack/tests/test_copy_as_message.py`
- Added `get_copy_message_script(doctype)` (whitelisted): enabled Form Client
  Scripts for the doctype, seeded `PowerPack - Copy as Message (<doctype>)` name
  first, first source matching the `add_custom_button('Copy as Message'…)`
  pattern; None without read permission on the doctype.
- Tests written first (7 new, red: AttributeError), then implementation.
- Verify: `bench run-tests --app cecypo_powerpack --module cecypo_powerpack.tests.test_copy_as_message`
- Result: PASS — 17 tests OK (10 pre-existing + 7 new).

## Step 2 — client (print preview Powerup, two items)
- Files: `cecypo_powerpack/public/js/copy_as_image.js`
- Powerup group built once with two items (each with a narrow-screen page-menu
  twin via `make_powerup_item`); items toggle independently; group shows if
  either does. Copy as Image rules unchanged; raw-printing now hides only the
  image item.
- `setup_copy_message`: fetches the script per doctype (cached `frappe.xcall`
  promise), runs it via `collect_copy_message` — `new Function('frappe',
  'cur_frm', src)` with an `Object.create(frappe)` shim overriding only
  `ui.form.on`, stub frm collecting the 'Copy as Message' action; stale fetches
  guarded by doc identity.
- Verify: `bench build --app cecypo_powerpack`
- Result: PASS — bundle built (cecypo_powerpack.bundle.*.js).

## Step 3 — browser e2e (dev.localhost)
- SI print preview: Powerup ▾ shows Copy as Image + Copy as Message; message
  click copied "Walk In, Invoice POS-01698 … View it here: https://dev.cecypo.tech/s/…"
  with 'Message copied' alert (clipboard intercepted to assert the text; paid
  invoice → no payment block, matching the script's logic).
- Customer print preview: whole group hidden.
- SI with raw format (SI - ESC/P LX350): image hidden, message still shown.
- Cancelled SI (POS-01590): script guard hides message; found Copy as Image
  still visible though the form hides it and the server refuses to print
  cancelled docs — fixed inline (docstatus !== 2 in update_print_view_powerup),
  rebuilt, re-verified: cancelled hides the whole group, submitted shows both.
- Result: PASS.
