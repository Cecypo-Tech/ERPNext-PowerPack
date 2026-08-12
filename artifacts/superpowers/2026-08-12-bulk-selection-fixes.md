# Bulk Selection — UOM, PO stock dulling, missing button

Date: 2026-08-12
Branch: feat/pay-by-link-mpesa
File: `cecypo_powerpack/public/js/bulk_selection.js`

## Goal

Fix three reported faults in the Bulk Selection dialog across all six supported
doctypes (Quotation, Sales Order, Purchase Order, Sales Invoice, Stock
Reconciliation, Stock Entry).

## Faults, with evidence

### F1 — Wrong UOM + "UOM conversion factor is required in every row"

Reported on Sales Order; the same code path serves all six doctypes.

The dialog already delegates to ERPNext's standard `item_code` trigger
(`bulk_selection.js:2172-2179`), so field population is *not* hand-rolled. The
defect is sequencing:

- ERPNext's `item_code` handler (`erpnext/public/js/controllers/transaction.js:777-801`)
  starts an async server round-trip and returns nothing — no promise.
- So `frappe.model.set_value(..., 'item_code', ...)` resolves immediately, and we
  set `qty` while item details are still in flight.
- At that instant the row is `uom = null`, `conversion_factor = 0` — blanked
  deliberately at `transaction.js:810-811`.
- Our `qty` set fires ERPNext's `qty` handler (`transaction.js:1779-1789`), which
  runs `conversion_factor()` and `apply_price_list()` against that blank state.

Corroboration:
- The Stock Entry branch has `setTimeout(…, 500)` (line 2125) and Stock
  Reconciliation `setTimeout(…, 300)` (line 2086) — prior sleep-based patches for
  the same race. The sales branch has no wait, which is where the bug was seen.
- `use_legacy_js_reactivity` is unset on this site, so `item_code` posts the whole
  document to the server (`transaction_base.py:353`) then calls
  `frm.refresh_fields()`, which lands on top of the qty we just set.

### F2 — Purchase Order dulls / hides zero-stock items

`bulk_selection.js:856` marks a row `unavailable-row` (opacity 0.5, line 1143) when
`warehouse && item.is_stock_item && actual_qty <= 0`. On a Purchase Order, zero
stock is the reason to buy.

Same class of problem at `bulk_selection.js:2004-2005`: "Available only" defaults to
**checked** whenever a warehouse is set, so on a PO zero-stock items are hidden
outright, not merely dulled.

### F3 — No Bulk Selection button on Stock Entry / Stock Reconciliation

`onload` kicks off `frappe.db.get_single_value(...)` and assigns
`frm._bulk_selection_enabled` in a `.then()`. The first `refresh` runs before that
resolves and returns early at line 140, so the button is never added.

Sales doctypes recover by accident: picking a customer causes ERPNext to refresh the
form again, and by then the flag is set. Stock Entry / Stock Reconciliation have no
such follow-up refresh, so the button never appears.

Verified in the browser on `dev.localhost`:

| Doctype | `_bulk_selection_enabled` | anchor present | button present |
|---|---|---|---|
| Stock Entry (new) | 1 | 1, not hidden | **0** |
| Stock Reconciliation (new) | 1 | 1 | **0** |

Forcing a second `cur_frm.refresh()` on Stock Reconciliation raised the button count
to 1 — confirming timing, not logic.

## Plan

1. **F3 first** (it gates manual testing of everything else). Replace the
   fire-and-forget flag with the documented house helper
   `CecypoPowerPack.Settings.isEnabled(field, cb)` (cached, cleared `after_save`;
   `get_settings_for_client` returns the full singleton so all
   `enable_*_bulk_selection` fields are present). Introduce one
   `ensure_bulk_button(frm)` used by `refresh` and by every party/warehouse handler,
   so the button is created *and* toggled from a single place.

2. **F1.** Replace all three branches of `add_items_to_form` with one path:
   seed the child row via `frm.add_child('items', {item_code, qty, ...warehouses})`,
   fire `frm.script_manager.trigger('item_code', …)`, then `await frappe.after_ajax()`
   (`frappe/public/js/frappe/request.js:516`). Seeding qty before the trigger means
   `get_item_details` reads the final qty (`transaction.js:851`) and returns a
   matching rate and conversion factor; no second mutation races the response.
   Delete both `setTimeout` sleeps. Keep zero manual field copying.

3. **F2.** Skip the stock term in `is_unavailable` for purchase doctypes, and do not
   default-check "Available only" for them (leave the checkbox available to opt in).

4. Leave the existing-row update path (`set_value('qty')`) alone — those rows already
   carry a valid UOM and conversion factor.

## Verification

- `bench build --app cecypo_powerpack`; `node --check` on the edited file.
- Browser, per doctype: button appears on a fresh form without a manual refresh.
- Sales Order: add items via the dialog, then compare each row's `uom`,
  `conversion_factor`, `stock_qty`, `rate`, `item_tax_template` against a row added
  manually through the grid for the same item. They must match.
- Repeat for Quotation, Sales Invoice, Purchase Order, Stock Entry.
- Stock Reconciliation has no `uom`/`conversion_factor` fields — verify separately
  that `warehouse`, `qty` and `valuation_rate` still populate.
- Purchase Order: zero-stock items neither dulled nor hidden by default.

## Results

Implemented and verified on `dev.localhost`. Two things surfaced during testing that
were not in the original plan:

- **Grid render timing.** Moving to the cached `Settings.isEnabled` made the callback
  fire *synchronously* on a cache hit, which put `add_bulk_selection_button` ahead of
  the grid toolbar it anchors to — briefly breaking every doctype, including the ones
  that used to work by accident. `add_bulk_selection_button` now returns a boolean and
  `ensure_bulk_button` retries (bounded, 20 × 100ms) until the toolbar exists.
- **Blank row on Stock Entry.** "Remove empty rows" ran before the adds, but the grid
  puts a fresh blank row back while items are being added, so one always survived.
  Moved the sweep to after the chain resolves.

Button present on a fresh form, no manual refresh, correct disabled state:

| Doctype | Button | Tooltip when disabled |
|---|---|---|
| Stock Entry | 1 | Please select a Source or Target Warehouse first |
| Stock Reconciliation | 1 | Please select a Warehouse first |
| Sales Order | 1 | Please select Customer and Warehouse first |
| Purchase Order | 1 | Please select a Supplier first |
| Quotation | 1 | Please select a Customer first |
| Sales Invoice | 1 | Please select Customer and Warehouse first |

Bulk-added row vs the same item added manually through the grid (Sales Order, F051 ×3)
— identical on every field:

```
BULK   {qty:3, uom:"CAN", cf:1, stock_qty:3, rate:0, itt:"Kenya Tax - DC", wh:"Stores - DC"}
MANUAL {qty:3, uom:"CAN", cf:1, stock_qty:3, rate:0, itt:"Kenya Tax - DC", wh:"Stores - DC"}
```

`conversion_factor` is 1 rather than 0, and the Sales Order saved cleanly
(SAL-ORD-2026-00015, since deleted) with no "UOM conversion factor is required in
every row". `rate: 0` appears on both rows, so it is a price-list gap in the test
data, not a regression.

Per-doctype adds, all correct:

- Purchase Order: `uom CAN, cf 1, stock_qty 5, warehouse set`
- Quotation / Sales Invoice: `uom CAN, cf 1, stock_qty 2`
- Stock Entry: `uom CAN, cf 1, transfer_qty 4, s_warehouse set, basic_rate 50`, no blank row
- Stock Reconciliation: entered qty 7 preserved, `current_qty 143`, `valuation_rate 50`,
  `amount 350` — seeding warehouse alongside item_code also fixed the first
  `set_valuation_rate_and_qty` call being a no-op

Purchase Order dialog: "Available only" now off by default, 0 of 20 rows dulled.
Sales Order unchanged: filter on by default, 18 of 20 dulled.

Note: browser asset caching masked the first round of results. Assets are served
unfingerprinted, so a hard reload is needed after `bench build`.

## Risks

- Stock Reconciliation and Stock Entry take different child fields (`warehouse`,
  `s_warehouse`/`t_warehouse`); the unified path must keep seeding those.
- Removing the sleeps depends entirely on `frappe.after_ajax()` covering the
  server round-trip. Verify on Stock Entry specifically, since it had the longest
  sleep (500ms).
