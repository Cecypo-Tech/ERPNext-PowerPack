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

---

# Execution notes: bulk selection fetch_from backfill (2026-10-04)

## Step 1 — implement
- Files: `cecypo_powerpack/public/js/bulk_selection.js` (`add_items_to_doc`)
- Fetch map built from the child doctype's client meta (`fetch_from` starting
  `item_code.`, custom fields included); one batched `frappe.db.get_list('Item')`
  for new items, placed at the head of the sequential chain.
- `backfill_fetch_fields` runs after each row's trigger (and SR's qty) settles,
  setting only empty targets — trigger output never overwritten.
- Verify: `bench build --app cecypo_powerpack`
- Result: PASS — build clean.

## Step 2 — browser e2e (dev.localhost)
- New Stock Reconciliation, warehouse Stores - DC, bulk-added F050/F051/F052 at
  qty 7/8/9: every row has item_name, item_group (Mixer), stock_uom, qty as
  entered, valuation_rate from ERPNext's trigger. Before save.
- New Sales Invoice (Walk In), bulk-added F050 x2: item_name, uom CAN,
  conversion_factor 1, item_tax_template, income_account, warehouse from the
  trigger as before; image backfilled. rate 0 is correct (F050 has no price in
  the doc's "Standard Selling" list).
- First attempt was intercepted by the "Version Updated" modal the build
  raised; reloaded and reran.
- Result: PASS.

## Step 3 — review fix + re-verify
- Review found (Major): client `frappe.db.get_list` resolves only on success;
  a server error (e.g. no Item read) left the promise pending, and since it
  heads the add chain, no rows would be added. Switched to `frappe.xcall`
  (rejects on error) + `.catch(() => {})`; limit bounded to the item count.
- Re-verified: SR bulk add F053 → item_name/item_group filled, qty 5; with the
  lookup forced to reject, F049 still added at qty 4 (backfill skipped).
- Result: PASS.

## PO buying prices (2026-10-04)
- Step 1 tests: `tests/test_bulk_selection_purchase.py` (3 tests) -> red as expected (purchase-only item dropped; no buying arg).
- Step 2 fix: `api.py` - `buying = doctype == 'Purchase Order'` threaded into tax-template, optimized, standard and `_get_item_price` lookups. Module green; full app suite 389 OK (skipped=1).
- Step 3 e2e: new PO, Supplier A -> buying_price_list Standard Buying KES; dialog row "F049 ... KES 400.00" (was "—"). Endpoint tax_rate 0 matches the purchase template (VAT not included in rate).
