# Plan: bulk selection — backfill fetch_from fields (Stock Recon item_name)

Approved in chat 2026-10-04. Root cause: bulk selection inserts rows via
`add_child` + ERPNext's `item_code` trigger, but `fetch_from` fields
(`item_name`/`stock_uom`/`item_group` on Stock Reconciliation Item, `image` etc.
on the others, plus any site custom field fetching from `item_code.*`) are
applied only by the Link control on manual entry, or by the server on save —
never by a programmatic insert. Grid shows blanks until save.

## Steps

1. **Implement** (`cecypo_powerpack/public/js/bulk_selection.js`,
   `add_items_to_doc` only):
   - Build the fetch map from the child doctype's client meta: fields whose
     `fetch_from` starts with `item_code.` (includes custom fields).
   - One batched `frappe.db.get_list('Item', …)` for the items being added
     (skip when the map or list is empty); chain starts after it resolves.
   - In `add_row`, after the trigger (and qty) settle: fill only the fetch
     targets the trigger left empty, from the batched values. Never overwrite
     a value the trigger set.
   Verify: `bench build --app cecypo_powerpack` clean.

2. **E2E (browser, dev.localhost)**:
   - New Stock Reconciliation: bulk-add 2+ items → grid rows carry item_name,
     stock_uom, item_group before save; qty = entered qty.
   - Sales Invoice: bulk-add an item → rate/uom/item_name as before, image
     backfilled, nothing clobbered.

3. **Review + land**: severity review; commit on
   `fix/bulk-selection-fetch-fields`, merge --no-ff to main, push upstream/main.

## Verification summary
- `bench build --app cecypo_powerpack`
- Browser e2e as step 2 (this file has no Node test harness; e2e is the check).
